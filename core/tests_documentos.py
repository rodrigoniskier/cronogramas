"""Testes da leitura de DOCX e PDF e do cruzamento de vários arquivos de formatos diferentes."""
import builtins
from datetime import date, time
from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from . import documentos as doc
from . import exports
from . import importacao as imp
from . import sugestoes as sg
from .models import Componente, Conflito, DataBloqueada, Encontro, HorarioSemanal, Importacao, Semestre, Usuario
from .services import sincronizar_conflitos

SEG, TER, QUA = date(2027, 3, 1), date(2027, 3, 2), date(2027, 3, 3)


def enviado(nome, dados):
    return SimpleUploadedFile(nome, dados)


def pdf_simples(desenhar):
    from reportlab.pdfgen import canvas

    saida = BytesIO()
    c = canvas.Canvas(saida)
    desenhar(c)
    c.save()
    return saida.getvalue()


class IdentificacaoTests(SimpleTestCase):
    def ident(self, texto):
        achado = {}
        doc._ler_identificacao(texto, achado)
        return achado

    def test_rotulos_em_celulas_separadas_e_em_uma_unica_linha(self):
        self.assertEqual(self.ident("2. COMPONENTE CURRICULAR: Anatomia Humana II"), {"componente": "Anatomia Humana II"})
        self.assertEqual(self.ident("CH: 60h/A"), {"carga_horaria": "60h/A"})
        self.assertEqual(self.ident("Teórica: 30h/A"), {"ch_teorica": "30h/A"})
        self.assertEqual(self.ident("PERÍODO: —"), {"periodo": ""})
        linha = "3. SEMESTRE: 2027.1 PERÍODO: 4º TURMA: A · Tarde"
        self.assertEqual(self.ident(linha), {"semestre": "2027.1", "periodo": "4º", "turma": "A", "turno": "Tarde"})
        self.assertEqual(self.ident("Curso: Medicina   Coordenadora: Profa. Ana Lima"),
                         {"curso": "Medicina", "coordenador": "Profa. Ana Lima"})
        self.assertEqual(self.ident("A turma A terá aula prática no laboratório."), {})

    def test_titulos_de_coluna_quebrados_no_meio_da_palavra(self):
        self.assertEqual(doc._campo_do_titulo("Tipo\ns"), "tipo")
        self.assertEqual(doc._campo_do_titulo("CONTEÚDO"), "conteudo")
        self.assertIsNone(doc._campo_do_titulo("Assinatura"))

    def test_tabela_sem_cabecalho_repetido_continua_a_anterior_e_feriado_e_ignorado(self):
        blocos = [
            ("texto", "COMPONENTE CURRICULAR: Bioquímica"), ("texto", "TURMA: B"),
            ("tabela", [["DATA", "HORÁRIO", "CONTEÚDO", "Tipos", "DOCENTE"],
                        ["01/03", "08h-10h", "Água", "T", "Ana"], [None, None, None, None, "Bruno"],
                        ["02/03", "08h-10h", "Feriado - Carnaval", "-", ""]]),
            ("tabela", [["03/03", "08h-10h", "pH", "P", "Ana"], ["", "", "", "", ""], ["", "", "solto", "", ""]]),
        ]
        cabecalhos, linhas, avisos = doc._extrair(blocos, eh_pdf=True)
        self.assertEqual(cabecalhos, ["Componente curricular", "Turma", "Data", "Horário", "Conteúdo", "Tipo", "Docente"])
        self.assertEqual([l["c"][2:] for l in linhas], [
            ["01/03", "08h-10h", "Água", "T", "Ana"], ["01/03", "08h-10h", "Água", "T", "Bruno"], ["03/03", "08h-10h", "pH", "P", "Ana"],
        ])
        self.assertEqual([l["n"] for l in linhas], [1, 2, 4])
        self.assertEqual(len(avisos), 2)

    def test_dois_cronogramas_no_mesmo_arquivo(self):
        tabela = lambda dia: ("tabela", [["DATA", "HORÁRIO", "DOCENTE"], [dia, "08h-10h", "Ana"]])
        blocos = [("texto", "COMPONENTE CURRICULAR: Um"), ("texto", "TURMA: A"), ("texto", "PERÍODO: 2º"), tabela("01/03"),
                  ("texto", "COMPONENTE CURRICULAR: Dois"), ("texto", "TURMA: B"), tabela("02/03")]
        _, linhas, _ = doc._extrair(blocos, eh_pdf=False)
        self.assertEqual([l["c"][:3] for l in linhas], [["Um", "A", "2º"], ["Dois", "B", ""]])

    def test_data_sem_ano_usa_o_semestre(self):
        class Sem:
            data_inicio, data_fim = date(2026, 8, 1), date(2027, 1, 20)

        self.assertEqual(imp.ler_data("15/09", Sem), date(2026, 9, 15))
        self.assertEqual(imp.ler_data("10/01", Sem), date(2027, 1, 10))
        self.assertEqual(imp.ler_data("15/03", Sem), date(2026, 3, 15))      # fora do semestre: será apontada na validação
        for texto in ("31/02", "15/03"):
            with self.assertRaises(ValueError):
                imp.ler_data(texto) if texto == "15/03" else imp.ler_data(texto, Sem)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = Usuario.objects.create_user
        cls.admin = Usuario.objects.create_superuser("admin@t.example", "senha-Teste-123", nome="Admin")
        cls.coord = U("coord@t.example", "senha-Teste-123", nome="Carla Nunes", perfil="COORD")
        cls.coord2 = U("coord2@t.example", "senha-Teste-123", nome="Coord Dois", perfil="COORD")
        cls.p1 = U("p1@t.example", "senha-Teste-123", nome="Ana Lima", perfil="PROF")
        cls.p2 = U("p2@t.example", "senha-Teste-123", nome="Bruno Sá", perfil="PROF")
        cls.p3 = U("p3@t.example", "senha-Teste-123", nome="Célia Reis", perfil="PROF")
        cls.sem = Semestre.objects.create(
            nome="2027.1", data_inicio=date(2027, 2, 1), data_fim=date(2027, 6, 30), preenchimento_liberado=True
        )

    def setUp(self):
        self.client.force_login(self.coord)

    def componente(self, nome="Anatomia II", turma="A", periodo="2º", encontros=(), coord=None, dias=()):
        comp = Componente.objects.create(
            nome=nome, turma=turma, periodo=periodo, semestre=self.sem, coordenador=coord or self.coord, carga_horaria=60,
            ch_teorica=40, ch_pratica=20, data_inicio=date(2027, 3, 1), data_fim=date(2027, 3, 31), local_padrao="Sala 1",
        )
        for dia in dias:
            HorarioSemanal.objects.create(componente=comp, dia_semana=dia, hora_inicio=time(8), hora_fim=time(10))
        for dia, ini, fim, prof, conteudo in encontros:
            Encontro.objects.create(
                componente=comp, data=dia, hora_inicio=time(*ini), hora_fim=time(*fim), professor=prof, conteudo=conteudo,
                tipo="T" if conteudo else "", atividade="Aula expositiva dialogada" if conteudo else "", grupos="TODOS" if conteudo else "",
                ch="2h", local="Sala 1",
            )
        return comp

    def exportar(self, comp, formato, nome=None):
        linhas = exports.linhas_cronograma(comp)
        dados = (exports.gerar_docx if formato == "docx" else exports.gerar_pdf)(comp, linhas, False)
        return enviado(nome or f"{comp.nome} {comp.turma}.{formato}", dados)

    def enviar(self, arquivos, **extra):
        return self.client.post(reverse("importar"), {"arquivo": arquivos, "semestre": self.sem.id, **extra})

    def conferir(self, arquivos, **extra):
        resposta = self.enviar(arquivos, **extra)
        self.assertEqual(resposta.status_code, 302, getattr(resposta, "context", None) and resposta.context["form"].errors)
        importacao = Importacao.objects.latest("id")
        return importacao, self.client.get(resposta["Location"]).context["analise"]

    def acao(self, importacao, **dados):
        return self.client.post(reverse("importacao_detalhe", args=[importacao.pk]), dados)

    def analise(self, importacao):
        return self.client.get(reverse("importacao_detalhe", args=[importacao.pk])).context["analise"]


