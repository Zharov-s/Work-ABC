import smtplib
import ssl
import re
import time
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from database import get_setting, get_db, normalize_mailing_email, sync_mailing_recipients, MAILING_BATCH_LIMIT

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'email_templates')

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

TEMPLATE_META = {
    'mitino': {
        'subject':    'Аренда производственных и коммерческих помещений',
        'preheader':  'Площади в аренду в ABCENTRUM: 11 776 м², класс A+, ввод — 3 кв. 2026.',
        'asset_key':  'asset_url_mitino',
        'html_file':  'mitino/email-cdn-template.html',
        'plain_file': 'mitino/plain-text.txt',
    },
    'grekova': {
        'subject':    'Грекова, 5–7: продажа медицинского здания',
        'preheader':  'Отдельно стоящее медицинское здание у метро «Медведково». 3 761,68 м², Shell & Core.',
        'asset_key':  'asset_url_grekova',
        'html_file':  'grekova/email-cdn-template.html',
        'plain_file': 'grekova/plain-text.txt',
    },
}

BATCH_SIZE = MAILING_BATCH_LIMIT
PAUSE_SEC  = 10


def normalize_email(raw):
    return normalize_mailing_email(raw)


def parse_addresses(raw_text):
    valid, invalid = [], []
    seen = set()
    for line in re.split(r'[\n,;]+', raw_text):
        raw = line.strip()
        if not raw:
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        addr = normalize_email(raw)
        if addr:
            valid.append(addr)
        else:
            invalid.append(raw)
    return valid, invalid


