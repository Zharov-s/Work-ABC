/**
 * companyCard.js — centered modal with blur backdrop, 5 tabs, edit/save.
 * Design tokens from main.css via CSS variables.
 */
(function() {
  var _editing = false;
  var _data = null;
  var _tab = 'overview';

  /* ── Open / Close ──────────────────────────────────────────── */
  window.openCompanyCard = function(companyId) {
    _tab = 'overview'; _editing = false; _data = null;
    var bd = document.getElementById('cc-backdrop');
    bd.classList.add('open');
    document.body.style.overflow = 'hidden';
    _showSkeleton();
    _load(companyId);
    var u = new URL(window.location);
    u.searchParams.set('company_id', companyId);
    history.replaceState(null, '', u);
  };

  window._ccClose = function() {
    var bd = document.getElementById('cc-backdrop');
    bd.classList.remove('open');
    document.body.style.overflow = '';
    _editing = false;
    var u = new URL(window.location);
    u.searchParams.delete('company_id');
    history.replaceState(null, '', u);
  };

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && document.getElementById('cc-backdrop').classList.contains('open')) {
      window._ccClose();
    }
  });

  /* ── Load ──────────────────────────────────────────────────── */
  function _load(cid) {
    fetch('/api/companies/' + cid + '/card', {credentials:'same-origin'})
      .then(function(r) { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
      .then(function(d) { _data = d; _render(); })
      .catch(function(e) {
        document.getElementById('cc-body').innerHTML =
          '<div class="cc-empty">⚠ Ошибка загрузки: '+_esc(e.message)+'<br>'
          +'<button class="cc-btn" onclick="openCompanyCard(\''+cid+'\')" style="margin-top:12px">↺ Повторить</button></div>';
      });
  }

  /* ── Skeleton ──────────────────────────────────────────────── */
  function _showSkeleton() {
    var m = document.getElementById('cc-modal');
    m.querySelector('.cc-head-top').innerHTML =
      '<div class="cc-sk-line" style="width:200px;height:20px;border-radius:6px"></div>'
      +'<button class="cc-close" onclick="_ccClose()">✕</button>';
    m.querySelector('.cc-meta').innerHTML = '';
    m.querySelector('.cc-warnings').innerHTML = '';
    m.querySelector('.cc-actions').innerHTML = '';
    m.querySelector('.cc-tabs').innerHTML = '';
    document.getElementById('cc-body').innerHTML =
      '<div>'
      +'<div class="cc-sk-line" style="width:55%"></div>'
      +'<div class="cc-sk-line" style="width:38%"></div>'
      +'<div class="cc-sk-line" style="width:70%;margin-top:16px"></div>'
      +'<div class="cc-sk-line" style="width:45%"></div>'
      +'<div class="cc-sk-line" style="width:60%"></div>'
      +'</div>';
    document.getElementById('cc-save-bar').className = 'cc-save-bar';
  }

  /* ── Render ────────────────────────────────────────────────── */
  function _render() {
    if (!_data) return;
    var c = _data.company;
    var m = document.getElementById('cc-modal');

    // Status badge
    var stMap = {
      verified:     {cls:'cc-badge-green',  lbl:'Подтверждён'},
      likely:       {cls:'cc-badge-blue',   lbl:'Вероятно'},
      conflict:     {cls:'cc-badge-red',    lbl:'Конфликт'},
      manual_review:{cls:'cc-badge-yellow', lbl:'Требует проверки'},
      not_found:    {cls:'cc-badge-gray',   lbl:'Не найден'},
    };
    var st = stMap[c.match_status] || {cls:'cc-badge-gray', lbl:'Проверка'};

    // Head
    m.querySelector('.cc-head-top').innerHTML =
      '<div>'
      +'<div class="cc-company-name">'+_esc(c.company_name_original||'—')+'</div>'
      +(c.legal_name_found&&c.legal_name_found!==c.company_name_original
        ? '<div class="cc-company-legal">'+_esc(c.legal_name_found)+'</div>' : '')
      +'</div>'
      +'<button class="cc-close" onclick="_ccClose()">✕</button>';

    // Meta
    var metaParts = ['<span class="cc-badge '+st.cls+'">'+st.lbl+'</span>'];
    if (c.inn) metaParts.push('ИНН&nbsp;<b>'+_esc(c.inn)+'</b>'
      +'<button class="cc-ch-btn" onclick="ccCopy(\''+_esc(c.inn)+'\')">⎘</button>');
    if (c.region) metaParts.push('📍&nbsp;'+_esc(c.region)+(c.city&&c.city!==c.region?',&nbsp;'+_esc(c.city):''));
    m.querySelector('.cc-meta').innerHTML = metaParts.join('<span class="cc-meta-sep"> · </span>');

    // Warnings
    var wHtml = '';
    (_data.warnings||[]).forEach(function(w){
      var isErr = w.type==='conflict'||w.type==='bounce';
      wHtml += '<div class="cc-warn'+(isErr?' err':'')+'">⚠&thinsp;'+_esc(w.text)+'</div>';
    });
    m.querySelector('.cc-warnings').innerHTML = wHtml;

    // Action buttons
    var emails = (_data.channels||[]).filter(function(ch){ return ch.channel_type==='email'&&ch.status==='active'; });
    m.querySelector('.cc-actions').innerHTML =
      (c.website ? '<a href="'+_esc(c.website)+'" target="_blank" class="cc-btn">↗ Сайт</a>' : '')
      +(c.inn  ? '<button class="cc-btn" onclick="ccCopy(\''+_esc(c.inn)+'\')">⎘ ИНН</button>' : '')
      +(emails.length ? '<button class="cc-btn" onclick="ccCopy(\''+_esc(emails[0].value)+'\')">⎘ Email</button>' : '')
      +'<button class="cc-btn cc-btn-primary" id="cc-edit-btn" onclick="ccToggleEdit()">'
      +(_editing?'✕ Отмена':'✎ Редактировать')+'</button>';

    // Tabs
    var TABS = [
      {id:'overview',  label:'Обзор'},
      {id:'contacts',  label:'Контакты&thinsp;('+(_data.channels||[]).length+')'},
      {id:'okved',     label:'ОКВЭД'},
      {id:'campaigns', label:'Рассылки&thinsp;('+(_data.campaign_history||[]).length+')'},
      {id:'history',   label:'История'},
    ];
    m.querySelector('.cc-tabs').innerHTML = TABS.map(function(t){
      return '<button class="cc-tab'+(_tab===t.id?' active':'')+'" onclick="ccTab(\''+t.id+'\')">'+t.label+'</button>';
    }).join('');

    _renderBody();
  }

  /* ── Body ──────────────────────────────────────────────────── */
  function _renderBody() {
    var body = document.getElementById('cc-body');
    var bar  = document.getElementById('cc-save-bar');
    if (_tab==='overview')  { body.innerHTML=_overview(); bar.className='cc-save-bar'+(_editing?' visible':''); }
    if (_tab==='contacts')  { body.innerHTML=_contacts(); bar.className='cc-save-bar'; }
    if (_tab==='okved')     { body.innerHTML=_okved();    bar.className='cc-save-bar'; }
    if (_tab==='campaigns') { body.innerHTML=_campaigns();bar.className='cc-save-bar'; }
    if (_tab==='history')   { body.innerHTML=_history();  bar.className='cc-save-bar'; }
  }

  /* ── Overview ──────────────────────────────────────────────── */
  function _overview() {
    var c = _data.company;
    if (_editing) {
      return '<div class="cc-field-grid">'
        +_ef('company_name_original','Название',c.company_name_original)
        +_ef('inn','ИНН',c.inn)
        +_ef('website','Сайт',c.website)
        +_ef('region','Регион',c.region)
        +_ef('city','Город',c.city)
        +_ef('segment','Сегмент',c.segment)
        +_ef('industry_group_final','Отрасль',c.industry_group_final,false,true)
        +_ef('activity_type_final','Вид деятельности',c.activity_type_final,false,true)
        +_ef('registration_address','Адрес регистрации',c.registration_address,false,true)
        +_ef('review_comment','Комментарий',c.review_comment,true,true)
        +'</div>';
    }
    function rv(label, val, isLink) {
      if (!val) return '';
      var disp = isLink
        ? '<a href="'+_esc(val)+'" target="_blank">'+_esc(val)+'</a>'
        : _esc(val);
      return '<div class="cc-field"><div class="cc-label">'+label+'</div>'
             +'<div class="cc-value">'+disp+'</div></div>';
    }
    return '<div class="cc-field-grid">'
      +rv('Название',          c.company_name_original)
      +rv('Юр. название',      c.legal_name_found)
      +rv('ИНН',               c.inn)
      +rv('ОГРН',              c.ogrn)
      +rv('Сайт',              c.website, true)
      +rv('Регион',            c.region)
      +rv('Город',             c.city)
      +rv('Сегмент',           c.segment)
      +rv('Отрасль',           c.industry_group_final)
      +rv('Вид деятельности',  c.activity_type_final)
      +rv('Адрес регистрации', c.registration_address)
      +(c.review_comment?'<div class="cc-field cc-field-wide"><div class="cc-label">Комментарий</div><div class="cc-value">'+_esc(c.review_comment)+'</div></div>':'')
      +'</div>';
  }

  function _ef(name, label, val, ta, wide) {
    var inp = ta
      ? '<textarea class="cc-textarea" name="'+name+'">'+_esc(val||'')+'</textarea>'
      : '<input class="cc-input" type="text" name="'+name+'" value="'+_esc(val||'')+'">';
    return '<div class="cc-field'+(wide?' cc-field-wide':'')+'"><div class="cc-label">'+label+'</div>'+inp+'</div>';
  }

  /* ── Contacts ──────────────────────────────────────────────── */
  function _contacts() {
    var chans = _data.channels||[];
    var ICON = {email:'✉',mobile_phone:'📱',landline_phone:'☎',website:'🌐'};
    var LTYPE = {email:'Email',mobile_phone:'Мобильный',landline_phone:'Городской',website:'Сайт'};
    var html = chans.length
      ? '<div class="cc-ch-list">'+chans.map(function(ch){
          var st = ch.status||'active';
          return '<div class="cc-ch-row">'
            +'<span class="cc-ch-icon">'+(ICON[ch.channel_type]||'📌')+'</span>'
            +'<span class="cc-ch-val">'+_esc(ch.value)+'</span>'
            +'<span class="cc-ch-type">'+(LTYPE[ch.channel_type]||ch.channel_type)+'</span>'
            +'<div class="cc-ch-status '+st+'" title="'+st+'"></div>'
            +'<div class="cc-ch-btns">'
            +'<button class="cc-ch-btn" onclick="ccCopy(\''+_esc(ch.value)+'\')">⎘</button>'
            +(st==='active'
              ?'<button class="cc-ch-btn" onclick="ccSetChSt('+ch.id+',\'inactive\')" title="Пометить неактуальным">✕</button>'
              :'<button class="cc-ch-btn" onclick="ccSetChSt('+ch.id+',\'active\')" title="Восстановить">✓</button>')
            +'</div></div>';
        }).join('')+'</div>'
      : '<div class="cc-empty">Каналы связи не найдены.</div>';

    html += '<div class="cc-add-ch">'
      +'<select id="cc-new-type"><option value="email">Email</option>'
      +'<option value="mobile_phone">Мобильный</option>'
      +'<option value="landline_phone">Городской</option>'
      +'<option value="website">Сайт</option></select>'
      +'<input id="cc-new-val" type="text" placeholder="Значение…">'
      +'<button class="cc-btn cc-btn-primary" onclick="ccAddCh()">+ Добавить</button>'
      +'</div>';
    return html;
  }

  /* ── OKVED ─────────────────────────────────────────────────── */
  function _okved() {
    var c = _data.company;
    var okveds = _data.okveds||[];
    var main = okveds.find(function(o){return o.okved_role==='main';});
    var others = okveds.filter(function(o){return o.okved_role!=='main';});
    var mainCode = main?main.okved_code:(c.okved_main_code!=='NOT_FOUND'?c.okved_main_code:null);
    var mainName = main?main.okved_name:c.okved_main_activity;
    var html = '';
    if (mainCode) {
      html += '<div class="cc-okved-main">'
        +'<div class="cc-okved-main-lbl">Основной ОКВЭД</div>'
        +'<div class="cc-okved-code">'+_esc(mainCode)+'</div>'
        +(mainName?'<div class="cc-okved-name">'+_esc(mainName)+'</div>':'')
        +'<button class="cc-okved-action" onclick="ccFindByOkved(\''+_esc(mainCode)+'\')">🔍 Найти похожие компании</button>'
        +'</div>';
    } else {
      html += '<div class="cc-warn">ОКВЭД не найден в справочниках</div>';
    }
    if (others.length) {
      html += '<div style="font-size:11px;font-weight:600;color:var(--text-2);text-transform:uppercase;letter-spacing:.06em;margin:14px 0 8px">Дополнительные ОКВЭД</div>'
        +'<div class="cc-okved-add-list">'+others.map(function(o){
          return '<div class="cc-okved-add-row">'
            +'<span class="cc-okved-add-code">'+_esc(o.okved_code)+'</span>'
            +'<span class="cc-okved-add-name">'+_esc(o.okved_name||'')+'</span>'
            +'</div>';
        }).join('')+'</div>';
    }
    if (!mainCode && !others.length) html += '<div class="cc-empty">Данные ОКВЭД отсутствуют.</div>';
    return html;
  }

  /* ── Campaigns ─────────────────────────────────────────────── */
  function _campaigns() {
    var hist = _data.campaign_history||[];
    if (!hist.length) return '<div class="cc-empty">Рассылки по этой компании не проводились.</div>';
    var stMap = {sent:'cc-badge-green',bounced:'cc-badge-red',failed:'cc-badge-red'};
    return '<div class="cc-camp-list">'+hist.map(function(h){
      var sc = stMap[h.status]||'cc-badge-gray';
      return '<div class="cc-camp-row">'
        +'<span class="cc-camp-name">'+_esc(h.campaign_name||'Рассылка #'+h.campaign_id)+'</span>'
        +'<span class="cc-camp-date">'+_esc((h.sent_at||'').slice(0,10))+'</span>'
        +'<span class="cc-badge '+sc+'">'+_esc(h.status)+'</span>'
        +'</div>';
    }).join('')+'</div>';
  }

  /* ── History ───────────────────────────────────────────────── */
  function _history() {
    var log = _data.contact_change_log||[];
    if (!log.length) return '<div class="cc-empty">История изменений пуста.</div>';
    var CHTYPE = {status_change:'Статус изменён',added:'Канал добавлен',replaced:'Заменён',bounced:'Bounce получен'};
    return '<div class="cc-hist-list">'+log.map(function(l){
      return '<div class="cc-hist-row">'
        +'<div class="cc-hist-date">'+_esc((l.created_at||'').slice(0,10))+'</div>'
        +'<div class="cc-hist-body">'
        +'<div class="cc-hist-type">'+(CHTYPE[l.change_type]||_esc(l.change_type))+'</div>'
        +((l.old_value||l.new_value)?'<div class="cc-hist-detail">'
          +(l.old_value?'Было: <span style="color:var(--text-3)">'+_esc(l.old_value)+'</span>':'')
          +(l.old_value&&l.new_value?' → ':'')
          +(l.new_value?_esc(l.new_value):'')
          +(l.reason?'<br>'+_esc(l.reason):'')
          +'</div>':'')
        +'</div></div>';
    }).join('')+'</div>';
  }

  /* ── Tab switch ────────────────────────────────────────────── */
  window.ccTab = function(tab) {
    _tab = tab;
    // Update active state on tab buttons
    document.querySelectorAll('.cc-tab').forEach(function(el,i){
      var tabs = ['overview','contacts','okved','campaigns','history'];
      el.classList.toggle('active', tabs[i]===tab);
    });
    _renderBody();
  };

  /* ── Edit / Save ───────────────────────────────────────────── */
  window.ccToggleEdit = function() {
    _editing = !_editing; _tab = 'overview'; _render();
  };

  window.ccSave = function() {
    var payload = {};
    document.getElementById('cc-body').querySelectorAll('[name]').forEach(function(el){
      if (el.value.trim()) payload[el.name] = el.value.trim();
    });
    var cid = _data.company.company_id;
    fetch('/api/companies/'+cid, {
      method:'PATCH', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    }).then(function(r){return r.json();}).then(function(d){
      if (d.ok) {
        Object.assign(_data.company, payload);
        _editing = false; _render();
        _toast('Данные сохранены');
      } else { _toast('Ошибка: '+(d.error||''), true); }
    });
  };

  /* ── Add channel ───────────────────────────────────────────── */
  window.ccAddCh = function() {
    var type = document.getElementById('cc-new-type').value;
    var val  = (document.getElementById('cc-new-val').value||'').trim();
    if (!val) return;
    fetch('/api/companies/'+_data.company.company_id+'/channels', {
      method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({channel_type:type, value:val})
    }).then(function(r){return r.json();}).then(function(d){
      if (d.ok) _load(_data.company.company_id);
      else _toast('Ошибка: '+(d.error||''), true);
    });
  };

  window.ccSetChSt = function(id, status) {
    fetch('/api/channels/'+id+'/status', {
      method:'PATCH', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({status:status, reason:'Изменено вручную'})
    }).then(function(){ _load(_data.company.company_id); });
  };

  /* ── Find by OKVED ─────────────────────────────────────────── */
  window.ccFindByOkved = function(code) {
    window._ccClose();
    if (typeof FP !== 'undefined') {
      FP.okvedInc = [code];
      fpSetMode('main');
    }
  };

  /* ── Copy ──────────────────────────────────────────────────── */
  window.ccCopy = function(text) {
    navigator.clipboard.writeText(text).then(function(){ _toast('Скопировано'); }).catch(function(){
      var ta = document.createElement('textarea');
      ta.value = text; document.body.appendChild(ta); ta.select();
      document.execCommand('copy'); document.body.removeChild(ta);
      _toast('Скопировано');
    });
  };

  /* ── Toast ─────────────────────────────────────────────────── */
  function _toast(msg, err) {
    var t = document.getElementById('_cc_toast');
    if (!t) {
      t = document.createElement('div'); t.id='_cc_toast';
      t.style.cssText='position:fixed;bottom:28px;left:50%;transform:translateX(-50%) translateY(14px);'
        +'padding:9px 20px;border-radius:99px;font-size:13px;font-weight:600;'
        +'z-index:9999;opacity:0;transition:all .22s;pointer-events:none;'
        +'box-shadow:0 4px 16px rgba(0,0,0,.18);';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.background = err ? 'var(--bdg-red-text)' : 'var(--accent)';
    t.style.color = '#fff';
    t.style.opacity='1'; t.style.transform='translateX(-50%) translateY(0)';
    clearTimeout(t._tm);
    t._tm = setTimeout(function(){ t.style.opacity='0'; t.style.transform='translateX(-50%) translateY(14px)'; }, 2400);
  }

  /* ── Deep link ─────────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function() {
    var p = new URLSearchParams(window.location.search);
    var cid = p.get('company_id');
    if (cid) setTimeout(function(){ window.openCompanyCard(cid); }, 200);
  });

  function _esc(s) {
    return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
})();
