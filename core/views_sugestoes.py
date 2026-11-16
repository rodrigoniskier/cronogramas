"""Telas do motor de sugestões: plano do semestre e aplicação de ações.

Nada do que o navegador envia é confiado: ao aplicar, as ações são reconstruídas,
conferidas contra o estado atual do banco (versões dos encontros e todas as
restrições rígidas) e gravadas por `alterar_encontro`, que impõe as permissões
e registra o histórico. Um plano é aplicado por inteiro ou não é aplicado.
"""
import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import sugestoes as sg
from .models import Componente, Conflito, Semestre
from .services import pode_gerenciar, registrar
from .views import ErroEdicao, alterar_encontro


def alcadas(usuario, semestre):
    """Componentes em elaboração do semestre em que o usuário pode agir.

    Retorna (ids em que pode mover aulas, ids em que pode trocar o docente),
    seguindo as mesmas regras do editor (services.motivo_sem_edicao).
    """
    gerencia, edita = set(), set()
    if not (usuario.eh_admin or semestre.preenchimento_liberado):
        return gerencia, edita
    vinculados = set(usuario.componentes_vinculados.values_list("id", flat=True))
    for comp in Componente.objects.filter(semestre=semestre, situacao=Componente.Situacao.RASCUNHO):
        if pode_gerenciar(usuario, comp):
            gerencia.add(comp.id)
            edita.add(comp.id)
        elif comp.id in vinculados:
            edita.add(comp.id)
    return gerencia, edita


def _apresentar(ctx, sugestao):
    sugestao.carga_json = json.dumps([sugestao.carga])
    sugestao.resolve_textos = [sg.descrever_conflito(ctx, c) for c in sugestao.resolve]
    return sugestao


def sugestoes_do_conflito(conflito, usuario):
    """Sugestões para a tela de detalhe de um conflito ativo."""
    semestre = conflito.encontro_a.componente.semestre
    ctx = sg.montar_contexto(semestre)
    achado = next((c for c in ctx.agenda.conflitos_de(conflito.encontro_a_id) if c.chave == conflito.chave), None) \
        if conflito.encontro_a_id in ctx.agenda.aulas else None
    if achado is None:
        return {"aplicaveis": [], "outras": [], "diagnostico": "Este conflito não aparece mais nos dados atuais. Use “Verificar novamente” na Central de Conflitos."}
    gerencia, edita = alcadas(usuario, semestre)
    aplicaveis, diagnostico = sg.sugerir(ctx, achado, lambda c: c.id in gerencia, lambda c: c.id in edita)
    # Alternativas que dependem de quem responde pelos demais componentes (apenas informativas).
    outras, _ = sg.sugerir(ctx, achado, lambda c: c.id not in gerencia, lambda c: c.id not in edita, limite=3)
    if not aplicaveis and not outras:
        # Ninguém tem alternativa: explica as restrições, independentemente de permissões.
        _, diagnostico = sg.sugerir(ctx, achado, lambda c: True)
    return {
        "aplicaveis": [_apresentar(ctx, s) for s in aplicaveis],
        "outras": [_apresentar(ctx, s) for s in outras],
        "diagnostico": "" if aplicaveis else diagnostico,
    }


@require_GET
def plano_remanejamento(request):
    semestres = list(Semestre.objects.all())
    escolhido = request.GET.get("semestre", "")
    semestre = next((s for s in semestres if str(s.pk) == escolhido), None)
    if semestre is None:
        com_conflito = Conflito.objects.filter(status=Conflito.Status.ATIVO).values_list(
            "encontro_a__componente__semestre_id", flat=True
        ).first()
        semestre = next((s for s in semestres if s.pk == com_conflito), semestres[0] if semestres else None)
    contexto = {"semestres": semestres, "semestre": semestre}
    if semestre:
        ctx = sg.montar_contexto(semestre)
        gerencia, _ = alcadas(request.user, semestre)
        plano = sg.planejar(ctx, lambda c: c.id in gerencia)
        for s in plano.sugestoes:
            _apresentar(ctx, s)
        contexto.update({
            "plano": plano,
            "cargas_json": json.dumps([s.carga for s in plano.sugestoes]),
            "sem_solucao": [(sg.descrever_conflito(ctx, c), texto) for c, texto in plano.sem_solucao],
            "fora_de_alcance": [(sg.descrever_conflito(ctx, c), texto) for c, texto in plano.fora_de_alcance],
            "resolvidos": plano.total - len(plano.sem_solucao) - len(plano.fora_de_alcance),
            "pesos": sg.PESOS,
        })
    return render(request, "core/plano_remanejamento.html", contexto)


class _Recusa(Exception):
    pass


@require_POST
def aplicar_sugestoes(request):
    proximo = request.POST.get("proximo", "")
    if not url_has_allowed_host_and_scheme(proximo, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        proximo = "conflitos"
    usuario = request.user
    try:
        cargas = json.loads(request.POST.get("acoes") or "null")
        if not isinstance(cargas, list) or not 1 <= len(cargas) <= 200 or not all(isinstance(c, dict) for c in cargas):
            raise ValueError
        pares = [sg.acao_da_carga(c) for c in cargas]
    except ValueError:
        messages.error(request, "Sugestão inválida. Gere as sugestões novamente.")
        return redirect(proximo)

    try:
        with transaction.atomic():
            ids = {acao.componente_id for acao, _ in pares}
            comps = {c.id: c for c in Componente.objects.select_for_update().filter(pk__in=ids).select_related("semestre")}
            if len(comps) != len(ids) or len({c.semestre_id for c in comps.values()}) != 1:
                raise _Recusa("As ações devem pertencer a componentes existentes de um mesmo semestre.")
            ctx = sg.montar_contexto(next(iter(comps.values())).semestre)
            for _, versoes in pares:
                if any(ctx.versoes.get(i) != v for i, v in versoes.items()):
                    raise _Recusa("Os encontros foram alterados depois que a sugestão foi gerada. Gere as sugestões novamente.")
            for acao, _ in pares:
                comp = comps[acao.componente_id]
                erros = sg.violacoes(ctx, acao)
                if erros:
                    raise _Recusa(f"{comp}: " + " ".join(erros))
                descricao = sg.descrever(ctx, acao)
                if acao.tipo == sg.MOVER:
                    campos = {"data": acao.data.isoformat(), "inicio": acao.inicio.strftime("%H:%M"), "fim": acao.fim.strftime("%H:%M")}
                else:
                    campos = {"professor_id": acao.professor_id}
                for encontro_id in acao.encontros:
                    alterar_encontro(usuario, encontro_id, campos)   # permissões, histórico e conflitos
                sg._aplicar(ctx.agenda, acao)                       # a próxima ação é conferida sobre o novo estado
                registrar(usuario, comp, "Remanejamento sugerido", "", descricao)
    except ErroEdicao as erro:
        if erro.status == 403:
            raise PermissionDenied(erro.mensagem)
        messages.error(request, f"Nada foi alterado. {erro.mensagem}")
    except _Recusa as erro:
        messages.error(request, f"Nada foi alterado. {erro}")
    else:
        n = len(pares)
        messages.success(request, f"{n} remanejamento{'s' if n > 1 else ''} aplicado{'s' if n > 1 else ''}. Os conflitos foram reavaliados.")
    return redirect(proximo)
