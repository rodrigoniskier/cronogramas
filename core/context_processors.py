from .models import Configuracao
from .services import conflitos_do_usuario


def globais(request):
    cfg = Configuracao.obter()
    ctx = {"instituicao": cfg.instituicao, "tem_logo": cfg.caminho_logo() is not None}
    if request.user.is_authenticated:
        ctx["n_minhas_pendencias"] = conflitos_do_usuario(request.user).count()
    return ctx
