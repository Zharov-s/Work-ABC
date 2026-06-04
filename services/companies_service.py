"""Aggregate company card data from multiple tables."""
from __future__ import annotations
from database import get_db


def get_company_card(company_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute('SELECT * FROM companies WHERE company_id=?', (company_id,)).fetchone()
    if not row:
        conn.close()
        return None
    company = dict(row)

    channels = [dict(r) for r in conn.execute(
        'SELECT * FROM company_channels WHERE company_id=? ORDER BY is_primary DESC, channel_type, id',
        (company_id,)
    ).fetchall()]

    okveds = [dict(r) for r in conn.execute(
        "SELECT * FROM company_okveds WHERE company_id=? ORDER BY CASE okved_role WHEN 'main' THEN 0 ELSE 1 END, okved_code",
        (company_id,)
    ).fetchall()]

    # Campaign history from legacy send_history/recipients
    campaign_history = [dict(r) for r in conn.execute(
        """SELECT sh.id AS campaign_id, sh.template AS campaign_name, sh.sent_at,
                  sr.status, sr.email
           FROM send_recipients sr
           JOIN send_history sh ON sr.send_id = sh.id
           WHERE lower(sr.email) IN (
               SELECT lower(value) FROM company_channels
               WHERE company_id=? AND channel_type='email'
           )
           ORDER BY sh.sent_at DESC LIMIT 20""",
        (company_id,)
    ).fetchall()]

    change_log = [dict(r) for r in conn.execute(
        'SELECT * FROM contact_change_log WHERE company_id=? ORDER BY created_at DESC LIMIT 30',
        (company_id,)
    ).fetchall()]

    # Warnings
    warnings = []
    emails = [ch for ch in channels if ch['channel_type'] == 'email' and ch.get('status') == 'active']
    if not emails:
        warnings.append({'type': 'no_email', 'text': 'Нет активного email'})
    if not okveds and (not company.get('okved_main_code') or company.get('okved_main_code') == 'NOT_FOUND'):
        warnings.append({'type': 'no_okved', 'text': 'ОКВЭД не найден'})
    if company.get('match_status') == 'conflict':
        warnings.append({'type': 'conflict', 'text': 'Конфликт данных в источниках'})
    bounced = [ch for ch in channels if ch.get('status') == 'bounced']
    if bounced:
        warnings.append({'type': 'bounce', 'text': f'Bounce: {len(bounced)} email'})

    conn.close()
    return {
        'company':         company,
        'channels':        channels,
        'okveds':          okveds,
        'campaign_history': campaign_history,
        'contact_change_log': change_log,
        'warnings':        warnings,
    }


def update_company(company_id: str, data: dict) -> bool:
    """Update editable company fields. Returns True if row was found."""
    allowed = {
        'company_name_original', 'inn', 'ogrn', 'registration_address',
        'website', 'city', 'region', 'segment', 'industry_group_final',
        'activity_type_final', 'review_comment',
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return False
    conn = get_db()
    row = conn.execute('SELECT id FROM companies WHERE company_id=?', (company_id,)).fetchone()
    if not row:
        conn.close()
        return False
    sets = ', '.join(f'{k}=?' for k in updates)
    values = list(updates.values()) + [company_id]
    conn.execute(f"UPDATE companies SET {sets}, updated_at=datetime('now') WHERE company_id=?", values)
    conn.commit()
    conn.close()
    return True


def add_channel(company_id: str, channel_type: str, value: str, source: str = 'manual') -> dict:
    conn = get_db()
    # Check company exists
    if not conn.execute('SELECT id FROM companies WHERE company_id=?', (company_id,)).fetchone():
        conn.close()
        return {'ok': False, 'error': 'Компания не найдена'}
    # Check duplicate
    existing = conn.execute(
        'SELECT id FROM company_channels WHERE company_id=? AND channel_type=? AND value=?',
        (company_id, channel_type, value)
    ).fetchone()
    if existing:
        conn.close()
        return {'ok': False, 'error': 'Такой канал уже существует'}
    cur = conn.execute(
        'INSERT INTO company_channels (company_id, channel_type, value, value_normalized, status, source_column) VALUES (?,?,?,?,?,?)',
        (company_id, channel_type, value, value.lower(), 'active', source)
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return {'ok': True, 'channel_id': cid}


def update_channel_status(channel_id: int, status: str, reason: str = '') -> bool:
    conn = get_db()
    row = conn.execute('SELECT company_id FROM company_channels WHERE id=?', (channel_id,)).fetchone()
    if not row:
        conn.close()
        return False
    old_row = dict(conn.execute('SELECT * FROM company_channels WHERE id=?', (channel_id,)).fetchone())
    conn.execute(
        "UPDATE company_channels SET status=?, updated_at=datetime('now') WHERE id=?",
        (status, channel_id)
    )
    conn.execute(
        'INSERT INTO contact_change_log (company_id, channel_id, change_type, old_value, new_value, reason, source) VALUES (?,?,?,?,?,?,?)',
        (row['company_id'], channel_id, 'status_change',
         old_row.get('status'), status, reason, 'manual')
    )
    conn.commit()
    conn.close()
    return True
