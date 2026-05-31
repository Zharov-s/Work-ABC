import os
import json
import io
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
load_dotenv()

from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, Response, flash, send_file)

from database import init_db, get_db, get_setting, set_setting, get_all_settings
from auth import check_credentials, set_password, set_login
from mailer import send_campaign, test_smtp, parse_addresses, TEMPLATE_META
from researcher import start_research, get_run_status, SEGMENT_LABELS, REGION_SUFFIX

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
               'Сегмент', 'Регион', 'Статус', 'Дата']
    ws.append(headers)
    for r in rows:
        ws.append([r['company_name'], r['website'], r['person_name'], r['title'],
                   r['email'], r['phone'], r['segment'], r['region'],
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
        regions=REGION_SUFFIX,
    )


@app.route('/research/start', methods=['POST'])
@login_required
def research_start():
    config = {
        'segment':  request.form.get('segment', 'electronics'),
        'region':   request.form.get('region', 'moscow'),
        'count':    int(request.form.get('count', 10)),
        'keywords': request.form.get('keywords', ''),
    }
    run_id = start_research(config)
    return jsonify({'ok': True, 'run_id': run_id})


@app.route('/research/status/<int:run_id>')
@login_required
def research_status(run_id):
    run = get_run_status(run_id)
    if not run:
        conn = get_db()
        row = conn.execute('SELECT * FROM research_runs WHERE id=?', (run_id,)).fetchone()
        conn.close()
        if row:
            return jsonify({'status': row['status'], 'log': row['log_text'].split('\n'),
                            'found_count': row['found_count']})
        return jsonify({'status': 'not_found', 'log': [], 'found_count': 0})
    return jsonify({'status': run['status'], 'log': run['log'], 'found_count': run['found_count']})


# ── Campaigns ─────────────────────────────────────────────────────────────────

@app.route('/campaigns')
@login_required
def campaigns():
    conn    = get_db()
    history = conn.execute(
        'SELECT * FROM send_history ORDER BY id DESC LIMIT 20'
    ).fetchall()

    # Предзаполнение адресов если пришли с Контактов
    preselect_ids  = request.args.get('ids', '')
    preselect_tmpl = request.args.get('template', 'mitino')
    preselect_addrs = ''
    if preselect_ids:
        ids = [int(x) for x in preselect_ids.split(',') if x.strip().isdigit()]
        rows = conn.execute(
            f"SELECT email FROM contacts WHERE id IN ({','.join('?'*len(ids))})", ids
        ).fetchall()
        preselect_addrs = '\n'.join(r['email'] for r in rows)

    conn.close()
    return render_template('campaigns.html',
        history=history,
        templates=TEMPLATE_META,
        preselect_addrs=preselect_addrs,
        preselect_tmpl=preselect_tmpl,
    )


@app.route('/campaigns/send', methods=['POST'])
@login_required
def campaign_send():
    template_key  = request.form.get('template', 'mitino')
    raw_addresses = request.form.get('addresses', '')
    result        = send_campaign(template_key, raw_addresses)
    return jsonify(result)


@app.route('/campaigns/<int:send_id>')
@login_required
def campaign_detail(send_id):
    conn = get_db()
    send = conn.execute('SELECT * FROM send_history WHERE id=?', (send_id,)).fetchone()
    recipients = conn.execute(
        'SELECT * FROM send_recipients WHERE send_id=?', (send_id,)
    ).fetchall()
    conn.close()
    if not send:
        return 'Не найдено', 404
    report = {}
    if send['report_json']:
        try:
            report = json.loads(send['report_json'])
        except Exception:
            pass
    return render_template('campaign_detail.html', send=send, recipients=recipients, report=report)


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

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5050))
    debug = os.getenv('FLASK_ENV') != 'production'
    app.run(debug=debug, host='0.0.0.0', port=port, use_reloader=False)
