import sqlite3
import os
import re

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'contacts.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    website      TEXT,
    person_name  TEXT,
    title        TEXT,
    email        TEXT,
    personal_email TEXT,
    generic_email  TEXT,
    phone        TEXT,
    mobile_phone  TEXT,
    generic_phone TEXT,
    inn          TEXT,
    source_url   TEXT,
    segment      TEXT,
    region       TEXT,
    date_found   TEXT,
    status       TEXT DEFAULT 'new',
    notes        TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    run_id       INTEGER REFERENCES research_runs(id),
    UNIQUE(email) ON CONFLICT IGNORE
);

CREATE TABLE IF NOT EXISTS send_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    template     TEXT NOT NULL,
    subject      TEXT,
    sent_at      TEXT DEFAULT (datetime('now')),
    total_sent   INTEGER DEFAULT 0,
    total_failed INTEGER DEFAULT 0,
    batch_count  INTEGER DEFAULT 0,
    status       TEXT,
    report_json  TEXT
);

CREATE TABLE IF NOT EXISTS send_recipients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    send_id    INTEGER REFERENCES send_history(id),
    contact_id INTEGER,
    email      TEXT NOT NULL,
    status     TEXT DEFAULT 'sent'
);

CREATE TABLE IF NOT EXISTS mailing_recipients (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id    INTEGER REFERENCES contacts(id),
    email         TEXT NOT NULL UNIQUE,
    email_type    TEXT,
    company_name  TEXT,
    person_name   TEXT,
    source_run_id INTEGER REFERENCES research_runs(id),
    status        TEXT DEFAULT 'new',
    sent_at       TEXT,
    last_error    TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    config_json  TEXT,
    status       TEXT DEFAULT 'running',
    found_count  INTEGER DEFAULT 0,
    log_text     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_SETTINGS = {
    'smtp_host':        'smtp.mail.ru',
    'smtp_port':        '465',
    'smtp_ssl':         'true',
    'smtp_user':        's.zharov@abcentrum.ru',
    'smtp_pass':        'mBZgN5SmVuz4uytUkLZb',
    'from_name':        'ABCENTRUM',
    'from_email':       's.zharov@abcentrum.ru',
    'reply_to':         's.zharov@abcentrum.ru',
    'asset_url_mitino': 'https://raw.githubusercontent.com/Zharov-s/email/main/assets',
    'asset_url_grekova':'https://raw.githubusercontent.com/Zharov-s/Grekova/main/assets',
    'unsubscribe_url':  'mailto:s.zharov@abcentrum.ru?subject=%D0%9E%D1%82%D0%BF%D0%B8%D1%81%D0%BA%D0%B0',
    'app_login':        'admin',
    'app_password_hash':'',  # будет заполнен при init
}

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MAILING_BATCH_LIMIT = 29


def normalize_mailing_email(raw):
    raw = (raw or '').strip().lower()
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
    email = f'{local}@{domain}'
    return email if EMAIL_RE.match(email) else None


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA)

    # Миграции: добавить новые колонки если их ещё нет
    cols = [r[1] for r in conn.execute('PRAGMA table_info(contacts)').fetchall()]
    if 'run_id' not in cols:
        conn.execute('ALTER TABLE contacts ADD COLUMN run_id INTEGER REFERENCES research_runs(id)')
    for col_name in ('personal_email', 'generic_email', 'mobile_phone', 'generic_phone', 'inn'):
        if col_name not in cols:
            conn.execute(f'ALTER TABLE contacts ADD COLUMN {col_name} TEXT')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_mailing_recipients_email ON mailing_recipients(email)')
    conn.commit()

    # Заполняем настройки по умолчанию (только если ключа ещё нет)
    import bcrypt
    for key, value in DEFAULT_SETTINGS.items():
        existing = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        if not existing:
            if key == 'app_password_hash':
                value = bcrypt.hashpw(b'admin', bcrypt.gensalt()).decode()
            conn.execute('INSERT INTO settings(key,value) VALUES(?,?)', (key, value))

    conn.commit()
    sync_mailing_recipients(conn)
    conn.commit()
    conn.close()


def sync_mailing_recipients(conn=None):
    own_conn = conn is None
    if own_conn:
        conn = get_db()

    rows = conn.execute(
        """SELECT id, company_name, person_name, email, personal_email, generic_email,
                  run_id, status
           FROM contacts"""
    ).fetchall()

    added = 0
    updated = 0
    for r in rows:
        candidates = [
            ('personal', normalize_mailing_email(r['personal_email'])),
            ('generic', normalize_mailing_email(r['generic_email'])),
            ('primary', normalize_mailing_email(r['email'])),
        ]
        seen = set()
        for email_type, email in candidates:
            if not email or email in seen:
                continue
            seen.add(email)
            desired_status = 'sent' if (r['status'] or '').lower() == 'sent' else 'new'
            existing = conn.execute(
                'SELECT id, status FROM mailing_recipients WHERE email=?',
                (email,)
            ).fetchone()
            if existing:
                status = existing['status']
                if desired_status == 'sent' and status != 'sent':
                    status = 'sent'
                conn.execute(
                    """UPDATE mailing_recipients
                       SET contact_id=COALESCE(contact_id, ?),
                           email_type=COALESCE(NULLIF(email_type, ''), ?),
                           company_name=COALESCE(NULLIF(company_name, ''), ?),
                           person_name=COALESCE(NULLIF(person_name, ''), ?),
                           source_run_id=COALESCE(source_run_id, ?),
                           status=?
                       WHERE id=?""",
                    (r['id'], email_type, r['company_name'], r['person_name'],
                     r['run_id'], status, existing['id'])
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO mailing_recipients
                       (contact_id, email, email_type, company_name, person_name, source_run_id, status)
                       VALUES(?,?,?,?,?,?,?)""",
                    (r['id'], email, email_type, r['company_name'], r['person_name'],
                     r['run_id'], desired_status)
                )
                added += 1

    if own_conn:
        conn.commit()
        conn.close()
    return {'added': added, 'updated': updated}


def get_mailing_stats(conn=None):
    own_conn = conn is None
    if own_conn:
        conn = get_db()
    total = conn.execute('SELECT COUNT(*) FROM mailing_recipients').fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM mailing_recipients WHERE status='sent'").fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM mailing_recipients WHERE status='failed'").fetchone()[0]
    remaining = max(total - sent, 0)
    stats = {
        'total': total,
        'sent': sent,
        'failed': failed,
        'remaining': remaining,
        'batch_limit': MAILING_BATCH_LIMIT,
        'next_batch': min(MAILING_BATCH_LIMIT, remaining),
        'batch_count': (remaining + MAILING_BATCH_LIMIT - 1) // MAILING_BATCH_LIMIT if remaining else 0,
    }
    if own_conn:
        conn.close()
    return stats


def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, value))
    conn.commit()
    conn.close()


def get_all_settings():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}
