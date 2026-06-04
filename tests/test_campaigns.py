"""Tests for campaign services."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from database import init_db
from services.campaigns_service import get_summary_stats, get_campaign_list
from services.mailer_service import validate_before_send, build_audience_from_filter

@pytest.fixture(autouse=True)
def ensure_db():
    init_db()

def test_summary_stats_keys():
    stats = get_summary_stats()
    for key in ['total_campaigns','total_sent','total_failed','open_rate','click_rate']:
        assert key in stats

def test_campaign_list():
    campaigns = get_campaign_list(5)
    assert isinstance(campaigns, list)
    for c in campaigns:
        assert 'id' in c
        assert 'template' in c

def test_validate_no_emails():
    result = validate_before_send([], 'mitino', False)
    assert result['ok'] is False
    assert any('получател' in e.lower() for e in result['errors'])

def test_validate_invalid_emails():
    result = validate_before_send(['not-email', 'also-bad'], 'mitino', False)
    assert result['ok'] is False

def test_validate_missing_template():
    result = validate_before_send(['test@test.ru'], 'nonexistent_template', False)
    assert result['ok'] is False

def test_validate_no_test_sent():
    result = validate_before_send(['test@test.ru'], 'mitino', False)
    assert result['ok'] is False
    assert any('тест' in e.lower() for e in result['errors'])

def test_validate_all_ok():
    result = validate_before_send(['test@test.ru', 'other@test.ru'], 'mitino', True)
    # Should pass all format/template/dedup checks (test_sent=True)
    assert result['ok'] is True

def test_audience_from_filter_structure():
    result = build_audience_from_filter({'okved_include': ['C'], 'regions': ['Москва']}, 'mitino')
    assert 'emails' in result
    assert 'total_companies' in result
    assert 'ready_count' in result
    assert 'skipped_count' in result
    assert result['total_companies'] > 0

def test_audience_empty_filter():
    # Should return some results even with no filter
    result = build_audience_from_filter({}, 'mitino')
    assert 'ready_count' in result
