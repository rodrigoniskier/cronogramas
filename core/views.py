import json
import re
import unicodedata
import secrets
from datetime import date, datetime, time
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash, views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from . import exports
from .forms import (
    CadastroProfessorForm, ComponenteForm, ConfiguracaoForm, DataBloqueadaForm,
    LoginForm, SemestreForm, TrocaSenhaForm, UsuarioForm,
)
from .models import (
    DIAS_SEMANA, Componente, Configuracao, Conflito, DataBloqueada, Encontro,
    HistoricoAlteracao, HorarioSemanal, ObservacaoConflito, Semestre, Usuario, ch_padrao,
)
from .services import (
    STATUS, _encontro_vazio, _status, conflitos_ativos, conflitos_do_usuario,
    criar_estrutura_cronograma, estatisticas, feriados_do_componente, gerar_encontros,
    motivo_sem_edicao, pode_editar, pode_gerenciar, problemas_para_aprovacao, registrar,
    sincronizar_conflitos, tem_vinculo,
)


# ------------------------------------------------------------------ utilidades


def apenas_admin(view):
    @wraps(view)
    def _w(request, *a, **kw):
        if not request.user.eh_admin:
            raise PermissionDenied
        return view(request, *a, **kw)
    return _w


def _local(dt):
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M") if dt else ""


def _componentes():
    return Componente.objects.select_related("semestre", "coordenador")


def _com_stats(componentes):
    componentes = list(componentes)
    st = estatisticas(componentes)
    for c in componentes:
        c.st = st[c.id]
    return componentes


def encontro_json(e, ver_observacoes=True):
    return {
        "id": e.id,
        "ordem": e.ordem,
        "reposicao": e.reposicao,
        "data": e.data.isoformat() if e.data else "",
        "data_br": e.data.strftime("%d/%m/%Y") if e.data else "",
        "data_curta": e.data.strftime("%d/%m") if e.data else "",
        "dia": e.dia_semana,
        "inicio": e.hora_inicio.strftime("%H:%M") if e.hora_inicio else "",
        "fim": e.hora_fim.strftime("%H:%M") if e.hora_fim else "",
        "conteudo": e.conteudo,
        "professor_id": e.professor_id,
        "professor_ids": e.lista_professor_ids(),
        "professor_nome": e.nomes_professores(),
        "tipo": e.tipo,
        "atividade": e.atividade,
        "recursos": e.recursos,
        "grupos": e.grupos,
        "ch": e.ch,
        "local": e.local,
        "horario": e.horario_modelo,
        "horario_modelo": e.horario_modelo,
        "observacoes": e.observacoes if ver_observacoes else "",
        "excepcional": e.excepcional,
        "versao": e.versao,
        "atualizado_por": e.atualizado_por.nome if e.atualizado_por_id else "",
        "atualizado_em": _local(e.atualizado_em),
        "preenchido": e.preenchido,
    }


def _conflito_lado(c, meu, outro):
    oc = outro.componente
    return {
        "id": c.id,
        "professor": c.professor.nome,
        "data_br": c.data.strftime("%d/%m/%Y"),
        "sobreposicao": f"{c.sobreposicao_inicio:%H:%M}–{c.sobreposicao_fim:%H:%M}",
        "meu_horario": f"{meu.hora_inicio:%H:%M}–{meu.hora_fim:%H:%M}",
        "outro_componente": oc.nome,
        "outro_turma": oc.turma,
        "outro_coordenador": oc.coordenador.nome,
        "outro_horario": f"{outro.hora_inicio:%H:%M}–{outro.hora_fim:%H:%M}",
        "outro_url": f"/componentes/{oc.id}/cronograma/#encontro-{outro.id}",
        "detalhe_url": f"/conflitos/{c.id}/",
    }


def estado_json(componente, usuario):
    vinculado = tem_vinculo(usuario, componente)
    encontros = list(
        componente.encontros.select_related("professor", "atualizado_por").prefetch_related("professores")
    )
    mapa = {}
    conflitos_ids = set()
    for c in conflitos_ativos().filter(
        Q(encontro_a__componente=componente) | Q(encontro_b__componente=componente)
    ):
        conflitos_ids.add(c.id)
        for meu, outro in ((c.encontro_a, c.encontro_b), (c.encontro_b, c.encontro_a)):
            if meu.componente_id == componente.id:
                mapa.setdefault(meu.id, []).append(_conflito_lado(c, meu, outro))
    ultimo = max((e for e in encontros if e.atualizado_em), key=lambda e: e.atualizado_em, default=None)
    contaveis = [e for e in encontros if not e.reposicao or not _encontro_vazio(e)]
    total = len(contaveis)
    preenchidos = sum(1 for e in contaveis if e.preenchido)
    iniciados = sum(1 for e in contaveis if not _encontro_vazio(e))
    n_conf = len(conflitos_ids)
    codigo = _status(componente, total, preenchidos, n_conf, iniciados=iniciados)
    rotulo, cor, icone = STATUS[codigo]
    return {
        "encontros": [encontro_json(e, ver_observacoes=vinculado) for e in encontros],
        "conflitos": mapa,
        "feriados": [
            {"data": f["data"].isoformat(), "data_br": f["data"].strftime("%d/%m/%Y"), "inicio": f["hora_inicio"].strftime("%H:%M"),
             "horario": f["horario"], "descricao": f["descricao"], "ch": f["ch"]}
            for f in feriados_do_componente(componente)
        ],
        "stats": {
            "total": total,
            "preenchidos": preenchidos,
            "pct": round(100 * preenchidos / total) if total else 0,
            "conflitos": n_conf,
            "status": codigo,
            "status_rotulo": rotulo,
            "status_cor": cor,
            "status_icone": icone,
        },
        "situacao": componente.situacao,
        "ultima_edicao": (
            {"por": ultimo.atualizado_por.nome if ultimo.atualizado_por_id else "—", "em": _local(ultimo.atualizado_em)}
            if ultimo else None
        ),
        "pode_editar": pode_editar(usuario, componente),
    }


# --------------------------------------------------------- alteração de encontro

CAMPOS_TEXTO = ("conteudo", "tipo", "atividade", "recursos", "grupos", "ch", "local", "observacoes")
LIMITES = {"grupos": 300, "ch": 10, "local": 120}
TIPOS_VALIDOS = {t for t, _ in Encontro.TIPOS}
CAMPOS_AGENDA = ("data", "inicio", "fim", "horario")
ROTULOS = {
    "conteudo": "Conteúdo", "tipo": "Tipo", "atividade": "Atividades", "recursos": "Recursos",
    "grupos": "Grupos", "ch": "CH", "local": "Local",
    "observacoes": "Observações", "professor_id": "Professor", "professor_ids": "Docente(s)",
    "data": "Data", "inicio": "Início", "fim": "Término", "horario": "Horário",
}


