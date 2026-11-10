"""Regras de negócio: geração de encontros, conflitos, estados e permissões."""
from collections import defaultdict
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import Componente, Conflito, DataBloqueada, Encontro, HistoricoAlteracao, ch_padrao, hora_modelo

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


def _encontro_vazio(enc):
    return not (
        enc.conteudo or enc.professor_id or enc.tipo or enc.atividade
        or enc.recursos or enc.grupos or enc.observacoes
    )


@transaction.atomic
def gerar_encontros(componente):
    """Sincroniza os encontros regulares com a grade semanal e o calendário.

    - cria os encontros que faltam;
    - remove encontros regulares vazios que deixaram de estar previstos;
    - preserva encontros já preenchidos (passam a ser excepcionais) e os excepcionais.
    Retorna (criados, removidos, preservados).
    """
    previstas = datas_previstas(componente)
    todos = list(componente.encontros.all())
    chaves_previstas = {(d, i): f for d, i, f in previstas}
    por_chave = defaultdict(int)
    for enc in todos:
        por_chave[(enc.data, enc.hora_inicio)] += 1
    regulares = set()
    criados = removidos = preservados = 0
    docentes_afetados = set()

    for enc in todos:
        chave = (enc.data, enc.hora_inicio)
        fim = chaves_previstas.get(chave)
        if enc.excepcional:
            if fim is not None:
                regulares.add(chave)
                if enc.hora_fim == fim and por_chave[chave] == 1:
                    enc.excepcional = False
                    enc.save(update_fields=["excepcional"])
            continue
        if fim is None:
            if _encontro_vazio(enc):
                enc.delete()
                removidos += 1
            else:
                enc.excepcional = True
                enc.save(update_fields=["excepcional"])
                preservados += 1
            continue
        regulares.add(chave)
        if fim != enc.hora_fim:
            ch_antiga = ch_padrao(enc.hora_inicio, enc.hora_fim)
            enc.hora_fim = fim
            enc.versao += 1
            campos_salvar = ["hora_fim", "versao"]
            if not enc.ch or enc.ch == ch_antiga:
                enc.ch = ch_padrao(enc.hora_inicio, fim)
                campos_salvar.append("ch")
            enc.save(update_fields=campos_salvar)
            docentes_afetados.add(enc.professor_id)

    novos = [
        Encontro(componente=componente, data=d, hora_inicio=i, hora_fim=f,
                 local=componente.local_padrao, ch=ch_padrao(i, f))
        for d, i, f in sorted(previstas)
        if (d, i) not in regulares
    ]
    Encontro.objects.bulk_create(novos)
    criados = len(novos)
    sincronizar_conflitos(docentes_afetados)
    return criados, removidos, preservados


# ------------------------------------------------------------------ conflitos


def _sobrepoe(a, b):
    """Intervalos semiabertos: aulas consecutivas (14–16 e 16–18) não conflitam."""
    return a.hora_inicio < b.hora_fim and b.hora_inicio < a.hora_fim


