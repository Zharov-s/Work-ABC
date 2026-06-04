/**
 * filters.js — client-side state and API wiring for the filter panel.
 * Works with templates/partials/filters_panel.html.
 * Exposes: fpInit(), fpGetRequest(), fpReset(), fpApply()
 */

var FP = {
  mode:      'main',
  okvedInc:  [],   // selected codes/sections to include
  okvedExc:  [],   // selected codes/sections to exclude
  regions:   [],
  industries:[],
  _debTimer: null,
  _tree:     [],   // full okved tree from API
  onApply:   null, // callback(filterRequest)
};

// ── Bootstrap ─────────────────────────────────────────────────────────────────
function fpInit(onApplyCb) {
  FP.onApply = onApplyCb || null;
  Promise.all([
    fetch('/api/filters/okved-tree').then(r=>r.json()),
    fetch('/api/filters/industry-groups').then(r=>r.json()),
    fetch('/api/filters/regions').then(r=>r.json()),
  ]).then(function(res) {
    FP._tree = res[0];
    _renderOkvedTree(res[0]);
    _renderChips('fp-industry-list', res[1], 'name', FP.industries, fpApply);
    _renderChips('fp-region-list',   res[2], 'region', FP.regions, fpApply);
    fpUpdateCount();
  });
}

// ── Mode toggle ───────────────────────────────────────────────────────────────
function fpSetMode(m) {
  FP.mode = m;
  document.getElementById('fp-mode-main').classList.toggle('active', m==='main');
  document.getElementById('fp-mode-all').classList.toggle('active',  m==='all');
  fpApply();
}

// ── OKVED tree render ─────────────────────────────────────────────────────────
function _renderOkvedTree(tree, filter) {
  var el = document.getElementById('fp-okved-tree');
  if (!el) return;
  var html = '';
  tree.forEach(function(sect) {
    var sHide = filter && !_matchesFilter(sect, filter);
    if (sHide) return;
    var sActive = FP.okvedInc.indexOf(sect.section) !== -1;
    html += '<div class="fp-tree-section">';
    html += '<div class="fp-tree-row fp-tree-section-row" onclick="fpToggleOkved(\''+sect.section+'\')">'
          + '<span class="fp-tree-arrow" data-sec="'+sect.section+'">▶</span>'
          + '<span class="fp-tree-check '+(sActive?'checked':'')+'"></span>'
          + '<span class="fp-tree-label"><b>'+sect.section+'</b> — '+_esc(sect.name)+'</span>'
          + '<span class="fp-tree-count">'+sect.company_count+'</span>'
          + '</div>';
    html += '<div class="fp-tree-children" id="fp-sec-'+sect.section+'" style="display:none">';
    (sect.classes||[]).forEach(function(cls) {
      var cActive = FP.okvedInc.indexOf(cls.code) !== -1;
      var cHide = filter && !_matchesFilter(cls, filter);
      if (cHide) return;
      html += '<div class="fp-tree-class">';
      html += '<div class="fp-tree-row" onclick="fpToggleOkved(\''+cls.code+'\')">'
            + '<span class="fp-tree-arrow" data-cls="'+cls.code+'">▶</span>'
            + '<span class="fp-tree-check '+(cActive?'checked':'')+'"></span>'
            + '<span class="fp-tree-label">'+cls.code+' — '+_esc(cls.name)+'</span>'
            + '<span class="fp-tree-count">'+cls.company_count+'</span>'
            + '</div>';
      html += '<div class="fp-tree-children" id="fp-cls-'+cls.code+'" style="display:none">';
      (cls.codes||[]).forEach(function(code) {
        var dActive = FP.okvedInc.indexOf(code.code) !== -1;
        var dHide = filter && !_matchesFilter(code, filter);
        if (dHide) return;
        html += '<div class="fp-tree-row fp-tree-leaf" onclick="fpToggleOkved(\''+code.code+'\')">'
              + '<span class="fp-tree-check '+(dActive?'checked':'')+'"></span>'
              + '<span class="fp-tree-label">'+code.code+' — '+_esc(code.name)+'</span>'
              + '<span class="fp-tree-count">'+code.company_count+'</span>'
              + '</div>';
      });
      html += '</div></div>';
    });
    html += '</div></div>';
  });
  el.innerHTML = html || '<div class="fp-empty">Ничего не найдено</div>';
}

function fpFilterOkvedTree(q) {
  _renderOkvedTree(FP._tree, q.trim().toLowerCase());
  if (q.trim()) {
    document.querySelectorAll('.fp-tree-children').forEach(function(el){ el.style.display='block'; });
  }
}

