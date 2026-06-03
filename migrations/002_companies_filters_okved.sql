-- Migration 002: Companies, channels, OKVED, industry groups
-- Applied in init_db() Stage 3 block (CREATE TABLE IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS companies (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id                  TEXT    NOT NULL UNIQUE,
    company_name_original       TEXT,
    inn                         TEXT,
    website                     TEXT,
    region                      TEXT,
    okved_main_code             TEXT,
    okved_status                TEXT,
    match_status                TEXT    DEFAULT 'manual_review',
    industry_group_final        TEXT,
    created_at                  TEXT    DEFAULT (datetime('now')),
    updated_at                  TEXT    DEFAULT (datetime('now'))
    -- (full schema in database.py)
);

CREATE TABLE IF NOT EXISTS company_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL,
    contact_name TEXT, position TEXT, status TEXT DEFAULT 'active',
    source TEXT, created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS company_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL,
    contact_id INTEGER, channel_type TEXT NOT NULL, value TEXT NOT NULL,
    value_normalized TEXT, is_primary INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active', sendable_status TEXT,
    bounce_count INTEGER DEFAULT 0, replaced_by_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS company_okveds (
    id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL,
    okved_code TEXT NOT NULL, okved_name TEXT, okved_role TEXT DEFAULT 'main',
    okved_section TEXT, okved_class TEXT, okved_status TEXT, source TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS okved_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE, name TEXT, parent_code TEXT,
    company_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS industry_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL, company_count INTEGER DEFAULT 0
);
