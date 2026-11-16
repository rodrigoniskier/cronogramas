"""Importação de cronogramas a partir de arquivos XLSX, DOCX e PDF.

Todos os formatos são reduzidos a uma tabela com uma linha por encontro e
colunas livres, mapeadas para os campos de `CAMPOS`. Vários arquivos, de
formatos diferentes, podem ser reunidos na mesma conferência (`anexar`) e
são validados e cruzados em conjunto. O fluxo tem três etapas, todas refeitas
a partir do estado atual do banco (nada é confiado ao navegador):

1. `ler_arquivo`    — lê cada arquivo com limites de tamanho e guarda o texto das
                      células (`ler_planilha` para XLSX; core/documentos.py para DOCX/PDF);
2. `analisar`       — valida cada linha, resolve docentes/componentes, planeja o que
                      será criado ou atualizado e prevê os conflitos resultantes —
                      entre os arquivos e com o que já está cadastrado;
3. `aplicar`        — grava tudo em uma única transação (ou nada, se houver erro).
"""
import hashlib
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import agenda as ag
from .models import Componente, Conflito, Encontro, HorarioSemanal, Usuario, ch_padrao
from .services import calendarios_de, datas_previstas, montar_agenda, pode_gerenciar, registrar, sincronizar_conflitos

MAX_BYTES = 4 * 1024 * 1024          # tamanho de cada arquivo enviado
MAX_ARQUIVOS = 20                     # arquivos reunidos em uma mesma conferência
FORMATOS = {".xlsx": "xlsx", ".docx": "docx", ".pdf": "pdf"}
MAX_DESCOMPACTADO = 30 * 1024 * 1024  # proteção contra arquivo-bomba (xlsx é um zip)
MAX_LINHAS = 3000
MAX_COLUNAS = 40
MAX_CELULA = 5000
MAX_TEXTO = 2_000_000                 # total de caracteres guardados por importação
MAX_VAZIAS_SEGUIDAS = 500             # depois disso, considera-se que os dados acabaram
LINHAS_CABECALHO = 20                 # o cabeçalho é procurado nas primeiras linhas
MAX_ERROS_EXIBIDOS = 200


class ErroImportacao(Exception):
    pass


@dataclass(frozen=True)
class Campo:
    nome: str
    rotulo: str
    apelidos: tuple = ()
    limite: int = MAX_CELULA
    do_componente: bool = False   # atributo do cadastro do componente (igual em todas as suas linhas)


CAMPOS = (
    Campo("componente", "Componente curricular", ("componente", "componente curricular", "disciplina", "unidade curricular", "modulo"), 150),
    Campo("turma", "Turma", ("turma",), 30),
    Campo("data", "Data", ("data", "dia")),
    Campo("horario", "Horário (início–término)", ("horario", "horarios")),
    Campo("inicio", "Início", ("inicio", "hora inicio", "hora de inicio", "hora inicial")),
    Campo("fim", "Término", ("fim", "termino", "hora fim", "hora final", "hora de termino")),
    Campo("docente", "Docente (e-mail, usuário ou nome)", ("docente", "docentes", "professor", "professor a", "docente e mail", "e mail do docente", "email do docente", "docente responsavel")),
    Campo("conteudo", "Conteúdo", ("conteudo", "conteudo programatico", "tema", "assunto")),
    Campo("tipo", "Tipo (T/P)", ("tipo", "tipos", "tipos t p", "t p")),
    Campo("atividade", "Atividades", ("atividade", "atividades", "metodologia")),
    Campo("recursos", "Recursos", ("recursos", "recurso")),
    Campo("grupos", "Grupos", ("grupos", "grupo"), 300),
    Campo("ch", "CH do encontro", ("ch", "ch do encontro", "carga horaria do encontro"), 10),
    Campo("local", "Local", ("local", "sala", "ambiente"), 120),
    Campo("observacoes", "Observações internas", ("observacoes", "observacao", "obs", "obs internas", "observacoes internas")),
    Campo("curso", "Curso", ("curso",), 80, True),
    Campo("periodo", "Período do curso", ("periodo", "periodo do curso", "serie"), 20, True),
    Campo("codigo", "Código do componente", ("codigo", "cod", "codigo do componente"), 30, True),
    Campo("turno", "Turno", ("turno",), 20, True),
    Campo("carga_horaria", "CH total (h/a)", ("ch total", "carga horaria", "carga horaria total"), 6, True),
    Campo("ch_teorica", "CH teórica (h/a)", ("ch teorica", "teorica"), 6, True),
    Campo("ch_pratica", "CH prática (h/a)", ("ch pratica", "pratica"), 6, True),
    Campo("coordenador", "Coordenador (e-mail ou nome)", ("coordenador", "coordenador a", "coordenador e mail", "e mail do coordenador"), 254, True),
    Campo("semestre", "Semestre (conferência)", ("semestre", "semestre letivo", "periodo letivo"), 40),
)
CAMPO = {c.nome: c for c in CAMPOS}
CAMPOS_ENCONTRO = ("conteudo", "tipo", "atividade", "recursos", "grupos", "ch", "local", "observacoes")

TIPOS = {"": "", "t": "T", "p": "P", "t/p": "T/P", "tp": "T/P", "-": "-",
         "teorica": "T", "pratica": "P", "teorico-pratica": "T/P", "teorico pratica": "T/P"}
TURNOS = {"manha": "MANHA", "tarde": "TARDE", "noite": "NOITE", "integral": "INTEGRAL"}


def _rotulo_normalizado(texto):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ag.normalizar(texto)).split())


_APELIDOS = {a: c.nome for c in CAMPOS for a in c.apelidos}


