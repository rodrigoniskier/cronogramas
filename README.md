# CronoMed UNIPÊ

Plataforma web multiusuário para construção colaborativa de cronogramas acadêmicos, com detecção automática de conflitos de horário docente.

**Créditos:** Prof. Rodrigo Niskier · Metodologia ADS-Niskier Fast MVP.

> MVP para piloto. Foi verificado nos fluxos essenciais (ver "O que foi verificado"), e possui testes automatizados apenas das regras críticas.

## 1. Como executar (local, SQLite)

Requer Python 3.11 ou superior.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # dados FICTÍCIOS; a senha de demonstração é exibida no terminal
python manage.py runserver
```

Acesse <http://127.0.0.1:8000>. O login é feito por e-mail.

- Para definir você mesmo a senha de demonstração: `CRONOMED_DEMO_PASSWORD='sua-senha' python manage.py seed_demo`.
- Para recriar os dados de demonstração: `python manage.py seed_demo --reset`.
- Para iniciar sem dados de demonstração, crie o administrador: `python manage.py createsuperuser`.

### Logomarca

A logomarca oficial está em `branding/logo.png` e é usada na interface e nos documentos, sempre com as proporções originais. Para trocá-la, substitua esse arquivo (ou, fora do Vercel, envie outro em **Administração → Configurações**). O arquivo recebido tem 469×188 px; para impressão mais nítida, substitua por uma versão em maior resolução.

### Testes

```bash
python manage.py test
```

## 2. Execução com Docker e PostgreSQL

```bash
cp .env.example .env        # edite: DJANGO_SECRET_KEY, POSTGRES_PASSWORD e a mesma senha em DATABASE_URL
docker compose up --build -d
docker compose exec web python manage.py seed_demo      # opcional
```

O `Dockerfile`/`docker-compose.yml` não puderam ser executados no ambiente de desenvolvimento (sem daemon Docker); a aplicação em si foi verificada com PostgreSQL 16 fora do Docker.

### Variáveis de ambiente

| Variável | Função |
|---|---|
| `DJANGO_SECRET_KEY` | Chave secreta. Se ausente, uma chave aleatória é criada em `.secret_key` (apenas para uso local). |
| `DJANGO_DEBUG` | `1` para depuração. Padrão `0`. |
| `DJANGO_ALLOWED_HOSTS` | Hosts aceitos, separados por vírgula. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origens confiáveis (ex.: `https://cronomed.exemplo.br`). |
| `DJANGO_HTTPS` | `1` em produção com HTTPS (cookies seguros, confia em `X-Forwarded-Proto`). |
| `DATABASE_URL` | Ex.: `postgres://usuario:senha@host:5432/banco`. Sem ela, usa SQLite. |
| `CRONOMED_MEDIA_ROOT` | Pasta dos arquivos enviados (logomarca). |
| `CRONOMED_DEMO_PASSWORD` | Senha dos usuários fictícios do `seed_demo`. |

## 2.1 Implantação no Vercel (usuários reais)

O repositório já contém `vercel.json` (Django como função Python) e os fluxos do GitHub Actions. **A publicação em si precisa ser feita na sua conta do Vercel** — não foi realizada nem testada no ambiente de desenvolvimento, que não tem acesso a ela. O comportamento do sistema com as configurações do Vercel foi apenas simulado localmente.

Passo a passo (uma única vez):

1. Em <https://vercel.com/new>, importe o repositório `rodrigoniskier/cronogramas` (Framework Preset: **Other**; não altere comandos de build).
2. No projeto, aba **Storage** → crie um banco **Postgres (Neon)** e conecte-o ao projeto. Isso cria a variável `DATABASE_URL`. Prefira a região de São Paulo, se disponível.
3. Em **Settings → Environment Variables**, crie `DJANGO_SECRET_KEY` com uma chave aleatória longa (comando em `.env.example`).
4. No GitHub, em **Settings → Secrets and variables → Actions**, cadastre os segredos `DATABASE_URL` (mesmo valor do Vercel), `DJANGO_SECRET_KEY` e `ADMIN_PASSWORD` (senha do primeiro administrador).
5. Em **Actions**, execute **"Criar administrador (manual)"** informando e-mail e nome. Ele aplica as migrações e cria o administrador.
6. No Vercel, faça **Redeploy**. Acesse a URL `*.vercel.app` e entre com o administrador.

