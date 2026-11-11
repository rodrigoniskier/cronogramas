/* ============================================
   JavaScript - Plataforma Alergias
   Interatividade dos exercicios e navegacao
   ============================================ */

// ===== MENU MOBILE =====
document.addEventListener('DOMContentLoaded', function() {
    const menuToggle = document.querySelector('.menu-toggle');
    const navbarMenu = document.querySelector('.navbar-menu');

    if (menuToggle) {
        menuToggle.addEventListener('click', function() {
            navbarMenu.classList.toggle('aberto');
        });
    }
});


// ===== EXERCICIOS INTERATIVOS =====
// Textos e endereco da API vem do servidor (window.I18N), no idioma da pagina.
const T = window.I18N || {};

// Selecionar alternativa (multipla escolha)
function selecionarAlternativa(elemento, questaoId) {
    const exercicio = elemento.closest('.exercicio');
    const alternativas = exercicio.querySelectorAll('.alternativas li');

    // Desmarca todas
    alternativas.forEach(a => {
        a.classList.remove('selecionada');
    });

    // Marca a clicada
    elemento.classList.add('selecionada');

    // Habilita o botao de verificar
    const btnVerificar = exercicio.querySelector('.btn-verificar');
    if (btnVerificar) {
        btnVerificar.disabled = false;
        btnVerificar.classList.add('ativo');
    }
}

// Verificar resposta (multipla escolha) via API
function verificarResposta(questaoId) {
    const exercicio = document.querySelector(`[data-questao-id="${questaoId}"]`);
    if (!exercicio) return;

    const selecionada = exercicio.querySelector('.alternativas li.selecionada');
    if (!selecionada) {
        alert(T.selecione || 'Selecione uma alternativa primeiro.');
        return;
    }

    const resposta = selecionada.getAttribute('data-letra');

    // Desabilita para evitar nova selecao
    const alternativas = exercicio.querySelectorAll('.alternativas li');
    alternativas.forEach(a => a.style.pointerEvents = 'none');

    fetch(T.verificarUrl || '/api/verificar', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            questao_id: questaoId,
            resposta: resposta,
            lang: T.lang
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.erro) {
            console.error('Erro:', data.erro);
            return;
        }

        // Marca a correta
        alternativas.forEach(a => {
            const letra = a.getAttribute('data-letra');
            if (letra === data.gabarito) {
                a.classList.add('correta');
            } else if (a.classList.contains('selecionada') && !data.correta) {
                a.classList.add('incorreta');
            }
        });

        // Mostra feedback
        const feedback = exercicio.querySelector('.feedback');
        if (feedback) {
            feedback.classList.add('visivel');
            if (data.correta) {
                feedback.classList.add('correta');
                feedback.classList.remove('incorreta');
                feedback.querySelector('.resultado-icon').textContent = T.correto;
                exercicio.classList.add('resolvida-correta');
            } else {
                feedback.classList.add('incorreta');
                feedback.classList.remove('correta');
                feedback.querySelector('.resultado-icon').textContent =
                    T.incorreto + data.gabarito;
                exercicio.classList.add('resolvida-incorreta');
            }

            const comentarioEl = feedback.querySelector('.comentario');
            if (comentarioEl) {
                comentarioEl.innerHTML = data.comentario || data.explicacao || '';
            }
        }

        // Atualiza placar
        atualizarPlacar();

        // Esconde botao verificar
        const btnVerificar = exercicio.querySelector('.btn-verificar');
        if (btnVerificar) {
            btnVerificar.style.display = 'none';
        }
    })
    .catch(error => {
        console.error('Erro na requisicao:', error);
    });
}

// Atualizar placar de progresso
function atualizarPlacar() {
    const totalMultipla = document.querySelectorAll('.exercicio[data-tipo="multipla_escolha"]').length;
    const corretas = document.querySelectorAll('.exercicio.resolvida-correta').length;
    const respondidas = document.querySelectorAll(
        '.exercicio.resolvida-correta, .exercicio.resolvida-incorreta'
    ).length;

    const contadorEl = document.querySelector('.placar .contador');
    const barraFill = document.querySelector('.placar .barra-progresso-fill');

    if (contadorEl) {
        contadorEl.textContent = (T.contador || '{acertos} / {respondidas} / {total}')
            .replace('{acertos}', corretas)
            .replace('{respondidas}', respondidas)
            .replace('{total}', totalMultipla);
    }

    if (barraFill && totalMultipla > 0) {
        const percent = (respondidas / totalMultipla) * 100;
        barraFill.style.width = percent + '%';
    }
}

// Mostrar/ocultar resposta (questoes discursivas e resolvidas)
function toggleResposta(botao) {
    const exercicio = botao.closest('.exercicio');
    const respostaOculta = exercicio.querySelector('.resposta-oculta');

    if (respostaOculta) {
        respostaOculta.classList.toggle('visivel');
        if (respostaOculta.classList.contains('visivel')) {
            botao.textContent = T.ocultar;
        } else {
            botao.textContent = botao.getAttribute('data-rotulo') || T.mostrar;
        }
    }
}


// ===== ABAS DO ESTUDO DE CASO =====
function trocarAba(elemento, abaId) {
    // Desmarca todas as abas
    const abas = document.querySelectorAll('.aba');
    abas.forEach(a => a.classList.remove('ativa'));

    // Esconde todos os conteudos
    const conteudos = document.querySelectorAll('.aba-conteudo');
    conteudos.forEach(c => c.classList.remove('ativa'));

    // Marca a aba clicada
    elemento.classList.add('ativa');

    // Mostra o conteudo correspondente
    const conteudo = document.getElementById(abaId);
    if (conteudo) {
        conteudo.classList.add('ativa');
    }
}


// ===== SCROLL SUAVE PARA LINKS INTERNOS =====
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        const href = this.getAttribute('href');
        if (href === '#') return;
        const target = document.querySelector(href);
        if (target) {
            e.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
});
