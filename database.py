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

CREATE TABLE IF NOT EXISTS email_opens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT NOT NULL,
    send_id    INTEGER REFERENCES send_history(id),
    contact_id INTEGER REFERENCES contacts(id),
    email      TEXT,
    opened_at  TEXT DEFAULT (datetime('now')),
    user_agent TEXT,
    ip_hash    TEXT
);

CREATE TABLE IF NOT EXISTS email_clicks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token        TEXT NOT NULL,
    send_id      INTEGER REFERENCES send_history(id),
    contact_id   INTEGER REFERENCES contacts(id),
    email        TEXT,
    url          TEXT,
    is_unsubscribe INTEGER DEFAULT 0,
    clicked_at   TEXT DEFAULT (datetime('now')),
    user_agent   TEXT
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
    'tracking_base_url': '',  # публичный URL для трекинг-пикселя, напр. https://myapp.railway.app
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
    for col_name in ('personal_email', 'generic_email', 'mobile_phone', 'generic_phone', 'inn', 'email_valid'):
        if col_name not in cols:
            conn.execute(f'ALTER TABLE contacts ADD COLUMN {col_name} TEXT')
    # Пункт 2: счётчик попыток bounce (правило двух сигналов)
    if 'bounce_count' not in cols:
        conn.execute('ALTER TABLE contacts ADD COLUMN bounce_count INTEGER DEFAULT 0')
    # Пункт 3: свежесть контакта
    if 'last_verified_at' not in cols:
        conn.execute('ALTER TABLE contacts ADD COLUMN last_verified_at TEXT')
        conn.execute(
            "UPDATE contacts SET last_verified_at=date_found WHERE last_verified_at IS NULL AND date_found IS NOT NULL"
        )
    if 'freshness_score' not in cols:
        conn.execute('ALTER TABLE contacts ADD COLUMN freshness_score REAL DEFAULT 1.0')

    # Миграция send_recipients: tracking_token
    sr_cols = [r[1] for r in conn.execute('PRAGMA table_info(send_recipients)').fetchall()]
    if 'tracking_token' not in sr_cols:
        conn.execute('ALTER TABLE send_recipients ADD COLUMN tracking_token TEXT')


    conn.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        type         TEXT NOT NULL,
        contact_id   INTEGER,
        company_name TEXT,
        from_email   TEXT,
        summary      TEXT,
        details_json TEXT,
        msg_id       TEXT UNIQUE,
        created_at   TEXT DEFAULT (datetime('now')),
        read_at      TEXT
    )''')
    # Индексы для трекинга
    conn.execute('CREATE INDEX IF NOT EXISTS idx_email_opens_token ON email_opens(token)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_email_clicks_token ON email_clicks(token)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_send_recipients_token ON send_recipients(tracking_token)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_mailing_recipients_email ON mailing_recipients(email)')

    # ── Новые таблицы SEARCH_ARCHITECTURE.md ──────────────────────────────
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS http_cache (
            cache_key TEXT PRIMARY KEY, url TEXT NOT NULL, domain TEXT,
            status_code INTEGER, response_text TEXT, response_hash TEXT,
            fetched_at TEXT, source_type TEXT, error TEXT
        );
        CREATE TABLE IF NOT EXISTS contact_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER, run_id INTEGER,
            company_key TEXT, field_name TEXT, field_value TEXT, source_url TEXT,
            source_type TEXT, extraction_method TEXT, confidence REAL, reliability REAL,
            accepted INTEGER, reject_reason TEXT, evidence_snippet TEXT,
            evidence_hash TEXT, collected_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS rejected_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, company_name TEXT,
            normalized_company_name TEXT, inn TEXT, website TEXT, reason TEXT,
            lead_score REAL, best_email TEXT, best_phone TEXT, source_url TEXT,
            diagnostic_json TEXT, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS research_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, metric_name TEXT,
            metric_value REAL, metric_text TEXT, source TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS parser_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
            parser_version TEXT NOT NULL, status TEXT NOT NULL, drift_score REAL,
            success_rate REAL, error_rate REAL, last_good_at TEXT, last_bad_at TEXT,
            diagnostic_json TEXT, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS manual_validation_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, contact_id INTEGER,
            company_name TEXT, field_name TEXT, field_value TEXT, evidence_url TEXT,
            model_confidence REAL, human_status TEXT DEFAULT 'pending', human_label TEXT,
            human_comment TEXT, reviewed_at TEXT, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS gold_dataset_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, benchmark_run_id INTEGER,
            gold_company_key TEXT, expected_field TEXT, expected_value TEXT,
            predicted_value TEXT, match_type TEXT, precision_hit INTEGER,
            recall_hit INTEGER, source TEXT, confidence REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS suppression_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, domain TEXT,
            reason TEXT, bounce_count INTEGER DEFAULT 0, source TEXT,
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
        );
    ''')

    # Новые колонки contacts: lead_score, confidence fields, ogrn
    _ctcols = [r[1] for r in conn.execute('PRAGMA table_info(contacts)').fetchall()]
    for _col, _def in [
        ('normalized_company_name', 'TEXT'),
        ('lead_score', 'REAL DEFAULT 0.0'),
        ('website_confidence', 'REAL DEFAULT 0.0'),
        ('email_confidence', 'REAL DEFAULT 0.0'),
        ('phone_confidence', 'REAL DEFAULT 0.0'),
        ('lpr_confidence', 'REAL DEFAULT 0.0'),
        ('ogrn', 'TEXT'),
        ('source_summary', 'TEXT'),
    ]:
        if _col not in _ctcols:
            conn.execute(f'ALTER TABLE contacts ADD COLUMN {_col} {_def}')

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


def compute_freshness_score(last_verified_at: str | None) -> float:
    """
    Свежесть контакта: 1.0 = только что проверен, 0.0 = не проверялся или >4 лет назад.
    Decay rate ~25% в год. Используется для приоритизации повторного ресёрча.
    """
    if not last_verified_at:
        return 0.0
    try:
        from datetime import datetime
        verified = datetime.strptime(last_verified_at[:10], '%Y-%m-%d')
        days = max(0, (datetime.now() - verified).days)
        return round(max(0.0, 1.0 - (days / 365) * 0.25), 3)
    except Exception:
        return 0.5


def update_contact_verified(conn, contact_id: int) -> None:
    """Отмечает контакт как только что проверенный (email открыт, ответ получен и т.п.)."""
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    conn.execute(
        "UPDATE contacts SET last_verified_at=?, freshness_score=1.0 WHERE id=?",
        (today, contact_id)
    )


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