class ErroEdicao(Exception):
    def __init__(self, mensagem, status=400, extra=None):
        self.mensagem, self.status, self.extra = mensagem, status, extra or {}


def _parse_data_flex(valor, ano_padrao=None):
    if valor in (None, ""):
        return ""
    s = str(valor).strip()
    if not s:
        return ""
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", s)
    if m:
        dia, mes, ano_s = int(m.group(1)), int(m.group(2)), m.group(3)
        ano = (int(ano_s) + 2000 if len(ano_s) == 2 else int(ano_s)) if ano_s else (ano_padrao or date.today().year)
        try:
            return date(ano, mes, dia).isoformat()
        except ValueError:
            pass
    raise ErroEdicao("Data: valor inválido (use DD/MM, DD/MM/AAAA ou AAAA-MM-DD).")


def _parse_hora_flex(valor):
    if valor in (None, ""):
        return ""
    s = str(valor).strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{1,2})(?:[:hH](\d{2})?)?", s)
    if m:
        try:
            return time(int(m.group(1)), int(m.group(2) or 0)).strftime("%H:%M")
        except ValueError:
            pass
    try:
        return time.fromisoformat(s[:5]).strftime("%H:%M")
    except ValueError:
        raise ErroEdicao("Horário: valor inválido.")


def _parse_horario_intervalo(valor):
    if valor in (None, ""):
        return ""
    s = str(valor).strip()
    if not s:
        return ""
    partes = re.split(r"\s*(?:[-–—/]|às|as|a)\s*", s, maxsplit=1)
    if len(partes) != 2:
        raise ErroEdicao("Horário: informe início e término (ex.: 15h30-18h ou 08h-12h).")
    ini = _parse_hora_flex(partes[0])
    fim = _parse_hora_flex(partes[1])
    if not (ini and fim):
        raise ErroEdicao("Horário: informe início e término (ex.: 15h30-18h).")
    if time.fromisoformat(fim) <= time.fromisoformat(ini):
        raise ErroEdicao("O horário de término deve ser posterior ao de início.")
    return f"{ini}-{fim}"


def _valor_atual(e, campo):
    if campo in CAMPOS_TEXTO:
        return getattr(e, campo)
    if campo == "professor_id":
        return e.professor_id
    if campo == "professor_ids":
        return e.lista_professor_ids()
    if campo == "data":
        return e.data.isoformat() if e.data else ""
    if campo == "inicio":
        return e.hora_inicio.strftime("%H:%M") if e.hora_inicio else ""
    if campo == "fim":
        return e.hora_fim.strftime("%H:%M") if e.hora_fim else ""
    if campo == "horario":
        return f"{e.hora_inicio:%H:%M}-{e.hora_fim:%H:%M}" if (e.hora_inicio and e.hora_fim) else ""
    return ""


def _normalizar(campo, valor, ano_padrao=None):
    if campo in CAMPOS_TEXTO:
        valor = "" if valor is None else str(valor).strip()
        if campo == "tipo" and valor not in TIPOS_VALIDOS:
            raise ErroEdicao("Tipo inválido (use T, P, T/P ou -).")
        if len(valor) > LIMITES.get(campo, 5000):
            raise ErroEdicao(f"{ROTULOS[campo]}: máximo de {LIMITES.get(campo, 5000)} caracteres.")
        return valor
    if campo == "professor_id":
        if valor in (None, "", 0, "0"):
            return None
        try:
            return int(valor)
        except (TypeError, ValueError):
            raise ErroEdicao("Professor inválido.")
    if campo == "professor_ids":
        if valor in (None, ""):
            return []
        if not isinstance(valor, (list, tuple)):
            raise ErroEdicao("Lista de docentes inválida.")
        ids = []
        for item in valor:
            if item in (None, "", 0, "0"):
                continue
            try:
                pid = int(item)
            except (TypeError, ValueError):
                raise ErroEdicao("Professor inválido.")
            if pid not in ids:
                ids.append(pid)
        return ids
    if campo == "data":
        return _parse_data_flex(valor, ano_padrao=ano_padrao)
    if campo == "horario":
        return _parse_horario_intervalo(valor)
    return _parse_hora_flex(valor)


