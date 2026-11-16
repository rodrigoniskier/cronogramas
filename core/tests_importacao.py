"""Testes da importação de planilhas: leitura, mapeamento, validação, aplicação e isolamento."""
from datetime import date, time
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from . import importacao as imp
from .models import (
    Componente, Conflito, DataBloqueada, Encontro, HistoricoAlteracao, HorarioSemanal, Importacao, Semestre, Usuario,
)
from .services import gerar_encontros

CAB = imp.CABECALHOS_MODELO
SEG, QUA = date(2027, 2, 15), date(2027, 2, 17)


def linha(comp="Farmaco", turma="A", dia=SEG, horario="08h-10h", docente="p1@t.example", conteudo="Aula", periodo="4º", tipo="T"):
    return (comp, "F-01", periodo, turma, "Manhã", dia, horario, conteudo, tipo, "Expositiva", "Quadro", "TODOS", docente, "", "Sala 1")


def arquivo(linhas, cabecalhos=CAB, nome="cronograma.xlsx", titulo="CRONOGRAMA DE AULAS"):
    return SimpleUploadedFile(nome, imp.gerar_planilha(linhas, cabecalhos, titulo))


class ConversaoTests(SimpleTestCase):
    def test_datas(self):
        for texto in ("15/02/2027", "15/2/27", "15-02-2027", "15.02.2027", "2027-02-15", "2027-02-15T00:00"):
            self.assertEqual(imp.ler_data(texto), SEG, texto)
        for texto in ("31/02/2027", "amanhã", "2027/02/15", ""):
            with self.assertRaises(ValueError, msg=texto):
                imp.ler_data(texto)

    def test_horas_e_horarios(self):
        casos = {"13:00": time(13), "13h": time(13), "13h30": time(13, 30), "8H": time(8), "13:30:00": time(13, 30),
                 "0.5": time(12), "0,3125": time(7, 30), "1900-01-01T13:30": time(13, 30)}
        for texto, esperado in casos.items():
            self.assertEqual(imp.ler_hora(texto), esperado, texto)
        for texto in ("25:00", "13:5", "tarde", ""):
            with self.assertRaises(ValueError, msg=texto):
                imp.ler_hora(texto)
        for texto in ("13h-15h30", "13:00 às 15:30", "13h a 15h30", "13:00–15:30", "13h até 15h30"):
            self.assertEqual(imp.ler_horario(texto), (time(13), time(15, 30)), texto)
        with self.assertRaises(ValueError):
            imp.ler_horario("13h")

    def test_colunas_sem_titulo_e_cabecalho_nao_reconhecido(self):
        cabecalhos, linhas = imp.ler_planilha(arquivo([("x", "y", "", "w", "")], cabecalhos=("Matéria", "Classe")))
        self.assertEqual(cabecalhos, ["Matéria", "Classe", "", ""])     # título solto ignorado; colunas com dados preservadas
        self.assertEqual(linhas, [{"n": 4, "c": ["x", "y", "", "w"]}])

    def test_leitura_localiza_cabecalho_abaixo_de_titulos(self):
        cabecalhos, linhas = imp.ler_planilha(arquivo([linha(), linha(dia=QUA)]))
        self.assertEqual(tuple(cabecalhos), CAB)
        self.assertEqual([l["n"] for l in linhas], [4, 5])          # título, linha vazia, cabeçalho, dados
        self.assertEqual(linhas[0]["c"][5], "2027-02-15")           # data do Excel vira texto ISO
        mapa = imp.sugerir_mapeamento(cabecalhos)
        self.assertEqual(imp.erros_do_mapeamento(mapa), [])
        self.assertEqual((mapa["componente"], mapa["docente"], mapa["horario"]), (0, 12, 6))

    def test_mapeamento_reconhece_variacoes_de_titulo(self):
        mapa = imp.sugerir_mapeamento(["DISCIPLINA", "Turma ", "dia", "Início", "Término", "PROFESSOR(A)", "Conteúdo Programático", "?"])
        self.assertEqual(mapa, {"componente": 0, "turma": 1, "data": 2, "inicio": 3, "fim": 4, "docente": 5, "conteudo": 6})
        self.assertTrue(imp.erros_do_mapeamento({"componente": 0, "turma": 1}))
        self.assertTrue(imp.erros_do_mapeamento({"componente": 0, "turma": 0, "data": 2, "horario": 3}))
        self.assertEqual(imp.limpar_mapeamento({"componente": 9, "x": 0, "turma": True, "data": 1}, 3), {"data": 1})

    def test_arquivos_invalidos(self):
        casos = {
            "extensão": SimpleUploadedFile("dados.csv", b"a,b"),
            "corrompido": SimpleUploadedFile("x.xlsx", b"isto nao e um zip"),
            "vazio": arquivo([], cabecalhos=(), titulo=None),
            "sem dados": arquivo([]),
        }
        for nome, arq in casos.items():
            with self.subTest(nome), self.assertRaises(imp.ErroImportacao):
                imp.ler_planilha(arq)
        with patch.object(imp, "MAX_LINHAS", 2), self.assertRaises(imp.ErroImportacao):
            imp.ler_planilha(arquivo([linha(dia=date(2027, 2, d)) for d in (1, 2, 3)]))
        with patch.object(imp, "MAX_BYTES", 100), self.assertRaises(imp.ErroImportacao):
            imp.ler_planilha(arquivo([linha()]))
        with patch.object(imp, "MAX_DESCOMPACTADO", 100), self.assertRaises(imp.ErroImportacao):
            imp.ler_planilha(arquivo([linha()]))


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = Usuario.objects.create_user
        cls.admin = Usuario.objects.create_superuser("admin@t.example", "senha-Teste-123", nome="Admin")
        cls.coord = U("coord@t.example", "senha-Teste-123", nome="Coord Um", perfil="COORD")
        cls.coord2 = U("coord2@t.example", "senha-Teste-123", nome="Coord Dois", perfil="COORD")
        cls.p1 = U("p1@t.example", "senha-Teste-123", nome="Ana Lima", perfil="PROF", username="ana.lima")
        cls.p2 = U("p2@t.example", "senha-Teste-123", nome="Bruno Sá", perfil="PROF")
        cls.sem = Semestre.objects.create(
            nome="2027.1", data_inicio=date(2027, 2, 1), data_fim=date(2027, 6, 30), preenchimento_liberado=True
        )
        cls.outro_sem = Semestre.objects.create(nome="2027.2", data_inicio=date(2027, 8, 1), data_fim=date(2027, 12, 15))

    def setUp(self):
        self.client.force_login(self.coord)

    def enviar(self, linhas, cabecalhos=CAB, semestre=None, **extra):
        return self.client.post(reverse("importar"), {"arquivo": arquivo(linhas, cabecalhos), "semestre": (semestre or self.sem).id, **extra})

    def conferir(self, linhas, cabecalhos=CAB, **extra):
        """Envia a planilha e devolve (importação, análise exibida na conferência)."""
        resposta = self.enviar(linhas, cabecalhos, **extra)
        self.assertEqual(resposta.status_code, 302, getattr(resposta, "context", None) and resposta.context["form"].errors)
        importacao = Importacao.objects.latest("id")
        return importacao, self.client.get(resposta["Location"]).context["analise"]

    def aplicar(self, importacao):
        return self.client.post(reverse("importacao_detalhe", args=[importacao.pk]), {"acao": "aplicar"})

    def existente(self, nome="Anatomia", coord=None, turma="A", ini=time(8), fim=time(10)):
        comp = Componente.objects.create(
            nome=nome, turma=turma, periodo="4º", semestre=self.sem, coordenador=coord or self.coord,
            data_inicio=date(2027, 2, 15), data_fim=date(2027, 2, 28),
        )
        HorarioSemanal.objects.create(componente=comp, dia_semana=0, hora_inicio=ini, hora_fim=fim)
        gerar_encontros(comp)
        return comp


