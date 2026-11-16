"""Testes da detecção determinística de conflitos: docente, turma e calendário."""
from datetime import date, time

from django.test import SimpleTestCase, TestCase

from . import agenda as ag
from .models import Componente, Conflito, DataBloqueada, Encontro, HorarioSemanal, Semestre, Usuario
from .services import gerar_encontros, problemas_para_aprovacao, sincronizar_conflitos

SEG, TER = date(2027, 2, 15), date(2027, 2, 16)


def aula(id_, comp, prof, turma, dia, ini, fim, sem=1):
    return ag.Aula(id_, comp, sem, turma, prof, dia, time(ini), time(fim))


class AgendaTests(SimpleTestCase):
    """Regras puras, sem banco."""

    T4A = ag.chave_turma(1, "Medicina", "4º", "A")

    def tipos(self, agenda):
        return sorted(c.tipo for c in agenda.conflitos())

    def test_chave_turma_normaliza_e_exige_periodo_e_turma(self):
        self.assertEqual(self.T4A, ag.chave_turma(1, "MEDICINA ", "4o período", " a"))
        self.assertNotEqual(self.T4A, ag.chave_turma(1, "Medicina", "5º", "A"))
        self.assertNotEqual(self.T4A, ag.chave_turma(2, "Medicina", "4º", "A"))
        self.assertIsNone(ag.chave_turma(1, "Medicina", "", "A"))
        self.assertIsNone(ag.chave_turma(1, "Medicina", "4º", " "))

    def test_docente_sobreposto_e_consecutivo(self):
        agenda = ag.Agenda([aula(1, 10, 7, None, SEG, 14, 16), aula(2, 20, 7, None, SEG, 15, 17),
                            aula(3, 30, 7, None, SEG, 17, 18)])
        (c,) = agenda.conflitos()
        self.assertEqual((c.tipo, c.a, c.b, c.professor_id, c.inicio, c.fim), ("DOCENTE", 1, 2, 7, time(15), time(16)))

    def test_turma_so_conflita_entre_componentes_diferentes(self):
        mesmo_componente = ag.Agenda([aula(1, 10, 7, self.T4A, SEG, 14, 16), aula(2, 10, 8, self.T4A, SEG, 14, 16)])
        self.assertEqual(self.tipos(mesmo_componente), [])
        outro = ag.Agenda([aula(1, 10, 7, self.T4A, SEG, 14, 16), aula(2, 20, 8, self.T4A, SEG, 15, 17)])
        self.assertEqual(self.tipos(outro), ["TURMA"])
        sem_dado = ag.Agenda([aula(1, 10, 7, None, SEG, 14, 16), aula(2, 20, 8, None, SEG, 15, 17)])
        self.assertEqual(self.tipos(sem_dado), [])

    def test_mesmo_par_pode_ter_conflito_docente_e_de_turma(self):
        agenda = ag.Agenda([aula(1, 10, 7, self.T4A, SEG, 14, 16), aula(2, 20, 7, self.T4A, SEG, 15, 17)])
        self.assertEqual(self.tipos(agenda), ["DOCENTE", "TURMA"])

    def test_tres_encontros_simultaneos_geram_tres_pares(self):
        agenda = ag.Agenda([aula(i, i * 10, 7, None, SEG, 14, 16) for i in (1, 2, 3)])
        self.assertEqual({(c.a, c.b) for c in agenda.conflitos()}, {(1, 2), (1, 3), (2, 3)})

    def test_calendario_data_bloqueada_e_fora_do_semestre(self):
        cal = {1: ag.Calendario(date(2027, 2, 1), date(2027, 6, 30), {TER: "Feriado local"})}
        agenda = ag.Agenda([aula(1, 10, None, None, TER, 8, 10), aula(2, 10, None, None, date(2027, 7, 1), 8, 10),
                            aula(3, 10, None, None, SEG, 8, 10)], cal)
        self.assertEqual({(c.a, c.motivo) for c in agenda.conflitos()},
                         {(1, "DATA_BLOQUEADA"), (2, "FORA_DO_SEMESTRE")})

    def test_alterar_mantem_indices_e_resultado_e_deterministico(self):
        aulas = [aula(1, 10, 7, self.T4A, SEG, 14, 16), aula(2, 20, 7, self.T4A, SEG, 15, 17)]
        agenda = ag.Agenda(aulas)
        antes = ag.ordenar(agenda.conflitos())
        self.assertEqual(antes, ag.ordenar(ag.Agenda(reversed(aulas)).conflitos()))
        anterior = agenda.alterar(2, data=TER)
        self.assertEqual(agenda.conflitos(), set())
        agenda.alterar(2, **anterior)
        self.assertEqual(ag.ordenar(agenda.conflitos()), antes)

    def test_ids_textuais_e_inteiros_convivem(self):
        agenda = ag.Agenda([aula(5, 10, 7, None, SEG, 14, 16), aula("L3", 20, 7, None, SEG, 15, 17)])
        (c,) = agenda.conflitos()
        self.assertEqual((c.a, c.b), (5, "L3"))


