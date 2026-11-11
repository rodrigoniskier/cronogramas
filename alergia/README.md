# Alergias — Mecanismos Imunológicos (PT · EN · 中文)

Plataforma web em **Flask** com apostila ilustrada, slides com roteiro de fala, exercícios interativos
e estudo de caso clínico (Graduação em Medicina, DCN 2025). Layout e conteúdo originais, agora
**trilíngues**: português, inglês e chinês simplificado.

> Esta pasta (`alergia/`) vive dentro do repositório `cronogramas`, ao lado do CronoMed (Django),
> sem interferir nele.

## Como o site funciona nos 3 idiomas

| Endereço | Idioma |
|---|---|
| `/` | Escolhe sozinho pelo idioma do navegador (padrão: português) |
| `/pt/…` | Português |
| `/en/…` | English |
| `/zh/…` | 中文 |

Páginas: `/<idioma>/`, `/<idioma>/apostila`, `/<idioma>/slides`, `/<idioma>/exercicios`,
`/<idioma>/estudo-caso`, `/<idioma>/sobre`. Os botões **PT / EN / 中文** no topo trocam de idioma
mantendo a mesma página. Os endereços antigos (`/apostila` etc.) redirecionam para o português.

### Onde ficam os textos

```
alergia/
├── deploy_pythonanywhere.sh        ← script de instalação (passo 4 do guia)
├── app/
│   ├── app.py  wsgi.py  requirements.txt
│   ├── i18n.py                     ← textos do menu, rodapé e botões (3 idiomas)
│   ├── templates/
│   │   ├── base.html  exercicios.html      ← compartilhados
│   │   ├── pt/  en/  zh/                   ← index, apostila, slides, estudo_caso, sobre
│   ├── data/exercicios_pt.json  exercicios_en.json  exercicios_zh.json
│   └── static/ (css, js)
└── material/                       ← HTMLs originais (somente português), mantidos como arquivo
```

Para **corrigir um texto**, edite o arquivo do idioma correspondente. Para **adicionar um idioma**,
inclua o código em `LANGS`, `HTML_LANG`, `LANG_LABEL` e `UI` (em `i18n.py`), crie `templates/<código>/`
e `data/exercicios_<código>.json`.

## Rodar no seu computador (opcional)

```bash
cd alergia/app
pip install -r requirements.txt
python app.py        # abra http://localhost:5000
```

---

# 🚀 Guia passo a passo: publicar no PythonAnywhere (para leigos)

Você vai usar apenas o navegador. Tempo estimado: 15 minutos. O plano **gratuito** ("Beginner") basta.

### Passo 1 — Criar a conta
1. Acesse <https://www.pythonanywhere.com> e clique em **Pricing & signup → Create a Beginner account**.
2. Escolha um **nome de usuário** (ele vira o endereço do site: `SEUUSUARIO.pythonanywhere.com`),
   e-mail e senha. Confirme o e-mail.

### Passo 2 — Baixar o código (Bash console)
1. No painel, clique na aba **Consoles** e depois em **Bash** (em "Start a new console").
   Abrirá uma tela preta de texto — é o "console".
2. Copie o comando abaixo, **cole** no console (clique com o botão direito → Colar) e aperte **Enter**:

```bash
git clone -b claude/blissful-brown-8ush8u https://github.com/rodrigoniskier/cronogramas.git
```

   - Quando esta versão for incorporada à branch principal (`main`), o comando passa a ser apenas
     `git clone https://github.com/rodrigoniskier/cronogramas.git`.
   - Se o repositório for **privado**, o GitHub pedirá usuário e senha: use seu usuário e, como senha,
     um *Personal Access Token* (GitHub → Settings → Developer settings → Tokens, com permissão `repo`).
3. Você verá "Receiving objects … done". Pronto: o código está em `~/cronogramas`.

### Passo 3 — (nada a fazer) conferir os arquivos
```bash
ls ~/cronogramas/alergia
```
Deve listar: `README.md`, `app`, `deploy_pythonanywhere.sh`, `material`.

