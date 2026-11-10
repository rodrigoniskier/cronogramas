/* CronoMed UNIPÊ — editor de cronograma: células editáveis, salvamento
   automático, controle de edição concorrente e alertas de conflito. */
(function () {
  'use strict';
  var cfg = JSON.parse(document.getElementById('cfg').textContent);
  var docentes = JSON.parse(document.getElementById('docentes').textContent);
  var estado = JSON.parse(document.getElementById('estado').textContent);
  var nomeDocente = {};
  docentes.forEach(function (d) { nomeDocente[d.id] = d.nome; });
  var corpo = document.getElementById('corpo');
  var linhas = new Map();           // id -> {dados, tr, sujos:Set, timer, ocupado, ts}
  var editavel = estado.pode_editar;
  var agenda = editavel && cfg.gerencia;
  var CAMPOS_TEXTO = ['conteudo', 'tipo', 'atividade', 'recursos', 'grupos', 'ch', 'local', 'observacoes'];
  var TIPOS = [['', '—'], ['T', 'T'], ['P', 'P'], ['T/P', 'T/P'], ['-', '-']];
  var LIMITE = {grupos: 300, ch: 10, local: 120};
  var NCOL = 12;
  var ROTULO = {conteudo: 'Conteúdo', tipo: 'Tipo', atividade: 'Atividades', recursos: 'Recursos', grupos: 'Grupos', ch: 'CH', local: 'Local', observacoes: 'Observações', professor_id: 'Professor(a)', data: 'Data', inicio: 'Início', fim: 'Término'};
  var falhaRede = false, geracao = 0;

  function csrf() { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : ''; }
  function el(tag, attrs, filhos) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k]; else if (k === 'html') e.innerHTML = attrs[k]; else e.setAttribute(k, attrs[k]);
    });
    (filhos || []).forEach(function (f) { if (f) e.appendChild(f); });
    return e;
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function api(url, corpoReq) {
    return fetch(url, {
      method: corpoReq === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf(), 'X-Requested-With': 'fetch'},
      body: corpoReq === undefined ? undefined : JSON.stringify(corpoReq)
    }).then(function (r) {
      return r.json().catch(function () { return {erro: 'Resposta inesperada do servidor (' + r.status + ').'}; })
        .then(function (j) { return {ok: r.ok, status: r.status, j: j}; });
    });
  }
  function toast(msg, tipo) {
    var t = el('div', {class: 'toast align-items-center border-0 text-bg-' + (tipo || 'primary'), role: tipo === 'danger' ? 'alert' : 'status'},
      [el('div', {class: 'd-flex'}, [el('div', {class: 'toast-body', text: msg}), el('button', {type: 'button', class: 'btn-close btn-close-white me-2 m-auto', 'data-bs-dismiss': 'toast', 'aria-label': 'Fechar'})])]);
    document.getElementById('toasts').appendChild(t);
    new bootstrap.Toast(t, {delay: tipo === 'danger' ? 9000 : 4000}).show();
    t.addEventListener('hidden.bs.toast', function () { t.remove(); });
  }
  function crescer(t) { t.style.height = 'auto'; t.style.height = Math.max(t.scrollHeight, 34) + 'px'; }

  // ------------------------------------------------------------ renderização
  function lerCampo(L, campo) {
    if (campo === 'professor_id') {
      var v = L.ts ? L.ts.getValue() : L.tr.querySelector('select[data-campo="professor_id"]').value;
      return v ? parseInt(v, 10) : null;
    }
    return L.tr.querySelector('[data-campo="' + campo + '"]').value;
  }
  function opcoesMinimas(sel, id) {
    sel.innerHTML = '';
    sel.appendChild(el('option', {value: '', text: '— selecionar —'}));
    if (id) { var o = el('option', {value: id, text: nomeDocente[id] || 'Docente inativo'}); o.selected = true; sel.appendChild(o); }
  }
  function escreverCampo(L, campo, valor) {
    if (campo === 'professor_id') {
      if (L.ts) L.ts.setValue(valor ? String(valor) : '', true);
      else opcoesMinimas(L.tr.querySelector('select[data-campo="professor_id"]'), valor);
      return;
    }
    var c = L.tr.querySelector('[data-campo="' + campo + '"]');
    c.value = valor;
    if (c.tagName === 'TEXTAREA') crescer(c);
  }
  function ativarSelect(L) {
    // O dropdown pesquisável é criado sob demanda para manter a tabela leve.
    if (L.ts) return L.ts;
    var sel = L.tr.querySelector('select[data-campo="professor_id"]');
    var atual = sel.value;
    sel.innerHTML = '';
    sel.appendChild(el('option', {value: '', text: '— selecionar —'}));
    [['Vinculados a este componente', true], ['Outros docentes', false]].forEach(function (g) {
      var og = el('optgroup', {label: g[0]});
      docentes.forEach(function (d) { if (d.vinculado === g[1]) og.appendChild(el('option', {value: d.id, text: d.nome})); });
      if (og.children.length) sel.appendChild(og);
    });
    if (atual && !nomeDocente[atual]) sel.appendChild(el('option', {value: atual, text: 'Docente inativo'}));
    sel.value = atual;
    var rotuloAria = sel.getAttribute('aria-label');
    L.ts = new TomSelect(sel, {
      maxOptions: 1000, allowEmptyOption: true, placeholder: 'Pesquisar docente…',
      dropdownParent: 'body',
      onChange: function () { sujar(L, 'professor_id'); agendar(L, 0); }
    });
    if (L.ts.control_input && rotuloAria) {
      L.ts.control_input.setAttribute('aria-label', rotuloAria);
    }
    return L.ts;
  }
  function celulaTexto(L, campo) {
    var td = el('td');
    if (!editavel) { td.appendChild(el('div', {class: 'leitura', text: L.dados[campo]})); return td; }
    if (campo === 'tipo') {
      var st = el('select', {class: 'celula celula-tipo', 'data-campo': 'tipo', 'aria-label': 'Tipo — ' + L.dados.data_br});
      TIPOS.forEach(function (o) { st.appendChild(el('option', {value: o[0], text: o[1]})); });
      st.value = L.dados.tipo; td.appendChild(st); return td;
    }
    var t = el('textarea', {class: 'celula', rows: 1, 'data-campo': campo, 'aria-label': ROTULO[campo] + ' — ' + L.dados.data_br});
    t.value = L.dados[campo];
    if (LIMITE[campo]) t.maxLength = LIMITE[campo];
    td.appendChild(t);
    return td;
  }
  function criarLinha(enc, anterior) {
    var L = {dados: enc, sujos: new Set(), timer: null, ocupado: false, ts: null};
    var tr = el('tr', {class: 'linha-encontro', id: 'encontro-' + enc.id});
    L.tr = tr;
    var tdData = el('td', {class: 'fixo'});
    var tdHora = el('td', {class: 'fixo'});
    if (agenda) {
      var d = el('input', {type: 'date', class: 'celula celula-agenda', 'data-campo': 'data', 'aria-label': 'Data — ' + enc.data_br}); d.value = enc.data;
      var i = el('input', {type: 'time', class: 'celula celula-agenda', 'data-campo': 'inicio', 'aria-label': 'Início — ' + enc.data_br}); i.value = enc.inicio;
      var f = el('input', {type: 'time', class: 'celula celula-agenda', 'data-campo': 'fim', 'aria-label': 'Término — ' + enc.data_br}); f.value = enc.fim;
      tdData.appendChild(d); tdHora.appendChild(i); tdHora.appendChild(f);
    } else {
      tdData.appendChild(el('span', {'data-txt': 'data'}));
      tdHora.appendChild(el('span', {'data-txt': 'hora'}));
    }
    tdData.appendChild(el('div', {class: 'dia-semana', 'data-dia': '1', text: enc.dia}));
    tdData.appendChild(el('div', {'data-selos': '1'}));
    tr.appendChild(tdData); tr.appendChild(tdHora);
    ['conteudo', 'tipo', 'atividade', 'recursos', 'grupos'].forEach(function (c) { tr.appendChild(celulaTexto(L, c)); });
    var tdProf = el('td');
    if (editavel) {
      var sel = el('select', {class: 'celula', 'data-campo': 'professor_id', 'aria-label': 'Docente — ' + enc.data_br});
      opcoesMinimas(sel, enc.professor_id);
      tdProf.appendChild(sel);
    } else tdProf.appendChild(el('div', {class: 'leitura', text: enc.professor_nome}));
    tr.appendChild(tdProf);
    ['ch', 'local', 'observacoes'].forEach(function (c) { tr.appendChild(celulaTexto(L, c)); });
    var tdAcoes = el('td', {class: 'acoes-linha'});
    tdAcoes.appendChild(el('button', {type: 'button', class: 'btn btn-sm btn-outline-secondary', 'data-acao': 'historico', 'aria-label': 'Histórico do encontro de ' + enc.data_br, html: '<i class="bi bi-clock-history"></i>'}));
    if (agenda) tdAcoes.appendChild(el('button', {type: 'button', class: 'btn btn-sm btn-outline-primary ms-1', 'data-acao': 'docente', title: 'Adicionar outro docente/grupo nesta mesma aula', 'aria-label': 'Adicionar outro docente na aula de ' + enc.data_br, html: '<i class="bi bi-person-plus"></i>'}));
    if (agenda) tdAcoes.appendChild(el('button', {type: 'button', class: 'btn btn-sm btn-outline-danger ms-1', 'data-acao': 'excluir', 'aria-label': 'Remover encontro de ' + enc.data_br, html: '<i class="bi bi-trash"></i>'}));
    tr.appendChild(tdAcoes);
    // preserva o que o usuário estava digitando quando a tabela é reconstruída
    if (anterior && anterior.sujos.size) {
      L.pendentes = {};
      anterior.sujos.forEach(function (c) { L.pendentes[c] = lerCampo(anterior, c); });
    }
    return L;
  }
  function decorar(L) {
    var enc = L.dados, tr = L.tr, conf = estado.conflitos[enc.id] || [];
    tr.classList.toggle('tem-conflito', conf.length > 0);
    tr.classList.toggle('completo', enc.preenchido && !conf.length);
    tr.classList.toggle('incompleto', !enc.preenchido && !conf.length);
    tr.querySelector('[data-dia]').textContent = enc.dia;
    var t = tr.querySelector('[data-txt="data"]'); if (t) t.textContent = enc.data_br;
    t = tr.querySelector('[data-txt="hora"]'); if (t) t.textContent = enc.horario_modelo;
    var selos = tr.querySelector('[data-selos]');
    selos.innerHTML = (conf.length ? '<span class="selo selo-conflito"><i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i> Conflito</span> ' : '') +
      (enc.excepcional ? '<span class="selo selo-excepcional" title="Encontro fora da grade semanal regular"><i class="bi bi-star-fill" aria-hidden="true"></i> Excepcional</span>' : '');
    var h = tr.querySelector('[data-acao="historico"]');
    h.title = enc.atualizado_por ? 'Última edição: ' + enc.atualizado_por + ' em ' + enc.atualizado_em : 'Sem edições registradas';
  }
  function linhaAlerta(enc) {
    var conf = estado.conflitos[enc.id];
    if (!conf) return null;
    var td = el('td', {colspan: NCOL});
    conf.forEach(function (c) {
      td.appendChild(el('div', {class: 'alerta-conflito', html:
        '<i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i> <strong>CONFLITO DE HORÁRIO DOCENTE:</strong> ' + esc(c.professor) +
        ' está alocado(a) em ' + esc(c.data_br) + ' neste encontro (' + esc(c.meu_horario) + ') e também em <strong>' + esc(c.outro_componente) +
        ' — Turma ' + esc(c.outro_turma) + '</strong> (' + esc(c.outro_horario) + ', coord. ' + esc(c.outro_coordenador) + '). Horário sobreposto: <strong>' + esc(c.sobreposicao) + '</strong>. ' +
        '<a href="' + esc(c.outro_url) + '">Abrir o outro encontro</a> · <a href="' + esc(c.detalhe_url) + '">Detalhes e resolução</a>'}));
    });
    return el('tr', {class: 'linha-alerta', 'data-alerta': enc.id}, [td]);
  }
  function mesmaEstrutura(encs) {
    var trs = corpo.querySelectorAll('tr.linha-encontro');
    if (trs.length !== encs.length) return false;
    for (var i = 0; i < encs.length; i++) if (trs[i].id !== 'encontro-' + encs[i].id) return false;
    return true;
  }
  function aplicarEstado(novo) {
    estado = novo;
    if (novo.pode_editar !== editavel) { location.reload(); return; }
    if (!mesmaEstrutura(novo.encontros)) {
      var antigas = linhas; linhas = new Map();
      antigas.forEach(function (L) { clearTimeout(L.timer); });
      var frag = document.createDocumentFragment();
      novo.encontros.forEach(function (enc) {
        var L = criarLinha(enc, antigas.get(enc.id));
        linhas.set(enc.id, L); frag.appendChild(L.tr);
      });
      antigas.forEach(function (L) { if (L.ts) L.ts.destroy(); });
      corpo.innerHTML = ''; corpo.appendChild(frag);
      linhas.forEach(function (L) {
        L.tr.querySelectorAll('textarea').forEach(crescer);
        if (L.pendentes) {
          Object.keys(L.pendentes).forEach(function (c) { escreverCampo(L, c, L.pendentes[c]); sujar(L, c); });
          delete L.pendentes; agendar(L, 800);
        }
      });
    } else {
      novo.encontros.forEach(function (enc) {
        var L = linhas.get(enc.id), mudou = enc.versao !== L.dados.versao;
        L.dados = enc;
        if (mudou && editavel) {
          CAMPOS_TEXTO.concat(['professor_id'], agenda ? ['data', 'inicio', 'fim'] : []).forEach(function (c) {
            var campo = L.tr.querySelector('[data-campo="' + c + '"]');
            var emUso = document.activeElement === campo || (c === 'professor_id' && L.ts && (L.ts.isFocused || L.ts.isOpen));
            if (!L.sujos.has(c) && !emUso && lerCampo(L, c) !== enc[c]) escreverCampo(L, c, enc[c]);
          });
        } else if (mudou) {
          var ro = L.tr.querySelectorAll('.leitura');
          [enc.conteudo, enc.tipo, enc.atividade, enc.recursos, enc.grupos, enc.professor_nome, enc.ch, enc.local, enc.observacoes].forEach(function (v, i) { ro[i].textContent = v; });
        }
      });
    }
    corpo.querySelectorAll('tr.linha-alerta').forEach(function (t) { t.remove(); });
    linhas.forEach(function (L) {
      decorar(L);
      var a = linhaAlerta(L.dados);
      if (a) L.tr.after(a);
    });
    corpo.querySelectorAll('tr.linha-feriado').forEach(function (t) { t.remove(); });
    (estado.feriados || []).forEach(function (f) {
      var tr = el('tr', {class: 'linha-feriado', 'data-data': f.data}, [
        el('td', {class: 'fixo', text: f.data_br}), el('td', {class: 'fixo', text: f.horario}),
        el('td', {html: '<i class="bi bi-calendar-x" aria-hidden="true"></i> <strong>' + esc(f.descricao) + '</strong>'}),
        el('td', {class: 'text-center', text: '-'}), el('td', {colspan: 4, class: 'text-secondary', text: 'Data bloqueada no calendário do semestre — sem aula.'}),
        el('td', {text: f.ch}), el('td', {colspan: 3})]);
      var depois = null;
      corpo.querySelectorAll('tr.linha-encontro').forEach(function (t) {
        var L = linhas.get(parseInt(t.id.split('-')[1], 10));
        if (!depois && L && (L.dados.data > f.data || (L.dados.data === f.data && L.dados.inicio >= f.inicio))) depois = t;
      });
      if (depois) corpo.insertBefore(tr, depois); else corpo.appendChild(tr);
    });
    cabecalho(); filtroDocentes(); filtrar();
  }
  function cabecalho() {
    var s = estado.stats;
    document.getElementById('selo-status').innerHTML =
      '<span class="badge badge-status text-bg-' + s.status_cor + '"><i class="bi ' + s.status_icone + '" aria-hidden="true"></i> ' + esc(s.status_rotulo) + '</span> ' +
      '<span class="small text-secondary ms-1">' + s.preenchidos + ' de ' + s.total + ' encontros preenchidos (' + s.pct + '%)</span>';
    var b = document.getElementById('banner-conflitos');
    b.innerHTML = s.conflitos ? '<div class="alert alert-danger d-flex flex-wrap align-items-center gap-2 mb-2"><i class="bi bi-exclamation-triangle-fill fs-5" aria-hidden="true"></i><div><strong>' + s.conflitos +
      (s.conflitos > 1 ? ' conflitos de horário docente' : ' conflito de horário docente') + ' neste cronograma.</strong> O salvamento continua permitido; a aprovação só será possível após a resolução.</div>' +
      '<button type="button" class="btn btn-sm btn-danger ms-auto" id="ver-conflitos"><i class="bi bi-funnel"></i> Mostrar só os conflitos</button>' +
      '<a class="btn btn-sm btn-outline-danger" href="/conflitos/?componente=' + cfg.compId + '">Central de Conflitos</a></div>' : '';
    var u = estado.ultima_edicao;
    document.getElementById('ultima-edicao').textContent = u ? 'Última edição: ' + u.por + ', ' + u.em : 'Nenhuma edição registrada';
  }

  // ------------------------------------------------------------------ filtros
  var fDoc = document.getElementById('f-docente'), fDe = document.getElementById('f-de'), fAte = document.getElementById('f-ate'), fSit = document.getElementById('f-sit');
  function filtroDocentes() {
    var atual = fDoc.value, vistos = {};
    estado.encontros.forEach(function (e) { if (e.professor_id) vistos[e.professor_id] = e.professor_nome; });
    while (fDoc.options.length > 2) fDoc.remove(2);
    Object.keys(vistos).sort(function (a, b) { return vistos[a].localeCompare(vistos[b]); })
      .forEach(function (id) { fDoc.appendChild(el('option', {value: id, text: vistos[id]})); });
    fDoc.value = atual; if (fDoc.selectedIndex < 0) fDoc.value = '';
  }
  function filtrar() {
    var n = 0;
    linhas.forEach(function (L) {
      var e = L.dados, conf = !!estado.conflitos[e.id], ok = true;
      if (fDoc.value === '0') ok = !e.professor_id; else if (fDoc.value) ok = String(e.professor_id) === fDoc.value;
      if (ok && fDe.value) ok = e.data >= fDe.value;
      if (ok && fAte.value) ok = e.data <= fAte.value;
      if (ok && fSit.value === 'completo') ok = e.preenchido;
      if (ok && fSit.value === 'incompleto') ok = !e.preenchido;
      if (ok && fSit.value === 'conflito') ok = conf;
      if (L.sujos.size) ok = true;
      L.tr.hidden = !ok;
      var a = corpo.querySelector('tr[data-alerta="' + e.id + '"]'); if (a) a.hidden = !ok;
      if (ok) n++;
    });
    corpo.querySelectorAll('tr.linha-feriado').forEach(function (t) {
      var d = t.dataset.data;
      t.hidden = !!(fDoc.value || fSit.value || (fDe.value && d < fDe.value) || (fAte.value && d > fAte.value));
    });
    document.getElementById('f-contagem').textContent = n + ' de ' + linhas.size;
    if (!linhas.size && !corpo.querySelector('.vazio')) corpo.appendChild(el('tr', {class: 'vazio'}, [el('td', {colspan: NCOL, class: 'text-center text-secondary p-4', text: 'Este componente ainda não possui encontros.'})]));
    else if (linhas.size) { var v = corpo.querySelector('.vazio'); if (v) v.remove(); }
  }
  [fDoc, fDe, fAte, fSit].forEach(function (f) { f.addEventListener('change', filtrar); });
  function limparFiltros() { fDoc.value = fDe.value = fAte.value = fSit.value = ''; filtrar(); }
  document.getElementById('f-limpar').addEventListener('click', limparFiltros);
  document.getElementById('banner-conflitos').addEventListener('click', function (ev) {
    if (ev.target.closest('#ver-conflitos')) { limparFiltros(); fSit.value = 'conflito'; filtrar(); }
  });

  // -------------------------------------------------------------- salvamento
  var indicador = document.getElementById('indicador');
  function atualizarIndicador() {
    if (!indicador) return;
    var sujo = false, ocupado = false;
    linhas.forEach(function (L) { if (L.sujos.size) sujo = true; if (L.ocupado) ocupado = true; });
    if (ocupado) indicador.innerHTML = '<span class="spinner-border spinner-border-sm text-primary" aria-hidden="true"></span> Salvando…';
    else if (falhaRede) indicador.innerHTML = '<span class="text-danger"><i class="bi bi-wifi-off"></i> Sem conexão — alterações ainda não salvas</span>';
    else if (sujo) indicador.innerHTML = '<span class="text-warning-emphasis"><i class="bi bi-circle-fill" style="font-size:.6rem"></i> Alterações não salvas</span>';
    else indicador.innerHTML = '<span class="text-success"><i class="bi bi-check-circle-fill"></i> Todas as alterações salvas</span>';
  }
  function sujar(L, campo) {
    L.sujos.add(campo);
    var c = L.tr.querySelector('[data-campo="' + campo + '"]'); if (c) c.classList.add('suja');
    atualizarIndicador();
  }
  function limpar(L, campo) {
    L.sujos.delete(campo);
    var c = L.tr.querySelector('[data-campo="' + campo + '"]'); if (c) c.classList.remove('suja');
  }
  function agendar(L, ms) { clearTimeout(L.timer); L.timer = setTimeout(function () { salvar(L); }, ms); }
  function salvar(L) {
    clearTimeout(L.timer);
    if (!L.sujos.size || !linhas.has(L.dados.id)) return Promise.resolve();
    if (L.emConcorrencia) return Promise.resolve();   // aguardando decisão do usuário
    if (L.ocupado) { L.repetir = true; return L.promessa; }
    var campos = {}, base = {}, enviados = Array.from(L.sujos);
    enviados.forEach(function (c) { campos[c] = lerCampo(L, c); base[c] = L.dados[c]; });
    L.ocupado = true; geracao++; atualizarIndicador();
    L.promessa = api('/api/encontros/' + L.dados.id + '/', {campos: campos, base: base, versao: L.dados.versao})
      .then(function (r) {
        falhaRede = false;
        if (r.ok) {
          enviados.forEach(function (c) { if (lerCampo(L, c) === campos[c]) limpar(L, c); else L.repetir = true; });
          L.dados = Object.assign({}, r.j.encontro, {versao: -1});   // força a atualização dos campos não editados
          aplicarEstado(r.j.estado);
        } else if (r.status === 409) {
          resolverConcorrencia(L, r.j, campos);
        } else if (r.status === 403 || r.status === 404) {
          enviados.forEach(function (c) { limpar(L, c); });
          toast(r.j.erro || 'Alteração não permitida.', 'danger');
          return api('/api/componentes/' + cfg.compId + '/estado/').then(function (e) {
            if (e.ok) { linhas.forEach(function (x) { x.dados = Object.assign({}, x.dados, {versao: -1}); }); aplicarEstado(e.j); }
          });
        } else {
          toast(r.j.erro || 'Não foi possível salvar.', 'danger');   // mantém o valor digitado para correção
        }
      })
      .catch(function () { falhaRede = true; L.repetir = false; agendar(L, 6000); })
      .then(function () {
        L.ocupado = false; geracao++;
        if (L.repetir) { L.repetir = false; agendar(L, 200); }
        atualizarIndicador();
      });
    return L.promessa;
  }
  function salvarTudo() {
    var ps = [];
    linhas.forEach(function (L) { if (L.sujos.size) ps.push(salvar(L)); });
    return Promise.all(ps);
  }
  function pendentes() { var n = 0; linhas.forEach(function (L) { n += L.sujos.size; }); return n; }

  // Edição concorrente: outro usuário alterou o mesmo campo.
  var modalConc = new bootstrap.Modal('#modal-concorrencia'), concAtual = null;
  function rotuloValor(campo, v) { return campo === 'professor_id' ? (v ? (nomeDocente[v] || 'Docente inativo') : '(sem professor)') : (v || '(vazio)'); }
  function resolverConcorrencia(L, j, campos) {
    concAtual = {L: L, j: j}; L.emConcorrencia = true;
    var html = '<p>Enquanto você editava o encontro de <strong>' + esc(j.encontro.data_br) + '</strong>, ele foi alterado por <strong>' + esc(j.encontro.atualizado_por || 'outro usuário') +
      '</strong> (' + esc(j.encontro.atualizado_em) + '). Nada foi sobrescrito. Escolha qual valor deve permanecer:</p><table class="table table-sm"><thead><tr><th>Campo</th><th>Valor atual no sistema</th><th>O seu valor</th></tr></thead><tbody>';
    j.campos.forEach(function (c) {
      html += '<tr><td>' + esc(ROTULO[c]) + '</td><td>' + esc(rotuloValor(c, j.encontro[c])) + '</td><td>' + esc(rotuloValor(c, campos[c])) + '</td></tr>';
    });
    document.getElementById('mc-corpo').innerHTML = html + '</tbody></table>';
    modalConc.show();
  }
  document.getElementById('mc-manter').addEventListener('click', function () {
    var L = concAtual.L, j = concAtual.j;
    L.emConcorrencia = false;
    L.dados = j.encontro;
    j.campos.forEach(function (c) { escreverCampo(L, c, j.encontro[c]); limpar(L, c); });
    modalConc.hide(); atualizarIndicador();
    if (L.sujos.size) agendar(L, 0);
    api('/api/componentes/' + cfg.compId + '/estado/').then(function (e) { if (e.ok) aplicarEstado(e.j); });
  });
  document.getElementById('mc-meu').addEventListener('click', function () {
    var L = concAtual.L;
    L.emConcorrencia = false;
    L.dados = concAtual.j.encontro;      // passa a partir da versão atual: a substituição é consciente
    modalConc.hide(); agendar(L, 0);
  });
  document.getElementById('modal-concorrencia').addEventListener('hidden.bs.modal', function () {
    if (concAtual && concAtual.L && concAtual.L.emConcorrencia) {
      concAtual.L.emConcorrencia = false;
      atualizarIndicador();
    }
  });

  // ------------------------------------------------------ eventos da tabela
  function linhaDe(alvo) { var tr = alvo.closest('tr.linha-encontro'); return tr ? linhas.get(parseInt(tr.id.split('-')[1], 10)) : null; }
  corpo.addEventListener('input', function (ev) {
    var c = ev.target; if (!c.dataset || !c.dataset.campo || c.tagName === 'SELECT') return;
    var L = linhaDe(c); if (!L) return;
    if (c.tagName === 'TEXTAREA') crescer(c);
    sujar(L, c.dataset.campo);
    agendar(L, c.tagName === 'TEXTAREA' ? 1500 : 2500);
  });
  corpo.addEventListener('change', function (ev) {
    var c = ev.target; if (!c.dataset || !c.dataset.campo) return;
    var L = linhaDe(c); if (!L || (L.ts && c.dataset.campo === 'professor_id')) return;
    if (c.tagName === 'SELECT') { sujar(L, c.dataset.campo); agendar(L, 0); }
    else if (c.tagName === 'TEXTAREA' && L.sujos.has(c.dataset.campo)) agendar(L, 0);
  });
  function abrirSelect(ev) {
    var c = ev.target;
    if (c.tagName !== 'SELECT' || c.dataset.campo !== 'professor_id') return;
    var L = linhaDe(c); if (!L || L.ts) return;
    if (document.activeElement && document.activeElement !== c && document.activeElement.blur) document.activeElement.blur();
    if (ev.type === 'mousedown') {
      // Substitui o select nativo pelo dropdown pesquisável e só o abre depois
      // que o clique termina (senão o próprio clique o fecharia).
      ev.preventDefault();
      var ts = ativarSelect(L);
      document.addEventListener('mouseup', function () { setTimeout(function () { ts.focus(); ts.open(); }, 40); }, {once: true});
    } else {
      var t = ativarSelect(L); t.focus(); t.open();
    }
  }
  corpo.addEventListener('mousedown', abrirSelect);
  corpo.addEventListener('focusin', abrirSelect);
  corpo.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && ev.target.dataset && ev.target.dataset.campo && ev.target.dataset.campo !== 'professor_id') {
      var L = linhaDe(ev.target), c = ev.target.dataset.campo;
      if (L && L.sujos.has(c)) { escreverCampo(L, c, L.dados[c]); limpar(L, c); atualizarIndicador(); }
    }
  });
  var modalHist = new bootstrap.Modal('#modal-hist');
  corpo.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-acao]'); if (!b) return;
    var L = linhaDe(b); if (!L) return;
    if (b.dataset.acao === 'historico') {
      var mh = document.getElementById('mh-corpo');
      mh.innerHTML = '<div class="text-center p-3"><span class="spinner-border text-primary" role="status"><span class="visually-hidden">Carregando…</span></span></div>';
      document.getElementById('mh-tit').textContent = 'Histórico — ' + L.dados.data_br + ' ' + L.dados.inicio + '–' + L.dados.fim;
      modalHist.show();
      api('/api/encontros/' + L.dados.id + '/historico/').then(function (r) {
        if (!r.ok || !r.j.itens.length) { mh.innerHTML = '<p class="text-secondary mb-0">Nenhuma alteração registrada para este encontro.</p>'; return; }
        mh.innerHTML = '<table class="table table-sm small"><thead><tr><th>Quando</th><th>Quem</th><th>Campo</th><th>Valor anterior</th><th>Novo valor</th></tr></thead><tbody>' +
          r.j.itens.map(function (h) { return '<tr><td class="text-nowrap">' + esc(h.quando) + '</td><td>' + esc(h.usuario) + '</td><td>' + esc(h.campo) + '</td><td class="text-secondary">' + esc(h.anterior || '(vazio)') + '</td><td>' + esc(h.novo || '(vazio)') + '</td></tr>'; }).join('') + '</tbody></table>';
      });
    } else if (b.dataset.acao === 'docente') {
      api('/api/componentes/' + cfg.compId + '/encontros/', {data: L.dados.data, inicio: L.dados.inicio, fim: L.dados.fim}).then(function (r) {
        if (!r.ok) { toast(r.j.erro, 'danger'); return; }
        aplicarEstado(r.j.estado); irPara(r.j.encontro_id);
        toast('Linha adicionada para outro docente ou grupo nesta aula. Escolha o docente.', 'success');
      });
    } else if (b.dataset.acao === 'excluir') {
      if (!confirm('Remover o encontro de ' + L.dados.data_br + ' (' + L.dados.inicio + '–' + L.dados.fim + ')? O conteúdo preenchido será perdido.')) return;
      api('/api/encontros/' + L.dados.id + '/excluir/', {}).then(function (r) {
        if (r.ok) { L.sujos.clear(); aplicarEstado(r.j.estado); toast('Encontro removido.', 'success'); } else toast(r.j.erro, 'danger');
      });
    }
  });

  // ------------------------------------------------------- barra de ações
  var bSalvar = document.getElementById('btn-salvar');
  if (bSalvar) bSalvar.addEventListener('click', function () {
    bSalvar.disabled = true;
    salvarTudo().then(function () {
      bSalvar.disabled = false;
      if (pendentes() || falhaRede) { toast('Há alterações que não puderam ser salvas. Verifique os avisos.', 'danger'); return; }
      var n = estado.stats.conflitos;
      toast(n ? 'Cronograma salvo. Atenção: ' + n + ' conflito(s) de horário permanece(m) pendente(s).' : 'Cronograma salvo.', n ? 'warning' : 'success');
    });
  });
  var modalValidar = new bootstrap.Modal('#modal-validar');
  document.getElementById('btn-validar').addEventListener('click', function () {
    var b = this; b.disabled = true;
    salvarTudo().then(function () { return api('/componentes/' + cfg.compId + '/validar/', {}); }).then(function (r) {
      b.disabled = false;
      if (!r.ok) { toast(r.j.erro || 'Não foi possível validar.', 'danger'); return; }
      aplicarEstado(r.j.estado);
      var p = r.j.problemas, mv = document.getElementById('mv-corpo'), fa = document.getElementById('form-aprovar');
      fa.hidden = !(r.j.pode_aprovar && !p.length);
      if (!p.length) {
        mv.innerHTML = '<div class="alert alert-success mb-0"><i class="bi bi-check-circle-fill"></i> <strong>Cronograma válido.</strong> Todos os encontros estão preenchidos e não há conflitos docentes. ' +
          (estado.situacao !== 'RASCUNHO' ? 'Este cronograma já está aprovado.' : (r.j.pode_aprovar ? 'Você já pode aprová-lo.' : 'A aprovação cabe ao coordenador responsável.')) + '</div>';
      } else {
        var nc = p.filter(function (x) { return x.tipo === 'conflito'; }).length;
        mv.innerHTML = '<div class="alert alert-warning"><i class="bi bi-exclamation-triangle-fill"></i> <strong>' + p.length + ' pendência(s)</strong> impedem a aprovação' +
          (nc ? ' — ' + nc + ' conflito(s) docente(s)' : '') + '. O rascunho permanece salvo.</div><ul class="list-group">' +
          p.map(function (x) {
            return '<li class="list-group-item d-flex gap-2 align-items-start"><i class="bi ' + (x.tipo === 'conflito' ? 'bi-exclamation-triangle-fill text-danger' : 'bi-pencil text-secondary') + '" aria-hidden="true"></i><span class="flex-grow-1">' +
              '<span class="badge ' + (x.tipo === 'conflito' ? 'text-bg-danger' : 'text-bg-secondary') + ' me-1">' + (x.tipo === 'conflito' ? 'Conflito' : x.tipo === 'incompleto' ? 'Incompleto' : 'Estrutura') + '</span>' + esc(x.mensagem) + '</span>' +
              (x.encontro_id ? '<a class="btn btn-sm btn-outline-primary text-nowrap" href="#encontro-' + x.encontro_id + '" data-ir="' + x.encontro_id + '">Ir ao encontro</a>' : '') + '</li>';
          }).join('') + '</ul>';
      }
      modalValidar.show();
    });
  });
  document.getElementById('mv-corpo').addEventListener('click', function (ev) {
    var a = ev.target.closest('[data-ir]'); if (!a) return;
    ev.preventDefault(); modalValidar.hide(); irPara(parseInt(a.dataset.ir, 10));
  });
  var fNovo = document.getElementById('form-novo');
  if (fNovo) fNovo.addEventListener('submit', function (ev) {
    ev.preventDefault();
    var erro = document.getElementById('n-erro'); erro.textContent = '';
    api('/api/componentes/' + cfg.compId + '/encontros/', {data: document.getElementById('n-data').value, inicio: document.getElementById('n-ini').value, fim: document.getElementById('n-fim').value})
      .then(function (r) {
        if (!r.ok) { erro.textContent = r.j.erro; return; }
        bootstrap.Modal.getInstance('#modal-novo').hide(); fNovo.reset();
        aplicarEstado(r.j.estado); irPara(r.j.encontro_id); toast('Encontro excepcional inserido.', 'success');
      });
  });
  // Antes de aprovar/publicar/exportar, garante que nada ficou por salvar.
  document.querySelectorAll('#exp-docx, #exp-pdf').forEach(function (a) {
    a.addEventListener('click', function (ev) {
      if (!pendentes()) return;
      ev.preventDefault(); salvarTudo().then(function () { location.href = a.href; });
    });
  });

  // ---------------------------------------------------------------- navegação
  function irPara(id) {
    var L = linhas.get(id); if (!L) return;
    if (L.tr.hidden) limparFiltros();
    L.tr.scrollIntoView({block: 'center', behavior: 'smooth'});
    L.tr.classList.remove('destaque'); void L.tr.offsetWidth; L.tr.classList.add('destaque');
    var foco = L.tr.querySelector('[data-campo="conteudo"]') || L.tr;
    if (foco.focus) { foco.setAttribute('tabindex', foco.getAttribute('tabindex') || '-1'); foco.focus({preventScroll: true}); }
  }
  function irParaHash() { var m = location.hash.match(/^#encontro-(\d+)$/); if (m) setTimeout(function () { irPara(parseInt(m[1], 10)); }, 150); }
  window.addEventListener('hashchange', irParaHash);
  window.addEventListener('beforeunload', function (ev) { if (pendentes()) { ev.preventDefault(); ev.returnValue = ''; } });

  // Atualização periódica: reflete alterações de outros usuários e conflitos
  // criados ou resolvidos em outros componentes.
  setInterval(function () {
    if (document.hidden || document.querySelector('.modal.show')) return;
    var ocupado = false; linhas.forEach(function (L) { if (L.ocupado) ocupado = true; });
    if (ocupado) return;
    var g = geracao;
    api('/api/componentes/' + cfg.compId + '/estado/').then(function (r) {
      if (r.ok && g === geracao) { falhaRede = false; aplicarEstado(r.j); atualizarIndicador(); }   // ignora resposta anterior a um salvamento
    }).catch(function () {});
  }, 20000);

  aplicarEstado(estado);
  atualizarIndicador();
  irParaHash();
})();
