"""Agenda em memória: implementação única e determinística das regras de conflito.

Não acessa o banco. Opera sobre registros simples (`Aula`) e é usada por:

- `services.sincronizar_conflitos` (persistência dos conflitos);
- `importacao` (prévia dos conflitos que a planilha causará);
- `sugestoes` (verificação de cada remanejamento proposto).

Regras (todas com intervalos semiabertos: 14–16 e 16–18 não se sobrepõem):

DOCENTE     mesmo docente em dois encontros distintos, na mesma data, com
            horários sobrepostos — em quaisquer componentes e semestres.
TURMA       mesma turma (semestre + curso + período + turma) em encontros
            sobrepostos de componentes DIFERENTES. Linhas do mesmo componente
            no mesmo horário representam vários docentes/grupos da mesma aula
            e não conflitam. Sem período ou turma informados não há dado
            confiável para identificar a turma, e a regra não se aplica.
CALENDARIO  encontro em data bloqueada (feriado/bloqueio) ou fora do período
            letivo do semestre.
"""
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time
from typing import NamedTuple

DOCENTE, TURMA, CALENDARIO = "DOCENTE", "TURMA", "CALENDARIO"
DATA_BLOQUEADA, FORA_DO_SEMESTRE = "DATA_BLOQUEADA", "FORA_DO_SEMESTRE"


def normalizar(texto):
    """Minúsculas, sem acentos e com espaços simples — para comparar rótulos."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.casefold().split())


def chave_turma(semestre_id, curso, periodo, turma):
    """Identidade da turma, ou None quando os dados não permitem identificá-la.

    "4º", "4o" e "4º período" são o mesmo período; "A" e "a" a mesma turma.
    """
    periodo, turma = normalizar(periodo), normalizar(turma)
    if not periodo or not turma:
        return None
    digitos = re.sub(r"\D", "", periodo)
    return (semestre_id, normalizar(curso), digitos or periodo, turma)


@dataclass
class Aula:
    id: object
    componente_id: object
    semestre_id: object
    turma: object            # resultado de chave_turma() ou None
    professor_id: object     # None = sem docente
    data: date
    inicio: time
    fim: time


@dataclass(frozen=True)
class Calendario:
    inicio: date
    fim: date
    bloqueadas: dict = field(default_factory=dict)   # {date: descrição}

    def restricao(self, dia):
        """(motivo, descrição) se a data viola o calendário; senão None."""
        if dia in self.bloqueadas:
            return DATA_BLOQUEADA, self.bloqueadas[dia]
        if not (self.inicio <= dia <= self.fim):
            return FORA_DO_SEMESTRE, f"fora do período letivo ({self.inicio:%d/%m/%Y} a {self.fim:%d/%m/%Y})"
        return None


class Achado(NamedTuple):
    """Um conflito detectado. `a` < `b` na ordenação dos ids; `b` é None em CALENDARIO."""

    tipo: str
    a: object
    b: object
    professor_id: object
    data: date
    inicio: time
    fim: time
    motivo: str = ""
    descricao: str = ""

    @property
    def chave(self):
        return (self.tipo, self.a, self.b, self.professor_id, self.motivo)

    @property
    def ids(self):
        return (self.a,) if self.b is None else (self.a, self.b)


def _ordem(i):
    """Permite ordenar ids inteiros (banco) e textuais (linhas de planilha) juntos."""
    return (isinstance(i, str), i)


def sobrepoe(ini_a, fim_a, ini_b, fim_b):
    return ini_a < fim_b and ini_b < fim_a


class Agenda:
    def __init__(self, aulas=(), calendarios=None):
        self.aulas = {}
        self.calendarios = calendarios or {}
        self._prof = defaultdict(set)    # (professor, data) -> ids
        self._turma = defaultdict(set)   # (turma, data) -> ids
        self._comp = defaultdict(set)    # (componente, data) -> ids
        for a in aulas:
            self.adicionar(a)

    # ------------------------------------------------------------- manutenção

    def _indexar(self, a, incluir):
        op = set.add if incluir else set.discard
        if a.professor_id:
            op(self._prof[(a.professor_id, a.data)], a.id)
        if a.turma:
            op(self._turma[(a.turma, a.data)], a.id)
        op(self._comp[(a.componente_id, a.data)], a.id)

    def adicionar(self, aula):
        self.aulas[aula.id] = aula
        self._indexar(aula, True)

    def remover(self, id_):
        self._indexar(self.aulas.pop(id_), False)

    def alterar(self, id_, **campos):
        """Altera campos de uma aula mantendo os índices. Retorna os valores anteriores."""
        a = self.aulas[id_]
        anteriores = {c: getattr(a, c) for c in campos}
        self._indexar(a, False)
        for c, v in campos.items():
            setattr(a, c, v)
        self._indexar(a, True)
        return anteriores

    # ---------------------------------------------------------------- consultas

    def _par(self, tipo, x, y, professor_id=None):
        a, b = (x, y) if _ordem(x.id) < _ordem(y.id) else (y, x)
        return Achado(tipo, a.id, b.id, professor_id, x.data, max(x.inicio, y.inicio), min(x.fim, y.fim))

    def conflitos_de(self, id_):
        """Todos os conflitos em que a aula está envolvida."""
        a = self.aulas[id_]
        achados = set()
        if a.professor_id:
            for oid in self._prof[(a.professor_id, a.data)]:
                o = self.aulas[oid]
                if oid != id_ and sobrepoe(a.inicio, a.fim, o.inicio, o.fim):
                    achados.add(self._par(DOCENTE, a, o, a.professor_id))
        if a.turma:
            for oid in self._turma[(a.turma, a.data)]:
                o = self.aulas[oid]
                if o.componente_id != a.componente_id and sobrepoe(a.inicio, a.fim, o.inicio, o.fim):
                    achados.add(self._par(TURMA, a, o))
        calendario = self.calendarios.get(a.semestre_id)
        restricao = calendario.restricao(a.data) if calendario else None
        if restricao:
            achados.add(Achado(CALENDARIO, a.id, None, None, a.data, a.inicio, a.fim, *restricao))
        return achados

    def conflitos(self, ids=None):
        """Conjunto de todos os conflitos (ou dos que envolvem `ids`)."""
        achados = set()
        for id_ in (self.aulas if ids is None else ids):
            achados |= self.conflitos_de(id_)
        return achados

    def ocupantes(self, indice, chave, dia, inicio, fim, ignorar=()):
        """Ids das aulas de um índice ('prof', 'turma' ou 'comp') que ocupam o intervalo."""
        mapa = {"prof": self._prof, "turma": self._turma, "comp": self._comp}[indice]
        return [
            i for i in mapa.get((chave, dia), ())
            if i not in ignorar and sobrepoe(inicio, fim, self.aulas[i].inicio, self.aulas[i].fim)
        ]


def ordenar(achados):
    """Ordem estável e determinística para exibição e para o motor de sugestões."""
    return sorted(achados, key=lambda c: (c.data, c.inicio, c.tipo, _ordem(c.a), _ordem(c.b) if c.b is not None else (False, 0), c.motivo))