class FluxoTests(Base):
    def test_importa_componentes_novos(self):
        linhas = [linha(dia=d) for d in (SEG, date(2027, 2, 22), date(2027, 3, 1))]
        linhas += [linha(dia=QUA, horario="14h-16h", docente="ana.lima")]            # excepcional, docente por usuário
        linhas += [linha(turma="B", dia=SEG, horario="10:00 às 12:00", docente="Bruno Sá", tipo="Prática")]
        importacao, analise = self.conferir(linhas)
        self.assertTrue(analise.ok, analise.erros)
        self.assertEqual(analise.contagem, {"linhas": 5, "criar": 5, "atualizar": 0, "sem_alteracao": 0,
                                            "componentes_novos": 2, "componentes_existentes": 0, "conflitos": 0})
        self.assertFalse(Componente.objects.exists())                 # conferir não grava nada
        self.assertRedirects(self.aplicar(importacao), reverse("importacao_detalhe", args=[importacao.pk]))

        a = Componente.objects.get(turma="A")
        self.assertEqual((a.nome, a.coordenador, a.periodo, a.codigo, a.turno, a.situacao), ("Farmaco", self.coord, "4º", "F-01", "MANHA", "RASCUNHO"))
        self.assertEqual((a.data_inicio, a.data_fim), (SEG, date(2027, 3, 1)))
        self.assertEqual([(h.dia_semana, h.hora_inicio) for h in a.horarios.all()], [(0, time(8))])   # só o horário que se repete
        self.assertEqual(list(a.professores.all()), [self.p1])
        encontros = list(a.encontros.all())
        self.assertEqual([e.excepcional for e in encontros], [False, True, False, False])
        e = encontros[0]
        self.assertEqual((e.professor, e.conteudo, e.tipo, e.ch, e.local, e.atualizado_por), (self.p1, "Aula", "T", "2h", "Sala 1", self.coord))
        b = Componente.objects.get(turma="B")
        self.assertEqual((b.encontros.get().professor, b.encontros.get().tipo), (self.p2, "P"))
        self.assertTrue(HistoricoAlteracao.objects.filter(componente=a, campo="Importação de planilha").exists())

        importacao.refresh_from_db()
        self.assertEqual((importacao.status, importacao.linhas, importacao.resumo["criados"]), ("APLICADA", [], 5))
        self.assertContains(self.client.get(reverse("importacao_detalhe", args=[importacao.pk])), "Abrir cronograma")
        # Segundo envio do formulário não aplica de novo.
        self.aplicar(importacao)
        self.assertEqual(Encontro.objects.count(), 5)
        # O componente importado abre normalmente no editor e no cadastro.
        self.assertEqual(self.client.get(reverse("cronograma", args=[a.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("componente_editar", args=[a.pk])).status_code, 200)

    def test_previa_e_registro_dos_tres_tipos_de_conflito(self):
        anatomia = self.existente()                                   # Turma A, 4º, segundas 08–10
        Encontro.objects.filter(componente=anatomia, data=SEG).update(professor=self.p2, conteudo="x")
        DataBloqueada.objects.create(semestre=self.sem, data=date(2027, 2, 16), descricao="Carnaval")
        linhas = [
            linha(turma="A", dia=SEG, horario="09h-11h", docente="p1@t.example"),       # TURMA × Anatomia
            linha(turma="B", dia=SEG, horario="09h-11h", docente="p2@t.example"),       # DOCENTE × Anatomia
            linha(turma="B", dia=date(2027, 2, 16), docente=""),                        # CALENDÁRIO
            linha(turma="B", dia=QUA, docente="p1@t.example"),                          # sem conflito
        ]
        importacao, analise = self.conferir(linhas)
        self.assertTrue(analise.ok, analise.erros)
        self.assertEqual(sorted(c["tipo"] for c in analise.conflitos), ["CALENDARIO", "DOCENTE", "TURMA"])
        self.assertIn("linha 4", " ".join(c["texto"] for c in analise.conflitos))
        self.assertFalse(Conflito.objects.exists())
        self.aplicar(importacao)
        self.assertEqual(sorted(Conflito.objects.filter(status="ATIVO").values_list("tipo", flat=True)),
                         ["CALENDARIO", "DOCENTE", "TURMA"])
        importacao.refresh_from_db()
        self.assertEqual(importacao.resumo["conflitos_por_tipo"], {"CALENDARIO": 1, "DOCENTE": 1, "TURMA": 1})

    def test_mapeamento_manual_de_colunas_nao_reconhecidas(self):
        cabecalhos = ("Matéria", "Classe", "Quando", "Das", "Até", "Quem", "Ignorar")
        linhas = [("Bioquímica", "A", "15/02/2027", "08:00", "10:00", "p1@t.example", "zzz")]
        importacao, analise = self.conferir(linhas, cabecalhos)
        self.assertFalse(analise.ok)
        self.assertEqual({e["campo"] for e in analise.erros}, {"Mapeamento"})
        url = reverse("importacao_detalhe", args=[importacao.pk])
        # A mesma coluna de destino duas vezes é recusada e o mapeamento anterior permanece.
        self.client.post(url, {"acao": "mapear", "col_0": "componente", "col_1": "componente"})
        importacao.refresh_from_db()
        self.assertEqual(importacao.mapeamento, {})
        self.client.post(url, {"acao": "mapear", "col_0": "componente", "col_1": "turma", "col_2": "data",
                               "col_3": "inicio", "col_4": "fim", "col_5": "docente", "col_6": "", "col_99": "local"})
        analise = self.client.get(url).context["analise"]
        self.assertTrue(analise.ok, analise.erros)
        self.aplicar(importacao)
        e = Encontro.objects.get()
        self.assertEqual((e.componente.nome, e.data, e.hora_inicio, e.hora_fim, e.professor), ("Bioquímica", SEG, time(8), time(10), self.p1))

    def test_reimportar_nao_duplica_e_preenche_encontros_vazios(self):
        anatomia = self.existente()                                    # encontros vazios em 15/02 e 22/02
        linhas = [linha(comp="anatomia", dia=SEG, conteudo="Osteologia"), linha(comp="anatomia", dia=QUA, conteudo="Extra")]
        importacao, analise = self.conferir(linhas)
        self.assertEqual((analise.contagem["atualizar"], analise.contagem["criar"], analise.contagem["componentes_existentes"]), (1, 1, 1))
        self.aplicar(importacao)
        self.assertEqual(Componente.objects.count(), 1)
        self.assertEqual(anatomia.encontros.count(), 3)
        preenchido = anatomia.encontros.get(data=SEG)
        self.assertEqual((preenchido.professor, preenchido.conteudo, preenchido.versao), (self.p1, "Osteologia", 2))
        self.assertIn(self.p1, anatomia.professores.all())
        # Mesma planilha de novo: nada a fazer.
        importacao, analise = self.conferir(linhas)
        self.assertEqual((analise.contagem["sem_alteracao"], analise.contagem["criar"], analise.contagem["atualizar"]), (2, 0, 0))
        self.aplicar(importacao)
        self.assertEqual(anatomia.encontros.count(), 3)
        # Segundo docente na mesma aula: nova linha, como no editor.
        importacao, analise = self.conferir([linha(comp="Anatomia", dia=SEG, docente="p2@t.example")])
        self.assertEqual(analise.contagem["criar"], 1)
        self.aplicar(importacao)
        self.assertEqual(anatomia.encontros.filter(data=SEG).count(), 2)

    def test_modelo_para_download_e_importavel(self):
        resposta = self.client.get(reverse("importacao_modelo"))
        self.assertEqual(resposta.status_code, 200)
        cabecalhos, linhas = imp.ler_planilha(SimpleUploadedFile("modelo.xlsx", resposta.content))
        self.assertEqual(imp.erros_do_mapeamento(imp.sugerir_mapeamento(cabecalhos)), [])
        self.assertEqual(len(linhas), 1)

    def test_planilhas_de_exemplo_do_repositorio(self):
        from .management.commands.gerar_exemplos import linhas_com_erros, linhas_validas

        Usuario.objects.create_user("prof8@demo.cronomed.example", "senha-Teste-123", nome="P8", perfil="PROF")
        importacao, analise = self.conferir(linhas_com_erros())
        self.assertEqual(sorted(e["linha"] for e in analise.erros), [5, 6, 7, 8, 9, 10, 11])
        self.assertEqual(self.aplicar(importacao).status_code, 302)
        self.assertFalse(Componente.objects.exists())
        for login in ("prof4", "prof7"):
            Usuario.objects.create_user(f"{login}@demo.cronomed.example", "senha-Teste-123", nome=login, perfil="PROF")
        _, analise = self.conferir(linhas_validas())
        self.assertTrue(analise.ok, analise.erros)
        self.assertEqual((analise.contagem["criar"], analise.contagem["componentes_novos"]), (15, 2))


class ValidacaoTests(Base):
    def erros(self, linhas, cabecalhos=CAB, **extra):
        importacao, analise = self.conferir(linhas, cabecalhos, **extra)
        self.assertFalse(analise.ok)
        # Com erro, confirmar não grava nada.
        antes = list(Encontro.objects.values_list("id", "versao", "professor"))
        self.aplicar(importacao)
        self.assertEqual(list(Encontro.objects.values_list("id", "versao", "professor")), antes)
        importacao.refresh_from_db()
        self.assertTrue(importacao.pendente)
        return [(e["linha"], e["campo"]) for e in analise.erros], " | ".join(e["mensagem"] for e in analise.erros)

    def test_cada_linha_invalida_e_apontada(self):
        Usuario.objects.create_user("inativo@t.example", "senha-Teste-123", nome="Inativo", perfil="PROF", is_active=False)
        Usuario.objects.create_user("homonimo@t.example", "senha-Teste-123", nome="ana lima", perfil="PROF")
        linhas = [
            linha(),                                             # 4: válida
            linha(comp=""),                                      # 5
            linha(turma=" "),                                    # 6
            linha(dia="31/02/2027"),                             # 7
            linha(dia=date(2027, 7, 1)),                         # 8: fora do semestre
            linha(dia=QUA, horario="10h-08h"),                   # 9
            linha(dia=QUA, horario="manhã"),                     # 10
            linha(dia=QUA, docente="ninguem@t.example"),         # 11
            linha(dia=QUA, docente="inativo@t.example"),         # 12
            linha(dia=QUA, docente="Ana Lima"),                  # 13: nome ambíguo
            linha(dia=QUA, tipo="X"),                            # 14
            linha(),                                             # 15: repetida
            linha(dia=QUA, periodo="5º"),                        # 16: diverge do cadastro informado antes
            linha(comp="C" * 151, dia=QUA),                      # 17
            linha(dia=QUA, horario=""),                          # 18
            linha(dia=QUA, docente="admin@t.example"),           # 19: administrador não é docente
        ]
        pares, texto = self.erros(linhas)
        self.assertEqual([n for n, _ in pares], list(range(5, 20)))
        self.assertEqual(dict(pares)[13], "Docente (e-mail, usuário ou nome)")
        for trecho in ("obrigatório", "Data inválida", "fora do semestre", "posterior ao início", "Horário inválido",
                       "não encontrado", "Há 2 docentes", "Tipo inválido", "Linha repetida", "diverge", "mais de 150", "não informado"):
            self.assertIn(trecho, texto)

    def test_erros_de_cadastro_do_componente(self):
        cabecalhos = CAB + ("Coordenador", "Semestre", "CH total")
        base = linha()
        pares, texto = self.erros([base + ("coord2@t.example", "2027.2", "muitas")], cabecalhos)
        self.assertEqual({c for _, c in pares}, {"Semestre (conferência)", "CH total (h/a)"})
        pares, texto = self.erros([base + ("coord2@t.example", "2027.1", "60h")], cabecalhos)
        self.assertIn("sob a sua coordenação", texto)

    def test_componente_de_outro_coordenador_aprovado_ou_nao_liberado(self):
        alheio = self.existente("Alheio", coord=self.coord2)
        aprovado = self.existente("Aprovado")
        Componente.objects.filter(pk=aprovado.pk).update(situacao="APROVADO")
        _, texto = self.erros([linha(comp="Alheio", dia=SEG), linha(comp="Aprovado", dia=SEG)])
        self.assertIn("coordenado por outra pessoa", texto)
        self.assertIn("aprovado/publicado", texto)
        self.assertFalse(alheio.encontros.exclude(professor=None).exists())
        Componente.objects.all().delete()
        self.existente("Meu")
        Semestre.objects.filter(pk=self.sem.pk).update(preenchimento_liberado=False)
        importacao, analise = self.conferir([linha(comp="Meu", dia=SEG)])
        self.assertIn("não foi liberado", analise.erros[0]["mensagem"])

    def test_envio_recusa_arquivo_invalido_sem_criar_importacao(self):
        for arq in (SimpleUploadedFile("planilha.xls", b"x"), SimpleUploadedFile("planilha.xlsx", b"PK\x03\x04lixo")):
            resposta = self.client.post(reverse("importar"), {"arquivo": arq, "semestre": self.sem.id})
            self.assertEqual(resposta.status_code, 200)
            self.assertIn("arquivo", resposta.context["form"].errors)
        resposta = self.client.post(reverse("importar"), {"semestre": self.sem.id})
        self.assertIn("arquivo", resposta.context["form"].errors)
        self.assertFalse(Importacao.objects.exists())

    def test_textos_da_planilha_sao_exibidos_como_texto(self):
        importacao, analise = self.conferir([linha(comp="<script>alert(1)</script>", docente="=cmd|x")])
        resposta = self.client.get(reverse("importacao_detalhe", args=[importacao.pk]))
        self.assertNotContains(resposta, "<script>alert(1)</script>")
        self.assertContains(resposta, "&lt;script&gt;alert(1)&lt;/script&gt;")


class PermissaoTests(Base):
    def test_admin_define_coordenador_pela_planilha_ou_pelo_padrao(self):
        self.client.force_login(self.admin)
        importacao, analise = self.conferir([linha()])
        self.assertIn("informe o coordenador", analise.erros[0]["mensagem"])
        importacao, analise = self.conferir([linha()], coordenador_padrao=self.coord2.id)
        self.assertTrue(analise.ok)
        self.aplicar(importacao)
        self.assertEqual(Componente.objects.get().coordenador, self.coord2)
        cabecalhos = CAB + ("Coordenador (e-mail)",)
        importacao, analise = self.conferir([linha(turma="B") + ("COORD@t.example",)], cabecalhos, coordenador_padrao=self.coord2.id)
        self.aplicar(importacao)
        self.assertEqual(Componente.objects.get(turma="B").coordenador, self.coord)
        _, analise = self.conferir([linha(turma="C") + ("p1@t.example",)], cabecalhos)
        self.assertIn("não encontrado entre os coordenadores", analise.erros[0]["mensagem"])

    def test_coordenador_importa_antes_da_liberacao_apenas_componentes_novos(self):
        Semestre.objects.filter(pk=self.sem.pk).update(preenchimento_liberado=False)
        importacao, analise = self.conferir([linha()])
        self.assertTrue(analise.ok)                                   # mesma regra do cadastro manual de componente

    def test_professor_e_anonimo_nao_importam(self):
        importacao, _ = self.conferir([linha()])
        urls = [reverse("importar"), reverse("importacao_modelo"), reverse("importacao_detalhe", args=[importacao.pk])]
        self.client.force_login(self.p1)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.enviar([linha()]).status_code, 403)
        self.assertEqual(self.aplicar(importacao).status_code, 403)
        self.assertNotContains(self.client.get(reverse("dashboard")), reverse("importar"))
        self.client.logout()
        for url in urls:
            self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
        self.assertFalse(Componente.objects.exists())

    def test_importacao_e_visivel_apenas_a_quem_enviou(self):
        importacao, _ = self.conferir([linha()])
        url = reverse("importacao_detalhe", args=[importacao.pk])
        for outro in (self.coord2, self.admin):
            self.client.force_login(outro)
            self.assertEqual(self.client.get(url).status_code, 404)
            for acao in ("aplicar", "descartar", "mapear"):
                self.assertEqual(self.client.post(url, {"acao": acao}).status_code, 404)
            self.assertNotContains(self.client.get(reverse("importar")), importacao.arquivo_nome)
        self.assertFalse(Componente.objects.exists())
        importacao.refresh_from_db()
        self.assertTrue(importacao.pendente)
        # Novo envio descarta apenas os rascunhos do próprio usuário.
        self.client.force_login(self.coord2)
        self.conferir([linha(turma="Z")])
        self.assertEqual(Importacao.objects.filter(status="PENDENTE").count(), 2)
        self.client.force_login(self.coord)
        self.assertContains(self.client.get(reverse("importar")), importacao.arquivo_nome)
        self.assertRedirects(self.client.post(url, {"acao": "descartar"}), reverse("importar"))
        self.assertEqual(list(Importacao.objects.values_list("usuario", flat=True)), [self.coord2.id])

    def test_envio_exige_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.coord)
        resposta = cliente.post(reverse("importar"), {"arquivo": arquivo([linha()]), "semestre": self.sem.id})
        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(Importacao.objects.exists())