def _send_addresses(template_key, valid, invalid=None, recipient_rows=None, source='manual'):
    meta = TEMPLATE_META.get(template_key)
    if not meta:
        return {'ok': False, 'error': f'Неизвестный шаблон: {template_key}'}

    if not valid:
        return {'ok': False, 'error': 'Нет валидных адресов для отправки'}

    smtp_host   = get_setting('smtp_host', 'smtp.mail.ru')
    smtp_port   = int(get_setting('smtp_port', '465'))
    smtp_user   = get_setting('smtp_user', '')
    smtp_pass   = get_setting('smtp_pass', '')
    from_name   = get_setting('from_name', 'ABCENTRUM')
    from_email  = get_setting('from_email', smtp_user)
    reply_to    = get_setting('reply_to', from_email)
    asset_url   = get_setting(meta['asset_key'], '')
    unsub_url   = get_setting('unsubscribe_url', '')

    html_path   = os.path.join(TEMPLATE_DIR, meta['html_file'])
    plain_path  = os.path.join(TEMPLATE_DIR, meta['plain_file'])

    if not os.path.exists(html_path):
        return {'ok': False, 'error': f'HTML-шаблон не найден: {html_path}'}

    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read() \
            .replace('{{ASSET_BASE_URL}}', asset_url) \
            .replace('{{unsubscribe_url}}', unsub_url)

    plain = ''
    if os.path.exists(plain_path):
        with open(plain_path, 'r', encoding='utf-8') as f:
            plain = f.read()

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE

    subject     = meta['subject']
    from_header = f'{from_name} <{from_email}>'

    batches    = [valid[i:i+BATCH_SIZE] for i in range(0, len(valid), BATCH_SIZE)]
    ok_count   = 0
    failed     = []
    failed_errors = {}

    def _send_batch(batch):
        msg = MIMEMultipart('alternative')
        msg['From']     = from_header
        msg['To']       = from_email
        msg['Reply-To'] = reply_to
        msg['Subject']  = subject
        if plain:
            msg.attach(MIMEText(plain, 'plain', 'utf-8'))
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        envelope = list({from_email} | set(batch))
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as srv:
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_user, envelope, msg.as_string())

    for i, batch in enumerate(batches, 1):
        sent = False
        last_error = ''
        for attempt in range(1, 4):
            try:
                _send_batch(batch)
                sent = True
                break
            except Exception as e:
                last_error = str(e)
                if attempt < 3:
                    time.sleep(30)
        if sent:
            ok_count += 1
        else:
            failed.extend(batch)
            for addr in batch:
                failed_errors[addr] = last_error
        if i < len(batches):
            time.sleep(PAUSE_SEC)

    total_sent   = len(valid) - len(failed)
    total_failed = len(failed)

    report = {
        'ok':          True,
        'template':    template_key,
        'subject':     subject,
        'valid':       valid,
        'invalid':     invalid,
        'total_sent':  total_sent,
        'total_failed':total_failed,
        'batch_count': len(batches),
        'failed':      failed,
        'source':      source,
    }

    # Сохранить в историю
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO send_history(template, subject, total_sent, total_failed, batch_count, status, report_json)
           VALUES(?,?,?,?,?,?,?)""",
        (template_key, subject, total_sent, total_failed, len(batches),
         'done' if not failed else 'partial', json.dumps(report, ensure_ascii=False))
    )
    send_id = cur.lastrowid

    recipients_by_email = {}
    for row in recipient_rows or []:
        email = row['email'] if hasattr(row, 'keys') else row.get('email')
        recipients_by_email[email] = row

    for addr in valid:
        status = 'failed' if addr in failed else 'sent'
        cid = None
        row = recipients_by_email.get(addr)
        if row:
            cid = row['contact_id'] if hasattr(row, 'keys') else row.get('contact_id')
        conn.execute(
            'INSERT INTO send_recipients(send_id, contact_id, email, status) VALUES(?,?,?,?)',
            (send_id, cid, addr, status)
        )
        if addr not in failed:
            conn.execute(
                """UPDATE contacts SET status='sent'
                   WHERE lower(email)=? OR lower(personal_email)=? OR lower(generic_email)=?""",
                (addr, addr, addr)
            )
            conn.execute(
                """INSERT INTO mailing_recipients(email, contact_id, status, sent_at, last_error)
                   VALUES(?,?, 'sent', datetime('now'), NULL)
                   ON CONFLICT(email) DO UPDATE SET
                     status='sent',
                     sent_at=datetime('now'),
                     last_error=NULL,
                     contact_id=COALESCE(mailing_recipients.contact_id, excluded.contact_id)""",
                (addr, cid)
            )
        else:
            conn.execute(
                """INSERT INTO mailing_recipients(email, contact_id, status, last_error)
                   VALUES(?,?, 'failed', ?)
                   ON CONFLICT(email) DO UPDATE SET
                     status='failed',
                     last_error=excluded.last_error,
                     contact_id=COALESCE(mailing_recipients.contact_id, excluded.contact_id)""",
                (addr, cid, failed_errors.get(addr, 'Ошибка отправки'))
            )

    conn.commit()
    conn.close()

    return report


def send_campaign(template_key, raw_addresses, contact_ids=None):
    """
    Ручная отправка по введённым адресам.
    Все адреса идут в BCC, To = from_email.
    За один ручной запуск нельзя отправить больше 29 адресов.
    """
    valid, invalid = parse_addresses(raw_addresses)

    if len(valid) > MAILING_BATCH_LIMIT:
        return {
            'ok': False,
            'error': f'Превышен лимит: {len(valid)} адресов (максимум {MAILING_BATCH_LIMIT} за раз)'
        }

    return _send_addresses(template_key, valid, invalid, source='manual')


def send_pending_campaign(template_key, requested_count=None):
    """
    Отправляет по оставшимся адресам из общего пула.
    Если адресов больше 29, они уходят несколькими SMTP-этапами по 29.
    """
    sync_mailing_recipients()
    conn = get_db()
    limit = ''
    params = []
    if requested_count:
        limit = 'LIMIT ?'
        params.append(int(requested_count))
    rows = conn.execute(
        f"""SELECT id, contact_id, email
            FROM mailing_recipients
            WHERE status!='sent'
            ORDER BY CASE WHEN status='failed' THEN 1 ELSE 0 END, id
            {limit}""",
        params
    ).fetchall()
    conn.close()

    addresses = [r['email'] for r in rows]
    return _send_addresses(template_key, addresses, [], recipient_rows=rows, source='queue')


def test_smtp():
    """Проверяет соединение — отправляет тестовое письмо самому себе."""
    smtp_host  = get_setting('smtp_host', 'smtp.mail.ru')
    smtp_port  = int(get_setting('smtp_port', '465'))
    smtp_user  = get_setting('smtp_user', '')
    smtp_pass  = get_setting('smtp_pass', '')
    from_name  = get_setting('from_name', 'ABCENTRUM')
    from_email = get_setting('from_email', smtp_user)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE

    try:
        msg = MIMEMultipart('alternative')
        msg['From']    = f'{from_name} <{from_email}>'
        msg['To']      = from_email
        msg['Subject'] = 'ABCENTRUM: тест SMTP соединения'
        msg.attach(MIMEText('Тест SMTP — соединение работает.', 'plain', 'utf-8'))
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as srv:
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_user, [from_email], msg.as_string())
        return {'ok': True, 'message': f'Тест отправлен на {from_email}'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
