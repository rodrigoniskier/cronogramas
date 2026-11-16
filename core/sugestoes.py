"""Motor de sugestões de remanejamento.

Para cada conflito ativo, propõe ações que o eliminam sem criar outro:

MOVER            muda data/horário da aula inteira (todas as linhas do mesmo componente,
                 dia e horário — isto é, todos os docentes/grupos daquela aula);
TROCAR_DOCENTE   substitui o docente de uma linha (apenas em conflitos docentes).

Restrições rígidas (uma sugestão que viole qualquer uma nunca é produzida nem aplicada):
  R1  nenhum docente da aula tem outro encontro sobreposto no novo horário;
  R2  a turma não tem aula de outro componente sobreposta, nem o próprio componente
      tem outro encontro sobreposto;
  R3  a data está dentro do período do componente e do semestre e não é bloqueada;
  R4  dia útil (segunda a sexta) ou dia em que o componente já tem aula na grade; nunca domingo;
  R5  duração preservada, entre 07:00 e 22:30;
  R6  somente cronogramas em elaboração são alterados (aprovados/publicados, nunca);
  R7  o substituto é docente ativo vinculado ao componente e está livre no horário;
  R8  a ação não cria nenhum conflito novo (verificado com as regras de core/agenda.py).

Preferências flexíveis (custo; menor é melhor) — ver PESOS.

Avaliação do OR-Tools CP-SAT: o problema real é pequeno (dezenas de conflitos, poucas
centenas de horários candidatos por aula) e cabe em uma busca com retrocesso e poda
(branch and bound) em Python puro, determinística e auditável. O CP-SAT acrescentaria
uma dependência binária de dezenas de MB — incompatível com o limite da função
serverless usada na implantação — sem ganho perceptível nesta escala. A interface
`planejar` isola a busca: trocá-la por CP-SAT não afeta o restante do sistema.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Q

from . import agenda as ag
from .models import Componente, Encontro, Usuario
from .services import calendarios_de, montar_agenda

JANELA = (time(7, 0), time(22, 30))
PASSO_MINUTOS = 30
TURNOS = {
    "MANHA": (time(7, 0), time(13, 0)),
    "TARDE": (time(13, 0), time(19, 0)),
    "NOITE": (time(18, 0), time(22, 30)),
    "INTEGRAL": (time(7, 0), time(19, 0)),
}
PESOS = {
    "dia": 1,              # por dia de distância da data original
    "horario": 10,         # mudar o horário de início
    "turno": 15,           # sair do turno do componente
    "dia_atipico": 5,      # dia da semana em que o componente não costuma ter aula
    "linha_extra": 2,      # por docente/grupo adicional na aula movida
    "troca_docente": 6,    # substituir o docente
    "carga_no_dia": 2,     # por encontro que o substituto já tem no mesmo dia
    "nao_resolvido": 10_000,
}
DIAS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
MOVER, TROCAR = "MOVER", "TROCAR_DOCENTE"


@dataclass(frozen=True)
class CompInfo:
    id: int
    rotulo: str
    semestre_id: int
    editavel: bool          # em elaboração (R6)
    turno: str
    inicio: date
    fim: date
    dias: frozenset         # dias da semana da grade
    vinculados: frozenset   # docentes ativos vinculados (R7)


@dataclass
class Contexto:
    semestre: object
    agenda: ag.Agenda
    comps: dict
    versoes: dict           # {encontro_id: versao} — detecta dados alterados após a sugestão
    docentes: dict          # {usuario_id: nome}


@dataclass(frozen=True)
class Acao:
    tipo: str
    encontros: tuple        # ids (a aula inteira em MOVER; uma linha em TROCAR_DOCENTE)
    componente_id: int
    data: date = None
    inicio: time = None
    fim: time = None
    professor_id: int = None
    custo: int = 0
    motivos: tuple = ()     # justificativa do custo, para exibição
    desvio: int = 0         # minutos entre o novo início e o original (critério de desempate)

    @property
    def ordem(self):
        return (self.custo, self.tipo, self.desvio, self.encontros, self.data or date.min,
                self.inicio or time.min, self.professor_id or 0)


@dataclass
class Sugestao:
    acao: Acao
    descricao: str
    resolve: list           # conflitos (Achado) eliminados
    carga: dict             # dados para aplicar (ids, versões e alvo)


@dataclass
class Plano:
    sugestoes: list = field(default_factory=list)
    sem_solucao: list = field(default_factory=list)      # [(Achado, diagnóstico)]
    fora_de_alcance: list = field(default_factory=list)  # [(Achado, motivo)]
    custo: int = 0
    completa: bool = True   # a busca percorreu todas as combinações dos candidatos considerados
    nos: int = 0
    total: int = 0


# ------------------------------------------------------------------ contexto


def montar_contexto(semestre):
    """Carrega do banco o necessário para sugerir remanejamentos em um semestre."""
    encontros = Encontro.objects.filter(
        Q(componente__semestre=semestre) | Q(data__range=(semestre.data_inicio, semestre.data_fim))
    )
    agenda = montar_agenda(encontros)
    agenda.calendarios.update(calendarios_de({semestre.id}))
    docentes = dict(Usuario.docentes().values_list("id", "nome"))
    comps = {}
    componentes = Componente.objects.filter(
        pk__in={a.componente_id for a in agenda.aulas.values()}
    ).prefetch_related("horarios", "professores")
    for c in componentes:
        vinculados = {p.id for p in c.professores.all()} | {c.coordenador_id}
        comps[c.id] = CompInfo(
            id=c.id, rotulo=str(c), semestre_id=c.semestre_id, editavel=not c.bloqueado, turno=c.turno,
            inicio=max(c.data_inicio, semestre.data_inicio), fim=min(c.data_fim, semestre.data_fim),
            dias=frozenset(h.dia_semana for h in c.horarios.all()),
            vinculados=frozenset(vinculados & docentes.keys()),
        )
    return Contexto(semestre, agenda, comps, dict(encontros.values_list("id", "versao")), docentes)


def conflitos_do_semestre(ctx):
    """Conflitos atuais (recalculados) que envolvem encontros do semestre, em ordem estável."""
    do_semestre = [i for i, a in ctx.agenda.aulas.items() if a.semestre_id == ctx.semestre.id]
    return ag.ordenar(ctx.agenda.conflitos(do_semestre))


# ------------------------------------------------------------- regras rígidas


def _minutos(t):
    return t.hour * 60 + t.minute


def _hora(minutos):
    return time(minutos // 60, minutos % 60)


def bloco(agenda, id_):
    """Ids de todas as linhas da mesma aula (mesmo componente, dia e horário)."""
    a = agenda.aulas[id_]
    return tuple(sorted(
        i for i in agenda.ocupantes("comp", a.componente_id, a.data, a.inicio, a.fim)
        if (agenda.aulas[i].inicio, agenda.aulas[i].fim) == (a.inicio, a.fim)
    ))


def _motivo_slot(ctx, comp, aulas, ids, dia, inicio, fim):
    """Código da primeira restrição rígida violada pelo novo horário, ou None (R1–R4)."""
    if not (comp.inicio <= dia <= comp.fim):
        return "periodo"
    if dia.weekday() == 6 or (dia.weekday() == 5 and 5 not in comp.dias):
        return "dia"
    calendario = ctx.agenda.calendarios.get(comp.semestre_id)
    if calendario and calendario.restricao(dia):
        return "calendario"
    if ctx.agenda.ocupantes("comp", comp.id, dia, inicio, fim, ids):
        return "componente"
    turma = aulas[0].turma
    if turma and ctx.agenda.ocupantes("turma", turma, dia, inicio, fim, ids):
        return "turma"
    for a in aulas:
        if a.professor_id and ctx.agenda.ocupantes("prof", a.professor_id, dia, inicio, fim, ids):
            return "docente"
    return None


def _aplicar(agenda, acao):
    if acao.tipo == MOVER:
        return [(i, agenda.alterar(i, data=acao.data, inicio=acao.inicio, fim=acao.fim)) for i in acao.encontros]
    return [(i, agenda.alterar(i, professor_id=acao.professor_id)) for i in acao.encontros]


def _desfazer(agenda, anteriores):
    for i, campos in reversed(anteriores):
        agenda.alterar(i, **campos)


def efeito(agenda, acao):
    """(conflitos eliminados, conflitos criados) pela ação, segundo as regras da agenda."""
    antes = {c.chave: c for i in acao.encontros for c in agenda.conflitos_de(i)}
    anteriores = _aplicar(agenda, acao)
    depois = {c.chave: c for i in acao.encontros for c in agenda.conflitos_de(i)}
    _desfazer(agenda, anteriores)
    return ([c for k, c in antes.items() if k not in depois], [c for k, c in depois.items() if k not in antes])


def violacoes(ctx, acao):
    """Verificação completa de uma ação contra o estado atual. Lista vazia = ação válida.

    É a verificação que vale: roda na geração (sobre os candidatos escolhidos) e de novo,
    com dados recém-lidos do banco, antes de qualquer gravação.
    """
    agenda = ctx.agenda
    if not acao.encontros or any(i not in agenda.aulas for i in acao.encontros):
        return ["Um dos encontros não existe mais."]
    aulas = [agenda.aulas[i] for i in acao.encontros]
    comp = ctx.comps.get(aulas[0].componente_id)
    if comp is None or comp.id != acao.componente_id or comp.semestre_id != ctx.semestre.id:
        return ["O encontro não pertence ao componente/semestre informado."]
    if not comp.editavel:
        return [f"{comp.rotulo} está aprovado/publicado e não pode ser alterado."]
    erros = []
    if acao.tipo == MOVER:
        if tuple(sorted(acao.encontros)) != bloco(agenda, acao.encontros[0]):
            return ["As linhas desta aula mudaram desde que a sugestão foi gerada."]
        a = aulas[0]
        if not (acao.data and acao.inicio and acao.fim) or acao.fim <= acao.inicio:
            return ["Horário de destino inválido."]
        if _minutos(acao.fim) - _minutos(acao.inicio) != _minutos(a.fim) - _minutos(a.inicio):
            erros.append("A duração da aula deve ser preservada.")
        if acao.inicio < JANELA[0] or acao.fim > JANELA[1]:
            erros.append("Horário fora da janela de aulas (07:00–22:30).")
        if (acao.data, acao.inicio) == (a.data, a.inicio):
            erros.append("O destino é igual ao horário atual.")
        motivo = _motivo_slot(ctx, comp, aulas, set(acao.encontros), acao.data, acao.inicio, acao.fim)
        if motivo:
            erros.append({
                "periodo": "A data está fora do período do componente.",
                "dia": "O dia da semana não é permitido para este componente.",
                "calendario": "A data é bloqueada ou está fora do período letivo.",
                "componente": "O componente já tem outro encontro nesse horário.",
                "turma": "A turma já tem aula de outro componente nesse horário.",
                "docente": "Um dos docentes da aula já tem outro encontro nesse horário.",
            }[motivo])
    elif acao.tipo == TROCAR:
        (a,) = aulas
        if acao.professor_id == a.professor_id or acao.professor_id not in comp.vinculados:
            erros.append("O substituto deve ser outro docente ativo vinculado ao componente.")
        elif agenda.ocupantes("prof", acao.professor_id, a.data, a.inicio, a.fim):
            erros.append("O substituto já tem outro encontro nesse horário.")
    else:
        return ["Tipo de ação desconhecido."]
    if not erros:
        resolvidos, criados = efeito(agenda, acao)
        if criados:
            erros.append("A ação criaria um novo conflito.")
        elif not resolvidos:
            erros.append("A ação não resolve mais nenhum conflito (os dados mudaram).")
    return erros


# ---------------------------------------------------------------- candidatos


def _movimentos(ctx, id_, limite, rejeitados):
    """Até `limite` movimentos válidos e de menor custo para a aula do encontro.

    No máximo um por data (o de menor custo; em empate, o horário mais próximo do
    original), para que as sugestões sejam alternativas de fato distintas.
    """
    agenda = ctx.agenda
    ids = bloco(agenda, id_)
    aulas = [agenda.aulas[i] for i in ids]
    a, comp = aulas[0], ctx.comps[aulas[0].componente_id]
    ignorar = set(ids)
    duracao = _minutos(a.fim) - _minutos(a.inicio)
    inicios = [_minutos(a.inicio)] + [
        m for m in range(_minutos(JANELA[0]), _minutos(JANELA[1]) - duracao + 1, PASSO_MINUTOS) if m != _minutos(a.inicio)
    ]
    turno = TURNOS.get(comp.turno)
    no_turno = turno and turno[0] <= a.inicio and a.fim <= turno[1]
    base = PESOS["linha_extra"] * (len(ids) - 1)

    # Datas do período em ordem de proximidade da data original (empate: a mais cedo).
    n_dias = (comp.fim - comp.inicio).days + 1
    datas = sorted((comp.inicio + timedelta(days=d) for d in range(max(n_dias, 0))), key=lambda d: (abs((d - a.data).days), d))
    melhores = []
    for dia in datas:
        distancia = abs((dia - a.data).days) * PESOS["dia"]
        if len(melhores) >= limite and base + distancia > melhores[-1].custo:
            break       # datas mais distantes só custam mais
        atipico = bool(comp.dias) and dia.weekday() not in comp.dias
        do_dia = None
        for m in inicios:
            inicio, fim = _hora(m), _hora(m + duracao)
            if (dia, inicio) == (a.data, a.inicio):
                continue
            motivo = _motivo_slot(ctx, comp, aulas, ignorar, dia, inicio, fim)
            if motivo:
                rejeitados[motivo] = rejeitados.get(motivo, 0) + 1
                continue
            custo, motivos = base + distancia, []
            if dia != a.data:
                dias = abs((dia - a.data).days)
                motivos.append(f"{dias} dia{'s' if dias > 1 else ''} de diferença")
            if inicio != a.inicio:
                custo += PESOS["horario"]
                motivos.append("muda o horário")
            else:
                motivos.append("mantém o horário")
            if no_turno and not (turno[0] <= inicio and fim <= turno[1]):
                custo += PESOS["turno"]
                motivos.append("fora do turno do componente")
            if atipico:
                custo += PESOS["dia_atipico"]
                motivos.append(f"{DIAS[dia.weekday()]} não é dia habitual do componente")
            if len(ids) > 1:
                motivos.append(f"move os {len(ids)} docentes/grupos da aula")
            acao = Acao(MOVER, ids, comp.id, dia, inicio, fim, None, custo, tuple(motivos), abs(m - _minutos(a.inicio)))
            if do_dia is None or acao.ordem < do_dia.ordem:
                do_dia = acao
        if do_dia:
            melhores = sorted(melhores + [do_dia], key=lambda x: x.ordem)[:limite]
    return melhores


def _trocas(ctx, id_, rejeitados):
    agenda = ctx.agenda
    a = agenda.aulas[id_]
    comp = ctx.comps[a.componente_id]
    acoes = []
    for prof in sorted(comp.vinculados - {a.professor_id}):
        if agenda.ocupantes("prof", prof, a.data, a.inicio, a.fim):
            rejeitados["substituto"] = rejeitados.get("substituto", 0) + 1
            continue
        carga = len(agenda._prof.get((prof, a.data), ()))
        custo = PESOS["troca_docente"] + PESOS["carga_no_dia"] * carga
        motivos = ["docente vinculado ao componente e livre no horário"]
        if carga:
            motivos.append(f"já tem {carga} encontro{'s' if carga > 1 else ''} no dia")
        acoes.append(Acao(TROCAR, (id_,), comp.id, professor_id=prof, custo=custo, motivos=tuple(motivos)))
    return acoes


def candidatos(ctx, conflito, pode_mover, pode_trocar=None, limite=5):
    """(ações válidas ordenadas por custo, diagnóstico de rejeições) para um conflito.

    `pode_mover(comp)` / `pode_trocar(comp)` restringem os componentes em que se pode agir.
    """
    pode_trocar = pode_trocar or pode_mover
    acoes, rejeitados = [], {}
    for id_ in conflito.ids:
        comp = ctx.comps.get(ctx.agenda.aulas[id_].componente_id)
        if comp is None or comp.semestre_id != ctx.semestre.id:
            rejeitados["outro_semestre"] = rejeitados.get("outro_semestre", 0) + 1
            continue
        if not comp.editavel:
            rejeitados["aprovado"] = rejeitados.get("aprovado", 0) + 1
            continue
        if pode_mover(comp):
            acoes += _movimentos(ctx, id_, limite, rejeitados)
        if conflito.tipo == ag.DOCENTE and pode_trocar(comp):
            acoes += _trocas(ctx, id_, rejeitados)
        if not pode_mover(comp) and not pode_trocar(comp):
            rejeitados["sem_permissao"] = rejeitados.get("sem_permissao", 0) + 1
    validas = []
    for acao in sorted(set(acoes), key=lambda x: x.ordem):
        # Verificação formal (R1–R8) e garantia de que ESTE conflito é eliminado.
        if not violacoes(ctx, acao) and conflito.chave in {c.chave for c in efeito(ctx.agenda, acao)[0]}:
            validas.append(acao)
        if len(validas) == limite:
            break
    return validas, rejeitados


def diagnostico(rejeitados):
    """Explica por que não há sugestão para um conflito."""
    partes = []
    rotulos = (
        ("aprovado", "cronograma aprovado/publicado (reabra-o para revisão)"),
        ("sem_permissao", "componente fora da sua alçada"),
        ("outro_semestre", "encontro de outro semestre"),
        ("turma", "horários em que a turma já tem aula"),
        ("docente", "horários em que o docente já tem aula"),
        ("componente", "horários já usados pelo próprio componente"),
        ("calendario", "horários em datas bloqueadas"),
        ("substituto", "docentes vinculados ocupados no horário"),
    )
    for chave, texto in rotulos:
        if rejeitados.get(chave):
            partes.append(f"{rejeitados[chave]} {texto}" if chave not in ("aprovado", "sem_permissao", "outro_semestre") else texto)
    return "Nenhuma alternativa atende às restrições rígidas" + (": " + "; ".join(partes) + "." if partes else ".")


# ------------------------------------------------------------------- exibição


def _quando(dia, inicio, fim):
    return f"{DIAS[dia.weekday()]} {dia:%d/%m/%Y} {inicio:%H:%M}–{fim:%H:%M}"


def descrever(ctx, acao):
    a = ctx.agenda.aulas[acao.encontros[0]]
    comp = ctx.comps[acao.componente_id]
    if acao.tipo == MOVER:
        return f"Mover {comp.rotulo} de {_quando(a.data, a.inicio, a.fim)} para {_quando(acao.data, acao.inicio, acao.fim)}"
    atual = ctx.docentes.get(a.professor_id, "docente atual")
    return (f"Trocar o docente de {comp.rotulo} em {_quando(a.data, a.inicio, a.fim)}: "
            f"{atual} → {ctx.docentes.get(acao.professor_id, 'substituto')}")


def descrever_conflito(ctx, c):
    """Texto curto de um conflito calculado (sem depender do registro no banco)."""
    rot = lambda i: ctx.comps[ctx.agenda.aulas[i].componente_id].rotulo if ctx.agenda.aulas[i].componente_id in ctx.comps else "outro componente"
    quando = f"{c.data:%d/%m/%Y} {c.inicio:%H:%M}–{c.fim:%H:%M}"
    if c.tipo == ag.CALENDARIO:
        detalhe = f"data bloqueada ({c.descricao})" if c.motivo == ag.DATA_BLOQUEADA else c.descricao
        return f"Calendário — {rot(c.a)} em {c.data:%d/%m/%Y}: {detalhe}"
    if c.tipo == ag.TURMA:
        return f"Turma — {rot(c.a)} × {rot(c.b)}, {quando}"
    return f"Docente — {ctx.docentes.get(c.professor_id, 'docente')}: {rot(c.a)} × {rot(c.b)}, {quando}"


def carga_da_acao(ctx, acao):
    """Dados mínimos para aplicar a ação; as versões detectam alterações posteriores."""
    carga = {"tipo": acao.tipo, "componente": acao.componente_id,
             "encontros": [[i, ctx.versoes.get(i)] for i in acao.encontros]}
    if acao.tipo == MOVER:
        carga.update(data=acao.data.isoformat(), inicio=acao.inicio.strftime("%H:%M"), fim=acao.fim.strftime("%H:%M"))
    else:
        carga["professor_id"] = acao.professor_id
    return carga


def acao_da_carga(carga):
    """Reconstrói uma ação a partir dos dados enviados pelo navegador (não confiáveis)."""
    try:
        encontros = tuple(int(i) for i, _ in carga["encontros"])
        versoes = {int(i): int(v) for i, v in carga["encontros"]}
        if not encontros or len(encontros) > 50:
            raise ValueError
        if carga["tipo"] == MOVER:
            acao = Acao(MOVER, encontros, int(carga["componente"]), date.fromisoformat(carga["data"]),
                        datetime.strptime(carga["inicio"], "%H:%M").time(), datetime.strptime(carga["fim"], "%H:%M").time())
        elif carga["tipo"] == TROCAR and len(encontros) == 1:
            acao = Acao(TROCAR, encontros, int(carga["componente"]), professor_id=int(carga["professor_id"]))
        else:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("Sugestão inválida.")
    return acao, versoes


def _sugestao(ctx, acao):
    return Sugestao(acao, descrever(ctx, acao), efeito(ctx.agenda, acao)[0], carga_da_acao(ctx, acao))


def sugerir(ctx, conflito, pode_mover, pode_trocar=None, limite=5):
    """Sugestões verificadas para um único conflito. Retorna (sugestões, diagnóstico)."""
    acoes, rejeitados = candidatos(ctx, conflito, pode_mover, pode_trocar, limite)
    return [_sugestao(ctx, a) for a in acoes], ("" if acoes else diagnostico(rejeitados))


# ---------------------------------------------------------------------- plano


def planejar(ctx, pode_mover, max_nos=300, por_conflito=4):
    """Plano conjunto para todos os conflitos do semestre.

    Busca com retrocesso e poda: escolhe uma ação por conflito, na ordem estável dos
    conflitos, reavaliando os candidatos sobre o estado já modificado pelas ações
    anteriores (uma ação pode resolver vários conflitos; os já resolvidos são pulados).
    Minimiza primeiro o número de conflitos sem solução e depois o custo total.
    O resultado é determinístico; `completa=False` indica que o limite de nós foi
    atingido e o plano é o melhor encontrado até então.
    """
    agenda = ctx.agenda
    plano = Plano()
    alvos = []
    todos = conflitos_do_semestre(ctx)
    plano.total = len(todos)
    for c in todos:
        comps = [ctx.comps.get(agenda.aulas[i].componente_id) for i in c.ids]
        do_semestre = [k for k in comps if k and k.semestre_id == ctx.semestre.id]
        if any(k.editavel and pode_mover(k) for k in do_semestre):
            alvos.append(c)
        elif any(k.editavel for k in do_semestre):
            plano.fora_de_alcance.append((c, "Os componentes envolvidos são coordenados por outras pessoas."))
        else:
            plano.fora_de_alcance.append((c, "Os cronogramas envolvidos estão aprovados/publicados ou são de outro semestre."))

    melhor = {"custo": None, "acoes": [], "pulados": []}
    estado = {"nos": 0, "completa": True}

    def presente(c):
        return any(x.chave == c.chave for x in agenda.conflitos_de(c.a))

    def buscar(i, custo, acoes, pulados):
        while i < len(alvos) and not presente(alvos[i]):
            i += 1
        if i == len(alvos):
            if melhor["custo"] is None or custo < melhor["custo"]:
                melhor.update(custo=custo, acoes=list(acoes), pulados=list(pulados))
            return
        if melhor["custo"] is not None:
            if custo >= melhor["custo"]:
                return                      # poda: já não pode melhorar
            if estado["nos"] >= max_nos:
                estado["completa"] = False  # orçamento esgotado: fica o melhor plano já encontrado
                return
        estado["nos"] += 1
        c = alvos[i]
        opcoes, rejeitados = candidatos(ctx, c, pode_mover, limite=por_conflito)
        for acao in opcoes:
            anteriores = _aplicar(agenda, acao)
            acoes.append(acao)
            buscar(i + 1, custo + acao.custo, acoes, pulados)
            acoes.pop()
            _desfazer(agenda, anteriores)
        pulados.append((c, diagnostico(rejeitados)))
        buscar(i + 1, custo + PESOS["nao_resolvido"], acoes, pulados)
        pulados.pop()

    buscar(0, 0, [], [])

    # Reaplica o melhor plano para descrever cada passo sobre o estado em que ele ocorre.
    desfazer = []
    for acao in melhor["acoes"]:
        plano.sugestoes.append(_sugestao(ctx, acao))
        desfazer.append(_aplicar(agenda, acao))
    plano.sem_solucao = [(c, texto) for c, texto in melhor["pulados"] if presente(c)]
    for anteriores in reversed(desfazer):
        _desfazer(agenda, anteriores)
    plano.custo = sum(a.custo for a in melhor["acoes"])
    plano.completa, plano.nos = estado["completa"], estado["nos"]
    return plano
