"""Testes essenciais das regras críticas (conflitos, permissões, concorrência)."""
import json
from datetime import date, time

from django.test import TestCase

from .models import Componente, Conflito, DataBloqueada, Encontro, HorarioSemanal, Semestre, Usuario
from .services import gerar_encontros, problemas_para_aprovacao, sincronizar_conflitos


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = Usuario.objects.create_user
        cls.admin = Usuario.objects.create_superuser("admin@t.example", "senha-Teste-123", nome="Admin")
        cls.coord = U("coord@t.example", "senha-Teste-123", nome="Coord", perfil="COORD")
        cls.coord2 = U("coord2@t.example", "senha-Teste-123", nome="Coord 2", perfil="COORD")
        cls.p1 = U("p1@t.example", "senha-Teste-123", nome="Prof 1", perfil="PROF")
        cls.p2 = U("p2@t.example", "senha-Teste-123", nome="Prof 2", perfil="PROF")
        cls.sem = Semestre.objects.create(
            nome="T.1", data_inicio=date(2027, 2, 1), data_fim=date(2027, 6, 30), preenchimento_liberado=True
        )
        DataBloqueada.objects.create(semestre=cls.sem, data=date(2027, 2, 8), descricao="Carnaval")
        cls.a = cls._comp("A", cls.coord, [cls.p1], 0, time(14), time(16))
        cls.b = cls._comp("B", cls.coord2, [cls.p1, cls.p2], 0, time(15), time(17))
        cls.c = cls._comp("C", cls.coord2, [cls.p2], 0, time(16), time(18))

    @classmethod
    def _comp(cls, nome, coord, profs, dia, ini, fim):
        c = Componente.objects.create(
            nome=nome, turma="A", semestre=cls.sem, coordenador=coord,
            data_inicio=date(2027, 2, 1), data_fim=date(2027, 2, 22),
        )
        c.professores.set(profs)
        HorarioSemanal.objects.create(componente=c, dia_semana=dia, hora_inicio=ini, hora_fim=fim)
        gerar_encontros(c)
        return c

    def alocar(self, comp, prof, dia=date(2027, 2, 15)):
        e = comp.encontros.get(data=dia)
        e.professor = prof
        e.conteudo = "Aula"
        e.save()
        sincronizar_conflitos({prof.id})
        return e

    def post(self, usuario, encontro, corpo):
        self.client.force_login(usuario)
        return self.client.post(f"/api/encontros/{encontro.id}/", json.dumps(corpo), content_type="application/json")


class GeracaoTests(Base):
    def test_gera_encontros_e_pula_data_bloqueada(self):
        datas = list(self.a.encontros.values_list("data", flat=True))
        self.assertEqual(datas, [date(2027, 2, 1), date(2027, 2, 15), date(2027, 2, 22)])

    def test_regerar_preserva_encontro_preenchido(self):
        e = self.alocar(self.a, self.p1)
        self.a.horarios.update(dia_semana=2)
        gerar_encontros(self.a)
        e.refresh_from_db()
        self.assertTrue(e.excepcional)


class ConflitoTests(Base):
    def test_sobreposicao_gera_conflito_entre_coordenadores_diferentes(self):
        self.alocar(self.a, self.p1)
        self.alocar(self.b, self.p1)
        c = Conflito.objects.get()
        self.assertEqual((c.status, c.sobreposicao_inicio, c.sobreposicao_fim), ("ATIVO", time(15), time(16)))

    def test_aulas_consecutivas_nao_conflitam(self):
        self.alocar(self.a, self.p1)   # 14–16
        self.alocar(self.c, self.p1)   # 16–18
        self.assertFalse(Conflito.objects.exists())

    def test_docentes_diferentes_nao_conflitam(self):
        self.alocar(self.a, self.p1)
        self.alocar(self.b, self.p2)
        self.assertFalse(Conflito.objects.exists())

    def test_salvar_com_conflito_e_resolver_pela_api(self):
        self.alocar(self.a, self.p1)
        e = self.b.encontros.get(data=date(2027, 2, 15))
        r = self.post(self.p2, e, {"campos": {"professor_id": self.p1.id, "conteudo": "X"}, "versao": e.versao})
        self.assertEqual(r.status_code, 200)                      # salvar não é bloqueado
        self.assertEqual(len(r.json()["estado"]["conflitos"]), 1)
        self.assertTrue(any(p["tipo"] == "conflito" for p in problemas_para_aprovacao(self.b)))
        e.refresh_from_db()
        r = self.post(self.p2, e, {"campos": {"professor_id": self.p2.id}, "versao": e.versao})
        self.assertEqual(r.json()["estado"]["conflitos"], {})
        self.assertEqual(Conflito.objects.get().status, "RESOLVIDO")


