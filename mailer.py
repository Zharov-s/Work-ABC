import smtplib
import ssl
import re
import time
import json
import os
import secrets
import hashlib
import imaplib
import email as emaillib
import urllib.parse
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


# ── Tracking helpers ──────────────────────────────────────────────────────────

def generate_token() -> str:
    """Генерирует уникальный 32-символьный hex-токен."""
    return secrets.token_hex(16)


def inject_tracking(html: str, token: str, base_url: str, unsub_token: str) -> str:
    """
    Встраивает в HTML-письмо:
    1. Трекинг-пиксель 1×1 (фиксирует открытие)
    2. Перехватывает клики через /track/c/<token>
    3. Заменяет ссылку отписки на /unsubscribe/<token>
    """
    base_url = base_url.rstrip('/')

    # Переписываем ссылки — заворачиваем через трекер
    def rewrite_href(m):
        url = m.group(1)
        # Не трогаем: mailto:, tel:, #, якоря, и уже трекинговые URL
        if url.startswith(('mailto:', 'tel:', '#', base_url)):
            return m.group(0)
        encoded = urllib.parse.quote(url, safe='')
        click_url = f'{base_url}/track/c/{token}?u={encoded}'
        return f'href="{click_url}"'

    html = re.sub(r'href=["\']([^"\']+)["\']', rewrite_href, html)

    # Заменяем ссылки отписки (встроенные в шаблон)
    html = re.sub(
        r'href=["\'][^"\']*unsubscribe[^"\']*["\']',
        f'href="{base_url}/unsubscribe/{unsub_token}"',
        html, flags=re.IGNORECASE
    )

    # Трекинг-пиксель перед </body>
    pixel = (
        f'<img src="{base_url}/track/o/{token}" '
        f'width="1" height="1" style="display:none;width:1px;height:1px" alt="" />'
    )
    if re.search(r'</body>', html, re.IGNORECASE):
        html = re.sub(r'</body>', pixel + '\n</body>', html, flags=re.IGNORECASE)
    else:
        html += '\n' + pixel

    return html


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

    smtp_host      = get_setting('smtp_host', 'smtp.mail.ru')
    smtp_port      = int(get_setting('smtp_port', '465'))
    smtp_user      = get_setting('smtp_user', '')
    smtp_pass      = get_setting('smtp_pass', '')
    from_name      = get_setting('from_name', 'ABCENTRUM')
    from_email     = get_setting('from_email', smtp_user)
    reply_to       = get_setting('reply_to', from_email)
    asset_url      = get_setting(meta['asset_key'], '')
    unsub_url      = get_setting('unsubscribe_url', '')
    tracking_base  = (get_setting('tracking_base_url', '') or '').rstrip('/')

    html_path = os.path.join(TEMPLATE_DIR, meta['html_file'])
    plain_path = os.path.join(TEMPLATE_DIR, meta['plain_file'])

    if not os.path.exists(html_path):
        return {'ok': False, 'error': f'HTML-шаблон не найден: {html_path}'}

    with open(html_path, 'r', encoding='utf-8') as f:
        html_base = f.read() \
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

    # Карта: email → contact_id + token
    recipients_by_email: dict = {}
    for row in recipient_rows or []:
        e = row['email'] if hasattr(row, 'keys') else row.get('email')
        recipients_by_email[e] = row

    failed: list[str] = []
    failed_errors: dict[str, str] = {}
    tokens: dict[str, str] = {}   # email → tracking_token

    # ── Режим A: per-recipient с трекингом ──────────────────────────────────
    if tracking_base:
        def _send_individual(addr: str, html_tracked: str) -> None:
            msg = MIMEMultipart('alternative')
            msg['From']     = from_header
            msg['To']       = addr
            msg['Reply-To'] = reply_to
            msg['Subject']  = subject
            if plain:
                msg.attach(MIMEText(plain, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_tracked, 'html', 'utf-8'))
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as srv:
                srv.login(smtp_user, smtp_pass)
                srv.sendmail(smtp_user, [addr], msg.as_string())

        for i, addr in enumerate(valid):
            token = generate_token()
            tokens[addr] = token
            html_tracked = inject_tracking(html_base, token, tracking_base, token)
            sent = False
            last_error = ''
            for attempt in range(1, 4):
                try:
                    _send_individual(addr, html_tracked)
                    sent = True
                    break
                except Exception as e:
                    last_error = str(e)
                    if attempt < 3:
                        time.sleep(20)
            if not sent:
                failed.append(addr)
                failed_errors[addr] = last_error
            # Небольшая пауза между отправками чтобы не превысить лимит SMTP
            if i < len(valid) - 1:
                time.sleep(0.4)

        batch_count = len(valid)  # каждый — отдельный «батч»

    # ── Режим B: BCC-батчи (без трекинга, исходное поведение) ──────────────
    else:
        batches = [valid[i:i+BATCH_SIZE] for i in range(0, len(valid), BATCH_SIZE)]
        ok_batches = 0

        def _send_batch(batch):
            msg = MIMEMultipart('alternative')
            msg['From']     = from_header
            msg['To']       = from_email
            msg['Reply-To'] = reply_to
            msg['Subject']  = subject
            if plain:
                msg.attach(MIMEText(plain, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_base, 'html', 'utf-8'))
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
                ok_batches += 1
            else:
                failed.extend(batch)
                for addr in batch:
                    failed_errors[addr] = last_error
            if i < len(batches):
                time.sleep(PAUSE_SEC)

        batch_count = len(batches)

    total_sent   = len(valid) - len(failed)
    total_failed = len(failed)

    report = {
        'ok':           True,
        'template':     template_key,
        'subject':      subject,
        'valid':        valid,
        'invalid':      invalid,
        'total_sent':   total_sent,
        'total_failed': total_failed,
        'batch_count':  batch_count,
        'failed':       failed,
        'source':       source,
        'tracking':     bool(tracking_base),
    }

    # ── Сохраняем в историю и send_recipients ───────────────────────────────
    conn = get_db()
    cur  = conn.execute(
        """INSERT INTO send_history(template, subject, total_sent, total_failed, batch_count, status, report_json)
           VALUES(?,?,?,?,?,?,?)""",
        (template_key, subject, total_sent, total_failed, batch_count,
         'done' if not failed else 'partial', json.dumps(report, ensure_ascii=False))
    )
    send_id = cur.lastrowid

    for addr in valid:
        status = 'failed' if addr in failed else 'sent'
        cid    = None
        row    = recipients_by_email.get(addr)
        if row:
            cid = row['contact_id'] if hasattr(row, 'keys') else row.get('contact_id')
        token  = tokens.get(addr)
        conn.execute(
            'INSERT INTO send_recipients(send_id, contact_id, email, status, tracking_token) VALUES(?,?,?,?,?)',
            (send_id, cid, addr, status, token)
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
                     status='sent', sent_at=datetime('now'), last_error=NULL,
                     contact_id=COALESCE(mailing_recipients.contact_id, excluded.contact_id)""",
                (addr, cid)
            )
        else:
            conn.execute(
                """INSERT INTO mailing_recipients(email, contact_id, status, last_error)
                   VALUES(?,?, 'failed', ?)
                   ON CONFLICT(email) DO UPDATE SET
                     status='failed', last_error=excluded.last_error,
                     contact_id=COALESCE(mailing_recipients.contact_id, excluded.contact_id)""",
                (addr, cid, failed_errors.get(addr, 'Ошибка отправки'))
            )

    conn.commit()
    conn.close()

    # Автоматически запускаем проверку bounce-писем в фоне через 5 минут
    # (Mail.ru присылает bounce-уведомления с задержкой)
    if total_sent > 0:
        import threading as _t, time as _time
        def _delayed_bounce_check():
            _time.sleep(300)   # 5 минут — bounce-письма обычно приходят за это время
            try:
                check_bounces()
            except Exception:
                pass
        _t.Thread(target=_delayed_bounce_check, daemon=True).start()

    return report


def send_campaign(template_key, raw_addresses, contact_ids=None):
    """
    Отправка по выбранным адресам. Если адресов > 29, автоматически
    разбивает на батчи и отправляет последовательно.
    """
    valid, invalid = parse_addresses(raw_addresses)
    if not valid:
        return {'ok': False, 'error': 'Нет валидных адресов для отправки'}
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


def retry_failed_send(send_id: int) -> dict:
    """
    Повторная отправка неотправленным получателям ОРИГИНАЛЬНОЙ записи send_id.
    Обновляет ту же запись в истории — новая строка не создаётся.
    Запускается в фоновом потоке, возвращает немедленно.
    """
    import threading

    conn = get_db()
    orig = conn.execute(
        'SELECT template FROM send_history WHERE id=?', (send_id,)
    ).fetchone()
    if not orig:
        conn.close()
        return {'ok': False, 'error': f'Рассылка #{send_id} не найдена'}

    template_key = orig['template']
    rows = conn.execute(
        """SELECT sr.email, sr.contact_id
           FROM send_recipients sr
           WHERE sr.send_id = ? AND sr.status = 'failed'
           ORDER BY sr.id""",
        (send_id,)
    ).fetchall()

    if not rows:
        conn.close()
        return {'ok': False, 'error': 'Нет неотправленных адресов в этой рассылке'}

    # Помечаем оригинальную запись как 'sending' — UI начнёт поллинг
    conn.execute("UPDATE send_history SET status='sending' WHERE id=?", (send_id,))
    conn.commit()
    conn.close()

    rows_snap = [{'email': r['email'], 'contact_id': r['contact_id']} for r in rows]

    def _worker():
        result = _send_addresses(
            template_key,
            [r['email'] for r in rows_snap], [],
            recipient_rows=rows_snap,
            source=f'retry:{send_id}',
        )
        newly_failed = set(result.get('failed', []))
        newly_sent   = result.get('total_sent', 0)

        conn2 = get_db()

        # Обновляем статусы получателей прямо в оригинальной записи
        for r in rows_snap:
            new_status = 'failed' if r['email'] in newly_failed else 'sent'
            conn2.execute(
                'UPDATE send_recipients SET status=? WHERE send_id=? AND lower(email)=?',
                (new_status, send_id, r['email'].lower())
            )

        # Обновляем счётчики оригинальной записи (total_sent суммируем, failed заменяем)
        conn2.execute(
            """UPDATE send_history
               SET total_sent   = total_sent + ?,
                   total_failed = ?,
                   status       = CASE WHEN ? = 0 THEN 'done' ELSE 'partial' END,
                   report_json  = ?
               WHERE id = ?""",
            (newly_sent, len(newly_failed), len(newly_failed),
             json.dumps(result), send_id)
        )

        # Удаляем временную запись, которую создал _send_addresses
        temp = conn2.execute(
            'SELECT id FROM send_history WHERE id > ? ORDER BY id DESC LIMIT 1',
            (send_id,)
        ).fetchone()
        if temp:
            conn2.execute('DELETE FROM send_recipients WHERE send_id=?', (temp['id'],))
            conn2.execute('DELETE FROM send_history WHERE id=?', (temp['id'],))

        conn2.commit()
        conn2.close()

    threading.Thread(target=_worker, daemon=True).start()
    # new_send_id = send_id: UI поллит и перезагружает ТУ ЖЕ страницу
    return {'ok': True, 'new_send_id': send_id, 'async': True, 'count': len(rows_snap)}


_EMAIL_RE_BOUNCE = re.compile(r'[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}')


def _classify_bounce_reason(text: str) -> str:
    """Определяет причину bounce по тексту SMTP-ответа."""
    t = text.lower()
    if any(x in t for x in ['spam', 'policy', '5.7.1', '5.7.2', 'rejected for policy', 'believe this mail is spam']):
        return 'спам/политика сервера'
    if any(x in t for x in ['user unknown', 'does not exist', 'no such user', 'user not found', 'invalid address']):
        return 'адрес не существует'
    if any(x in t for x in ['mailbox full', 'quota', 'over quota']):
        return 'ящик переполнен'
    if any(x in t for x in ['connection refused', 'host not found', 'name or service not known']):
        return 'сервер недоступен'
    if '554' in t or '553' in t:
        return 'отклонено получателем'
    if '550' in t:
        return 'адрес не существует'
    if '452' in t or '421' in t:
        return 'временная ошибка'
    return 'ошибка доставки'


def _parse_bounce_details(msg) -> dict:
    """
    Извлекает упавшие адреса и причины из bounce-сообщения Mail.ru.
    Возвращает dict: {email: reason_str}
    """
    result = {}

    # 1. X-Failed-Recipients header (самый надёжный)
    header = msg.get('X-Failed-Recipients', '')
    for addr in _EMAIL_RE_BOUNCE.findall(header):
        result[addr.lower()] = 'ошибка доставки'

    # 2. Тело письма
    body = ''
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ('text/plain', 'message/delivery-status'):
                try:
                    raw = part.get_payload(decode=True)
                    if raw:
                        body += raw.decode('utf-8', 'ignore') + '\n'
                except Exception:
                    pass
    else:
        try:
            raw = msg.get_payload(decode=True)
            if raw:
                body = raw.decode('utf-8', 'ignore')
        except Exception:
            pass

    # Парсим блоки: email\n  host...\n  SMTP error: XXX
    block_re = re.compile(
        r'^\s{0,4}([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})\s*$',
        re.M
    )
    lines = body.split('\n')
    for i, line in enumerate(lines):
        m = block_re.match(line)
        if m:
            addr = m.group(1).lower()
            # Берём следующие 4 строки как контекст для определения причины
            context = '\n'.join(lines[i+1:i+5])
            reason = _classify_bounce_reason(context)
            result[addr] = reason

    # Final-Recipient (RFC 3464)
    for m in re.finditer(
        r'Final-Recipient[^:]*:[^\n]*rfc822;?\s*([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})',
        body, re.I
    ):
        addr = m.group(1).lower()
        if addr not in result:
            result[addr] = 'ошибка доставки'

    return result


def _parse_bounce_addresses(msg) -> set:
    """Обратная совместимость — возвращает только множество адресов."""
    return set(_parse_bounce_details(msg).keys())


def check_bounces() -> dict:
    """
    Подключается к входящей почте (IMAP), находит уведомления об ошибках доставки,
    извлекает упавшие адреса и помечает их в базе как bounced.
    Возвращает: {'ok': True, 'total': N, 'new': M, 'bounced': [...]}
    """
    smtp_host  = get_setting('smtp_host', 'smtp.mail.ru')
    smtp_user  = get_setting('smtp_user', '')
    smtp_pass  = get_setting('smtp_pass', '')

    if not smtp_user or not smtp_pass:
        return {'ok': False, 'error': 'Не настроены SMTP-реквизиты'}

    # Производим IMAP-хост из SMTP-хоста: smtp.X → imap.X
    imap_host = smtp_host.replace('smtp.', 'imap.', 1) if smtp_host.startswith('smtp.') else 'imap.mail.ru'

    try:
        mail = imaplib.IMAP4_SSL(imap_host, 993, timeout=10)
        mail.login(smtp_user, smtp_pass)
        mail.select('INBOX')
    except Exception as e:
        return {'ok': False, 'error': f'IMAP: {e}'}

    # Собираем ID bounce-сообщений по нескольким критериям
    msg_ids: set = set()
    for crit in [
        b'FROM "MAILER-DAEMON"',
        b'FROM "mailer-daemon"',
        b'SUBJECT "Mail failure"',
        b'SUBJECT "delivery"',
        b'SUBJECT "undeliverable"',
        b'SUBJECT "Undeliverable"',
        b'SUBJECT "failed"',
    ]:
        try:
            st, data = mail.search(None, crit)
            if st == 'OK' and data[0]:
                for mid in data[0].split():
                    msg_ids.add(mid)
        except Exception:
            pass

    # Парсим сообщения — собираем {email: reason}
    bounced_with_reasons: dict = {}
    for mid in msg_ids:
        try:
            st, data = mail.fetch(mid, b'(RFC822)')
            if st != 'OK':
                continue
            msg = emaillib.message_from_bytes(data[0][1])
            details = _parse_bounce_details(msg)
            for addr, reason in details.items():
                if addr not in bounced_with_reasons:
                    bounced_with_reasons[addr] = reason
        except Exception:
            continue

    try:
        mail.logout()
    except Exception:
        pass

    if not bounced_with_reasons:
        return {'ok': True, 'total': len(msg_ids), 'new': 0, 'bounced': []}

    # Получаем все email из нашей базы — обрабатываем только известные
    conn = get_db()
    known_contacts = {
        r['email'].lower(): dict(r)
        for r in conn.execute(
            "SELECT id, email, status, company_name FROM contacts WHERE email IS NOT NULL AND email != ''"
        ).fetchall()
    }

    # Только реально нерабочие адреса требуют действий и уведомлений.
    # Спам/политика (554/553), временные ошибки, полный ящик — адрес РАБОЧИЙ,
    # просто сервер отклонил конкретное письмо. Игнорируем полностью.
    ACTIONABLE_REASONS = {'адрес не существует'}

    new_count   = 0
    bounced_list = []

    for addr, reason in bounced_with_reasons.items():
        # Пропускаем спам-отказы и временные ошибки — адрес валиден
        if reason not in ACTIONABLE_REASONS:
            continue

        if addr not in known_contacts:
            continue

        contact = known_contacts[addr]
        company = contact.get('company_name') or ''
        company_str = f' ({company})' if company else ''

        was_new = (contact.get('status') != 'bounced')

        # Удаляем из базы рассылки
        conn.execute(
            "UPDATE contacts SET status='bounced' WHERE lower(email)=?", (addr,)
        )
        conn.execute(
            "UPDATE mailing_recipients SET status='bounced' WHERE lower(email)=? AND status != 'bounced'",
            (addr,)
        )

        # Корректируем статистику последней рассылки
        send_row = conn.execute(
            """SELECT sr.id, sr.send_id FROM send_recipients sr
               WHERE lower(sr.email)=? AND sr.status='sent'
               ORDER BY sr.send_id DESC LIMIT 1""",
            (addr,)
        ).fetchone()
        if send_row:
            conn.execute(
                "UPDATE send_recipients SET status='bounced' WHERE id=?",
                (send_row['id'],)
            )
            conn.execute(
                """UPDATE send_history
                   SET total_failed = total_failed + 1, status = 'partial'
                   WHERE id = ?""",
                (send_row['send_id'],)
            )

        # Уведомление только при первом обнаружении — без дублей при повторных запусках
        if was_new:
            summary = f'{addr}{company_str} — адрес не существует. Удалён из базы рассылки.'
            details = {
                'from_email':   addr,
                'company':      company,
                'action_done':  'Адрес удалён из базы рассылки',
                'body_preview': f'Bounce: адрес не существует\n{addr}{company_str}',
            }
            conn.execute(
                """INSERT INTO notifications
                   (type, contact_id, company_name, from_email, summary, details_json)
                   VALUES ('bounce', ?, ?, ?, ?, ?)""",
                (contact.get('id'), company, addr, summary,
                 json.dumps(details, ensure_ascii=False))
            )
            new_count += 1
        bounced_list.append({'email': addr, 'company': company, 'reason': reason})

    conn.commit()
    conn.close()

    return {
        'ok':      True,
        'total':   len(msg_ids),
        'new':     new_count,
        'bounced': bounced_list,
    }


# ── Паттерны для классификации входящих ответов ───────────────────────────

_OOO_KEYWORDS = [
    'больничном', 'в отпуске', 'в отпуску', 'недоступен', 'отсутствую',
    'нет доступа к почте', 'ограниченным доступом', 'автоматический ответ',
    'out of office', 'away from office', 'on vacation', 'on leave',
    'вернусь', 'temporarily', 'временно', 'отпуск',
]
_GONE_KEYWORDS = [
    'больше нет', 'больше с нами нет', 'покинул', 'уволился', 'ушёл из компании',
    'не работает в', 'не является сотрудником', 'умер', 'скончался',
    'к нашему огромному сожалению', 'к сожалению', 'не работает данный адрес',
    'данный почтовый ящик', 'данный адрес',
]
_OUR_SUBJECT = 'аренда производственных'   # частичное совпадение темы рассылки


def _classify_reply(subject: str, body: str) -> str:
    """Возвращает тип ответа: 'ooo', 'gone', 'reply'."""
    subj_l = subject.lower()
    body_l  = body.lower()
    if any(k in subj_l for k in ['автоматический ответ', 'out of office', 'auto-reply', 'auto reply']):
        return 'ooo'
    if any(k in body_l for k in _OOO_KEYWORDS):
        return 'ooo'
    if any(k in body_l for k in _GONE_KEYWORDS):
        return 'gone'
    return 'reply'


_NAME_PATTERNS = [
    re.compile(r'(?:обращайтесь к|пишите к|к|директора|менеджера|ответственного|руководителя)\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2})', re.I),
    re.compile(r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)'),  # ФИО
    re.compile(r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)'),                    # Имя Фамилия
]


def _extract_contacts_from_text(text: str, exclude_emails: set | None = None) -> dict:
    """Извлекает email, телефон, имя из текста сообщения."""
    exclude_emails = {e.lower() for e in (exclude_emails or [])}
    exclude_emails.add(get_setting('smtp_user', '').lower())

    emails = [
        e.lower() for e in _EMAIL_RE_BOUNCE.findall(text)
        if e.lower() not in exclude_emails and '.' in e.split('@')[-1]
    ]
    phones = re.findall(
        r'(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}',
        text
    )
    name = None
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            candidate = m.group(1).strip()
            if len(candidate.split()) >= 2:
                name = candidate
                break

    return {
        'emails': emails[:3],
        'phones': [re.sub(r'[^\d+]', '', p) for p in phones[:3]],
        'name':   name,
    }


def _get_message_body(msg) -> str:
    """Возвращает текстовое содержимое письма."""
    body = ''
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                try:
                    raw = part.get_payload(decode=True)
                    if raw:
                        body += raw.decode('utf-8', 'ignore') + '\n'
                except Exception:
                    pass
    else:
        try:
            raw = msg.get_payload(decode=True)
            if raw:
                body = raw.decode('utf-8', 'ignore')
        except Exception:
            pass
    return body


def scan_replies() -> dict:
    """
    Сканирует входящие ответы на рассылку. Определяет тип каждого ответа:
    - ooo   : автоответ об отсутствии, может содержать новые контакты
    - gone  : человека нет, в письме новые контакты
    - reply : обычный ответ с контактами

    Создаёт уведомления, обновляет карточки компаний.
    Возвращает: {'ok': True, 'scanned': N, 'new_notifications': M}
    """
    smtp_host = get_setting('smtp_host', 'smtp.mail.ru')
    smtp_user = get_setting('smtp_user', '')
    smtp_pass = get_setting('smtp_pass', '')
    if not smtp_user or not smtp_pass:
        return {'ok': False, 'error': 'Не настроены SMTP-реквизиты'}

    imap_host = smtp_host.replace('smtp.', 'imap.', 1) if smtp_host.startswith('smtp.') else 'imap.mail.ru'
    try:
        mail = imaplib.IMAP4_SSL(imap_host, 993, timeout=12)
        mail.login(smtp_user, smtp_pass)
        mail.select('INBOX')
    except Exception as e:
        return {'ok': False, 'error': f'IMAP: {e}'}

    # Собираем ID сообщений: ответы на нашу рассылку + автоответы + все непрочитанные за 7 дней
    import datetime as _dt
    since_7d = (_dt.datetime.now() - _dt.timedelta(days=7)).strftime('%d-%b-%Y')

    msg_ids: set = set()
    search_terms = [
        b'SUBJECT "Re: ' + _OUR_SUBJECT.encode() + b'"',
        ('SUBJECT "' + _OUR_SUBJECT + '"').encode(),
        'SUBJECT "Автоматический ответ"'.encode(),
        b'SUBJECT "out of office"',
        b'SUBJECT "Auto-Reply"',
        b'SUBJECT "Undeliverable"',
        # Все непрочитанные за 7 дней — поймаем "ушёл из компании" с любой темой
        f'UNSEEN SINCE {since_7d}'.encode(),
    ]
    for crit in search_terms:
        try:
            st, data = mail.search(None, crit)
            if st == 'OK' and data[0]:
                for mid in data[0].split():
                    msg_ids.add(mid)
        except Exception:
            pass

    # Все email из нашей базы (для определения компании)
    conn = get_db()
    contacts_by_email = {
        r['email'].lower(): dict(r)
        for r in conn.execute(
            "SELECT id, email, company_name, person_name, website, segment, region, mobile_phone, generic_phone FROM contacts WHERE email IS NOT NULL"
        ).fetchall()
    }
    existing_msg_ids = {
        r['msg_id'] for r in conn.execute("SELECT msg_id FROM notifications WHERE msg_id IS NOT NULL").fetchall()
    }
    conn.close()

    new_notifs = 0
    scanned = 0

    for mid in msg_ids:
        try:
            st, data = mail.fetch(mid, b'(RFC822)')
            if st != 'OK':
                continue
            msg = emaillib.message_from_bytes(data[0][1])

            msg_id_header = msg.get('Message-ID', '').strip()
            if msg_id_header and msg_id_header in existing_msg_ids:
                continue  # уже обработано

            scanned += 1
            from_raw = emaillib.utils.parseaddr(msg.get('From', ''))[1].lower().strip()
            subj_raw = msg.get('Subject', '')
            # Декодируем subject
            try:
                import email.header as _eh
                parts = _eh.decode_header(subj_raw)
                subj = ''.join(
                    (p.decode(enc or 'utf-8') if isinstance(p, bytes) else p)
                    for p, enc in parts
                )
            except Exception:
                subj = subj_raw

            body = _get_message_body(msg)
            reply_type = _classify_reply(subj, body)

            # Находим контакт в базе по From:
            contact = contacts_by_email.get(from_raw)
            company_name = contact['company_name'] if contact else None

            # Пропускаем если: отправитель не в базе И нет нашей темы И нет gone/ooo-ключей в теле
            if not contact and _OUR_SUBJECT not in subj.lower():
                body_lower = body.lower()
                has_relevant = any(k in body_lower for k in _GONE_KEYWORDS + _OOO_KEYWORDS)
                if not has_relevant:
                    continue

            # Извлекаем новые контакты из тела письма
            extracted = _extract_contacts_from_text(body, exclude_emails={from_raw})

            # Формируем понятный summary с реальным контекстом
            person = (contact['person_name'] if contact and contact.get('person_name') else None)
            co = company_name or from_raw

            new_contacts_parts = []
            if extracted.get('name'):    new_contacts_parts.append(extracted['name'])
            if extracted.get('emails'):  new_contacts_parts.append(extracted['emails'][0])
            if extracted.get('phones'):  new_contacts_parts.append(extracted['phones'][0])
            new_contacts_str = ', '.join(new_contacts_parts)

            if reply_type == 'gone':
                who = f'{person} ({co})' if person else co
                if new_contacts_str:
                    summary = f'{who} — больше не работает. Новые контакты: {new_contacts_str}. Данные обновлены в базе.'
                else:
                    summary = f'{who} — больше не работает. Контакт удалён из базы рассылки.'
            elif reply_type == 'ooo':
                who = f'{person}, {co}' if person else co
                if new_contacts_str:
                    summary = f'{who} — временно недоступен. В письме найдены контакты: {new_contacts_str}.'
                else:
                    summary = f'{who} — автоответ об отсутствии. Добавьте замену при наличии.'
            else:
                who = f'{person} ({co})' if person else co
                if new_contacts_str:
                    summary = f'Ответ от {who}. Найдены новые контакты: {new_contacts_str}.'
                else:
                    summary = f'Ответ на рассылку от {who}.'

            details = {
                'from_email':  from_raw,
                'subject':     subj,
                'reply_type':  reply_type,
                'new_emails':  extracted['emails'],
                'new_phones':  extracted['phones'],
                'new_name':    extracted['name'],
                'body_preview': body[:500].strip(),
            }

            # ── Обновляем базу контактов ────────────────────────────────────
            actions = []   # что реально сделали — для details
            conn2 = get_db()
            try:
                today = __import__('datetime').datetime.now().strftime('%Y-%m-%d')

                if reply_type == 'gone' and contact:
                    # Помечаем ушедшего как bounced
                    conn2.execute(
                        "UPDATE contacts SET status='bounced' WHERE id=?",
                        (contact['id'],)
                    )
                    conn2.execute(
                        "UPDATE mailing_recipients SET status='bounced' WHERE lower(email)=?",
                        (from_raw,)
                    )
                    actions.append(f'email {from_raw} помечен как недействительный')

                    # Добавляем новые контакты в карточку компании
                    new_emails = extracted['emails']
                    new_phones = extracted['phones']
                    new_name   = extracted['name']

                    for new_email in new_emails:
                        # Проверяем, нет ли уже в базе
                        exists = conn2.execute(
                            "SELECT id FROM contacts WHERE lower(email)=?", (new_email,)
                        ).fetchone()
                        if not exists:
                            conn2.execute(
                                """INSERT INTO contacts
                                   (company_name, website, person_name, email,
                                    phone, segment, region, date_found, status, notes)
                                   VALUES (?,?,?,?,?,?,?,?,'new',?)""",
                                (contact['company_name'], contact.get('website'),
                                 new_name,
                                 new_email,
                                 new_phones[0] if new_phones else None,
                                 contact.get('segment'), contact.get('region'),
                                 today,
                                 f'Добавлен из ответа на рассылку (замена {from_raw})')
                            )
                            actions.append(f'добавлен новый контакт: {new_name or ""} {new_email}')

                    # Если телефон есть, но нового email нет — добавляем строку только с телефоном
                    if new_phones and not new_emails:
                        conn2.execute(
                            """INSERT INTO contacts
                               (company_name, website, person_name,
                                phone, segment, region, date_found, status, notes)
                               VALUES (?,?,?,?,?,?,?,'new',?)""",
                            (contact['company_name'], contact.get('website'),
                             new_name,
                             new_phones[0],
                             contact.get('segment'), contact.get('region'),
                             today,
                             f'Добавлен из ответа на рассылку (замена {from_raw})')
                        )
                        actions.append(f'добавлен телефон: {new_phones[0]} ({new_name or ""})')

                elif reply_type in ('ooo', 'reply') and contact:
                    # Автоответ или обычный ответ: дополняем карточку новыми данными
                    new_phones = extracted['phones']
                    new_emails = [e for e in extracted['emails'] if e != from_raw]

                    # Обновляем телефон если не заполнен
                    if new_phones:
                        existing = conn2.execute(
                            "SELECT mobile_phone, generic_phone FROM contacts WHERE id=?",
                            (contact['id'],)
                        ).fetchone()
                        if existing and not existing['mobile_phone'] and not existing['generic_phone']:
                            conn2.execute(
                                "UPDATE contacts SET mobile_phone=? WHERE id=?",
                                (new_phones[0], contact['id'])
                            )
                            actions.append(f'добавлен телефон: {new_phones[0]}')

                    # Новые email — добавляем как дополнительные контакты компании
                    for new_email in new_emails:
                        exists = conn2.execute(
                            "SELECT id FROM contacts WHERE lower(email)=?", (new_email,)
                        ).fetchone()
                        if not exists:
                            conn2.execute(
                                """INSERT INTO contacts
                                   (company_name, website, person_name, email,
                                    segment, region, date_found, status, notes)
                                   VALUES (?,?,?,?,?,?,?,'new',?)""",
                                (contact['company_name'], contact.get('website'),
                                 extracted['name'],
                                 new_email,
                                 contact.get('segment'), contact.get('region'),
                                 today,
                                 f'Добавлен из {"автоответа" if reply_type=="ooo" else "ответа"} {from_raw}')
                            )
                            actions.append(f'добавлен email: {new_email}')

                # Обновляем details с тем, что реально сделали
                details['actions'] = actions

                # Сохраняем уведомление
                conn2.execute(
                    """INSERT OR IGNORE INTO notifications
                       (type, contact_id, company_name, from_email, summary, details_json, msg_id)
                       VALUES (?,?,?,?,?,?,?)""",
                    (reply_type,
                     contact['id'] if contact else None,
                     company_name, from_raw, summary,
                     json.dumps(details, ensure_ascii=False),
                     msg_id_header or None)
                )

                conn2.commit()
                if conn2.execute("SELECT changes()").fetchone()[0] > 0:
                    new_notifs += 1
                    existing_msg_ids.add(msg_id_header)
            except Exception:
                pass
            finally:
                conn2.close()

        except Exception:
            continue

    try:
        mail.logout()
    except Exception:
        pass

    return {'ok': True, 'scanned': scanned, 'new_notifications': new_notifs}

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
