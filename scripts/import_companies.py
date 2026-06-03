#!/usr/bin/env python3
"""
Import companies dataset into the main SQLite database.
Reads data/companies/{companies.csv, company_channels.csv}.
Safe: uses INSERT OR IGNORE on company_id — never deletes existing records.

Usage: python scripts/import_companies.py [--dry-run]
"""
import csv
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import get_db, init_db

DATA = ROOT / 'data' / 'companies'


def _ensure_companies_tables(conn) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id                  TEXT    NOT NULL UNIQUE,
            company_name_original       TEXT,
            company_name_normalized     TEXT,
            legal_name_found            TEXT,
            inn                         TEXT,
            ogrn                        TEXT,
            registration_address        TEXT,
            website                     TEXT,
            city                        TEXT,
            region                      TEXT,
            segment                     TEXT,
            industry_group_final        TEXT,
            activity_type_final         TEXT,
            okved_main_code             TEXT,
            okved_main_activity         TEXT,
            okved_additional_activities TEXT,
            okved_section               TEXT,
            okved_status                TEXT,
            okved_match_method          TEXT,
            okved_confidence_score      REAL    DEFAULT 0.0,
            match_status                TEXT    DEFAULT 'manual_review',
            confidence_score            REAL    DEFAULT 0.0,
            contacts_count              INTEGER DEFAULT 0,
            source_inn                  TEXT,
            source_address              TEXT,
            source_website              TEXT,
            review_comment              TEXT,
            checked_at                  TEXT,
            created_at                  TEXT    DEFAULT (datetime('now')),
            updated_at                  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS company_channels (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id       TEXT    NOT NULL REFERENCES companies(company_id),
            channel_type     TEXT    NOT NULL,
            value            TEXT    NOT NULL,
            value_normalized TEXT,
            is_primary       INTEGER DEFAULT 0,
            status           TEXT    DEFAULT 'active',
            sendable_status  TEXT,
            source_column    TEXT,
            is_free_email    INTEGER DEFAULT 0,
            created_at       TEXT    DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_companies_company_id ON companies(company_id);
        CREATE INDEX IF NOT EXISTS idx_companies_inn        ON companies(inn);
        CREATE INDEX IF NOT EXISTS idx_companies_region     ON companies(region);
        CREATE INDEX IF NOT EXISTS idx_companies_okved      ON companies(okved_main_code);
        CREATE INDEX IF NOT EXISTS idx_companies_industry   ON companies(industry_group_final);
        CREATE INDEX IF NOT EXISTS idx_channels_company_id  ON company_channels(company_id);
        CREATE INDEX IF NOT EXISTS idx_channels_type_value  ON company_channels(channel_type, value);
    """)


def import_companies(conn, rows: list[dict], dry_run: bool) -> tuple[int, int]:
    added = skipped = 0
    for r in rows:
        cid = r.get('company_id', '').strip()
        if not cid:
            continue
        existing = conn.execute(
            'SELECT id FROM companies WHERE company_id=?', (cid,)
        ).fetchone()
        if existing:
            skipped += 1
            continue
        if not dry_run:
            conn.execute(
                """INSERT INTO companies
                   (company_id, company_name_original, company_name_normalized,
                    legal_name_found, inn, registration_address, website,
                    city, region, segment, industry_group_final, activity_type_final,
                    okved_main_code, okved_main_activity, okved_additional_activities,
                    okved_section, okved_status, okved_match_method,
                    okved_confidence_score, match_status, confidence_score,
                    contacts_count, source_inn, source_address, source_website,
                    review_comment, checked_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cid,
                    r.get('company_name_original', '').strip(),
                    r.get('company_name_normalized', '').strip(),
                    r.get('legal_name_found', '').strip(),
                    r.get('inn', '').strip(),
                    r.get('registration_address', '').strip(),
                    r.get('website', '').strip(),
                    r.get('city', '').strip(),
                    r.get('region', '').strip(),
                    r.get('segment', '').strip(),
                    r.get('industry_group_final', '').strip(),
                    r.get('activity_type_final', '').strip(),
                    r.get('okved_main_code', '').strip(),
                    r.get('okved_main_activity', '').strip(),
                    r.get('okved_additional_activities', '').strip(),
                    r.get('okved_section', '').strip(),
                    r.get('okved_status', '').strip(),
                    r.get('okved_match_method', '').strip(),
                    float(r.get('okved_confidence_score') or 0),
                    r.get('match_status', 'manual_review').strip(),
                    float(r.get('confidence_score') or 0),
                    int(r.get('contacts_count') or 0),
                    r.get('source_inn', '').strip(),
                    r.get('source_address', '').strip(),
                    r.get('source_website', '').strip(),
                    r.get('review_comment', '').strip(),
                    r.get('checked_at', '').strip(),
                )
            )
        added += 1
    return added, skipped


def import_channels(conn, rows: list[dict], dry_run: bool) -> tuple[int, int]:
    added = skipped = 0
    for r in rows:
        cid   = r.get('company_id', '').strip()
        ctype = r.get('channel_type', '').strip()
        val   = r.get('value', '').strip()
        if not cid or not ctype or not val:
            continue
        existing = conn.execute(
            'SELECT id FROM company_channels WHERE company_id=? AND channel_type=? AND value=?',
            (cid, ctype, val)
        ).fetchone()
        if existing:
            skipped += 1
            continue
        if not dry_run:
            is_free = 1 if r.get('is_free_email_domain', '').lower() == 'true' else 0
            conn.execute(
                """INSERT INTO company_channels
                   (company_id, channel_type, value, value_normalized,
                    sendable_status, source_column, is_free_email)
                   VALUES (?,?,?,?,?,?,?)""",
                (cid, ctype, val, val.lower(),
                 r.get('sendable_status', '').strip(),
                 r.get('source_column', '').strip(),
                 is_free)
            )
        added += 1
    return added, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description='Import companies dataset into SQLite')
    parser.add_argument('--dry-run', action='store_true', help='Validate only, no DB writes')
    args = parser.parse_args()

    print('=== Import Companies Dataset ===')
    if args.dry_run:
        print('DRY RUN — no database writes')
    print()

    companies_path = DATA / 'companies.csv'
    channels_path  = DATA / 'company_channels.csv'

    if not companies_path.exists():
        print(f'ERROR: {companies_path} not found.')
        print('Run: cp hunter/companies_ai_dataset_package/data/ data/companies/')
        return 1

    print('Reading CSV files...')
    with open(companies_path, encoding='utf-8', newline='') as f:
        companies_rows = list(csv.DictReader(f))
    print(f'  companies.csv: {len(companies_rows)} rows')

    channels_rows: list[dict] = []
    if channels_path.exists():
        with open(channels_path, encoding='utf-8', newline='') as f:
            channels_rows = list(csv.DictReader(f))
        print(f'  company_channels.csv: {len(channels_rows)} rows')

    print()
    print('Initialising database...')
    init_db()
    conn = get_db()

    print('Ensuring tables exist...')
    _ensure_companies_tables(conn)

    print('Importing companies...')
    c_added, c_skipped = import_companies(conn, companies_rows, args.dry_run)
    print(f'  added: {c_added}, skipped (already exist): {c_skipped}')

    print('Importing channels...')
    ch_added, ch_skipped = import_channels(conn, channels_rows, args.dry_run)
    print(f'  added: {ch_added}, skipped (already exist): {ch_skipped}')

    if not args.dry_run:
        conn.commit()
        print()
        print('Committed to database.')

    conn.close()
    print()
    print(f'Done. Companies processed: {c_added + c_skipped}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
