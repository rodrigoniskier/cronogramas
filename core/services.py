"""Regras de negócio: geração de encontros, conflitos, estados e permissões."""
from collections import defaultdict
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from . import agenda as ag
from .models import (
    Componente, Conflito, DataBloqueada, Encontro, HistoricoAlteracao, Semestre, ch_padrao, hora_modelo,
)

# ---------------------------------------------------------------- permissões


def pode_gerenciar(usuario, componente):
    """Cadastro, encontros excepcionais, aprovação, publicação e revisão."""
    return usuario.eh_admin or (usuario.eh_coordenador and componente.coordenador_id == usuario.id)


def tem_vinculo(usuario, componente):
    if pode_gerenciar(usuario, componente):
        return True
    return componente.professores.filter(pk=usuario.pk).exists()


def motivo_sem_edicao(usuario, componente):
    """Retorna '' se o usuário pode editar o cronograma, ou o motivo do bloqueio."""
    if not tem_vinculo(usuario, componente):
        return "Você não está vinculado a este componente. A consulta é livre, mas a edição é restrita aos docentes vinculados e ao coordenador responsável."
    if componente.situacao == Componente.Situacao.APROVADO:
        return "Cronograma aprovado. Para alterar, o coordenador deve reabri-lo para revisão."
    if componente.situacao == Componente.Situacao.PUBLICADO:
        return "Cronograma publicado. Para alterar, o coordenador deve reabri-lo para revisão."
    if not usuario.eh_admin and not componente.semestre.preenchimento_liberado:
        return "O período de preenchimento deste semestre ainda não foi liberado pela administração."
    return ""


def pode_editar(usuario, componente):
    return motivo_sem_edicao(usuario, componente) == ""


# ------------------------------------------------------------------ histórico


def registrar(usuario, componente, campo, anterior="", novo="", encontro=None):
    HistoricoAlteracao.objects.create(
        usuario=usuario,
        componente=componente,
        encontro=encontro,
        encontro_descricao=encontro.descricao if encontro else "",
        campo=campo,
        valor_anterior=str(anterior or ""),
        valor_novo=str(novo or ""),
    )


# -------------------------------------------------------- geração de encontros


def datas_previstas(componente):
    """Conjunto {(data, inicio, fim)} a partir dos horários semanais e do calendário."""
    bloqueadas = set(
        DataBloqueada.objects.filter(semestre=componente.semestre_id).values_list("data", flat=True)
    )
    horarios = list(componente.horarios.all())
    previstas = set()
    dia = componente.data_inicio
    while dia <= componente.data_fim:
        if dia not in bloqueadas:
            for h in horarios:
                if h.dia_semana == dia.weekday():
                    previstas.add((dia, h.hora_inicio, h.hora_fim))
        dia += timedelta(days=1)
    return previstas


@transaction.atomic
def gerar_encontros(componente, sincronizar=True):
    """Sincroniza os encontros regulares com a grade semanal e o calendário.

    - cria os encontros que faltam;
    - remove encontros regulares vazios que deixaram de estar previstos;
    - preserva encontros já preenchidos (passam a ser excepcionais) e os excepcionais.
    Retorna (criados, removidos, preservados). Com `sincronizar=False`, quem chama
    assume o recálculo dos conflitos (útil ao regerar vários componentes de uma vez).
    """
    previstas = datas_previstas(componente)
    todos = list(componente.encontros.all())
    chaves_previstas = {(d, i): f for d, i, f in previstas}
    regulares = set()
    criados = removidos = preservados = 0
    docentes_afetados = set()

    for enc in todos:
        if enc.excepcional:
            continue
        chave = (enc.data, enc.hora_inicio)
        fim = chaves_previstas.get(chave)
        if fim is None:
            vazio = not (enc.conteudo or enc.professor_id or enc.atividade or enc.recursos or enc.observacoes)
            if vazio:
                enc.delete()
                removidos += 1
            else:
                enc.excepcional = True
                enc.save(update_fields=["excepcional"])
                preservados += 1
            continue
        regulares.add(chave)
        if fim != enc.hora_fim:
            enc.hora_fim = fim
            enc.versao += 1
            enc.save(update_fields=["hora_fim", "versao"])
            docentes_afetados.add(enc.professor_id)

    novos = [
        Encontro(componente=componente, data=d, hora_inicio=i, hora_fim=f,
                 local=componente.local_padrao, ch=ch_padrao(i, f))
        for d, i, f in sorted(previstas)
        if (d, i) not in regulares
    ]
    Encontro.objects.bulk_create(novos)
    criados = len(novos)
    if sincronizar:
        sincronizar_conflitos(docentes_afetados, {componente.semestre_id})
    return criados, removidos, preservados


# ------------------------------------------------------------------ conflitos


