"""Leitura de cronogramas em DOCX e PDF no modelo institucional "CRONOGRAMA DE AULAS".

Os dois formatos são reduzidos à mesma estrutura — uma sequência de blocos de
texto e de tabelas — e daí ao mesmo formato tabular das planilhas (uma linha
por encontro), de modo que validação, cruzamento e importação são idênticos
para XLSX, DOCX e PDF.

O que é reconhecido:

- quadro de identificação (em tabela ou em texto corrido): CURSO, COMPONENTE
  CURRICULAR, CH, Teórica, Prática, SEMESTRE, PERÍODO, TURMA e COORDENADOR;
- tabela do cronograma: a que tem colunas de data e de horário; os títulos são
  reconhecidos pelos mesmos apelidos usados nas planilhas;
- vários docentes na mesma aula (células mescladas): cada docente vira uma linha;
- cabeçalho repetido a cada página e tabela continuada em várias páginas;
- linhas de feriado/sem aula (tipo "-" e sem docente) são ignoradas;
- vários cronogramas no mesmo arquivo, cada um com seu quadro de identificação.

PDF digitalizado (imagem, sem texto selecionável) não é lido: não há OCR.
"""
import re
import zipfile

from .importacao import (
    MAX_CELULA, MAX_DESCOMPACTADO, MAX_LINHAS, TIPOS, ErroImportacao, _APELIDOS, _rotulo_normalizado,
)
from . import agenda as ag

MAX_PAGINAS = 60
MAX_TABELAS = 300

# Título de cada campo nas colunas geradas (todos são apelidos reconhecidos pelo mapeamento).
TITULOS = {
    "componente": "Componente curricular", "turma": "Turma", "periodo": "Período", "curso": "Curso",
    "semestre": "Semestre", "coordenador": "Coordenador", "carga_horaria": "CH total",
    "ch_teorica": "CH teórica", "ch_pratica": "CH prática", "turno": "Turno", "codigo": "Código",
    "data": "Data", "horario": "Horário", "inicio": "Início", "fim": "Término", "conteudo": "Conteúdo",
    "tipo": "Tipo", "atividade": "Atividades", "recursos": "Recursos", "grupos": "Grupos",
    "docente": "Docente", "ch": "CH", "local": "Local", "observacoes": "Observações",
}
IDENTIFICACAO = ("componente", "turma", "periodo", "curso", "semestre", "coordenador",
                 "carga_horaria", "ch_teorica", "ch_pratica", "turno")
TEXTO_LONGO = {"conteudo", "atividade", "recursos", "observacoes"}

_ROTULOS = (
    ("componente", r"COMPONENTE\s+CURRICULAR"),
    ("curso", r"CURSO"),
    ("semestre", r"SEMESTRE(?:\s+LETIVO)?"),
    ("periodo", r"PER[IÍ]ODO(?:\s+DO\s+CURSO)?"),
    ("turma", r"TURMA"),
    ("coordenador", r"COORDENADOR(?:\s*\(A\)|A)?"),
    ("ch_teorica", r"(?:CH\s+)?TE[OÓ]RICA"),
    ("ch_pratica", r"(?:CH\s+)?PR[AÁ]TICA"),
    ("carga_horaria", r"CH(?:\s+TOTAL)?|CARGA\s+HOR[AÁ]RIA(?:\s+TOTAL)?"),
    ("turno", r"TURNO"),
)
_QUALQUER_ROTULO = "|".join(f"(?:{padrao})" for _, padrao in _ROTULOS)
_IDENT = re.compile(
    r"(?:^|(?<=\s))(?:\d+\s*[.)]\s*)?(?P<rotulo>" + _QUALQUER_ROTULO + r")\s*:\s*"
    r"(?P<valor>.*?)(?=\s+(?:\d+\s*[.)]\s*)?(?:" + _QUALQUER_ROTULO + r")\s*:|$)",
    re.IGNORECASE,
)
_CAMPO_DO_ROTULO = [(re.compile(rf"^(?:{padrao})$", re.IGNORECASE), campo) for campo, padrao in _ROTULOS]


def _uma_linha(texto):
    return " ".join(str(texto or "").split())


def _campo_do_titulo(titulo):
    """Campo do sistema para o título de uma coluna (tolerando quebra no meio da palavra)."""
    bruto = str(titulo or "")
    return _APELIDOS.get(_rotulo_normalizado(bruto)) or _APELIDOS.get(_rotulo_normalizado(bruto.replace("\n", "")))


