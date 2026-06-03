"""HTTP cache + per-domain rate limiter + metrics + evidence per SEARCH_ARCHITECTURE.md."""
from __future__ import annotations
import hashlib
import json
import time
import threading
from datetime import datetime, timedelta
from database import get_db

CACHE_TTL = {
    'search': 14, 'egrul': 90, 'official_site': 30,
    'aggregator': 30, 'dns_mx': 30, 'robots_txt': 7,
}

DOMAIN_LIMITS = {
    'egrul.nalog.ru':  {'rpm': 6,  'cooldown_on_block': 300},
    'rusprofile.ru':   {'rpm': 4,  'cooldown_on_block': 900},
    'checko.ru':       {'rpm': 5,  'cooldown_on_block': 900},
    'list-org.com':    {'rpm': 4,  'cooldown_on_block': 900},
    '2gis.ru':         {'rpm': 6,  'cooldown_on_block': 600},
    'default':         {'rpm': 10, 'cooldown_on_block': 300},
}

_rate_state: dict[str, dict] = {}
_rate_lock = threading.Lock()


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def get_cached(url: str, source_type: str = 'search') -> str | None:
    ttl_days = CACHE_TTL.get(source_type, 14)
    expires = (datetime.utcnow() - timedelta(days=ttl_days)).strftime('%Y-%m-%d %H:%M:%S')
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT response_text FROM http_cache WHERE cache_key=? AND fetched_at>?',
            (_cache_key(url), expires)
        ).fetchone()
        conn.close()
        return row['response_text'] if row else None
    except Exception:
        return None


def save_cache(url: str, text: str, source_type: str = 'search', status_code: int = 200) -> None:
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    try:
        conn = get_db()
        conn.execute(
            '''INSERT OR REPLACE INTO http_cache
               (cache_key, url, domain, status_code, response_text, fetched_at, source_type)
               VALUES (?,?,?,?,?,?,?)''',
            (_cache_key(url), url, domain, status_code, text, now, source_type)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def rate_limit_wait(domain: str) -> None:
    limits = DOMAIN_LIMITS.get(domain, DOMAIN_LIMITS['default'])
    min_interval = 60.0 / limits['rpm']
    with _rate_lock:
        state = _rate_state.setdefault(domain, {'last_call': 0.0, 'blocked_until': 0.0})
        now = time.monotonic()
        if state['blocked_until'] > now:
            time.sleep(state['blocked_until'] - now)
            state['blocked_until'] = 0.0
        elapsed = now - state['last_call']
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        state['last_call'] = time.monotonic()


def mark_domain_blocked(domain: str) -> None:
    cooldown = DOMAIN_LIMITS.get(domain, DOMAIN_LIMITS['default'])['cooldown_on_block']
    with _rate_lock:
        state = _rate_state.setdefault(domain, {'last_call': 0.0, 'blocked_until': 0.0})
        state['blocked_until'] = time.monotonic() + cooldown


def record_metric(run_id: int, name: str, value: float = 0.0, text: str = '', source: str = '') -> None:
    try:
        conn = get_db()
        conn.execute(
            'INSERT INTO research_metrics (run_id, metric_name, metric_value, metric_text, source) VALUES (?,?,?,?,?)',
            (run_id, name, value, text, source)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def save_rejected(run_id: int, company_name: str, reason: str,
                  inn: str = '', website: str = '', lead_score: float = 0.0,
                  email: str = '', phone: str = '', source_url: str = '',
                  diagnostic: dict | None = None) -> None:
    norm = company_name.lower().strip()
    try:
        conn = get_db()
        conn.execute(
            '''INSERT INTO rejected_candidates
               (run_id, company_name, normalized_company_name, inn, website, reason,
                lead_score, best_email, best_phone, source_url, diagnostic_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (run_id, company_name, norm, inn, website, reason,
             lead_score, email, phone, source_url,
             json.dumps(diagnostic, ensure_ascii=False) if diagnostic else None)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def save_evidence_row(contact_id: int, run_id: int, company_key: str,
                      field_name: str, value: str, source_url: str,
                      source_type: str, extraction_method: str,
                      confidence: float, reliability: float,
                      accepted: bool = True, reject_reason: str = '',
                      snippet: str = '') -> None:
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    try:
        conn = get_db()
        conn.execute(
            '''INSERT INTO contact_evidence
               (contact_id, run_id, company_key, field_name, field_value,
                source_url, source_type, extraction_method,
                confidence, reliability, accepted, reject_reason,
                evidence_snippet, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (contact_id, run_id, company_key, field_name, value,
             source_url, source_type, extraction_method,
             confidence, reliability, 1 if accepted else 0,
             reject_reason, snippet[:500], now)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