class BaseConflitos(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = Usuario.objects.create_user
        cls.coord = U("coord@t.example", "senha-Teste-123", nome="Coord", perfil="COORD")
        cls.p1 = U("p1@t.example", "senha-Teste-123", nome="Prof 1", perfil="PROF")
        cls.p2 = U("p2@t.example", "senha-Teste-123", nome="Prof 2", perfil="PROF")
        cls.sem = Semestre.objects.create(
            nome="T.1", data_inicio=date(2027, 2, 1), data_fim=date(2027, 6, 30), preenchimento_liberado=True
        )

    def comp(self, nome, turma="A", periodo="4º", ini=time(14), fim=time(16), dia=0, sem=None):
        c = Componente.objects.create(
            nome=nome, turma=turma, periodo=periodo, semestre=sem or self.sem, coordenador=self.coord,
            data_inicio=date(2027, 2, 15), data_fim=date(2027, 2, 21),
        )
        HorarioSemanal.objects.create(componente=c, dia_semana=dia, hora_inicio=ini, hora_fim=fim)
        gerar_encontros(c)
        return c

    def ativos(self, tipo=None):
        qs = Conflito.objects.filter(status="ATIVO")
        return qs.filter(tipo=tipo) if tipo else qs


class ConflitoTurmaTests(BaseConflitos):
    def test_mesma_turma_em_componentes_diferentes(self):
        a = self.comp("A")
        b = self.comp("B", ini=time(15), fim=time(17))
        c = self.ativos().get()
        self.assertEqual((c.tipo, c.professor, c.sobreposicao_inicio, c.sobreposicao_fim), ("TURMA", None, time(15), time(16)))
        self.assertEqual({c.encontro_a.componente_id, c.encontro_b.componente_id}, {a.id, b.id})
        self.assertIn("Turma A", c.explicacao)
        for comp in (a, b):
            self.assertTrue(any(p["tipo"] == "conflito" for p in problemas_para_aprovacao(comp)))

    def test_turmas_periodos_ou_semestres_diferentes_nao_conflitam(self):
        outro_sem = Semestre.objects.create(nome="T.2", data_inicio=date(2027, 2, 1), data_fim=date(2027, 6, 30))
        self.comp("A")
        self.comp("B", turma="B")
        self.comp("C", periodo="5º")
        self.comp("D", sem=outro_sem)
        self.comp("E", periodo="")           # sem período: dado insuficiente para identificar a turma
        self.assertFalse(self.ativos().exists())

    def test_resolve_ao_mudar_horario_e_reaparece_ao_voltar(self):
        self.comp("A")
        b = self.comp("B", ini=time(15), fim=time(17))
        e = b.encontros.get()
        Encontro.objects.filter(pk=e.pk).update(hora_inicio=time(16), hora_fim=time(18))
        sincronizar_conflitos(semestre_ids={self.sem.id})
        c = Conflito.objects.get()
        self.assertEqual(c.status, "RESOLVIDO")
        Encontro.objects.filter(pk=e.pk).update(hora_inicio=time(15), hora_fim=time(17))
        sincronizar_conflitos(semestre_ids={self.sem.id})
        c.refresh_from_db()
        self.assertEqual((c.status, c.resolvido_em), ("ATIVO", None))
        self.assertEqual(Conflito.objects.count(), 1)     # o mesmo registro é reativado

    def test_edicao_pela_api_recalcula_turma(self):
        a = self.comp("A")
        self.comp("B", ini=time(16), fim=time(18))
        self.assertFalse(self.ativos().exists())
        self.client.force_login(self.coord)
        e = a.encontros.get()
        r = self.client.post(f"/api/encontros/{e.id}/", {"campos": {"fim": "17:00"}, "versao": e.versao},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ativos("TURMA").count(), 1)
        (lado,) = r.json()["estado"]["conflitos"][str(e.id)]
        self.assertEqual((lado["tipo"], lado["titulo"]), ("TURMA", "Conflito de turma"))


class ConflitoCalendarioTests(BaseConflitos):
    def test_bloquear_data_gera_restricao_para_encontro_preenchido(self):
        a = self.comp("A")
        e = a.encontros.get()
        Encontro.objects.filter(pk=e.pk).update(conteudo="Aula", professor=self.p1)
        self.client.force_login(Usuario.objects.create_superuser("adm@t.example", "senha-Teste-123", nome="Adm"))
        r = self.client.post(f"/semestres/{self.sem.id}/", {
            "acao": "bloquear_data", "data": "2027-02-15", "descricao": "Feriado municipal", "tipo": "FERIADO",
        })
        self.assertEqual(r.status_code, 302)
        c = self.ativos().get()
        self.assertEqual((c.tipo, c.motivo, c.encontro_b, c.encontro_a_id), ("CALENDARIO", "DATA_BLOQUEADA", None, e.id))
        self.assertIn("Feriado municipal", c.explicacao)
        self.assertTrue(any(p["tipo"] == "conflito" for p in problemas_para_aprovacao(a)))
        bloqueio = DataBloqueada.objects.get()
        self.client.post(f"/semestres/{self.sem.id}/", {"acao": "remover_data", "id": bloqueio.id})
        c.refresh_from_db()
        self.assertEqual(c.status, "RESOLVIDO")

    def test_encontro_fora_do_periodo_letivo(self):
        a = self.comp("A")
        self.client.force_login(self.coord)
        e = a.encontros.get()
        r = self.client.post(f"/api/encontros/{e.id}/", {"campos": {"data": "2027-07-05"}, "versao": e.versao},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)        # salvar nunca é bloqueado por conflito
        c = self.ativos().get()
        self.assertEqual((c.tipo, c.motivo), ("CALENDARIO", "FORA_DO_SEMESTRE"))

    def test_encontro_excepcional_em_data_bloqueada(self):
        a = self.comp("A")
        DataBloqueada.objects.create(semestre=self.sem, data=date(2027, 2, 17), descricao="Recesso")
        self.client.force_login(self.coord)
        r = self.client.post(f"/api/componentes/{a.id}/encontros/",
                             {"data": "2027-02-17", "inicio": "08:00", "fim": "10:00"}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ativos("CALENDARIO").count(), 1)


class ConflitosSimultaneosTests(BaseConflitos):
    def test_docente_turma_e_calendario_ao_mesmo_tempo(self):
        a = self.comp("A")
        b = self.comp("B", ini=time(15), fim=time(17))
        Encontro.objects.filter(componente__in=[a, b]).update(professor=self.p1)
        DataBloqueada.objects.create(semestre=self.sem, data=date(2027, 2, 15), descricao="Feriado")
        sincronizar_conflitos()
        self.assertEqual(sorted(self.ativos().values_list("tipo", flat=True)),
                         ["CALENDARIO", "CALENDARIO", "DOCENTE", "TURMA"])
        # Sincronizações repetidas e parciais não duplicam nem perdem registros.
        sincronizar_conflitos()
        sincronizar_conflitos({self.p1.id})
        sincronizar_conflitos(semestre_ids={self.sem.id})
        self.assertEqual(Conflito.objects.count(), 4)

    def test_telas_exibem_todos_os_tipos(self):
        a = self.comp("A")
        b = self.comp("B", ini=time(15), fim=time(17))
        Encontro.objects.filter(componente__in=[a, b]).update(professor=self.p1)
        DataBloqueada.objects.create(semestre=self.sem, data=date(2027, 2, 15), descricao="Feriado")
        sincronizar_conflitos()
        self.client.force_login(self.coord)
        r = self.client.get("/conflitos/")
        for texto in ("Conflito docente", "Conflito de turma", "Restrição de calendário"):
            self.assertContains(r, texto)
        self.assertEqual(len(self.client.get("/conflitos/?tipo=TURMA").context["conflitos"]), 1)
        for c in Conflito.objects.all():
            self.assertEqual(self.client.get(f"/conflitos/{c.id}/").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get(f"/componentes/{a.id}/cronograma/").status_code, 200)
        self.assertEqual(self.client.post(f"/componentes/{a.id}/validar/").status_code, 200)
