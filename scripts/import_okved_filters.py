#!/usr/bin/env python3
"""
Import OKVED filter data into the main SQLite database.
Reads data/company_filters/data/{okved_nodes.csv, company_okveds.csv, industry_groups.csv}.
Safe: INSERT OR IGNORE — never deletes existing records.

Usage: python scripts/import_okved_filters.py [--dry-run]
"""
import csv
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import get_db, init_db

FILTERS = ROOT / 'data' / 'company_filters'


def _ensure_filter_tables(conn) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS okved_nodes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            level         TEXT    NOT NULL,
            code          TEXT    NOT NULL UNIQUE,
            name          TEXT,
            parent_code   TEXT,
            company_count INTEGER DEFAULT 0,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS company_okveds (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id    TEXT    NOT NULL REFERENCES companies(company_id),
            okved_code    TEXT    NOT NULL,
            okved_name    TEXT,
            okved_role    TEXT    DEFAULT 'main',
            okved_section TEXT,
            okved_class   TEXT,
            okved_status  TEXT,
            source        TEXT,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS industry_groups (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id      TEXT    NOT NULL UNIQUE,
            name          TEXT    NOT NULL,
            company_count INTEGER DEFAULT 0,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_okved_nodes_code       ON okved_nodes(code);
        CREATE INDEX IF NOT EXISTS idx_okved_nodes_parent     ON okved_nodes(parent_code);
        CREATE INDEX IF NOT EXISTS idx_company_okveds_company ON company_okveds(company_id);
        CREATE INDEX IF NOT EXISTS idx_company_okveds_code    ON company_okveds(okved_code);
        CREATE INDEX IF NOT EXISTS idx_industry_groups_id     ON industry_groups(group_id);
    """)


def import_okved_nodes(conn, dry_run: bool) -> tuple[int, int]:
    path = FILTERS / 'data' / 'okved_nodes.csv'
    if not path.exists():
        print(f'  SKIP: {path} not found')
        return 0, 0
    added = skipped = 0
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            code = r.get('code', '').strip()
            if not code:
                continue
            existing = conn.execute('SELECT id FROM okved_nodes WHERE code=?', (code,)).fetchone()
            if existing:
                skipped += 1
                continue
            if not dry_run:
                conn.execute(
                    """INSERT INTO okved_nodes (level, code, name, parent_code, company_count)
                       VALUES (?,?,?,?,?)""",
                    (r.get('level', ''), code,
                     r.get('name', ''),  r.get('parent_code', ''),
                     int(r.get('company_count') or 0))
                )
            added += 1
    return added, skipped


def import_company_okveds(conn, dry_run: bool) -> tuple[int, int]:
    path = FILTERS / 'data' / 'company_okveds.csv'
    if not path.exists():
        print(f'  SKIP: {path} not found')
        return 0, 0
    added = skipped = 0
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            cid  = r.get('company_id', '').strip()
            code = r.get('okved_code', '').strip()
            role = r.get('okved_role', 'main').strip()
            if not cid or not code:
                continue
            existing = conn.execute(
                'SELECT id FROM company_okveds WHERE company_id=? AND okved_code=? AND okved_role=?',
                (cid, code, role)
            ).fetchone()
            if existing:
                skipped += 1
                continue
            if not dry_run:
                conn.execute(
                    """INSERT INTO company_okveds
                       (company_id, okved_code, okved_name, okved_role,
                        okved_section, okved_class, okved_status, source)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (cid, code, r.get('okved_name', ''), role,
                     r.get('okved_section', ''), r.get('okved_class', ''),
                     r.get('okved_status', ''), r.get('source', ''))
                )
            added += 1
    return added, skipped


def import_industry_groups(conn, dry_run: bool) -> tuple[int, int]:
    path = FILTERS / 'data' / 'industry_groups.csv'
    if not path.exists():
        print(f'  SKIP: {path} not found')
        return 0, 0
    added = skipped = 0
    with open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            gid  = r.get('id', '').strip()
            name = r.get('name', '').strip()
            if not gid or not name:
                continue
            existing = conn.execute(
                'SELECT id FROM industry_groups WHERE group_id=?', (gid,)
            ).fetchone()
            if existing:
                skipped += 1
                continue
            if not dry_run:
                conn.execute(
                    """INSERT INTO industry_groups (group_id, name, company_count)
                       VALUES (?,?,?)""",
                    (gid, name, int(r.get('company_count') or 0))
                )
            added += 1
    return added, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description='Import OKVED filter data into SQLite')
    parser.add_argument('--dry-run', action='store_true', help='Validate only, no DB writes')
    args = parser.parse_args()

    print('=== Import OKVED Filters ===')
    if args.dry_run:
        print('DRY RUN — no database writes')
    print()

    print('Initialising database...')
    init_db()
    conn = get_db()

    print('Ensuring tables exist...')
    _ensure_filter_tables(conn)

    print('Importing okved_nodes...')
    n_added, n_skipped = import_okved_nodes(conn, args.dry_run)
    print(f'  added: {n_added}, skipped: {n_skipped}')

    print('Importing company_okveds...')
    o_added, o_skipped = import_company_okveds(conn, args.dry_run)
    print(f'  added: {o_added}, skipped: {o_skipped}')

    print('Importing industry_groups...')
    g_added, g_skipped = import_industry_groups(conn, args.dry_run)
    print(f'  added: {g_added}, skipped: {g_skipped}')

    if not args.dry_run:
        conn.commit()
        print()
        print('Committed to database.')

    conn.close()
    print()
    print(f'Done. okved_nodes: {n_added + n_skipped}, '
          f'company_okveds: {o_added + o_skipped}, '
          f'industry_groups: {g_added + g_skipped}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
