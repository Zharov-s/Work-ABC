import os
import json
import io
import hashlib
import urllib.parse
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
load_dotenv()

from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, Response, flash, send_file, make_response)

from database import (
    init_db, get_db, get_setting, set_setting, get_all_settings,
    sync_mailing_recipients, get_mailing_stats, MAILING_BATCH_LIMIT,
    normalize_mailing_email,
)
from auth import check_credentials, set_password, set_login
from mailer import send_campaign, send_pending_campaign, retry_failed_send, test_smtp, parse_addresses, TEMPLATE_META
from validator import validate_email, validate_emails_batch
from researcher import (
    start_research, get_run_status, pause_research, resume_research, finish_research,
    SEGMENT_LABELS, SEGMENT_VRI, REGION_SUFFIX, INDUSTRY_LABELS, SCALE_LABELS,
    CONTACT_REQUIREMENT_LABELS, normalize_contact_requirements, contact_satisfies_requirements,
    project_contact_to_requirements,
)

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'abcentrum-dev-key')

@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value)
    except Exception:
        return {}


# ── Auth decorator ────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ── Login / Logout ────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        login_val = request.form.get('login', '').strip()
        password  = request.form.get('password', '')
        if check_credentials(login_val, password):
            session['logged_in'] = True
            session['user']      = login_val
            return redirect(url_for('dashboard'))
        error = 'Неверный логин или пароль'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    conn = get_db()
    total_contacts = conn.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]
    new_contacts   = conn.execute("SELECT COUNT(*) FROM contacts WHERE status='new'").fetchone()[0]
    total_sends    = conn.execute('SELECT COUNT(*) FROM send_history').fetchone()[0]

    last_run = conn.execute(
        "SELECT * FROM research_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    recent_sends = conn.execute(
        "SELECT * FROM send_history ORDER BY id DESC LIMIT 5"
    ).fetchall()

    conn.close()
    return render_template('dashboard.html',
        total_contacts=total_contacts,
        new_contacts=new_contacts,
        total_sends=total_sends,
        last_run=last_run,
        recent_sends=recent_sends,
    )


# ── Contacts ──────────────────────────────────────────────────────────────────

@app.route('/contacts')
@login_required
def contacts():
    conn = get_db()

    q       = request.args.get('q', '').strip()
    segment = request.args.get('segment', '')
    region  = request.args.get('region', '')
    status  = request.args.get('status', '')
    page    = max(1, int(request.args.get('page', 1)))
    per_page = 50

    filters = []
    params  = []
    if q:
        filters.append("(company_name LIKE ? OR person_name LIKE ? OR email LIKE ?)")
        params += [f'%{q}%', f'%{q}%', f'%{q}%']
    if segment:
        filters.append('segment = ?')
        params.append(segment)
    if region:
        filters.append('region = ?')
        params.append(region)
    if status:
        filters.append('status = ?')
        params.append(status)

    where = ('WHERE ' + ' AND '.join(filters)) if filters else ''

    total = conn.execute(f'SELECT COUNT(*) FROM contacts {where}', params).fetchone()[0]
    rows  = conn.execute(
        f'SELECT * FROM contacts {where} ORDER BY id DESC LIMIT ? OFFSET ?',
        params + [per_page, (page - 1) * per_page]
    ).fetchall()

    segments = [r['segment'] for r in
                conn.execute('SELECT DISTINCT segment FROM contacts WHERE segment IS NOT NULL').fetchall()]
    regions  = [r['region'] for r in
                conn.execute('SELECT DISTINCT region FROM contacts WHERE region IS NOT NULL').fetchall()]

    conn.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template('contacts.html',
        contacts=rows,
        total=total,
        page=page,
        total_pages=total_pages,
        segments=segments,
        regions=regions,
        q=q,
        filter_segment=segment,
        filter_region=region,
        filter_status=status,
    )


@app.route('/contacts/add', methods=['POST'])
@login_required
def add_contact():
    data = request.form
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO contacts
               (company_name, website, person_name, title, email, phone,
                segment, region, date_found, status, notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get('company_name'), data.get('website'),
             data.get('person_name'), data.get('title'),
             data.get('email'), data.get('phone'),
             data.get('segment'), data.get('region'),
             datetime.now().strftime('%Y-%m-%d'),
             data.get('status', 'new'),
             data.get('notes'))
        )
        conn.commit()
        flash('Контакт добавлен', 'success')
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('contacts'))


