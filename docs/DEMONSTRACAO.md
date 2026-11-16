# Guia de demonstração: importar, detectar conflitos e remanejar

Roteiro de cerca de dez minutos, com dados fictícios. Complementa o roteiro geral do `README.md` (seção 4).

## Preparação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
CRONOMED_DEMO_PASSWORD='escolha-uma-senha' python manage.py seed_demo
python manage.py runserver
```

As planilhas usadas estão em `exemplos/` (para recriá-las: `python manage.py gerar_exemplos`). Para repetir a demonstração do zero: `python manage.py seed_demo --reset`.

O semestre de demonstração começa com **dois conflitos docentes** já semeados.

## 1. Planilha com erros é recusada, com indicação linha a linha

1. Entre como `coord2@demo.cronomed.example`.
2. No menu, abra **Importar planilha**. Escolha `exemplos/cronograma_exemplo_com_erros.xlsx`, o semestre **2027.1 (DEMONSTRAÇÃO)** e clique em **Enviar e conferir**.
3. A conferência mostra **7 erros em 8 linhas**: linha repetida, componente vazio, data inexistente, término antes do início, docente não cadastrado, tipo inválido e data fora do semestre. O botão **Confirmar importação** fica desabilitado.
4. Clique em **Descartar**. Nada foi gravado.

## 2. Planilha válida: mapeamento, prévia de conflitos e importação

1. Envie `exemplos/cronograma_exemplo.xlsx` para o mesmo semestre.
2. **Mapeamento das colunas**: os 15 títulos são reconhecidos automaticamente (a linha de título acima do cabeçalho é ignorada). Para ver a validação reagir, troque “Data” para “— não importar —” e aplique: a validação acusa o campo obrigatório sem coluna. Depois volte ao mapeamento original.
3. **Validação**: 15 encontros a criar em 2 componentes novos (Farmacologia Básica, turmas A e B), sob a coordenação de quem importa.
4. **Conflitos que a importação causará**: três, um de cada tipo —
   - restrição de calendário: aula em 08/02/2027, data bloqueada (Carnaval);
   - conflito docente: Gustavo Arruda em 23/02/2027, 08:00–10:00, também em Morfofuncional II;
   - conflito de turma: Turma A do 4º período em 03/03/2027, 13:00–15:30, também em MAPD II.
5. Clique em **Confirmar importação**. O resultado lista os componentes criados e os conflitos registrados.
6. Clique em **Abrir cronograma** da Turma A: as linhas de 08/02 e 03/03 aparecem destacadas, com os alertas “RESTRIÇÃO DE CALENDÁRIO” e “CONFLITO DE TURMA”.

Se a mesma planilha for enviada outra vez neste ponto, a conferência mostra “0 encontros a criar … 15 sem alteração”: a importação não duplica encontros.

## 3. Sugestões para um conflito

1. Abra **Central de Conflitos** (5 conflitos ativos; use o filtro **Tipo**).
2. Em **Detalhes, histórico e resolução** da restrição de calendário, a seção **Sugestões de remanejamento** lista alternativas em ordem de custo, cada uma com a justificativa e o selo “Verificado: elimina 1 conflito e não cria nenhum”. A primeira é mover a aula para quarta, 10/02/2027, no mesmo horário.
3. Abra o conflito docente de Rafael Moura (MAPD II × Habilidades Clínicas II). Como `coord2` coordena apenas Habilidades Clínicas II, as ações sobre esse componente têm botão **Aplicar** (mover a aula ou trocar o docente por outro vinculado e livre); as que dependem de MAPD II aparecem só como alternativas, para solicitação ao outro coordenador.

## 4. Plano de remanejamento do semestre

1. Na Central de Conflitos, clique em **Plano de remanejamento**.
2. O plano propõe 5 ações encadeadas (custo total 22) que resolvem os 5 conflitos ao alcance de `coord2`. “Como o plano é calculado” resume restrições e preferências.
3. Clique em **Aplicar plano completo**. A tela passa a informar que não há conflitos ativos; na Central, com Situação → Resolvidos, os cinco aparecem como resolvidos; o **Histórico de alterações** registra cada remanejamento, com autor e valores anterior e novo.

## 5. Permissões e isolamento

- Entre como `prof1@demo.cronomed.example`: o menu não mostra **Importar planilha** e o endereço `/importar/` responde 403. O professor consulta o plano, mas nenhuma ação está ao seu alcance; nos componentes a que está vinculado, pode trocar o docente por uma sugestão, mas não mover aulas.
- Copie o endereço da importação feita por `coord2` (por exemplo, `/importar/2/`), entre como `coord1@demo.cronomed.example` e abra-o: 404. Cada importação é visível apenas a quem a enviou.
- Cronogramas aprovados ou publicados nunca são alterados por sugestões nem por importação (comportamento coberto por testes automatizados; não faz parte deste roteiro manual).

## Caso sem solução

Quando nenhuma alternativa atende às restrições rígidas, a tela do conflito e o plano dizem isso e explicam o motivo (por exemplo, “horários em que a turma já tem aula”, “cronograma aprovado/publicado”). Um exemplo reproduzível está nos testes: `core/tests_sugestoes.py`, `test_sem_solucao_explica_o_motivo`.