class LeituraTests(Base):
    def test_docx_e_pdf_exportados_pelo_sistema_sao_lidos_de_forma_identica(self):
        DataBloqueada.objects.create(semestre=self.sem, data=date(2027, 3, 8), descricao="Feriado local")
        comp = self.componente(dias=(0,), encontros=[
            (SEG, (8, 0), (10, 0), self.p1, "Introdução à anatomia com um título longo o bastante para quebrar a linha na célula"),
            (SEG, (8, 0), (10, 0), self.p2, "Introdução à anatomia com um título longo o bastante para quebrar a linha na célula"),
            (date(2027, 3, 15), (8, 0), (10, 0), self.p3, "Osteologia"),
            (date(2027, 3, 22), (15, 30), (18, 0), None, ""),                    # encontro ainda sem docente
        ])
        lidos = {f: imp.ler_arquivo(self.exportar(comp, f)) for f in ("docx", "pdf")}
        for formato, lido in lidos.items():
            with self.subTest(formato):
                self.assertEqual(lido.formato, formato)
                self.assertEqual(len(lido.linhas), 4)
                self.assertIn("feriado", lido.avisos[0])
                registro = dict(zip(lido.cabecalhos, lido.linhas[1]["c"]))      # segundo docente da mesma aula
                self.assertEqual(
                    {k: registro[k] for k in ("Componente curricular", "Turma", "Período", "Curso", "Semestre", "Coordenador",
                                              "CH total", "Data", "Horário", "Docente", "Tipo", "Grupos", "CH", "Local")},
                    {"Componente curricular": "Anatomia II", "Turma": "A", "Período": "2º", "Curso": "Medicina", "Semestre": "2027.1",
                     "Coordenador": "Carla Nunes", "CH total": "60h/A", "Data": "01/03", "Horário": "08h-10h", "Docente": "Bruno Sá",
                     "Tipo": "T", "Grupos": "TODOS", "CH": "2h", "Local": "Sala 1"},
                )
                self.assertTrue(registro["Conteúdo"].startswith("Introdução à anatomia com um título longo"))
                self.assertEqual(dict(zip(lido.cabecalhos, lido.linhas[3]["c"]))["Horário"], "15h30-18h")
        self.assertEqual(lidos["docx"].cabecalhos, lidos["pdf"].cabecalhos)
        self.assertEqual([l["c"] for l in lidos["docx"].linhas], [l["c"] for l in lidos["pdf"].linhas])
        self.assertNotEqual(lidos["docx"].sha256, lidos["pdf"].sha256)

    def test_pdf_de_varias_paginas_com_cabecalho_repetido(self):
        comp = self.componente(nome="Longo", encontros=[
            (date(2027, 3, 1 + i % 28), (7 + i // 28 * 3, 0), (9 + i // 28 * 3, 0), self.p1, f"Tema {i} com texto suficiente para ocupar mais de uma linha")
            for i in range(84)
        ])
        lido = imp.ler_arquivo(self.exportar(comp, "pdf"))
        self.assertEqual(len(lido.linhas), 84)
        self.assertEqual([l["n"] for l in lido.linhas], list(range(1, 85)))
        conteudo = lido.cabecalhos.index("Conteúdo")
        self.assertEqual({l["c"][conteudo].split(" com ")[0] for l in lido.linhas}, {f"Tema {i}" for i in range(84)})

    def test_arquivos_que_nao_podem_ser_lidos(self):
        from docx import Document

        sem_tabela = BytesIO()
        Document().save(sem_tabela)
        documento = Document()
        tabela = documento.add_table(rows=2, cols=2)
        tabela.cell(0, 0).text, tabela.cell(0, 1).text = "Item", "Valor"
        outra_tabela = BytesIO()
        documento.save(outra_tabela)
        casos = {
            "formato não aceito": enviado("cronograma.doc", b"x"),
            "sem extensão": enviado("cronograma", b"x"),
            "docx corrompido": enviado("a.docx", b"PK\x03\x04lixo"),
            "pdf corrompido": enviado("a.pdf", b"%PDF-1.4 lixo"),
            "docx sem tabela": enviado("vazio.docx", sem_tabela.getvalue()),
            "docx com outra tabela": enviado("outra.docx", outra_tabela.getvalue()),
            "pdf digitalizado": enviado("imagem.pdf", pdf_simples(lambda c: c.rect(50, 50, 200, 200, fill=1))),
            "pdf sem tabela": enviado("texto.pdf", pdf_simples(lambda c: c.drawString(72, 720, "Ata da reunião do colegiado"))),
        }
        esperado = {"pdf digitalizado": "não tem texto selecionável", "pdf sem tabela": "nenhuma tabela de cronograma",
                    "docx sem tabela": "nenhuma tabela de cronograma", "docx com outra tabela": "nenhuma tabela de cronograma",
                    "formato não aceito": "formato não aceito", "sem extensão": "formato não aceito"}
        for nome, arquivo in casos.items():
            with self.subTest(nome):
                with self.assertRaises(imp.ErroImportacao) as erro:
                    imp.ler_arquivo(arquivo)
                self.assertIn(arquivo.name, str(erro.exception))
                self.assertIn(esperado.get(nome, "não foi possível ler"), str(erro.exception))
        for nome in ("pdf digitalizado", "formato não aceito"):
            casos[nome].seek(0)
        resposta = self.enviar([casos["pdf digitalizado"], casos["formato não aceito"]])
        self.assertEqual(len(resposta.context["form"].errors["arquivo"]), 2)
        self.assertFalse(Importacao.objects.exists())

    def test_limites_de_tamanho_paginas_e_quantidade(self):
        comp = self.componente(encontros=[(SEG, (8, 0), (10, 0), self.p1, "Aula")])
        with patch.object(imp, "MAX_BYTES", 100), self.assertRaises(imp.ErroImportacao):
            imp.ler_arquivo(self.exportar(comp, "pdf"))
        with patch.object(doc, "MAX_PAGINAS", 0), self.assertRaises(imp.ErroImportacao):
            imp.ler_arquivo(self.exportar(comp, "pdf"))
        with patch.object(doc, "MAX_DESCOMPACTADO", 100), self.assertRaises(imp.ErroImportacao):
            imp.ler_arquivo(self.exportar(comp, "docx"))
        with patch.object(imp, "MAX_ARQUIVOS", 1):
            resposta = self.enviar([self.exportar(comp, "pdf"), self.exportar(comp, "docx")])
            self.assertIn("arquivo", resposta.context["form"].errors)

    def test_pdf_indisponivel_sem_a_biblioteca(self):
        comp = self.componente(encontros=[(SEG, (8, 0), (10, 0), self.p1, "Aula")])
        importar = builtins.__import__

        def sem_pdfplumber(nome, *a, **kw):
            if nome == "pdfplumber":
                raise ImportError
            return importar(nome, *a, **kw)

        with patch.object(builtins, "__import__", sem_pdfplumber), self.assertRaises(imp.ErroImportacao) as erro:
            imp.ler_arquivo(self.exportar(comp, "pdf"))
        self.assertIn("não está disponível", str(erro.exception))


class ImportacaoDeDocumentosTests(Base):
    def test_exportar_apagar_e_reimportar_recria_o_cronograma(self):
        for formato in ("docx", "pdf"):
            with self.subTest(formato):
                comp = self.componente(encontros=[
                    (SEG, (8, 0), (10, 0), self.p1, "Introdução"), (SEG, (8, 0), (10, 0), self.p2, "Introdução"),
                    (date(2027, 3, 8), (8, 0), (10, 0), self.p3, "Osteologia"), (date(2027, 3, 15), (13, 0), (15, 30), None, ""),
                ])
                antes = list(comp.encontros.values_list("data", "hora_inicio", "hora_fim", "professor", "conteudo", "tipo", "grupos", "ch", "local"))
                arquivo = self.exportar(comp, formato)
                # Com o componente ainda cadastrado, reimportar não muda nada.
                importacao, analise = self.conferir(arquivo)
                self.assertTrue(analise.ok, analise.erros)
                self.assertEqual((analise.contagem["sem_alteracao"], analise.contagem["criar"], analise.contagem["atualizar"]), (4, 0, 0))
                comp.delete()
                arquivo.seek(0)
                importacao, analise = self.conferir(arquivo)
                self.assertTrue(analise.ok, analise.erros)
                self.assertEqual(analise.contagem["criar"], 4)
                self.acao(importacao, acao="aplicar")
                novo = Componente.objects.get()
                self.assertEqual((novo.nome, novo.turma, novo.periodo, novo.curso, novo.coordenador, novo.carga_horaria, novo.ch_teorica, novo.ch_pratica),
                                 ("Anatomia II", "A", "2º", "Medicina", self.coord, 60, 40, 20))
                self.assertEqual(list(novo.encontros.values_list("data", "hora_inicio", "hora_fim", "professor", "conteudo", "tipo", "grupos", "ch", "local")), antes)
                importacao.refresh_from_db()
                self.assertEqual(importacao.arquivos[0]["formato"], formato)
                novo.delete()

    def test_semestre_do_documento_diferente_do_destino_e_erro(self):
        comp = self.componente(encontros=[(SEG, (8, 0), (10, 0), self.p1, "Aula")])
        arquivo = self.exportar(comp, "docx")
        outro = Semestre.objects.create(nome="2027.2", data_inicio=date(2027, 8, 1), data_fim=date(2027, 12, 15))
        resposta = self.client.post(reverse("importar"), {"arquivo": arquivo, "semestre": outro.id})
        analise = self.client.get(resposta["Location"]).context["analise"]
        self.assertIn("mas a importação é para 2027.2", " ".join(e["mensagem"] for e in analise.erros))

    def test_nomes_com_titulo_sao_reconhecidos_e_os_demais_podem_ser_associados(self):
        cabecalhos = ("Componente curricular", "Turma", "Data", "Horário", "Docente", "Coordenador")
        linhas = [
            ("Bioética", "A", SEG, "08h-10h", "Profa. Dra. Ana Lima", "Prof. Carla Nunes"),     # reconhecidos sem os títulos
            ("Bioética", "A", TER, "08h-10h", "B. Sá", "Prof. Carla Nunes"),                    # abreviado: precisa de associação
            ("Bioética", "A", QUA, "08h-10h", "Docente a definir", "Prof. Carla Nunes"),
        ]
        importacao, analise = self.conferir(enviado("bioetica.xlsx", imp.gerar_planilha(linhas, cabecalhos)))
        self.assertFalse(analise.ok)
        self.assertEqual([(p["texto"], p["papel"], p["linhas"], p["valor"]) for p in analise.pessoas],
                         [("B. Sá", "docente", 1, None), ("Docente a definir", "docente", 1, None)])
        self.assertContains(self.client.get(reverse("importacao_detalhe", args=[importacao.pk])), "Nomes de docentes e coordenadores a associar")
        # Associação inválida (administrador não é docente; id inexistente) é ignorada.
        self.acao(importacao, acao="associar", total=2, nome_0="B. Sá", pessoa_0=self.admin.id, nome_1="Docente a definir", pessoa_1=999999)
        self.assertEqual(Importacao.objects.get(pk=importacao.pk).associacoes, {})
        self.acao(importacao, acao="associar", total=2, nome_0="B. Sá", pessoa_0=self.p2.id, nome_1="Docente a definir", pessoa_1=0)
        analise = self.analise(importacao)
        self.assertTrue(analise.ok, analise.erros)
        self.assertEqual([p["valor"] for p in analise.pessoas], [self.p2.id, 0])        # continuam visíveis para revisão
        self.acao(importacao, acao="aplicar")
        self.assertEqual(list(Encontro.objects.order_by("data").values_list("professor", flat=True)), [self.p1.id, self.p2.id, None])
        self.assertEqual(Componente.objects.get().coordenador, self.coord)

    def test_resolucao_de_nomes_tolera_titulos_parenteses_e_email_quebrado(self):
        Usuario.objects.filter(pk=self.p3.pk).update(nome="Célia Reis (substituta)")
        docentes = imp._Docentes()
        casos = {"Ana Lima": self.p1, "PROFA. DRA. ANA LIMA": self.p1, "Prof. Me. Bruno Sá": self.p2, "Célia Reis": self.p3,
                 "Profa. Célia Reis (substituta)": self.p3, "p1@t. example": self.p1, "P2@T.EXAMPLE": self.p2}
        for texto, esperado in casos.items():
            self.assertEqual(docentes.resolver(texto), (esperado, ""), texto)
        for texto in ("Ana", "Lima", "Maria Ana Lima", "x@t.example"):
            self.assertIsNone(docentes.resolver(texto)[0], texto)
        self.assertEqual(docentes.resolver("Carla Nunes", "coordenador"), (self.coord, ""))
        self.assertIsNone(docentes.resolver("Ana Lima", "coordenador")[0])       # professora não é coordenadora

    def test_coordenador_do_documento_precisa_ser_quem_importa_ou_ser_associado(self):
        comp = self.componente(coord=self.coord2, encontros=[(SEG, (8, 0), (10, 0), self.p1, "Aula")])
        arquivo = self.exportar(comp, "pdf")
        comp.delete()
        importacao, analise = self.conferir(arquivo)                       # coord importa documento de Coord Dois
        self.assertIn("sob a sua coordenação", analise.erros[0]["mensagem"])
        # A administração importa o mesmo documento: o coordenador vem do próprio arquivo.
        self.client.force_login(self.admin)
        arquivo.seek(0)
        importacao, analise = self.conferir(arquivo)
        self.assertTrue(analise.ok, analise.erros)
        self.assertEqual(analise.componentes[0].coordenador, self.coord2)
        # Nome de coordenador desconhecido: fica pendente até ser associado ou ignorado.
        Usuario.objects.filter(pk=self.coord2.pk).update(nome="Outro Nome")
        analise = self.analise(importacao)
        self.assertEqual([(p["texto"], p["papel"]) for p in analise.pessoas], [("Coord Dois", "coordenador")])
        self.acao(importacao, acao="associar", total=1, nome_0="Coord Dois", pessoa_0=self.p1.id)   # professor não coordena
        self.assertFalse(self.analise(importacao).ok)
        self.acao(importacao, acao="associar", total=1, nome_0="Coord Dois", pessoa_0=self.coord.id)
        analise = self.analise(importacao)
        self.assertTrue(analise.ok, analise.erros)
        self.assertEqual(analise.componentes[0].coordenador, self.coord)


class CruzamentoTests(Base):
    def cinco_arquivos(self):
        """Cinco cronogramas em três formatos; os conflitos só existem entre arquivos diferentes."""
        segundas = [date(2027, 3, d) for d in (1, 8, 15)]
        DataBloqueada.objects.create(semestre=self.sem, data=date(2027, 3, 19), descricao="Feriado local")
        specs = [
            ("docx", "Anatomia II", "A", [(d, (8, 0), (10, 0), self.p1, "Aula") for d in segundas]),
            ("pdf", "Fisiologia II", "A", [(d, (10, 0), (12, 0), self.p2, "Aula") for d in segundas[:2]]
             + [(segundas[2], (9, 0), (11, 0), self.p2, "Aula")]),                                    # TURMA × Anatomia
            ("pdf", "Histologia II", "B", [(d, (14, 0), (16, 0), self.p3, "Aula") for d in segundas[:2]]
             + [(segundas[1], (8, 0), (10, 0), self.p1, "Aula")]),                                    # DOCENTE × Anatomia
            ("docx", "Saúde da Família II", "B", [(date(2027, 3, d), (8, 0), (10, 0), self.p3, "Aula") for d in (12, 19, 26)]),   # CALENDÁRIO em 19/03
        ]
        arquivos = []
        for formato, nome, turma, encontros in specs:
            comp = self.componente(nome=nome, turma=turma, encontros=encontros)
            arquivos.append(self.exportar(comp, formato, f"{nome}.{formato}"))
            comp.delete()
        planilha = imp.gerar_planilha([
            ("Bioquímica II", "", "2º", "B", "Tarde", segundas[0], "15h-17h", "Aula", "T", "", "", "TODOS", "p2@t.example", "", "Sala 2"),  # TURMA × Histologia
        ])
        arquivos.append(enviado("Bioquímica II.xlsx", planilha))
        return arquivos

    def test_cinco_cronogramas_em_tres_formatos_sao_cruzados_entre_si(self):
        importacao, analise = self.conferir(self.cinco_arquivos())
        self.assertTrue(analise.ok, analise.erros)
        self.assertEqual([a["formato"] for a in importacao.arquivos], ["docx", "pdf", "pdf", "docx", "xlsx"])
        self.assertEqual((analise.contagem["linhas"], analise.contagem["criar"], analise.contagem["componentes_novos"]), (13, 13, 5))
        self.assertEqual(sorted(c["tipo"] for c in analise.conflitos), ["CALENDARIO", "DOCENTE", "TURMA", "TURMA"])
        textos = " | ".join(c["texto"] for c in analise.conflitos)
        for trecho in ("de Anatomia II.docx", "de Fisiologia II.pdf", "de Histologia II.pdf", "de Saúde da Família II.docx", "de Bioquímica II.xlsx"):
            self.assertIn(trecho, textos)
        self.assertNotIn("já cadastrado", textos)                 # todos os conflitos são entre os próprios arquivos
        self.assertFalse(Componente.objects.exists())             # conferir não grava nada

        pagina = self.client.get(reverse("importacao_detalhe", args=[importacao.pk]))
        self.assertContains(pagina, "entre os próprios arquivos")
        self.acao(importacao, acao="aplicar")
        self.assertEqual(Componente.objects.count(), 5)
        self.assertEqual(sorted(Conflito.objects.filter(status="ATIVO").values_list("tipo", flat=True)),
                         ["CALENDARIO", "DOCENTE", "TURMA", "TURMA"])
        # O plano de remanejamento resolve os conflitos trazidos pelos cinco arquivos.
        plano = sg.planejar(sg.montar_contexto(self.sem), lambda c: True)
        self.assertEqual((plano.total, plano.sem_solucao), (4, []))
        self.client.post(reverse("aplicar_sugestoes"), {"acoes": __import__("json").dumps([s.carga for s in plano.sugestoes])})
        sincronizar_conflitos()
        self.assertFalse(Conflito.objects.filter(status="ATIVO").exists())

    def test_anexar_e_retirar_arquivos_da_conferencia(self):
        arquivos = self.cinco_arquivos()
        importacao, analise = self.conferir(arquivos[0])
        self.assertEqual((analise.contagem["linhas"], len(analise.conflitos), analise.varios_arquivos), (3, 0, False))
        self.acao(importacao, acao="anexar", arquivo=arquivos[1:3])
        analise = self.analise(importacao)
        self.assertEqual((analise.contagem["linhas"], sorted(c["tipo"] for c in analise.conflitos)), (9, ["DOCENTE", "TURMA"]))
        importacao.refresh_from_db()
        self.assertTrue(importacao.arquivo_nome.startswith("3 arquivos: Anatomia II.docx"))
        # O mesmo arquivo de novo é recusado; nada muda.
        arquivos[1].seek(0)
        resposta = self.client.post(reverse("importacao_detalhe", args=[importacao.pk]), {"acao": "anexar", "arquivo": arquivos[1]}, follow=True)
        self.assertContains(resposta, "já está anexado")
        self.assertEqual(self.analise(importacao).contagem["linhas"], 9)
        # Arquivo ilegível também não altera a conferência.
        resposta = self.client.post(reverse("importacao_detalhe", args=[importacao.pk]), {"acao": "anexar", "arquivo": enviado("x.pdf", b"lixo")}, follow=True)
        self.assertContains(resposta, "Nenhum arquivo foi anexado")
        # Retirar o PDF de Fisiologia elimina o conflito de turma.
        self.acao(importacao, acao="remover_arquivo", arquivo=1)
        analise = self.analise(importacao)
        self.assertEqual((analise.contagem["linhas"], [c["tipo"] for c in analise.conflitos]), (6, ["DOCENTE"]))
        self.assertIn("de Histologia II.pdf", analise.conflitos[0]["texto"])
        self.acao(importacao, acao="remover_arquivo", arquivo=2)
        self.acao(importacao, acao="remover_arquivo", arquivo=0)             # o último arquivo não pode ser retirado
        self.assertEqual(self.analise(importacao).contagem["linhas"], 3)
        self.acao(importacao, acao="aplicar")
        self.assertEqual(list(Componente.objects.values_list("nome", flat=True)), ["Anatomia II"])

    def test_mesmo_cronograma_em_dois_formatos_e_apontado_como_repeticao(self):
        comp = self.componente(encontros=[(SEG, (8, 0), (10, 0), self.p1, "Aula"), (TER, (8, 0), (10, 0), self.p1, "Aula")])
        em_docx, em_pdf = self.exportar(comp, "docx", "anatomia.docx"), self.exportar(comp, "pdf", "anatomia.pdf")
        comp.delete()
        importacao, analise = self.conferir([em_docx, em_pdf])
        self.assertEqual([(e["arquivo"], e["linha"]) for e in analise.erros], [("anatomia.pdf", 1), ("anatomia.pdf", 2)])
        self.assertIn("da linha 1 de anatomia.docx", analise.erros[0]["mensagem"])
        self.assertContains(self.client.get(reverse("importacao_detalhe", args=[importacao.pk])), "<th>Arquivo</th>")

    def test_cadastros_divergentes_do_mesmo_componente_em_arquivos_diferentes(self):
        comp = self.componente(encontros=[(SEG, (8, 0), (10, 0), self.p1, "Aula")])
        em_pdf = self.exportar(comp, "pdf", "anatomia.pdf")
        comp.delete()
        planilha = imp.gerar_planilha([("Anatomia II", "", "3º", "A", "", TER, "08h-10h", "Aula", "T", "", "", "", "p1@t.example", "", "")])
        _, analise = self.conferir([em_pdf, enviado("extra.xlsx", planilha)])
        self.assertEqual([(e["arquivo"], e["campo"]) for e in analise.erros], [("extra.xlsx", "Período do curso")])
        self.assertIn("informado para o mesmo componente na linha 1 de anatomia.pdf", analise.erros[0]["mensagem"])

    def test_isolamento_das_novas_acoes_da_conferencia(self):
        arquivos = self.cinco_arquivos()
        importacao, _ = self.conferir(arquivos[:2])
        url = reverse("importacao_detalhe", args=[importacao.pk])
        for outro in (self.coord2, self.admin, self.p1):
            self.client.force_login(outro)
            esperado = 403 if outro == self.p1 else 404
            for dados in ({"acao": "anexar", "arquivo": arquivos[2]}, {"acao": "remover_arquivo", "arquivo": 0},
                          {"acao": "associar", "total": 1, "nome_0": "x", "pessoa_0": self.p1.id}):
                arquivos[2].seek(0)
                self.assertEqual(self.client.post(url, dados).status_code, esperado)
        importacao.refresh_from_db()
        self.assertEqual((len(importacao.arquivos), importacao.associacoes, len(importacao.linhas)), (2, {}, 6))


class ExemplosDoRepositorioTests(TestCase):
    def test_exemplos_de_cruzamento_gerados_a_partir_da_demonstracao(self):
        from .management.commands.gerar_exemplos import gerar_cruzamento

        with patch.dict("os.environ", {"CRONOMED_DEMO_PASSWORD": "Senha-De-Teste-123"}):
            call_command("seed_demo", stdout=BytesIO() and __import__("io").StringIO())
        semestre = Semestre.objects.get()
        coord2 = Usuario.objects.get(email="coord2@demo.cronomed.example")
        componentes = Componente.objects.count()
        arquivos = gerar_cruzamento(semestre, coord2)
        self.assertEqual(Componente.objects.count(), componentes)        # a geração não deixa nada no banco
        self.assertEqual(sorted(n.rsplit(".", 1)[1] for n in arquivos), ["docx", "docx", "pdf", "pdf", "xlsx"])
        cabecalhos, linhas, anexados = [], [], []
        for nome, dados in arquivos.items():
            cabecalhos, linhas, anexados = imp.anexar(cabecalhos, linhas, anexados, imp.ler_arquivo(enviado(nome, dados)))
        analise = imp.analisar(cabecalhos, linhas, imp.completar_mapeamento({}, cabecalhos), coord2, semestre,
                               arquivos=[a["nome"] for a in anexados])
        self.assertTrue(analise.ok, analise.erros)
        self.assertEqual((analise.contagem["criar"], analise.contagem["componentes_novos"]), (22, 5))
        self.assertEqual(sorted(c["tipo"] for c in analise.conflitos), ["CALENDARIO", "DOCENTE", "TURMA", "TURMA"])
