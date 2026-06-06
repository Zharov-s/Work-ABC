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
from database import (get_setting, get_db, normalize_mailing_email,
                       sync_mailing_recipients, MAILING_BATCH_LIMIT,
                       compute_freshness_score, update_contact_verified)

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
    failed_types: dict[str, str] = {}   # email → classified failure type
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
                refused = srv.sendmail(smtp_user, [addr], msg.as_string())
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)

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
                failed_types[addr] = _classify_bounce_reason(last_error)
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
                return srv.sendmail(smtp_user, envelope, msg.as_string())

        for i, batch in enumerate(batches, 1):
            sent = False
            last_error = ''
            for attempt in range(1, 4):
                try:
                    refused = _send_batch(batch)
                    refused_recipients = {
                        addr for addr in refused
                        if addr.lower() != from_email.lower()
                    }
                    if refused_recipients:
                        for addr in refused_recipients:
                            failed.append(addr)
                            err_text = str(refused[addr])
                            failed_errors[addr] = err_text
                            failed_types[addr] = _classify_bounce_reason(err_text)
                    sent = True
                    break
                except Exception as e:
                    last_error = str(e)
                    if attempt < 3:
                        time.sleep(30)
            if sent:
                ok_batches += 1
            else:
                raw_type = _classify_bounce_reason(last_error)
                # batch-level exception не привязан к конкретному адресу —
                # нельзя приписывать nonexistent_email всей пачке.
                batch_fail_type = raw_type if raw_type != 'nonexistent_email' else 'unknown_failure'
                failed.extend(batch)
                for addr in batch:
                    failed_errors[addr] = last_error
                    failed_types[addr] = batch_fail_type
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
            fail_type = failed_types.get(addr, 'unknown_failure')
            # GUARD: только nonexistent_email → bounced; всё остальное НЕ удаляется
            if fail_type == 'nonexistent_email':
                mr_status = 'bounced'
                conn.execute(
                    """UPDATE contacts SET status='bounced', bounce_count=COALESCE(bounce_count,0)+1
                       WHERE lower(email)=? OR lower(personal_email)=? OR lower(generic_email)=?""",
                    (addr, addr, addr)
                )
            elif fail_type == 'blocked_or_policy':
                mr_status = 'blocked'
            else:
                mr_status = 'failed'
            conn.execute(
                """INSERT INTO mailing_recipients(email, contact_id, status, last_error)
                   VALUES(?,?,?,?)
                   ON CONFLICT(email) DO UPDATE SET
                     status=CASE WHEN mailing_recipients.status = 'bounced'
                                 THEN 'bounced' ELSE excluded.status END,
                     last_error=excluded.last_error,
                     contact_id=COALESCE(mailing_recipients.contact_id, excluded.contact_id)""",
                (addr, cid, mr_status, failed_errors.get(addr, 'Ошибка отправки'))
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
            WHERE status IN ('pending', 'failed')
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
    """
    Классифицирует причину отказа доставки по тексту SMTP-ответа или bounce-письма.

    Возвращает ТОЛЬКО одно из четырёх значений:
      'nonexistent_email'  — адрес явно не существует → разрешено ставить bounced
      'blocked_or_policy'  — доставка заблокирована антиспамом/политикой, адрес рабочий
      'temporary_failure'  — временная ошибка, адрес рабочий
      'unknown_failure'    — причина неизвестна, адрес считать рабочим

    КРИТИЧНО: логика консервативная.
    Нет 100% явного признака несуществования → НЕ возвращать 'nonexistent_email'.
    По умолчанию → 'unknown_failure': адрес НЕ удаляется и НЕ становится bounced.

    Примеры → 'nonexistent_email' (только для этого класса разрешён bounced/удаление):
      "user unknown", "no such user", "mailbox not found", "does not exist",
      "5.1.1 user unknown", "recipient not found", "domain not found"

    Примеры → 'blocked_or_policy' (НЕ bounced, НЕ удалять — адрес валиден):
      "550 rejected for policy", "554 message rejected as spam",
      "5.7.1 blocked", "5.7.2 policy violation", "blacklist",
      "believe this mail is spam", "non-local recipient verification failed",
      "recipient verification failed", "DMARC", "SPF", "DKIM"

    Примеры → 'temporary_failure' (НЕ bounced, НЕ удалять — временная проблема):
      "421", "451", "452", "ratelimit", "try again later",
      "temporarily unavailable", "greylisted", "timeout", "connection refused"
    """
    t = text.lower()

    # Порядок проверок: temporary → blocked → nonexistent.
    # Более конкретные (и более опасные) проверки — позже.
    # Если error-текст содержит и временный код, и слово nonexistent — временный побеждает.

    # ── 1. Временные ошибки — адрес рабочий, попробовать позже ────────────
    # НЕ bounced, НЕ удалять! Проверяем ПЕРВЫМИ.
    _TEMPORARY = [
        'ratelimit', 'rate limit', 'rate-limit',
        'too many messages', 'too many connections', 'too busy',
        'try again', 'try later', 'please retry', 'come back later',
        'temporarily', 'temporary', 'transient',
        'greylisted', 'greylisting', 'grey listed',
        'timeout', 'timed out',
        'connection refused', 'connection reset',
        'cannot connect', 'network unreachable', 'service unavailable',
        'mailbox full', 'over quota', 'quota exceeded', 'storage full',
        '421', '450', '451', '452',
    ]
    if any(x in t for x in _TEMPORARY):
        return 'temporary_failure'

    # ── 2. Антиспам, политика, репутация — адрес может быть рабочим ────────
    # НЕ bounced, НЕ удалять! Проверяем ВТОРЫМИ.
    _BLOCKED = [
        'spam', 'junk', 'blacklist', 'black list', 'blocklist',
        'blocked', 'blocking',
        'policy', 'rejected for policy', 'believe this mail is spam',
        'message rejected', 'relay denied', 'relay not permitted',
        'relay access denied',
        'access denied', 'sender rejected', 'sender not allowed',
        'reputation', 'dmarc', 'spf', 'dkim',
        'non-local recipient verification failed',
        'recipient verification failed',
        '5.7.0', '5.7.1', '5.7.2', '5.7.3', '5.7.4', '5.7.5',
        '5.7.6', '5.7.7', '5.7.8', '5.7.9',
    ]
    if any(x in t for x in _BLOCKED):
        return 'blocked_or_policy'

    # ── 3. Явные признаки несуществующего адреса/домена ────────────────────
    # ТОЛЬКО при этих признаках разрешено ставить status='bounced'. Проверяем ПОСЛЕДНИМИ.
    _NONEXISTENT = [
        'user unknown', 'unknown user', 'no such user', 'no such mailbox',
        'mailbox unavailable', 'mailbox not found', 'mailbox does not exist',
        'no mailbox here', 'invalid mailbox',
        'account does not exist',
        'user not found', 'recipient not found', 'address not found',
        'recipient address rejected: user unknown',
        'invalid recipient',
        'does not exist',
        'domain not found', 'no such domain',
        'host not found', 'unresolvable address',
        '5.1.1', '5.1.2', '5.1.3',
    ]
    if any(x in t for x in _NONEXISTENT):
        return 'nonexistent_email'

    # ── 4. 554/553/550 без явных слов — консервативно НЕ bounced ───────────
    # В России эти коды часто используются для спам-политики, а не несуществующих адресов.
    if '554' in t or '553' in t or '550' in t:
        return 'blocked_or_policy'

    # ── 5. Неизвестная причина — консервативно: адрес считать рабочим ──────
    return 'unknown_failure'


def _parse_bounce_details(msg) -> dict:
    """
    Извлекает упавшие адреса и причины из bounce-сообщения Mail.ru.
    Возвращает dict: {email: {'reason': reason_str, 'raw': raw_context_str}}

    raw — фрагмент DSN-текста, на основе которого принято решение (для аудита).
    """
    result = {}

    # 1. X-Failed-Recipients header (самый надёжный)
    header = msg.get('X-Failed-Recipients', '')
    for addr in _EMAIL_RE_BOUNCE.findall(header):
        result[addr.lower()] = {'reason': 'unknown_failure', 'raw': f'X-Failed-Recipients: {header.strip()}'}

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
            result[addr] = {'reason': reason, 'raw': context.strip()[:500]}

    # Final-Recipient (RFC 3464) — извлекаем Diagnostic-Code как raw
    dsn_re = re.compile(
        r'Final-Recipient[^:]*:[^\n]*rfc822;?\s*([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})'
        r'(?:[^\n]*\n)*?(?:Diagnostic-Code[^:]*:\s*([^\n]+))?',
        re.I
    )
    for m in dsn_re.finditer(body):
        addr = m.group(1).lower()
        diag = (m.group(2) or '').strip()
        if addr not in result:
            raw_ctx = diag if diag else 'Final-Recipient (no Diagnostic-Code)'
            reason = _classify_bounce_reason(diag) if diag else 'unknown_failure'
            result[addr] = {'reason': reason, 'raw': raw_ctx[:500]}
        elif diag and result[addr]['reason'] == 'unknown_failure':
            # Уточняем причину если нашли Diagnostic-Code
            new_reason = _classify_bounce_reason(diag)
            result[addr] = {'reason': new_reason, 'raw': diag[:500]}

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

    # Загружаем Message-ID уже обработанных bounce-уведомлений для дедупликации.
    # Без этого каждый вызов check_bounces() обрабатывает одни и те же IMAP-сообщения
    # снова и снова, накапливая bounce_count до 100+ и ложно финализируя контакты.
    _conn_dup = get_db()
    processed_bounce_msg_ids: set = {
        r[0] for r in _conn_dup.execute(
            "SELECT msg_id FROM notifications WHERE type='bounce' AND msg_id IS NOT NULL"
        ).fetchall()
    }
    _conn_dup.close()

    # Собираем ID bounce-сообщений по нескольким критериям.
    # UNSEEN — обрабатываем только непрочитанные сообщения.
    # mail.fetch(RFC822) автоматически ставит флаг \Seen на Mail.ru/Dovecot,
    # поэтому повторный запуск не найдёт уже обработанные письма.
    msg_ids: set = set()
    for crit in [
        b'UNSEEN FROM "MAILER-DAEMON"',
        b'UNSEEN FROM "mailer-daemon"',
        b'UNSEEN SUBJECT "Mail failure"',
        b'UNSEEN SUBJECT "delivery"',
        b'UNSEEN SUBJECT "undeliverable"',
        b'UNSEEN SUBJECT "Undeliverable"',
        b'UNSEEN SUBJECT "failed"',
    ]:
        try:
            st, data = mail.search(None, crit)
            if st == 'OK' and data[0]:
                for mid in data[0].split():
                    msg_ids.add(mid)
        except Exception:
            pass

    # Парсим сообщения — собираем {email: {'reason': str, 'raw': str}}.
    # \Seen НЕ ставим здесь — только после успешного commit в БД (см. ниже).
    bounced_with_reasons: dict = {}       # email → reason_type
    bounce_raw_texts: dict = {}           # email → raw DSN text для аудита
    bounce_msg_ids: dict = {}             # email → Message-ID для дедупликации
    successfully_parsed_mids: dict = {}  # msg_id_header → imap mid (для post-commit \Seen)

    for mid in msg_ids:
        try:
            st, data = mail.fetch(mid, b'(RFC822)')
            if st != 'OK':
                continue
            msg = emaillib.message_from_bytes(data[0][1])

            # Сначала парсим — результат нужен для synthetic Message-ID.
            # Synthetic ID должен включать parsed content (extracted emails + raw reason),
            # иначе разные bounce-письма с одинаковой темой/датой склеиваются в один ID.
            details = _parse_bounce_details(msg)

            msg_id_header = msg.get('Message-ID', '').strip()
            if not msg_id_header:
                # Synthetic ID: Date + Subject + From + To + extracted_emails + raw_reasons.
                # Включаем parsed content для устойчивой дедупликации без Message-ID.
                date_h = msg.get('Date', '')
                subj_h = msg.get('Subject', '')
                from_h = msg.get('From', '')
                to_h   = msg.get('To', '')
                extracted_emails = ','.join(sorted(details.keys()))
                raw_reasons = ','.join(sorted(v['raw'][:120] for v in details.values()))
                raw_key = '\x00'.join([date_h, subj_h, from_h, to_h, extracted_emails, raw_reasons])
                if raw_key.replace('\x00', '').strip():
                    msg_id_header = 'synthetic:' + hashlib.md5(raw_key.encode('utf-8', 'ignore')).hexdigest()

            # Дедупликация: persistent в БД, переживает перезапуски приложения.
            if msg_id_header and msg_id_header in processed_bounce_msg_ids:
                continue

            for addr, info in details.items():
                if addr not in bounced_with_reasons:
                    bounced_with_reasons[addr] = info['reason']
                    bounce_raw_texts[addr]     = info['raw']
                    if msg_id_header:
                        bounce_msg_ids[addr]   = msg_id_header

            # Трекаем mid для \Seen после commit. Если commit упадёт —
            # письмо останется UNSEEN и будет обработано повторно.
            if msg_id_header:
                successfully_parsed_mids[msg_id_header] = mid

        except Exception:
            continue

    # ── Вспомогательная функция: помечает IMAP-письма \Seen ─────────────────
    def _mark_seen_after_commit():
        """Вызывается ТОЛЬКО после успешного conn.commit()."""
        for _mid in successfully_parsed_mids.values():
            try:
                mail.store(_mid, '+FLAGS', '\\Seen')
            except Exception:
                pass

    if not bounced_with_reasons:
        # Нет новых bounce-адресов. Письма обработаны (возможно, все адреса
        # не из нашей базы) — помечаем \Seen и завершаем без DB-записей.
        _mark_seen_after_commit()
        try:
            mail.logout()
        except Exception:
            pass
        return {'ok': True, 'total': len(msg_ids), 'new': 0, 'bounced': []}

    # Получаем все email из нашей базы — обрабатываем только известные
    new_count   = 0
    bounced_list = []
    db_committed = False
    conn = get_db()
    try:
        known_contacts = {
            r['email'].lower(): dict(r)
            for r in conn.execute(
                "SELECT id, email, status, company_name FROM contacts WHERE email IS NOT NULL AND email != ''"
            ).fetchall()
        }

        for addr, reason in bounced_with_reasons.items():
            # ── GUARD: только nonexistent_email может вести к bounced/удалению ──
            # blocked_or_policy, temporary_failure, unknown_failure —
            # адрес остаётся в базе как рабочий контакт, НЕ помечается bounced,
            # bounce_count НЕ увеличивается, контакт НЕ удаляется.
            if reason != 'nonexistent_email':
                raw_text = bounce_raw_texts.get(addr, '')
                if addr in known_contacts:
                    if reason == 'blocked_or_policy':
                        err = f'Заблокировано: антиспам или политика сервера. {raw_text}'[:500]
                        conn.execute(
                            """UPDATE mailing_recipients
                               SET status='blocked', last_error=?
                               WHERE lower(email)=?
                                 AND status != 'bounced'""",
                            (err, addr)
                        )
                    elif reason == 'temporary_failure':
                        err = f'Временная ошибка доставки, адрес не изменён. {raw_text}'[:500]
                        conn.execute(
                            """UPDATE mailing_recipients
                               SET last_error=?
                               WHERE lower(email)=?
                                 AND status != 'bounced'""",
                            (err, addr)
                        )
                    # unknown_failure: никаких изменений — email остаётся как есть
                company_name = (known_contacts[addr].get('company_name') or '') if addr in known_contacts else ''
                bounced_list.append({'email': addr, 'company': company_name, 'reason': reason})
                continue

            if addr not in known_contacts:
                continue

            contact = known_contacts[addr]
            company = contact.get('company_name') or ''
            company_str = f' ({company})' if company else ''

            current_status = contact.get('status', '')
            bounce_count   = contact.get('bounce_count') or 0
            was_confirmed  = (current_status == 'bounced')

            # ── Правило двух сигналов ──────────────────────────────────────
            # Сигнал 1: текущий hard bounce с raw DSN и reason=nonexistent_email
            # Сигнал 2: предыдущий bounce (bounce_count > 0) — другое IMAP-письмо,
            #           другой Message-ID (UNSEEN-фильтр гарантирует независимость).
            #
            # dead MX убран из two_signals: DNS-сбой ≠ несуществующий адрес.
            two_signals = bounce_count > 0

            raw_bounce    = bounce_raw_texts.get(addr, '')
            bounce_msg_id = bounce_msg_ids.get(addr)

            if two_signals:
                # Подтверждённый несуществующий адрес — второй независимый сигнал.
                # Только UPDATE. DELETE contacts никогда не выполняется.
                conn.execute(
                    """UPDATE contacts SET status='bounced', bounce_count=bounce_count+1
                       WHERE lower(email)=? AND status != 'bounced'""",
                    (addr,)
                )
                conn.execute(
                    "UPDATE mailing_recipients SET status='bounced' WHERE lower(email)=? AND status!='bounced'",
                    (addr,)
                )
                send_row = conn.execute(
                    """SELECT sr.id, sr.send_id FROM send_recipients sr
                       WHERE lower(sr.email)=? AND sr.status='sent'
                       ORDER BY sr.send_id DESC LIMIT 1""", (addr,)
                ).fetchone()
                if send_row:
                    conn.execute("UPDATE send_recipients SET status='bounced' WHERE id=?", (send_row['id'],))
                    conn.execute(
                        "UPDATE send_history SET total_failed=total_failed+1, status='partial' WHERE id=?",
                        (send_row['send_id'],)
                    )
                if not was_confirmed:
                    summary = f'{addr}{company_str} — адрес не существует, подтверждено 2 bounce-сигналами. Исключён из рассылки.'
                    notif_details = {
                        'from_email':        addr, 'company': company,
                        'action_done':       'Адрес исключён из рассылки (2 подтверждённых bounce с raw DSN)',
                        'body_preview':      'Bounce: адрес не существует (сигнал 2/2)',
                        'raw_bounce_reason': raw_bounce,
                        'reason_type':       'nonexistent_email',
                    }
                    conn.execute(
                        """INSERT INTO notifications
                           (type,contact_id,company_name,from_email,summary,details_json,msg_id)
                           VALUES('bounce',?,?,?,?,?,?)""",
                        (contact.get('id'), company, addr, summary,
                         json.dumps(notif_details, ensure_ascii=False), bounce_msg_id)
                    )
                    new_count += 1
            else:
                # Первый сигнал — probable_bounce только при наличии raw DSN.
                # probable_bounce значит: "есть реальный DSN с reason=nonexistent_email,
                # ждём второго независимого сигнала для подтверждения".
                conn.execute(
                    "UPDATE contacts SET bounce_count=1 WHERE lower(email)=?", (addr,)
                )
                last_err = f'[nonexistent_email] {raw_bounce}'[:500] if raw_bounce \
                    else '[nonexistent_email] Bounce: адрес не найден на сервере (нет raw DSN)'
                conn.execute(
                    """UPDATE mailing_recipients
                       SET status='probable_bounce', last_error=?
                       WHERE lower(email)=? AND status NOT IN ('bounced','probable_bounce','needs_review')""",
                    (last_err, addr)
                )
                if current_status not in ('bounced', 'probable_bounce'):
                    summary = f'{addr}{company_str} — bounce получен (сигнал 1/2). Повторный bounce подтвердит исключение.'
                    notif_details = {
                        'from_email':        addr, 'company': company,
                        'action_done':       'Помечен probable_bounce (сигнал 1/2, raw DSN сохранён)',
                        'body_preview':      'Bounce: адрес не существует (сигнал 1/2)',
                        'raw_bounce_reason': raw_bounce,
                        'reason_type':       'nonexistent_email',
                    }
                    conn.execute(
                        """INSERT INTO notifications
                           (type,contact_id,company_name,from_email,summary,details_json,msg_id)
                           VALUES('bounce',?,?,?,?,?,?)""",
                        (contact.get('id'), company, addr, summary,
                         json.dumps(notif_details, ensure_ascii=False), bounce_msg_id)
                    )
                    new_count += 1
            bounced_list.append({'email': addr, 'company': company, 'reason': reason})

        conn.commit()
        db_committed = True

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    # Помечаем IMAP-письма \Seen ТОЛЬКО после успешного commit.
    # Если commit упал — письма остаются UNSEEN для повторной обработки.
    if db_committed:
        _mark_seen_after_commit()

    try:
        mail.logout()
    except Exception:
        pass

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
    # Russian
    'больше нет', 'больше с нами нет', 'покинул', 'уволился', 'ушёл из компании',
    'не работает в', 'не является сотрудником', 'умер', 'скончался',
    'к нашему огромному сожалению', 'к сожалению', 'не работает данный адрес',
    'данный почтовый ящик', 'данный адрес',
    # English
    'no longer with us', 'no longer employed', 'has left the company',
    'left the company', 'is no longer', 'no longer works', 'left our company',
    'departed from', 'is not available anymore', 'has departed',
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


_GENERIC_EMAIL_PREFIXES = {'info', 'mail', 'office', 'admin', 'support', 'noreply',
                           'no-reply', 'postmaster', 'sales', 'contact', 'hello', 'help'}

# Шаблон для пар «Имя Фамилия[,—] email@domain» в структурированных письмах
_PAIR_RE = re.compile(
    r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁа-яёA-Z][а-яёA-Za-z.]{0,20}){1,2})'  # Имя (И.О. или полное)
    r'[\s,\-—.]+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})',
    re.M
)


