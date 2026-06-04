"""
contacts_service.py — contact lifecycle management.
Works with company_channels + contact_change_log (new model)
AND legacy contacts table (preserved, not deleted).
"""
from __future__ import annotations
import re
from database import get_db, normalize_mailing_email

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _log(conn, company_id, channel_id, contact_id, change_type,
         old_value='', new_value='', reason='', source='manual', actor='user'):
    conn.execute(
        """INSERT INTO contact_change_log
           (company_id, channel_id, contact_id, change_type,
            old_value, new_value, reason, source, actor)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (company_id, channel_id, contact_id,
         change_type, old_value, new_value, reason, source, actor)
    )


# ── Bounce ────────────────────────────────────────────────────────────────────
def handle_bounce(channel_id: int, reason: str = '') -> dict:
    """
    Mark a channel as bounced, exclude from mailings.
    Also updates legacy contacts table.
    """
    conn = get_db()
    ch = conn.execute('SELECT * FROM company_channels WHERE id=?', (channel_id,)).fetchone()
    if not ch:
        conn.close()
        return {'ok': False, 'error': 'Канал не найден'}

    ch = dict(ch)
    old_status = ch.get('status', 'active')

    # Update channel
    conn.execute(
        """UPDATE company_channels
           SET status='bounced',
               bounce_count=COALESCE(bounce_count,0)+1,
               updated_at=datetime('now')
           WHERE id=?""",
        (channel_id,)
    )

    # Also update legacy contacts table if email matches
    if ch['channel_type'] == 'email':
        conn.execute(
            """UPDATE contacts SET status='bounced',
               bounce_count=COALESCE(bounce_count,0)+1
               WHERE lower(email)=? OR lower(personal_email)=? OR lower(generic_email)=?""",
            (ch['value'].lower(),) * 3
        )
        # Add to mailing suppression
        conn.execute(
            "UPDATE mailing_recipients SET status='bounced' WHERE lower(email)=?",
            (ch['value'].lower(),)
        )

    _log(conn, ch.get('company_id'), channel_id, None,
         'bounced', old_status, 'bounced', reason or 'Bounce получен', 'system')

    conn.commit()
    conn.close()
    return {'ok': True, 'channel_id': channel_id, 'status': 'bounced'}


# ── Add from reply ────────────────────────────────────────────────────────────
def add_contact_from_reply(
    company_id: str,
    channel_type: str,
    value: str,
    contact_name: str = '',
    source_email: str = '',
) -> dict:
    """
    Add a new contact found in a reply email.
    Status: needs_review — shown to user for confirmation.
    """
    value = value.strip()
    if channel_type == 'email' and not EMAIL_RE.match(value.lower()):
        return {'ok': False, 'error': 'Невалидный email'}

    conn = get_db()
    existing = conn.execute(
        'SELECT id, status FROM company_channels WHERE company_id=? AND channel_type=? AND lower(value)=?',
        (company_id, channel_type, value.lower())
    ).fetchone()

    if existing:
        conn.close()
        return {'ok': False, 'error': 'Канал уже существует', 'channel_id': existing['id']}

    cur = conn.execute(
        """INSERT INTO company_channels
           (company_id, channel_type, value, value_normalized, status, source_column)
           VALUES (?,?,?,?,'needs_review','reply')""",
        (company_id, channel_type, value, value.lower())
    )
    cid = cur.lastrowid

    _log(conn, company_id, cid, None, 'added_from_reply',
         '', value, f'Из ответа: {source_email}', 'reply')

    conn.commit()
    conn.close()
    return {'ok': True, 'channel_id': cid, 'status': 'needs_review'}


# ── Confirm needs_review contact ──────────────────────────────────────────────
def confirm_contact(channel_id: int) -> dict:
    conn = get_db()
    ch = conn.execute('SELECT * FROM company_channels WHERE id=?', (channel_id,)).fetchone()
    if not ch:
        conn.close()
        return {'ok': False, 'error': 'Канал не найден'}
    ch = dict(ch)
    conn.execute(
        "UPDATE company_channels SET status='active', updated_at=datetime('now') WHERE id=?",
        (channel_id,)
    )
    _log(conn, ch['company_id'], channel_id, None, 'confirmed',
         'needs_review', 'active', 'Подтверждено пользователем', 'manual')
    conn.commit()
    conn.close()
    return {'ok': True, 'channel_id': channel_id, 'status': 'active'}


# ── Replace contact ───────────────────────────────────────────────────────────
def replace_contact(
    old_channel_id: int,
    new_value: str,
    reason: str = '',
) -> dict:
    """
    Old channel → replaced; new channel → active.
    Old channel keeps replaced_by_id reference.
    """
    new_value = new_value.strip()
    conn = get_db()
    old_ch = conn.execute('SELECT * FROM company_channels WHERE id=?', (old_channel_id,)).fetchone()
    if not old_ch:
        conn.close()
        return {'ok': False, 'error': 'Исходный канал не найден'}
    old_ch = dict(old_ch)

    # Create new channel
    cur = conn.execute(
        """INSERT OR IGNORE INTO company_channels
           (company_id, channel_type, value, value_normalized, status, source_column)
           VALUES (?,?,?,?,'active','manual_replace')""",
        (old_ch['company_id'], old_ch['channel_type'], new_value, new_value.lower())
    )
    new_id = cur.lastrowid
    if not new_id:
        new_row = conn.execute(
            'SELECT id FROM company_channels WHERE company_id=? AND channel_type=? AND lower(value)=?',
            (old_ch['company_id'], old_ch['channel_type'], new_value.lower())
        ).fetchone()
        new_id = new_row['id'] if new_row else None

    # Mark old as replaced
    conn.execute(
        """UPDATE company_channels
           SET status='replaced', replaced_by_id=?, updated_at=datetime('now')
           WHERE id=?""",
        (new_id, old_channel_id)
    )

    _log(conn, old_ch['company_id'], old_channel_id, None,
         'replaced', old_ch['value'], new_value, reason or 'Заменён вручную', 'manual')

    # Update legacy contacts if email
    if old_ch['channel_type'] == 'email':
        conn.execute(
            """UPDATE contacts SET email=?, status='new'
               WHERE (lower(email)=? OR lower(personal_email)=? OR lower(generic_email)=?)
               AND status NOT IN ('bounced','unsubscribed')""",
            (new_value, old_ch['value'].lower()) + (old_ch['value'].lower(),) * 2
        )

    conn.commit()
    conn.close()
    return {'ok': True, 'old_channel_id': old_channel_id, 'new_channel_id': new_id,
            'old_value': old_ch['value'], 'new_value': new_value}


# ── Manual add ────────────────────────────────────────────────────────────────
def add_channel_manual(
    company_id: str,
    channel_type: str,
    value: str,
    status: str = 'active',
) -> dict:
    value = value.strip()
    if channel_type == 'email':
        normalized = normalize_mailing_email(value)
        if not normalized:
            return {'ok': False, 'error': 'Невалидный email'}
        value = normalized

    conn = get_db()
    existing = conn.execute(
        'SELECT id FROM company_channels WHERE company_id=? AND channel_type=? AND lower(value)=?',
        (company_id, channel_type, value.lower())
    ).fetchone()
    if existing:
        conn.close()
        return {'ok': False, 'error': 'Канал уже существует'}

    cur = conn.execute(
        """INSERT INTO company_channels
           (company_id, channel_type, value, value_normalized, status, source_column)
           VALUES (?,?,?,?,?,'manual')""",
        (company_id, channel_type, value, value.lower(), status)
    )
    cid = cur.lastrowid
    _log(conn, company_id, cid, None, 'added', '', value, 'Добавлено вручную', 'manual')
    conn.commit()
    conn.close()
    return {'ok': True, 'channel_id': cid, 'status': status}


# ── Get contacts needing review ───────────────────────────────────────────────
def get_needs_review(limit: int = 50) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT cc.*, c.company_name_original
           FROM company_channels cc
           LEFT JOIN companies c ON cc.company_id = c.company_id
           WHERE cc.status = 'needs_review'
           ORDER BY cc.created_at DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Stats ─────────────────────────────────────────────────────────────────────
def get_contact_stats() -> dict:
    conn = get_db()
    total   = conn.execute('SELECT COUNT(*) FROM company_channels').fetchone()[0]
    active  = conn.execute("SELECT COUNT(*) FROM company_channels WHERE status='active'").fetchone()[0]
    bounced = conn.execute("SELECT COUNT(*) FROM company_channels WHERE status='bounced'").fetchone()[0]
    unsub   = conn.execute("SELECT COUNT(*) FROM company_channels WHERE status='unsubscribed'").fetchone()[0]
    review  = conn.execute("SELECT COUNT(*) FROM company_channels WHERE status='needs_review'").fetchone()[0]
    replaced= conn.execute("SELECT COUNT(*) FROM company_channels WHERE status='replaced'").fetchone()[0]
    email_active = conn.execute("SELECT COUNT(*) FROM company_channels WHERE channel_type='email' AND status='active'").fetchone()[0]
    conn.close()
    return {
        'total': total, 'active': active, 'bounced': bounced,
        'unsubscribed': unsub, 'needs_review': review, 'replaced': replaced,
        'email_active': email_active,
    }
