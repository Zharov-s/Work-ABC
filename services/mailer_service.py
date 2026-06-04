"""
mailer_service.py — thin wrapper around mailer.py.
Keeps existing send logic intact; adds pre-send validation and
audience building from the new companies data model.
"""
from __future__ import annotations
import re
from database import get_db, normalize_mailing_email
from mailer import (
    send_campaign as _send_campaign,
    send_pending_campaign as _send_pending,
    retry_failed_send as _retry,
    check_bounces as _check_bounces,
    scan_replies as _scan_replies,
    test_smtp as _test_smtp,
    TEMPLATE_META,
    BATCH_SIZE,
)


# ── Re-exports ────────────────────────────────────────────────────────────────
def send_campaign(template_key: str, raw_addresses: str) -> dict:
    return _send_campaign(template_key, raw_addresses)

def send_pending_campaign(template_key: str, requested_count=None) -> dict:
    return _send_pending(template_key, requested_count)

def retry_failed_send(send_id: int) -> dict:
    return _retry(send_id)

def check_bounces() -> dict:
    return _check_bounces()

def scan_replies() -> dict:
    return _scan_replies()

def test_smtp() -> dict:
    return _test_smtp()

def get_templates() -> dict:
    return TEMPLATE_META


# ── Audience building ─────────────────────────────────────────────────────────
def build_audience_from_filter(filter_req: dict, template_key: str) -> dict:
    """
    Build mailing audience from companies filter.
    Returns {emails, companies_count, skipped, reasons}.
    """
    from services.filters_service import build_filter_where
    from repositories.companies_repo import list_companies

    where, params = build_filter_where(filter_req)
    rows, total = list_companies(where, params, page=1, per_page=10000)

    emails: list[dict] = []
    skipped: list[dict] = []

    # Emails already sent for this template
    conn = get_db()
    sent_emails: set = set()
    sent_rows = conn.execute(
        """SELECT DISTINCT lower(sr.email) AS email
           FROM send_recipients sr
           JOIN send_history sh ON sr.send_id = sh.id
           WHERE sh.template = ? AND sr.status = 'sent'""",
        (template_key,)
    ).fetchall()
    sent_emails = {r['email'] for r in sent_rows}

    # Bounced/unsubscribed from company_channels
    bad_emails: set = set()
    bad_rows = conn.execute(
        "SELECT lower(value) as v FROM company_channels WHERE channel_type='email' AND status IN ('bounced','unsubscribed')"
    ).fetchall()
    bad_emails = {r['v'] for r in bad_rows}

    conn.close()

    for r in rows:
        company_id   = r.get('company_id', '')
        company_name = r.get('company_name_original', '')

        # Get all email channels for this company
        conn2 = get_db()
        ch_rows = conn2.execute(
            "SELECT value, status FROM company_channels WHERE company_id=? AND channel_type='email' ORDER BY is_primary DESC",
            (company_id,)
        ).fetchall()
        conn2.close()

        # Also check direct emails_all field
        emails_all = r.get('emails_all', '') or ''
        raw_emails = [ch['value'] for ch in ch_rows]
        if not raw_emails and emails_all:
            raw_emails = [e.strip() for e in emails_all.split(';') if e.strip()]

        if not raw_emails:
            skipped.append({'company': company_name, 'reason': 'no_email'})
            continue

        added = False
        for raw_email in raw_emails:
            normalized = normalize_mailing_email(raw_email)
            if not normalized:
                continue
            nl = normalized.lower()
            if nl in bad_emails:
                skipped.append({'company': company_name, 'reason': 'bounced_or_unsubscribed', 'email': normalized})
                continue
            if nl in sent_emails:
                skipped.append({'company': company_name, 'reason': 'already_sent', 'email': normalized})
                continue
            emails.append({'email': normalized, 'company_id': company_id, 'company': company_name})
            added = True
            break  # Use first valid email per company

        if not added and raw_emails:
            skipped.append({'company': company_name, 'reason': 'all_filtered'})

    return {
        'emails':          emails,
        'total_companies': total,
        'ready_count':     len(emails),
        'skipped_count':   len(skipped),
        'skipped':         skipped[:50],  # cap for response size
    }


# ── Pre-send validation ───────────────────────────────────────────────────────
def validate_before_send(emails: list[str], template_key: str, test_sent: bool) -> dict:
    """Validate audience before campaign launch. Returns {ok, checks, errors}."""
    checks = []
    errors = []

    def chk(label: str, ok: bool, detail: str = ''):
        checks.append({'label': label, 'ok': ok, 'detail': detail})
        if not ok:
            errors.append(label + (': ' + detail if detail else ''))

    chk('HTML-шаблон существует', template_key in TEMPLATE_META,
        '' if template_key in TEMPLATE_META else f'Шаблон «{template_key}» не найден')

    chk('Есть получатели', len(emails) > 0,
        'Список получателей пуст' if not emails else f'{len(emails)} адресов')

    # No duplicates
    uniq = len(set(e.lower() for e in emails))
    chk('Нет дублей email', uniq == len(emails),
        f'{len(emails) - uniq} дублей' if uniq != len(emails) else '')

    # All valid format
    invalid = [e for e in emails if not normalize_mailing_email(e)]
    chk('Все email валидны', len(invalid) == 0,
        f'Невалидные: {", ".join(invalid[:5])}' if invalid else '')

    # Test sent
    chk('Тестовое письмо отправлено', test_sent, 'Отправьте тест перед запуском' if not test_sent else '')

    return {'ok': len(errors) == 0, 'checks': checks, 'errors': errors}
