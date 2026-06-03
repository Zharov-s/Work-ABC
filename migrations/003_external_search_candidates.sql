-- Migration 003: External search candidates and filter presets

CREATE TABLE IF NOT EXISTS external_company_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_source TEXT NOT NULL, external_id TEXT,
    company_name TEXT, inn TEXT, ogrn TEXT, website TEXT,
    website_domain TEXT, email TEXT, email_domain TEXT,
    region TEXT, city TEXT, okved_main_code TEXT, industry_group TEXT,
    raw_json TEXT,
    dedupe_status TEXT DEFAULT 'new',
    matched_company_id TEXT REFERENCES companies(company_id),
    dedupe_score REAL DEFAULT 0.0, dedupe_notes TEXT,
    imported_at TEXT, rejected_at TEXT, reject_reason TEXT,
    filter_request_json TEXT, created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS saved_filter_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, filter_json TEXT NOT NULL,
    scope TEXT DEFAULT 'internal',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
