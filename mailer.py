import smtplib
import ssl
import re
import time
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from database import get_setting, get_db

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

BATCH_SIZE = 10
PAUSE_SEC  = 10


def normalize_email(raw):
    raw = raw.strip().lower()
    if '@' not in raw:
        return None
    local, domain = raw.rsplit('@', 1)
    try:
        domain.encode('ascii')
    except UnicodeEncodeError:
        try:
            domain = '.'.join(
                p.encode('idna').decode('ascii') if not p.isascii() else p
                for p in domain.split('.')
            )
        except Exception:
            return None
    addr = f'{local}@{domain}'
    return addr if EMAIL_RE.match(addr) else None


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


def send_campaign(template_key, raw_addresses, contact_ids=None):
    """
    Отправляет рассылку.
    Возвращает dict с отчётом.
    Все адреса идут в BCC, To = from_email.
    Максимум 30 адресов за вызов (проверяется здесь и в UI).
    """
    meta = TEMPLATE_META.get(template_key)
    if not meta:
        return {'ok': False, 'error': f'Неизвестный шаблон: {template_key}'}

    valid, invalid = parse_addresses(raw_addresses)

    if len(valid) > 30:
        return {'ok': False, 'error': f'Превышен лимит: {len(valid)} адресов (максимум 30 за раз)'}

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
        for attempt in range(1, 4):
            try:
                _send_batch(batch)
                sent = True
                break
            except Exception as e:
                if attempt < 3:
                    time.sleep(30)
        if sent:
            ok_count += 1
        else:
            failed.extend(batch)
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

    for addr in valid:
        status = 'failed' if addr in failed else 'sent'
        cid = None
        if contact_ids:
            pass  # contact_ids is a list of (email, id) pairs
        conn.execute(
            'INSERT INTO send_recipients(send_id, email, status) VALUES(?,?,?)',
            (send_id, addr, status)
        )
        # Обновить статус контакта
        if addr not in failed:
            conn.execute("UPDATE contacts SET status='sent' WHERE email=?", (addr,))

    conn.commit()
    conn.close()

    return report


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
