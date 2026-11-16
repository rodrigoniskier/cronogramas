# Arquitetura resumida

CronoMed é um monólito Django (um projeto `config`, um app `core`), com páginas renderizadas no servidor, um editor em JavaScript sem framework e PostgreSQL em produção (SQLite para uso local). Este documento descreve o que foi encontrado na auditoria e como importação, detecção de conflitos e sugestões se encaixam no que já existia.

## 1. Diagnóstico da auditoria

| Aspecto | Situação encontrada |
|---|---|
| Estrutura | App único `core`: `models.py`, `services.py` (regras), `views.py` (páginas e API JSON do editor), `exports.py` (DOCX/PDF), `forms.py`. |
| Autenticação | Usuário próprio (`Usuario`, login por e-mail ou nome de usuário), `LoginRequiredMiddleware` global, três perfis (administrador, coordenador, professor), troca obrigatória de senha após redefinição. |
| Autorização | Instituição única: todos os usuários autenticados **consultam** todos os cronogramas; a **edição** é restrita a docentes vinculados, coordenador responsável e administração, sempre verificada no servidor. |
| Conflitos | Apenas conflito docente, calculado em `services.sincronizar_conflitos` e persistido em `Conflito`. |
| Testes | 22 testes (regras críticas, permissões, autocadastro, exportação). CI roda `check`, verificação de migrações e testes. |
| Implantação | Docker Compose ou Vercel (função serverless, disco somente leitura, limite de tamanho). |
| Lacunas | Sem importação de planilhas; sem conflito de turma ou de calendário; resolução de conflitos totalmente manual. |
| Riscos considerados | Regressão nas telas que assumiam conflito sempre docente; dependências pesadas inviáveis no Vercel; armazenamento de arquivos indisponível no Vercel; diferenças SQLite × PostgreSQL. |

## 2. Módulos

| Módulo | Responsabilidade |
|---|---|
| `core/agenda.py` (novo) | Regras de conflito, puras e determinísticas, sobre registros em memória. Não acessa o banco. |
| `core/services.py` | Permissões, geração de encontros, estados e **persistência** dos conflitos (`sincronizar_conflitos`), agora baseada na agenda. |
| `core/importacao.py` (novo) | Leitura do `.xlsx`, mapeamento de colunas, validação, plano de importação, prévia de conflitos e gravação. |
| `core/sugestoes.py` (novo) | Motor de sugestões: candidatos, restrições rígidas, custo, verificação e plano conjunto. |
| `core/views_importacao.py`, `core/views_sugestoes.py` (novos) | Telas dessas duas funcionalidades. |
| `core/views.py` | Telas existentes; ajustadas para exibir os três tipos de conflito e as sugestões. `alterar_encontro` continua sendo o único ponto de gravação de encontros pelo usuário. |

```
planilha .xlsx ──► importacao.ler_planilha ──► Importacao (conteúdo no banco, privada do usuário)
                                                   │
                        mapeamento de colunas ─────┤
                                                   ▼
                              importacao.analisar ──► erros por linha · plano · conflitos previstos
                                                   │            (usa agenda.py sobre banco + planilha)
                                    confirmar      ▼
                              importacao.aplicar ──► Componente / HorarioSemanal / Encontro (uma transação)
                                                   │
                                                   ▼
                        services.sincronizar_conflitos ──► Conflito (DOCENTE · TURMA · CALENDARIO)
                                                   │
                                                   ▼
        sugestoes.sugerir / sugestoes.planejar ──► ações verificadas ──► views_sugestoes.aplicar_sugestoes
                                                                              │ reverifica tudo
                                                                              ▼
                                                                    views.alterar_encontro (permissões,
                                                                    histórico, versão, novo recálculo)
```

## 3. Modelo de dados (alterações)

- **`Conflito`**: novo campo `tipo` (`DOCENTE`, `TURMA`, `CALENDARIO`), `motivo` e `descricao` (restrições de calendário); `encontro_b` e `professor` tornaram-se opcionais. Registros existentes permanecem válidos como `DOCENTE`. Unicidade garantida por restrições condicionais (migração `0004`).
- **`Importacao`** (migração `0005`): planilha enviada, com cabeçalhos, linhas (texto das células em JSON), mapeamento, situação e resumo. O conteúdo fica no banco porque o Vercel não tem disco gravável.

Nenhum modelo ou campo existente foi removido.

## 4. Regras de conflito

Intervalos semiabertos: 14–16 e 16–18 não se sobrepõem.

| Tipo | Definição | Dado em que se apoia |
|---|---|---|
| `DOCENTE` | Mesmo docente em dois encontros distintos, na mesma data, com horários sobrepostos — em quaisquer componentes e semestres. | ID do usuário (nunca o nome). |
| `TURMA` | Mesma turma em encontros sobrepostos de componentes **diferentes**. | Semestre + curso + período + turma do cadastro do componente. Sem período ou turma, a regra não se aplica. |
| `CALENDARIO` | Encontro em data bloqueada (feriado/bloqueio) ou fora do período letivo do semestre. | `DataBloqueada` e datas do `Semestre`. |

