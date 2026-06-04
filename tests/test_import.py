"""Tests for data import scripts."""
import sys, os, csv, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from database import init_db, get_db
from pathlib import Path

ROOT = Path(__file__).parent.parent

@pytest.fixture(autouse=True)
def ensure_db():
    init_db()

# ── Dataset files ─────────────────────────────────────────────────────────────
def test_companies_csv_exists():
    assert (ROOT / 'data' / 'companies' / 'companies.csv').exists()

def test_company_channels_csv_exists():
    assert (ROOT / 'data' / 'companies' / 'company_channels.csv').exists()

def test_raw_contacts_preserved():
    assert (ROOT / 'data' / 'companies' / 'raw_contacts_preserved.csv').exists()

def test_companies_csv_row_count():
    path = ROOT / 'data' / 'companies' / 'companies.csv'
    if not path.exists(): pytest.skip('dataset not available')
    with open(path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 3000, f'Expected >=3000 companies, got {len(rows)}'

def test_companies_no_duplicate_ids():
    path = ROOT / 'data' / 'companies' / 'companies.csv'
    if not path.exists(): pytest.skip('dataset not available')
    with open(path, encoding='utf-8') as f:
        ids = [r['company_id'] for r in csv.DictReader(f)]
    assert len(ids) == len(set(ids)), 'Duplicate company_id found'

# ── Database import verification ──────────────────────────────────────────────
def test_companies_imported():
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0]
    conn.close()
    assert count > 0, 'companies table is empty — run import_companies.py'

def test_channels_imported():
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM company_channels').fetchone()[0]
    conn.close()
    assert count > 0, 'company_channels table is empty'

def test_okved_nodes_imported():
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM okved_nodes').fetchone()[0]
    conn.close()
    assert count > 0, 'okved_nodes table is empty — run import_okved_filters.py'

def test_industry_groups_imported():
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM industry_groups').fetchone()[0]
    conn.close()
    assert count > 0

def test_companies_have_required_fields():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM companies WHERE company_name_original IS NOT NULL AND company_name_original != '' LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row['company_id']
    assert row['company_name_original']

# ── Health endpoint ───────────────────────────────────────────────────────────
def test_health_endpoint():
    from app import app
    c = app.test_client()
    r = c.get('/health')
    assert r.status_code == 200
    import json
    d = json.loads(r.data)
    assert d['status'] == 'ok'
    assert d['database'] == 'ok'