Depois disso, tudo é automático: a cada `git push` na branch `main`, o GitHub Actions roda os testes e aplica as migrações no banco, e o Vercel publica a nova versão.

Pontos de atenção:

- **Arquivos:** no Vercel o disco é somente leitura. Por isso a logomarca vem do repositório e o envio pela tela fica desativado. Os documentos DOCX/PDF são gerados em memória e funcionam normalmente.
- **Plano:** o plano gratuito (Hobby) do Vercel é restrito a uso pessoal e não comercial; verifique se o uso institucional exige o plano Pro.
- **Dados pessoais:** nomes e e-mails de docentes ficarão em serviços de terceiros (Vercel/Neon). Confirme com a TI/encarregado de dados do UNIPÊ antes do uso real.
- **Domínio próprio:** ao usar um domínio institucional, acrescente-o em `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS` (ex.: `https://cronogramas.unipe.edu.br`).
- **Alternativa:** um servidor da própria instituição com `docker compose` (seção 2) mantém os dados internamente.

## 3. Dados de demonstração (fictícios)

`seed_demo` cria 1 administrador, 3 coordenadores, 8 professores, 1 semestre e 4 componentes (turmas A e B), com feriado bloqueado, cronogramas parciais, um cronograma completo e **dois conflitos intencionais**. Todos os nomes trazem a indicação "fictício".

| Login (e-mail) | Perfil | Papel na demonstração |
|---|---|---|
| `admin@demo.cronomed.example` | Administrador | acesso total |
| `coord1@demo.cronomed.example` | Coordenador | coordena MAPD II |
| `coord2@demo.cronomed.example` | Coordenador | coordena Habilidades Clínicas II e Saúde Coletiva II |
| `coord3@demo.cronomed.example` | Coordenador | coordena Morfofuncional II (completo, sem conflitos) |
| `prof1@…` a `prof8@…` | Professor | `prof1` e `prof2` estão nos conflitos |

Conflitos semeados:

1. **prof1 (Rafael Moura)**, 15/02/2027 — MAPD II 13:00–15:30 × Habilidades Clínicas II 14:30–17:00 (sobreposição 14:30–15:30).
2. **prof2 (Beatriz Lacerda)**, 24/02/2027 — MAPD II 13:00–15:30 × Saúde Coletiva II 15:00–17:30 (sobreposição 15:00–15:30).

Contraexemplo: prof3 em 17/02/2027 tem MAPD II 13:00–15:30 e Habilidades 15:30–18:00 — aulas consecutivas, **sem** conflito.

## 4. Roteiro de demonstração

1. Entre como `prof1`. Um aviso (não bloqueante) informa as pendências; o painel as lista no topo.
2. Abra **MAPD II**. As linhas de 15/02 e 24/02 aparecem destacadas, com selo "Conflito" e alerta textual indicando professor, data, outro componente, turma, horários e sobreposição.
3. Edite qualquer célula e observe "Todas as alterações salvas". Clique em **Salvar**: o cronograma é salvo mesmo com conflitos.
4. No alerta, clique em **Abrir o outro encontro** — o sistema leva ao encontro de Habilidades Clínicas II.
5. Nesse encontro, troque o professor (dropdown pesquisável) para outro docente. O destaque desaparece e o conflito passa a "Resolvido" na **Central de Conflitos** (filtro Situação → Resolvidos).
6. Para criar um conflito novo: em dois componentes diferentes, aloque o mesmo docente em encontros do mesmo dia com horários sobrepostos.
7. Entre como `coord3`, abra **Morfofuncional II**, clique em **Validar cronograma** e depois em **Aprovar cronograma**. Em seguida, **Publicar**. Exporte DOCX e PDF (versão oficial, sem marca de rascunho).
8. Entre como `coord1`, abra **MAPD II** e clique em **Validar cronograma**: a lista de pendências impede a aprovação. Exporte: o arquivo sai marcado "NÃO APROVADO".
9. Permissões: como `prof1`, abra **Saúde Coletiva II** (sem vínculo) — a tela fica em modo consulta.