class PermissaoTests(Base):
    def test_professor_sem_vinculo_nao_edita(self):
        e = self.a.encontros.first()
        self.assertEqual(self.post(self.p2, e, {"campos": {"conteudo": "X"}}).status_code, 403)

    def test_professor_nao_altera_data(self):
        e = self.a.encontros.first()
        self.assertEqual(self.post(self.p1, e, {"campos": {"data": "2027-02-02"}}).status_code, 403)

    def test_sem_liberacao_professor_nao_edita_mas_admin_sim(self):
        Semestre.objects.update(preenchimento_liberado=False)
        e = self.a.encontros.first()
        self.assertEqual(self.post(self.p1, e, {"campos": {"conteudo": "X"}}).status_code, 403)
        self.assertEqual(self.post(self.admin, e, {"campos": {"conteudo": "X"}}).status_code, 200)

    def test_paginas_exigem_login_e_perfil(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.client.force_login(self.p1)
        self.assertEqual(self.client.get("/usuarios/").status_code, 403)
        self.assertEqual(self.client.get(f"/componentes/{self.b.id}/cronograma/").status_code, 200)

    def test_aprovacao_exige_cronograma_completo_e_bloqueia_edicao(self):
        self.client.force_login(self.coord)
        self.client.post(f"/componentes/{self.a.id}/aprovar/")
        self.a.refresh_from_db()
        self.assertEqual(self.a.situacao, "RASCUNHO")
        self.a.encontros.update(professor=self.p1, conteudo="Aula")
        self.client.post(f"/componentes/{self.a.id}/aprovar/")
        self.a.refresh_from_db()
        self.assertEqual(self.a.situacao, "APROVADO")
        e = self.a.encontros.first()
        self.assertEqual(self.post(self.p1, e, {"campos": {"conteudo": "Y"}}).status_code, 403)


class ConcorrenciaTests(Base):
    def test_mesmo_campo_gera_409_e_campos_diferentes_mesclam(self):
        e = self.a.encontros.first()
        self.assertEqual(self.post(self.p1, e, {"campos": {"conteudo": "um"}, "base": {"conteudo": ""}, "versao": 1}).status_code, 200)
        r = self.post(self.coord, e, {"campos": {"conteudo": "dois"}, "base": {"conteudo": ""}, "versao": 1})
        self.assertEqual(r.status_code, 409)
        r = self.post(self.coord, e, {"campos": {"local": "Sala 1"}, "base": {"local": ""}, "versao": 1})
        self.assertEqual(r.status_code, 200)
        e.refresh_from_db()
        self.assertEqual((e.conteudo, e.local), ("um", "Sala 1"))


class ExportacaoTests(Base):
    def test_docx_e_pdf(self):
        self.client.force_login(self.p1)
        r = self.client.get(f"/componentes/{self.a.id}/exportar/docx/")
        self.assertTrue(r.content.startswith(b"PK") and "RASCUNHO" in r["Content-Disposition"])
        r = self.client.get(f"/componentes/{self.a.id}/exportar/pdf/")
        self.assertTrue(r.content.startswith(b"%PDF"))