def calendarios_de(semestre_ids):
    """{semestre_id: agenda.Calendario} com o período letivo e as datas bloqueadas."""
    bloqueadas = defaultdict(dict)
    for sem_id, dia, descricao in DataBloqueada.objects.filter(semestre__in=semestre_ids).values_list(
        "semestre_id", "data", "descricao"
    ):
        bloqueadas[sem_id][dia] = descricao
    return {
        sem_id: ag.Calendario(inicio, fim, bloqueadas[sem_id])
        for sem_id, inicio, fim in Semestre.objects.filter(pk__in=semestre_ids).values_list(
            "id", "data_inicio", "data_fim"
        )
    }


def montar_agenda(encontros, docente=True, turma_calendario=True):
    """Constrói a agenda em memória a partir de um queryset de encontros.

    `docente=False` ignora os docentes e `turma_calendario=False` ignora turmas e
    calendário — usados para recalcular só a parte afetada por uma alteração.
    """
    linhas = list(encontros.values_list(
        "id", "componente_id", "componente__semestre_id", "componente__curso",
        "componente__periodo", "componente__turma", "professor_id", "data", "hora_inicio", "hora_fim",
    ))
    calendarios = calendarios_de({l[2] for l in linhas}) if turma_calendario else {}
    return ag.Agenda(
        (
            ag.Aula(
                id=i, componente_id=comp, semestre_id=sem,
                turma=ag.chave_turma(sem, curso, periodo, turma) if turma_calendario else None,
                professor_id=prof if docente else None, data=dia, inicio=ini, fim=fim,
            )
            for i, comp, sem, curso, periodo, turma, prof, dia, ini, fim in linhas
        ),
        calendarios,
    )


@transaction.atomic
def sincronizar_conflitos(professor_ids=None, semestre_ids=None):
    """Recalcula e persiste os conflitos (regras em core/agenda.py).

    Sem argumentos, verifica toda a base. Com `professor_ids`, recalcula os
    conflitos docentes desses docentes (em todos os componentes e semestres);
    com `semestre_ids`, os conflitos de turma e de calendário desses semestres.
    """
    T = Conflito.Tipo
    if professor_ids is None and semestre_ids is None:
        achados = montar_agenda(Encontro.objects.all()).conflitos()
        existentes = Conflito.objects.all()
    else:
        profs = {p for p in (professor_ids or ()) if p}
        sems = {s for s in (semestre_ids or ()) if s}
        if not profs and not sems:
            return
        achados, escopo = set(), Q(pk__in=[])
        if profs:
            achados |= montar_agenda(
                Encontro.objects.filter(professor_id__in=profs), turma_calendario=False
            ).conflitos()
            escopo |= Q(tipo=T.DOCENTE, professor_id__in=profs)
        if sems:
            achados |= montar_agenda(
                Encontro.objects.filter(componente__semestre_id__in=sems), docente=False
            ).conflitos()
            escopo |= Q(tipo__in=[T.TURMA, T.CALENDARIO]) & (
                Q(encontro_a__componente__semestre_id__in=sems) | Q(encontro_b__componente__semestre_id__in=sems)
            )
        existentes = Conflito.objects.filter(escopo)

    atuais = {c.chave: c for c in achados}
    agora = timezone.now()
    vistos = set()
    for c in existentes:
        vistos.add(c.chave)
        achado = atuais.get(c.chave)
        if achado:
            novo = (achado.data, achado.inicio, achado.fim, achado.descricao)
            if not c.ativo or (c.data, c.sobreposicao_inicio, c.sobreposicao_fim, c.descricao) != novo:
                c.status = Conflito.Status.ATIVO
                c.resolvido_em = None
                c.data, c.sobreposicao_inicio, c.sobreposicao_fim, c.descricao = novo
                c.save()
        elif c.ativo:
            c.status = Conflito.Status.RESOLVIDO
            c.resolvido_em = agora
            c.save(update_fields=["status", "resolvido_em"])

    for chave, achado in atuais.items():
        if chave in vistos:
            continue
        try:
            with transaction.atomic():
                Conflito.objects.create(
                    tipo=achado.tipo, encontro_a_id=achado.a, encontro_b_id=achado.b,
                    professor_id=achado.professor_id, data=achado.data,
                    sobreposicao_inicio=achado.inicio, sobreposicao_fim=achado.fim,
                    motivo=achado.motivo, descricao=achado.descricao[:160],
                )
        except IntegrityError:
            pass  # criado por requisição concorrente


def conflitos_ativos():
    return Conflito.objects.filter(status=Conflito.Status.ATIVO).select_related(
        "professor",
        "encontro_a__componente__coordenador",
        "encontro_b__componente__coordenador",
        "encontro_a__componente__semestre",
        "encontro_b__componente__semestre",
    )


def conflitos_do_usuario(usuario):
    """Conflitos ativos em que o usuário é o docente ou atua em um dos componentes."""
    q = (
        Q(professor=usuario)
        | Q(encontro_a__componente__professores=usuario)
        | Q(encontro_b__componente__professores=usuario)
        | Q(encontro_a__componente__coordenador=usuario)
        | Q(encontro_b__componente__coordenador=usuario)
    )
    return conflitos_ativos().filter(q).distinct()


