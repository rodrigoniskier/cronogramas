/* CronoMed UNIPÊ — editor de cronograma: células clicáveis, lista dropdown
   de docentes com caixas de seleção (checkboxes), salvamento automático,
   controle de edição concorrente e alertas de conflito. */
(function () {
  'use strict';
  var cfg = JSON.parse(document.getElementById('cfg').textContent);
  var docentes = JSON.parse(document.getElementById('docentes').textContent);
  var estado = JSON.parse(document.getElementById('estado').textContent);
  var nomeDocente = {};
  docentes.forEach(function (d) { nomeDocente[d.id] = d.nome; });
  var corpo = document.getElementById('corpo');
  var linhas = new Map();           // id -> {dados, tr, sujos:Set, timer, ocupado}
  var editavel = estado.pode_editar;
  var agenda = editavel && cfg.gerencia;
  var CAMPOS_TEXTO = ['conteudo', 'tipo', 'atividade', 'recursos', 'grupos', 'ch', 'local', 'observacoes'];
  var TIPOS = [['', ''], ['T', 'T'], ['P', 'P'], ['T/P', 'T/P'], ['-', '-']];
  var LIMITE = {grupos: 300, ch: 10, local: 120};
  var NCOL = 12;
  var ROTULO = {
    conteudo: 'Conteúdo', tipo: 'Tipo', atividade: 'Atividades', recursos: 'Recursos',
    grupos: 'Grupos', ch: 'CH', local: 'Local', observacoes: 'Observações',
    professor_id: 'Professor(a)', professor_ids: 'Docente(s)',
    data: 'Data', inicio: 'Início', fim: 'Término', horario: 'Horário'
  };
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
  function mesmoValor(a, b) {
    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return false;
      for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
      return true;
    }
    return a === b;
  }
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

  function rotuloLinha(enc) {
    if (enc.data_br) return enc.data_br;
    if (enc.reposicao) return 'Reposição ' + (enc.ordem || '');
    return 'Aula ' + (enc.ordem || enc.id);
  }

  // ------------------------------------------------ dropdown checkbox docentes
  function atualizarResumoDocentes(L) {
    var btn = L.tr.querySelector('.btn-dropdown-docentes');
    if (!btn) return;
    var ids = lerCampo(L, 'professor_ids');
    var nomes = ids.map(function (id) { return nomeDocente[id] || 'Docente #' + id; });
    var span = btn.querySelector('.docentes-resumo');
    span.textContent = nomes.join(', ');
    btn.classList.toggle('tem-docente', nomes.length > 0);
  }

  function criarCelulaDocentes(L) {
    var enc = L.dados;
    var td = el('td', {class: 'celula-td-docente'});
    if (!editavel) {
      td.appendChild(el('div', {class: 'leitura', text: enc.professor_nome}));
      return td;
    }
    var selecionados = new Set((enc.professor_ids || (enc.professor_id ? [enc.professor_id] : [])).map(function (x) { return parseInt(x, 10); }));
    var wrap = el('div', {class: 'dropdown-docentes', 'data-campo': 'professor_ids'});
    var btn = el('button', {
      type: 'button',
      class: 'celula btn-dropdown-docentes' + (selecionados.size ? ' tem-docente' : ''),
      'aria-expanded': 'false',
      'aria-label': 'Docentes — ' + rotuloLinha(enc)
    }, [
      el('span', {class: 'docentes-resumo', text: enc.professor_nome || ''}),
      el('i', {class: 'bi bi-chevron-down seta-dropdown', 'aria-hidden': 'true'})
    ]);
    var menu = el('div', {class: 'menu-dropdown-docentes', hidden: 'hidden'});
    var busca = el('input', {
      type: 'search',
      class: 'form-control form-control-sm filtro-docentes-menu mb-1',
      placeholder: 'Pesquisar docente…',
      'aria-label': 'Pesquisar docente — ' + rotuloLinha(enc)
    });
    var lista = el('div', {class: 'lista-docentes-check'});
    docentes.forEach(function (d) {
      var chk = el('input', {
        type: 'checkbox',
        class: 'form-check-input me-2 check-docente',
        value: String(d.id),
        'data-docente-id': String(d.id)
      });
      if (selecionados.has(d.id)) chk.checked = true;
      var item = el('label', {class: 'item-docente-check', 'data-nome': d.nome.toLowerCase()}, [
        chk,
        el('span', {class: 'nome-docente-check', text: d.nome})
      ]);
      lista.appendChild(item);
    });
    // Preserva docente inativo caso exista no encontro
    selecionados.forEach(function (id) {
      if (!nomeDocente[id]) {
        var chk = el('input', {
          type: 'checkbox',
          class: 'form-check-input me-2 check-docente',
          value: String(id),
          'data-docente-id': String(id)
        });
        chk.checked = true;
        lista.appendChild(el('label', {class: 'item-docente-check', 'data-nome': 'inativo'}, [
          chk,
          el('span', {class: 'nome-docente-check', text: 'Docente inativo'})
        ]));
      }
    });
    menu.appendChild(busca);
    menu.appendChild(lista);
    wrap.appendChild(btn);
    wrap.appendChild(menu);
    td.appendChild(wrap);
    return td;
  }

  function fecharDropdownsDocentes(excetoWrap) {
    corpo.querySelectorAll('.dropdown-docentes').forEach(function (w) {
      if (w === excetoWrap) return;
      var m = w.querySelector('.menu-dropdown-docentes');
      var b = w.querySelector('.btn-dropdown-docentes');
      if (m && !m.hidden) {
        m.hidden = true;
        if (b) b.setAttribute('aria-expanded', 'false');
        var L = linhaDe(w);
        if (L && L.sujos.has('professor_ids')) agendar(L, 0);
      }
    });
  }

  // ------------------------------------------------------------ renderização
  function lerCampo(L, campo) {
    if (campo === 'professor_ids') {
      var ids = [];
      L.tr.querySelectorAll('input.check-docente:checked').forEach(function (cb) {
        ids.push(parseInt(cb.value, 10));
      });
      return ids;
    }
    var elCampo = L.tr.querySelector('[data-campo="' + campo + '"]');
    return elCampo ? elCampo.value : '';
  }

  function escreverCampo(L, campo, valor) {
    if (campo === 'professor_ids') {
      var conj = new Set((valor || []).map(function (x) { return parseInt(x, 10); }));
      L.tr.querySelectorAll('input.check-docente').forEach(function (cb) {
        cb.checked = conj.has(parseInt(cb.value, 10));
      });
      atualizarResumoDocentes(L);
      return;
    }
    var c = L.tr.querySelector('[data-campo="' + campo + '"]');
    if (!c) return;
    if (campo === 'data') {
      c.value = (valor && L.dados.data === valor && L.dados.data_curta) ? L.dados.data_curta : (valor || '');
      return;
    }
    if (campo === 'horario') {
      c.value = L.dados.horario_modelo || valor || '';
      return;
    }
    c.value = valor == null ? '' : valor;
    if (c.tagName === 'TEXTAREA') crescer(c);
  }

  function celulaTexto(L, campo) {
    var td = el('td');
    var rot = rotuloLinha(L.dados);
    if (!editavel) { td.appendChild(el('div', {class: 'leitura', text: L.dados[campo]})); return td; }
    if (campo === 'tipo') {
      var st = el('select', {class: 'celula celula-tipo', 'data-campo': 'tipo', 'aria-label': 'Tipo — ' + rot});
      TIPOS.forEach(function (o) { st.appendChild(el('option', {value: o[0], text: o[1]})); });
      st.value = L.dados.tipo; td.appendChild(st); return td;
    }
    var t = el('textarea', {class: 'celula', rows: 1, 'data-campo': campo, 'aria-label': ROTULO[campo] + ' — ' + rot});
    t.value = L.dados[campo];
    if (LIMITE[campo]) t.maxLength = LIMITE[campo];
    td.appendChild(t);
    return td;
  }

  function criarLinha(enc, anterior) {
    var L = {dados: enc, sujos: new Set(), timer: null, ocupado: false};
    var tr = el('tr', {class: 'linha-encontro' + (enc.reposicao ? ' linha-reposicao' : ''), id: 'encontro-' + enc.id});
    L.tr = tr;
    var rot = rotuloLinha(enc);
    var tdData = el('td', {class: 'fixo celula-td-agenda'});
    var tdHora = el('td', {class: 'fixo celula-td-agenda'});
    var podeEditarData = editavel && (agenda || !enc.data);
    var podeEditarHora = editavel && (agenda || !enc.inicio);

    if (podeEditarData) {
      var d = el('input', {
        type: 'text',
        class: 'celula celula-agenda-texto text-center',
        'data-campo': 'data',
        'aria-label': 'Data — ' + rot
      });
      d.value = enc.data_curta || enc.data_br || '';
      tdData.appendChild(d);
    } else {
      tdData.appendChild(el('span', {'data-txt': 'data', text: enc.data_curta || enc.data_br}));
    }
    tdData.appendChild(el('div', {class: 'dia-semana', 'data-dia': '1', text: enc.dia}));
    tdData.appendChild(el('div', {'data-selos': '1'}));

    if (podeEditarHora) {
      var h = el('input', {
        type: 'text',
        class: 'celula celula-agenda-texto text-center',
        'data-campo': 'horario',
        'aria-label': 'Horário — ' + rot
      });
      h.value = enc.horario_modelo || '';
      tdHora.appendChild(h);
    } else {
      tdHora.appendChild(el('span', {'data-txt': 'hora', text: enc.horario_modelo}));
    }

    tr.appendChild(tdData);
    tr.appendChild(tdHora);
    ['conteudo', 'tipo', 'atividade', 'recursos', 'grupos'].forEach(function (c) { tr.appendChild(celulaTexto(L, c)); });
    tr.appendChild(criarCelulaDocentes(L));
    ['ch', 'local', 'observacoes'].forEach(function (c) { tr.appendChild(celulaTexto(L, c)); });
    var tdAcoes = el('td', {class: 'acoes-linha'});
    tdAcoes.appendChild(el('button', {type: 'button', class: 'btn btn-sm btn-outline-secondary', 'data-acao': 'historico', 'aria-label': 'Histórico do encontro de ' + rot, html: '<i class="bi bi-clock-history"></i>'}));
    if (agenda) tdAcoes.appendChild(el('button', {type: 'button', class: 'btn btn-sm btn-outline-danger ms-1', 'data-acao': 'excluir', 'aria-label': 'Remover encontro de ' + rot, html: '<i class="bi bi-trash"></i>'}));
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
    var t = tr.querySelector('[data-txt="data"]'); if (t) t.textContent = enc.data_curta || enc.data_br;
    t = tr.querySelector('[data-txt="hora"]'); if (t) t.textContent = enc.horario_modelo;
    var selos = tr.querySelector('[data-selos]');
    selos.innerHTML = (conf.length ? '<span class="selo selo-conflito"><i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i> Conflito</span> ' : '');
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
      var inseriuSecaoRep = false;
      novo.encontros.forEach(function (enc) {
        if (enc.reposicao && !inseriuSecaoRep) {
          inseriuSecaoRep = true;
          frag.appendChild(el('tr', {class: 'linha-secao-reposicao'}, [
            el('td', {colspan: NCOL, class: 'celula-secao-reposicao', text: 'Reposições - Ajustar com a turma'})
          ]));
        }
        var L = criarLinha(enc, antigas.get(enc.id));
        linhas.set(enc.id, L); frag.appendChild(L.tr);
      });
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
          CAMPOS_TEXTO.concat(['professor_ids', 'data', 'horario']).forEach(function (c) {
            var campo = L.tr.querySelector('[data-campo="' + c + '"]');
            if (!campo) return;
            var menuAberto = c === 'professor_ids' && !campo.querySelector('.menu-dropdown-docentes').hidden;
            var emUso = document.activeElement === campo || menuAberto;
            if (!L.sujos.has(c) && !emUso && !mesmoValor(lerCampo(L, c), enc[c])) {
              escreverCampo(L, c, enc[c]);
            }
          });
        } else if (mudou) {
          var ro = L.tr.querySelectorAll('.leitura');
          [enc.conteudo, enc.tipo, enc.atividade, enc.recursos, enc.grupos, enc.professor_nome, enc.ch, enc.local, enc.observacoes].forEach(function (v, i) { if (ro[i]) ro[i].textContent = v; });
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
        el('td', {class: 'fixo text-center', text: f.data_br.slice(0, 5)}), el('td', {class: 'fixo text-center', text: f.horario}),
        el('td', {html: '<i class="bi bi-calendar-x" aria-hidden="true"></i> <strong>' + esc(f.descricao) + '</strong>'}),
        el('td', {class: 'text-center', text: '-'}), el('td', {colspan: 4, class: 'text-secondary', text: 'Data bloqueada no calendário do semestre — sem aula.'}),
        el('td', {class: 'text-center', text: f.ch}), el('td', {colspan: 3})]);
      var depois = null;
      corpo.querySelectorAll('tr.linha-encontro').forEach(function (t) {
        var L = linhas.get(parseInt(t.id.split('-')[1], 10));
        if (!depois && L && !L.dados.reposicao && L.dados.data && (L.dados.data > f.data || (L.dados.data === f.data && L.dados.inicio >= f.inicio))) depois = t;
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
    estado.encontros.forEach(function (e) {
      (e.professor_ids || (e.professor_id ? [e.professor_id] : [])).forEach(function (pid) {
        if (pid) vistos[pid] = nomeDocente[pid] || e.professor_nome;
      });
    });
    while (fDoc.options.length > 2) fDoc.remove(2);
    Object.keys(vistos).sort(function (a, b) { return vistos[a].localeCompare(vistos[b]); })
      .forEach(function (id) { fDoc.appendChild(el('option', {value: id, text: vistos[id]})); });
    fDoc.value = atual; if (fDoc.selectedIndex < 0) fDoc.value = '';
  }
  function filtrar() {
    var n = 0;
    linhas.forEach(function (L) {
      var e = L.dados, conf = !!estado.conflitos[e.id], ok = true;
      var pids = e.professor_ids || (e.professor_id ? [e.professor_id] : []);
      if (fDoc.value === '0') ok = pids.length === 0;
      else if (fDoc.value) ok = pids.indexOf(parseInt(fDoc.value, 10)) !== -1;
      if (ok && fDe.value) ok = e.data && e.data >= fDe.value;
      if (ok && fAte.value) ok = e.data && e.data <= fAte.value;
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
    if (L.emConcorrencia) return Promise.resolve();
    if (L.ocupado) { L.repetir = true; return L.promessa; }
    var campos = {}, base = {}, enviados = Array.from(L.sujos);
    enviados.forEach(function (c) { campos[c] = lerCampo(L, c); base[c] = L.dados[c]; });
    L.ocupado = true; geracao++; atualizarIndicador();
    L.promessa = api('/api/encontros/' + L.dados.id + '/', {campos: campos, base: base, versao: L.dados.versao})
      .then(function (r) {
        falhaRede = false;
        if (r.ok) {
          enviados.forEach(function (c) { if (mesmoValor(lerCampo(L, c), campos[c])) limpar(L, c); else L.repetir = true; });
          L.dados = Object.assign({}, r.j.encontro, {versao: -1});
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
          toast(r.j.erro || 'Não foi possível salvar.', 'danger');
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
  function rotuloValor(campo, v) {
    if (campo === 'professor_id') return v ? (nomeDocente[v] || 'Docente inativo') : '(sem professor)';
    if (campo === 'professor_ids') {
      var arr = Array.isArray(v) ? v : [];
      return arr.length ? arr.map(function (id) { return nomeDocente[id] || 'Docente'; }).join(', ') : '(sem professor)';
    }
    return v || '(vazio)';
  }
  function resolverConcorrencia(L, j, campos) {
    concAtual = {L: L, j: j}; L.emConcorrencia = true;
    var html = '<p>Enquanto você editava o encontro de <strong>' + esc(rotuloLinha(j.encontro)) + '</strong>, ele foi alterado por <strong>' + esc(j.encontro.atualizado_por || 'outro usuário') +
      '</strong> (' + esc(j.encontro.atualizado_em) + '). Nada foi sobrescrito. Escolha qual valor deve permanecer:</p><table class="table table-sm"><thead><tr><th>Campo</th><th>Valor atual no sistema</th><th>O seu valor</th></tr></thead><tbody>';
    j.campos.forEach(function (c) {
      html += '<tr><td>' + esc(ROTULO[c] || c) + '</td><td>' + esc(rotuloValor(c, j.encontro[c])) + '</td><td>' + esc(rotuloValor(c, campos[c])) + '</td></tr>';
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
    L.dados = concAtual.j.encontro;
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
    var c = ev.target;
    if (c.classList.contains('filtro-docentes-menu')) {
      var termo = c.value.trim().toLowerCase();
      var menu = c.closest('.menu-dropdown-docentes');
      menu.querySelectorAll('.item-docente-check').forEach(function (lbl) {
        lbl.hidden = !!(termo && lbl.dataset.nome.indexOf(termo) === -1);
      });
      return;
    }
    if (!c.dataset || !c.dataset.campo || c.tagName === 'SELECT') return;
    var L = linhaDe(c); if (!L) return;
    if (c.tagName === 'TEXTAREA') crescer(c);
    sujar(L, c.dataset.campo);
    agendar(L, c.tagName === 'TEXTAREA' ? 1500 : 1800);
  });

  corpo.addEventListener('change', function (ev) {
    var c = ev.target;
    if (c.classList.contains('check-docente')) {
      var L = linhaDe(c); if (!L) return;
      atualizarResumoDocentes(L);
      sujar(L, 'professor_ids');
      agendar(L, 350);
      return;
    }
    if (!c.dataset || !c.dataset.campo) return;
    var L2 = linhaDe(c); if (!L2) return;
    if (c.tagName === 'SELECT') { sujar(L2, c.dataset.campo); agendar(L2, 0); }
    else if (L2.sujos.has(c.dataset.campo)) agendar(L2, 0);
  });

  corpo.addEventListener('click', function (ev) {
    var btnDoc = ev.target.closest('.btn-dropdown-docentes');
    if (btnDoc) {
      var wrap = btnDoc.closest('.dropdown-docentes');
      var menu = wrap.querySelector('.menu-dropdown-docentes');
      var abrir = menu.hidden;
      fecharDropdownsDocentes(wrap);
      menu.hidden = !abrir;
      btnDoc.setAttribute('aria-expanded', abrir ? 'true' : 'false');
      if (abrir) {
        var inp = menu.querySelector('.filtro-docentes-menu');
        if (inp) { inp.value = ''; menu.querySelectorAll('.item-docente-check').forEach(function (l) { l.hidden = false; }); inp.focus(); }
      } else {
        var L = linhaDe(wrap);
        if (L && L.sujos.has('professor_ids')) agendar(L, 0);
      }
      return;
    }
    var b = ev.target.closest('[data-acao]'); if (!b) return;
    var L2 = linhaDe(b); if (!L2) return;
    if (b.dataset.acao === 'historico') {
      var mh = document.getElementById('mh-corpo');
      mh.innerHTML = '<div class="text-center p-3"><span class="spinner-border text-primary" role="status"><span class="visually-hidden">Carregando…</span></span></div>';
      document.getElementById('mh-tit').textContent = 'Histórico — ' + rotuloLinha(L2.dados) + (L2.dados.horario_modelo ? ' (' + L2.dados.horario_modelo + ')' : '');
      modalHist.show();
      api('/api/encontros/' + L2.dados.id + '/historico/').then(function (r) {
        if (!r.ok || !r.j.itens.length) { mh.innerHTML = '<p class="text-secondary mb-0">Nenhuma alteração registrada para este encontro.</p>'; return; }
        mh.innerHTML = '<table class="table table-sm small"><thead><tr><th>Quando</th><th>Quem</th><th>Campo</th><th>Valor anterior</th><th>Novo valor</th></tr></thead><tbody>' +
          r.j.itens.map(function (h) { return '<tr><td class="text-nowrap">' + esc(h.quando) + '</td><td>' + esc(h.usuario) + '</td><td>' + esc(h.campo) + '</td><td class="text-secondary">' + esc(h.anterior || '(vazio)') + '</td><td>' + esc(h.novo || '(vazio)') + '</td></tr>'; }).join('') + '</tbody></table>';
      });
    } else if (b.dataset.acao === 'excluir') {
      if (!confirm('Remover a linha de ' + rotuloLinha(L2.dados) + '? O conteúdo preenchido será perdido.')) return;
      api('/api/encontros/' + L2.dados.id + '/excluir/', {}).then(function (r) {
        if (r.ok) { L2.sujos.clear(); aplicarEstado(r.j.estado); toast('Linha removida.', 'success'); } else toast(r.j.erro, 'danger');
      });
    }
  });

  document.addEventListener('click', function (ev) {
    if (!ev.target.closest('.dropdown-docentes')) fecharDropdownsDocentes(null);
  });

  corpo.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') {
      var wrap = ev.target.closest('.dropdown-docentes');
      if (wrap) {
        fecharDropdownsDocentes(null);
        var btn = wrap.querySelector('.btn-dropdown-docentes');
        if (btn) btn.focus();
        return;
      }
      if (ev.target.dataset && ev.target.dataset.campo) {
        var L = linhaDe(ev.target), c = ev.target.dataset.campo;
        if (L && L.sujos.has(c)) { escreverCampo(L, c, L.dados[c]); limpar(L, c); atualizarIndicador(); }
      }
    }
  });

  var modalHist = new bootstrap.Modal('#modal-hist');

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

  setInterval(function () {
    if (document.hidden || document.querySelector('.modal.show')) return;
    var ocupado = false; linhas.forEach(function (L) { if (L.ocupado) ocupado = true; });
    if (ocupado) return;
    var g = geracao;
    api('/api/componentes/' + cfg.compId + '/estado/').then(function (r) {
      if (r.ok && g === geracao) { falhaRede = false; aplicarEstado(r.j); atualizarIndicador(); }
    }).catch(function () {});
  }, 20000);

  aplicarEstado(estado);
  atualizarIndicador();
  irParaHash();
})();