@transaction.atomic
def alterar_encontro(usuario, pk, campos, base=None, versao=None, forcar=False):
    """Aplica alterações a um encontro com controle de concorrência por campo.

    Se outro usuário alterou o MESMO campo desde que o cliente o carregou
    (valor atual != valor-base enviado), levanta ErroEdicao 409 em vez de
    sobrescrever. Alterações em campos diferentes são mescladas.
    """
    if not isinstance(campos, dict) or (base is not None and not isinstance(base, dict)):
        raise ErroEdicao("Requisição inválida.")

    try:
        e = Encontro.objects.select_for_update(of=("self",)).select_related(
            "componente__semestre", "componente__coordenador", "professor", "atualizado_por"
        ).prefetch_related("professores").get(pk=pk)
    except Encontro.DoesNotExist:
        raise ErroEdicao("Este encontro não existe mais (pode ter sido removido).", 404)
    comp = e.componente
    motivo = motivo_sem_edicao(usuario, comp)
    if motivo:
        raise ErroEdicao(motivo, 403)

    permitidos = set(CAMPOS_TEXTO) | {"professor_id", "professor_ids"}
    if pode_gerenciar(usuario, comp):
        permitidos |= set(CAMPOS_AGENDA)
    else:
        if e.data is None:
            permitidos.add("data")
        if e.hora_inicio is None or e.hora_fim is None:
            permitidos |= {"horario", "inicio", "fim"}

    ano_padrao = comp.data_inicio.year if comp.data_inicio else None
    novos = {}
    for campo, valor in campos.items():
        if campo not in permitidos:
            raise ErroEdicao(f"Você não tem permissão para alterar o campo “{ROTULOS.get(campo, campo)}”.", 403)
        novos[campo] = _normalizar(campo, valor, ano_padrao=ano_padrao)

    if versao is not None and versao != e.versao and not forcar:
        base = base or {}
        divergentes = [
            c for c, novo in novos.items()
            if (c not in base or _valor_atual(e, c) != _normalizar(c, base[c], ano_padrao=ano_padrao))
            and _valor_atual(e, c) != novo
        ]
        if divergentes:
            raise ErroEdicao(
                "Outro usuário alterou este encontro enquanto você editava.", 409,
                {"campos": divergentes, "rotulos": {c: ROTULOS[c] for c in divergentes}},
            )

    mudancas = {c: v for c, v in novos.items() if _valor_atual(e, c) != v}
    if not mudancas:
        return e, False

    docentes_afetados = set(e.lista_professor_ids())
    novos_profs_m2m = None
    for campo, novo in mudancas.items():
        anterior = _valor_atual(e, campo)
        if campo == "professor_id":
            nome_ant = e.nomes_professores()
            if novo is not None:
                prof = Usuario.docentes().filter(pk=novo).first()
                if not prof:
                    raise ErroEdicao("Professor não encontrado no cadastro de docentes ativos.")
                e.professor = prof
                novos_profs_m2m = [prof]
            else:
                e.professor = None
                novos_profs_m2m = []
            registrar(usuario, comp, "Professor", nome_ant, e.professor.nome if e.professor else "", e)
        elif campo == "professor_ids":
            nome_ant = e.nomes_professores()
            mapa_profs = {p.id: p for p in Usuario.docentes().filter(pk__in=novo)}
            if len(mapa_profs) != len(novo):
                raise ErroEdicao("Professor não encontrado no cadastro de docentes ativos.")
            lista_profs = [mapa_profs[pid] for pid in novo]
            e.professor = lista_profs[0] if lista_profs else None
            novos_profs_m2m = lista_profs
            registrar(usuario, comp, "Professor", nome_ant, ", ".join(p.nome for p in lista_profs), e)
        else:
            if campo == "data":
                e.data = date.fromisoformat(novo) if novo else None
            elif campo == "inicio":
                e.hora_inicio = time.fromisoformat(novo) if novo else None
            elif campo == "fim":
                e.hora_fim = time.fromisoformat(novo) if novo else None
            elif campo == "horario":
                if novo:
                    ini_s, fim_s = novo.split("-")
                    e.hora_inicio = time.fromisoformat(ini_s)
                    e.hora_fim = time.fromisoformat(fim_s)
                    if not e.ch and "ch" not in mudancas:
                        e.ch = ch_padrao(e.hora_inicio, e.hora_fim)
                else:
                    e.hora_inicio = None
                    e.hora_fim = None
            else:
                setattr(e, campo, novo)
            registrar(usuario, comp, ROTULOS[campo], anterior, novo, e)
    if e.hora_inicio and e.hora_fim and e.hora_fim <= e.hora_inicio:
        raise ErroEdicao("O horário de término deve ser posterior ao de início.")
    if set(mudancas) & set(CAMPOS_AGENDA):
        e.excepcional = True
    e.versao += 1
    e.atualizado_por = usuario
    e.atualizado_em = timezone.now()
    e.save()
    if novos_profs_m2m is not None:
        e.professores.set(novos_profs_m2m)
        e._prefetched_objects_cache = {}
    docentes_afetados.update(e.lista_professor_ids())
    if set(mudancas) & ({"professor_id", "professor_ids"} | set(CAMPOS_AGENDA)):
        sincronizar_conflitos(docentes_afetados)
    return e, True


def _json_corpo(request):
    try:
        dados = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ErroEdicao("Requisição inválida.")
    if not isinstance(dados, dict):
        raise ErroEdicao("Requisição inválida.")
    return dados


def _erro_json(err):
    return JsonResponse({"erro": err.mensagem, **err.extra}, status=err.status)


@require_POST
def api_encontro_salvar(request, pk):
    try:
        d = _json_corpo(request)
        try:
            e, _ = alterar_encontro(
                request.user, pk, d.get("campos") if "campos" in d else {}, d.get("base"), d.get("versao"), bool(d.get("forcar"))
            )
        except ErroEdicao as err:
            if err.status == 409:
                atual = Encontro.objects.select_related(
                    "professor", "atualizado_por", "componente"
                ).prefetch_related("professores").get(pk=pk)
                err.extra["encontro"] = encontro_json(atual, ver_observacoes=tem_vinculo(request.user, atual.componente))
            raise
    except ErroEdicao as err:
        return _erro_json(err)
    return JsonResponse({
        "encontro": encontro_json(e, ver_observacoes=tem_vinculo(request.user, e.componente)),
        "estado": estado_json(e.componente, request.user),
    })


@require_safe
def api_estado(request, pk):
    comp = get_object_or_404(_componentes(), pk=pk)
    return JsonResponse(estado_json(comp, request.user))


@require_POST
def api_encontro_criar(request, pk):
    comp = get_object_or_404(_componentes(), pk=pk)
    if not pode_gerenciar(request.user, comp):
        return JsonResponse({"erro": "Apenas o coordenador responsável ou a administração podem inserir encontros."}, status=403)
    if comp.bloqueado:
        return JsonResponse({"erro": "Reabra o cronograma para revisão antes de inserir encontros."}, status=403)
    if not request.user.eh_admin and not comp.semestre.preenchimento_liberado:
        return JsonResponse({"erro": "O período de preenchimento deste semestre ainda não foi liberado pela administração."}, status=403)
    try:
        d = _json_corpo(request)
        data_s = _normalizar("data", d.get("data"), ano_padrao=comp.data_inicio.year if comp.data_inicio else None)
        ini_s = _normalizar("inicio", d.get("inicio"))
        fim_s = _normalizar("fim", d.get("fim"))
        if not (data_s and ini_s and fim_s):
            raise ErroEdicao("Informe data, início e término.")
        dia = date.fromisoformat(data_s)
        ini = time.fromisoformat(ini_s)
        fim = time.fromisoformat(fim_s)
        if fim <= ini:
            raise ErroEdicao("O horário de término deve ser posterior ao de início.")
        with transaction.atomic():
            # Copia o conteúdo de um encontro já existente no mesmo dia/horário:
            # é o caso de um segundo docente (ou grupo) na mesma aula.
            irmao = (
                comp.encontros.filter(data=dia, hora_inicio=ini, hora_fim=fim).first()
                or comp.encontros.filter(data=dia, hora_inicio=ini).first()
            )
            e = Encontro.objects.create(
                componente=comp, data=dia, hora_inicio=ini, hora_fim=fim, excepcional=True,
                local=irmao.local if irmao else comp.local_padrao,
                ch=(irmao.ch or ch_padrao(ini, fim)) if irmao else ch_padrao(ini, fim),
                conteudo=irmao.conteudo if irmao else "", tipo=irmao.tipo if irmao else "",
                atividade=irmao.atividade if irmao else "", recursos=irmao.recursos if irmao else "",
                grupos=irmao.grupos if irmao else "",
                atualizado_por=request.user, atualizado_em=timezone.now(),
            )
            registrar(request.user, comp, "Encontro inserido", "", e.descricao, e)
    except ErroEdicao as err:
        return _erro_json(err)
    return JsonResponse({"encontro_id": e.id, "estado": estado_json(comp, request.user)})


