"""Tests for contact lifecycle (bounce, replace, add)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from database import init_db, get_db
from services.contacts_service import (
    handle_bounce, replace_contact, add_channel_manual, confirm_contact,
    add_contact_from_reply, get_contact_stats
)

@pytest.fixture(autouse=True)
def ensure_db():
    init_db()

def _make_company(conn, company_id='test_co_001', name='Тест Компания'):
    conn.execute(
        "INSERT OR IGNORE INTO companies (company_id, company_name_original, match_status) VALUES (?,?,'manual_review')",
        (company_id, name)
    )
    conn.commit()

def _make_channel(conn, company_id='test_co_001', ctype='email', value='test@test.ru'):
    cur = conn.execute(
        "INSERT OR IGNORE INTO company_channels (company_id, channel_type, value, value_normalized, status) VALUES (?,?,?,?,'active')",
        (company_id, ctype, value, value.lower())
    )
    conn.commit()
    return cur.lastrowid or conn.execute(
        "SELECT id FROM company_channels WHERE company_id=? AND channel_type=? AND lower(value)=?",
        (company_id, ctype, value.lower())
    ).fetchone()['id']

def test_bounce_channel(tmp_path):
    conn = get_db()
    _make_company(conn)
    ch_id = _make_channel(conn)
    conn.close()

    result = handle_bounce(ch_id, 'Test bounce')
    assert result['ok'] is True
    assert result['status'] == 'bounced'

    conn = get_db()
    ch = conn.execute('SELECT status FROM company_channels WHERE id=?', (ch_id,)).fetchone()
    assert ch['status'] == 'bounced'
    log = conn.execute('SELECT * FROM contact_change_log WHERE channel_id=?', (ch_id,)).fetchone()
    assert log is not None
    assert log['change_type'] == 'bounced'
    conn.close()

def test_replace_channel():
    conn = get_db()
    _make_company(conn)
    ch_id = _make_channel(conn, value='old@test.ru')
    conn.close()

    result = replace_contact(ch_id, 'new@test.ru', 'Ответил с нового адреса')
    assert result['ok'] is True
    assert result['old_value'] == 'old@test.ru'
    assert result['new_value'] == 'new@test.ru'

    conn = get_db()
    old_ch = conn.execute('SELECT status FROM company_channels WHERE id=?', (ch_id,)).fetchone()
    assert old_ch['status'] == 'replaced'
    new_ch = conn.execute("SELECT status FROM company_channels WHERE value='new@test.ru'").fetchone()
    assert new_ch is not None
    assert new_ch['status'] == 'active'
    log = conn.execute('SELECT * FROM contact_change_log WHERE channel_id=?', (ch_id,)).fetchone()
    assert log['change_type'] == 'replaced'
    conn.close()

def test_add_channel_manual_email():
    conn = get_db()
    _make_company(conn, 'co_add_001')
    conn.close()
    result = add_channel_manual('co_add_001', 'email', 'manual@company.ru')
    assert result['ok'] is True
    assert result['status'] == 'active'

def test_add_channel_invalid_email():
    result = add_channel_manual('co_add_001', 'email', 'not-an-email')
    assert result['ok'] is False

def test_add_from_reply_and_confirm():
    conn = get_db()
    _make_company(conn, 'co_reply_001')
    conn.close()

    r1 = add_contact_from_reply('co_reply_001', 'email', 'reply@company.ru',
                                 'Иван Иванов', 'source@mail.ru')
    assert r1['ok'] is True
    assert r1['status'] == 'needs_review'

    r2 = confirm_contact(r1['channel_id'])
    assert r2['ok'] is True
    assert r2['status'] == 'active'

def test_get_contact_stats():
    stats = get_contact_stats()
    assert 'total' in stats
    assert 'active' in stats
    assert 'bounced' in stats
    assert stats['total'] >= 0
