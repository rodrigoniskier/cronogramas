"""Testes do motor de sugestões: restrições rígidas, preferências, plano conjunto e aplicação."""
import json
from datetime import date, time

from django.test import TestCase
from django.urls import reverse

from . import agenda as ag
from . import sugestoes as sg
from .models import Componente, Conflito, DataBloqueada, Encontro, HistoricoAlteracao, HorarioSemanal, Semestre, Usuario
from .services import sincronizar_conflitos

SEG, TER, QUA, QUI, SEX, SAB, DOM = (date(2027, 2, d) for d in range(15, 22))
LIVRE = lambda comp: True


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = Usuario.objects.create_user
        cls.admin = Usuario.objects.create_superuser("admin@t.example", "senha-Teste-123", nome="Admin")
        cls.coord = U("coord@t.example", "senha-Teste-123", nome="Coord Um", perfil="COORD")
        cls.coord2 = U("coord2@t.example", "senha-Teste-123", nome="Coord Dois", perfil="COORD")
        cls.p1 = U("p1@t.example", "senha-Teste-123", nome="Prof 1", perfil="PROF")
        cls.p2 = U("p2@t.example", "senha-Teste-123", nome="Prof 2", perfil="PROF")
        cls.p3 = U("p3@t.example", "senha-Teste-123", nome="Prof 3", perfil="PROF")
        cls.sem = Semestre.objects.create(
            nome="2027.1", data_inicio=date(2027, 2, 1), data_fim=date(2027, 6, 30), preenchimento_liberado=True
        )

    def comp(self, nome, turma="A", coord=None, profs=(), inicio=SEG, fim=SEX, dias=(0,), periodo="4º", turno="TARDE"):
        c = Componente.objects.create(
            nome=nome, turma=turma, periodo=periodo, turno=turno, semestre=self.sem,
            coordenador=coord or self.coord, data_inicio=inicio, data_fim=fim,
        )
        c.professores.set(profs)
        HorarioSemanal.objects.bulk_create(
            [HorarioSemanal(componente=c, dia_semana=d, hora_inicio=time(14), hora_fim=time(16)) for d in dias]
        )
        return c

    def enc(self, comp, dia=SEG, ini=14, fim=16, prof=None):
        return Encontro.objects.create(
            componente=comp, data=dia, hora_inicio=time(ini), hora_fim=time(fim), professor=prof, conteudo="Aula"
        )

    def ativos(self):
        return Conflito.objects.filter(status="ATIVO")

    def contexto(self):
        sincronizar_conflitos()
        return sg.montar_contexto(self.sem)

    def conferir_efeito(self, ctx, conflito, sugestao):
        """Verificação independente do motor: reaplica a ação e recalcula TODOS os conflitos."""
        antes = {c.chave for c in ctx.agenda.conflitos()}
        anteriores = sg._aplicar(ctx.agenda, sugestao.acao)
        depois = {c.chave for c in ctx.agenda.conflitos()}
        sg._desfazer(ctx.agenda, anteriores)
        self.assertNotIn(conflito.chave, depois, sugestao.descricao)
        self.assertLessEqual(depois, antes, f"criou conflito: {sugestao.descricao}")
        self.assertEqual({c.chave for c in ctx.agenda.conflitos()}, antes)       # o estado foi restaurado

    def postar(self, sugestoes, usuario=None, proximo="/conflitos/"):
        if usuario:
            self.client.force_login(usuario)
        cargas = [s.carga if hasattr(s, "carga") else s for s in sugestoes]
        return self.client.post(reverse("aplicar_sugestoes"), {"acoes": json.dumps(cargas), "proximo": proximo})