Linhas do mesmo componente no mesmo horário são vários docentes/grupos da mesma aula e não geram conflito de turma. **Conflito de sala não foi implementado**: o local é texto livre, sem cadastro que permita comparação confiável.

O recálculo é incremental: alterar o docente recalcula os conflitos desse docente; alterar data/horário, inserir encontro, mudar o calendário ou o cadastro recalcula também turma e calendário do semestre. “Verificar novamente” recalcula toda a base.

## 5. Motor de sugestões

**Ações**: mover a aula inteira (todas as linhas do mesmo componente, dia e horário) ou trocar o docente de uma linha (só em conflitos docentes).

**Restrições rígidas** — uma ação que viole qualquer uma não é produzida nem aceita:

1. nenhum docente da aula tem outro encontro sobreposto no destino;
2. a turma não tem aula de outro componente, nem o próprio componente tem outro encontro, no destino;
3. a data está no período do componente e do semestre e não é bloqueada;
4. dia útil, ou dia em que o componente já tem aula na grade; nunca domingo;
5. duração preservada, entre 07:00 e 22:30;
6. só cronogramas em elaboração (aprovados/publicados nunca são alterados);
7. o substituto é docente ativo vinculado ao componente e está livre;
8. a ação não cria nenhum conflito novo.

**Preferências flexíveis** (custo, menor é melhor; constantes em `sugestoes.PESOS`): 1 por dia de distância da data original; 10 por mudar o horário; 15 por sair do turno; 5 por dia da semana não habitual; 2 por docente/grupo adicional movido; 6 por troca de docente, mais 2 por encontro que o substituto já tenha no dia.

**Verificação**: cada sugestão é conferida reaplicando a ação em memória e recalculando os conflitos com as mesmas regras de `agenda.py` (o conflito-alvo deve sumir e nenhum outro pode surgir). Ao aplicar, o servidor reconstrói a ação, confere as versões dos encontros, repete todas as verificações sobre dados recém-lidos e grava por `alterar_encontro`. Um plano é aplicado por inteiro ou não é aplicado.

**Plano do semestre**: busca com retrocesso e poda (*branch and bound*). Percorre os conflitos em ordem estável; para cada um, tenta as ações de menor custo sobre o estado já modificado pelas anteriores (uma ação pode resolver vários conflitos; os já resolvidos são pulados). Minimiza primeiro os conflitos sem solução e depois o custo. O resultado é determinístico; um limite de nós (300) garante tempo de resposta e, quando atingido, o plano é informado como “melhor encontrado”, não como ótimo. Conflitos sem alternativa são listados com o motivo.

**OR-Tools CP-SAT foi avaliado e não adotado.** O problema real é pequeno (dezenas de conflitos, poucas centenas de destinos por aula). O pacote acrescentaria dezenas de MB de binários a uma função serverless com limite de 60 MB, além de uma dependência nativa a manter, sem ganho perceptível nesta escala. A busca fica isolada em `sugestoes.planejar`; se o problema crescer (por exemplo, montar a grade inteira do semestre), essa função pode ser substituída por um modelo CP-SAT sem tocar no restante.

## 6. Segurança e isolamento

- Todas as rotas novas exigem login (middleware global) e CSRF.
- **Importação**: só administradores e coordenadores. Cada importação é filtrada por `usuario=request.user` — outro usuário, mesmo administrador, recebe 404. Coordenadores só criam componentes sob sua coordenação e só atualizam os que coordenam; componentes aprovados/publicados não são alterados.
- **Arquivo**: apenas `.xlsx`, até 2 MB, com limite de tamanho descompactado, de linhas, de colunas e de texto; lido em modo somente leitura; nunca gravado em disco. Docentes inexistentes não são criados. Textos da planilha são sempre exibidos com escape.
- **Sugestões**: qualquer usuário consulta; mover aula exige gerenciar o componente, trocar docente exige poder editá-lo — as mesmas regras do editor, impostas por `alterar_encontro`. Dados enviados pelo navegador não são confiados.
- Nenhuma credencial foi adicionada ao repositório; exemplos usam apenas dados fictícios (`*.example`).

## 7. Suposições adotadas

1. “Isolamento entre usuários” foi entendido no modelo existente (instituição única, consulta livre): isolamento de **edição** por vínculo/coordenação e de **importações** por autor. Não foi introduzida multi-instituição.
2. A turma é identificada por semestre + curso + período + turma.
3. A importação é “tudo ou nada”: qualquer erro de validação impede a gravação.
4. Em componentes já existentes, a planilha acrescenta ou preenche encontros, mas não altera o cadastro do componente.
5. Docentes são identificados por e-mail, nome de usuário ou nome completo sem homônimos.
6. Restrições de calendário impedem a aprovação, como os demais conflitos.

## 8. Desempenho medido

Base sintética local (SQLite): 80 componentes, 3.360 encontros, 166 conflitos — recálculo completo em 0,10 s; plano do semestre em 0,8 s (limite de nós atingido, 162 ações, todos os conflitos resolvidos); aplicação das 162 ações em 6,5 s. Não foram feitos testes de carga com usuários simultâneos.
