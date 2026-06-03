#!/usr/bin/env python3
"""
Validate companies dataset before import.
Usage: python scripts/validate_dataset.py
Exit 0 = OK, Exit 1 = errors found.
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data' / 'companies'

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

errors: list[str] = []
warnings: list[str] = []


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def check_companies() -> list[dict]:
    path = DATA / 'companies.csv'
    if not path.exists():
        errors.append(f'MISSING: {path}')
        return []
    rows = read_csv(path)
    print(f'  companies.csv: {len(rows)} rows')

    ids = [r.get('company_id', '') for r in rows]
    if len(ids) != len(set(ids)):
        errors.append('Duplicate company_id values in companies.csv')
    if any(not x for x in ids):
        errors.append('Empty company_id values in companies.csv')

    for r in rows:
        inn = r.get('inn', '').strip()
        if inn and (not inn.isdigit() or len(inn) not in (10, 12)):
            warnings.append(f"Suspicious INN: company_id={r.get('company_id')} inn={inn}")

        for field in ('emails_all', 'mobile_phones_all', 'landline_phones_all'):
            vals = [v.strip().lower() for v in r.get(field, '').split(';') if v.strip()]
            if len(vals) != len(set(vals)):
                warnings.append(f"Duplicate values in {field}: company_id={r.get('company_id')}")

        for email in [v.strip() for v in r.get('emails_all', '').split(';') if v.strip()]:
            if not EMAIL_RE.match(email.lower()):
                warnings.append(f"Suspicious email: company_id={r.get('company_id')} email={email}")

    return rows


def check_channels(company_ids: set[str]) -> None:
    path = DATA / 'company_channels.csv'
    if not path.exists():
        errors.append(f'MISSING: {path}')
        return
    rows = read_csv(path)
    print(f'  company_channels.csv: {len(rows)} rows')

    for r in rows:
        if r.get('company_id') not in company_ids:
            errors.append(f"Channel references unknown company_id={r.get('company_id')}")
        if r.get('channel_type') == 'email':
            val = r.get('value', '').strip().lower()
            if val and not EMAIL_RE.match(val):
                warnings.append(f"Suspicious channel email: {val}")


def check_raw_contacts_preserved() -> None:
    path = DATA / 'raw_contacts_preserved.csv'
    if not path.exists():
        errors.append(f'MISSING (required): {path}')
        return
    rows = read_csv(path)
    print(f'  raw_contacts_preserved.csv: {len(rows)} rows — preserved OK')


def check_okved_filters() -> None:
    okveds_path = ROOT / 'data' / 'company_filters' / 'data' / 'company_okveds.csv'
    tree_path   = ROOT / 'data' / 'company_filters' / 'data' / 'okved_tree.json'
    if not okveds_path.exists():
        warnings.append(f'Filter file missing: {okveds_path} — run import_okved_filters.py')
        return
    if not tree_path.exists():
        warnings.append(f'Filter file missing: {tree_path} — run import_okved_filters.py')
        return
    rows = read_csv(okveds_path)
    print(f'  company_okveds.csv: {len(rows)} rows')


def main() -> int:
    print('=== Validating companies dataset ===')
    print()

    companies = check_companies()
    company_ids = {r.get('company_id', '') for r in companies}

    check_channels(company_ids)
    check_raw_contacts_preserved()
    check_okved_filters()

    print()
    print(f'companies: {len(companies)}')
    print(f'warnings:  {len(warnings)}')
    print(f'errors:    {len(errors)}')

    if warnings:
        print()
        print('WARNINGS (first 20):')
        for w in warnings[:20]:
            print(f'  WARNING: {w}')

    if errors:
        print()
        print('ERRORS:')
        for e in errors:
            print(f'  ERROR: {e}')
        return 1

    print()
    print('OK: dataset validation passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
