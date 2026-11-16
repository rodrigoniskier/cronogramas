"""Telas da importação de cronogramas: envio, conferência (mapeamento, validação,
cruzamento entre arquivos) e aplicação.

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

from . import agenda as ag
from .forms import AnexoForm, ImportacaoForm
from .importacao import (
    CAMPO, CAMPOS, LINHA_MODELO, MAX_ARQUIVOS, MAX_ERROS_EXIBIDOS, ErroImportacao, analisar, anexar, aplicar,
    completar_mapeamento, erros_do_mapeamento, gerar_planilha, limpar_mapeamento, remover_arquivo,
)
from .models import Importacao, Usuario

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _exigir_importador(usuario):
    """Importam cronogramas os mesmos perfis que cadastram componentes."""
    if not (usuario.eh_admin or usuario.eh_coordenador):
        raise PermissionDenied


def _anexar_lidos(imp, lidos):
    """Junta os arquivos lidos à conferência (em memória). Levanta ErroImportacao."""
    cabecalhos, linhas, arquivos = imp.cabecalhos, imp.linhas, imp.arquivos
    for lido in lidos:
        cabecalhos, linhas, arquivos = anexar(cabecalhos, linhas, arquivos, lido)
    imp.cabecalhos, imp.linhas, imp.arquivos = cabecalhos, linhas, arquivos
    imp.mapeamento = completar_mapeamento(imp.mapeamento, cabecalhos)
    ativos = [a["nome"] for a in arquivos if not a.get("removido")]
    imp.arquivo_nome = (ativos[0] if len(ativos) == 1 else f"{len(ativos)} arquivos: " + ", ".join(ativos))[:200]


def importar(request):
    _exigir_importador(request.user)
    form = ImportacaoForm(request.POST or None, request.FILES or None, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        imp = form.save(commit=False)
        imp.usuario = request.user
        try:
            _anexar_lidos(imp, form.lidos)
        except ErroImportacao as erro:
            form.add_error("arquivo", str(erro))
        else:
            with transaction.atomic():
                # Uma conferência por vez: rascunhos anteriores do próprio usuário são descartados.
                Importacao.objects.filter(usuario=request.user, status=Importacao.Status.PENDENTE).delete()
                imp.save()
            return redirect("importacao_detalhe", pk=imp.pk)
    return render(request, "core/importar.html", {
        "form": form,
        "importacoes": Importacao.objects.filter(usuario=request.user).defer("linhas").select_related("semestre")[:20],
        "max_arquivos": MAX_ARQUIVOS,
    })


@require_GET
def importacao_modelo(request):
    _exigir_importador(request.user)
    resposta = HttpResponse(gerar_planilha([LINHA_MODELO]), content_type=XLSX)
    resposta["Content-Disposition"] = content_disposition_header(True, "modelo_importacao_cronograma.xlsx")
    return resposta


def _colunas(imp):
    """Colunas da tabela da conferência com um valor de exemplo e o campo associado."""
    inverso = {i: campo for campo, i in limpar_mapeamento(imp.mapeamento, len(imp.cabecalhos)).items()}
    colunas = []
    for i, titulo in enumerate(imp.cabecalhos):
        exemplo = next((l["c"][i] for l in imp.linhas if i < len(l["c"]) and l["c"][i]), "")
        colunas.append({"indice": i, "titulo": titulo or f"(coluna {i + 1} sem título)", "exemplo": exemplo[:60], "campo": inverso.get(i, "")})
    return colunas


def _analisar(imp, usuario):
    return analisar(
        imp.cabecalhos, imp.linhas, imp.mapeamento, usuario, imp.semestre, imp.coordenador_padrao,
        arquivos=imp.nomes_dos_arquivos, associacoes=imp.associacoes,
    )


def importacao_detalhe(request, pk):
    _exigir_importador(request.user)
    imp = get_object_or_404(Importacao.objects.select_related("semestre", "coordenador_padrao"), pk=pk, usuario=request.user)
    anexo = AnexoForm()

    if request.method == "POST":
        acao = request.POST.get("acao")
        if not imp.pendente:
            messages.error(request, "Esta importação já foi concluída.")
        elif acao == "descartar":
            imp.delete()
            messages.info(request, "Importação descartada. Nada foi gravado.")
            return redirect("importar")
        elif acao == "anexar":
            anexo = AnexoForm(request.POST, request.FILES)
            if anexo.is_valid():
                try:
                    _anexar_lidos(imp, anexo.lidos)
                except ErroImportacao as erro:
                    messages.error(request, f"Nenhum arquivo foi anexado. {erro}")
                else:
                    imp.save()
                    messages.success(request, f"{len(anexo.lidos)} arquivo(s) anexado(s). A conferência foi refeita com todos os arquivos.")
            else:
                for erro in anexo.errors.get("arquivo", []):
                    messages.error(request, f"Nenhum arquivo foi anexado. {erro}")
        elif acao == "remover_arquivo":
            indice = request.POST.get("arquivo", "")
            ativos = [i for i, a in enumerate(imp.arquivos) if not a.get("removido")]
            if indice.isdigit() and int(indice) in ativos and len(ativos) > 1:
                imp.linhas, imp.arquivos = remover_arquivo(imp.linhas, imp.arquivos, int(indice))
                restantes = [a["nome"] for a in imp.arquivos if not a.get("removido")]
                imp.arquivo_nome = (restantes[0] if len(restantes) == 1 else f"{len(restantes)} arquivos: " + ", ".join(restantes))[:200]
                imp.save()
                messages.info(request, "Arquivo retirado da conferência.")
            else:
                messages.error(request, "Não foi possível retirar o arquivo. Para desistir de tudo, use Descartar.")
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
        elif acao == "associar":
            # De-para de nomes não reconhecidos: só aceita docentes ativos do cadastro.
            validos = set(Usuario.docentes().values_list("id", flat=True))
            associacoes = dict(imp.associacoes)
            total = request.POST.get("total", "")
            for i in range(min(int(total), 500) if total.isdigit() else 0):
                chave = ag.normalizar(request.POST.get(f"nome_{i}", ""))[:200]
                valor = request.POST.get(f"pessoa_{i}", "")
                if not chave:
                    continue
                if valor == "":
                    associacoes.pop(chave, None)
                elif valor.isdigit() and (int(valor) == 0 or int(valor) in validos):
                    associacoes[chave] = int(valor)
            imp.associacoes = associacoes
            imp.save(update_fields=["associacoes"])
            messages.success(request, "Associações de nomes atualizadas. A validação foi refeita.")
        elif acao == "aplicar":
            try:
                with transaction.atomic():
                    # Trava o registro: dois cliques não aplicam a mesma importação duas vezes.
                    travada = Importacao.objects.select_for_update(of=("self",)).select_related("semestre", "coordenador_padrao").get(pk=imp.pk)
                    if not travada.pendente:
                        raise ErroImportacao("Esta importação já foi concluída.")
                    analise = _analisar(travada, request.user)
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

    arquivos = [{**a, "indice": i} for i, a in enumerate(imp.arquivos) if not a.get("removido")]
    contexto = {"imp": imp, "arquivos": arquivos}
    if imp.pendente:
        analise = _analisar(imp, request.user)
        contexto.update({
            "analise": analise,
            "erros": analise.erros[:MAX_ERROS_EXIBIDOS],
            "erros_ocultos": max(0, len(analise.erros) - MAX_ERROS_EXIBIDOS),
            "colunas": _colunas(imp),
            "campos": CAMPOS,
            "mapeamento_ok": not erros_do_mapeamento(limpar_mapeamento(imp.mapeamento, len(imp.cabecalhos))),
            "anexo": anexo,
            "pode_anexar": len(arquivos) < MAX_ARQUIVOS,
            "docentes": Usuario.docentes().values("id", "nome", "email") if analise.pessoas else [],
        })
    return render(request, "core/importacao_detalhe.html", contexto)
