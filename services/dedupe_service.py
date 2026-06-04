"""
Deduplication: checks external candidates against internal companies table.
Statuses: duplicate, possible_duplicate, needs_review, new
"""
from __future__ import annotations
import re
from urllib.parse import urlparse
from database import get_db


def _norm_inn(inn: str) -> str:
    return re.sub(r'\D', '', inn or '')


def _extract_domain(s: str) -> str:
    s = (s or '').strip().lower()
    if not s:
        return ''
    if '@' in s:
        return s.split('@')[-1]
    try:
        parsed = urlparse(s if '://' in s else 'https://' + s)
        return parsed.netloc.lstrip('www.') or ''
    except Exception:
        return ''


def _norm_name(name: str) -> str:
    name = (name or '').upper()
    for stop in ['ООО', 'АО', 'ОАО', 'ЗАО', 'ПАО', 'ИП', 'НАО', 'МУП', 'ГУП', 'АНО',
                 'LLC', 'JSC', 'CJSC', 'PJSC', '"', "'", '«', '»', ' ']:
        name = name.replace(stop, '')
    return re.sub(r'\s+', '', name)


def dedupe_candidate(candidate: dict) -> dict:
    """
    Compare candidate against internal companies.
    Returns {status, matched_company_id, score, notes}
    """
    inn        = _norm_inn(candidate.get('inn', ''))
    ogrn       = _norm_inn(candidate.get('ogrn', ''))
    website    = candidate.get('website', '')
    email      = candidate.get('email', '')
    name       = candidate.get('company_name', '')
    region     = (candidate.get('region') or '').strip().lower()

    site_domain  = _extract_domain(website)
    email_domain = _extract_domain(email)
    norm_name    = _norm_name(name)

    conn = get_db()

    # 1. INN exact match → duplicate
    if inn and len(inn) >= 10:
        row = conn.execute('SELECT company_id FROM companies WHERE inn=?', (inn,)).fetchone()
        if row:
            conn.close()
            return {'status': 'duplicate', 'matched_company_id': row['company_id'],
                    'score': 1.0, 'notes': f'ИНН совпал: {inn}'}

    # 2. OGRN exact match → duplicate
    if ogrn and len(ogrn) >= 13:
        row = conn.execute('SELECT company_id FROM companies WHERE ogrn=?', (ogrn,)).fetchone()
        if row:
            conn.close()
            return {'status': 'duplicate', 'matched_company_id': row['company_id'],
                    'score': 1.0, 'notes': f'ОГРН совпал: {ogrn}'}

    # 3. Website domain match → possible_duplicate
    if site_domain and len(site_domain) > 4:
        row = conn.execute(
            "SELECT company_id FROM companies WHERE website LIKE ? OR website LIKE ?",
            (f'%{site_domain}%', f'%{site_domain}%')
        ).fetchone()
        if row:
            conn.close()
            return {'status': 'possible_duplicate', 'matched_company_id': row['company_id'],
                    'score': 0.8, 'notes': f'Домен сайта совпал: {site_domain}'}

    # 4. Email domain match → possible_duplicate
    if email_domain and '.' in email_domain and email_domain not in ('gmail.com','mail.ru','yandex.ru','bk.ru','list.ru'):
        rows = conn.execute('SELECT company_id, website FROM companies WHERE website IS NOT NULL').fetchall()
        for r in rows:
            if _extract_domain(r['website']) == email_domain:
                conn.close()
                return {'status': 'possible_duplicate', 'matched_company_id': r['company_id'],
                        'score': 0.7, 'notes': f'Email-домен совпал: {email_domain}'}

    # 5. Normalized name + region → possible_duplicate
    if norm_name and len(norm_name) >= 4:
        all_companies = conn.execute(
            'SELECT company_id, company_name_normalized, region FROM companies'
        ).fetchall()
        for r in all_companies:
            rname = _norm_name(r['company_name_normalized'] or '')
            rreg  = (r['region'] or '').strip().lower()
            if rname and rname == norm_name:
                if not region or not rreg or region == rreg:
                    conn.close()
                    return {'status': 'possible_duplicate', 'matched_company_id': r['company_id'],
                            'score': 0.65, 'notes': f'Совпало нормализованное название + регион'}

    conn.close()
    return {'status': 'new', 'matched_company_id': None, 'score': 0.0, 'notes': ''}
