# Exemplos de entrada e saída

Todos os dados são **fictícios**: nomes marcados como fictícios e e-mails no domínio reservado `demo.cronomed.example`. Os arquivos referenciam os usuários e o semestre criados por `python manage.py seed_demo` e são gerados por `python manage.py gerar_exemplos` (os DOCX e PDF, pelas rotinas de exportação do próprio sistema).

As saídas abaixo foram obtidas executando o sistema sobre a base de demonstração recém-criada, importando como `coord2`.

## Entrada

Planilha: `.xlsx`, uma linha por encontro, na primeira aba. Linhas de título acima do cabeçalho são ignoradas. Documento (`.docx`) e PDF: modelo institucional “CRONOGRAMA DE AULAS” (ver “Cruzamento”, abaixo).

| Componente curricular | Código | Período | Turma | Turno | Data | Horário | Conteúdo | Tipo | Atividades | Recursos | Grupos | Docente (e-mail) | CH | Local |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Farmacologia Básica (DEMO) | DEMO-05 | 4º | A | Manhã | 04/02/2027 | 08h-10h | Introdução à farmacologia | T | Aula expositiva dialogada | Datashow e quadro | TODOS | prof8@demo.cronomed.example | | Sala 302 — Bloco D |

- `cronograma_exemplo.xlsx` — 15 linhas válidas (duas turmas), com três conflitos intencionais.
- `cronograma_exemplo_com_erros.xlsx` — 8 linhas com os erros de preenchimento mais comuns.

Também são aceitos: colunas separadas de início e término; horários como `13:00`, `13h30` ou `13:00 às 15:30`; datas como `15/02/2027` ou data do Excel; docente por e-mail, nome de usuário ou nome completo sem homônimos. Títulos de coluna diferentes podem ser associados manualmente na conferência.

## Saída 1 — validação de `cronograma_exemplo_com_erros.xlsx`

Nada é importado (a importação é “tudo ou nada”).

| Linha | Campo | Problema |
|---|---|---|
| 5 | Data | Linha repetida: mesmo componente, data, horário, docente e grupo da linha 4. |
| 6 | Componente curricular | Campo obrigatório vazio. |
| 7 | Data | Data inválida: “31/02/2027”. Use DD/MM/AAAA. |
| 8 | Horário (início–término) | O término deve ser posterior ao início. |
| 9 | Docente (e-mail, usuário ou nome) | Docente “nao.cadastrado@demo.cronomed.example” não encontrado entre os docentes ativos. |
| 10 | Tipo (T/P) | Tipo inválido: “X”. Use T, P, T/P ou -. |
| 11 | Data | 12/08/2027 está fora do semestre 2027.1 (DEMONSTRAÇÃO) (01/02/2027 a 30/06/2027). |

## Saída 2 — conferência de `cronograma_exemplo.xlsx`

15 linhas lidas: 15 encontros a criar, 0 a atualizar, 0 sem alteração, em 2 componentes novos.

Conflitos previstos:

- **Restrição de calendário** — linha 16 (Farmacologia Básica (DEMO) — Turma A) em 08/02/2027: data bloqueada (Carnaval (fictício p/ demonstração))
- **Conflito docente** — Gustavo Arruda (prof. fictício) em dois encontros, 23/02/2027 08:00–10:00: Morfofuncional II (DEMO) — Turma A — já cadastrado × linha 18 (Farmacologia Básica (DEMO) — Turma B)
- **Conflito de turma** — Mesma turma em dois componentes, 03/03/2027 13:00–15:30: MAPD II (DEMO) — Turma A — já cadastrado × linha 17 (Farmacologia Básica (DEMO) — Turma A)

## Saída 3 — resumo gravado após confirmar

```json
{
  "componentes": [
    {"rotulo": "Farmacologia Básica (DEMO) — Turma A", "novo": true, "criados": 8, "atualizados": 0, "sem_alteracao": 0},
    {"rotulo": "Farmacologia Básica (DEMO) — Turma B", "novo": true, "criados": 7, "atualizados": 0, "sem_alteracao": 0}
  ],
  "criados": 15,
  "atualizados": 0,
  "sem_alteracao": 0,
  "conflitos_por_tipo": {"CALENDARIO": 1, "DOCENTE": 1, "TURMA": 1}
}
```

## Saída 4 — plano de remanejamento do semestre

5 conflitos ativos (os 3 da planilha e os 2 já semeados), 5 ações, custo total 22, busca concluída.

1. Mover Farmacologia Básica (DEMO) — Turma A de seg 08/02/2027 08:00–10:00 para qua 10/02/2027 08:00–10:00 — 2 dias de diferença · mantém o horário · qua não é dia habitual do componente · custo 7
2. Mover Habilidades Clínicas II (DEMO) — Turma B de seg 15/02/2027 14:30–17:00 para ter 16/02/2027 14:30–17:00 — 1 dia de diferença · mantém o horário · ter não é dia habitual do componente · custo 6
3. Mover Farmacologia Básica (DEMO) — Turma B de ter 23/02/2027 08:00–10:00 para qui 25/02/2027 08:00–10:00 — 2 dias de diferença · mantém o horário · custo 2
4. Mover Saúde Coletiva II (DEMO) — Turma C de qua 24/02/2027 15:00–17:30 para ter 23/02/2027 15:00–17:30 — 1 dia de diferença · mantém o horário · ter não é dia habitual do componente · custo 6
5. Mover Farmacologia Básica (DEMO) — Turma A de qua 03/03/2027 13:00–15:30 para qui 04/03/2027 13:00–15:30 — 1 dia de diferença · mantém o horário · custo 1