function _matchesFilter(node, q) {
  if (!q) return true;
  var text = ((node.code||'') + ' ' + (node.name||node.section||'')).toLowerCase();
  return text.indexOf(q) !== -1;
}

// ── OKVED selection ───────────────────────────────────────────────────────────
function fpToggleOkved(code) {
  var idx = FP.okvedInc.indexOf(code);
  if (idx === -1) {
    FP.okvedInc.push(code);
  } else {
    FP.okvedInc.splice(idx, 1);
  }
  // Re-render to update check marks
  _renderOkvedTree(FP._tree);
  fpApply();
}

// ── Chip lists ────────────────────────────────────────────────────────────────
function _renderChips(elId, items, labelKey, selectedArr, onChange) {
  var el = document.getElementById(elId);
  if (!el) return;
  var html = '';
  items.forEach(function(item) {
    var val   = item[labelKey];
    var cnt   = item.company_count || '';
    var isOn  = selectedArr.indexOf(val) !== -1;
    html += '<button class="fp-chip'+(isOn?' active':'')+'" onclick="fpToggleChip(\''+elId+'\',\''+_esc(val)+'\',event)">'
          + _esc(val) + (cnt ? ' <span class="fp-chip-cnt">'+cnt+'</span>' : '')
          + '</button>';
  });
  el.innerHTML = html || '<span class="fp-empty">—</span>';
}

function fpToggleChip(elId, val, evt) {
  var arr = elId.indexOf('industry') !== -1 ? FP.industries : FP.regions;
  var idx = arr.indexOf(val);
  if (idx === -1) arr.push(val); else arr.splice(idx, 1);
  evt.target.closest('button').classList.toggle('active', arr.indexOf(val) !== -1);
  fpApply();
}

// ── Count preview ─────────────────────────────────────────────────────────────
function fpUpdateCount() {
  var req = fpGetRequest();
  fetch('/api/filters/count-preview', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(req)
  }).then(function(r){ return r.json(); })
    .then(function(d) {
      var el = document.getElementById('fp-count');
      if (el) el.textContent = 'Найдено: ' + d.total + ' компаний · ' + d.with_email + ' с email';
    }).catch(function(){});
}

// ── Apply / Debounce ──────────────────────────────────────────────────────────
function fpApply() {
  fpUpdateCount();
  if (FP.onApply) FP.onApply(fpGetRequest());
}

function fpDebounce() {
  clearTimeout(FP._debTimer);
  FP._debTimer = setTimeout(fpApply, 350);
}

// ── Get current filter request ────────────────────────────────────────────────
function fpGetRequest() {
  return {
    q:              (document.getElementById('fp-q')||{}).value || '',
    okved_include:  FP.okvedInc.slice(),
    okved_exclude:  FP.okvedExc.slice(),
    okved_mode:     FP.mode,
    regions:        FP.regions.slice(),
    industry_groups:FP.industries.slice(),
    has_email:      !!(document.getElementById('fp-has-email')||{}).checked,
    has_phone:      !!(document.getElementById('fp-has-phone')||{}).checked,
    has_website:    !!(document.getElementById('fp-has-website')||{}).checked,
  };
}

// ── Reset ─────────────────────────────────────────────────────────────────────
function fpReset() {
  FP.okvedInc = []; FP.okvedExc = []; FP.regions = []; FP.industries = [];
  FP.mode = 'main';
  var q = document.getElementById('fp-q'); if (q) q.value = '';
  ['fp-has-email','fp-has-phone','fp-has-website'].forEach(function(id){
    var el = document.getElementById(id); if (el) el.checked = false;
  });
  document.querySelectorAll('.fp-chip.active').forEach(function(el){ el.classList.remove('active'); });
  document.querySelectorAll('.fp-tree-check.checked').forEach(function(el){ el.classList.remove('checked'); });
  document.getElementById('fp-mode-main').classList.add('active');
  document.getElementById('fp-mode-all').classList.remove('active');
  fpApply();
}

// ── Save preset ───────────────────────────────────────────────────────────────
function fpSavePreset() {
  var name = prompt('Название пресета:');
  if (!name) return;
  fetch('/api/filters/save-preset', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({name: name, filter: fpGetRequest()})
  }).then(function(r){ return r.json(); })
    .then(function(d){ if (d.ok) alert('Пресет «'+name+'» сохранён'); });
}

function _esc(s) {
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
