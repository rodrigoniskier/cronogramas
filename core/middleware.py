from django.shortcuts import redirect
from django.urls import reverse


class TrocaSenhaObrigatoriaMiddleware:
    """Após redefinição administrativa, exige que o usuário escolha nova senha."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = request.user
        if u.is_authenticated and u.precisa_trocar_senha:
            livres = {reverse("trocar_senha"), reverse("logout"), reverse("logo")}
            if request.path not in livres and not request.path.startswith("/static/"):
                return redirect("trocar_senha")
        return self.get_response(request)