class SugestaoTests(Base):
    def test_sugestoes_ordenadas_por_custo_e_verificadas(self):
        a = self.comp("A", profs=[self.p1, self.p2])
        b = self.comp("B", turma="B", profs=[self.p1])
        self.enc(a, prof=self.p1)
        eb = self.enc(b, ini=15, fim=17, prof=self.p1)
        ctx = self.contexto()
        (conflito,) = sg.conflitos_do_semestre(ctx)
        sugestoes, diagnostico = sg.sugerir(ctx, conflito, LIVRE, limite=8)
        self.assertEqual(diagnostico, "")
        self.assertEqual(len(sugestoes), 8)
        custos = [s.acao.custo for s in sugestoes]
        self.assertEqual(custos, sorted(custos))
        self.assertEqual({s.acao.tipo for s in sugestoes}, {"MOVER", "TROCAR_DOCENTE"})
        for s in sugestoes:
            self.assertEqual([c.chave for c in s.resolve], [conflito.chave])
            self.conferir_efeito(ctx, conflito, s)
        # A mais barata mantém o horário e muda um dia; trocar o docente só é proposto com vinculado livre.
        melhor = sugestoes[0].acao
        self.assertEqual((melhor.tipo, melhor.inicio, abs((melhor.data - SEG).days)), ("MOVER", melhor.inicio, 1))
        trocas = [s.acao for s in sugestoes if s.acao.tipo == "TROCAR_DOCENTE"]
        self.assertEqual({(t.componente_id, t.professor_id) for t in trocas},
                         {(a.id, self.p2.id), (a.id, self.coord.id), (b.id, self.coord.id)})
        # No máximo um movimento por aula e por data: alternativas realmente distintas.
        movimentos = [(s.acao.encontros, s.acao.data) for s in sugestoes if s.acao.tipo == "MOVER"]
        self.assertEqual(len(movimentos), len(set(movimentos)))
        # Resultado determinístico.
        de_novo, _ = sg.sugerir(sg.montar_contexto(self.sem), conflito, LIVRE, limite=8)
        self.assertEqual([s.carga for s in de_novo], [s.carga for s in sugestoes])
        self.assertIn(eb.id, {i for s in sugestoes for i in s.acao.encontros})

    def test_restricoes_rigidas_delimitam_os_destinos(self):
        # A (Turma A) em data bloqueada. Destinos possíveis: apenas dentro do período do componente (seg–sex).
        a = self.comp("A", profs=[self.p1], inicio=SEG, fim=DOM, dias=(0,))
        alvo = self.enc(a, SEG, prof=self.p1)
        DataBloqueada.objects.create(semestre=self.sem, data=SEG, descricao="Feriado")
        DataBloqueada.objects.create(semestre=self.sem, data=TER, descricao="Ponto facultativo")
        outro = self.comp("Outro", turma="A", inicio=SEG, fim=DOM)             # mesma turma: ocupa a quarta inteira
        self.enc(outro, QUA, 7, 22)
        ocupado = self.comp("Ocupado", turma="Z", inicio=SEG, fim=DOM)         # o docente está ocupado na quinta à tarde
        self.enc(ocupado, QUI, 13, 22, prof=self.p1)
        ctx = self.contexto()
        conflito = next(c for c in sg.conflitos_do_semestre(ctx) if c.a == alvo.id)
        sugestoes, _ = sg.sugerir(ctx, conflito, LIVRE, limite=200)
        self.assertTrue(sugestoes)
        destinos = {(s.acao.data, s.acao.inicio, s.acao.fim) for s in sugestoes}
        datas = {d for d, _, _ in destinos}
        self.assertEqual(datas, {QUI, SEX})                    # nunca seg/ter (bloqueadas), qua (turma), sáb/dom
        for dia, inicio, fim in destinos:
            self.assertEqual((fim.hour * 60 + fim.minute) - (inicio.hour * 60 + inicio.minute), 120)   # duração preservada
            self.assertTrue(time(7) <= inicio and fim <= time(22, 30))
            if dia == QUI:
                self.assertLessEqual(fim, time(13))            # docente ocupado das 13h em diante
        for s in sugestoes:
            self.conferir_efeito(ctx, conflito, s)
        # Preferências: sexta 14h (mantém horário, fora da grade) custa menos que quinta de manhã (muda horário e turno).
        self.assertEqual((sugestoes[0].acao.data, sugestoes[0].acao.inicio), (SEX, time(14)))

    def test_sabado_so_e_sugerido_se_o_componente_ja_tem_aula_aos_sabados(self):
        a = self.comp("A", inicio=SEX, fim=DOM, dias=(4, 5))
        alvo = self.enc(a, SEX)
        DataBloqueada.objects.create(semestre=self.sem, data=SEX, descricao="Feriado")
        ctx = self.contexto()
        (conflito,) = sg.conflitos_do_semestre(ctx)
        sugestoes, _ = sg.sugerir(ctx, conflito, LIVRE, limite=100)
        self.assertEqual({s.acao.data for s in sugestoes}, {SAB})
        self.assertEqual(alvo.id, sugestoes[0].acao.encontros[0])

    def test_aula_com_varios_docentes_e_movida_inteira(self):
        a = self.comp("A", profs=[self.p1, self.p2])
        e1, e2 = self.enc(a, prof=self.p1), self.enc(a, prof=self.p2)
        b = self.comp("B", turma="B")
        self.enc(b, ini=15, fim=17, prof=self.p1)
        ocupado = self.comp("Ocupado", turma="Z")
        self.enc(ocupado, TER, 7, 22, prof=self.p2)            # o segundo docente da aula não pode na terça
        ctx = self.contexto()
        (conflito,) = sg.conflitos_do_semestre(ctx)
        sugestoes, _ = sg.sugerir(ctx, conflito, lambda c: c.id == a.id, lambda c: False, limite=50)
        self.assertTrue(sugestoes)
        for s in sugestoes:
            self.assertEqual(s.acao.encontros, (e1.id, e2.id))
            self.assertNotEqual(s.acao.data, TER)
            self.assertIn("2 docentes", " ".join(s.acao.motivos))

    def test_sem_solucao_explica_o_motivo(self):
        # Componente de um único dia letivo; a turma está ocupada o dia todo e não há substituto vinculado.
        a = self.comp("A", profs=[self.p1], inicio=SEG, fim=SEG)
        b = self.comp("B", turma="B", profs=[self.p1], inicio=SEG, fim=SEG)
        self.enc(a, prof=self.p1)
        self.enc(b, ini=15, fim=17, prof=self.p1)
        Componente.objects.filter(pk__in=[a.pk, b.pk]).update(coordenador=self.admin)   # admin não é docente
        for turma in ("A", "B"):
            cheio = self.comp(f"Cheio {turma}", turma=turma, inicio=SEG, fim=SEG)
            self.enc(cheio, SEG, 7, 14)
            self.enc(cheio, SEG, 17, 22)
        ctx = self.contexto()
        conflito = next(c for c in sg.conflitos_do_semestre(ctx) if c.tipo == "DOCENTE")
        sugestoes, diagnostico = sg.sugerir(ctx, conflito, LIVRE)
        self.assertEqual(sugestoes, [])
        self.assertIn("Nenhuma alternativa atende às restrições rígidas", diagnostico)
        self.assertIn("a turma já tem aula", diagnostico)
        plano = sg.planejar(ctx, LIVRE)
        self.assertEqual(plano.sugestoes, [])
        self.assertIn(conflito.chave, [c.chave for c, _ in plano.sem_solucao])
        self.client.force_login(self.admin)
        resposta = self.client.get(reverse("plano_remanejamento"), {"semestre": self.sem.id})
        self.assertContains(resposta, "Sem solução automática")
        self.assertNotContains(resposta, "Aplicar plano completo")
        detalhe = self.client.get(reverse("conflito_detalhe", args=[self.ativos().get(tipo="DOCENTE").pk]))
        self.assertContains(detalhe, "Nenhuma alternativa atende às restrições rígidas")

    def test_cronograma_aprovado_nunca_e_alterado(self):
        a = self.comp("A", profs=[self.p1, self.p2])
        b = self.comp("B", turma="B", profs=[self.p1, self.p2])
        self.enc(a, prof=self.p1)
        self.enc(b, ini=15, fim=17, prof=self.p1)
        Componente.objects.filter(pk=a.pk).update(situacao="APROVADO")
        ctx = self.contexto()
        (conflito,) = sg.conflitos_do_semestre(ctx)
        sugestoes, _ = sg.sugerir(ctx, conflito, LIVRE, limite=50)
        self.assertEqual({s.acao.componente_id for s in sugestoes}, {b.id})
        Componente.objects.filter(pk=b.pk).update(situacao="PUBLICADO")
        ctx = self.contexto()
        sugestoes, diagnostico = sg.sugerir(ctx, conflito, LIVRE)
        self.assertEqual(sugestoes, [])
        self.assertIn("aprovado/publicado", diagnostico)
        plano = sg.planejar(ctx, LIVRE)
        self.assertEqual((plano.sugestoes, len(plano.fora_de_alcance)), ([], 1))