def _ler_identificacao(texto, ident):
    """Acrescenta a `ident` os campos de identificação encontrados no texto. Retorna quantos achou."""
    achados = 0
    for linha in str(texto or "").split("\n\n"):
        for m in _IDENT.finditer(_uma_linha(linha)):
            campo = next(c for padrao, c in _CAMPO_DO_ROTULO if padrao.match(_uma_linha(m["rotulo"])))
            valor = m["valor"].strip(" .;")
            if valor in ("—", "-", "–"):
                valor = ""
            if campo == "turma" and "·" in valor:        # "A · Tarde"
                valor, _, turno = (p.strip() for p in valor.partition("·"))
                ident.setdefault("turno", turno)
            ident[campo] = valor[:MAX_CELULA]
            achados += 1
    return achados


def _linha_de_cabecalho(tabela):
    """(índice da linha de títulos, [campo ou None por coluna]) se for a tabela do cronograma."""
    for i, linha in enumerate(tabela[:8]):
        campos = [_campo_do_titulo(c) for c in linha]
        presentes = set(campos) - {None}
        if "data" in presentes and ("horario" in presentes or {"inicio", "fim"} <= presentes):
            return i, campos
    return None, None


def _extrair(blocos, eh_pdf):
    """Converte blocos ("texto", str) / ("tabela", [[células]]) em (cabeçalhos, linhas, avisos)."""
    ident, ident_usada = {}, False
    colunas = None            # campo (ou título) de cada coluna da tabela de cronograma corrente
    anterior = None
    registros, avisos = [], []
    n = ignoradas = sem_data = 0

    def identificar(texto):
        nonlocal ident, ident_usada
        provisoria = {}
        if _ler_identificacao(texto, provisoria):
            if ident_usada:                 # começa o quadro de identificação de outro cronograma
                ident, ident_usada = {}, False
            ident.update(provisoria)

    for tipo, conteudo in blocos:
        if tipo == "texto":
            identificar(conteudo)
            continue
        tabela = [list(l) for l in conteudo if l]
        if not tabela:
            continue
        indice, campos = _linha_de_cabecalho(tabela)
        if indice is None:
            continuacao = colunas is not None and all(len(l) == len(colunas) for l in tabela) and not any(
                _IDENT.search(_uma_linha(c)) for l in tabela for c in l if c
            )
            if not continuacao:
                for linha in tabela:        # quadro de identificação (ou tabela sem relação com o cronograma)
                    for celula in dict.fromkeys(c for c in linha if c):
                        identificar(celula)
                continue
            dados = tabela
        else:
            for linha in tabela[:indice]:
                for celula in dict.fromkeys(c for c in linha if c):
                    identificar(celula)
            colunas = [campo or _uma_linha(titulo) or f"Coluna {j + 1}" for j, (campo, titulo) in enumerate(zip(campos, tabela[indice]))]
            dados, anterior = tabela[indice + 1:], None

        for linha in dados:
            if len(linha) != len(colunas):
                continue
            if [_campo_do_titulo(c) for c in linha] == [c if c in TITULOS else None for c in colunas]:
                continue                    # cabeçalho repetido em nova página
            valores = {}
            for chave, celula in zip(colunas, linha):
                if celula is None:
                    valores[chave] = None
                elif chave in TEXTO_LONGO and not eh_pdf:
                    valores[chave] = "\n".join(_uma_linha(p) for p in str(celula).split("\n")).strip()[:MAX_CELULA]
                else:
                    valores[chave] = _uma_linha(celula)[:MAX_CELULA]
            if not any(valores.values()):
                continue
            n += 1
            if not valores.get("data") and not valores.get("docente"):
                sem_data += 1
                continue
            if not valores.get("data") and anterior:
                # Segundo docente da mesma aula: as demais células estão mescladas com a linha de cima.
                for chave in colunas:
                    if not valores.get(chave) and chave not in ("docente", "ch"):
                        valores[chave] = anterior.get(chave)
            valores = {k: v or "" for k, v in valores.items()}
            anterior = valores
            if not valores.get("docente") and TIPOS.get(ag.normalizar(valores.get("tipo", ""))) == "-":
                ignoradas += 1               # feriado ou dia sem aula
                continue
            ident_usada = True
            registros.append((n, {**{c: ident.get(c, "") for c in IDENTIFICACAO if c not in colunas}, **valores}))
            if len(registros) > MAX_LINHAS:
                raise ErroImportacao(f"O documento tem mais de {MAX_LINHAS} linhas de cronograma.")

    if colunas is None:
        raise ErroImportacao("nenhuma tabela de cronograma foi encontrada (são necessárias colunas de data e de horário).")
    if not registros:
        raise ErroImportacao("a tabela do cronograma não tem encontros.")
    if ignoradas:
        avisos.append(f"{ignoradas} linha(s) de feriado ou sem aula (tipo “-”, sem docente) foram ignoradas.")
    if sem_data:
        avisos.append(f"{sem_data} linha(s) sem data e sem docente foram ignoradas.")
    if not all(r.get("componente") and r.get("turma") for _, r in registros):
        avisos.append("O quadro de identificação (COMPONENTE CURRICULAR e TURMA) não foi encontrado em parte do documento.")

    chaves = list(dict.fromkeys(k for _, r in registros for k in r))
    # Colunas reconhecidas e totalmente vazias são omitidas, exceto as obrigatórias.
    chaves = [k for k in chaves if k not in TITULOS or k in ("componente", "turma", "data") or any(r.get(k) for _, r in registros)]
    cabecalhos = [TITULOS.get(k, k) for k in chaves]
    linhas = [{"n": n, "c": [r.get(k, "") for k in chaves]} for n, r in registros]
    return cabecalhos, linhas, avisos


