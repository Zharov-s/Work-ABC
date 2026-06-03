-- Migration 005: Contact change log

CREATE TABLE IF NOT EXISTS contact_change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT REFERENCES companies(company_id),
    channel_id INTEGER REFERENCES company_channels(id),
    contact_id INTEGER REFERENCES company_contacts(id),
    change_type TEXT NOT NULL,
    old_value TEXT, new_value TEXT,
    reason TEXT, source TEXT, actor TEXT DEFAULT 'system',
    created_at TEXT DEFAULT (datetime('now'))
);
