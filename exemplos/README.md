# Exemplos de entrada e saída

Todos os dados são **fictícios**: nomes marcados como fictícios e e-mails no domínio reservado `demo.cronomed.example`. As planilhas referenciam os usuários e o semestre criados por `python manage.py seed_demo` e são geradas por `python manage.py gerar_exemplos`.

As saídas abaixo foram obtidas executando o sistema sobre a base de demonstração recém-criada, importando como `coord2`.

## Entrada

Formato: `.xlsx`, uma linha por encontro, na primeira aba. Linhas de título acima do cabeçalho são ignoradas.

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