class PlanoTests(Base):
    def cenario(self):
        """Seis conflitos simultâneos: três pares do mesmo docente, um de turma e dois de calendário."""
        a = self.comp("A", profs=[self.p1], inicio=SEG, fim=date(2027, 2, 26))
        b = self.comp("B", turma="B", profs=[self.p1], inicio=SEG, fim=date(2027, 2, 26))
        c = self.comp("C", turma="C", profs=[self.p1], inicio=SEG, fim=date(2027, 2, 26))
        d = self.comp("D", turma="A", profs=[self.p2], inicio=SEG, fim=date(2027, 2, 26), dias=(2,))
        for comp in (a, b, c):
            self.enc(comp, SEG, prof=self.p1)                  # o mesmo docente em três turmas ao mesmo tempo
        self.enc(a, QUA, prof=self.p3)
        self.enc(d, QUA, 15, 17, prof=self.p2)                 # Turma A em dois componentes
        DataBloqueada.objects.create(semestre=self.sem, data=QUI, descricao="Feriado")
        self.enc(b, QUI, prof=self.p3)
        self.enc(c, QUI, 8, 10, prof=self.p2)
        return a, b, c, d

    def test_plano_resolve_conflitos_simultaneos_e_e_aplicado_por_inteiro(self):
        self.cenario()
        ctx = self.contexto()
        self.assertEqual(sorted(k.tipo for k in sg.conflitos_do_semestre(ctx)),
                         ["CALENDARIO", "CALENDARIO", "DOCENTE", "DOCENTE", "DOCENTE", "TURMA"])
        plano = sg.planejar(ctx, LIVRE)
        self.assertEqual((plano.total, plano.sem_solucao, plano.fora_de_alcance, plano.completa), (6, [], [], True))
        # Três pares do mesmo docente pedem duas ações; turma e calendário, uma cada.
        self.assertEqual(len(plano.sugestoes), 5)
        self.assertEqual(sum(len(s.resolve) for s in plano.sugestoes), 6)
        self.assertEqual(plano.custo, sum(s.acao.custo for s in plano.sugestoes))
        self.assertEqual({k.chave for k in ctx.agenda.conflitos()}, {k.chave for k in sg.conflitos_do_semestre(ctx)})  # agenda intacta
        outro = sg.planejar(sg.montar_contexto(self.sem), LIVRE)
        self.assertEqual([s.carga for s in outro.sugestoes], [s.carga for s in plano.sugestoes])   # determinístico

        resposta = self.postar(plano.sugestoes, self.admin, proximo=f"/conflitos/plano/?semestre={self.sem.id}")
        self.assertRedirects(resposta, f"/conflitos/plano/?semestre={self.sem.id}")
        self.assertEqual(self.ativos().count(), 0)
        self.assertEqual(Conflito.objects.filter(status="RESOLVIDO").count(), 6)
        sincronizar_conflitos()                                # verificação completa e independente
        self.assertEqual(self.ativos().count(), 0)
        self.assertEqual(HistoricoAlteracao.objects.filter(campo="Remanejamento sugerido").count(), 5)
        self.assertContains(self.client.get(resposta["Location"]), "Não há conflitos ativos neste semestre")

    def test_acoes_disputando_o_mesmo_horario_recebem_destinos_distintos(self):
        # Dois componentes da mesma turma com aula em data bloqueada: ambos prefeririam o mesmo horário vizinho.
        DataBloqueada.objects.create(semestre=self.sem, data=SEG, descricao="Feriado")
        x = self.comp("X", inicio=SEG, fim=TER)
        y = self.comp("Y", inicio=SEG, fim=TER)
        self.enc(x, SEG, 14, 18)
        self.enc(y, SEG, 14, 18)
        ctx = self.contexto()
        self.assertEqual(sorted(k.tipo for k in sg.conflitos_do_semestre(ctx)), ["CALENDARIO", "CALENDARIO", "TURMA"])
        plano = sg.planejar(ctx, LIVRE)
        self.assertEqual((len(plano.sugestoes), plano.sem_solucao), (2, []))
        (m1, m2) = (s.acao for s in plano.sugestoes)
        self.assertEqual({m1.data, m2.data}, {TER})
        self.assertTrue(m1.fim <= m2.inicio or m2.fim <= m1.inicio)          # não se sobrepõem
        self.postar(plano.sugestoes, self.admin)
        sincronizar_conflitos()
        self.assertEqual(self.ativos().count(), 0)

    def test_orcamento_de_busca_esgotado_ainda_devolve_plano_valido(self):
        self.cenario()
        ctx = self.contexto()
        plano = sg.planejar(ctx, LIVRE, max_nos=1)
        self.assertFalse(plano.completa)
        self.assertEqual((len(plano.sugestoes), plano.sem_solucao), (5, []))
        self.postar(plano.sugestoes, self.admin)
        self.assertEqual(self.ativos().count(), 0)

    def test_plano_respeita_a_alcada_do_usuario(self):
        a, b, c, d = self.cenario()
        Componente.objects.filter(pk__in=[b.pk, c.pk]).update(coordenador=self.coord2)
        self.client.force_login(self.coord)                    # coordena A e D
        resposta = self.client.get(reverse("plano_remanejamento"), {"semestre": self.sem.id})
        plano = resposta.context["plano"]
        self.assertTrue(plano.sugestoes)
        self.assertLessEqual({s.acao.componente_id for s in plano.sugestoes}, {a.id, d.id})
        self.assertEqual(len(plano.fora_de_alcance), 3)        # B×C do docente e os dois de calendário (B e C)
        self.assertContains(resposta, "Fora da sua alçada")
        # Professor: consulta o plano, mas nada está ao seu alcance.
        self.client.force_login(self.p1)
        plano = self.client.get(reverse("plano_remanejamento"), {"semestre": self.sem.id}).context["plano"]
        self.assertEqual((plano.sugestoes, len(plano.fora_de_alcance)), ([], 6))
        # Sem liberação do semestre, coordenadores não alteram; a administração sim.
        Semestre.objects.filter(pk=self.sem.pk).update(preenchimento_liberado=False)
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get(reverse("plano_remanejamento"), {"semestre": self.sem.id}).context["plano"].sugestoes, [])
        self.client.force_login(self.admin)
        self.assertEqual(len(self.client.get(reverse("plano_remanejamento")).context["plano"].sugestoes), 5)


