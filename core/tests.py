"""Testes essenciais das regras críticas (conflitos, permissões, concorrência)."""
import json
from datetime import date, time
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY
from django.test import Client, TestCase
from django.urls import reverse

from .forms import CadastroProfessorForm
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


class CadastroProfessorTests(Base):
    senha = "Aula!Horizonte2027"

    def dados(self, **alteracoes):
        return {
            "nome": "Maria Oliveira",
            "email": "Maria@t.example",
            "username": "Maria.Docente",
            "password1": self.senha,
            "password2": self.senha,
            **alteracoes,
        }

    def cadastrar(self, **alteracoes):
        return self.client.post(reverse("cadastro_professor"), self.dados(**alteracoes))

    def test_telas_publicas_e_protecao_csrf(self):
        url = reverse("cadastro_professor")
        self.assertContains(self.client.get(reverse("login")), f'href="{url}"')
        cliente = Client(enforce_csrf_checks=True)
        self.assertContains(cliente.get(url), "Criar conta e entrar")
        self.assertEqual(cliente.post(url, self.dados()).status_code, 403)
        self.assertFalse(Usuario.objects.filter(username="maria.docente").exists())
        token = cliente.cookies["csrftoken"].value
        resposta = cliente.post(url, self.dados(csrfmiddlewaretoken=token))
        self.assertRedirects(resposta, reverse("dashboard"))
        self.assertNotEqual(cliente.cookies["csrftoken"].value, token)

    def test_cria_professor_ativo_com_sessao_e_sem_vinculo(self):
        resposta = self.cadastrar(
            perfil="ADMIN", is_staff="1", is_superuser="1", precisa_trocar_senha="1",
            componentes_vinculados=self.a.pk,
        )
        self.assertRedirects(resposta, reverse("dashboard"))
        usuario = Usuario.objects.get(username="maria.docente")
        self.assertEqual(usuario.email, "maria@t.example")
        self.assertEqual(usuario.perfil, Usuario.Perfil.PROF)
        self.assertTrue(usuario.is_active)
        self.assertFalse(usuario.is_staff or usuario.is_superuser or usuario.precisa_trocar_senha)
        self.assertNotEqual(usuario.password, self.senha)
        self.assertTrue(usuario.check_password(self.senha))
        self.assertEqual(self.client.session[SESSION_KEY], str(usuario.pk))
        self.assertEqual(self.client.get(reverse("usuarios")).status_code, 403)
        self.assertEqual(self.client.get(reverse("cronograma", args=[self.a.pk])).status_code, 200)
        encontro = self.a.encontros.first()
        resposta = self.client.post(
            reverse("api_encontro_salvar", args=[encontro.pk]),
            {"campos": {"conteudo": "X"}},
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_reentrada_por_nome_de_usuario_e_email(self):
        self.cadastrar()
        usuario = Usuario.objects.get(username="maria.docente")
        for login in (" Maria.DOCENTE ", "MARIA@T.EXAMPLE"):
            with self.subTest(login=login):
                self.client.post(reverse("logout"))
                self.assertNotIn(SESSION_KEY, self.client.session)
                resposta = self.client.post(reverse("login"), {"username": login, "password": self.senha})
                self.assertRedirects(resposta, reverse("dashboard"))
                self.assertEqual(self.client.session[SESSION_KEY], str(usuario.pk))

    def test_recusa_senha_incorreta_e_conta_desativada(self):
        self.cadastrar()
        self.client.post(reverse("logout"))
        resposta = self.client.post(reverse("login"), {"username": "maria.docente", "password": "incorreta"})
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)
        Usuario.objects.filter(username="maria.docente").update(is_active=False)
        resposta = self.client.post(reverse("login"), {"username": "maria.docente", "password": self.senha})
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_preserva_login_legado_e_troca_obrigatoria(self):
        url = reverse("login")
        dados = {"username": self.coord.email.upper(), "password": "senha-Teste-123"}
        self.assertRedirects(self.client.post(url, dados), reverse("dashboard"))
        self.client.post(reverse("logout"))
        Usuario.objects.filter(pk=self.coord.pk).update(precisa_trocar_senha=True)
        resposta = self.client.post(url, dados, follow=True)
        self.assertEqual(resposta.redirect_chain, [(reverse("dashboard"), 302), (reverse("trocar_senha"), 302)])

    def test_rejeita_dados_invalidos_sem_criar_conta(self):
        quantidade = Usuario.objects.count()
        casos = (
            ("password2", {"password2": "senha-diferente"}),
            ("password2", {"password1": "12345678", "password2": "12345678"}),
            ("username", {"username": "maria@exemplo.com"}),
            ("username", {"username": ""}),
            ("email", {"email": "sem-arroba"}),
        )
        for campo, dados in casos:
            with self.subTest(dados=dados):
                resposta = self.cadastrar(**dados)
                self.assertEqual(resposta.status_code, 200)
                self.assertIn(campo, resposta.context["form"].errors)
                self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(Usuario.objects.count(), quantidade)

    def test_rejeita_email_e_nome_de_usuario_duplicados(self):
        self.cadastrar()
        self.client.post(reverse("logout"))
        quantidade = Usuario.objects.count()
        resposta = self.cadastrar(username="MARIA.Docente", email="outro@t.example")
        self.assertIn("username", resposta.context["form"].errors)
        resposta = self.cadastrar(username="outro", email=self.admin.email.upper())
        self.assertIn("email", resposta.context["form"].errors)
        self.assertEqual(Usuario.objects.count(), quantidade)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_colisao_detectada_no_banco_retorna_erro_no_formulario(self):
        Usuario.objects.create_user("outro@t.example", self.senha, nome="Outra docente", username="maria.docente")
        validar_real = CadastroProfessorForm.validate_unique

        # Simula uma conta concorrente que ainda não aparecia na primeira validação.
        with patch.object(CadastroProfessorForm, "validate_unique", autospec=True) as validar:
            def validar_apos_colisao(form):
                if validar.call_count > 1:
                    validar_real(form)

            validar.side_effect = validar_apos_colisao
            resposta = self.cadastrar()
        self.assertIn("username", resposta.context["form"].errors)
        self.assertFalse(Usuario.objects.filter(email="maria@t.example").exists())

    def test_sessao_ativa_nao_abre_novo_cadastro(self):
        self.client.force_login(self.p1)
        self.assertRedirects(self.client.get(reverse("cadastro_professor")), reverse("dashboard"))
        self.assertRedirects(self.cadastrar(), reverse("dashboard"))
        self.assertEqual(self.client.session[SESSION_KEY], str(self.p1.pk))
        self.assertFalse(Usuario.objects.filter(username="maria.docente").exists())


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
