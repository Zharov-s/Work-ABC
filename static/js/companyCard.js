/**
 * companyCard.js — centered modal company card with blur backdrop, tabs, edit/save.
 */
(function() {
  var _editing = false;
  var _data    = null;
  var _tab     = 'overview';

  // ── Open / Close ─────────────────────────────────────────────────────────
  window.openCompanyCard = function(companyId) {
    _tab     = 'overview';
    _editing = false;
    _data    = null;

    var bd = document.getElementById('cc-backdrop');
    bd.classList.add('open');
    document.body.style.overflow = 'hidden';

    _showSkeleton();
    _loadCard(companyId);

    // Update URL without navigation
    var url = new URL(window.location);
    url.searchParams.set('company_id', companyId);
    history.replaceState(null, '', url);
  };

  function _closeCard() {
    var bd = document.getElementById('cc-backdrop');
    bd.classList.remove('open');
    document.body.style.overflow = '';
    _editing = false;
    var url = new URL(window.location);
    url.searchParams.delete('company_id');
    history.replaceState(null, '', url);
  }

  // ── Load data ─────────────────────────────────────────────────────────────
  function _loadCard(companyId) {
    fetch('/api/companies/' + companyId + '/card', {credentials: 'same-origin'})
      .then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(d) {
        _data = d;
        _render();
      })
      .catch(function(e) {
        document.getElementById('cc-body').innerHTML =
          '<div class="cc-empty">⚠ Не удалось загрузить карточку: ' + e.message + '<br>' +
          '<button class="cc-btn" onclick="openCompanyCard(\'' + companyId + '\')" style="margin-top:12px">↺ Повторить</button></div>';
      });
  }

  // ── Skeleton ──────────────────────────────────────────────────────────────
  function _showSkeleton() {
    var modal = document.getElementById('cc-modal');
    modal.querySelector('.cc-head-top').innerHTML =
      '<div class="cc-skeleton"><div class="cc-skeleton-line" style="width:220px;height:22px"></div></div>' +
      '<button class="cc-close" onclick="_ccClose()">✕</button>';
    modal.querySelector('.cc-tabs').innerHTML =
      '<div class="cc-skeleton" style="display:flex;gap:8px;padding:8px 0">' +
      ['Обзор','Контакты','ОКВЭД','Рассылки','История'].map(function(t){
        return '<div class="cc-skeleton-line" style="width:60px;height:32px;border-radius:6px"></div>';
      }).join('') + '</div>';
    document.getElementById('cc-body').innerHTML =
      '<div class="cc-skeleton">' +
      '<div class="cc-skeleton-line" style="width:60%"></div>'.repeat(6) +
      '</div>';
    document.getElementById('cc-save-bar').style.display = 'none';
  }

  // ── Render card ───────────────────────────────────────────────────────────
  function _render() {
    if (!_data) return;
    var c = _data.company;
    var modal = document.getElementById('cc-modal');

    // head
    var st = c.match_status || 'manual_review';
    var stCls   = {verified:'cc-badge-green', likely:'cc-badge-blue', conflict:'cc-badge-red', manual_review:'cc-badge-yellow'}[st] || 'cc-badge-gray';
    var stLabel = {verified:'Подтверждён', likely:'Вероятно', conflict:'Конфликт', manual_review:'Требует проверки', not_found:'Не найден'}[st] || st;

    modal.querySelector('.cc-head-top').innerHTML =
      '<div>' +
      '<div class="cc-company-name">' + _esc(c.company_name_original || '—') + '</div>' +
      (c.legal_name_found && c.legal_name_found !== c.company_name_original
        ? '<div style="font-size:12px;color:var(--text-muted);margin-top:2px">' + _esc(c.legal_name_found) + '</div>' : '') +
      '</div>' +
      '<button class="cc-close" onclick="_ccClose()">✕</button>';

    modal.querySelector('.cc-meta').innerHTML =
      '<span class="cc-badge ' + stCls + '">' + stLabel + '</span>' +
      (c.inn ? '<span>ИНН&nbsp;<b>' + c.inn + '</b></span><button class="cc-copy-btn" onclick="ccCopy(\'' + c.inn + '\')">⎘</button>' : '') +
      (c.region ? '<span>📍&nbsp;' + _esc(c.region) + (c.city && c.city !== c.region ? ',&nbsp;' + _esc(c.city) : '') + '</span>' : '');

    // warnings
    var warnHtml = '';
    (_data.warnings || []).forEach(function(w) {
      var isErr = w.type === 'conflict' || w.type === 'bounce';
      warnHtml += '<div class="cc-warn' + (isErr?' err':'') + '">⚠&nbsp;' + _esc(w.text) + '</div>';
    });
    modal.querySelector('.cc-warnings').innerHTML = warnHtml;

    // action buttons
    var emails = (_data.channels||[]).filter(function(ch){ return ch.channel_type==='email' && ch.status==='active'; });
    var emailLink = emails.length ? 'mailto:' + emails[0].value : '#';
    modal.querySelector('.cc-actions').innerHTML =
      (c.website ? '<a href="' + _esc(c.website) + '" target="_blank" class="cc-btn">↗ Сайт</a>' : '') +
      (c.inn ? '<button class="cc-btn" onclick="ccCopy(\'' + c.inn + '\')">⎘ ИНН</button>' : '') +
      (emails.length ? '<button class="cc-btn" onclick="ccCopy(\'' + emails[0].value + '\')">⎘ Email</button>' : '') +
      '<button class="cc-btn cc-btn-primary" id="cc-edit-btn" onclick="ccToggleEdit()">' + (_editing ? '✕ Отмена' : '✎ Редактировать') + '</button>';

    // tabs
    var tabs = [
      {id:'overview', label:'Обзор'},
      {id:'contacts', label:'Контакты&nbsp;(' + (_data.channels||[]).length + ')'},
      {id:'okved',    label:'ОКВЭД'},
      {id:'campaigns',label:'Рассылки&nbsp;(' + (_data.campaign_history||[]).length + ')'},
      {id:'history',  label:'История'},
    ];
    modal.querySelector('.cc-tabs').innerHTML = tabs.map(function(t) {
      return '<button class="cc-tab' + (_tab===t.id?' active':'') + '" onclick="ccTab(\'' + t.id + '\')">' + t.label + '</button>';
    }).join('');

    _renderTab();
  }

  function _renderTab() {
    var body = document.getElementById('cc-body');
    var saveBar = document.getElementById('cc-save-bar');
    if (!_data) return;

    if (_tab === 'overview')  { body.innerHTML = _renderOverview(); saveBar.style.display = _editing ? 'flex' : 'none'; }
    if (_tab === 'contacts')  { body.innerHTML = _renderContacts(); saveBar.style.display = 'none'; }
    if (_tab === 'okved')     { body.innerHTML = _renderOkved();    saveBar.style.display = 'none'; }
    if (_tab === 'campaigns') { body.innerHTML = _renderCampaigns();saveBar.style.display = 'none'; }
    if (_tab === 'history')   { body.innerHTML = _renderHistory();  saveBar.style.display = 'none'; }
  }

  // ── Tab: Overview ─────────────────────────────────────────────────────────
  function _renderOverview() {
    var c = _data.company;
    if (_editing) {
      return '<div class="cc-field-grid">' +
        _field('company_name_original', 'Название',            c.company_name_original, 'input') +
        _field('inn',                   'ИНН',                 c.inn, 'input') +
        _field('website',               'Сайт',                c.website, 'input') +
        _field('region',                'Регион',              c.region, 'input') +
        _field('city',                  'Город',               c.city, 'input') +
        _field('segment',               'Сегмент',             c.segment, 'input') +
        _field('industry_group_final',  'Отрасль',             c.industry_group_final, 'input', true) +
        _field('activity_type_final',   'Вид деятельности',    c.activity_type_final, 'input', true) +
        _field('registration_address',  'Адрес регистрации',   c.registration_address, 'input', true) +
        _field('review_comment',        'Комментарий',         c.review_comment, 'textarea', true) +
        '</div>';
    }
    function row(label, val, link) {
      if (!val) return '';
      var display = link ? '<a href="' + _esc(val) + '" target="_blank">' + _esc(val) + '</a>' : _esc(val);
      return '<div class="cc-field"><div class="cc-label">' + label + '</div><div class="cc-value">' + display + '</div></div>';
    }
    return '<div class="cc-field-grid">' +
      row('Название',          c.company_name_original) +
      row('Юр. название',      c.legal_name_found) +
      row('ИНН',               c.inn) +
      row('ОГРН',              c.ogrn) +
      row('Сайт',              c.website, true) +
      row('Регион',            c.region) +
      row('Город',             c.city) +
      row('Сегмент',           c.segment) +
      row('Отрасль',           c.industry_group_final) +
      row('Вид деятельности',  c.activity_type_final) +
      row('Адрес регистрации', c.registration_address) +
      (c.review_comment ? '<div class="cc-field cc-field-wide"><div class="cc-label">Комментарий</div><div class="cc-value">' + _esc(c.review_comment) + '</div></div>' : '') +
      '</div>';
  }

  function _field(name, label, val, type, wide) {
    var input = type === 'textarea'
      ? '<textarea class="cc-textarea" name="' + name + '">' + _esc(val||'') + '</textarea>'
      : '<input class="cc-input" type="text" name="' + name + '" value="' + _esc(val||'') + '">';
    return '<div class="cc-field' + (wide?' cc-field-wide':'') + '">' +
           '<div class="cc-label">' + label + '</div>' + input + '</div>';
  }

  // ── Tab: Contacts ─────────────────────────────────────────────────────────
  function _renderContacts() {
    var chans = _data.channels || [];
    if (!chans.length) return '<div class="cc-empty">Контакты не найдены.<br>Добавьте первый канал связи.</div>' + _addChannelForm();
    var icons = {email:'✉', mobile_phone:'📱', landline_phone:'☎', website:'🌐'};
    var html = '<div class="cc-ch-list">';
    chans.forEach(function(ch) {
      var statusCls = ch.status || 'active';
      html += '<div class="cc-ch-row">' +
        '<span class="cc-ch-icon">' + (icons[ch.channel_type]||'📌') + '</span>' +
        '<span class="cc-ch-val">' + _esc(ch.value) + '</span>' +
        '<span class="cc-ch-type">' + _typeLabel(ch.channel_type) + '</span>' +
        '<div class="cc-ch-status-dot ' + statusCls + '" title="' + statusCls + '"></div>' +
        '<div class="cc-ch-actions">' +
        '<button class="cc-copy-btn" onclick="ccCopy(\'' + _esc(ch.value) + '\')">⎘</button>' +
        (statusCls === 'active'
          ? '<button class="cc-copy-btn" onclick="ccSetChannelStatus(' + ch.id + ',\'inactive\')" title="Пометить неактуальным">✕</button>'
          : '<button class="cc-copy-btn" onclick="ccSetChannelStatus(' + ch.id + ',\'active\')" title="Восстановить">✓</button>') +
        '</div></div>';
    });
    html += '</div>' + _addChannelForm();
    return html;
  }

  function _addChannelForm() {
    return '<div class="cc-add-ch" style="margin-top:14px">' +
      '<select id="cc-ch-type"><option value="email">Email</option><option value="mobile_phone">Мобильный</option><option value="landline_phone">Городской</option><option value="website">Сайт</option></select>' +
      '<input id="cc-ch-val" type="text" placeholder="Введите значение…">' +
      '<button class="cc-btn cc-btn-primary" onclick="ccAddChannel()">+ Добавить</button>' +
      '</div>';
  }

  function _typeLabel(t) {
    return {email:'Email', mobile_phone:'Мобильный', landline_phone:'Городской', website:'Сайт'}[t] || t;
  }

  // ── Tab: OKVED ────────────────────────────────────────────────────────────
  function _renderOkved() {
    var c = _data.company;
    var okveds = _data.okveds || [];
    var main = okveds.find(function(o){ return o.okved_role === 'main'; });
    var others = okveds.filter(function(o){ return o.okved_role !== 'main'; });
    var mainCode = main ? main.okved_code : (c.okved_main_code !== 'NOT_FOUND' ? c.okved_main_code : null);
    var mainName = main ? main.okved_name : c.okved_main_activity;

    var html = '';
    if (mainCode) {
      html += '<div class="cc-okved-main">' +
        '<div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Основной ОКВЭД</div>' +
        '<div class="cc-okved-code">' + mainCode + '</div>' +
        '<div class="cc-okved-name">' + _esc(mainName || '') + '</div>' +
        '<button class="cc-okved-add" onclick="ccFilterByOkved(\'' + mainCode + '\')" style="margin-top:8px">🔍 Найти похожие по ОКВЭД</button>' +
        '</div>';
    } else {
      html += '<div class="cc-warn">ОКВЭД не найден в справочниках. Требуется ручная проверка.</div>';
    }
    if (others.length) {
      html += '<div style="font-size:12px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em;margin:12px 0 8px">Дополнительные ОКВЭД</div>';
      html += '<div class="cc-okved-list">';
      others.forEach(function(o) {
        html += '<div class="cc-okved-row"><span class="cc-okved-badge">' + o.okved_code + '</span><span style="color:var(--text-muted)">' + _esc(o.okved_name || '') + '</span></div>';
      });
      html += '</div>';
    }
    if (c.okved_additional_activities && !others.length) {
      html += '<div style="font-size:12px;color:var(--text-muted);margin-top:10px;background:var(--surface);padding:10px;border-radius:8px;">' +
        '<b>Из исходных данных:</b> ' + _esc(c.okved_additional_activities) + '</div>';
    }
    if (!mainCode && !others.length) {
      html += '<div class="cc-empty">Данные ОКВЭД отсутствуют.</div>';
    }
    return html;
  }

  // ── Tab: Campaigns ────────────────────────────────────────────────────────
  function _renderCampaigns() {
    var hist = _data.campaign_history || [];
    if (!hist.length) return '<div class="cc-empty">Рассылки по этой компании не проводились.</div>';
    var html = '';
    hist.forEach(function(h) {
      var stCls = h.status === 'sent' ? 'cc-badge-green' : h.status === 'bounced' ? 'cc-badge-red' : 'cc-badge-gray';
      html += '<div class="cc-camp-row">' +
        '<div class="cc-camp-name">' + _esc(h.campaign_name || 'Рассылка #' + h.campaign_id) + '</div>' +
        '<div style="font-size:12px;color:var(--text-muted)">' + _esc((h.sent_at||'').slice(0,10)) + '</div>' +
        '<span class="cc-badge ' + stCls + '">' + _esc(h.status) + '</span>' +
        '</div>';
    });
    return html;
  }

  // ── Tab: History ──────────────────────────────────────────────────────────
  function _renderHistory() {
    var log = _data.contact_change_log || [];
    if (!log.length) return '<div class="cc-empty">История изменений пуста.</div>';
    var html = '';
    log.forEach(function(l) {
      html += '<div class="cc-hist-row">' +
        '<div class="cc-hist-date">' + _esc((l.created_at||'').slice(0,10)) + '</div>' +
        '<div class="cc-hist-body">' +
        '<b>' + _esc(_changeLabel(l.change_type)) + '</b>' +
        (l.old_value ? ' — было: <span style="color:var(--text-muted)">' + _esc(l.old_value) + '</span>' : '') +
        (l.new_value ? ' → <span>' + _esc(l.new_value) + '</span>' : '') +
        (l.reason    ? '<div style="font-size:12px;color:var(--text-muted)">' + _esc(l.reason) + '</div>' : '') +
        '</div></div>';
    });
    return html;
  }

  function _changeLabel(t) {
    return {status_change:'Статус изменён', added:'Добавлен', replaced:'Заменён', bounced:'Bounce'}[t] || t;
  }

  // ── Tab switch ────────────────────────────────────────────────────────────
  window.ccTab = function(tab) {
    _tab = tab;
    document.querySelectorAll('.cc-tab').forEach(function(el){ el.classList.toggle('active', el.textContent.trim().startsWith(tab==='overview'?'Обзор':tab==='contacts'?'Контакты':tab==='okved'?'ОКВЭД':tab==='campaigns'?'Рассылки':'История')); });
    // simpler: re-render tabs and body
    _render();
  };

  // ── Edit toggle ───────────────────────────────────────────────────────────
  window.ccToggleEdit = function() {
    _editing = !_editing;
    _tab = 'overview';
    _render();
  };

  // ── Save ──────────────────────────────────────────────────────────────────
  window.ccSave = function() {
    var form = document.getElementById('cc-body');
    var inputs = form.querySelectorAll('[name]');
    var payload = {};
    inputs.forEach(function(inp){ if (inp.value.trim() !== '') payload[inp.name] = inp.value.trim(); });
    var companyId = _data.company.company_id;

    fetch('/api/companies/' + companyId, {
      method: 'PATCH',
      headers: {'Content-Type':'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    }).then(function(r){ return r.json(); })
      .then(function(d) {
        if (d.ok) {
          // Update local data and re-render
          Object.assign(_data.company, payload);
          _editing = false;
          _render();
          _showToast('Данные сохранены');
        } else {
          _showToast('Ошибка: ' + d.error, true);
        }
      });
  };

  // ── Add channel ───────────────────────────────────────────────────────────
  window.ccAddChannel = function() {
    var type = document.getElementById('cc-ch-type').value;
    var val  = (document.getElementById('cc-ch-val').value || '').trim();
    if (!val) return;
    fetch('/api/companies/' + _data.company.company_id + '/channels', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({channel_type: type, value: val})
    }).then(function(r){ return r.json(); })
      .then(function(d) {
        if (d.ok) { _loadCard(_data.company.company_id); }
        else _showToast('Ошибка: ' + d.error, true);
      });
  };

  // ── Set channel status ────────────────────────────────────────────────────
  window.ccSetChannelStatus = function(channelId, status) {
    fetch('/api/channels/' + channelId + '/status', {
      method: 'PATCH',
      headers: {'Content-Type':'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify({status: status, reason: 'Изменено вручную'})
    }).then(function(){ _loadCard(_data.company.company_id); });
  };

  // ── Filter by OKVED ───────────────────────────────────────────────────────
  window.ccFilterByOkved = function(code) {
    _ccClose();
    if (typeof fpInit === 'function') {
      FP.okvedInc = [code]; fpApply();
    }
  };

  // ── Copy helper ───────────────────────────────────────────────────────────
  window.ccCopy = function(text) {
    navigator.clipboard.writeText(text).then(function(){ _showToast('Скопировано'); });
  };

  // ── Toast ─────────────────────────────────────────────────────────────────
  function _showToast(msg, isError) {
    var t = document.getElementById('cc-toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'cc-toast';
      t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(20px);' +
        'background:#1c3a34;color:#fff;padding:10px 20px;border-radius:99px;font-size:13px;font-weight:600;' +
        'z-index:9999;opacity:0;transition:all .2s;pointer-events:none;';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.background = isError ? '#ef4444' : '#1c3a34';
    t.style.opacity = '1'; t.style.transform = 'translateX(-50%) translateY(0)';
    clearTimeout(t._timer);
    t._timer = setTimeout(function(){
      t.style.opacity='0'; t.style.transform='translateX(-50%) translateY(20px)';
    }, 2200);
  }

  // ── Escape close ─────────────────────────────────────────────────────────
  window._ccClose = _closeCard;
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') _closeCard();
  });

  // ── Deep link: open card from URL ─────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function() {
    var params = new URLSearchParams(window.location.search);
    var cid = params.get('company_id');
    if (cid) setTimeout(function(){ openCompanyCard(cid); }, 300);
  });

  function _esc(s) {
    return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
})();