class AplicacaoTests(Base):
    def setUp(self):
        self.a = self.comp("A", coord=self.coord, profs=[self.p1, self.p2])
        self.b = self.comp("B", turma="B", coord=self.coord2, profs=[self.p1, self.p3])
        self.ea = self.enc(self.a, prof=self.p1)
        self.eb = self.enc(self.b, ini=15, fim=17, prof=self.p1)
        self.ctx = self.contexto()
        (self.conflito,) = sg.conflitos_do_semestre(self.ctx)
        self.registro = self.ativos().get()

    def sugestao(self, tipo, comp):
        pode = lambda c: c.id == comp.id
        sugestoes, _ = sg.sugerir(self.ctx, self.conflito, pode, pode, limite=30)
        return next(s for s in sugestoes if s.acao.tipo == tipo)

    def estado(self):
        return list(Encontro.objects.order_by("id").values_list("data", "hora_inicio", "hora_fim", "professor", "versao"))

    def test_coordenador_aplica_movimento_no_proprio_componente(self):
        s = self.sugestao("MOVER", self.a)
        url = reverse("conflito_detalhe", args=[self.registro.pk])
        self.client.force_login(self.coord)
        pagina = self.client.get(url)
        self.assertContains(pagina, "Sugestões de remanejamento")
        self.assertContains(pagina, s.descricao)
        self.assertRedirects(self.postar([s], proximo=url), url)
        self.ea.refresh_from_db()
        self.assertEqual((self.ea.data, self.ea.hora_inicio, self.ea.excepcional, self.ea.versao, self.ea.atualizado_por),
                         (s.acao.data, s.acao.inicio, True, 2, self.coord))
        self.registro.refresh_from_db()
        self.assertEqual(self.registro.status, "RESOLVIDO")
        campos = set(HistoricoAlteracao.objects.filter(componente=self.a).values_list("campo", flat=True))
        self.assertLessEqual({"Data", "Remanejamento sugerido"}, campos)
        self.assertNotContains(self.client.get(url), "Sugestões de remanejamento")      # conflito resolvido

    def test_isolamento_coordenador_nao_altera_componente_alheio(self):
        antes = self.estado()
        for tipo in ("MOVER", "TROCAR_DOCENTE"):
            resposta = self.postar([self.sugestao(tipo, self.b)], self.coord)             # B é de coord2
            self.assertEqual(resposta.status_code, 403, tipo)
        # Na tela, as ações sobre B aparecem apenas como alternativas, sem botão de aplicar.
        contexto = self.client.get(reverse("conflito_detalhe", args=[self.registro.pk])).context["sugestoes"]
        self.assertEqual({s.acao.componente_id for s in contexto["aplicaveis"]}, {self.a.id})
        self.assertEqual({s.acao.componente_id for s in contexto["outras"]}, {self.b.id})
        self.assertEqual(self.estado(), antes)
        self.assertEqual(self.ativos().count(), 1)

    def test_professor_vinculado_troca_docente_mas_nao_move_aula(self):
        antes = self.estado()
        self.assertEqual(self.postar([self.sugestao("MOVER", self.a)], self.p2).status_code, 403)
        self.assertEqual(self.postar([self.sugestao("TROCAR_DOCENTE", self.a)], self.p3).status_code, 403)   # sem vínculo com A
        self.assertEqual(self.estado(), antes)
        troca = self.sugestao("TROCAR_DOCENTE", self.a)
        self.assertEqual(self.postar([troca], self.p2).status_code, 302)                   # vinculado a A
        self.ea.refresh_from_db()
        self.assertEqual(self.ea.professor_id, troca.acao.professor_id)
        self.assertEqual(self.ativos().count(), 0)

    def test_anonimo_e_metodo_get_sao_recusados(self):
        s = self.sugestao("MOVER", self.a)
        resposta = self.postar([s])
        self.assertEqual((resposta.status_code, resposta["Location"].split("?")[0]), (302, reverse("login")))
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get(reverse("aplicar_sugestoes")).status_code, 405)
        self.assertEqual(self.ativos().count(), 1)

    def test_sugestao_desatualizada_e_recusada(self):
        s = self.sugestao("MOVER", self.a)
        self.client.force_login(self.coord)
        self.client.post(f"/api/encontros/{self.ea.id}/", {"campos": {"conteudo": "Outra coisa"}}, content_type="application/json")
        antes = self.estado()
        resposta = self.postar([s], proximo="/conflitos/")
        self.assertIn("alterados depois", str(list(self.client.get(resposta["Location"]).context["messages"])[0]))
        self.assertEqual(self.estado(), antes)

    def test_dados_adulterados_sao_reverificados_no_servidor(self):
        self.client.force_login(self.admin)
        base = self.sugestao("MOVER", self.a).carga
        ocupado = self.comp("Ocupado", turma="Z")
        self.enc(ocupado, QUA, 7, 22, prof=self.p1)
        DataBloqueada.objects.create(semestre=self.sem, data=TER, descricao="Feriado")
        versao = lambda e: Encontro.objects.get(pk=e.pk).versao
        adulteradas = {
            "docente ocupado": {**base, "data": QUA.isoformat()},
            "data bloqueada": {**base, "data": TER.isoformat()},
            "fora do período": {**base, "data": "2027-03-15"},
            "duração alterada": {**base, "data": QUI.isoformat(), "fim": "19:00"},
            "fora da janela": {**base, "data": QUI.isoformat(), "inicio": "05:00", "fim": "07:00"},
            "não resolve nada": {**base, "data": SEG.isoformat(), "inicio": "14:30", "fim": "16:30"},
            "componente trocado": {**base, "componente": self.b.id},
            "encontro de outro componente": {**base, "encontros": [[self.eb.id, versao(self.eb)]]},
            "substituto sem vínculo": {"tipo": "TROCAR_DOCENTE", "componente": self.a.id,
                                       "encontros": [[self.ea.id, 1]], "professor_id": self.p3.id},
            "substituto administrador": {"tipo": "TROCAR_DOCENTE", "componente": self.a.id,
                                         "encontros": [[self.ea.id, 1]], "professor_id": self.admin.id},
            "tipo desconhecido": {**base, "tipo": "APAGAR"},
            "sem encontros": {**base, "encontros": []},
            "campos ausentes": {"tipo": "MOVER"},
        }
        sincronizar_conflitos()
        antes = self.estado()
        for nome, carga in adulteradas.items():
            with self.subTest(nome):
                resposta = self.postar([carga])
                self.assertEqual(resposta.status_code, 302)
                mensagens = [str(m) for m in self.client.get(resposta["Location"]).context["messages"]]
                self.assertTrue(any("Nada foi alterado" in m or "inválida" in m for m in mensagens), mensagens)
                self.assertEqual(self.estado(), antes)
        for corpo in ("", "{}", "[]", "[1]", "não é json"):
            resposta = self.client.post(reverse("aplicar_sugestoes"), {"acoes": corpo})
            self.assertRedirects(resposta, reverse("conflitos"))
        self.assertEqual(self.estado(), antes)

    def test_plano_e_tudo_ou_nada_e_redirecionamento_externo_e_ignorado(self):
        self.client.force_login(self.admin)
        boa = self.sugestao("MOVER", self.a).carga
        ruim = {**self.sugestao("MOVER", self.b).carga, "data": "2027-03-15"}
        antes = self.estado()
        resposta = self.postar([boa, ruim], proximo="https://malicioso.example/")
        self.assertRedirects(resposta, reverse("conflitos"))
        self.assertEqual(self.estado(), antes)                  # a ação válida também foi desfeita
        self.assertFalse(HistoricoAlteracao.objects.exists())

    def test_cronograma_aprovado_recusa_aplicacao(self):
        s = self.sugestao("MOVER", self.a)
        Componente.objects.filter(pk=self.a.pk).update(situacao="APROVADO")
        antes = self.estado()
        self.postar([s], self.admin)
        self.assertEqual(self.estado(), antes)

    def test_detalhe_de_conflitos_de_turma_e_calendario_traz_sugestoes(self):
        d = self.comp("D", turma="A", coord=self.coord)
        self.enc(d, SEG, 15, 17)
        DataBloqueada.objects.create(semestre=self.sem, data=QUA, descricao="Feriado")
        self.enc(d, QUA)
        sincronizar_conflitos()
        self.client.force_login(self.coord)
        for tipo in ("TURMA", "CALENDARIO"):
            registro = self.ativos().get(tipo=tipo)
            resposta = self.client.get(reverse("conflito_detalhe", args=[registro.pk]))
            sugestoes = resposta.context["sugestoes"]["aplicaveis"]
            self.assertTrue(sugestoes, tipo)
            self.assertEqual({s.acao.tipo for s in sugestoes}, {"MOVER"})
            self.assertContains(resposta, "Verificado: elimina")
            self.assertRedirects(self.postar([sugestoes[0]], proximo=f"/conflitos/{registro.pk}/"), f"/conflitos/{registro.pk}/")
            registro.refresh_from_db()
            self.assertEqual(registro.status, "RESOLVIDO", tipo)