def _extract_contacts_from_text(text: str, exclude_emails: set | None = None) -> dict:
    """Извлекает email, телефон, имена из текста. Возвращает все найденные + пары имя→email."""
    exclude_emails = {e.lower() for e in (exclude_emails or [])}
    exclude_emails.add(get_setting('smtp_user', '').lower())

    all_found = _EMAIL_RE_BOUNCE.findall(text)
    seen: set = set()
    emails = []
    for e in all_found:
        el = e.lower()
        if el in exclude_emails or el in seen or '.' not in el.split('@')[-1]:
            continue
        seen.add(el)
        emails.append(el)

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

    # Пары «Имя → email» из структурированных писем ("Галаган Н.М., n.galagan@domain.ru")
    pairs: dict[str, str] = {}
    for rus_name, addr in _PAIR_RE.findall(text):
        al = addr.lower()
        if al not in exclude_emails:
            pairs[al] = rus_name.strip()
            if al not in seen:
                seen.add(al)
                emails.append(al)

    return {
        'emails': emails[:10],
        'phones': [re.sub(r'[^\d+]', '', p) for p in phones[:3]],
        'name':   name,
        'pairs':  pairs,   # {email: имя} — найденные пары
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


_SIG_MARKERS = re.compile(
    r'^\s*(-{2,}|_{2,}|С уважением[,.]?|Best regards[,.]?|Regards[,.]?|Sincerely[,.]?|Спасибо[,.]?)\s*$',
    re.I | re.M
)
_SIG_PHONE_RE = re.compile(r'(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}')
_SIG_TITLE_RE = re.compile(
    r'^[\s•\-]*([А-ЯЁA-Z][а-яёa-z\s,А-ЯЁA-Z]{5,60}(?:директор|менеджер|руководитель|начальник|'
    r'специалист|бухгалтер|юрист|аналитик|coordinator|manager|director|head|chief)[а-яёa-z\s,А-ЯЁA-Z]{0,40})',
    re.I | re.M
)


def _parse_signature(body: str) -> dict:
    """
    Извлекает из подписи письма: телефон и должность.
    Ищет блок после стандартных маркеров подписи (---, С уважением, и т.п.)
    """
    result: dict = {'phone': None, 'title': None}
    # Ищем начало подписи
    m = _SIG_MARKERS.search(body)
    sig_block = body[m.start():] if m else body[-600:]  # последние 600 символов как fallback

    phone_m = _SIG_PHONE_RE.search(sig_block)
    if phone_m:
        result['phone'] = re.sub(r'[^\d+]', '', phone_m.group())

    title_m = _SIG_TITLE_RE.search(sig_block)
    if title_m:
        result['title'] = title_m.group(1).strip()

    return result


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
    # Domain → company info для сопоставления неизвестных отправителей с известными компаниями
    companies_by_domain: dict = {}
    for _e, _c in contacts_by_email.items():
        _d = _e.split('@')[1] if '@' in _e else ''
        if _d and _d not in companies_by_domain:
            companies_by_domain[_d] = _c
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
            # Если отправитель не в базе — пробуем найти компанию по домену email
            from_domain = from_raw.split('@')[1] if '@' in from_raw else ''
            company_by_domain = companies_by_domain.get(from_domain) if not contact else None
            company_name = (
                (contact['company_name'] if contact else None)
                or (company_by_domain['company_name'] if company_by_domain else None)
            )

            # Пропускаем если: отправитель не в базе, нет domain-match, нет нашей темы,
            # нет gone/ooo-ключей в теле
            if not contact and not company_by_domain and _OUR_SUBJECT not in subj.lower():
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

                if reply_type == 'gone':
                    # Работаем даже если контакта нет в базе —
                    # главное добавить новые адреса из письма.
                    # Метаданные компании берём из контакта или из domain-match.
                    co_info = contact or company_by_domain
                    co_name = company_name  # уже включает domain-match из company_name
                    website = co_info.get('website') if co_info else None
                    segment = co_info.get('segment') if co_info else None
                    region  = co_info.get('region')  if co_info else None

                    if contact:
                        conn2.execute(
                            "UPDATE contacts SET status='bounced' WHERE id=?",
                            (contact['id'],)
                        )
                        conn2.execute(
                            "UPDATE mailing_recipients SET status='bounced' WHERE lower(email)=?",
                            (from_raw,)
                        )
                        actions.append(f'email {from_raw} помечен как недействительный')

                    new_emails = extracted['emails']
                    new_phones = extracted['phones']
                    pairs      = extracted.get('pairs', {})   # {email: имя из структур. письма}

                    for new_email in new_emails:
                        # Пропускаем generic-адреса (info@, mail@, ...) — не личные контакты
                        local_part = new_email.split('@')[0]
                        if local_part in _GENERIC_EMAIL_PREFIXES:
                            continue
                        exists = conn2.execute(
                            "SELECT id FROM contacts WHERE lower(email)=?", (new_email,)
                        ).fetchone()
                        if not exists:
                            # Имя берём из пары (если нашли в тексте), иначе общее
                            paired_name = pairs.get(new_email) or extracted['name']
                            conn2.execute(
                                """INSERT INTO contacts
                                   (company_name, website, person_name, email,
                                    phone, segment, region, date_found, status, notes)
                                   VALUES (?,?,?,?,?,?,?,?,'new',?)""",
                                (co_name, website, paired_name, new_email,
                                 new_phones[0] if new_phones else None,
                                 segment, region, today,
                                 f'Добавлен из ответа на рассылку (замена {from_raw})')
                            )
                            label = f'{paired_name} <{new_email}>' if paired_name else new_email
                            actions.append(f'добавлен контакт: {label}')

                elif reply_type in ('ooo', 'reply') and (contact or company_by_domain):
                    # Автоответ или обычный ответ: дополняем карточку новыми данными.
                    # Метаданные компании берём из контакта или из domain-match.
                    co_info = contact or company_by_domain
                    new_phones = extracted['phones']
                    new_emails = [e for e in extracted['emails'] if e != from_raw]
                    pairs = extracted.get('pairs', {})

                    # Обновляем телефон исходного контакта если не заполнен
                    if contact and new_phones:
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
                        # Пропускаем generic-адреса (info@, mail@, ...) — не личные контакты
                        local_part = new_email.split('@')[0]
                        if local_part in _GENERIC_EMAIL_PREFIXES:
                            continue
                        exists = conn2.execute(
                            "SELECT id FROM contacts WHERE lower(email)=?", (new_email,)
                        ).fetchone()
                        if not exists:
                            paired_name = pairs.get(new_email) or extracted['name']
                            conn2.execute(
                                """INSERT INTO contacts
                                   (company_name, website, person_name, email,
                                    phone, segment, region, date_found, status, notes)
                                   VALUES (?,?,?,?,?,?,?,?,'new',?)""",
                                (co_info['company_name'], co_info.get('website'),
                                 paired_name,
                                 new_email,
                                 new_phones[0] if new_phones else None,
                                 co_info.get('segment'), co_info.get('region'),
                                 today,
                                 f'Добавлен из {"автоответа" if reply_type=="ooo" else "ответа"} {from_raw}')
                            )
                            label = f'{paired_name} <{new_email}>' if paired_name else new_email
                            actions.append(f'добавлен контакт: {label}')

                # Пункт 6: Парсинг подписи — обновляем телефон и должность контакта
                if contact:
                    sig = _parse_signature(body)
                    sig_updates = []
                    if sig['phone']:
                        existing = conn2.execute(
                            "SELECT mobile_phone, generic_phone FROM contacts WHERE id=?",
                            (contact['id'],)
                        ).fetchone()
                        if existing and not existing['mobile_phone'] and not existing['generic_phone']:
                            conn2.execute(
                                "UPDATE contacts SET mobile_phone=? WHERE id=?",
                                (sig['phone'], contact['id'])
                            )
                            sig_updates.append(f'телефон из подписи: {sig["phone"]}')
                    if sig['title']:
                        existing_title = conn2.execute(
                            "SELECT title FROM contacts WHERE id=?", (contact['id'],)
                        ).fetchone()
                        if existing_title and not existing_title['title']:
                            conn2.execute(
                                "UPDATE contacts SET title=? WHERE id=?",
                                (sig['title'], contact['id'])
                            )
                            sig_updates.append(f'должность из подписи: {sig["title"]}')
                    if sig_updates:
                        actions.extend(sig_updates)

                # Пункт 3: Обновляем last_verified_at — человек активен (ответил на письмо)
                if contact and reply_type in ('ooo', 'reply'):
                    update_contact_verified(conn2, contact['id'])

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
