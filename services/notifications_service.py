"""
notifications_service.py — create and manage app notifications.
Works with the existing notifications table.
All notification creation funnels through create_notification().
"""
from __future__ import annotations
import json
from database import get_db

# ── Notification type catalogue ───────────────────────────────────────────────
NOTIFICATION_TYPES = {
    'bounce':                  {'label': 'Bounce',               'icon': '⚠️',  'color': 'red'},
    'reply':                   {'label': 'Ответ',                'icon': '💬',  'color': 'green'},
    'ooo':                     {'label': 'Автоответ',            'icon': '📭',  'color': 'yellow'},
    'gone':                    {'label': 'Ушёл из компании',     'icon': '🚪',  'color': 'red'},
    'campaign_completed':      {'label': 'Рассылка завершена',   'icon': '✅',  'color': 'green'},
    'campaign_failed':         {'label': 'Ошибка рассылки',      'icon': '❌',  'color': 'red'},
    'new_replies_detected':    {'label': 'Новые ответы',         'icon': '💬',  'color': 'green'},
    'contacts_need_update':    {'label': 'Контакты на замену',   'icon': '🔄',  'color': 'yellow'},
    'external_search_completed':{'label': 'Поиск завершён',      'icon': '🔍',  'color': 'blue'},
    'import_completed':        {'label': 'Импорт завершён',      'icon': '📥',  'color': 'blue'},
    'data_quality_warning':    {'label': 'Качество данных',      'icon': '⚠️',  'color': 'yellow'},
}


def create_notification(
    type_: str,
    summary: str,
    details: dict | None = None,
    company_name: str = '',
    from_email: str = '',
    contact_id: int | None = None,
    msg_id: str | None = None,
) -> int | None:
    """
    Insert a notification. Returns new id or None if msg_id dedup skipped it.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO notifications
               (type, contact_id, company_name, from_email, summary, details_json, msg_id)
               VALUES (?,?,?,?,?,?,?)""",
            (type_, contact_id, company_name, from_email, summary,
             json.dumps(details or {}, ensure_ascii=False), msg_id)
        )
        conn.commit()
        return cur.lastrowid if cur.rowcount else None
    finally:
        conn.close()


def create_campaign_notification(send_result: dict, template_name: str = '') -> int | None:
    """
    Create a campaign_completed or campaign_failed notification.
    send_result: dict returned by mailer.py send functions.
    """
    ok           = send_result.get('ok', False)
    total_sent   = send_result.get('total_sent', 0)
    total_failed = send_result.get('total_failed', 0)
    subject      = send_result.get('subject', template_name)

    # Get opens/clicks/replies/bounces from latest send_history
    conn = get_db()
    latest = conn.execute(
        "SELECT id FROM send_history ORDER BY id DESC LIMIT 1"
    ).fetchone()
    opens = clicks = replies = bounced = 0
    if latest:
        sid = latest['id']
        opens   = conn.execute('SELECT COUNT(DISTINCT token) FROM email_opens  WHERE send_id=?', (sid,)).fetchone()[0]
        clicks  = conn.execute('SELECT COUNT(DISTINCT token) FROM email_clicks WHERE send_id=? AND is_unsubscribe=0', (sid,)).fetchone()[0]
        bounced = conn.execute("SELECT COUNT(*) FROM send_recipients WHERE send_id=? AND status='bounced'", (sid,)).fetchone()[0]
    conn.close()

    ntype   = 'campaign_completed' if ok else 'campaign_failed'
    summary = (
        f'Рассылка завершена: «{subject}» — '
        f'отправлено {total_sent}, ошибок {total_failed}'
    ) if ok else f'Ошибка рассылки «{subject}»'

    details = {
        'subject':      subject,
        'total_sent':   total_sent,
        'total_failed': total_failed,
        'opens':        opens,
        'clicks':       clicks,
        'bounced':      bounced,
        'tracking':     send_result.get('tracking', False),
    }

    return create_notification(ntype, summary, details)


def create_search_completed_notification(run_result: dict) -> int | None:
    saved = run_result.get('saved', 0)
    stats = run_result.get('stats', {})
    summary = f'Поиск завершён: {saved} кандидатов · {stats.get("new", 0)} новых · {stats.get("duplicate", 0)} дублей'
    return create_notification('external_search_completed', summary, run_result)


def create_import_completed_notification(count: int, source: str = '') -> int | None:
    summary = f'Импорт завершён: добавлено {count} компаний' + (f' из {source}' if source else '')
    return create_notification('import_completed', summary, {'count': count, 'source': source})


def create_data_quality_warning(company_name: str, issue: str) -> int | None:
    summary = f'Проблема качества данных: {company_name} — {issue}'
    return create_notification('data_quality_warning', summary,
                               {'issue': issue}, company_name=company_name)


def get_unread_count() -> int:
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM notifications WHERE read_at IS NULL").fetchone()[0]
    conn.close()
    return n


def get_notifications(limit: int = 50) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT id, type, company_name, from_email, summary, details_json,
                  created_at, read_at
           FROM notifications ORDER BY id DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['details'] = json.loads(d.pop('details_json') or '{}')
        except Exception:
            d['details'] = {}
        # Enrich with type meta
        meta = NOTIFICATION_TYPES.get(d['type'], {'label': d['type'], 'icon': '📌', 'color': 'gray'})
        d['type_label'] = meta['label']
        d['type_icon']  = meta['icon']
        d['type_color'] = meta['color']
        result.append(d)
    return result
