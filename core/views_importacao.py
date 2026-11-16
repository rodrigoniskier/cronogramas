"""Telas da importação de planilhas: envio, mapeamento/validação e aplicação.

Cada importação pertence a quem a enviou: as consultas filtram sempre por
`usuario=request.user`, de modo que outro usuário recebe 404.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET

from .forms import ImportacaoForm
from .importacao import (
    CAMPO, CAMPOS, LINHA_MODELO, ErroImportacao, analisar, aplicar, erros_do_mapeamento, gerar_planilha,
    limpar_mapeamento, sugerir_mapeamento, MAX_ERROS_EXIBIDOS,
)
from .models import Importacao

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _exigir_importador(usuario):
    """Importam planilhas os mesmos perfis que cadastram componentes."""
    if not (usuario.eh_admin or usuario.eh_coordenador):
        raise PermissionDenied


def importar(request):
    _exigir_importador(request.user)
    form = ImportacaoForm(request.POST or None, request.FILES or None, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        cabecalhos, linhas = form.planilha
        imp = form.save(commit=False)
        imp.usuario = request.user
        imp.arquivo_nome = form.cleaned_data["arquivo"].name.replace("\\", "/").rsplit("/", 1)[-1][:200]
        imp.cabecalhos, imp.linhas = cabecalhos, linhas
        imp.mapeamento = sugerir_mapeamento(cabecalhos)
        with transaction.atomic():
            # Uma conferência por vez: rascunhos anteriores do próprio usuário são descartados.
            Importacao.objects.filter(usuario=request.user, status=Importacao.Status.PENDENTE).delete()
            imp.save()
        return redirect("importacao_detalhe", pk=imp.pk)
    return render(request, "core/importar.html", {
        "form": form,
        "importacoes": Importacao.objects.filter(usuario=request.user).defer("linhas").select_related("semestre")[:20],
        "campos": CAMPOS,
    })


@require_GET
def importacao_modelo(request):
    _exigir_importador(request.user)
    resposta = HttpResponse(gerar_planilha([LINHA_MODELO]), content_type=XLSX)
    resposta["Content-Disposition"] = content_disposition_header(True, "modelo_importacao_cronograma.xlsx")
    return resposta


def _colunas(imp):
    """Colunas da planilha com um valor de exemplo e o campo associado."""
    inverso = {i: campo for campo, i in limpar_mapeamento(imp.mapeamento, len(imp.cabecalhos)).items()}
    colunas = []
    for i, titulo in enumerate(imp.cabecalhos):
        exemplo = next((l["c"][i] for l in imp.linhas[:50] if i < len(l["c"]) and l["c"][i]), "")
        colunas.append({"indice": i, "titulo": titulo or f"(coluna {i + 1} sem título)", "exemplo": exemplo[:60], "campo": inverso.get(i, "")})
    return colunas


def importacao_detalhe(request, pk):
    _exigir_importador(request.user)
    imp = get_object_or_404(Importacao.objects.select_related("semestre", "coordenador_padrao"), pk=pk, usuario=request.user)

    if request.method == "POST":
        acao = request.POST.get("acao")
        if not imp.pendente:
            messages.error(request, "Esta importação já foi concluída.")
        elif acao == "descartar":
            imp.delete()
            messages.info(request, "Importação descartada. Nada foi gravado.")
            return redirect("importar")
        elif acao == "mapear":
            mapa, repetidos = {}, set()
            for i in range(len(imp.cabecalhos)):
                campo = request.POST.get(f"col_{i}", "")
                if campo in CAMPO:
                    if campo in mapa:
                        repetidos.add(CAMPO[campo].rotulo)
                    mapa[campo] = i
            if repetidos:
                messages.error(request, "Cada campo pode receber apenas uma coluna. Repetidos: " + ", ".join(sorted(repetidos)) + ".")
            else:
                imp.mapeamento = mapa
                imp.save(update_fields=["mapeamento"])
                messages.success(request, "Mapeamento atualizado. A validação foi refeita.")
        elif acao == "aplicar":
            try:
                with transaction.atomic():
                    # Trava o registro: dois cliques não aplicam a mesma planilha duas vezes.
                    travada = Importacao.objects.select_for_update(of=("self",)).select_related("semestre", "coordenador_padrao").get(pk=imp.pk)
                    if not travada.pendente:
                        raise ErroImportacao("Esta importação já foi concluída.")
                    analise = analisar(
                        travada.cabecalhos, travada.linhas, travada.mapeamento,
                        request.user, travada.semestre, travada.coordenador_padrao,
                    )
                    resumo = aplicar(analise, request.user, travada.semestre, travada.arquivo_nome)
                    travada.status, travada.resumo, travada.aplicado_em = Importacao.Status.APLICADA, resumo, timezone.now()
                    travada.linhas = []    # o conteúdo bruto não é mais necessário
                    travada.save()
            except ErroImportacao as erro:
                messages.error(request, f"Nada foi importado. {erro}")
            else:
                messages.success(
                    request,
                    f"Importação concluída: {resumo['criados']} encontro(s) criado(s) e {resumo['atualizados']} atualizado(s) "
                    f"em {len(resumo['componentes'])} componente(s).",
                )
        return redirect("importacao_detalhe", pk=pk)

    contexto = {"imp": imp}
    if imp.pendente:
        analise = analisar(imp.cabecalhos, imp.linhas, imp.mapeamento, request.user, imp.semestre, imp.coordenador_padrao)
        contexto.update({
            "analise": analise,
            "erros": analise.erros[:MAX_ERROS_EXIBIDOS],
            "erros_ocultos": max(0, len(analise.erros) - MAX_ERROS_EXIBIDOS),
            "colunas": _colunas(imp),
            "campos": CAMPOS,
            "mapeamento_ok": not erros_do_mapeamento(limpar_mapeamento(imp.mapeamento, len(imp.cabecalhos))),
        })
    return render(request, "core/importacao_detalhe.html", contexto)