# ----------------------------------------------------------- estados e números

STATUS = {
    "NAO_INICIADO": ("Não iniciado", "secondary", "bi-circle"),
    "EM_PREENCHIMENTO": ("Em preenchimento", "primary", "bi-pencil-square"),
    "COM_PENDENCIAS": ("Com pendências", "danger", "bi-exclamation-triangle-fill"),
    "PRONTO": ("Pronto para aprovação", "warning", "bi-hourglass-split"),
    "APROVADO": ("Aprovado", "success", "bi-check-circle-fill"),
    "PUBLICADO": ("Publicado", "success", "bi-megaphone-fill"),
}


def _status(componente, total, preenchidos, conflitos):
    if componente.situacao == Componente.Situacao.PUBLICADO:
        return "PUBLICADO"
    if componente.situacao == Componente.Situacao.APROVADO:
        return "APROVADO"
    if conflitos:
        return "COM_PENDENCIAS"
    if total == 0 or preenchidos == 0:
        iniciado = total and componente.encontros.exclude(
            conteudo="", professor__isnull=True, atividade="", recursos="", observacoes=""
        ).exists()
        return "EM_PREENCHIMENTO" if iniciado else "NAO_INICIADO"
    if preenchidos == total:
        return "PRONTO"
    return "EM_PREENCHIMENTO"


def estatisticas(componentes):
    """{componente_id: dict(total, preenchidos, pct, conflitos, status, ...)}."""
    componentes = list(componentes)
    ids = [c.id for c in componentes]
    contagem = {
        r["componente"]: r
        for r in Encontro.objects.filter(componente__in=ids)
        .values("componente")
        .annotate(
            total=Count("id"),
            preenchidos=Count("id", filter=Q(professor__isnull=False) & ~Q(conteudo="")),
        )
    }
    conf = defaultdict(int)
    for a, b in Conflito.objects.filter(status=Conflito.Status.ATIVO).values_list(
        "encontro_a__componente", "encontro_b__componente"
    ):
        for cid in {a, b} - {None}:
            conf[cid] += 1
    saida = {}
    for c in componentes:
        r = contagem.get(c.id, {"total": 0, "preenchidos": 0})
        total, preench = r["total"], r["preenchidos"]
        codigo = _status(c, total, preench, conf[c.id])
        rotulo, cor, icone = STATUS[codigo]
        saida[c.id] = {
            "total": total,
            "preenchidos": preench,
            "pct": round(100 * preench / total) if total else 0,
            "conflitos": conf[c.id],
            "status": codigo,
            "status_rotulo": rotulo,
            "status_cor": cor,
            "status_icone": icone,
        }
    return saida


def problemas_para_aprovacao(componente):
    """Lista de impedimentos à aprovação: [{tipo, mensagem, encontro_id}]."""
    problemas = []
    encontros = list(componente.encontros.all())
    if not encontros:
        problemas.append({"tipo": "estrutura", "mensagem": "O componente não possui encontros cadastrados.", "encontro_id": None})
    for e in encontros:
        faltas = []
        if not e.conteudo.strip():
            faltas.append("conteúdo programático")
        if not e.professor_id:
            faltas.append("professor responsável")
        if faltas:
            problemas.append({
                "tipo": "incompleto",
                "mensagem": f"{e.descricao}: falta {' e '.join(faltas)}.",
                "encontro_id": e.id,
            })
    ativos = conflitos_ativos().filter(
        Q(encontro_a__componente=componente) | Q(encontro_b__componente=componente)
    )
    for c in ativos:
        meu = c.encontro_a if c.encontro_a.componente_id == componente.id else c.encontro_b
        problemas.append({
            "tipo": "conflito",
            "mensagem": f"{c.get_tipo_display()} — {c.explicacao}",
            "encontro_id": meu.id,
        })
    return problemas


def feriados_do_componente(componente):
    """Datas bloqueadas que caem em dia de aula: aparecem como linhas do cronograma,
    como no modelo institucional ("Feriado - Independência do Brasil")."""
    horarios = list(componente.horarios.all())
    saida = []
    for b in DataBloqueada.objects.filter(
        semestre=componente.semestre_id, data__gte=componente.data_inicio, data__lte=componente.data_fim
    ):
        for h in horarios:
            if h.dia_semana == b.data.weekday():
                rotulo = b.descricao if b.tipo != DataBloqueada.Tipo.FERIADO or b.descricao.lower().startswith("feriado") else f"Feriado - {b.descricao}"
                saida.append({
                    "data": b.data, "hora_inicio": h.hora_inicio, "hora_fim": h.hora_fim,
                    "horario": f"{hora_modelo(h.hora_inicio)}-{hora_modelo(h.hora_fim)}",
                    "descricao": rotulo, "ch": ch_padrao(h.hora_inicio, h.hora_fim),
                })
    return saida
