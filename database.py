import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'contacts.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    website      TEXT,
    person_name  TEXT,
    title        TEXT,
    email        TEXT,
    phone        TEXT,
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


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA)

    # Миграция: добавить run_id если колонки ещё нет
    cols = [r[1] for r in conn.execute('PRAGMA table_info(contacts)').fetchall()]
    if 'run_id' not in cols:
        conn.execute('ALTER TABLE contacts ADD COLUMN run_id INTEGER REFERENCES research_runs(id)')
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
    conn.close()


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
