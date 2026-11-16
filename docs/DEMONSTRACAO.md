# Guia de demonstração: importar (XLSX, DOCX, PDF), cruzar cronogramas, detectar conflitos e remanejar

Roteiro de cerca de quinze minutos, com dados fictícios. Complementa o roteiro geral do `README.md` (seção 4).

## Preparação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
CRONOMED_DEMO_PASSWORD='escolha-uma-senha' python manage.py seed_demo
python manage.py runserver
```

Os arquivos usados estão em `exemplos/` (para recriá-los, depois do `seed_demo`: `python manage.py gerar_exemplos`). Para repetir a demonstração do zero: `python manage.py seed_demo --reset`.

O semestre de demonstração começa com **dois conflitos docentes** já semeados.

## 1. Planilha com erros é recusada, com indicação linha a linha

1. Entre como `coord2@demo.cronomed.example`.
2. No menu, abra **Importar cronogramas**. Escolha `exemplos/cronograma_exemplo_com_erros.xlsx`, o semestre **2027.1 (DEMONSTRAÇÃO)** e clique em **Enviar e conferir**.
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

## 5. Cruzar cinco cronogramas em formatos diferentes (DOCX, PDF e XLSX)

Os arquivos `exemplos/cruzamento_*` são cinco cronogramas do 2º período: dois em DOCX e dois em PDF (gerados pela exportação do próprio sistema, no modelo institucional, com a marca de rascunho) e um em planilha. Isoladamente nenhum tem problema entre componentes; os conflitos só aparecem quando são cruzados.

1. Ainda como `coord2`, abra **Importar cronogramas**, selecione de uma vez `cruzamento_1_anatomia.docx`, `cruzamento_2_fisiologia.pdf`, `cruzamento_3_bioquimica.xlsx` e `cruzamento_4_histologia.pdf`, escolha o semestre de demonstração e clique em **Enviar e conferir**.
2. O quadro **Arquivos desta conferência** lista os quatro, com formato e encontros lidos. A prévia mostra **2 conflitos**, ambos entre arquivos de formatos diferentes.
3. No mesmo quadro, anexe `cruzamento_5_saude_da_familia.docx` (**Anexar à conferência**). A conferência é refeita com os cinco arquivos: 22 encontros em 5 componentes novos e **4 conflitos**, cada um citando arquivo e linha —
   - restrição de calendário: Saúde da Família II em 09/02/2027 (Carnaval), no DOCX;
   - conflito de turma: Anatomia (DOCX) × Fisiologia (PDF), Turma A, 15/03/2027, 09:00–10:00;
   - conflito de turma: Bioquímica (XLSX) × Saúde da Família (DOCX), Turma B, 16/03/2027, 14:00–15:00;
   - conflito docente: Fernanda Queiroz em Anatomia (DOCX) e Histologia (PDF), 22/03/2027, 08:00–10:00.
4. Opcional: **Retirar** um arquivo e observar a prévia mudar; anexá-lo de novo. Anexar duas vezes o mesmo arquivo é recusado.
5. **Confirmar importação** e, no resultado, **Ver plano de remanejamento sugerido**: 4 ações (custo 21) — três movimentos de aula e uma troca de docente. **Aplicar plano completo** zera os conflitos.

Os docentes e o coordenador aparecem nesses documentos pelo **nome**, não pelo e-mail, e são reconhecidos automaticamente. Quando um nome não é reconhecido (abreviado, por exemplo), a conferência mostra o quadro **Nomes de docentes e coordenadores a associar**, onde se indica o cadastro correspondente ou se opta por importar sem docente.

Qualquer cronograma do sistema pode ser usado da mesma forma: exporte-o em DOCX ou PDF (botões do cronograma) e envie o arquivo na importação.

## 6. Permissões e isolamento

- Entre como `prof1@demo.cronomed.example`: o menu não mostra **Importar cronogramas** e o endereço `/importar/` responde 403. O professor consulta o plano, mas nenhuma ação está ao seu alcance; nos componentes a que está vinculado, pode trocar o docente por uma sugestão, mas não mover aulas.
- Copie o endereço da importação feita por `coord2` (por exemplo, `/importar/2/`), entre como `coord1@demo.cronomed.example` e abra-o: 404. Cada importação é visível apenas a quem a enviou.
- Cronogramas aprovados ou publicados nunca são alterados por sugestões nem por importação (comportamento coberto por testes automatizados; não faz parte deste roteiro manual).

## Caso sem solução

Quando nenhuma alternativa atende às restrições rígidas, a tela do conflito e o plano dizem isso e explicam o motivo (por exemplo, “horários em que a turma já tem aula”, “cronograma aprovado/publicado”). Um exemplo reproduzível está nos testes: `core/tests_sugestoes.py`, `test_sem_solucao_explica_o_motivo`.
