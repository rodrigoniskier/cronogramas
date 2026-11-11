#!/bin/bash
# ============================================================
# Preparação automática para o PythonAnywhere
# Plataforma "Mecanismos Imunológicos das Alergias" (PT / EN / 中文)
#
# Uso (no Bash console do PythonAnywhere, depois de clonar o repositório):
#     bash ~/cronogramas/alergia/deploy_pythonanywhere.sh
#
# O script:
#   1) cria o "ambiente virtual" (uma caixinha isolada de programas);
#   2) instala o Flask dentro dele;
#   3) testa se o site abre nos 3 idiomas;
#   4) mostra, já preenchidos com o SEU usuário, os textos que você deve
#      colar na aba Web do PythonAnywhere.
# É seguro rodar de novo quantas vezes quiser (por exemplo, após atualizar).
# ============================================================
set -e

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # .../cronogramas/alergia
APP_DIR="$AQUI/app"
VENV="$HOME/.virtualenvs/alergia-venv"
USUARIO="$(whoami)"

if [ ! -f "$APP_DIR/app.py" ]; then
    echo "[ERRO] Não encontrei $APP_DIR/app.py"
    echo "       Confira se você clonou o repositório (passo 2 do guia)."
    exit 1
fi

# Escolhe o Python (3.10 é o padrão do guia; usa outro se não existir)
if [ -z "$PYTHON" ]; then
    for candidato in python3.10 python3.11 python3.12 python3.9 python3; do
        if command -v "$candidato" >/dev/null 2>&1; then PYTHON="$candidato"; break; fi
    done
fi
VERSAO="$($PYTHON -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

echo "========================================"
echo "  Preparando o site (Python $VERSAO)"
echo "========================================"

echo "[1/3] Criando o ambiente virtual em $VENV ..."
mkdir -p "$HOME/.virtualenvs"
if [ ! -x "$VENV/bin/python" ]; then
    "$PYTHON" -m venv "$VENV"
fi

echo "[2/3] Instalando o Flask ..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "[3/3] Testando o site nos 3 idiomas ..."
(
  cd "$APP_DIR"
  "$VENV/bin/python" - <<'PY'
from app import app
c = app.test_client()
for lang in ('pt', 'en', 'zh'):
    for pagina in ('', 'apostila', 'slides', 'exercicios', 'estudo-caso', 'sobre'):
        r = c.get('/%s/%s' % (lang, pagina))
        assert r.status_code == 200, (lang, pagina, r.status_code)
print('      OK: 18 páginas (6 páginas x 3 idiomas) funcionando.')
PY
)

ARQ="$HOME/alergia_wsgi_para_colar.txt"
cat > "$ARQ" <<TXT
import sys

path = '$APP_DIR'
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application  # noqa
TXT

cat <<MSG

========================================
  PRONTO! Agora, na aba "Web" do PythonAnywhere:
========================================

 1) Add a new web app  ->  Next  ->  "Manual configuration"
    ->  escolha Python $VERSAO  ->  Next

 2) Na seção "Code", preencha:
      Source code:   $APP_DIR
      Working directory:  $APP_DIR

 3) Na seção "Virtualenv", digite:
      $VENV

 4) Clique no link "WSGI configuration file", APAGUE tudo o que
    estiver lá e cole o texto abaixo (também salvo em $ARQ):

----------------------------------------
$(cat "$ARQ")
----------------------------------------

 5) (Opcional, deixa mais rápido) Em "Static files" adicione:
      URL:        /static/
      Directory:  $APP_DIR/static

 6) Clique no botão verde "Reload" e abra:
      https://$USUARIO.pythonanywhere.com

MSG
