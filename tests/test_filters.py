"""Tests for OKVED filter logic and company filtering API."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from services.filters_service import build_filter_where, _expand_code, count_preview
from database import init_db, get_db

@pytest.fixture(autouse=True)
def ensure_db():
    init_db()

# ── _expand_code ─────────────────────────────────────────────────────────────
def test_expand_section_c():
    patterns = _expand_code('C')
    # Section C = classes 10-33
    assert any('10.%' in p or p == '10' for p in patterns)
    assert any('26.%' in p or p == '26' for p in patterns)
    assert any('33.%' in p or p == '33' for p in patterns)

def test_expand_class():
    patterns = _expand_code('26')
    assert '26.%' in patterns
    assert '26' in patterns

def test_expand_specific_code():
    patterns = _expand_code('26.51')
    assert '26.51' in patterns
    assert '26.51.%' in patterns

def test_expand_empty():
    assert _expand_code('') == []

# ── build_filter_where ────────────────────────────────────────────────────────
def test_empty_filter():
    where, params = build_filter_where({})
    assert where == ''
    assert params == []

def test_okved_main_mode():
    where, params = build_filter_where({'okved_include': ['26'], 'okved_mode': 'main'})
    assert 'okved_main_code' in where
    assert len(params) > 0

def test_okved_all_mode():
    where, params = build_filter_where({'okved_include': ['26'], 'okved_mode': 'all'})
    assert 'company_okveds' in where

def test_okved_exclude():
    where, params = build_filter_where({'okved_include': ['C'], 'okved_exclude': ['G'], 'okved_mode': 'main'})
    assert 'NOT' in where

def test_region_filter():
    where, params = build_filter_where({'regions': ['Москва']})
    assert 'region' in where
    assert 'Москва' in params

def test_industry_filter():
    where, params = build_filter_where({'industry_groups': ['Электроника, электротехника и приборостроение']})
    assert 'industry_group_final' in where

def test_has_email_filter():
    where, params = build_filter_where({'has_email': True})
    assert 'company_channels' in where
    assert "channel_type='email'" in where

def test_has_phone_filter():
    where, params = build_filter_where({'has_phone': True})
    assert 'mobile_phone' in where

def test_search_query():
    where, params = build_filter_where({'q': 'Электрон'})
    assert 'LIKE' in where
    assert any('%Электрон%' in str(p) for p in params)

# ── count_preview ─────────────────────────────────────────────────────────────
def test_count_preview_total():
    result = count_preview({})
    assert 'total' in result
    assert result['total'] >= 0

def test_count_preview_section_c():
    result = count_preview({'okved_include': ['C'], 'okved_mode': 'main'})
    assert result['total'] > 0
    assert result['with_email'] >= 0
    assert result['with_email'] <= result['total']