Fluxo administrativo (como `admin`): **Usuários** (criar, editar, redefinir senha), **Semestres e calendário** (criar semestre, bloquear datas, liberar preenchimento), **Componentes → Novo componente** (os encontros são gerados ao salvar).

## 5. Regras implementadas

- **Conflito docente:** mesmo docente (por ID, nunca por nome) em dois encontros distintos, na mesma data, com intervalos sobrepostos (`início_A < fim_B` e `início_B < fim_A`). Intervalos consecutivos não conflitam. Considera todos os componentes de todos os coordenadores.
- **Quando é recalculado:** a cada alteração de professor, data ou horário; ao inserir/remover encontros; ao regerar encontros; ao validar e ao aprovar; e pelo botão **Verificar novamente** (toda a base). A tela do editor também se atualiza a cada 20 s, refletindo mudanças feitas em outros componentes.
- **Salvar nunca é bloqueado por conflito.** Apenas a aprovação exige: todos os encontros com conteúdo e professor, e nenhum conflito ativo.
- **Estados:** Não iniciado → Em preenchimento → Com pendências (há conflito) → Pronto para aprovação → Aprovado → Publicado. Os quatro primeiros são calculados a partir dos dados; aprovação e publicação são ações do coordenador responsável (ou do administrador). Aprovados/publicados ficam bloqueados; **Reabrir para revisão** (com motivo, registrado no histórico) devolve o cronograma à elaboração.
- **Permissões:** todos consultam tudo. Professores editam conteúdo, professor, atividade, local e observações dos componentes a que estão vinculados. Coordenador responsável e administrador também alteram data/horário, inserem/removem encontros, editam o cadastro, aprovam e publicam. Professores e coordenadores só editam após a liberação do semestre. As regras são verificadas no servidor.
- **Modelo institucional:** a tabela do editor e os documentos seguem o "CRONOGRAMA DE AULAS" da Coordenação de Medicina: quadro numerado (curso, componente, CH total/teórica/prática, semestre, período, turma, coordenador) e colunas DATA, HORÁRIO, CONTEÚDO, Tipos (T/P), ATIVIDADES, RECURSOS, GRUPOS, DOCENTE, CH e LOCAL. Feriados e datas bloqueadas aparecem como linhas ("Feriado - …"). A coluna "Obs. internas" existe só no sistema e não é exportada. A CH de cada encontro é sugerida em horas-aula de 50 min (15h30–18h = 3h) e pode ser editada.
- **Vários docentes na mesma aula:** o coordenador usa o botão "adicionar docente" da linha; cada docente (ou grupo) ocupa uma linha no mesmo dia e horário, com sua própria CH. Na exportação, linhas idênticas nas demais colunas são mescladas, como no modelo.
- **Geração de encontros:** a partir dos horários semanais, entre as datas do componente, pulando datas bloqueadas. Ao alterar o cadastro ou o calendário, encontros vazios fora da grade são removidos e encontros já preenchidos são preservados como "excepcionais".
- **Edição simultânea:** cada encontro tem número de versão. Se dois usuários alteram **o mesmo campo**, o segundo recebe um aviso e escolhe qual valor manter — nada é sobrescrito em silêncio. Alterações em campos diferentes do mesmo encontro são mescladas.
- **Histórico:** usuário, data/hora, encontro, campo, valor anterior e novo valor; também registra inserções, remoções, aprovação, publicação e reabertura.
- **Senhas:** armazenadas com hash (padrão Django). Redefinição administrativa gera senha temporária exibida uma única vez, com troca obrigatória no acesso seguinte.

## 6. Estrutura técnica

- **Stack:** Python, Django 6 (templates), Bootstrap 5, Bootstrap Icons e Tom Select (incluídos em `core/static/vendor`, sem CDN), JavaScript sem framework, python-docx, ReportLab, WhiteNoise. Banco: PostgreSQL (`DATABASE_URL`) ou SQLite.

