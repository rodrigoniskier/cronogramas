"""Configurações do CronoMed UNIPÊ.

Toda configuração sensível vem de variáveis de ambiente (ver .env.example).
"""
import os
from pathlib import Path

import dj_database_url
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(nome, padrao=False):
    return os.environ.get(nome, str(padrao)).strip().lower() in ("1", "true", "sim", "yes", "on")


def _env_lista(nome, padrao=""):
    return [v.strip() for v in os.environ.get(nome, padrao).split(",") if v.strip()]


DEBUG = _env_bool("DJANGO_DEBUG", False)

NO_VERCEL = bool(os.environ.get("VERCEL"))

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if NO_VERCEL:
        raise RuntimeError("Defina a variável de ambiente DJANGO_SECRET_KEY no projeto do Vercel.")
    # Execução local: gera uma chave aleatória persistida fora do versionamento.
    # Em produção, defina DJANGO_SECRET_KEY.
    _arquivo_chave = BASE_DIR / ".secret_key"
    if not _arquivo_chave.exists():
        _arquivo_chave.write_text(get_random_secret_key())
        _arquivo_chave.chmod(0o600)
    SECRET_KEY = _arquivo_chave.read_text().strip()

ALLOWED_HOSTS = _env_lista("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = _env_lista("DJANGO_CSRF_TRUSTED_ORIGINS")
if NO_VERCEL:
    ALLOWED_HOSTS += [".vercel.app"]
    CSRF_TRUSTED_ORIGINS += ["https://*.vercel.app"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "core.middleware.TrocaSenhaObrigatoriaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.globais",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Banco: PostgreSQL via DATABASE_URL; SQLite como padrão para execução local.
_banco_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if NO_VERCEL and not _banco_url:
    raise RuntimeError("Conecte um banco PostgreSQL ao projeto do Vercel (variável DATABASE_URL).")
DATABASES = {
    "default": dj_database_url.parse(
        _banco_url or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=0 if NO_VERCEL else 600,   # funções serverless não mantêm conexões
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.Usuario"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Recife"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path("/tmp/staticfiles") if NO_VERCEL else BASE_DIR / "staticfiles"
try:
    STATIC_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
WHITENOISE_USE_FINDERS = True  # dispensa collectstatic na execução local
WHITENOISE_AUTOREFRESH = DEBUG

MEDIA_ROOT = Path(os.environ.get("CRONOMED_MEDIA_ROOT", BASE_DIR / "media"))

# Logomarca institucional: arquivo enviado em Configurações tem prioridade;
# na ausência, usa-se branding/logo.png, se existir.
LOGO_PADRAO = BASE_DIR / "branding" / "logo.png"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 10
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
if _env_bool("DJANGO_HTTPS", False) or NO_VERCEL:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = _env_bool("DJANGO_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", 31536000))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("DJANGO_HSTS_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = _env_bool("DJANGO_HSTS_PRELOAD", True)
if _env_bool("DJANGO_HTTPS", False) or _env_bool("DJANGO_TRUST_PROXY", False) or NO_VERCEL:
    # Atrás de proxy reverso que termina o TLS e envia X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Limites contra tentativas automatizadas em endpoints públicos (login e autocadastro).
CRONOMED_LIMITE_LOGIN_TENTATIVAS = int(os.environ.get("CRONOMED_LIMITE_LOGIN_TENTATIVAS", 10))
CRONOMED_LIMITE_LOGIN_JANELA = int(os.environ.get("CRONOMED_LIMITE_LOGIN_JANELA", 300))
CRONOMED_LIMITE_CADASTRO_TENTATIVAS = int(os.environ.get("CRONOMED_LIMITE_CADASTRO_TENTATIVAS", 30))
CRONOMED_LIMITE_CADASTRO_JANELA = int(os.environ.get("CRONOMED_LIMITE_CADASTRO_JANELA", 600))

# Restrições do autocadastro de professores (domínio institucional e código de convite).
CRONOMED_DOMINIOS_CADASTRO = tuple(
    d.strip().lower().lstrip("@")
    for d in os.environ.get("CRONOMED_DOMINIOS_CADASTRO", "unipe.edu.br").split(",")
    if d.strip()
)
CRONOMED_CODIGO_CONVITE = os.environ.get("CRONOMED_CODIGO_CONVITE", "primeiro-ano")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simples": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simples"},
    },
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

# No Vercel o sistema de arquivos é somente leitura: a logomarca vem de
# branding/logo.png (versionada) e o envio pela tela fica desativado.
ENVIO_DE_ARQUIVOS = not NO_VERCEL
