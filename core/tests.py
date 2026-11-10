"""Testes essenciais das regras críticas (conflitos, permissões, concorrência)."""
import io
import json
from datetime import date, time
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from docx import Document

from .exports import linhas_cronograma
from .forms import CadastroProfessorForm, SemestreForm
from .models import (
    Componente,
    Conflito,
    DataBloqueada,
    Encontro,
    HistoricoAlteracao,
    HorarioSemanal,
    ObservacaoConflito,
    Semestre,
    Usuario,
)
from .services import estatisticas, gerar_encontros, problemas_para_aprovacao, sincronizar_conflitos


class Base(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
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

    def test_regerar_preserva_encontro_com_grupos_ou_tipo_e_nao_duplica_ao_desbloquear(self):
        e_grupos = self.a.encontros.get(data=date(2027, 2, 1))
        e_grupos.grupos = "Subgrupo Prático G1"
        e_grupos.tipo = "P"
        e_grupos.save()
        DataBloqueada.objects.create(semestre=self.sem, data=date(2027, 2, 1), descricao="Recesso")
        gerar_encontros(self.a)
        e_grupos.refresh_from_db()
        self.assertTrue(e_grupos.excepcional)
        self.assertEqual((e_grupos.grupos, e_grupos.tipo), ("Subgrupo Prático G1", "P"))

        # Ao remover o bloqueio e regerar, deve restaurar excepcional=False sem criar duplicata.
        DataBloqueada.objects.filter(semestre=self.sem, data=date(2027, 2, 1)).delete()
        gerar_encontros(self.a)
        encontros_dia = list(self.a.encontros.filter(data=date(2027, 2, 1), hora_inicio=time(14)))
        self.assertEqual(len(encontros_dia), 1)
        self.assertFalse(encontros_dia[0].excepcional)
        self.assertEqual(encontros_dia[0].grupos, "Subgrupo Prático G1")

    def test_alterar_hora_fim_atualiza_ch_padrao(self):
        e_custom = self.a.encontros.get(data=date(2027, 2, 1))
        e_custom.ch = "5h"
        e_custom.save()
        self.a.horarios.update(hora_fim=time(17))
        gerar_encontros(self.a)
        e_custom.refresh_from_db()
        e_padrao = self.a.encontros.get(data=date(2027, 2, 15))
        self.assertEqual(e_custom.ch, "5h")
        self.assertEqual(e_padrao.ch, "4h")
        self.assertEqual(e_padrao.hora_fim, time(17))


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

    def test_sem_liberacao_coordenador_nao_cria_exclui_nem_aprova(self):
        self.a.encontros.update(professor=self.p1, conteudo="Aula")
        Semestre.objects.update(preenchimento_liberado=False)
        e = self.a.encontros.first()
        self.client.force_login(self.coord)
        r_criar = self.client.post(
            f"/api/componentes/{self.a.id}/encontros/",
            json.dumps({"apos_id": e.id}),
            content_type="application/json",
        )
        r_excluir = self.client.post(f"/api/encontros/{e.id}/excluir/")
        r_aprovar = self.client.post(f"/componentes/{self.a.id}/aprovar/")
        self.a.refresh_from_db()
        self.assertEqual(r_criar.status_code, 403)
        self.assertEqual(r_excluir.status_code, 403)
        self.assertEqual(r_aprovar.status_code, 302)
        self.assertEqual(self.a.situacao, "RASCUNHO")

    def test_observacoes_internas_ocultas_para_usuario_sem_vinculo(self):
        e = self.a.encontros.first()
        self.post(self.coord, e, {"campos": {"observacoes": "Sigilo interno da coordenação"}, "versao": e.versao})

        # Professor sem vínculo (p2) não enxerga observações na API nem no histórico.
        self.client.force_login(self.p2)
        estado_p2 = self.client.get(f"/api/componentes/{self.a.id}/estado/").json()
        enc_p2 = next(x for x in estado_p2["encontros"] if x["id"] == e.id)
        self.assertEqual(enc_p2["observacoes"], "")
        hist_p2 = self.client.get(f"/api/encontros/{e.id}/historico/").json()
        self.assertFalse(any(r["campo"] == "Observações" for r in hist_p2["itens"]))
        r_hist_pag = self.client.get(f"/historico/?componente={self.a.id}")
        self.assertNotContains(r_hist_pag, "Sigilo interno da coordenação")

        # Professor vinculado (p1) e coordenador enxergam normalmente.
        self.client.force_login(self.p1)
        estado_p1 = self.client.get(f"/api/componentes/{self.a.id}/estado/").json()
        enc_p1 = next(x for x in estado_p1["encontros"] if x["id"] == e.id)
        self.assertEqual(enc_p1["observacoes"], "Sigilo interno da coordenação")

    def test_comentario_em_conflito_restrito_aos_envolvidos(self):
        self.alocar(self.a, self.p1)
        self.alocar(self.b, self.p1)
        conflito = Conflito.objects.get()
        p_externo = Usuario.objects.create_user("externo@t.example", "senha-Teste-123", nome="Externo", perfil="PROF")

        self.client.force_login(p_externo)
        r = self.client.post(f"/conflitos/{conflito.id}/", {"acao": "observacao", "texto": "Intruso"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ObservacaoConflito.objects.filter(conflito=conflito, texto="Intruso").exists())

        self.client.force_login(self.p1)
        r_ok = self.client.post(f"/conflitos/{conflito.id}/", {"acao": "observacao", "texto": "Ajustarei horário"})
        self.assertEqual(r_ok.status_code, 302)
        self.assertTrue(ObservacaoConflito.objects.filter(conflito=conflito, texto="Ajustarei horário").exists())

    def test_open_redirect_bloqueado_em_conflitos_verificar(self):
        self.client.force_login(self.p1)
        for destino_malicioso in ("https://evil.example/phish", "//evil.example/phish", "javascript:alert(1)"):
            with self.subTest(destino=destino_malicioso):
                r = self.client.post("/conflitos/verificar/", {"proximo": destino_malicioso})
                self.assertEqual(r.status_code, 302)
                self.assertEqual(r["Location"], reverse("conflitos"))
        r_interno = self.client.post("/conflitos/verificar/", {"proximo": reverse("dashboard")})
        self.assertEqual(r_interno["Location"], reverse("dashboard"))

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

    def test_head_permitido_em_rotas_publicas_e_apis(self):
        self.assertEqual(self.client.head(reverse("cadastro_professor")).status_code, 200)
        self.assertEqual(self.client.head(reverse("login")).status_code, 200)
        self.client.force_login(self.p1)
        e = self.a.encontros.first()
        self.assertEqual(self.client.head(reverse("api_estado", args=[self.a.pk])).status_code, 200)
        self.assertEqual(self.client.head(reverse("api_encontro_historico", args=[e.pk])).status_code, 200)

    def test_troca_obrigatoria_rejeita_mesma_senha_e_bloqueia_api_com_403(self):
        u = Usuario.objects.create_user(
            "temp@t.example", "SenhaTemp#2027", nome="Docente Temp", perfil="PROF", precisa_trocar_senha=True
        )
        self.client.login(username="temp@t.example", password="SenhaTemp#2027")
        r_api = self.client.get(reverse("api_estado", args=[self.a.pk]))
        self.assertEqual(r_api.status_code, 403)
        self.assertIn("erro", r_api.json())

        # Tentar manter a mesma senha temporária deve falhar.
        r_mesma = self.client.post(
            reverse("trocar_senha"),
            {"old_password": "SenhaTemp#2027", "new_password1": "SenhaTemp#2027", "new_password2": "SenhaTemp#2027"},
        )
        self.assertEqual(r_mesma.status_code, 200)
        u.refresh_from_db()
        self.assertTrue(u.precisa_trocar_senha)

        # Nova senha válida libera a conta e mantém a sessão.
        r_nova = self.client.post(
            reverse("trocar_senha"),
            {"old_password": "SenhaTemp#2027", "new_password1": "NovaSenha!2027", "new_password2": "NovaSenha!2027"},
        )
        self.assertRedirects(r_nova, reverse("dashboard"))
        u.refresh_from_db()
        self.assertFalse(u.precisa_trocar_senha)

    def test_admin_nao_redefine_propria_senha_com_temporaria(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("usuario_redefinir_senha", args=[self.admin.pk]), follow=True)
        self.assertEqual(r.status_code, 200)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.precisa_trocar_senha)
        self.assertEqual(self.client.session.get(SESSION_KEY), str(self.admin.pk))

    @override_settings(CRONOMED_LIMITE_LOGIN_TENTATIVAS=3, CRONOMED_LIMITE_CADASTRO_TENTATIVAS=2)
    def test_rate_limit_em_login_e_cadastro(self):
        for _ in range(3):
            self.client.post(reverse("login"), {"username": "p1@t.example", "password": "errada"})
        r_login = self.client.post(reverse("login"), {"username": "p1@t.example", "password": "errada"})
        self.assertEqual(r_login.status_code, 429)

        cache.clear()
        for _ in range(2):
            self.cadastrar(password2="diferente")
        r_cad = self.cadastrar(password2="diferente")
        self.assertEqual(r_cad.status_code, 429)


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

    def test_payload_json_invalido_ou_nao_objeto_retorna_400(self):
        e = self.a.encontros.first()
        self.client.force_login(self.p1)
        for payload in ("{invalido", "[]", "null", '"texto"', '{"campos": []}'):
            with self.subTest(payload=payload):
                r = self.client.post(f"/api/encontros/{e.id}/", payload, content_type="application/json")
                self.assertEqual(r.status_code, 400)

    def test_rejeita_horarios_semanais_sobrepostos_e_encolhimento_invalido_de_semestre(self):
        self.client.force_login(self.coord)
        r = self.client.post(
            reverse("componente_editar", args=[self.a.pk]),
            {
                "curso": self.a.curso,
                "nome": self.a.nome,
                "codigo": self.a.codigo,
                "periodo": self.a.periodo,
                "turma": self.a.turma,
                "turno": self.a.turno,
                "semestre": self.sem.pk,
                "carga_horaria": self.a.carga_horaria,
                "ch_teorica": self.a.ch_teorica,
                "ch_pratica": self.a.ch_pratica,
                "professores": [self.p1.pk],
                "data_inicio": "2027-02-01",
                "data_fim": "2027-02-22",
                "local_padrao": "",
                "h_dia": ["0", "0"],
                "h_inicio": ["14:00", "15:00"],
                "h_fim": ["16:00", "17:00"],
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "sobrepostos")

        form_sem = SemestreForm(
            data={
                "nome": self.sem.nome,
                "data_inicio": "2027-02-10",
                "data_fim": "2027-06-30",
                "preenchimento_liberado": True,
            },
            instance=self.sem,
        )
        self.assertFalse(form_sem.is_valid())


class ExportacaoTests(Base):
    def test_docx_e_pdf(self):
        self.client.force_login(self.p1)
        r = self.client.get(f"/componentes/{self.a.id}/exportar/docx/")
        self.assertTrue(r.content.startswith(b"PK") and "RASCUNHO" in r["Content-Disposition"])
        r = self.client.get(f"/componentes/{self.a.id}/exportar/pdf/")
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_multiplos_docentes_copia_grupos_e_mescla_na_exportacao_docx_e_pdf(self):
        e1 = self.b.encontros.first()
        e1.professor = self.p1
        e1.conteudo = "Semiologia abdominal"
        e1.grupos = "Grupos A e B"
        e1.save()

        self.client.force_login(self.coord2)
        r_novo = self.client.post(
            f"/api/componentes/{self.b.id}/encontros/",
            json.dumps({
                "data": e1.data.isoformat(),
                "inicio": e1.hora_inicio.strftime("%H:%M"),
                "fim": e1.hora_fim.strftime("%H:%M"),
            }),
            content_type="application/json",
        )
        self.assertEqual(r_novo.status_code, 200)
        e2 = Encontro.objects.get(pk=r_novo.json()["encontro_id"])
        self.assertEqual(e2.grupos, "Grupos A e B")
        e2.professor = self.p2
        e2.save()

        linhas = [l for l in linhas_cronograma(self.b) if not l.get("feriado") and l["celulas"][0] == "01/02"]
        self.assertEqual(len(linhas), 2)
        self.assertTrue(linhas[1].get("continua"))

        # Exporta mesmo se aprovado_em estiver ausente (dados legados) e confere conteúdo do DOCX.
        Componente.objects.filter(pk=self.b.pk).update(situacao="APROVADO", aprovado_em=None)
        r_docx = self.client.get(f"/componentes/{self.b.id}/exportar/docx/")
        self.assertEqual(r_docx.status_code, 200)
        doc = Document(io.BytesIO(r_docx.content))
        texto_tabelas = "\n".join(cel.text for tab in doc.tables for lin in tab.rows for cel in lin.cells)
        self.assertIn("Semiologia abdominal", texto_tabelas)
        self.assertIn("Prof 1", texto_tabelas)
        self.assertIn("Prof 2", texto_tabelas)
        self.assertIn("Carnaval", texto_tabelas)

        r_pdf = self.client.get(f"/componentes/{self.b.id}/exportar/pdf/")
        self.assertEqual(r_pdf.status_code, 200)
        self.assertTrue(r_pdf.content.startswith(b"%PDF"))

    def test_estatisticas_sem_n_mais_1_queries(self):
        comps = list(Componente.objects.all())
        with self.assertNumQueries(2):
            stats = estatisticas(comps)
        self.assertEqual(set(stats.keys()), {c.id for c in comps})
