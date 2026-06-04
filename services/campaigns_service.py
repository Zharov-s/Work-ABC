"""
campaigns_service.py — campaign lifecycle and stats aggregation.
Works alongside the existing send_history / send_recipients tables.
"""
from __future__ import annotations
from database import get_db, get_mailing_stats


def get_campaign_list(limit: int = 30) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM send_history ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_campaign_detail(send_id: int) -> dict | None:
    conn = get_db()
    send = conn.execute('SELECT * FROM send_history WHERE id=?', (send_id,)).fetchone()
    if not send:
        conn.close()
        return None
    send = dict(send)

    recipients = [dict(r) for r in conn.execute(
        'SELECT * FROM send_recipients WHERE send_id=? ORDER BY id', (send_id,)
    ).fetchall()]

    opens  = conn.execute('SELECT COUNT(DISTINCT token) FROM email_opens  WHERE send_id=?', (send_id,)).fetchone()[0]
    clicks = conn.execute('SELECT COUNT(DISTINCT token) FROM email_clicks WHERE send_id=? AND is_unsubscribe=0', (send_id,)).fetchone()[0]
    unsubs = conn.execute('SELECT COUNT(DISTINCT token) FROM email_clicks WHERE send_id=? AND is_unsubscribe=1', (send_id,)).fetchone()[0]

    total   = len(recipients)
    sent    = sum(1 for r in recipients if r['status'] == 'sent')
    bounced = sum(1 for r in recipients if r['status'] == 'bounced')
    failed  = sum(1 for r in recipients if r['status'] in ('failed', 'bounced'))

    def pct(n): return round(n / total * 100, 1) if total else 0.0

    send['stats'] = {
        'total': total, 'sent': sent, 'failed': failed, 'bounced': bounced,
        'opens': opens, 'clicks': clicks, 'unsubs': unsubs,
        'open_rate': pct(opens), 'click_rate': pct(clicks), 'unsub_rate': pct(unsubs),
        'delivered_rate': pct(sent), 'failed_rate': pct(failed),
    }
    send['recipients'] = recipients
    conn.close()
    return send


def get_mailing_pool_stats() -> dict:
    return get_mailing_stats()


def get_summary_stats() -> dict:
    """Dashboard-level campaign stats."""
    conn = get_db()
    total_campaigns = conn.execute('SELECT COUNT(*) FROM send_history').fetchone()[0]
    total_sent      = conn.execute('SELECT SUM(total_sent) FROM send_history').fetchone()[0] or 0
    total_failed    = conn.execute('SELECT SUM(total_failed) FROM send_history').fetchone()[0] or 0
    total_opens     = conn.execute('SELECT COUNT(DISTINCT token) FROM email_opens').fetchone()[0]
    total_clicks    = conn.execute('SELECT COUNT(DISTINCT token) FROM email_clicks WHERE is_unsubscribe=0').fetchone()[0]
    total_unsubs    = conn.execute('SELECT COUNT(DISTINCT token) FROM email_clicks WHERE is_unsubscribe=1').fetchone()[0]
    conn.close()
    return {
        'total_campaigns': total_campaigns, 'total_sent': total_sent,
        'total_failed': total_failed, 'total_opens': total_opens,
        'total_clicks': total_clicks, 'total_unsubs': total_unsubs,
        'open_rate':  round(total_opens  / total_sent * 100, 1) if total_sent else 0.0,
        'click_rate': round(total_clicks / total_sent * 100, 1) if total_sent else 0.0,
        'unsub_rate': round(total_unsubs / total_sent * 100, 1) if total_sent else 0.0,
    }
