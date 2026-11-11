"""Textos da interface (menu, rodapé, botões) nos três idiomas.

O conteúdo longo (apostila, slides, estudo de caso etc.) fica em
templates/<idioma>/*.html e os exercícios em data/exercicios_<idioma>.json.
"""

LANGS = ('pt', 'en', 'zh')
DEFAULT_LANG = 'pt'

# Código usado no atributo <html lang="..."> e nos hreflang
HTML_LANG = {'pt': 'pt-BR', 'en': 'en', 'zh': 'zh-CN'}

# Nome do idioma exibido no seletor
LANG_LABEL = {'pt': 'PT', 'en': 'EN', 'zh': '中文'}

UI = {
    'pt': {
        'titulo_site': 'Alergias — Mecanismos Imunológicos',
        'dcn_ref': 'Resolução CNE/CES nº 3/2025',
        'logo_titulo': 'Mecanismos Imunológicos das Alergias',
        'logo_sub': 'Plataforma de Ensino • Graduação em Medicina',
        'menu_inicio': 'Início',
        'menu_apostila': 'Apostila',
        'menu_slides': 'Slides',
        'menu_exercicios': 'Exercícios',
        'menu_caso': 'Estudo de Caso',
        'menu_sobre': 'Sobre',
        'menu_label': 'Menu',
        'idioma_label': 'Idioma',
        'rodape_linha1': 'Plataforma de Ensino — <strong>Mecanismos Imunológicos das Alergias</strong><br>'
                         'Desenvolvido conforme as DCN de Medicina 2025 ({dcn})',
        'rodape_linha2': 'Material de caráter didático. Fontes verificadas: Abbas &amp; Lichtman, Janeway/Murphy, WAO, GINA. '
                         'Não substitui consulta às fontes primárias nem julgamento clínico individualizado.',
        # Exercícios
        'ex_titulo': 'Exercícios',
        'ex_aviso': '<strong>Protocolo de Integridade:</strong> Todas as questões e resoluções baseiam-se em fontes científicas '
                    'verificadas. Citações [n] remetem às referências da apostila. Fontes principais: Abbas &amp; Lichtman [6], '
                    'Murphy &amp; Weaver (Janeway) [7], WAO Anaphylaxis Guidance 2020 [4], GINA [8], DCN de Medicina 2025 [5].',
        'ex_progresso': '📊 Progresso nos exercícios de fixação',
        'ex_contador': '{acertos} acertos / {respondidas} respondidas / {total} total',
        'ex_questoes': 'questões',
        'ex_mostrar_resolucao': 'mostrar resolução passo a passo',
        'ex_mostrar_resposta': 'mostrar resposta comentada',
        'ex_ocultar': 'ocultar resposta',
        'ex_mostrar': 'mostrar resposta',
        'ex_verificar': 'Verificar resposta',
        'ex_selecione': 'Selecione uma alternativa primeiro.',
        'ex_correto': '✓ Correto!',
        'ex_incorreto': '✗ Resposta incorreta. Gabarito: ',
        'ex_referencias': 'Referências',
        'ex_refs': [
            ('4', 'Cardona V, et al. WAO Anaphylaxis Guidance 2020. <em>World Allergy Organ J.</em> 2020;13(10):100607.'),
            ('5', 'Brasil. MEC/CNE. Resolução CNE/CES nº 3/2025 (DCN Medicina). DOU 1º out. 2025.'),
            ('6', 'Abbas AK, Lichtman AH, Pillai S. <em>Imunologia Celular e Molecular.</em> 10ª ed. Elsevier; 2022.'),
            ('7', "Murphy K, Weaver C. <em>Janeway's Immunobiology.</em> 10ª ed. Garland; 2022."),
            ('8', 'GINA. Global Strategy for Asthma Management and Prevention. 2023.'),
            ('10', 'Thermo Fisher Scientific. Mast Cell Overview (conteúdo científico revisado).'),
            ('11', 'Wynn TA. Type 2 cytokines. <em>Nat Rev Drug Discov.</em> 2015;14(11):739–753.'),
            ('12', 'Bousquet J, et al. Care pathways for biological treatment of severe asthma. <em>Allergy.</em>'),
            ('13', 'Dermatite de contato alérgica (tipo IV); corroborado por [6,7].'),
            ('15', 'Sampson HA, et al. Definition and management of anaphylaxis. <em>Ann Emerg Med.</em> 2006;47(4):373–380.'),
        ],
    },
    'en': {
        'titulo_site': 'Allergies — Immunological Mechanisms',
        'dcn_ref': 'CNE/CES Resolution No. 3/2025',
        'logo_titulo': 'Immunological Mechanisms of Allergies',
        'logo_sub': 'Teaching Platform • Undergraduate Medicine',
        'menu_inicio': 'Home',
        'menu_apostila': 'Handout',
        'menu_slides': 'Slides',
        'menu_exercicios': 'Exercises',
        'menu_caso': 'Case Study',
        'menu_sobre': 'About',
        'menu_label': 'Menu',
        'idioma_label': 'Language',
        'rodape_linha1': 'Teaching Platform — <strong>Immunological Mechanisms of Allergies</strong><br>'
                         'Developed in line with the 2025 Brazilian National Curriculum Guidelines (DCN) for Medicine ({dcn})',
        'rodape_linha2': 'Educational material. Verified sources: Abbas &amp; Lichtman, Janeway/Murphy, WAO, GINA. '
                         'It does not replace consultation of the primary sources or individualized clinical judgment.',
        'ex_titulo': 'Exercises',
        'ex_aviso': '<strong>Integrity Protocol:</strong> All questions and solutions are based on verified scientific sources. '
                    'Citations [n] refer to the references in the handout. Main sources: Abbas &amp; Lichtman [6], '
                    'Murphy &amp; Weaver (Janeway) [7], WAO Anaphylaxis Guidance 2020 [4], GINA [8], Brazilian Medicine DCN 2025 [5].',
        'ex_progresso': '📊 Progress in the practice exercises',
        'ex_contador': '{acertos} correct / {respondidas} answered / {total} total',
        'ex_questoes': 'questions',
        'ex_mostrar_resolucao': 'show step-by-step solution',
        'ex_mostrar_resposta': 'show annotated answer',
        'ex_ocultar': 'hide answer',
        'ex_mostrar': 'show answer',
        'ex_verificar': 'Check answer',
        'ex_selecione': 'Please select an option first.',
        'ex_correto': '✓ Correct!',
        'ex_incorreto': '✗ Incorrect answer. Correct option: ',
        'ex_referencias': 'References',
        'ex_refs': [
            ('4', 'Cardona V, et al. WAO Anaphylaxis Guidance 2020. <em>World Allergy Organ J.</em> 2020;13(10):100607.'),
            ('5', 'Brazil. MEC/CNE. CNE/CES Resolution No. 3/2025 (Medicine DCN). DOU, 1 Oct 2025.'),
            ('6', 'Abbas AK, Lichtman AH, Pillai S. <em>Cellular and Molecular Immunology.</em> 10th ed. Elsevier; 2022.'),
            ('7', "Murphy K, Weaver C. <em>Janeway's Immunobiology.</em> 10th ed. Garland; 2022."),
            ('8', 'GINA. Global Strategy for Asthma Management and Prevention. 2023.'),
            ('10', 'Thermo Fisher Scientific. Mast Cell Overview (reviewed scientific content).'),
            ('11', 'Wynn TA. Type 2 cytokines. <em>Nat Rev Drug Discov.</em> 2015;14(11):739–753.'),
            ('12', 'Bousquet J, et al. Care pathways for biological treatment of severe asthma. <em>Allergy.</em>'),
            ('13', 'Allergic contact dermatitis (type IV); corroborated by [6,7].'),
            ('15', 'Sampson HA, et al. Definition and management of anaphylaxis. <em>Ann Emerg Med.</em> 2006;47(4):373–380.'),
        ],
    },
    'zh': {
        'titulo_site': '过敏——免疫学机制',
        'dcn_ref': '巴西CNE/CES第3/2025号决议',
        'logo_titulo': '过敏的免疫学机制',
        'logo_sub': '教学平台 • 医学本科教育',
        'menu_inicio': '首页',
        'menu_apostila': '讲义',
        'menu_slides': '幻灯片',
        'menu_exercicios': '练习题',
        'menu_caso': '病例研究',
        'menu_sobre': '关于',
        'menu_label': '菜单',
        'idioma_label': '语言',
        'rodape_linha1': '教学平台——<strong>过敏的免疫学机制</strong><br>'
                         '依据巴西2025年医学国家课程指南（DCN）编写（{dcn}）',
        'rodape_linha2': '本材料用于教学目的。已核实来源：Abbas &amp; Lichtman、Janeway/Murphy、WAO、GINA。'
                         '不能替代对原始文献的查阅，也不能替代个体化的临床判断。',
        'ex_titulo': '练习题',
        'ex_aviso': '<strong>诚信协议：</strong>所有题目与解析均基于经核实的科学来源。方括号引用 [n] 对应讲义中的参考文献。'
                    '主要来源：Abbas &amp; Lichtman [6]、Murphy &amp; Weaver（Janeway）[7]、WAO 2020年过敏反应指南 [4]、'
                    'GINA [8]、巴西2025年医学DCN [5]。',
        'ex_progresso': '📊 巩固练习进度',
        'ex_contador': '答对 {acertos} 题 / 已作答 {respondidas} 题 / 共 {total} 题',
        'ex_questoes': '道题',
        'ex_mostrar_resolucao': '显示分步解析',
        'ex_mostrar_resposta': '显示详细解答',
        'ex_ocultar': '隐藏答案',
        'ex_mostrar': '显示答案',
        'ex_verificar': '检查答案',
        'ex_selecione': '请先选择一个选项。',
        'ex_correto': '✓ 回答正确！',
        'ex_incorreto': '✗ 回答错误。正确答案：',
        'ex_referencias': '参考文献',
        'ex_refs': [
            ('4', 'Cardona V, et al. WAO Anaphylaxis Guidance 2020. <em>World Allergy Organ J.</em> 2020;13(10):100607.'),
            ('5', '巴西教育部/国家教育委员会（MEC/CNE）。CNE/CES第3/2025号决议（医学DCN）。《联邦政府公报》（DOU），2025年10月1日。'),
            ('6', 'Abbas AK, Lichtman AH, Pillai S. <em>Cellular and Molecular Immunology</em>（《细胞与分子免疫学》）. 第10版. Elsevier; 2022.'),
            ('7', "Murphy K, Weaver C. <em>Janeway's Immunobiology.</em> 第10版. Garland; 2022."),
            ('8', 'GINA. Global Strategy for Asthma Management and Prevention. 2023.'),
            ('10', 'Thermo Fisher Scientific. Mast Cell Overview（经审核的科学内容）。'),
            ('11', 'Wynn TA. Type 2 cytokines. <em>Nat Rev Drug Discov.</em> 2015;14(11):739–753.'),
            ('12', 'Bousquet J, et al. Care pathways for biological treatment of severe asthma. <em>Allergy.</em>'),
            ('13', '变应性接触性皮炎（IV型）；与 [6,7] 相互印证。'),
            ('15', 'Sampson HA, et al. Definition and management of anaphylaxis. <em>Ann Emerg Med.</em> 2006;47(4):373–380.'),
        ],
    },
}


def melhor_idioma(accept_language_header):
    """Escolhe o idioma a partir do cabeçalho Accept-Language do navegador."""
    if not accept_language_header:
        return DEFAULT_LANG
    for parte in accept_language_header.split(','):
        codigo = parte.split(';')[0].strip().lower()
        if codigo.startswith('pt'):
            return 'pt'
        if codigo.startswith('en'):
            return 'en'
        if codigo.startswith('zh'):
            return 'zh'
    return DEFAULT_LANG
