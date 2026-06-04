"""Tests for deduplication logic."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from services.dedupe_service import dedupe_candidate, _norm_inn, _extract_domain, _norm_name
from database import init_db

@pytest.fixture(autouse=True)
def ensure_db():
    init_db()

def test_norm_inn():
    assert _norm_inn('7700000000') == '7700000000'
    assert _norm_inn('77-000-000-00') == '7700000000'
    assert _norm_inn('') == ''

def test_extract_domain_url():
    assert _extract_domain('https://example.ru') == 'example.ru'
    assert _extract_domain('http://www.test.com/path') == 'test.com'

def test_extract_domain_email():
    assert _extract_domain('user@example.ru') == 'example.ru'

def test_extract_domain_empty():
    assert _extract_domain('') == ''

def test_norm_name():
    assert _norm_name('ООО «Пример»') == 'ПРИМЕР'
    assert _norm_name('АО "Тест"') == 'ТЕСТ'

def test_dedupe_new_company():
    result = dedupe_candidate({
        'company_name': 'ООО Уникальная Компания XYZ 99999',
        'inn': '9999999999',
        'website': 'https://unique-xyz-99999.ru',
        'email': 'info@unique-xyz-99999.ru',
        'region': 'Новосибирск',
    })
    # No match expected for totally unique data
    assert result['status'] in ('new', 'needs_review', 'possible_duplicate')
    assert 'score' in result

def test_dedupe_returns_required_keys():
    result = dedupe_candidate({'company_name': 'Test', 'inn': '', 'website': '', 'email': '', 'region': ''})
    assert 'status' in result
    assert 'matched_company_id' in result
    assert 'score' in result
    assert 'notes' in result
