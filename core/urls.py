from django.contrib.auth import views as auth
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path("entrar/", auth.LoginView.as_view(authentication_form=LoginForm, redirect_authenticated_user=True), name="login"),
    path("sair/", auth.LogoutView.as_view(), name="logout"),
    path("senha/", views.trocar_senha, name="trocar_senha"),
    path("logo/", views.logo, name="logo"),
    path("", views.dashboard, name="dashboard"),
    path("componentes/", views.componentes_lista, name="componentes"),
    path("componentes/novo/", views.componente_form, name="componente_novo"),
    path("componentes/<int:pk>/editar/", views.componente_form, name="componente_editar"),
    path("componentes/<int:pk>/excluir/", views.componente_excluir, name="componente_excluir"),
    path("componentes/<int:pk>/cronograma/", views.cronograma, name="cronograma"),
    path("componentes/<int:pk>/validar/", views.componente_validar, name="componente_validar"),
    path("componentes/<int:pk>/exportar/<str:formato>/", views.exportar, name="exportar"),
    path("componentes/<int:pk>/<str:acao>/", views.componente_transicao, name="componente_transicao"),
    path("api/componentes/<int:pk>/estado/", views.api_estado, name="api_estado"),
    path("api/componentes/<int:pk>/encontros/", views.api_encontro_criar, name="api_encontro_criar"),
    path("api/encontros/<int:pk>/", views.api_encontro_salvar, name="api_encontro_salvar"),
    path("api/encontros/<int:pk>/excluir/", views.api_encontro_excluir, name="api_encontro_excluir"),
    path("api/encontros/<int:pk>/historico/", views.api_encontro_historico, name="api_encontro_historico"),
    path("conflitos/", views.conflitos, name="conflitos"),
    path("conflitos/verificar/", views.conflitos_verificar, name="conflitos_verificar"),
    path("conflitos/<int:pk>/", views.conflito_detalhe, name="conflito_detalhe"),
    path("historico/", views.historico, name="historico"),
    path("usuarios/", views.usuarios, name="usuarios"),
    path("usuarios/novo/", views.usuario_form, name="usuario_novo"),
    path("usuarios/<int:pk>/", views.usuario_form, name="usuario_editar"),
    path("usuarios/<int:pk>/redefinir-senha/", views.usuario_redefinir_senha, name="usuario_redefinir_senha"),
    path("semestres/", views.semestres, name="semestres"),
    path("semestres/novo/", views.semestre_form, name="semestre_novo"),
    path("semestres/<int:pk>/", views.semestre_detalhe, name="semestre_detalhe"),
    path("semestres/<int:pk>/editar/", views.semestre_form, name="semestre_editar"),
    path("configuracoes/", views.configuracoes, name="configuracoes"),
]