# ------------------------------------------------------------------- leitura


def _texto_celula(valor):
    """Converte o valor da célula em texto estável, guardado em JSON."""
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        if valor.year < 1901:                       # célula de hora lida como data-base do Excel
            return valor.strftime("%H:%M")
        if valor.time() == time(0):
            return valor.date().isoformat()
        return valor.strftime("%Y-%m-%dT%H:%M")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, time):
        return valor.strftime("%H:%M")
    if isinstance(valor, timedelta):
        minutos = round(valor.total_seconds() / 60)
        return f"{minutos // 60:02d}:{minutos % 60:02d}"
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()[:MAX_CELULA]


def ler_planilha(arquivo):
    """Lê a primeira aba do .xlsx. Retorna (cabeçalhos, linhas).

    `linhas` é uma lista de {"n": número da linha no Excel, "c": [textos]}.
    """
    from openpyxl import load_workbook

    nome = (getattr(arquivo, "name", "") or "").lower()
    if not nome.endswith(".xlsx"):
        raise ErroImportacao("Envie um arquivo Excel no formato .xlsx.")
    if getattr(arquivo, "size", 0) > MAX_BYTES:
        raise ErroImportacao(f"O arquivo excede o limite de {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        arquivo.seek(0)
        with zipfile.ZipFile(arquivo) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPACTADO:
                raise ErroImportacao("O arquivo é grande demais depois de descompactado.")
        arquivo.seek(0)
        pasta = load_workbook(arquivo, read_only=True, data_only=True)
        aba = pasta.worksheets[0]
        brutas, vazias_seguidas = [], 0
        for n, valores in enumerate(aba.iter_rows(values_only=True), start=1):
            celulas = [_texto_celula(v) for v in valores[:MAX_COLUNAS]]
            if not any(celulas):
                # Planilhas formatadas costumam ter milhares de linhas vazias no final.
                vazias_seguidas += 1
                if vazias_seguidas > MAX_VAZIAS_SEGUIDAS:
                    break
                continue
            vazias_seguidas = 0
            brutas.append((n, celulas))
            if len(brutas) > MAX_LINHAS + LINHAS_CABECALHO:
                raise ErroImportacao(f"A planilha tem mais de {MAX_LINHAS} linhas. Divida-a em arquivos menores.")
        pasta.close()
    except ErroImportacao:
        raise
    except Exception:
        # Arquivo corrompido, protegido por senha ou que não é uma planilha.
        raise ErroImportacao("Não foi possível ler o arquivo. Verifique se é uma planilha .xlsx válida e sem senha.")
    if not brutas:
        raise ErroImportacao("A planilha está vazia.")

    # Cabeçalho: a linha, entre as primeiras, com mais títulos reconhecidos. Se nenhuma tiver
    # ao menos dois, a primeira com duas ou mais células (títulos soltos ocupam uma só).
    candidatas = [b for b in brutas if b[0] <= LINHAS_CABECALHO]
    pontos = lambda b: sum(1 for c in b[1] if _rotulo_normalizado(c) in _APELIDOS)
    melhor = max(candidatas, key=pontos, default=None)
    if not melhor or pontos(melhor) < 2:
        melhor = next((b for b in candidatas if sum(1 for c in b[1] if c) >= 2), brutas[0])
    dados = [(n, c) for n, c in brutas if n > melhor[0]]
    # Largura: até a última coluna com título ou com algum dado.
    largura = max(
        [max((i + 1 for i, c in enumerate(celulas) if c), default=0) for _, celulas in [melhor] + dados]
    )
    cabecalhos = (melhor[1] + [""] * largura)[:largura]
    linhas = [{"n": n, "c": (c + [""] * largura)[:largura]} for n, c in dados]
    if not cabecalhos or not linhas:
        raise ErroImportacao("A planilha não tem linhas de dados abaixo do cabeçalho.")
    if sum(len(c) for l in linhas for c in l["c"]) > MAX_TEXTO:
        raise ErroImportacao("A planilha tem texto demais. Divida-a em arquivos menores.")
    if len(linhas) > MAX_LINHAS:
        raise ErroImportacao(f"A planilha tem mais de {MAX_LINHAS} linhas. Divida-a em arquivos menores.")
    return cabecalhos, linhas


# ------------------------------------------------- vários arquivos e formatos


@dataclass
class ArquivoLido:
    nome: str
    formato: str            # xlsx | docx | pdf
    cabecalhos: list
    linhas: list            # [{"n": linha no arquivo, "c": [textos]}]
    avisos: list
    sha256: str


def ler_arquivo(arquivo):
    """Lê um arquivo enviado, em qualquer dos formatos aceitos."""
    nome = (getattr(arquivo, "name", "") or "arquivo").replace("\\", "/").rsplit("/", 1)[-1][:120]
    formato = FORMATOS.get("." + nome.lower().rsplit(".", 1)[-1] if "." in nome else "")
    if not formato:
        raise ErroImportacao(f"{nome}: formato não aceito. Envie arquivos .xlsx, .docx ou .pdf.")
    if getattr(arquivo, "size", 0) > MAX_BYTES:
        raise ErroImportacao(f"{nome}: o arquivo excede o limite de {MAX_BYTES // (1024 * 1024)} MB.")
    arquivo.seek(0)
    sha256 = hashlib.sha256(arquivo.read()).hexdigest()
    try:
        if formato == "xlsx":
            cabecalhos, linhas = ler_planilha(arquivo)
            avisos = []
        else:
            from . import documentos   # import tardio: documentos.py usa as definições deste módulo

            cabecalhos, linhas, avisos = (documentos.ler_docx if formato == "docx" else documentos.ler_pdf)(arquivo)
    except ErroImportacao as erro:
        raise ErroImportacao(f"{nome}: {erro}")
    return ArquivoLido(nome, formato, cabecalhos, linhas, avisos, sha256)


def anexar(cabecalhos, linhas, arquivos, lido):
    """Acrescenta um arquivo lido à tabela única da conferência.

    Colunas equivalentes são unificadas: pelo campo reconhecido no título
    ("Disciplina" e "Componente curricular" são a mesma coluna) ou, se o título
    não é reconhecido, pelo próprio título. Cada linha guarda em "f" o índice
    do arquivo de origem. Retorna (cabeçalhos, linhas, arquivos) novos.
    """
    ativos = [a for a in arquivos if not a.get("removido")]
    if len(ativos) >= MAX_ARQUIVOS:
        raise ErroImportacao(f"{lido.nome}: a conferência já tem {MAX_ARQUIVOS} arquivos.")
    if any(a.get("sha256") == lido.sha256 for a in ativos):
        raise ErroImportacao(f"{lido.nome}: este arquivo já está anexado.")

    def chave(titulo, sufixo):
        campo = _APELIDOS.get(_rotulo_normalizado(titulo))
        return f"@{campo}" if campo else (_rotulo_normalizado(titulo) or f"#{sufixo}")

    f = len(arquivos)
    cabecalhos = list(cabecalhos)
    posicao = {}
    for i, titulo in enumerate(cabecalhos):
        posicao.setdefault(chave(titulo, f"a{i}"), i)
    destino, usadas = [], set()
    for j, titulo in enumerate(lido.cabecalhos):
        k = chave(titulo, f"{f}.{j}")
        if k in usadas:                          # título repetido no mesmo arquivo: coluna própria
            k = f"{k}#{f}.{j}"
        usadas.add(k)
        if k not in posicao:
            posicao[k] = len(cabecalhos)
            cabecalhos.append(titulo)
        destino.append(posicao[k])
    if len(cabecalhos) > 2 * MAX_COLUNAS:
        raise ErroImportacao(f"{lido.nome}: os arquivos, juntos, têm colunas demais.")

    largura = len(cabecalhos)
    linhas = [{**l, "c": (l["c"] + [""] * largura)[:largura]} for l in linhas]
    for l in lido.linhas:
        celulas = [""] * largura
        for j, valor in enumerate(l["c"]):
            if j < len(destino) and valor:
                celulas[destino[j]] = valor
        linhas.append({"n": l["n"], "f": f, "c": celulas})
    if len(linhas) > MAX_LINHAS:
        raise ErroImportacao(f"{lido.nome}: os arquivos, juntos, têm mais de {MAX_LINHAS} linhas.")
    if sum(len(c) for l in linhas for c in l["c"]) > MAX_TEXTO:
        raise ErroImportacao(f"{lido.nome}: os arquivos, juntos, têm texto demais.")
    arquivos = arquivos + [{
        "nome": lido.nome, "formato": lido.formato, "linhas": len(lido.linhas), "avisos": lido.avisos, "sha256": lido.sha256,
    }]
    return cabecalhos, linhas, arquivos


def remover_arquivo(linhas, arquivos, f):
    """Retira da conferência as linhas de um arquivo (os índices dos demais não mudam)."""
    arquivos = [{**a, "removido": True} if i == f else a for i, a in enumerate(arquivos)]
    return [l for l in linhas if l.get("f", 0) != f], arquivos


def completar_mapeamento(mapa, cabecalhos):
    """Mantém o mapeamento atual e acrescenta os campos reconhecidos nas colunas novas."""
    mapa = limpar_mapeamento(mapa, len(cabecalhos))
    usadas = set(mapa.values())
    for campo, i in sugerir_mapeamento(cabecalhos).items():
        if campo not in mapa and i not in usadas:
            mapa[campo] = i
    return mapa


# ---------------------------------------------------------------- mapeamento


def sugerir_mapeamento(cabecalhos):
    """{campo: índice da coluna} a partir dos títulos reconhecidos (primeira ocorrência)."""
    mapa = {}
    for i, titulo in enumerate(cabecalhos):
        campo = _APELIDOS.get(_rotulo_normalizado(titulo))
        if campo and campo not in mapa:
            mapa[campo] = i
    return mapa


def limpar_mapeamento(mapa, n_colunas):
    """Descarta campos desconhecidos e índices fora da planilha."""
    limpo = {}
    for campo, i in (mapa or {}).items():
        if campo in CAMPO and isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n_colunas:
            limpo[campo] = i
    return limpo


def erros_do_mapeamento(mapa):
    erros = []
    repetidas = [i for i, n in Counter(mapa.values()).items() if n > 1]
    if repetidas:
        erros.append("Uma mesma coluna da planilha foi associada a mais de um campo.")
    for campo in ("componente", "turma", "data"):
        if campo not in mapa:
            erros.append(f"Associe uma coluna ao campo obrigatório “{CAMPO[campo].rotulo}”.")
    if "horario" not in mapa and not ("inicio" in mapa and "fim" in mapa):
        erros.append("Associe a coluna “Horário (início–término)” ou as colunas “Início” e “Término”.")
    return erros


# -------------------------------------------------------- conversão de valores


def ler_data(texto, semestre=None):
    """Aceita 15/02/2027, 15/2/27, 2027-02-15 e, conhecido o semestre, 15/02 (sem ano),
    como no modelo institucional: o ano é o que coloca a data dentro do semestre."""
    texto = texto.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?", texto)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})", texto)
    if m:
        ano = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return date(ano, int(m[2]), int(m[1]))
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})", texto)
    if m and semestre is not None:
        candidatas = []
        for ano in dict.fromkeys((semestre.data_inicio.year, semestre.data_fim.year)):
            try:
                candidatas.append(date(ano, int(m[2]), int(m[1])))
            except ValueError:
                pass
        if candidatas:
            return next((d for d in candidatas if semestre.data_inicio <= d <= semestre.data_fim), candidatas[0])
    raise ValueError


