"""Exportação do cronograma para DOCX (python-docx) e PDF (ReportLab).

O leiaute segue o modelo institucional "CRONOGRAMA DE AULAS" da Coordenação
de Medicina do UNIPÊ (A4 retrato; quadro de identificação numerado; tabela
DATA | HORÁRIO | CONTEÚDO | Tipos | ATIVIDADES | RECURSOS | GRUPOS | DOCENTE |
CH | LOCAL). As constantes abaixo concentram os ajustes de aparência.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import Configuracao
from .services import feriados_do_componente

AZUL_CABECALHO = "405F91"      # linha de títulos da tabela (como no modelo)
AZUL_TITULO = "8DB3E2"         # faixa "CRONOGRAMA DE AULAS"
MARCA_RASCUNHO = "RASCUNHO — NÃO APROVADO"
COLUNAS = ["DATA", "HORÁRIO", "CONTEÚDO", "Tipos", "ATIVIDADES", "RECURSOS", "GRUPOS", "DOCENTE", "CH", "LOCAL"]
LARGURAS_CM = [1.25, 1.85, 3.0, 1.0, 2.9, 2.6, 1.9, 2.1, 0.9, 1.5]   # soma 19,0 cm (A4 retrato, margens 1 cm)
COLUNAS_MESCLAVEIS = [0, 1, 2, 3, 4, 5, 6, 9]   # tudo, menos DOCENTE e CH (uma linha por docente)
LARGURAS_IDENT_CM = [9.4, 3.0, 3.3, 3.3]


def linhas_cronograma(comp):
    """Linhas do cronograma na ordem do documento: encontros e feriados."""
    linhas = []
    for e in comp.encontros.select_related("professor"):
        linhas.append({
            "ordem": (e.data, e.hora_inicio, 1, e.id), "chave": (e.data, e.hora_inicio, e.hora_fim), "feriado": False,
            "celulas": [e.data.strftime("%d/%m"), e.horario_modelo, e.conteudo, e.tipo, e.atividade, e.recursos,
                        e.grupos, e.professor.nome if e.professor_id else "", e.ch, e.local],
        })
    for f in feriados_do_componente(comp):
        linhas.append({
            "ordem": (f["data"], f["hora_inicio"], 0, 0), "chave": None, "feriado": True,
            "celulas": [f["data"].strftime("%d/%m"), f["horario"], f["descricao"], "-", "-", "-", "", "", f["ch"], ""],
        })
    linhas.sort(key=lambda l: l["ordem"])
    # Linhas consecutivas do mesmo dia/horário e mesmo conteúdo formam um único
    # encontro com vários docentes: as células comuns são mescladas.
    for i, l in enumerate(linhas):
        ant = linhas[i - 1] if i else None
        l["continua"] = bool(
            ant and not l["feriado"] and not ant["feriado"] and l["chave"] == ant["chave"]
            and all(l["celulas"][c] == ant["celulas"][c] for c in COLUNAS_MESCLAVEIS)
        )
    return linhas


def _grupos(linhas):
    """[(inicio, fim)] dos blocos de linhas mescladas (índices inclusivos)."""
    blocos, i = [], 0
    while i < len(linhas):
        j = i
        while j + 1 < len(linhas) and linhas[j + 1]["continua"]:
            j += 1
        if j > i:
            blocos.append((i, j))
        i = j + 1
    return blocos


def _identificacao(comp):
    return {
        "curso": f"1. CURSO: {comp.curso}",
        "componente": f"2. COMPONENTE CURRICULAR: {comp.nome}",
        "ch": f"CH: {comp.carga_horaria}h/A",
        "teorica": f"Teórica: {comp.ch_teorica}h/A",
        "pratica": f"Prática: {comp.ch_pratica}h/A",
        "semestre": f"3. SEMESTRE: {comp.semestre.nome}",
        "periodo": f"PERÍODO: {comp.periodo or '—'}",
        "turma": f"TURMA: {comp.turma}",
        "coordenador": f"4. COORDENADOR: {comp.coordenador.nome}",
    }


def _situacao_texto(comp, oficial):
    if not oficial:
        return f"{MARCA_RASCUNHO} · gerado em {timezone.localtime():%d/%m/%Y %H:%M}"
    txt = f"Aprovado por {comp.aprovado_por.nome if comp.aprovado_por else '—'} em {timezone.localtime(comp.aprovado_em):%d/%m/%Y}"
    if comp.publicado_em:
        txt += f" · Publicado em {timezone.localtime(comp.publicado_em):%d/%m/%Y}"
    return txt


# ------------------------------------------------------------------- DOCX


def _sombrear(celula, cor):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), cor)
    celula._tc.get_or_add_tcPr().append(shd)


def _campo(paragrafo, instrucao):
    for tipo in ("begin", None, "end"):
        run = paragrafo.add_run()
        run.font.size = Pt(8)
        if tipo:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tipo)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = instrucao
        run._r.append(el)


def _texto(celula, texto, negrito=False, tamanho=9, cor=None, alinhamento=None):
    celula.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    p = celula.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    if alinhamento is not None:
        p.alignment = alinhamento
    partes = str(texto).split("\n")
    for i, parte in enumerate(partes):
        r = p.add_run(parte)
        r.bold = negrito
        r.font.size = Pt(tamanho)
        if cor:
            r.font.color.rgb = RGBColor.from_string(cor)
        if i < len(partes) - 1:
            r.add_break()


def _sem_bordas(tabela):
    pr = tabela._tbl.tblPr
    bordas = OxmlElement("w:tblBorders")
    for lado in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{lado}")
        b.set(qn("w:val"), "nil")
        bordas.append(b)
    pr.append(bordas)


def gerar_docx(comp, linhas, oficial):
    cfg = Configuracao.obter()
    logo = cfg.caminho_logo()
    doc = Document()
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(9)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(1.0)
    sec.top_margin, sec.bottom_margin = Cm(1.0), Cm(1.3)

    # Topo: logomarca à esquerda e coordenação à direita (como no modelo)
    topo = doc.add_table(rows=1, cols=2)
    topo.autofit = False
    _sem_bordas(topo)
    for i, w in enumerate((7.0, 12.0)):
        topo.columns[i].width = Cm(w)
        topo.rows[0].cells[i].width = Cm(w)
    c_logo, c_txt = topo.rows[0].cells
    if logo:
        c_logo.paragraphs[0].add_run().add_picture(str(logo), height=Cm(1.6))
    else:
        _texto(c_logo, cfg.instituicao, negrito=True, tamanho=10)
    c_txt.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
    p = c_txt.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p.add_run(f"Coordenação de {comp.curso}")
    r.italic = True
    r.font.size = Pt(11)
    c_txt.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM

    if not oficial:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(MARCA_RASCUNHO)
        r.bold = True
        r.font.size = Pt(13)
        r.font.color.rgb = RGBColor(0xC6, 0x28, 0x28)
        cab = sec.header.paragraphs[0]
        cab.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = cab.add_run(MARCA_RASCUNHO)
        r.bold = True
        r.font.size = Pt(8)
        r.font.color.rgb = RGBColor(0xC6, 0x28, 0x28)
    else:
        doc.add_paragraph().paragraph_format.space_after = Pt(0)

    # Rodapé
    p = sec.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"{comp.nome} — Turma {comp.turma} — {comp.semestre.nome}   ·   {_situacao_texto(comp, oficial)}   ·   Página ")
    r.font.size = Pt(8)
    _campo(p, "PAGE")
    r = p.add_run(" de ")
    r.font.size = Pt(8)
    _campo(p, "NUMPAGES")

    # Quadro de identificação
    d = _identificacao(comp)
    ident = doc.add_table(rows=5, cols=4)
    ident.style = "Table Grid"
    ident.alignment = WD_TABLE_ALIGNMENT.CENTER
    ident.autofit = False
    for i, w in enumerate(LARGURAS_IDENT_CM):
        ident.columns[i].width = Cm(w)
        for linha in ident.rows:
            linha.cells[i].width = Cm(w)
    titulo = ident.cell(0, 0).merge(ident.cell(0, 3))
    _sombrear(titulo, AZUL_TITULO)
    _texto(titulo, "\nCRONOGRAMA DE AULAS\n", negrito=True, tamanho=12, alinhamento=WD_ALIGN_PARAGRAPH.CENTER)
    _texto(ident.cell(1, 0).merge(ident.cell(1, 3)), d["curso"], tamanho=11)
    for i, chave in enumerate(("componente", "ch", "teorica", "pratica")):
        _texto(ident.cell(2, i), d[chave], tamanho=11)
    _texto(ident.cell(3, 0), d["semestre"], tamanho=11)
    _texto(ident.cell(3, 1), d["periodo"], tamanho=11)
    _texto(ident.cell(3, 2).merge(ident.cell(3, 3)), d["turma"], tamanho=11)
    _texto(ident.cell(4, 0).merge(ident.cell(4, 3)), d["coordenador"], tamanho=11)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run("CRONOGRAMA")
    r.bold = True
    r.font.size = Pt(12)

    # Cronograma
    tab = doc.add_table(rows=1, cols=len(COLUNAS))
    tab.style = "Table Grid"
    tab.alignment = WD_TABLE_ALIGNMENT.CENTER
    tab.autofit = False
    for i, w in enumerate(LARGURAS_CM):
        tab.columns[i].width = Cm(w)
    cab_linha = tab.rows[0]
    rep = OxmlElement("w:tblHeader")
    rep.set(qn("w:val"), "true")
    cab_linha._tr.get_or_add_trPr().append(rep)
    for i, titulo in enumerate(COLUNAS):
        c = cab_linha.cells[i]
        c.width = Cm(LARGURAS_CM[i])
        _sombrear(c, AZUL_CABECALHO)
        _texto(c, titulo, negrito=True, tamanho=8, cor="FFFFFF", alinhamento=WD_ALIGN_PARAGRAPH.CENTER)
    centradas = {0, 1, 3, 8}
    for l in linhas:
        linha = tab.add_row()
        nq = OxmlElement("w:cantSplit")
        nq.set(qn("w:val"), "true")
        linha._tr.get_or_add_trPr().append(nq)
        for i, valor in enumerate(l["celulas"]):
            c = linha.cells[i]
            c.width = Cm(LARGURAS_CM[i])
            if l["continua"] and i in COLUNAS_MESCLAVEIS:
                continue   # ficará dentro da célula mesclada
            _texto(c, valor, negrito=l["feriado"] and i == 2, tamanho=8,
                   alinhamento=WD_ALIGN_PARAGRAPH.CENTER if i in centradas else None)
    for ini, fim in _grupos(linhas):
        for col in COLUNAS_MESCLAVEIS:
            tab.cell(ini + 1, col).merge(tab.cell(fim + 1, col))
    if not linhas:
        doc.add_paragraph("Nenhum encontro cadastrado.")

    saida = BytesIO()
    doc.save(saida)
    return saida.getvalue()


# -------------------------------------------------------------------- PDF


def gerar_pdf(comp, linhas, oficial):
    cfg = Configuracao.obter()
    logo = cfg.caminho_logo()
    azul = colors.HexColor("#" + AZUL_CABECALHO)
    grade = colors.HexColor("#7F8FA6")
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=7.5, leading=9.5)
    centro = ParagraphStyle("centro", parent=base, alignment=TA_CENTER)
    negrito = ParagraphStyle("neg", parent=base, fontName="Helvetica-Bold")
    cab_st = ParagraphStyle("cab", parent=centro, fontName="Helvetica-Bold", textColor=colors.white, fontSize=7.5)
    ident_st = ParagraphStyle("ident", parent=base, fontSize=10, leading=12.5)
    titulo_st = ParagraphStyle("tit", parent=centro, fontName="Helvetica-Bold", fontSize=12, leading=15)

    def par(texto, estilo=base):
        return Paragraph(escape(str(texto)).replace("\n", "<br/>"), estilo)

    largura, altura = A4
    rodape = f"{comp.nome} — Turma {comp.turma} — {comp.semestre.nome}   ·   {_situacao_texto(comp, oficial)}"

    def pagina(canvas, doc):
        canvas.saveState()
        if doc.page == 1:
            y = altura - 1.0 * cm
            if logo:
                try:
                    img = ImageReader(str(logo))
                    w, h = img.getSize()
                    alt = 1.6 * cm
                    canvas.drawImage(img, 1 * cm, y - alt, width=alt * w / h, height=alt, mask="auto")
                except Exception:
                    pass
            else:
                canvas.setFont("Helvetica-Bold", 10)
                canvas.drawString(1 * cm, y - 1.0 * cm, cfg.instituicao)
            canvas.setFont("Helvetica-Oblique", 11)
            canvas.drawRightString(largura - 1 * cm, y - 1.5 * cm, f"Coordenação de {comp.curso}")
        if not oficial:
            canvas.setFillColor(colors.HexColor("#C62828"))
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawCentredString(largura / 2, altura - 0.7 * cm, MARCA_RASCUNHO)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(1 * cm, 0.7 * cm, rodape[:150])
        canvas.drawRightString(largura - 1 * cm, 0.7 * cm, f"Página {doc.page}")
        canvas.restoreState()

    class _Documento(SimpleDocTemplate):
        def afterPage(self):
            if oficial:
                return
            c = self.canv
            c.saveState()
            c.setFont("Helvetica-Bold", 58)
            c.setFillColor(colors.Color(0.78, 0.16, 0.16, alpha=0.13))
            c.translate(largura / 2, altura / 2)
            c.rotate(50)
            c.drawCentredString(0, -20, "NÃO APROVADO")
            c.restoreState()

    saida = BytesIO()
    doc = _Documento(
        saida, pagesize=A4, leftMargin=1 * cm, rightMargin=1 * cm, topMargin=1.2 * cm, bottomMargin=1.4 * cm,
        title=f"Cronograma — {comp.nome} — Turma {comp.turma}", author=cfg.instituicao,
    )
    d = _identificacao(comp)
    ident = Table(
        [
            [Paragraph("<br/>CRONOGRAMA DE AULAS<br/>&nbsp;", titulo_st), "", "", ""],
            [par(d["curso"], ident_st), "", "", ""],
            [par(d["componente"], ident_st), par(d["ch"], ident_st), par(d["teorica"], ident_st), par(d["pratica"], ident_st)],
            [par(d["semestre"], ident_st), par(d["periodo"], ident_st), par(d["turma"], ident_st), ""],
            [par(d["coordenador"], ident_st), "", "", ""],
        ],
        colWidths=[w * cm for w in LARGURAS_IDENT_CM],
    )
    ident.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("SPAN", (0, 0), (-1, 0)), ("SPAN", (0, 1), (-1, 1)), ("SPAN", (2, 3), (3, 3)), ("SPAN", (0, 4), (-1, 4)),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + AZUL_TITULO)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 2), ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
    ]))
    fluxo = [Spacer(1, 1.9 * cm), ident, Spacer(1, 0.35 * cm), Paragraph("CRONOGRAMA", titulo_st), Spacer(1, 0.25 * cm)]

    centradas = {0, 1, 3, 8}
    corpo = [[par(c, cab_st) for c in COLUNAS]]
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.5, grade),
        ("BACKGROUND", (0, 0), (-1, 0), azul),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for l in linhas:
        linha = []
        for i, valor in enumerate(l["celulas"]):
            if l["continua"] and i in COLUNAS_MESCLAVEIS:
                linha.append("")
            else:
                linha.append(par(valor, negrito if (l["feriado"] and i == 2) else (centro if i in centradas else base)))
        corpo.append(linha)
    for ini, fim in _grupos(linhas):
        for col in COLUNAS_MESCLAVEIS:
            estilo.append(("SPAN", (col, ini + 1), (col, fim + 1)))
    if not linhas:
        corpo.append([par("Nenhum encontro cadastrado.")] + [""] * (len(COLUNAS) - 1))
        estilo.append(("SPAN", (0, 1), (-1, 1)))
    tab = Table(corpo, colWidths=[w * cm for w in LARGURAS_CM], repeatRows=1)
    tab.setStyle(TableStyle(estilo))
    fluxo.append(tab)
    doc.build(fluxo, onFirstPage=pagina, onLaterPages=pagina)
    return saida.getvalue()