### Passo 4 — Rodar o script que prepara tudo
Ainda no console, cole e aperte Enter:

```bash
bash ~/cronogramas/alergia/deploy_pythonanywhere.sh
```

Ele cria o ambiente virtual, instala o Flask, **testa as 18 páginas** (6 páginas × 3 idiomas) e, no
final, imprime um quadro **"PRONTO!"** com os valores exatos (já com o seu usuário) para os próximos passos.
Deixe essa janela aberta para copiar de lá.

### Passo 5 — Criar o aplicativo web
1. Clique na aba **Web** (menu superior) → **Add a new web app** → **Next**.
2. Escolha **Manual configuration** (⚠ *não* escolha "Flask") → **Next**.
3. Escolha a versão do **Python** que o script informou (ex.: *Python 3.10*) → **Next**.

### Passo 6 — Configurar 3 campos na página Web
Role a página até estas seções e preencha com os valores do quadro "PRONTO!"
(troque `SEUUSUARIO` pelo seu usuário, se estiver copiando daqui):

| Campo | Valor |
|---|---|
| **Source code** | `/home/SEUUSUARIO/cronogramas/alergia/app` |
| **Working directory** | `/home/SEUUSUARIO/cronogramas/alergia/app` |
| **Virtualenv** | `/home/SEUUSUARIO/.virtualenvs/alergia-venv` |

Ao digitar o Virtualenv e confirmar (✔), o PythonAnywhere aceita se o caminho existir.

### Passo 7 — Colar o arquivo WSGI
1. Na seção **Code**, clique no link **WSGI configuration file** (algo como
   `/var/www/seuusuario_pythonanywhere_com_wsgi.py`).
2. **Apague todo o texto** que está lá e cole este (trocando `SEUUSUARIO`; o script já mostra pronto):

```python
import sys

path = '/home/SEUUSUARIO/cronogramas/alergia/app'
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application  # noqa
```
3. Clique em **Save** (canto superior direito).

### Passo 8 — (Opcional) Arquivos estáticos
Na seção **Static files**, clique em *Enter URL* e preencha:
URL `/static/` — Directory `/home/SEUUSUARIO/cronogramas/alergia/app/static`. (Deixa o site mais rápido;
funciona sem isso também.)

### Passo 9 — Ligar o site
Volte ao topo da aba **Web** e clique no botão verde **Reload SEUUSUARIO.pythonanywhere.com**.
Abra `https://SEUUSUARIO.pythonanywhere.com` — o site escolherá o idioma do seu navegador, e você poderá
trocar em **PT / EN / 中文**.

## 🔄 Como atualizar depois
No Bash console:
```bash
cd ~/cronogramas && git pull
bash ~/cronogramas/alergia/deploy_pythonanywhere.sh
```
Depois, na aba **Web**, clique em **Reload**.

## 🛠 Se algo der errado
| Sintoma | O que fazer |
|---|---|
| Página "Something went wrong" | Aba **Web** → seção *Log files* → abra o **Error log** e olhe as últimas linhas. |
| `ModuleNotFoundError: flask` | O campo **Virtualenv** (Passo 6) está vazio ou errado. |
| `ModuleNotFoundError: app` | **Source code** ou o `path` do WSGI (Passo 7) está errado — confira o usuário. |
| Versão de Python diferente | O Python do web app (Passo 5) deve ser igual ao informado pelo script. Se mudar, apague `~/.virtualenvs/alergia-venv` e rode o script de novo com `PYTHON=python3.10 bash …deploy_pythonanywhere.sh`. |
| Mudei algo e nada mudou | Clique em **Reload** na aba Web. |
| Plano gratuito | O site fica ativo, mas é preciso clicar em "Run until 3 months from today" na aba Web a cada ~3 meses. |

*Material de caráter didático. Não substitui a consulta às fontes primárias nem o julgamento clínico individualizado.*