```
config/                  configurações e rotas do projeto
core/models.py           Usuario, Semestre, DataBloqueada, Componente, HorarioSemanal,
                         Encontro, Conflito, ObservacaoConflito, HistoricoAlteracao, Configuracao
core/services.py         regras de negócio: geração de encontros, conflitos, estados, permissões
core/views.py            páginas e API JSON do editor
core/exports.py          geração de DOCX e PDF (constantes de leiaute no topo do arquivo)
core/static/core/        app.css (cores institucionais em variáveis) e editor.js
core/templates/          telas
core/management/commands/seed_demo.py   dados de demonstração
core/tests.py            testes das regras críticas
vercel.json              implantação no Vercel
.github/workflows/       testes, migração automática e criação do administrador
```

## 7. O que foi verificado

Executado com navegador automatizado (Chromium) sobre os dados de demonstração: login; criação de usuário com senha temporária e troca obrigatória; criação de semestre, data bloqueada e componente com dois horários semanais (geração correta dos encontros, pulando o feriado); bloqueio antes da liberação e edição depois; edição de células com salvamento automático e persistência; seleção de docente no dropdown; aviso de edição concorrente e mescla de campos distintos; aviso de pendências no login; destaque e texto dos conflitos; salvar com conflitos; navegação ao componente conflitante; resolução automática após troca de docente; recusa de edição sem vínculo (tela e API, HTTP 403); validação com pendências; aprovação, bloqueio pós-aprovação e publicação; exportação DOCX e PDF (rascunho e oficial; DOCX aberto no LibreOffice); encontro excepcional; leiaute em celular. Migrações, dados de demonstração e regras centrais também foram executados em PostgreSQL 16.

## 8. Limitações conhecidas

- As cores da interface (`--unipe-azul: #003a70`, `--unipe-amarelo: #ffc20e` em `app.css`) são aproximações a conferir com o manual de marca.
- A seção "Reposições - Ajustar com a turma" do modelo (aulas sem data) não é suportada: todo encontro precisa de data e horário.
- Os documentos reproduzem a estrutura do modelo, mas não são gerados a partir do arquivo Word original; fontes e espaçamentos podem diferir ligeiramente.
- Implantação no Vercel preparada, porém não executada nem testada (ver seção 2.1).
- Recuperação de senha apenas por redefinição administrativa (sem e-mail).
- Não há edição em tempo real: mudanças de outros usuários aparecem em até 20 s ou ao salvar.
- Só são detectados conflitos **de docente**. Conflitos de sala ou de turma não são verificados.
- Um cronograma já aprovado pode passar a ter conflito se outro componente alocar o mesmo docente no mesmo horário; o conflito aparece na Central e no painel, mas a situação "Aprovado" não é revertida automaticamente.
- "Publicado" é uma marcação de situação visível a todos os usuários autenticados; não há página pública para alunos.
- Não há importação de planilhas/Word nem cadastro em lote de usuários.
- A marca de rascunho no DOCX é uma faixa no cabeçalho de todas as páginas (no PDF há também marca-d'água diagonal).
- Há 13 testes automatizados das regras críticas (`core/tests.py`), mas sem testes de carga nem auditoria de segurança formal.

## 9. Recomendações para o piloto

Peça a professores e coordenadores que avaliem:

1. Se as colunas da tabela correspondem ao cronograma Word usado hoje (o que falta, o que sobra).
2. Se os alertas de conflito são compreensíveis e se fica claro quem deve agir.
3. Se a divisão de permissões (professor × coordenador) corresponde à prática real — em especial quem pode mudar data e horário.
4. Se a exigência de "conteúdo + professor" em todos os encontros é adequada para aprovar (ex.: avaliações, feriados compensados).
5. A fidelidade dos DOCX/PDF ao padrão institucional.
6. O comportamento quando duas pessoas editam o mesmo componente ao mesmo tempo.
7. O uso em telas menores (notebook, tablet).

Antes de uso com dados reais: definir `DJANGO_SECRET_KEY`, usar PostgreSQL com backup, HTTPS, e remover os usuários de demonstração.

---
CronoMed UNIPÊ — Desenvolvido por Prof. Rodrigo Niskier.