@app.route('/contacts/<int:cid>/delete', methods=['POST'])
@login_required
def delete_contact(cid):
    conn = get_db()
    conn.execute('DELETE FROM contacts WHERE id=?', (cid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/contacts/<int:cid>/status', methods=['POST'])
@login_required
def update_contact_status(cid):
    new_status = request.json.get('status', 'new')
    conn = get_db()
    conn.execute('UPDATE contacts SET status=? WHERE id=?', (new_status, cid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/contacts/export')
@login_required
def export_contacts():
    import openpyxl
    ids_raw = request.args.get('ids', '')
    conn    = get_db()
    if ids_raw:
        ids  = [int(x) for x in ids_raw.split(',') if x.strip().isdigit()]
        rows = conn.execute(
            f"SELECT * FROM contacts WHERE id IN ({','.join('?'*len(ids))})", ids
        ).fetchall()
    else:
        rows = conn.execute('SELECT * FROM contacts').fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Контакты'
    headers = ['Компания', 'Сайт', 'ФИО', 'Должность', 'Email', 'Телефон',
               'Email личный', 'Email общий', 'Телефон мобильный',
               'Телефон общий', 'ИНН', 'Сегмент', 'Регион', 'Статус', 'Дата']
    ws.append(headers)
    for r in rows:
        ws.append([r['company_name'], r['website'], r['person_name'], r['title'],
                   r['email'], r['phone'], r['personal_email'], r['generic_email'],
                   r['mobile_phone'], r['generic_phone'], r['inn'],
                   r['segment'], r['region'],
                   r['status'], r['date_found']])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 25

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name='contacts_export.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ── Research ──────────────────────────────────────────────────────────────────

@app.route('/research')
@login_required
def research():
    conn = get_db()
    runs = conn.execute(
        'SELECT * FROM research_runs ORDER BY id DESC LIMIT 10'
    ).fetchall()
    conn.close()
    return render_template('research.html',
        runs=runs,
        segments=SEGMENT_LABELS,
        segment_vri=SEGMENT_VRI,
        industries=INDUSTRY_LABELS,
        regions=REGION_SUFFIX,
        scales=SCALE_LABELS,
        contact_requirements=CONTACT_REQUIREMENT_LABELS,
        research_features_version=2,
    )


@app.route('/research/start', methods=['POST'])
@login_required
def research_start():
    segments = request.form.getlist('segments') or ['electronics']
    regions = request.form.getlist('regions') or [request.form.get('region', 'moscow')]
    company_scales = request.form.getlist('company_scales') or [request.form.get('company_scale', 'any')]
    contact_requirements = request.form.getlist('contact_requirements')
    if not contact_requirements:
        return jsonify({'ok': False, 'error': 'Выберите хотя бы одно требование к контакту'})
    contact_requirements = normalize_contact_requirements(contact_requirements)
    try:
        target_count = int(request.form.get('count', 10))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Введите корректное количество компаний'})
    if target_count < 1:
        return jsonify({'ok': False, 'error': 'Количество компаний должно быть больше нуля'})
    config = {
        'segments':      segments,
        'industries':    request.form.getlist('industries'),
        'regions':       regions,
        'region':        regions[0],
        'count':         target_count,
        'keywords':      request.form.get('keywords', ''),
        'company_scales': company_scales,
        'company_scale': company_scales[0],
        'contact_requirements': contact_requirements,
        'require_email': bool(request.form.get('require_email')),
        'require_phone': bool(request.form.get('require_phone')),
        'active_only':   True,
    }
    run_id = start_research(config)
    return jsonify({
        'ok': True,
        'run_id': run_id,
        'contact_requirements': contact_requirements,
        'research_features_version': 2,
    })


@app.route('/research/run/<int:run_id>/pause', methods=['POST'])
@login_required
def research_run_pause(run_id):
    return jsonify({'ok': pause_research(run_id)})


@app.route('/research/run/<int:run_id>/resume', methods=['POST'])
@login_required
def research_run_resume(run_id):
    return jsonify({'ok': resume_research(run_id)})


@app.route('/research/run/<int:run_id>/finish', methods=['POST'])
@login_required
def research_run_finish(run_id):
    return jsonify({'ok': finish_research(run_id)})


@app.route('/research/run/<int:run_id>/contacts')
@login_required
def research_run_contacts(run_id):
    conn = get_db()
    run_row = conn.execute('SELECT config_json FROM research_runs WHERE id=?', (run_id,)).fetchone()
    rows = conn.execute(
        """SELECT id, company_name, website, person_name, title, email, phone,
                  personal_email, generic_email, mobile_phone, generic_phone, inn, segment
           FROM contacts WHERE run_id=? ORDER BY id""",
        (run_id,)
    ).fetchall()
    conn.close()
    requirements = None
    if run_row and run_row['config_json']:
        try:
            cfg = json.loads(run_row['config_json'])
            requirements = cfg.get('contact_requirements')
        except Exception:
            requirements = None
    if requirements:
        requirements = normalize_contact_requirements(requirements)
        filtered = []
        for r in rows:
            item = dict(r)
            ok, _ = contact_satisfies_requirements(item, requirements)
            if ok:
                item = project_contact_to_requirements(item, requirements)
                item['_contact_requirements'] = requirements
                filtered.append(item)
        return jsonify(filtered)
    return jsonify([dict(r) for r in rows])


@app.route('/research/run/<int:run_id>/delete', methods=['POST'])
@login_required
def research_run_delete(run_id):
    conn = get_db()
    conn.execute('DELETE FROM research_runs WHERE id=?', (run_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/research/status/<int:run_id>')
@login_required
def research_status(run_id):
    run = get_run_status(run_id)
    if not run:
        conn = get_db()
        row = conn.execute('SELECT * FROM research_runs WHERE id=?', (run_id,)).fetchone()
        conn.close()
        if row:
            import json as _json
            cfg = _json.loads(row['config_json']) if row['config_json'] else {}
            return jsonify({'status': row['status'], 'log': row['log_text'].split('\n'),
                            'found_count': row['found_count'],
                            'target_count': int(cfg.get('count', 0))})
        return jsonify({'status': 'not_found', 'log': [], 'found_count': 0, 'target_count': 0})
    return jsonify({'status': run['status'], 'log': run['log'],
                    'found_count': run['found_count'],
                    'target_count': run.get('target_count', 0)})


# ── Campaigns ─────────────────────────────────────────────────────────────────

@app.route('/campaigns')
@login_required
def campaigns():
    conn = get_db()
    sync_mailing_recipients(conn)
    conn.commit()
    mailing_stats = get_mailing_stats(conn)
    history = conn.execute(
        'SELECT * FROM send_history ORDER BY id DESC LIMIT 20'
    ).fetchall()

    preselect_ids_raw = request.args.get('ids', '')
    preselect_tmpl    = request.args.get('template', 'mitino')
    preselect_ids     = [int(x) for x in preselect_ids_raw.split(',')
                         if x.strip().isdigit()] if preselect_ids_raw else []
    conn.close()
    return render_template('campaigns.html',
        history=history,
        templates=TEMPLATE_META,
        preselect_ids=json.dumps(preselect_ids),
        preselect_tmpl=preselect_tmpl,
        mailing_stats=mailing_stats,
        mailing_batch_limit=MAILING_BATCH_LIMIT,
    )


@app.route('/api/contacts/for-campaign')
@login_required
def contacts_for_campaign():
    """Возвращает список контактов для пикера получателей рассылки."""
    template      = request.args.get('template', 'mitino')
    status_filter = request.args.get('status', 'new')   # 'new' | 'all'
    segments_raw  = request.args.get('segments', '').strip()
    segments      = [s.strip() for s in segments_raw.split(',') if s.strip()]
    search        = request.args.get('search', '').strip()

    conn = get_db()

    # email-адреса, которым уже отправляли именно этот шаблон
    sent_emails: set = set()
    if status_filter == 'new':
        rows = conn.execute(
            """SELECT DISTINCT lower(sr.email) AS email
               FROM send_recipients sr
               JOIN send_history sh ON sr.send_id = sh.id
               WHERE sh.template = ? AND sr.status = 'sent'""",
            (template,)
        ).fetchall()
        sent_emails = {r['email'] for r in rows}

    # Строим запрос контактов
    conditions = ["c.email IS NOT NULL AND c.email != ''"]
    params: list = []

    if search:
        like = f'%{search}%'
        conditions.append(
            '(c.company_name LIKE ? OR c.person_name LIKE ? OR c.email LIKE ?)'
        )
        params.extend([like, like, like])

    if segments:
        placeholders = ','.join('?' * len(segments))
        conditions.append(f'c.segment IN ({placeholders})')
        params.extend(segments)

    where = ' AND '.join(conditions)
    contacts_raw = conn.execute(
        f"""SELECT c.id, c.company_name, c.person_name,
                   c.email, c.personal_email, c.generic_email, c.segment
            FROM contacts c
            WHERE {where}
            ORDER BY c.company_name COLLATE NOCASE""",
        params
    ).fetchall()

    segments = [r[0] for r in conn.execute(
        "SELECT DISTINCT segment FROM contacts "
        "WHERE segment IS NOT NULL AND segment != '' ORDER BY segment"
    ).fetchall()]

    conn.close()

    contacts = []
    for r in contacts_raw:
        all_emails = {
            (r['email']          or '').lower(),
            (r['personal_email'] or '').lower(),
            (r['generic_email']  or '').lower(),
        } - {''}
        is_sent = bool(all_emails & sent_emails)

        if status_filter == 'new' and is_sent:
            continue

        contacts.append({
            'id':       r['id'],
            'company':  r['company_name'] or '',
            'person':   r['person_name']  or '',
            'email':    r['email'],
            'segment':  r['segment']      or '',
            'is_sent':  is_sent,
            'is_valid': normalize_mailing_email(r['email']) is not None,
        })

    return jsonify({'contacts': contacts, 'segments': segments})


@app.route('/campaigns/send', methods=['POST'])
@login_required
def campaign_send():
    template_key  = request.form.get('template', 'mitino')
    raw_addresses = request.form.get('addresses', '')
    result        = send_campaign(template_key, raw_addresses)
    result['mailing_stats'] = get_mailing_stats()
    return jsonify(result)


@app.route('/campaigns/send-pending', methods=['POST'])
@login_required
def campaign_send_pending():
    template_key = request.form.get('template', 'mitino')
    count_raw = request.form.get('count', 'all')
    requested_count = None
    if count_raw != 'all':
        try:
            requested_count = max(int(count_raw), 0)
        except ValueError:
            requested_count = None
    result = send_pending_campaign(template_key, requested_count)
    result['mailing_stats'] = get_mailing_stats()
    return jsonify(result)




@app.route('/campaigns/<int:send_id>/retry', methods=['POST'])
@login_required
def campaign_retry(send_id):
    """Повторная отправка неотправленным получателям рассылки send_id."""
    result = retry_failed_send(send_id)
    if result.get('mailing_stats') is None:
        result['mailing_stats'] = get_mailing_stats()
    return jsonify(result)

@app.route('/campaigns/<int:send_id>')
@login_required
def campaign_detail(send_id):
    conn = get_db()
    send = conn.execute('SELECT * FROM send_history WHERE id=?', (send_id,)).fetchone()
    if not send:
        conn.close()
        return 'Не найдено', 404
    recipients = conn.execute(
        'SELECT * FROM send_recipients WHERE send_id=?', (send_id,)
    ).fetchall()

    # ── Трекинг-статистика ────────────────────────────────────────────────
    opens_count = conn.execute(
        'SELECT COUNT(DISTINCT token) FROM email_opens WHERE send_id=?', (send_id,)
    ).fetchone()[0]
    clicks_count = conn.execute(
        'SELECT COUNT(DISTINCT token) FROM email_clicks WHERE send_id=? AND is_unsubscribe=0', (send_id,)
    ).fetchone()[0]
    unsub_count  = conn.execute(
        'SELECT COUNT(DISTINCT token) FROM email_clicks WHERE send_id=? AND is_unsubscribe=1', (send_id,)
    ).fetchone()[0]

    # Кто открыл
    openers = conn.execute(
        """SELECT DISTINCT eo.email, eo.opened_at
           FROM email_opens eo WHERE eo.send_id=?
           ORDER BY eo.opened_at DESC LIMIT 50""", (send_id,)
    ).fetchall()

    conn.close()

    report = {}
    if send['report_json']:
        try:
            report = json.loads(send['report_json'])
        except Exception:
            pass

    total_sent = send['total_sent'] or 0
    tracking_stats = {
        'opens':    opens_count,
        'clicks':   clicks_count,
        'unsubs':   unsub_count,
        'open_rate':  round(opens_count  / total_sent * 100, 1) if total_sent else 0,
        'click_rate': round(clicks_count / total_sent * 100, 1) if total_sent else 0,
        'unsub_rate': round(unsub_count  / total_sent * 100, 1) if total_sent else 0,
        'delivered': total_sent - (send['total_failed'] or 0),
        'failed':    send['total_failed'] or 0,
        'delivered_rate': round((total_sent - (send['total_failed'] or 0)) / total_sent * 100, 1) if total_sent else 0,
        'failed_rate':    round((send['total_failed'] or 0) / total_sent * 100, 1) if total_sent else 0,
    }
    return render_template('campaign_detail.html',
                           send=send, recipients=recipients,
                           report=report, stats=tracking_stats,
                           openers=openers)


# ── Tracking pixel & click routes (не требуют авторизации) ───────────────────

# 1×1 прозрачный GIF
_PIXEL_GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00'
    b'!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01'
    b'\x00\x00\x02\x02D\x01\x00;'
)


@app.route('/track/o/<token>')
def track_open(token):
    """Трекинг-пиксель: фиксирует открытие письма."""
    if token:
        try:
            conn = get_db()
            row  = conn.execute(
                'SELECT send_id, contact_id, email FROM send_recipients WHERE tracking_token=?',
                (token,)
            ).fetchone()
            if row:
                ip_raw = request.headers.get('X-Forwarded-For', request.remote_addr or '')
                ip_hash = hashlib.sha256(ip_raw.encode()).hexdigest()[:16]
                conn.execute(
                    'INSERT INTO email_opens(token, send_id, contact_id, email, user_agent, ip_hash) VALUES(?,?,?,?,?,?)',
                    (token, row['send_id'], row['contact_id'], row['email'],
                     request.user_agent.string[:255] if request.user_agent else None,
                     ip_hash)
                )
                conn.commit()
            conn.close()
        except Exception:
            pass

    resp = make_response(_PIXEL_GIF)
    resp.headers['Content-Type']  = 'image/gif'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma']        = 'no-cache'
    return resp


@app.route('/track/c/<token>')
def track_click(token):
    """Трекинг перехода по ссылке из письма."""
    url = request.args.get('u', '')
    is_unsub = request.args.get('unsub', '0') == '1'
    if token and url:
        try:
            decoded_url = urllib.parse.unquote(url)
            conn = get_db()
            row  = conn.execute(
                'SELECT send_id, contact_id, email FROM send_recipients WHERE tracking_token=?',
                (token,)
            ).fetchone()
            if row:
                conn.execute(
                    'INSERT INTO email_clicks(token, send_id, contact_id, email, url, is_unsubscribe, user_agent) VALUES(?,?,?,?,?,?,?)',
                    (token, row['send_id'], row['contact_id'], row['email'],
                     decoded_url[:500], 1 if is_unsub else 0,
                     request.user_agent.string[:255] if request.user_agent else None)
                )
                conn.commit()
            conn.close()
            return redirect(decoded_url)
        except Exception:
            pass
    return redirect(url or '/')


@app.route('/unsubscribe/<token>', methods=['GET', 'POST'])
def unsubscribe(token):
    """Страница отписки от рассылки."""
    conn = get_db()
    row  = conn.execute(
        'SELECT send_id, contact_id, email FROM send_recipients WHERE tracking_token=?',
        (token,)
    ).fetchone()
    if not row:
        conn.close()
        return render_template('unsubscribe.html', status='invalid', email=None)

    email = row['email']

    if request.method == 'POST':
        # Помечаем контакт как отписавшегося
        conn.execute(
            "UPDATE contacts SET status='unsubscribed' WHERE lower(email)=? OR lower(personal_email)=? OR lower(generic_email)=?",
            (email, email, email)
        )
        conn.execute(
            """INSERT INTO email_clicks(token, send_id, contact_id, email, url, is_unsubscribe, user_agent)
               VALUES(?,?,?,?,'unsubscribe',1,?)""",
            (token, row['send_id'], row['contact_id'], email,
             request.user_agent.string[:255] if request.user_agent else None)
        )
        conn.commit()
        conn.close()
        return render_template('unsubscribe.html', status='done', email=email)

    conn.close()
    return render_template('unsubscribe.html', status='confirm', email=email, token=token)


# ── Email validation route ────────────────────────────────────────────────────

@app.route('/contacts/validate-emails', methods=['POST'])
@login_required
def validate_emails_route():
    """Batch MX-валидация всех email в базе."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, email FROM contacts WHERE email IS NOT NULL AND email != ''"
    ).fetchall()
    conn.close()

    emails = [r['email'] for r in rows if r['email']]
    results = validate_emails_batch(emails)

    # Обновляем поле email_valid
    conn = get_db()
    for r in rows:
        if r['email'] in results:
            conn.execute('UPDATE contacts SET email_valid=? WHERE id=?',
                         (results[r['email']], r['id']))
    conn.commit()

    counts = {'valid': 0, 'invalid': 0, 'unknown': 0}
    for s in results.values():
        counts[s] = counts.get(s, 0) + 1
    conn.close()

    return jsonify({'ok': True, 'total': len(emails), **counts})


# ── Settings ──────────────────────────────────────────────────────────────────

@app.route('/settings')
@login_required
def settings():
    s = get_all_settings()
    return render_template('settings.html', s=s)


@app.route('/settings/save', methods=['POST'])
@login_required
def settings_save():
    keys = ['smtp_host', 'smtp_port', 'smtp_ssl', 'smtp_user', 'smtp_pass',
            'from_name', 'from_email', 'reply_to',
            'asset_url_mitino', 'asset_url_grekova', 'unsubscribe_url']
    for k in keys:
        val = request.form.get(k, '').strip()
        if val:
            set_setting(k, val)

    # Пароль входа
    new_login    = request.form.get('app_login', '').strip()
    new_password = request.form.get('new_password', '').strip()
    if new_login:
        set_login(new_login)
    if new_password and len(new_password) >= 4:
        set_password(new_password)

    flash('Настройки сохранены', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/test-smtp', methods=['POST'])
@login_required
def settings_test_smtp():
    result = test_smtp()
    return jsonify(result)


# ── API: preview template ─────────────────────────────────────────────────────

@app.route('/preview/<template_key>')
@login_required
def preview_template(template_key):
    import os
    from mailer import TEMPLATE_DIR
    meta = TEMPLATE_META.get(template_key)
    if not meta:
        return 'Шаблон не найден', 404
    asset_url = get_setting(meta['asset_key'], '')
    unsub_url = get_setting('unsubscribe_url', '')
    html_path = os.path.join(TEMPLATE_DIR, meta['html_file'])
    if not os.path.exists(html_path):
        return 'HTML-файл шаблона не найден', 404
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read() \
            .replace('{{ASSET_BASE_URL}}', asset_url) \
            .replace('{{unsubscribe_url}}', unsub_url)
    return Response(html, mimetype='text/html')


# ── Init DB on startup (работает и с gunicorn, и напрямую) ───────────────────
init_db()

# При рестарте все "running" воркеры убиты — помечаем как interrupted
_boot_conn = get_db()
_boot_conn.execute("UPDATE research_runs SET status='interrupted' WHERE status IN ('running','paused','finishing')")
_boot_conn.commit()
_boot_conn.close()

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5050))
    debug = os.getenv('FLASK_ENV') != 'production'
    app.run(debug=debug, host='0.0.0.0', port=port, use_reloader=False)