# ----------------------------------------------------------------------- DOCX


def ler_docx(arquivo):
    from docx import Document
    from docx.table import Table

    try:
        arquivo.seek(0)
        with zipfile.ZipFile(arquivo) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPACTADO:
                raise ErroImportacao("o arquivo é grande demais depois de descompactado.")
        arquivo.seek(0)
        documento = Document(arquivo)
        blocos, tabelas = [], 0
        for bloco in documento.iter_inner_content():
            if isinstance(bloco, Table):
                tabelas += 1
                if tabelas > MAX_TABELAS:
                    raise ErroImportacao("o documento tem tabelas demais.")
                blocos.append(("tabela", [[c.text for c in linha.cells] for linha in bloco.rows]))
            elif bloco.text.strip():
                blocos.append(("texto", bloco.text))
    except ErroImportacao:
        raise
    except Exception:
        raise ErroImportacao("não foi possível ler o arquivo. Verifique se é um documento .docx válido e sem senha.")
    return _extrair(blocos, eh_pdf=False)


# ------------------------------------------------------------------------ PDF


def _sem_rotacao(objeto):
    """Descarta texto girado (marca-d'água diagonal), que se misturaria ao conteúdo das células."""
    if objeto.get("object_type") != "char":
        return True
    matriz = objeto.get("matrix") or (1, 0, 0, 1, 0, 0)
    return abs(matriz[1]) < 1e-3 and abs(matriz[2]) < 1e-3


def _texto_da_faixa(pagina, blocos, esquerda, direita, de, ate):
    """Acrescenta a `blocos` o texto da faixa horizontal [de, ate] da página (entre tabelas)."""
    if ate - de < 1:
        return
    texto = pagina.crop((esquerda, de, direita, ate)).extract_text() or ""
    if texto.strip():
        blocos.append(("texto", texto.replace("\n", "\n\n")))


def ler_pdf(arquivo):
    try:
        import pdfplumber
    except ImportError:
        raise ErroImportacao("a leitura de PDF não está disponível nesta instalação (pacote pdfplumber ausente). Envie o cronograma em DOCX ou XLSX.")

    blocos, caracteres = [], 0
    try:
        arquivo.seek(0)
        with pdfplumber.open(arquivo) as pdf:
            if len(pdf.pages) > MAX_PAGINAS:
                raise ErroImportacao(f"o PDF tem mais de {MAX_PAGINAS} páginas.")
            for pagina in pdf.pages:
                pagina = pagina.filter(_sem_rotacao)
                caracteres += len(pagina.chars)
                # Texto e tabelas na ordem em que aparecem na página: a identificação escrita
                # acima de uma tabela vale para ela, e não para as tabelas seguintes.
                esquerda, topo, direita, base = pagina.bbox
                cursor = topo
                for tabela in sorted(pagina.find_tables(), key=lambda t: (t.bbox[1], t.bbox[0])):
                    _texto_da_faixa(pagina, blocos, esquerda, direita, cursor, min(tabela.bbox[1], base))
                    blocos.append(("tabela", tabela.extract()))
                    cursor = max(cursor, min(tabela.bbox[3], base))
                _texto_da_faixa(pagina, blocos, esquerda, direita, cursor, base)
                pagina.flush_cache()
    except ErroImportacao:
        raise
    except Exception:
        raise ErroImportacao("não foi possível ler o arquivo. Verifique se é um PDF válido e sem senha.")
    if not caracteres:
        raise ErroImportacao("o PDF não tem texto selecionável (parece digitalizado). Envie o arquivo original em DOCX, XLSX ou PDF gerado pelo editor de texto.")
    return _extrair(blocos, eh_pdf=True)