def ler_hora(texto):
    texto = texto.strip().lower()
    m = re.fullmatch(r"\d{4}-\d{2}-\d{2}[t ](\d{2}):(\d{2}).*", texto)
    if not m:
        m = re.fullmatch(r"(\d{1,2})\s*(?:[:h]\s*(\d{2})?)?(?::\d{2})?\s*(?:min|hs?)?", texto)
    if m:
        return time(int(m[1]), int(m[2] or 0))
    if re.fullmatch(r"0?[.,]\d+", texto):            # fração de dia do Excel (0,5 = 12:00)
        minutos = round(float(texto.replace(",", ".")) * 24 * 60)
        return time(minutos // 60, minutos % 60)
    raise ValueError


def ler_horario(texto):
    """'13h-15h30', '13:00 às 15:30', '08h a 10h' → (início, término)."""
    partes = re.split(r"\s*(?:[-–—]|\bàs\b|\bas\b|\baté\b|\bate\b|\ba\b)\s*", texto.strip(), flags=re.IGNORECASE)
    if len(partes) != 2:
        raise ValueError
    return ler_hora(partes[0]), ler_hora(partes[1])


def _inteiro(texto):
    valor = int(re.sub(r"\s*h(/a)?$", "", texto.strip(), flags=re.IGNORECASE))
    if not 0 <= valor <= 100000:
        raise ValueError
    return valor


# ------------------------------------------------------------------- análise


class Pos(int):
    """Número da linha no arquivo de origem; `f` é o índice do arquivo na conferência."""

    def __new__(cls, n, f=0):
        pos = super().__new__(cls, n)
        pos.f = f
        return pos


@dataclass
class LinhaPlano:
    n: int
    data: date
    inicio: time
    fim: time
    professor: object
    campos: dict
    acao: str = "CRIAR"          # CRIAR | ATUALIZAR | SEM_ALTERACAO
    encontro: object = None


@dataclass
class ComponentePlano:
    nome: str
    turma: str
    atributos: dict
    coordenador: object = None
    existente: object = None
    linhas: list = field(default_factory=list)
    origem: dict = field(default_factory=dict)   # {atributo: linha em que foi informado}

    @property
    def novo(self):
        return self.existente is None

    @property
    def rotulo(self):
        return f"{self.nome} — Turma {self.turma}"


@dataclass
class Analise:
    erros: list = field(default_factory=list)       # [{linha, campo, mensagem}]
    avisos: list = field(default_factory=list)      # [str]
    componentes: list = field(default_factory=list)
    conflitos: list = field(default_factory=list)   # [{tipo, texto}]
    linhas_lidas: int = 0
    arquivos: list = field(default_factory=list)    # nomes dos arquivos, pelo índice "f" das linhas
    pessoas: list = field(default_factory=list)     # nomes não reconhecidos ou associados manualmente

    @property
    def ok(self):
        return not self.erros and bool(self.componentes)

    @property
    def varios_arquivos(self):
        return len([a for a in self.arquivos if a]) > 1

    def nome_arquivo(self, linha):
        f = getattr(linha, "f", 0)
        return self.arquivos[f] if f < len(self.arquivos) and self.arquivos[f] else ""

    def ref(self, linha):
        """'linha 4' ou, havendo vários arquivos, 'linha 4 de cronograma.pdf'."""
        return f"linha {int(linha)}" + (f" de {self.nome_arquivo(linha)}" if self.varios_arquivos else "")

    def erro(self, linha, campo, mensagem):
        eh_linha = isinstance(linha, int)
        self.erros.append({
            "linha": int(linha) if eh_linha else linha, "f": getattr(linha, "f", 0),
            "arquivo": self.nome_arquivo(linha) if eh_linha else "",
            "campo": CAMPO[campo].rotulo if campo in CAMPO else campo, "mensagem": mensagem,
        })

    @property
    def contagem(self):
        acoes = Counter(l.acao for c in self.componentes for l in c.linhas)
        return {
            "linhas": self.linhas_lidas,
            "criar": acoes["CRIAR"], "atualizar": acoes["ATUALIZAR"], "sem_alteracao": acoes["SEM_ALTERACAO"],
            "componentes_novos": sum(1 for c in self.componentes if c.novo),
            "componentes_existentes": sum(1 for c in self.componentes if not c.novo),
            "conflitos": len(self.conflitos),
        }


_TITULOS_DE_PESSOA = re.compile(r"^(?:(?:prof(?:a|essora?)?|dr(?:a)?|me|ma|msc|esp|phd)\b\.?\s*)+")


def _sem_titulo(nome):
    """'Profa. Dra. Ana Lima (substituta)' → 'ana lima' (comparação de nomes vindos de documentos)."""
    limpo = " ".join(re.sub(r"\([^)]*\)", " ", ag.normalizar(nome)).split())
    return _TITULOS_DE_PESSOA.sub("", limpo).strip() or ag.normalizar(nome)


class _Docentes:
    """Resolve o texto das colunas de docente e de coordenador para um usuário do cadastro.

    Nunca cria usuários. Ordem: associação manual feita na conferência; e-mail; nome de
    usuário; nome completo; nome sem títulos (Prof., Dra. …). Nomes ambíguos ou
    desconhecidos ficam pendentes, para associação manual.
    """

    def __init__(self, associacoes=None):
        self.associacoes = associacoes or {}
        self.todos = list(Usuario.docentes())
        self.por_id = {u.id: u for u in self.todos}
        self.consultadas = {}     # {chave: {texto, papel, linhas}} — nomes que precisaram de associação

    def _anotar(self, chave, texto, papel):
        item = self.consultadas.setdefault(chave, {"chave": chave, "texto": texto, "papel": papel, "linhas": 0})
        item["linhas"] += 1

    def resolver(self, texto, papel="docente"):
        """Retorna (usuário ou None, mensagem de erro)."""
        coordenador = papel == "coordenador"
        candidatos = [u for u in self.todos if u.perfil == Usuario.Perfil.COORD] if coordenador else self.todos
        grupo = "coordenadores" if coordenador else "docentes"
        rotulo = "Coordenador" if coordenador else "Docente"
        chave = ag.normalizar(texto)
        if chave in self.associacoes:
            self._anotar(chave, texto, papel)
            escolhido = self.associacoes[chave]
            if escolhido == 0:
                return None, ""            # importar sem docente / usar o coordenador padrão
            usuario = self.por_id.get(escolhido)
            if usuario in candidatos:
                return usuario, ""
        if "@" in chave:
            # E-mail não tem espaços: em PDF, uma célula estreita pode quebrá-lo em várias linhas.
            achados = [u for u in candidatos if u.email == chave.replace(" ", "")]
        else:
            achados = [u for u in candidatos if u.username and u.username == chave]
            achados = achados or [u for u in candidatos if ag.normalizar(u.nome) == chave]
            achados = achados or [u for u in candidatos if _sem_titulo(u.nome) == _sem_titulo(texto)]
        if len(achados) == 1:
            return achados[0], ""
        if chave not in self.associacoes:
            self._anotar(chave, texto, papel)
        if achados:
            return None, f"Há {len(achados)} {grupo} chamados “{texto}”. Informe o e-mail ou associe o nome a um cadastro."
        return None, (f"{rotulo} “{texto}” não encontrado entre os {grupo} ativos. "
                      "Informe o e-mail cadastrado ou associe o nome a um cadastro.")


def _ler_linha(analise, linha, mapa, semestre, docentes):
    """Converte uma linha da planilha. Retorna dict de valores, ou None se houver erro."""
    n, celulas = Pos(linha["n"], linha.get("f", 0)), linha["c"]
    bruto = {campo: celulas[i].strip() if i < len(celulas) else "" for campo, i in mapa.items()}
    erros_antes = len(analise.erros)
    v = {}

    for campo, texto in bruto.items():
        if len(texto) > CAMPO[campo].limite:
            analise.erro(n, campo, f"Texto com mais de {CAMPO[campo].limite} caracteres.")
    for campo in ("componente", "turma", "data"):
        if not bruto.get(campo):
            analise.erro(n, campo, "Campo obrigatório vazio.")

    if bruto.get("data"):
        try:
            v["data"] = ler_data(bruto["data"], semestre)
        except ValueError:
            analise.erro(n, "data", f"Data inválida: “{bruto['data']}”. Use DD/MM/AAAA.")
        else:
            if not (semestre.data_inicio <= v["data"] <= semestre.data_fim):
                analise.erro(n, "data", f"{v['data']:%d/%m/%Y} está fora do semestre {semestre.nome} "
                                        f"({semestre.data_inicio:%d/%m/%Y} a {semestre.data_fim:%d/%m/%Y}).")
    try:
        if bruto.get("inicio") or bruto.get("fim"):
            campo_hora = "inicio"
            v["inicio"] = ler_hora(bruto.get("inicio", ""))
            campo_hora = "fim"
            v["fim"] = ler_hora(bruto.get("fim", ""))
        elif bruto.get("horario"):
            campo_hora = "horario"
            v["inicio"], v["fim"] = ler_horario(bruto["horario"])
        else:
            analise.erro(n, "horario" if "horario" in mapa else "inicio", "Horário não informado.")
    except ValueError:
        analise.erro(n, campo_hora, f"Horário inválido: “{bruto.get(campo_hora, '')}”. Use 13:00 ou 13h30.")
    else:
        if "fim" in v and v["fim"] <= v["inicio"]:
            analise.erro(n, "fim" if "fim" in mapa else "horario", "O término deve ser posterior ao início.")

    v["professor"] = None
    if bruto.get("docente"):
        v["professor"], msg = docentes.resolver(bruto["docente"])
        if msg:
            analise.erro(n, "docente", msg)
    tipo = TIPOS.get(ag.normalizar(bruto.get("tipo", "")))
    if tipo is None:
        analise.erro(n, "tipo", f"Tipo inválido: “{bruto['tipo']}”. Use T, P, T/P ou -.")
    v["campos"] = {c: bruto.get(c, "") for c in CAMPOS_ENCONTRO}
    v["campos"]["tipo"] = tipo or ""

    turno = bruto.get("turno", "")
    if turno and ag.normalizar(turno) not in TURNOS:
        analise.erro(n, "turno", f"Turno inválido: “{turno}”. Use Manhã, Tarde, Noite ou Integral.")
    for campo in ("carga_horaria", "ch_teorica", "ch_pratica"):
        if bruto.get(campo):
            try:
                _inteiro(bruto[campo])
            except ValueError:
                analise.erro(n, campo, f"Número inválido: “{bruto[campo]}”.")
    if bruto.get("semestre") and ag.normalizar(bruto["semestre"]) != ag.normalizar(semestre.nome):
        analise.erro(n, "semestre", f"A linha indica o semestre “{bruto['semestre']}”, mas a importação é para {semestre.nome}.")

    if len(analise.erros) > erros_antes:
        return None
    v["n"] = n
    v["componente"], v["turma"] = bruto["componente"], bruto["turma"]
    v["atributos"] = {c.nome: bruto.get(c.nome, "") for c in CAMPOS if c.do_componente}
    return v


def _resolver_componente(analise, plano, primeira_linha, usuario, semestre, coordenador_padrao, existentes, docentes):
    """Define se o componente será criado ou atualizado e verifica as permissões."""
    existente = existentes.get((ag.normalizar(plano.nome), ag.normalizar(plano.turma)))
    if existente:
        plano.existente, plano.coordenador = existente, existente.coordenador
        if not pode_gerenciar(usuario, existente):
            analise.erro(primeira_linha, "componente", f"{plano.rotulo} já existe e é coordenado por outra pessoa. "
                                                         "Apenas o coordenador responsável ou a administração podem importá-lo.")
        elif existente.bloqueado:
            analise.erro(primeira_linha, "componente", f"{plano.rotulo} está aprovado/publicado. Reabra-o para revisão antes de importar.")
        elif not usuario.eh_admin and not semestre.preenchimento_liberado:
            analise.erro(primeira_linha, "componente", f"{plano.rotulo}: o preenchimento do semestre ainda não foi liberado pela administração.")
        periodo = plano.atributos.get("periodo")
        if periodo and ag.normalizar(periodo) != ag.normalizar(existente.periodo):
            analise.avisos.append(f"{plano.rotulo} já existe: o cadastro atual (período “{existente.periodo or '—'}”) "
                                  "foi mantido; os dados de cadastro da planilha não são aplicados a componentes existentes.")
        return

    texto = plano.atributos.get("coordenador", "").strip()
    indicado, msg = docentes.resolver(texto, "coordenador") if texto else (None, "")
    if msg:
        analise.erro(primeira_linha, "coordenador", msg)
    elif usuario.eh_admin:
        plano.coordenador = indicado or coordenador_padrao
        if not plano.coordenador:
            analise.erro(primeira_linha, "coordenador", f"{plano.rotulo} é novo: informe o coordenador no arquivo "
                                                         "ou escolha um coordenador padrão ao enviar.")
    else:
        # Coordenador importa apenas componentes sob sua própria responsabilidade.
        if indicado and indicado.id != usuario.id:
            analise.erro(primeira_linha, "coordenador", f"{plano.rotulo}: você só pode criar componentes sob a sua coordenação "
                                                         f"(o arquivo indica {indicado.nome}).")
        plano.coordenador = usuario


def _casar_com_existentes(plano):
    """Define a ação de cada linha frente aos encontros já cadastrados do componente."""
    livres = defaultdict(list)
    for e in plano.existente.encontros.select_related("professor"):
        livres[(e.data, e.hora_inicio, e.hora_fim)].append(e)
    usados = set()

    def tomar(chave, criterio):
        for e in livres.get(chave, ()):
            if e.id not in usados and criterio(e):
                usados.add(e.id)
                return e
        return None

    # 1º: mesmo dia, horário e docente; 2º: encontro ainda vazio no mesmo dia e horário.
    for l in plano.linhas:
        prof_id = l.professor.id if l.professor else None
        l.encontro = tomar((l.data, l.inicio, l.fim), lambda e: e.professor_id == prof_id)
    for l in plano.linhas:
        if l.encontro is None:
            l.encontro = tomar((l.data, l.inicio, l.fim), lambda e: not e.professor_id and not e.conteudo.strip())
    for l in plano.linhas:
        if l.encontro is None:
            continue
        e = l.encontro
        muda = (l.professor and e.professor_id != l.professor.id) or any(
            valor and valor != getattr(e, campo) for campo, valor in l.campos.items()
        )
        l.acao = "ATUALIZAR" if muda else "SEM_ALTERACAO"


def _prever_conflitos(analise, semestre):
    """Conflitos que existirão após a importação e que envolvem as linhas da planilha."""
    docentes = {l.professor.id: l.professor.nome for c in analise.componentes for l in c.linhas if l.professor}
    agenda = montar_agenda(Encontro.objects.filter(Q(componente__semestre=semestre) | Q(professor_id__in=docentes)))
    agenda.calendarios.update(calendarios_de({semestre.id}))
    rotulos, tocados = {}, []
    for i, plano in enumerate(analise.componentes):
        comp = plano.existente
        comp_id = comp.id if comp else f"novo-{i}"
        turma = ag.chave_turma(
            semestre.id,
            comp.curso if comp else plano.atributos.get("curso") or Componente._meta.get_field("curso").default,
            comp.periodo if comp else plano.atributos.get("periodo", ""),
            plano.turma,
        )
        for l in plano.linhas:
            prof_id = l.professor.id if l.professor else None
            if l.acao == "CRIAR":
                id_ = f"L{getattr(l.n, 'f', 0)}.{int(l.n)}"
                agenda.adicionar(ag.Aula(id_, comp_id, semestre.id, turma, prof_id, l.data, l.inicio, l.fim))
            elif l.acao == "ATUALIZAR" and prof_id:
                id_ = l.encontro.id
                agenda.alterar(id_, professor_id=prof_id)
            else:
                continue
            tocados.append(id_)
            rotulos[id_] = f"{analise.ref(l.n)} ({plano.rotulo})"

    achados = ag.ordenar(agenda.conflitos(tocados))
    outros = {i for c in achados for i in c.ids if i not in rotulos}
    for e in Encontro.objects.filter(pk__in=outros).select_related("componente"):
        rotulos[e.id] = f"{e.componente} — já cadastrado"
    nomes = dict(Usuario.objects.filter(pk__in={c.professor_id for c in achados if c.professor_id}).values_list("id", "nome"))
    titulos = dict(Conflito.Tipo.choices)
    for c in achados:
        quando = f"{c.data:%d/%m/%Y} {c.inicio:%H:%M}–{c.fim:%H:%M}"
        if c.tipo == ag.CALENDARIO:
            texto = f"{rotulos[c.a]} em {c.data:%d/%m/%Y}: " + (
                f"data bloqueada ({c.descricao})" if c.motivo == ag.DATA_BLOQUEADA else c.descricao)
        elif c.tipo == ag.TURMA:
            texto = f"Mesma turma em dois componentes, {quando}: {rotulos[c.a]} × {rotulos[c.b]}"
        else:
            texto = f"{nomes.get(c.professor_id, 'Docente')} em dois encontros, {quando}: {rotulos[c.a]} × {rotulos[c.b]}"
        analise.conflitos.append({"tipo": c.tipo, "titulo": titulos[c.tipo], "texto": texto})


def analisar(cabecalhos, linhas, mapeamento, usuario, semestre, coordenador_padrao=None, arquivos=(), associacoes=None):
    """Valida as linhas (de um ou de vários arquivos) e planeja a importação, sem gravar nada.

    `arquivos` são os nomes dos arquivos de origem, na ordem do índice "f" das linhas;
    `associacoes` é o de-para {nome normalizado: id do usuário, ou 0 para ignorar}.
    """
    analise = Analise(linhas_lidas=len(linhas), arquivos=list(arquivos))
    mapa = limpar_mapeamento(mapeamento, len(cabecalhos))
    for msg in erros_do_mapeamento(mapa):
        analise.erro("—", "Mapeamento", msg)
    if analise.erros:
        return analise

    docentes = _Docentes(associacoes)
    grupos, vistos = {}, {}
    for linha in linhas:
        v = _ler_linha(analise, linha, mapa, semestre, docentes)
        if v is None:
            continue
        chave = (ag.normalizar(v["componente"]), ag.normalizar(v["turma"]))
        plano = grupos.get(chave)
        if plano is None:
            plano = grupos[chave] = ComponentePlano(v["componente"], v["turma"], {})
        # Atributos de cadastro: valem para o componente inteiro e não podem divergir entre linhas.
        for campo, valor in v["atributos"].items():
            if not valor:
                continue
            anterior = plano.atributos.get(campo)
            if anterior is None:
                plano.atributos[campo], plano.origem[campo] = valor, v["n"]
            elif ag.normalizar(anterior) != ag.normalizar(valor):
                analise.erro(v["n"], campo, f"“{valor}” diverge de “{anterior}”, informado para o mesmo componente na {analise.ref(plano.origem[campo])}.")
        prof_id = v["professor"].id if v["professor"] else None
        duplicata = (chave, v["data"], v["inicio"], v["fim"], prof_id, ag.normalizar(v["campos"]["grupos"]))
        if duplicata in vistos:
            analise.erro(v["n"], "data", f"Linha repetida: mesmo componente, data, horário, docente e grupo da {analise.ref(vistos[duplicata])}.")
            continue
        vistos[duplicata] = v["n"]
        plano.linhas.append(LinhaPlano(v["n"], v["data"], v["inicio"], v["fim"], v["professor"], v["campos"]))

    existentes = {
        (ag.normalizar(c.nome), ag.normalizar(c.turma)): c
        for c in Componente.objects.filter(semestre=semestre).select_related("coordenador", "semestre")
    }
    for plano in grupos.values():
        if not plano.linhas:
            continue
        _resolver_componente(analise, plano, plano.linhas[0].n, usuario, semestre, coordenador_padrao, existentes, docentes)
        if plano.existente:
            _casar_com_existentes(plano)
        analise.componentes.append(plano)

    analise.pessoas = sorted(docentes.consultadas.values(), key=lambda p: (p["papel"], p["texto"]))
    for pessoa in analise.pessoas:
        pessoa["valor"] = (associacoes or {}).get(pessoa["chave"])
    analise.erros.sort(key=lambda e: (not isinstance(e["linha"], int), e["f"], e["linha"] if isinstance(e["linha"], int) else 0))
    if not analise.erros:
        if not analise.componentes:
            analise.erro("—", "Planilha", "Nenhuma linha válida para importar.")
        else:
            _prever_conflitos(analise, semestre)
    return analise


# ----------------------------------------------------------------- aplicação


def _grade_semanal(linhas):
    """Horários semanais do componente novo: combinações (dia, início, término) que se
    repetem em pelo menos duas datas; se nenhuma se repete, todas as combinações."""
    datas = defaultdict(set)
    for l in linhas:
        datas[(l.data.weekday(), l.inicio, l.fim)].add(l.data)
    regulares = [k for k, d in datas.items() if len(d) >= 2]
    return sorted(regulares or datas)


def _turno(linhas):
    primeira = min(l.inicio for l in linhas)
    return "MANHA" if primeira.hour < 12 else "TARDE" if primeira.hour < 18 else "NOITE"


@transaction.atomic
def aplicar(analise, usuario, semestre, arquivo_nome=""):
    """Grava o plano de importação. Deve receber uma análise recém-calculada e sem erros."""
    if not analise.ok:
        raise ErroImportacao("A planilha tem erros e não pode ser importada.")
    agora = timezone.now()
    docentes_afetados = set()
    resumo = {"componentes": [], "criados": 0, "atualizados": 0, "sem_alteracao": 0}

    for plano in analise.componentes:
        comp = plano.existente
        if comp is None:
            a = plano.atributos
            comp = Componente.objects.create(
                nome=plano.nome[:150], turma=plano.turma[:30], semestre=semestre, coordenador=plano.coordenador,
                curso=a.get("curso") or Componente._meta.get_field("curso").default,
                periodo=a.get("periodo", ""), codigo=a.get("codigo", ""),
                turno=TURNOS.get(ag.normalizar(a.get("turno", ""))) or _turno(plano.linhas),
                carga_horaria=_inteiro(a["carga_horaria"]) if a.get("carga_horaria") else 0,
                ch_teorica=_inteiro(a["ch_teorica"]) if a.get("ch_teorica") else 0,
                ch_pratica=_inteiro(a["ch_pratica"]) if a.get("ch_pratica") else 0,
                data_inicio=min(l.data for l in plano.linhas), data_fim=max(l.data for l in plano.linhas),
            )
            HorarioSemanal.objects.bulk_create([
                HorarioSemanal(componente=comp, dia_semana=d, hora_inicio=i, hora_fim=f)
                for d, i, f in _grade_semanal(plano.linhas)
            ])
        else:
            # Trava o componente: a situação pode ter mudado desde a análise.
            comp = Componente.objects.select_for_update().get(pk=comp.pk)
            if comp.bloqueado:
                raise ErroImportacao(f"{plano.rotulo} foi aprovado enquanto a importação era preparada.")
        comp.professores.add(*{l.professor for l in plano.linhas if l.professor})

        regulares = {(d, i) for d, i, _ in datas_previstas(comp)}
        contagem = Counter()
        for l in plano.linhas:
            contagem[l.acao] += 1
            if l.acao == "CRIAR":
                campos = dict(l.campos)
                campos["ch"] = campos["ch"] or ch_padrao(l.inicio, l.fim)
                Encontro.objects.create(
                    componente=comp, data=l.data, hora_inicio=l.inicio, hora_fim=l.fim, professor=l.professor,
                    excepcional=(l.data, l.inicio) not in regulares, atualizado_por=usuario, atualizado_em=agora, **campos,
                )
                docentes_afetados.add(l.professor.id if l.professor else None)
            elif l.acao == "ATUALIZAR":
                e = l.encontro
                docentes_afetados.add(e.professor_id)
                if l.professor:
                    e.professor = l.professor
                    docentes_afetados.add(l.professor.id)
                for campo, valor in l.campos.items():
                    if valor:
                        setattr(e, campo, valor)
                e.versao += 1
                e.atualizado_por, e.atualizado_em = usuario, agora
                e.save()
        registrar(
            usuario, comp, "Importação de planilha", "",
            f"{arquivo_nome}: {contagem['CRIAR']} encontro(s) criado(s), {contagem['ATUALIZAR']} atualizado(s), "
            f"{contagem['SEM_ALTERACAO']} sem alteração" + (" — componente criado" if plano.novo else ""),
        )
        resumo["componentes"].append({
            "id": comp.id, "rotulo": str(comp), "novo": plano.novo, "criados": contagem["CRIAR"],
            "atualizados": contagem["ATUALIZAR"], "sem_alteracao": contagem["SEM_ALTERACAO"],
        })
        resumo["criados"] += contagem["CRIAR"]
        resumo["atualizados"] += contagem["ATUALIZAR"]
        resumo["sem_alteracao"] += contagem["SEM_ALTERACAO"]

    sincronizar_conflitos(docentes_afetados, {semestre.id})
    resumo["conflitos_previstos"] = [c["texto"] for c in analise.conflitos][:100]
    resumo["conflitos_por_tipo"] = dict(Counter(c["tipo"] for c in analise.conflitos))
    return resumo


# ------------------------------------------------------- geração de planilhas

CABECALHOS_MODELO = (
    "Componente curricular", "Código", "Período", "Turma", "Turno", "Data", "Horário", "Conteúdo",
    "Tipo", "Atividades", "Recursos", "Grupos", "Docente (e-mail)", "CH", "Local",
)
LINHA_MODELO = (
    "Nome do componente", "COD-01", "4º", "A", "Tarde", date(2027, 2, 15), "13h-15h30",
    "Tema da aula", "T", "Aula expositiva dialogada", "Datashow e quadro", "TODOS", "", "3h", "Sala 101",
)


def gerar_planilha(linhas, cabecalhos=CABECALHOS_MODELO, titulo="CRONOGRAMA DE AULAS — planilha de importação (uma linha por encontro)"):
    """Monta um .xlsx em memória (modelo para download, exemplos e testes)."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    pasta = Workbook()
    aba = pasta.active
    aba.title = "Cronograma"
    if titulo:
        aba.append([titulo])
        aba["A1"].font = Font(bold=True, size=12)
        aba.append([])
    aba.append(list(cabecalhos))
    for celula in aba[aba.max_row]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="405F91")
    for linha in linhas:
        aba.append(list(linha))
    for coluna in aba.columns:
        letra = coluna[0].column_letter
        largura = max((len(str(c.value)) for c in coluna[2 if titulo else 0:] if c.value is not None), default=8)
        aba.column_dimensions[letra].width = min(max(largura + 2, 10), 45)
    for linha in aba.iter_rows():
        for celula in linha:
            if isinstance(celula.value, date):
                celula.number_format = "DD/MM/YYYY"
    saida = BytesIO()
    pasta.save(saida)
    return saida.getvalue()
