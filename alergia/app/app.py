"""
Plataforma Interativa: Mecanismos Imunológicos das Alergias (trilíngue: PT / EN / 中文)
Aplicação Flask para apresentar apostila, slides, exercícios interativos e estudo de caso.
Desenvolvido conforme as DCN de Medicina 2025 (Res. CNE/CES nº 3/2025).
Pronto para deploy no PythonAnywhere.

URLs:  /pt/...   /en/...   /zh/...      ( "/" escolhe o idioma pelo navegador )
"""

import json
import os

from flask import (Flask, abort, g, jsonify, redirect, render_template,
                   request, url_for)

from i18n import DEFAULT_LANG, HTML_LANG, LANG_LABEL, LANGS, UI, melhor_idioma

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.json.ensure_ascii = False  # mantém acentos e caracteres chineses legíveis na API

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')


def carregar_dados(arquivo):
    """Carrega um arquivo JSON da pasta data/."""
    caminho = os.path.join(DATA_DIR, arquivo)
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------- idioma ----
@app.url_value_preprocessor
def extrair_idioma(endpoint, values):
    """Tira 'lang' da URL e guarda em g.lang (idioma da página atual)."""
    g.lang = DEFAULT_LANG
    if values and 'lang' in values:
        lang = values.pop('lang')
        if lang not in LANGS:
            abort(404)
        g.lang = lang


@app.url_defaults
def adicionar_idioma(endpoint, values):
    """url_for('apostila') passa a gerar /<idioma-atual>/apostila automaticamente."""
    if 'lang' in values or not app.url_map.is_endpoint_expecting(endpoint, 'lang'):
        return
    values['lang'] = g.get('lang', DEFAULT_LANG)


@app.context_processor
def inject_globais():
    """Disponibiliza variáveis globais para todos os templates."""
    lang = g.get('lang', DEFAULT_LANG)
    ui = UI[lang]
    return {
        'lang': lang,
        'html_lang': HTML_LANG[lang],
        't': ui,
        'titulo_site': ui['titulo_site'],
        'dcn_ref': ui['dcn_ref'],
        'idiomas': [(c, LANG_LABEL[c], HTML_LANG[c]) for c in LANGS],
    }


def pagina(nome, **contexto):
    """Renderiza templates/<idioma>/<nome>.html."""
    return render_template(f'{g.lang}/{nome}.html', **contexto)


# ----------------------------------------------------------------- rotas ----
@app.route('/')
def raiz():
    """Redireciona para o idioma preferido do navegador (padrão: português)."""
    lang = melhor_idioma(request.headers.get('Accept-Language'))
    return redirect(url_for('index', lang=lang))


# Endereços antigos (sem idioma) continuam funcionando -> português
@app.route('/apostila')
@app.route('/slides')
@app.route('/exercicios')
@app.route('/estudo-caso')
@app.route('/sobre')
def legado():
    return redirect('/' + DEFAULT_LANG + request.path, code=301)


@app.route('/<lang>/')
def index():
    """Página inicial com apresentação do curso e navegação."""
    return pagina('index')


@app.route('/<lang>/apostila')
def apostila():
    """Apostila ilustrada: conteúdo teórico completo."""
    return pagina('apostila')


@app.route('/<lang>/slides')
def slides():
    """Apresentação de slides com roteiro de fala."""
    return pagina('slides')


@app.route('/<lang>/exercicios')
def exercicios():
    """Lista de exercícios interativa com verificação de respostas."""
    questoes = carregar_dados(f'exercicios_{g.lang}.json')
    if questoes is None:
        questoes = {'blocos': []}
    return render_template('exercicios.html', dados=questoes)


@app.route('/api/verificar', methods=['POST'])
def verificar_resposta():
    """API para verificar respostas das questões de múltipla escolha."""
    dados = request.get_json(silent=True)
    if not dados or 'questao_id' not in dados or 'resposta' not in dados:
        return jsonify({'erro': 'Dados invalidos'}), 400

    lang = dados.get('lang', DEFAULT_LANG)
    if lang not in LANGS:
        lang = DEFAULT_LANG

    questao_id = dados['questao_id']
    resposta_usuario = str(dados['resposta']).strip().upper()

    questoes = carregar_dados(f'exercicios_{lang}.json')
    if questoes is None:
        return jsonify({'erro': 'Dados das questoes indisponiveis'}), 500

    # Busca a questão em todos os blocos
    questao = None
    for bloco in questoes.get('blocos', []):
        for q in bloco.get('questoes', []):
            if q.get('id') == questao_id:
                questao = q
                break
        if questao:
            break

    if questao is None or questao.get('tipo') != 'multipla_escolha':
        return jsonify({'erro': 'Questao nao encontrada ou nao e de multipla escolha'}), 404

    gabarito = questao.get('gabarito', '').strip().upper()
    correta = (resposta_usuario == gabarito)

    return jsonify({
        'correta': correta,
        'gabarito': gabarito,
        'comentario': questao.get('comentario', ''),
        'explicacao': questao.get('explicacao', ''),
    })


@app.route('/<lang>/estudo-caso')
def estudo_caso():
    """Estudo de caso clínico navegável."""
    return pagina('estudo_caso')


@app.route('/<lang>/sobre')
def sobre():
    """Página sobre o material, fontes e DCN 2025."""
    return pagina('sobre')


if __name__ == '__main__':
    # Configuração para desenvolvimento local
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
