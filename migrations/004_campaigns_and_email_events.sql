-- Migration 004: Email campaigns, recipients and events (new architecture)

CREATE TABLE IF NOT EXISTS email_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, template_key TEXT NOT NULL, subject TEXT,
    filter_json TEXT, status TEXT DEFAULT 'draft',
    test_sent_at TEXT, started_at TEXT, finished_at TEXT,
    total_recipients INTEGER DEFAULT 0, total_sent INTEGER DEFAULT 0,
    total_failed INTEGER DEFAULT 0, total_opened INTEGER DEFAULT 0,
    total_clicked INTEGER DEFAULT 0, total_replied INTEGER DEFAULT 0,
    total_bounced INTEGER DEFAULT 0, total_unsubscribed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_campaign_recipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES email_campaigns(id),
    company_id TEXT REFERENCES companies(company_id),
    contact_id INTEGER REFERENCES company_contacts(id),
    channel_id INTEGER REFERENCES company_channels(id),
    email TEXT NOT NULL, status TEXT DEFAULT 'pending',
    tracking_token TEXT UNIQUE,
    sent_at TEXT, opened_at TEXT, clicked_at TEXT,
    replied_at TEXT, bounced_at TEXT, error_msg TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES email_campaigns(id),
    recipient_id INTEGER REFERENCES email_campaign_recipients(id),
    event_type TEXT NOT NULL, email TEXT, url TEXT,
    user_agent TEXT, ip_hash TEXT, raw_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