@require_POST
def api_encontro_excluir(request, pk):
    e = get_object_or_404(
        Encontro.objects.select_related("componente__semestre", "componente__coordenador").prefetch_related("professores"),
        pk=pk,
    )
    comp = e.componente
    if not pode_gerenciar(request.user, comp):
        return JsonResponse({"erro": "Apenas o coordenador responsável ou a administração podem remover encontros."}, status=403)
    if comp.bloqueado:
        return JsonResponse({"erro": "Reabra o cronograma para revisão antes de remover encontros."}, status=403)
    if not request.user.eh_admin and not comp.semestre.preenchimento_liberado:
        return JsonResponse({"erro": "O período de preenchimento deste semestre ainda não foi liberado pela administração."}, status=403)
    with transaction.atomic():
        profs = set(e.lista_professor_ids())
        registrar(request.user, comp, "Encontro removido", f"{e.descricao} — {e.conteudo[:80]}", "")
        e.delete()
        sincronizar_conflitos(profs)
    return JsonResponse({"estado": estado_json(comp, request.user)})


@require_safe
def api_encontro_historico(request, pk):
    e = get_object_or_404(Encontro.objects.select_related("componente"), pk=pk)
    qs = HistoricoAlteracao.objects.filter(encontro=e).select_related("usuario")
    if not tem_vinculo(request.user, e.componente):
        qs = qs.exclude(campo="Observações")
    itens = qs[:100]
    return JsonResponse({"itens": [
        {"quando": _local(h.data_hora), "usuario": h.usuario.nome if h.usuario else "—",
         "campo": h.campo, "anterior": h.valor_anterior, "novo": h.valor_novo}
        for h in itens
    ]})


# ---------------------------------------------------------------- acesso


def _ip_cliente(request):
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "desconhecido")


def _incrementar_tentativa(chave, janela):
    atual = cache.get(chave, 0)
    cache.set(chave, atual + 1, timeout=janela)


_login_view = auth_views.LoginView.as_view(authentication_form=LoginForm, redirect_authenticated_user=True)


def _erro_limite(form, mensagem: str) -> None:
    """Registra erro de limite de tentativas sem executar validação pesada (ex.: hash de senha)."""
    from django.forms.utils import ErrorDict

    form._errors = ErrorDict()
    form.cleaned_data = {}
    form.add_error(None, mensagem)


@login_not_required
@sensitive_post_parameters()
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def entrar(request):
    if request.method == "POST" and not request.user.is_authenticated:
        ip = _ip_cliente(request)
        ident = (request.POST.get("username") or "").strip().lower()[:150]
        limite = getattr(settings, "CRONOMED_LIMITE_LOGIN_TENTATIVAS", 10)
        janela = getattr(settings, "CRONOMED_LIMITE_LOGIN_JANELA", 300)
        chave_ip = f"cronomed:login:ip:{ip}"
        chave_id = f"cronomed:login:id:{ip}:{ident}" if ident else None
        if cache.get(chave_ip, 0) >= limite * 3 or (chave_id and cache.get(chave_id, 0) >= limite):
            form = LoginForm(request)
            _erro_limite(form, "Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente.")
            return render(request, "registration/login.html", {"form": form, "next": request.POST.get("next", "")}, status=429)
        resposta = _login_view(request)
        if resposta.status_code == 200:
            _incrementar_tentativa(chave_ip, janela)
            if chave_id:
                _incrementar_tentativa(chave_id, janela)
        elif resposta.status_code in (301, 302) and chave_id:
            cache.delete(chave_id)
        return resposta
    return _login_view(request)


