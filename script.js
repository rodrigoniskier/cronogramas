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
     * Extraídos dos arquivos PDF e CSV fornecidos.
     */
    const CALENDARIO_2026_1 = {
        // INÍCIO DAS AULAS 2026.1 
        inicioAulas: new Date("2026-02-05T00:00:00-03:00"), 
        // Encerramento semestre 2026.1 
        fimSemestre: new Date("2026-07-01T23:59:59-03:00"), 
        
        // Feriados e eventos que param as aulas 
        feriados: [
            "2026-02-16", // Carnaval 
            "2026-02-17", // Carnaval 
            "2026-02-18", // Carnaval 
            "2026-04-02", // Feriado Semana Santa 
            "2026-04-03", // Feriado Semana Santa 
            "2026-04-21", // Feriado Tiradentes 
            "2026-05-01", // Feriado Dia do Trabalhador 
            "2026-05-08", // III MED INOVA 
            "2026-06-04", // Feriado de Corpus Christi 
            "2026-06-24", // Feriado de São João 
        ],

        // Datas de provas fixas do calendário geral 
        provaIntegrada: "2026-06-13", // 
        reposicao: "2026-06-15", //  (Usaremos a primeira data do período)
        avaliacaoFinal: "2026-06-22", //  (Usaremos a primeira data do período)
    };

    // Datas específicas das provas P3 e P4 
    const PROVAS_2026_1 = {
        P3: {
            "1a_avaliacao": "2026-04-27" // MAPD P3 [cite: 14]
        },
        P4: {
            "1a_avaliacao": "2026-04-01" // MAPD P4 [cite: 15]
        }
    };

    /**
     * MODELO DE CONTEÚDO - MAPD 1 (Período 3)
     * Extraído do arquivo: CRONOGRAMA MAPD-1 TURMA ÚNICA 2025-2.docx 
     * 'dataFixaKey' mapeia este evento para uma data específica.
     */
    const TEMPLATE_MAPD1 = {
        info: {
            componente: "Mecanismos de Agressão, Patológicos e Defesa 1.", // [cite: 2]
            ch: "60h/A", // [cite: 2]
            teorica: "30h/A", // [cite: 2]
            pratica: "30h/A", // [cite: 2]
            periodo: "3º", // [cite: 2]
            coordenador: "Rodrigo Niskier Ferreira Barbosa." // [cite: 2]
        },
        conteudo: [
            // 
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
            { data: null, dataFixaKey: "provaIntegrada", conteudo: "Avaliação integrada", ch: "3h/T", atividades: "", recursos: "", grupos: "", docente: "", local: "" }, // 
            { data: null, dataFixaKey: "reposicao", conteudo: "Reposição das avaliações de aprendizagem", ch: "3h/T", atividades: "Prova teórica", recursos: "Prova, Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" }, // 
            { data: null, dataFixaKey: "avaliacaoFinal", conteudo: "Avaliação final", ch: "3h/T", atividades: "Prova teórica", recursos: "Prova, Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de aula" } // 
        ]
    };

    /**
     * MODELO DE CONTEÚDO - MAPD 2 (Período 4)
     * Extraído do arquivo: CRONOGRAMA MAPD-2 TURMA A 2025-2.docx 
     */
    const TEMPLATE_MAPD2 = {
        info: {
            componente: "Mecanismos de Agressão, Patológicos e Defesa 2.", // [cite: 6]
            ch: "60h/A", // [cite: 6]
            teorica: "30h/A", // [cite: 6]
            pratica: "30h/A", // [cite: 6]
            periodo: "4º", // [cite: 6]
            coordenador: "Rodrigo Niskier Ferreira Barbosa." // [cite: 6]
        },
        conteudo: [
            // 
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
            { data: null, dataFixaKey: "provaIntegrada", conteudo: "PROVA INTEGRADA (comum para todas as turmas)", ch: "3h/T", atividades: "", recursos: "", grupos: "", docente: "", local: "" }, // 
            { data: null, dataFixaKey: "reposicao", conteudo: "REPOSIÇÕES", ch: "3h/T", atividades: "Prova teórica", recursos: "Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" }, // 
            // O Feriado de 08/12  não existe em 2026.1, então o ignoramos.
            { data: null, dataFixaKey: "avaliacaoFinal", conteudo: "AVALIAÇÃO FINAL", ch: "3h/T", atividades: "Prova teórica", recursos: "Espelho de prova", grupos: "Todos", docente: "Rodrigo Niskier", local: "Laboratório de Informática" }, // 
            { data: null, dataFixaKey: null, conteudo: "FEEDBACK FINAL E ENCERRAMENTO", ch: "3h/T", atividades: "Revisão de avaliações e inclusão de notas no sistema acadêmico", recursos: "Plataforma BlackBoard", grupos: "Todos", docente: "Rodrigo Niskier", local: "Sala de Aula" } // 
        ]
    };

    // Objeto 'window.docx' é fornecido pela biblioteca 'docx' carregada no HTML
    const { Document, Packer, Paragraph, Table, TableRow, TableCell, WidthType, ImageRun, HeadingLevel, TextRun, AlignmentType } = window.docx;

    /**
     * Função principal que é chamada quando o botão é clicado.
     */
    async function lidarComGeracao() {
        botaoGerar.disabled = true;
        statusEl.textContent = "Gerando cronograma... (isso pode levar alguns segundos)";

        try {
            // 1. Coletar dados do formulário
            const selecao = {
                componente: inputs.componente.value,
                turma: inputs.turma.value,
                diaSemana: parseInt(inputs.diaSemana.value, 10), // 1 = Seg, 2 = Ter, ..., 5 = Sex
                horario: inputs.horario.value,
                diaSemanaTexto: inputs.diaSemana.options[inputs.diaSemana.selectedIndex].text
            };

            // 2. Escolher o modelo e as datas de prova corretos
            const template = (selecao.componente === 'mapd1') ? TEMPLATE_MAPD1 : TEMPLATE_MAPD2;
            const provas = (selecao.componente === 'mapd1') ? PROVAS_2026_1.P3 : PROVAS_2026_1.P4;

            // 3. Calcular todas as datas dos eventos
            const eventosCalculados = calcularDatasEventos(
                template.conteudo,
                selecao.diaSemana,
                CALENDARIO_2026_1,
                provas
            );
            
            // 4. Buscar o logo
            const logoBuffer = await fetch('./logo.jpg')
                .then(res => res.arrayBuffer())
                .catch(err => {
                    console.error("Erro ao carregar o logo.jpg. Certifique-se que o arquivo existe e que está a usar um servidor local.");
                    throw new Error("Falha ao carregar logo.jpg");
                });

            // 5. Preparar dados completos para o gerador DOCX
            const dadosDocumento = {
                ...selecao,
                info: template.info,
                eventos: eventosCalculados,
                logo: logoBuffer
            };
            
            // 6. Criar o documento
            const doc = criarDocumento(dadosDocumento);

            // 7. Gerar e salvar o arquivo
            const blob = await Packer.toBlob(doc);
            saveAs(blob, `cronograma_${selecao.componente}_${selecao.turma}_2026-1.docx`);
            statusEl.textContent = "Cronograma gerado com sucesso!";

        } catch (error) {
            console.error(error);
            statusEl.textContent = `Erro: ${error.message}`;
        } finally {
            botaoGerar.disabled = false;
        }
    }

    /**
     * Calcula as datas para cada evento do cronograma.
     * @param {Array} conteudoTemplate - A lista de objetos de conteúdo.
     * @param {number} diaSemanaEscolhido - O dia da semana (1-5).
     * @param {object} calendario - O objeto CALENDARIO_2026_1.
     * @param {object} provas - O objeto de provas (P3 ou P4).
     * @returns {Array} A lista de eventos com as datas calculadas.
     */
    function calcularDatasEventos(conteudoTemplate, diaSemanaEscolhido, calendario, provas) {
        // Faz uma cópia para não alterar o original
        let eventos = JSON.parse(JSON.stringify(conteudoTemplate));
        
        // Mapeia todas as datas fixas
        const datasFixas = {
            "1a_avaliacao": provas["1a_avaliacao"],
            "provaIntegrada": calendario.provaIntegrada,
            "reposicao": calendario.reposicao,
            "avaliacaoFinal": calendario.avaliacaoFinal
        };

        let dataAtual = new Date(calendario.inicioAulas);

        // 1. Acha a primeira data de aula
        // Avança a data até ser o dia da semana escolhido
        while (dataAtual.getDay() !== diaSemanaEscolhido) {
            dataAtual.setDate(dataAtual.getDate() + 1);
        }

        // 2. Itera sobre cada evento do template e atribui uma data
        for (const evento of eventos) {
            // Verifica se este evento tem uma data fixa (ex: Prova)
            if (evento.dataFixaKey && datasFixas[evento.dataFixaKey]) {
                const dataFixaStr = datasFixas[evento.dataFixaKey];
                evento.data = new Date(`${dataFixaStr}T00:00:00-03:00`); // Define a data fixa
                
                // Se for uma prova que substitui uma aula semanal,
                // avançamos a 'dataAtual' para a semana seguinte
                // para que a próxima aula não caia na mesma data da prova.
                if (dataAtual < evento.data) {
                    dataAtual.setTime(evento.data.getTime());
                    dataAtual.setDate(dataAtual.getDate() + 7);
                }
            
            } else {
                // Evento normal (aula semanal)
                
                // 3. Verifica se a data atual é um feriado
                let dataValida = false;
                while (!dataValida) {
                    // Formata para 'YYYY-MM-DD'
                    const dataAtualStr = dataAtual.toISOString().split('T')[0];
                    
                    if (calendario.feriados.includes(dataAtualStr)) {
                        // É feriado, pula para a próxima semana
                        dataAtual.setDate(dataAtual.getDate() + 7);
                    } else {
                        // Não é feriado, data é válida
                        dataValida = true;
                    }
                }
                
                // 4. Atribui a data válida ao evento
                evento.data = new Date(dataAtual);
                
                // 5. Avança para a próxima semana
                dataAtual.setDate(dataAtual.getDate() + 7);
            }
        }
        
        return eventos;
    }

    /**
     * Formata um objeto Date para "DD/MM"
     */
    function formatarData(data) {
        if (!data) return "";
        const dia = String(data.getDate()).padStart(2, '0');
        const mes = String(data.getMonth() + 1).padStart(2, '0'); // Meses são 0-indexados
        return `${dia}/${mes}`;
    }

    /**
     * Cria o objeto do documento DOCX.
     * @param {object} dados - Todos os dados compilados.
     * @returns {Document} O objeto Document da biblioteca docx.
     */
    function criarDocumento(dados) {
        const doc = new Document({
            sections: [{
                properties: {
                    // Configura margens (opcional, mas bom para layout)
                    // Unidade: 1/1440 de uma polegada (twips)
                    margin: { top: 720, right: 720, bottom: 720, left: 720 },
                },
                children: [
                    // --- Logótipo ---
                    new Paragraph({
                        children: [
                            new ImageRun({
                                data: dados.logo,
                                transformation: {
                                    width: 200,
                                    height: 57, // Proporção aproximada do logo
                                },
                            }),
                        ],
                    }),
                    new Paragraph({ text: "Coordenação de Medicina", style: "Heading2" }), // 
                    
                    // --- Tabela de Cabeçalho (Info do Curso) ---
                    // 
                    new Table({
                        width: { size: 100, type: WidthType.PERCENTAGE },
                        rows: [
                            new TableRow({
                                children: [
                                    new TableCell({ children: [new Paragraph("1. CURSO: Medicina")] }),
                                    new TableCell({ children: [new Paragraph("CRONOGRAMA DE AULAS")] }),
                                ],
                            }),
                            new TableRow({
                                children: [
                                    new TableCell({ children: [new Paragraph(`2. COMPONENTE CURRICULAR: ${dados.info.componente}`)] }),
                                    new TableCell({ children: [
                                        new Paragraph(`CH: ${dados.info.ch}`),
                                        new Paragraph(`Teórica: ${dados.info.teorica}`),
                                        new Paragraph(`Prática: ${dados.info.pratica}`),
                                    ]}),
                                ],
                            }),
                            new TableRow({
                                children: [
                                    new TableCell({ children: [new Paragraph("3. SEMESTRE: 2026/1")] }),
                                    new TableCell({ children: [
                                        new Paragraph(`PERÍODO: ${dados.info.periodo}`),
                                        new Paragraph(`TURMA: ${dados.turma}`),
                                    ]}),
                                ],
                            }),
                            new TableRow({
                                children: [
                                    new TableCell({ children: [new Paragraph(`4. COORDENADOR: ${dados.info.coordenador}`)] }),
                                    new TableCell({ children: [new Paragraph("")] }), // Célula vazia
                                ],
                            }),
                        ],
                    }),
                    
                    new Paragraph({ text: "CRONOGRAMA", style: "Heading1", alignment: AlignmentType.CENTER }), // [cite: 3, 7]

                    // --- Tabela Principal do Cronograma ---
                    // [cite: 4, 8]
                    new Table({
                        width: { size: 100, type: WidthType.PERCENTAGE },
                        rows: [
                            // Cabeçalho da Tabela
                            new TableRow({
                                tableHeader: true,
                                children: [
                                    new TableCell({ children: [new Paragraph("DATA")] }),
                                    new TableCell({ children: [new Paragraph(`(${dados.diaSemanaTexto})`)] }),
                                    new TableCell({ children: [new Paragraph("HORÁRIO")] }),
                                    new TableCell({ children: [new Paragraph("CONTEÚDO")] }),
                                    new TableCell({ children: [new Paragraph("CH")] }),
                                    new TableCell({ children: [new Paragraph("ATIVIDADES")] }),
                                    new TableCell({ children: [new Paragraph("RECURSOS")] }),
                                    new TableCell({ children: [new Paragraph("GRUPOS")] }),
                                    new TableCell({ children: [new Paragraph("DOCENTES")] }),
                                    new TableCell({ children: [new Paragraph("LOCAL")] }),
                                ],
                            }),
                            
                            // Linhas de Conteúdo (geradas dinamicamente)
                            ...dados.eventos.map(evento => {
                                return new TableRow({
                                    children: [
                                        new TableCell({ children: [new Paragraph(formatarData(evento.data))] }),
                                        new TableCell({ children: [new Paragraph("")] }), // Coluna do dia da semana (vazia)
                                        new TableCell({ children: [new Paragraph(dados.horario)] }),
                                        new TableCell({ children: [new Paragraph(evento.conteudo)] }),
                                        new TableCell({ children: [new Paragraph(evento.ch)] }),
                                        new TableCell({ children: [new Paragraph(evento.atividades)] }),
                                        new TableCell({ children: [new Paragraph(evento.recursos)] }),
                                        new TableCell({ children: [new Paragraph(evento.grupos)] }),
                                        new TableCell({ children: [new Paragraph(evento.docente)] }),
                                        new TableCell({ children: [new Paragraph(evento.local)] }),
                                    ],
                                });
                            })
                        ],
                    }),
                ],
            }],
            // Define estilos básicos (opcional, mas melhora a aparência)
            styles: {
                default: {
                    heading1: { run: { size: 32, bold: true }, paragraph: { spacing: { before: 240, after: 120 } } },
                    heading2: { run: { size: 28, bold: true }, paragraph: { spacing: { before: 200, after: 100 } } },
                },
            },
        });

        return doc;
    }

    // Adiciona o 'listener' ao botão
    botaoGerar.addEventListener("click", lidarComGeracao);
});