@transaction.atomic
def sincronizar_conflitos(professor_ids=None):
    """Recalcula os conflitos docentes.

    Considera todos os componentes, independentemente do coordenador. Com
    `professor_ids`, limita o recálculo aos docentes afetados por uma alteração;
    sem argumento, verifica toda a base.
    """
    encontros = Encontro.objects.filter(professor__isnull=False)
    existentes = Conflito.objects.all()
    if professor_ids is not None:
        ids = {p for p in professor_ids if p}
        if not ids:
            return
        encontros = encontros.filter(professor_id__in=ids)
        existentes = existentes.filter(professor_id__in=ids)

    por_docente_dia = defaultdict(list)
    for e in encontros.only("id", "professor_id", "data", "hora_inicio", "hora_fim"):
        por_docente_dia[(e.professor_id, e.data)].append(e)

    atuais = {}
    for (prof_id, data), lista in por_docente_dia.items():
        if len(lista) < 2:
            continue
        lista.sort(key=lambda e: (e.hora_inicio, e.id))
        for i, a in enumerate(lista):
            for b in lista[i + 1:]:
                if b.hora_inicio >= a.hora_fim:
                    break
                if _sobrepoe(a, b):
                    x, y = (a, b) if a.id < b.id else (b, a)
                    atuais[(x.id, y.id, prof_id)] = (
                        data,
                        max(a.hora_inicio, b.hora_inicio),
                        min(a.hora_fim, b.hora_fim),
                    )

    agora = timezone.now()
    vistos = set()
    for c in existentes:
        chave = (c.encontro_a_id, c.encontro_b_id, c.professor_id)
        vistos.add(chave)
        if chave in atuais:
            data, ini, fim = atuais[chave]
            if not c.ativo or (c.data, c.sobreposicao_inicio, c.sobreposicao_fim) != (data, ini, fim):
                c.status = Conflito.Status.ATIVO
                c.resolvido_em = None
                c.data, c.sobreposicao_inicio, c.sobreposicao_fim = data, ini, fim
                c.save()
        elif c.ativo:
            c.status = Conflito.Status.RESOLVIDO
            c.resolvido_em = agora
            c.save(update_fields=["status", "resolvido_em"])

    for chave, (data, ini, fim) in atuais.items():
        if chave in vistos:
            continue
        try:
            with transaction.atomic():
                Conflito.objects.create(
                    encontro_a_id=chave[0], encontro_b_id=chave[1], professor_id=chave[2],
                    data=data, sobreposicao_inicio=ini, sobreposicao_fim=fim,
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
    """Conflitos ativos em que o usuário é o docente ou atua no componente."""
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


def _status(componente, total, preenchidos, conflitos, iniciados=None):
    if componente.situacao == Componente.Situacao.PUBLICADO:
        return "PUBLICADO"
    if componente.situacao == Componente.Situacao.APROVADO:
        return "APROVADO"
    if conflitos:
        return "COM_PENDENCIAS"
    if total == 0 or preenchidos == 0:
        if iniciados is None:
            iniciados = total and componente.encontros.exclude(
                conteudo="", professor__isnull=True, tipo="", atividade="",
                recursos="", grupos="", observacoes="",
            ).exists()
        return "EM_PREENCHIMENTO" if iniciados else "NAO_INICIADO"
    if preenchidos == total:
        return "PRONTO"
    return "EM_PREENCHIMENTO"


def estatisticas(componentes):
    """{componente_id: dict(total, preenchidos, pct, conflitos, status, ...)}."""
    componentes = list(componentes)
    if not componentes:
        return {}
    ids = [c.id for c in componentes]
    filtro_iniciado = ~Q(
        conteudo="", professor__isnull=True, tipo="", atividade="",
        recursos="", grupos="", observacoes="",
    )
    contagem = {
        r["componente"]: r
        for r in Encontro.objects.filter(componente__in=ids)
        .values("componente")
        .annotate(
            total=Count("id"),
            preenchidos=Count("id", filter=Q(professor__isnull=False) & ~Q(conteudo="")),
            iniciados=Count("id", filter=filtro_iniciado),
        )
    }
    conf = defaultdict(int)
    for a, b in Conflito.objects.filter(
        status=Conflito.Status.ATIVO,
    ).filter(
        Q(encontro_a__componente__in=ids) | Q(encontro_b__componente__in=ids)
    ).values_list("encontro_a__componente", "encontro_b__componente"):
        for cid in {a, b}:
            conf[cid] += 1
    saida = {}
    for c in componentes:
        r = contagem.get(c.id, {"total": 0, "preenchidos": 0, "iniciados": 0})
        total, preench, inic = r["total"], r["preenchidos"], r["iniciados"]
        codigo = _status(c, total, preench, conf[c.id], iniciados=inic)
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
        meu, outro = (c.encontro_a, c.encontro_b) if c.encontro_a.componente_id == componente.id else (c.encontro_b, c.encontro_a)
        problemas.append({
            "tipo": "conflito",
            "mensagem": (
                f"{meu.descricao}: conflito docente de {c.professor.nome} com "
                f"{outro.componente.nome} (Turma {outro.componente.turma}), "
                f"{c.sobreposicao_inicio:%H:%M}–{c.sobreposicao_fim:%H:%M}."
            ),
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