@login_not_required
@sensitive_post_parameters()
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def cadastro_professor(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = CadastroProfessorForm(
        request.POST if request.method == "POST" else None,
        instance=Usuario(perfil=Usuario.Perfil.PROF),
    )
    if request.method == "POST":
        ip = _ip_cliente(request)
        limite = getattr(settings, "CRONOMED_LIMITE_CADASTRO_TENTATIVAS", 30)
        janela = getattr(settings, "CRONOMED_LIMITE_CADASTRO_JANELA", 600)
        chave_ip = f"cronomed:cadastro:ip:{ip}"
        if cache.get(chave_ip, 0) >= limite:
            _erro_limite(form, "Muitas tentativas de cadastro a partir deste endereço. Aguarde alguns minutos.")
            return render(request, "registration/cadastro.html", {"form": form}, status=429)
        _incrementar_tentativa(chave_ip, janela)

    if form.is_valid():
        try:
            with transaction.atomic():
                usuario = form.save()
        except IntegrityError:
            # Outra requisição pode cadastrar o mesmo e-mail ou login após a validação.
            form.validate_unique()
            if not form.errors:
                raise
        else:
            login(request, usuario)
            return redirect("dashboard")
    return render(request, "registration/cadastro.html", {"form": form})


# ---------------------------------------------------------------- dashboard


def _int_ch(valor, padrao=0):
    if valor in (None, ""):
        return padrao
    m = re.search(r"\d+", str(valor))
    if not m:
        return padrao
    return max(0, min(9999, int(m.group(0))))


def _obter_ou_criar_semestre(nome_bruto):
    nome = (nome_bruto or "").strip()[:40]
    if not nome:
        nome = f"{date.today().year}/2"
    sem = Semestre.objects.filter(nome__iexact=nome).first()
    if sem:
        if not sem.preenchimento_liberado:
            sem.preenchimento_liberado = True
            sem.liberado_em = timezone.now()
            sem.save(update_fields=["preenchimento_liberado", "liberado_em"])
        return sem
    m = re.search(r"(\d{4})\D*([12])?", nome)
    ano = int(m.group(1)) if m else date.today().year
    metade = m.group(2) if (m and m.group(2)) else "2"
    if metade == "1":
        ini, fim = date(ano, 2, 1), date(ano, 6, 30)
    else:
        ini, fim = date(ano, 8, 1), date(ano, 12, 18)
    return Semestre.objects.create(
        nome=nome,
        data_inicio=ini,
        data_fim=fim,
        preenchimento_liberado=True,
        liberado_em=timezone.now(),
    )


def _profs_componente(comp):
    ids = set(comp.encontros.values_list("professor_id", flat=True))
    ids.update(
        Encontro.professores.through.objects.filter(encontro__componente=comp).values_list("usuario_id", flat=True)
    )
    return ids


@require_http_methods(["GET", "HEAD", "POST"])
def dashboard(request):
    u = request.user
    erros_cadastro = []
    semestres = list(Semestre.objects.all())
    semestre_padrao = semestres[0].nome if semestres else f"{date.today().year}/2"
    dados_form = {
        "curso": "Medicina",
        "nome": "",
        "carga_horaria": "",
        "ch_teorica": "",
        "ch_pratica": "",
        "semestre_nome": semestre_padrao,
        "periodo": "",
        "turma": "",
        "coordenador": str(u.id),
    }

    if request.method == "POST":
        dados_form = {
            "curso": (request.POST.get("curso") or "Medicina").strip()[:80] or "Medicina",
            "nome": (request.POST.get("nome") or "").strip()[:150],
            "carga_horaria": (request.POST.get("carga_horaria") or "").strip(),
            "ch_teorica": (request.POST.get("ch_teorica") or "").strip(),
            "ch_pratica": (request.POST.get("ch_pratica") or "").strip(),
            "semestre_nome": (request.POST.get("semestre_nome") or "").strip()[:40],
            "periodo": (request.POST.get("periodo") or "").strip()[:20],
            "turma": (request.POST.get("turma") or "").strip()[:30],
            "coordenador": (request.POST.get("coordenador") or str(u.id)).strip(),
        }
        if not dados_form["nome"]:
            erros_cadastro.append("Informe o nome do Componente Curricular.")
        if not dados_form["semestre_nome"]:
            erros_cadastro.append("Informe o Semestre (ex.: 2026/2).")
        if not dados_form["turma"]:
            erros_cadastro.append("Informe a Turma (ex.: A).")

        coord = u
        if dados_form["coordenador"].isdigit():
            coord_cand = Usuario.objects.filter(is_active=True, pk=int(dados_form["coordenador"])).first()
            if coord_cand:
                coord = coord_cand

        if not erros_cadastro:
            try:
                with transaction.atomic():
                    sem = _obter_ou_criar_semestre(dados_form["semestre_nome"])
                    comp = Componente.objects.create(
                        curso=dados_form["curso"],
                        nome=dados_form["nome"],
                        periodo=dados_form["periodo"],
                        turma=dados_form["turma"],
                        semestre=sem,
                        carga_horaria=_int_ch(dados_form["carga_horaria"], 0),
                        ch_teorica=_int_ch(dados_form["ch_teorica"], 0),
                        ch_pratica=_int_ch(dados_form["ch_pratica"], 0),
                        coordenador=coord,
                        data_inicio=sem.data_inicio,
                        data_fim=sem.data_fim,
                    )
                    comp.professores.add(u)
                    if coord.id != u.id:
                        comp.professores.add(coord)
                    criar_estrutura_cronograma(comp, total_aulas=20, total_reposicoes=3)
                    registrar(
                        u, comp, "Cadastro do componente", "",
                        "Componente criado com estrutura de 20 aulas",
                    )
            except IntegrityError:
                erros_cadastro.append("Já existe este componente para a mesma turma e semestre.")
            else:
                messages.success(
                    request,
                    "Informações básicas cadastradas. Preencha abaixo as 20 linhas do cronograma clicando diretamente nos campos.",
                )
                return redirect("cronograma", pk=comp.pk)

    semestres = Semestre.objects.all()
    sem_id = request.GET.get("semestre", "")
    qs = _componentes()
    if sem_id.isdigit():
        qs = qs.filter(semestre_id=sem_id)
    componentes = _com_stats(qs)
    meus_ids = set(u.componentes_vinculados.values_list("id", flat=True)) | set(
        u.componentes_coordenados.values_list("id", flat=True)
    )
    for c in componentes:
        c.meu = c.id in meus_ids
    if request.GET.get("meus") == "1":
        componentes = [c for c in componentes if c.meu]
    componentes.sort(key=lambda c: (not c.meu, c.nome, c.turma))
    total_enc = sum(c.st["total"] for c in componentes)
    preench = sum(c.st["preenchidos"] for c in componentes)
    ids = [c.id for c in componentes]
    n_conf = conflitos_ativos().filter(
        Q(encontro_a__componente__in=ids) | Q(encontro_b__componente__in=ids)
    ).count()
    cont = lambda s: sum(1 for c in componentes if c.st["status"] == s)
    pendencias = list(conflitos_do_usuario(u)[:8])
    for c in pendencias:
        c.url_a = f"/componentes/{c.encontro_a.componente_id}/cronograma/#encontro-{c.encontro_a_id}"
    return render(request, "core/dashboard.html", {
        "componentes": componentes,
        "semestres": semestres,
        "sem_id": sem_id,
        "so_meus": request.GET.get("meus") == "1",
        "dados_form": dados_form,
        "erros_cadastro": erros_cadastro,
        "docentes_ativos": Usuario.objects.filter(is_active=True).order_by("nome"),
        "ind": {
            "componentes": len(componentes),
            "professores": Usuario.docentes().count(),
            "encontros": total_enc,
            "preenchidos": preench,
            "pct": round(100 * preench / total_enc) if total_enc else 0,
            "conflitos": n_conf,
            "pendencias": cont("COM_PENDENCIAS"),
            "prontos": cont("PRONTO"),
            "aprovados": cont("APROVADO") + cont("PUBLICADO"),
        },
        "pendencias": pendencias,
        "avisar": bool(request.session.pop("avisar_pendencias", False)) and bool(pendencias),
        "meus_coordenados": [c for c in componentes if c.coordenador_id == u.id],
    })


@require_POST
def componente_cabecalho_salvar(request, pk):
    comp = get_object_or_404(_componentes(), pk=pk)
    u = request.user
    if not pode_editar(u, comp):
        messages.error(request, motivo_sem_edicao(u, comp) or "Sem permissão para alterar este cronograma.")
        return redirect("cronograma", pk=comp.pk)
    curso = (request.POST.get("curso") or comp.curso or "Medicina").strip()[:80]
    nome = (request.POST.get("nome") or comp.nome).strip()[:150]
    periodo = (request.POST.get("periodo") or "").strip()[:20]
    turma = (request.POST.get("turma") or comp.turma).strip()[:30]
    semestre_nome = (request.POST.get("semestre_nome") or comp.semestre.nome).strip()[:40]
    carga_horaria = _int_ch(request.POST.get("carga_horaria"), comp.carga_horaria)
    ch_teorica = _int_ch(request.POST.get("ch_teorica"), comp.ch_teorica)
    ch_pratica = _int_ch(request.POST.get("ch_pratica"), comp.ch_pratica)
    coord_id = (request.POST.get("coordenador") or "").strip()

    try:
        with transaction.atomic():
            sem = _obter_ou_criar_semestre(semestre_nome) if semestre_nome else comp.semestre
            comp.curso = curso
            comp.nome = nome
            comp.periodo = periodo
            comp.turma = turma
            comp.semestre = sem
            comp.carga_horaria = carga_horaria
            comp.ch_teorica = ch_teorica
            comp.ch_pratica = ch_pratica
            if coord_id.isdigit() and pode_gerenciar(u, comp):
                novo_coord = Usuario.objects.filter(is_active=True, pk=int(coord_id)).first()
                if novo_coord:
                    comp.coordenador = novo_coord
                    comp.professores.add(novo_coord)
            comp.save()
            registrar(u, comp, "Cabeçalho do componente", "", f"{comp.nome} — Turma {comp.turma} ({comp.semestre.nome})")
    except IntegrityError:
        messages.error(request, "Já existe um componente com este nome, turma e semestre.")
    else:
        messages.success(request, "Informações básicas do componente atualizadas.")
    return redirect("cronograma", pk=comp.pk)


# --------------------------------------------------------------- componentes


def componentes_lista(request):
    sem_id = request.GET.get("semestre", "")
    qs = _componentes()
    if sem_id.isdigit():
        qs = qs.filter(semestre_id=sem_id)
    return render(request, "core/componentes.html", {
        "componentes": _com_stats(qs),
        "semestres": Semestre.objects.all(),
        "sem_id": sem_id,
        "pode_criar": request.user.eh_admin or request.user.eh_coordenador,
    })


def _ler_horarios(post):
    """Lê as linhas de horário semanal do formulário. Retorna (lista, erros)."""
    horarios, erros = [], []
    for d, i, f in zip(post.getlist("h_dia"), post.getlist("h_inicio"), post.getlist("h_fim")):
        if not (d or i or f):
            continue
        try:
            dia, ini, fim = int(d), time.fromisoformat(i), time.fromisoformat(f)
            if dia not in range(7) or fim <= ini:
                raise ValueError
            horarios.append((dia, ini, fim))
        except ValueError:
            erros.append("Há um horário semanal inválido (verifique dia, início e término).")
    if not horarios and not erros:
        erros.append("Informe ao menos um horário semanal.")
    if len({(d, i) for d, i, _ in horarios}) != len(horarios):
        erros.append("Há horários semanais repetidos.")
    else:
        por_dia = {}
        for d, i, f in sorted(horarios):
            if any(i < f_ant and i_ant < f for i_ant, f_ant in por_dia.get(d, [])):
                erros.append("Há horários semanais sobrepostos no mesmo dia da semana.")
                break
            por_dia.setdefault(d, []).append((i, f))
    return horarios, erros


def componente_form(request, pk=None):
    u = request.user
    comp = get_object_or_404(_componentes(), pk=pk) if pk else None
    if comp:
        if not pode_gerenciar(u, comp):
            raise PermissionDenied
        if comp.bloqueado:
            messages.warning(request, "Cronograma aprovado/publicado: reabra-o para revisão antes de alterar o cadastro.")
            return redirect("cronograma", pk=comp.pk)
    elif not (u.eh_admin or u.eh_coordenador):
        raise PermissionDenied

    form = ComponenteForm(request.POST or None, instance=comp, usuario=u)
    horarios = [(h.dia_semana, h.hora_inicio, h.hora_fim) for h in comp.horarios.all()] if comp else []
    erros_h = []
    if request.method == "POST":
        horarios, erros_h = _ler_horarios(request.POST)
        if form.is_valid() and not erros_h:
            try:
                with transaction.atomic():
                    obj = form.save(commit=False)
                    if not u.eh_admin:
                        obj.coordenador = u
                    obj.save()
                    form.save_m2m()
                    obj.horarios.all().delete()
                    HorarioSemanal.objects.bulk_create(
                        [HorarioSemanal(componente=obj, dia_semana=d, hora_inicio=i, hora_fim=f) for d, i, f in horarios]
                    )
                    criados, removidos, preservados = gerar_encontros(obj)
                    registrar(u, obj, "Cadastro do componente", "", "Componente criado" if not comp else "Cadastro atualizado")
            except IntegrityError:
                form.add_error("nome", "Já existe este componente para a mesma turma e semestre.")
            else:
                msg = f"Componente salvo. Encontros gerados: {criados} novo(s), {removidos} removido(s)."
                if preservados:
                    msg += f" {preservados} encontro(s) já preenchido(s) fora da grade foram preservados como excepcionais."
                messages.success(request, msg)
                return redirect("cronograma", pk=obj.pk)
    return render(request, "core/componente_form.html", {
        "form": form, "comp": comp, "erros_h": erros_h, "dias": DIAS_SEMANA,
        "horarios": [(d, i.strftime("%H:%M"), f.strftime("%H:%M")) for d, i, f in horarios] or [("", "", "")],
    })


@require_POST
def componente_excluir(request, pk):
    comp = get_object_or_404(Componente, pk=pk)
    if not pode_gerenciar(request.user, comp):
        raise PermissionDenied
    if comp.bloqueado:
        messages.error(request, "Componentes aprovados ou publicados não podem ser excluídos.")
        return redirect("cronograma", pk=pk)
    with transaction.atomic():
        profs = _profs_componente(comp)
        nome = str(comp)
        comp.delete()
        sincronizar_conflitos(profs)
    messages.success(request, f"Componente “{nome}” excluído.")
    return redirect("componentes")


def cronograma(request, pk):
    comp = get_object_or_404(_componentes(), pk=pk)
    u = request.user
    docentes = list(Usuario.docentes().values("id", "nome"))
    vinculados = set(comp.professores.values_list("id", flat=True)) | {comp.coordenador_id}
    for d in docentes:
        d["vinculado"] = d["id"] in vinculados
    return render(request, "core/cronograma.html", {
        "comp": comp,
        "professores": comp.professores.all(),
        "horarios": comp.horarios.all(),
        "estado": estado_json(comp, u),
        "docentes": docentes,
        "docentes_ativos": Usuario.objects.filter(is_active=True).order_by("nome"),
        "gerencia": pode_gerenciar(u, comp),
        "pode_editar_cronograma": pode_editar(u, comp),
        "motivo": motivo_sem_edicao(u, comp),
        "outros": _componentes().filter(semestre=comp.semestre),
    })


@require_POST
def componente_validar(request, pk):
    comp = get_object_or_404(_componentes(), pk=pk)
    sincronizar_conflitos(_profs_componente(comp))
    u = request.user
    sem_liberado = u.eh_admin or comp.semestre.preenchimento_liberado
    return JsonResponse({
        "problemas": problemas_para_aprovacao(comp),
        "estado": estado_json(comp, u),
        "pode_aprovar": pode_gerenciar(u, comp) and sem_liberado and comp.situacao == Componente.Situacao.RASCUNHO,
    })


@require_POST
def componente_transicao(request, pk, acao):
    with transaction.atomic():
        comp = get_object_or_404(Componente.objects.select_for_update(of=("self",)).select_related("semestre"), pk=pk)
        u = request.user
        if not pode_gerenciar(u, comp):
            raise PermissionDenied
        if not u.eh_admin and not comp.semestre.preenchimento_liberado:
            messages.error(request, "O período de preenchimento deste semestre ainda não foi liberado pela administração.")
            return redirect("cronograma", pk=pk)
        S = Componente.Situacao
        agora = timezone.now()
        if acao == "aprovar" and comp.situacao == S.RASCUNHO:
            sincronizar_conflitos(_profs_componente(comp))
            problemas = problemas_para_aprovacao(comp)
            if problemas:
                messages.error(request, f"Aprovação impedida: {len(problemas)} pendência(s). Use “Validar cronograma” para ver a lista.")
            else:
                comp.situacao, comp.aprovado_por, comp.aprovado_em = S.APROVADO, u, agora
                comp.save()
                registrar(u, comp, "Situação", "Em elaboração", "Aprovado")
                messages.success(request, "Cronograma aprovado. A versão oficial já pode ser exportada.")
        elif acao == "publicar" and comp.situacao == S.APROVADO:
            comp.situacao, comp.publicado_por, comp.publicado_em = S.PUBLICADO, u, agora
            comp.save()
            registrar(u, comp, "Situação", "Aprovado", "Publicado")
            messages.success(request, "Cronograma publicado.")
        elif acao == "reabrir" and comp.situacao in (S.APROVADO, S.PUBLICADO):
            anterior = comp.get_situacao_display()
            comp.situacao = S.RASCUNHO
            comp.aprovado_por = comp.aprovado_em = comp.publicado_por = comp.publicado_em = None
            comp.save()
            motivo = request.POST.get("motivo", "").strip()[:300]
            registrar(u, comp, "Situação", anterior, "Reaberto para revisão" + (f" — {motivo}" if motivo else ""))
            messages.warning(request, "Cronograma reaberto para revisão. Será necessária nova aprovação.")
        else:
            messages.error(request, "Ação não disponível na situação atual do cronograma.")
    return redirect("cronograma", pk=pk)


def exportar(request, pk, formato):
    comp = get_object_or_404(_componentes(), pk=pk)
    oficial = comp.situacao in (Componente.Situacao.APROVADO, Componente.Situacao.PUBLICADO)
    encontros = exports.linhas_cronograma(comp)
    sufixo = "" if oficial else "_RASCUNHO"
    base = f"Cronograma_{comp.nome}_Turma_{comp.turma}_{comp.semestre.nome}{sufixo}"
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    nome = re.sub(r"_+", "_", "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in base)).strip("_")
    if formato == "docx":
        dados = exports.gerar_docx(comp, encontros, oficial)
        tipo = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif formato == "pdf":
        dados = exports.gerar_pdf(comp, encontros, oficial)
        tipo = "application/pdf"
    else:
        raise Http404
    resp = HttpResponse(dados, content_type=tipo)
    resp["Content-Disposition"] = content_disposition_header(True, f"{nome}.{formato}")
    return resp


# ------------------------------------------------------------------ conflitos


def _lados(c, usuario):
    c.lados = []
    for meu in (c.encontro_a, c.encontro_b):
        c.lados.append({
            "enc": meu,
            "comp": meu.componente,
            "url": f"/componentes/{meu.componente_id}/cronograma/#encontro-{meu.id}",
            "pode_editar": pode_editar(usuario, meu.componente),
            "motivo": motivo_sem_edicao(usuario, meu.componente),
        })
    return c


def conflitos(request):
    g = request.GET
    situacao = g.get("situacao", "ATIVO")
    qs = Conflito.objects.select_related(
        "professor", "encontro_a__componente__coordenador", "encontro_b__componente__coordenador",
        "encontro_a__componente__semestre", "encontro_b__componente__semestre",
    )
    if situacao in ("ATIVO", "RESOLVIDO"):
        qs = qs.filter(status=situacao)
    if g.get("professor", "").isdigit():
        qs = qs.filter(professor_id=g["professor"])
    if g.get("componente", "").isdigit():
        qs = qs.filter(Q(encontro_a__componente_id=g["componente"]) | Q(encontro_b__componente_id=g["componente"]))
    if g.get("coordenador", "").isdigit():
        qs = qs.filter(
            Q(encontro_a__componente__coordenador_id=g["coordenador"]) | Q(encontro_b__componente__coordenador_id=g["coordenador"])
        )
    if g.get("semestre", "").isdigit():
        qs = qs.filter(
            Q(encontro_a__componente__semestre_id=g["semestre"])
            | Q(encontro_b__componente__semestre_id=g["semestre"])
        )
    if g.get("data"):
        try:
            qs = qs.filter(data=date.fromisoformat(g["data"]))
        except ValueError:
            pass
    if g.get("meus") == "1":
        u = request.user
        qs = qs.filter(
            Q(professor=u) | Q(encontro_a__componente__professores=u) | Q(encontro_b__componente__professores=u)
            | Q(encontro_a__componente__coordenador=u) | Q(encontro_b__componente__coordenador=u)
        ).distinct()
    lista = [_lados(c, request.user) for c in qs[:300]]
    return render(request, "core/conflitos.html", {
        "conflitos": lista, "g": g, "situacao": situacao,
        "docentes": Usuario.docentes(),
        "coordenadores": Usuario.objects.filter(perfil=Usuario.Perfil.COORD),
        "componentes": _componentes(),
        "semestres": Semestre.objects.all(),
    })


@require_POST
def conflitos_verificar(request):
    sincronizar_conflitos()
    n = Conflito.objects.filter(status=Conflito.Status.ATIVO).count()
    messages.info(request, f"Verificação concluída em toda a base: {n} conflito(s) ativo(s).")
    proximo = request.POST.get("proximo") or ""
    if not url_has_allowed_host_and_scheme(
        proximo, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        proximo = "conflitos"
    return redirect(proximo)


def conflito_detalhe(request, pk):
    c = get_object_or_404(
        Conflito.objects.select_related(
            "professor", "encontro_a__componente__coordenador", "encontro_b__componente__coordenador",
            "encontro_a__componente__semestre", "encontro_b__componente__semestre",
            "encontro_a__professor", "encontro_b__professor",
        ), pk=pk,
    )
    u = request.user
    pode_comentar = (
        u.eh_admin
        or u.id == c.professor_id
        or tem_vinculo(u, c.encontro_a.componente)
        or tem_vinculo(u, c.encontro_b.componente)
    )
    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "observacao":
            if not pode_comentar:
                raise PermissionDenied
            texto = request.POST.get("texto", "").strip()
            if texto:
                ObservacaoConflito.objects.create(conflito=c, autor=u, texto=texto[:2000])
                messages.success(request, "Solicitação/observação registrada.")
        elif acao == "trocar_professor":
            enc_id = request.POST.get("encontro")
            if enc_id in (str(c.encontro_a_id), str(c.encontro_b_id)):
                try:
                    alterar_encontro(u, int(enc_id), {"professor_id": request.POST.get("professor_id")})
                    messages.success(request, "Alocação atualizada. O conflito foi reavaliado automaticamente.")
                except ErroEdicao as err:
                    messages.error(request, err.mensagem)
        return redirect("conflito_detalhe", pk=pk)
    _lados(c, u)
    historico = HistoricoAlteracao.objects.filter(
        encontro_id__in=[c.encontro_a_id, c.encontro_b_id]
    ).select_related("usuario", "componente")
    if not u.eh_admin:
        historico = historico.exclude(
            ~Q(componente__professores=u) & ~Q(componente__coordenador=u),
            campo="Observações",
        )
    return render(request, "core/conflito_detalhe.html", {
        "c": c, "historico": historico[:50], "docentes": Usuario.docentes(),
        "observacoes": c.observacoes.select_related("autor"),
        "pode_comentar": pode_comentar,
    })


def historico(request):
    qs = HistoricoAlteracao.objects.select_related("usuario", "componente")
    if not request.user.eh_admin:
        qs = qs.exclude(
            ~Q(componente__professores=request.user) & ~Q(componente__coordenador=request.user),
            campo="Observações",
        ).distinct()
    comp_id = request.GET.get("componente", "")
    if comp_id.isdigit():
        qs = qs.filter(componente_id=comp_id)
    pagina = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "core/historico.html", {
        "pagina": pagina, "componentes": _componentes(), "comp_id": comp_id,
    })


# ------------------------------------------------------------ administração


def _senha_temporaria():
    return secrets.token_urlsafe(9)


@apenas_admin
def usuarios(request):
    return render(request, "core/usuarios.html", {"usuarios": Usuario.objects.all()})


@apenas_admin
def usuario_form(request, pk=None):
    alvo = get_object_or_404(Usuario, pk=pk) if pk else None
    form = UsuarioForm(request.POST or None, instance=alvo)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if alvo and alvo.pk == request.user.pk and (not obj.is_active or obj.perfil != Usuario.Perfil.ADMIN):
            form.add_error(None, "Você não pode desativar ou rebaixar o seu próprio usuário administrador.")
        else:
            obj.is_staff = obj.is_superuser = obj.perfil == Usuario.Perfil.ADMIN
            senha = None
            if not alvo:
                senha = _senha_temporaria()
                obj.set_password(senha)
                obj.precisa_trocar_senha = True
            try:
                with transaction.atomic():
                    obj.save()
            except IntegrityError:
                form.validate_unique()
                if not form.errors:
                    raise
            else:
                if not alvo:
                    messages.success(
                        request,
                        f"Usuário criado. Senha temporária de {obj.email}: {senha} — anote e entregue ao usuário; "
                        "ela não será exibida novamente e deverá ser trocada no primeiro acesso.",
                    )
                else:
                    messages.success(request, "Usuário atualizado.")
                return redirect("usuarios")
    return render(request, "core/usuario_form.html", {"form": form, "alvo": alvo})


@apenas_admin
@require_POST
def usuario_redefinir_senha(request, pk):
    alvo = get_object_or_404(Usuario, pk=pk)
    if alvo.pk == request.user.pk:
        messages.error(request, "Para alterar a sua própria senha, utilize a opção “Alterar senha” no menu do usuário.")
        return redirect("usuarios")
    senha = _senha_temporaria()
    alvo.set_password(senha)
    alvo.precisa_trocar_senha = True
    alvo.save()
    messages.success(
        request,
        f"Senha redefinida. Senha temporária de {alvo.email}: {senha} — ela não será exibida novamente "
        "e deverá ser trocada no próximo acesso.",
    )
    return redirect("usuarios")


@sensitive_post_parameters()
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def trocar_senha(request):
    form = TrocaSenhaForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        u = form.save()
        u.precisa_trocar_senha = False
        u.save(update_fields=["precisa_trocar_senha"])
        update_session_auth_hash(request, u)
        messages.success(request, "Senha alterada com sucesso.")
        return redirect("dashboard")
    return render(request, "core/senha.html", {"form": form})


@apenas_admin
def semestres(request):
    lista = Semestre.objects.prefetch_related("datas_bloqueadas", "componentes")
    return render(request, "core/semestres.html", {"semestres": lista})


@apenas_admin
def semestre_form(request, pk=None):
    sem = get_object_or_404(Semestre, pk=pk) if pk else None
    form = SemestreForm(request.POST or None, instance=sem)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, "Semestre salvo.")
        return redirect("semestre_detalhe", pk=obj.pk)
    return render(request, "core/semestre_form.html", {"form": form, "sem": sem})


def _regerar_semestre(sem):
    total = 0
    for comp in sem.componentes.filter(situacao=Componente.Situacao.RASCUNHO):
        gerar_encontros(comp)
        total += 1
    return total


@apenas_admin
def semestre_detalhe(request, pk):
    sem = get_object_or_404(Semestre, pk=pk)
    form = DataBloqueadaForm(semestre=sem)
    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "liberar":
            sem.preenchimento_liberado = True
            sem.liberado_em = timezone.now()
            sem.save()
            messages.success(request, "Preenchimento liberado para professores e coordenadores.")
        elif acao == "suspender":
            sem.preenchimento_liberado = False
            sem.save()
            messages.warning(request, "Preenchimento suspenso. Os cronogramas continuam disponíveis para consulta.")
        elif acao == "bloquear_data":
            form = DataBloqueadaForm(request.POST, semestre=sem)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.semestre = sem
                obj.save()
                n = _regerar_semestre(sem)
                messages.success(request, f"Data bloqueada. Encontros de {n} componente(s) em elaboração foram recalculados (encontros já preenchidos são preservados).")
            else:
                return render(request, "core/semestre_detalhe.html", {"sem": sem, "form": form})
        elif acao == "remover_data":
            data_id = request.POST.get("id", "")
            if str(data_id).isdigit():
                DataBloqueada.objects.filter(semestre=sem, pk=int(data_id)).delete()
                n = _regerar_semestre(sem)
                messages.success(request, f"Data liberada. Encontros de {n} componente(s) em elaboração foram recalculados.")
        return redirect("semestre_detalhe", pk=pk)
    return render(request, "core/semestre_detalhe.html", {"sem": sem, "form": form})


@apenas_admin
def configuracoes(request):
    cfg = Configuracao.obter()
    form = ConfiguracaoForm(request.POST or None, request.FILES or None, instance=cfg)
    if not settings.ENVIO_DE_ARQUIVOS:
        del form.fields["logo"]
    if request.method == "POST":
        if request.POST.get("acao") == "remover_logo":
            cfg.logo.delete(save=True)
            messages.success(request, "Logomarca removida.")
            return redirect("configuracoes")
        if form.is_valid():
            form.save()
            messages.success(request, "Configurações salvas.")
            return redirect("configuracoes")
    return render(request, "core/configuracoes.html", {"form": form, "cfg": cfg, "envio": settings.ENVIO_DE_ARQUIVOS})


@login_not_required
def logo(request):
    caminho = Configuracao.obter().caminho_logo()
    if not caminho:
        raise Http404
    tipo = "image/png" if caminho.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(open(caminho, "rb"), content_type=tipo)