Cada ação traz o selo “Verificado: elimina 1 conflito e não cria nenhum”. Depois de **Aplicar plano completo**, os cinco conflitos passam a “Resolvido” e uma verificação completa da base não encontra conflitos ativos.

Dados enviados ao servidor para aplicar a primeira ação (os identificadores variam conforme a base; o segundo número de cada par é a versão do encontro, usada para recusar sugestões desatualizadas):

```json
{"tipo": "MOVER", "componente": 5, "encontros": [[46, 1]], "data": "2027-02-10", "inicio": "08:00", "fim": "10:00"}
```


## Cruzamento de cinco cronogramas em três formatos

Entrada — cinco arquivos do 2º período, enviados na mesma conferência:

| Arquivo | Formato | Componente | Turma | Encontros |
|---|---|---|---|---|
| `cruzamento_1_anatomia.docx` | DOCX | Anatomia Humana II (DEMO) | A | 4 |
| `cruzamento_2_fisiologia.pdf` | PDF | Fisiologia II (DEMO) | A | 4 |
| `cruzamento_3_bioquimica.xlsx` | XLSX | Bioquímica II (DEMO) | B | 4 |
| `cruzamento_4_histologia.pdf` | PDF | Histologia II (DEMO) | B | 4 |
| `cruzamento_5_saude_da_familia.docx` | DOCX | Saúde da Família II (DEMO) | B | 6 |

Os DOCX e PDF trazem o quadro de identificação (curso, componente, CH, semestre, período, turma, coordenador) e a tabela DATA, HORÁRIO, CONTEÚDO, Tipos, ATIVIDADES, RECURSOS, GRUPOS, DOCENTE, CH, LOCAL, com datas no formato `01/03` e docentes pelo nome. Depois de lidos, todos os arquivos ficam na mesma forma tabular; por exemplo, a primeira linha de `cruzamento_2_fisiologia.pdf`:

| Componente curricular | Turma | Período | Curso | Semestre | Coordenador | Data | Horário | Conteúdo | Docente | CH | Local |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Fisiologia II (DEMO) | A | 2º | Medicina | 2027.1 (DEMONSTRAÇÃO) | Marcos Teles (coord. fictício) | 01/03 | 10h-12h | Introdução | Gustavo Arruda (prof. fictício) | 2h | Sala 110 — Bloco B |

Saída — conferência: 22 linhas lidas, 22 encontros a criar em 5 componentes novos, e 4 conflitos, todos entre arquivos diferentes:

- **Restrição de calendário** — linha 1 de cruzamento_5_saude_da_familia.docx (Saúde da Família II (DEMO) — Turma B) em 09/02/2027: data bloqueada (Carnaval (fictício p/ demonstração))
- **Conflito de turma** — Mesma turma em dois componentes, 15/03/2027 09:00–10:00: linha 3 de cruzamento_1_anatomia.docx (Anatomia Humana II (DEMO) — Turma A) × linha 3 de cruzamento_2_fisiologia.pdf (Fisiologia II (DEMO) — Turma A)
- **Conflito de turma** — Mesma turma em dois componentes, 16/03/2027 14:00–15:00: linha 6 de cruzamento_3_bioquimica.xlsx (Bioquímica II (DEMO) — Turma B) × linha 4 de cruzamento_5_saude_da_familia.docx (Saúde da Família II (DEMO) — Turma B)
- **Conflito docente** — Fernanda Queiroz (profa. fictícia) em dois encontros, 22/03/2027 08:00–10:00: linha 4 de cruzamento_1_anatomia.docx (Anatomia Humana II (DEMO) — Turma A) × linha 4 de cruzamento_4_histologia.pdf (Histologia II (DEMO) — Turma B)

Em planilhas, “linha” é a linha do Excel; em DOCX e PDF, é a posição da linha na tabela do cronograma, sem contar o cabeçalho.

Saída — plano de remanejamento após confirmar a importação (4 ações, custo 21, busca concluída):

1. Mover Saúde da Família II (DEMO) — Turma B de ter 09/02/2027 13:00–15:00 para sex 12/02/2027 13:00–15:00 — 3 dias de diferença · mantém o horário · custo 3
2. Mover Anatomia Humana II (DEMO) — Turma A de seg 15/03/2027 08:00–10:00 para ter 16/03/2027 08:00–10:00 — 1 dia de diferença · mantém o horário · ter não é dia habitual do componente · custo 6
3. Mover Bioquímica II (DEMO) — Turma B de ter 16/03/2027 13:00–15:00 para seg 15/03/2027 13:00–15:00 — 1 dia de diferença · mantém o horário · seg não é dia habitual do componente · custo 6
4. Trocar o docente de Anatomia Humana II (DEMO) — Turma A em seg 22/03/2027 08:00–10:00: Fernanda Queiroz (profa. fictícia) → Marcos Teles (coord. fictício) — docente vinculado ao componente e livre no horário · custo 6

Aplicado o plano, uma verificação completa da base não encontra conflitos ativos.
