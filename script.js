// Aguarda o carregamento do DOM antes de executar o script
document.addEventListener("DOMContentLoaded", () => {
    
    // Pega os elementos do HTML
    const botaoGerar = document.getElementById("gerarBtn");
    const statusEl = document.getElementById("status");
    const inputs = {
        componente: document.getElementById("componente"),
        turma: document.getElementById("turma"),
        diaSemana: document.getElementById("diaSemana"),
        horario: document.getElementById("horario"),
    };

    /**
     * DADOS FIXOS DO CALENDÁRIO 2026.1
     * (Exatamente como antes)
     */
    const CALENDARIO_2026_1 = {
        inicioAulas: new Date("2026-02-05T00:00:00-03:00"), 
        fimSemestre: new Date("2026-07-01T23:59:59-03:00"), 
        feriados: [
            "2026-02-16", "2026-02-17", "2026-02-18", "2026-04-02", "2026-04-03",
            "2026-04-21", "2026-05-01", "2026-05-08", "2026-06-04", "2026-06-24",
        ],
        provaIntegrada: "2026-06-13",
        reposicao: "2026-06-15",
        avaliacaoFinal: "2026-06-22",
    };

    const PROVAS_2026_1 = {
        P3: { "1a_avaliacao": "2026-04-27" },
        P4: { "1a_avaliacao": "2026-04-01" }
    };

    /**
     * MODELO DE CONTEÚDO - MAPD 1
     * (Exatamente como antes)
     */
    const TEMPLATE_MAPD1 = {
        info: {
            componente: "Mecanismos de Agressão, Patológicos e Defesa 1.",
            ch: "60h/A", teorica: "30h/A", pratica: "30h/A",
            periodo: "3º", coordenador: "Rodrigo Niskier Ferreira Barbosa."
        },
        conteudo: [
            { data: null, dataFixaKey: null, conteudo: "Apresentação do componente, Lesões e Adaptações", ch: "3h/T", atividades: "Aula expositiva; metodologia ativa; uso de TICs.", recursos: "Vídeos, Power Point, Imagens, Software", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Morte Celular: Necrose e Apoptose", ch: "3h/T", atividades: "Aula expositiva; metodologia ativa; uso de TICs.", recursos: "Vídeos, Power Point, Imagens, Software", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula teórico-prática: Discussão de casos clínicos", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Imunidade inata", ch: "3h/T", atividades: "Aula expositiva; metodologia ativa; uso de TICs.", recursos: "Vídeos, Power Point, Imagens, Software", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Resposta de Células T", ch: "3h/T", atividades: "Aula expositiva; metodologia ativa; uso de TICs.", recursos: "Vídeos, Power Point, Imagens, Software", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Resposta de Células B", ch: "3h/T", atividades: "Aula expositiva; metodologia ativa; uso de TICs.", recursos: "Vídeos, Power Point, Imagens, Software", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: "1a_avaliacao", conteudo: "Realização da 1ª avaliação de aprendizagem", ch: "3h/T", atividades: "Prova teórica", recursos: "Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "LABORATÓRIO DE INFORMÁTICA" },
            { data: null, dataFixaKey: null, conteudo: "Aula teórico-prática: Análise de imagens Patológicas", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Padrões de Inflamações agudas e crônicas", ch: "3h/T", atividades: "Aula expositiva; metodologia ativa; uso de TICs.", recursos: "Vídeos, Power Point, Imagens, Software", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula teórico-prática: Análise de imagens imunopatológicas", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula teórico prática: Introdução à microbiologia (Baseado na plataforma Jaleko)", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula teórico-prática: discussão de casos clínicos de infecções (bactérias)", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula teórico-prática: generalidades sobre infecções (fungos e vírus)", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Discussão de Casos Clínicos", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula teórico-prática: Projeto de Controle de infecções em serviços de saúde", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula teórico-prática: Resistência aos antibióticos", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula teórico-prática: discussão de caso clínico", ch: "3h/P", atividades: "Uso de Plataformas Digitais", recursos: "Dispositivos digitais", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: "provaIntegrada", conteudo: "Avaliação integrada", ch: "3h/T", atividades: "", recursos: "", grupos: "", docente: "", local: "" },
            { data: null, dataFixaKey: "reposicao", conteudo: "Reposição das avaliações de aprendizagem", ch: "3h/T", atividades: "Prova teórica", recursos: "Prova, Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" },
            { data: null, dataFixaKey: "avaliacaoFinal", conteudo: "Avaliação final", ch: "3h/T", atividades: "Prova teórica", recursos: "Prova, Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" }
        ]
    };

    /**
     * MODELO DE CONTEÚDO - MAPD 2
     * (Exatamente como antes)
     */
    const TEMPLATE_MAPD2 = {
        info: {
            componente: "Mecanismos de Agressão, Patológicos e Defesa 2.",
            ch: "60h/A", teorica: "30h/A", pratica: "30h/A",
            periodo: "4º", coordenador: "Rodrigo Niskier Ferreira Barbosa."
        },
        conteudo: [
            { data: null, dataFixaKey: null, conteudo: "Apresentação do Componente; Resgate de conteúdos (Foco: Mecanismos Básicos de Agressão, Patológicos e de Defesa)", ch: "3h/T", atividades: "Apresentação do modelo e plataformas IA; Definição de metas iniciais; Início da interação com IA para explorar \"Lesões e Adaptações\", \"Morte Celular\" e \"Imunidade\" via casos e simulações.", recursos: "Plataforma Black Board (IA); Material Institucional.", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de Aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula Teórico-Prática: Casos Clínicos - Foco em Bactérias de Interesse Clínico", ch: "3h/P", atividades: "Discussão de casos complexos envolvendo bactérias comuns; Análise de raciocínio diagnóstico inicial e resposta imune inata; Mentoria sobre uso da IA para pesquisa de patógenos.", recursos: "Plataforma Black Board (Dados de Interação IA, Casos); Artigos/Guidelines (via IA).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: null, conteudo: "Aula Teórica- Prática: Habilidades Laboratoriais de Microbiologia (Coloração de Gram, Semeadura - Princípios)", ch: "3h/P", atividades: "Prática orientada em laboratório físico focada na aplicação clínica da coloração de Gram e semeadura; Atividade baseada em IA para estudo guiado.", recursos: "Laboratório de Microbiologia; Microscópios; Corantes; Placas; Plataforma Black Board (Guias virtuais).", grupos: "Grupos:1 e 2 (prática), Grupos 3 e 4 Atividade via BB", docente: "Rodrigo Niskier", local: "Laboratório de Microbiologia (Bloco G)" },
            { data: null, dataFixaKey: null, conteudo: "Aula Teórica- Prática: Habilidades Laboratoriais de Microbiologia (Coloração de Gram, Semeadura - Princípios)", ch: "3h/P", atividades: "Prática orientada em laboratório físico focada na aplicação clínica da coloração de Gram e semeadura; Atividade baseada em IA para estudo guiado.", recursos: "Laboratório de Microbiologia; Microscópios; Corantes; Placas; Plataforma Black Board (Guias virtuais).", grupos: "Grupos:3 e 4 (prática), Grupos 1 e 2 Atividade via BB", docente: "Rodrigo Niskier", local: "Laboratório de Microbiologia (Bloco G)" },
            { data: null, dataFixaKey: "1a_avaliacao", conteudo: "1ª AVALIAÇÃO DE APRENDIZAGEM (AV1)/ Discussão Pós-AV1", ch: "3h/T", atividades: "Prova teórica/Feedback coletivo da AV1", recursos: "Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: null, conteudo: "Aula Teórico- Prática: Princípio e Interpretação de Antibiograma e Testes de Sensibilidade - Plataforma Jaleko", ch: "3h/P", atividades: "Prática de interpretação de antibiogramas simulados; Discussão dos mecanismos de resistência; Uso da IA para acessar guidelines de tratamento e analisar padrões de resistência.", recursos: "Plataforma Black Board (Simulação de antibiogramas, acesso a guidelines); (Via plataforma Jaleko).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: null, conteudo: "Aula Teórico-Prática: Casos Clínicos - Foco em Vírus e Fungos de Interesse Clínico", ch: "3h/P", atividades: "Discussão de casos envolvendo infecções virais e fúngicas; Análise da ativação e função de Células B e T na resposta a esses patógenos; Mentoria sobre como a IA simula respostas imunes.", recursos: "Plataforma Black Board (Casos, Simulações IA); Material de revisão (via IA).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: null, conteudo: "Parasitas de Interesse Clínico - Plataforma Jaleko", ch: "3h/T", atividades: "Discussão de casos clínicos de parasitoses comuns; Análise dos ciclos de vida e mecanismos de evasão imune dos parasitas.", recursos: "Plataforma Black Board (Casos); Material sobre Parasitologia (via Plataforma Jaleko).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de Aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula Teórico-Prática: Microscopia de Parasitas e Interpretação de Achados", ch: "3h/P", atividades: "Prática de identificação microscópica de parasitas em lâminas reais ou virtuais; Discussão da relevância clínica dos achados; Uso da IA para reconhecimento de imagens e guias.", recursos: "Laboratório de Parasitologia/Informática; Microscópios; Lâminas/Imagens; Plataforma Black Board (Reconhecimento de imagem IA).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório / Sala de Microscopia (Bloco G)" },
            { data: null, dataFixaKey: null, conteudo: "Aula Teórico-Prática: Casos - Foco em Hipersensibilidade e Imunodeficiências (Imunopatologia)", ch: "3h/P", atividades: "Discussão de casos de reações alérgicas, doenças autoimunes iniciais e imunodeficiências primárias/secundárias; Análise dos mecanismos imunopatológicos envolvidos.", recursos: "Plataforma Black Board (Casos, Simulações IA); Material sobre Imunopatologia (via IA).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: null, conteudo: "Autoimunidade - Plataforma Jaleko", ch: "3h/T", atividades: "Discussão de casos de doenças autoimunes complexas", recursos: "Plataforma Black Board (Casos); Artigos/Revisões (via Plataforma Jaleko).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de Aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula Teórico-Prática: Imunologia de Transplantes", ch: "3h/P", atividades: "Discussão de desafios imunológicos em transplantes de órgãos/tecidos.", recursos: "Plataforma Black Board (Casos); Artigos/Revisões (via IA).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: null, conteudo: "Biologia do Câncer - Plataforma Jaleko", ch: "3h/T", atividades: "Alunos apresentam a resolução de um Mega-Desafio inicial sobre oncogenese; Feedback focado no raciocínio e uso da IA na pesquisa.", recursos: "Apresentações dos alunos; Plataforma Black Board (Via Plataforma Jaleko).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de Aula" },
            { data: null, dataFixaKey: null, conteudo: "Imunidade Antitumoral", ch: "3h/T", atividades: "Alunos apresentam a resolução de um Mega-Desafio inicial sobre interação tumor-imunidade; Feedback focado no raciocínio e uso da IA na pesquisa.", recursos: "Apresentações dos alunos; Plataforma Black Board (Análise de processo IA).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de Aula" },
            { data: null, dataFixaKey: null, conteudo: "Aula Teórico-Prática: Casos - Foco em Imunoterapia e Novas Abordagens em Câncer", ch: "3h/P", atividades: "Discussão de casos que aplicam imunoterapia ou terapias alvo em oncologia; Análise dos mecanismos de ação e efeitos adversos.", recursos: "Plataforma Black Board (Casos, Simulações IA de tratamento); Artigos/Revisões (via IA).", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: null, conteudo: "Oficina Prática (Simulação/Discussão): Estudo de Casos Clínicos (Teórico-Prática - Integração)", ch: "3h/P", atividades: "Resolução guiada de casos clínicos complexos (utilizando IA); Foco na integração de todos os temas em um único paciente.", recursos: "Plataforma Black Board (Casos simulados, Ferramentas IA); Material de referência.", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: "provaIntegrada", conteudo: "PROVA INTEGRADA (comum para todas as turmas)", ch: "3h/T", atividades: "", recursos: "", grupos: "", docente: "", local: "" },
            { data: null, dataFixaKey: "reposicao", conteudo: "REPOSIÇÕES", ch: "3h/T", atividades: "Prova teórica", recursos: "Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: "avaliacaoFinal", conteudo: "AVALIAÇÃO FINAL", ch: "3h/T", atividades: "Prova teórica", recursos: "Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" },
            { data: null, dataFixaKey: null, conteudo: "FEEDBACK FINAL E ENCERRAMENTO", ch: "3h/T", atividades: "Revisão de avaliações e inclusão de notas no sistema acadêmico", recursos: "Plataforma BlackBoard", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de Aula" }
        ]
    };

    /**
     * NOVA FUNÇÃO: Converte um arquivo (como o logo) para Base64.
     * Isto permite-nos incorporar a imagem no HTML.
     */
    function converterParaBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
    }

    /**
     * FUNÇÃO PRINCIPAL (MODIFICADA)
     */
    async function lidarComGeracao() {
        botaoGerar.disabled = true;
        statusEl.textContent = "Gerando cronograma...";

        try {
            // 1. Coletar dados (igual a antes)
            const selecao = {
                componente: inputs.componente.value,
                turma: inputs.turma.value,
                diaSemana: parseInt(inputs.diaSemana.value, 10),
                horario: inputs.horario.value,
                diaSemanaTexto: inputs.diaSemana.options[inputs.diaSemana.selectedIndex].text
            };

            // 2. Escolher modelo (igual a antes)
            const template = (selecao.componente === 'mapd1') ? TEMPLATE_MAPD1 : TEMPLATE_MAPD2;
            const provas = (selecao.componente === 'mapd1') ? PROVAS_2026_1.P3 : PROVAS_2026_1.P4;

            // 3. Calcular datas (igual a antes)
            const eventosCalculados = calcularDatasEventos(
                template.conteudo,
                selecao.diaSemana,
                CALENDARIO_2026_1,
                provas
            );
            
            // 4. (NOVO) Carregar o logo e converter para Base64
            // Isto garante que a imagem funciona na nova aba.
            const logoBase64 = await fetch('./logo.jpg')
                .then(res => res.blob())
                .then(converterParaBase64)
                .catch(err => {
                    console.error("Erro ao carregar o logo.jpg.", err);
                    throw new Error("Falha ao carregar logo.jpg. Verifique se o arquivo está na pasta.");
                });

            // 5. Preparar dados completos (igual a antes)
            const dadosDocumento = {
                ...selecao,
                info: template.info,
                eventos: eventosCalculados,
                logo: logoBase64 // Agora contém a string Base64
            };
            
            // 6. (NOVO) Gerar a string HTML
            const htmlString = gerarHtmlDoCronograma(dadosDocumento);

            // 7. (NOVO) Abrir a nova aba e escrever o HTML
            const novaAba = window.open();
            novaAba.document.write(htmlString);
            novaAba.document.close(); // Finaliza a escrita

            statusEl.textContent = "Visualização gerada com sucesso!";

        } catch (error) {
            console.error(error);
            statusEl.textContent = `Erro: ${error.message}`;
        } finally {
            botaoGerar.disabled = false;
        }
    }

    /**
     * LÓGICA DE DATAS (Exatamente como antes)
     */
    function calcularDatasEventos(conteudoTemplate, diaSemanaEscolhido, calendario, provas) {
        let eventos = JSON.parse(JSON.stringify(conteudoTemplate));
        const datasFixas = {
            "1a_avaliacao": provas["1a_avaliacao"],
            "provaIntegrada": calendario.provaIntegrada,
            "reposicao": calendario.reposicao,
            "avaliacaoFinal": calendario.avaliacaoFinal
        };

        let dataAtual = new Date(calendario.inicioAulas);
        while (dataAtual.getDay() !== diaSemanaEscolhido) {
            dataAtual.setDate(dataAtual.getDate() + 1);
        }

        for (const evento of eventos) {
            if (evento.dataFixaKey && datasFixas[evento.dataFixaKey]) {
                const dataFixaStr = datasFixas[evento.dataFixaKey];
                evento.data = new Date(`${dataFixaStr}T00:00:00-03:00`);
                if (dataAtual < evento.data) {
                    dataAtual.setTime(evento.data.getTime());
                    dataAtual.setDate(dataAtual.getDate() + 7);
                }
            } else {
                let dataValida = false;
                while (!dataValida) {
                    const dataAtualStr = dataAtual.toISOString().split('T')[0];
                    if (calendario.feriados.includes(dataAtualStr)) {
                        dataAtual.setDate(dataAtual.getDate() + 7);
                    } else {
                        dataValida = true;
                    }
                }
                evento.data = new Date(dataAtual);
                dataAtual.setDate(dataAtual.getDate() + 7);
            }
        }
        return eventos;
    }

    /**
     * Formata "DD/MM" (Exatamente como antes)
     */
    function formatarData(data) {
        if (!data) return "";
        const dia = String(data.getDate()).padStart(2, '0');
        const mes = String(data.getMonth() + 1).padStart(2, '0');
        return `${dia}/${mes}`;
    }

    /**
     * NOVA FUNÇÃO: Gera a string HTML completa para a nova aba.
     */
    function gerarHtmlDoCronograma(dados) {
        // Gera as linhas da tabela principal
        const linhasTabela = dados.eventos.map(evento => `
            <tr>
                <td>${formatarData(evento.data)}</td>
                <td></td> <td>${dados.horario}</td>
                <td>${evento.conteudo || ''}</td>
                <td>${evento.ch || ''}</td>
                <td>${evento.atividades || ''}</td>
                <td>${evento.recursos || ''}</td>
                <td>${evento.grupos || ''}</td>
                <td>${evento.docente || ''}</td>
                <td>${evento.local || ''}</td>
            </tr>
        `).join(''); // .join('') junta todas as strings das linhas

        // Retorna o HTML completo da página
        return `
            <!DOCTYPE html>
            <html lang="pt-br">
            <head>
                <meta charset="UTF-B">
                <title>Cronograma ${dados.info.componente} - ${dados.turma}</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; }
                    h2 { text-align: center; }
                    table { width: 100%; border-collapse: collapse; margin-top: 15px; }
                    th, td { border: 1px solid #ccc; padding: 6px; font-size: 10pt; text-align: left; vertical-align: top; }
                    th { background-color: #f4f4f4; }
                    
                    /* Estilos da tabela de cabeçalho (para ficar igual ao modelo) */
                    .table-header { margin-bottom: 20px; }
                    .table-header td { border: 1px solid #999; vertical-align: top; padding: 5px; }
                    .table-header tr td:first-child { width: 50%; }
                    
                    /* Estilos para Impressão */
                    @media print {
                        body { margin: 0.5cm; }
                        /* Esconde o botão de imprimir ao imprimir */
                        .no-print { display: none; }
                        /* Tenta quebrar a página de forma inteligente (evita quebrar linhas da tabela) */
                        tr { page-break-inside: avoid; }
                    }
                    
                    /* Estilo do botão de imprimir */
                    .print-button {
                        padding: 10px 15px; font-size: 16px; background-color: #007bff;
                        color: white; border: none; border-radius: 5px; cursor: pointer;
                        margin-bottom: 20px;
                    }
                </style>
            </head>
            <body>
                <button class="print-button no-print" onclick="window.print()">
                    Imprimir para PDF
                </button>

                <img src="${dados.logo}" alt="Logo UNIPÊ" style="width: 200px; height: auto;">
                <p>Coordenação de Medicina</p>

                <table class="table-header">
                    <tr>
                        <td>1. CURSO: Medicina</td>
                        <td>CRONOGRAMA DE AULAS</td>
                    </tr>
                    <tr>
                        <td>2. COMPONENTE CURRICULAR: ${dados.info.componente}</td>
                        <td>
                            CH: ${dados.info.ch}<br>
                            Teórica: ${dados.info.teorica}<br>
                            Prática: ${dados.info.pratica}
                        </td>
                    </tr>
                    <tr>
                        <td>3. SEMESTRE: 2026/1</td>
                        <td>
                            PERÍODO: ${dados.info.periodo}<br>
                            TURMA: ${dados.turma}
                        </td>
                    </tr>
                    <tr>
                        <td>4. COORDENADOR: ${dados.info.coordenador}</td>
                        <td></td>
                    </tr>
                </table>

                <h2>CRONOGRAMA</h2>

                <table>
                    <thead>
                        <tr>
                            <th>DATA</th>
                            <th>(${dados.diaSemanaTexto})</th>
                            <th>HORÁRIO</th>
                            <th>CONTEÚDO</th>
                            <th>CH</th>
                            <th>ATIVIDADES</th>
                            <th>RECURSOS</th>
                            <th>GRUPOS</th>
                            <th>DOCENTES</th>
                            <th>LOCAL</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${linhasTabela}
                    </tbody>
                </table>
            </body>
            </html>
        `;
    }

    // Adiciona o 'listener' ao botão
    botaoGerar.addEventListener("click", lidarComGeracao);
});
