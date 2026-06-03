"""Confidence scoring and lead quality scoring per SEARCH_ARCHITECTURE.md."""
from __future__ import annotations
import re
from research_models import LeadScore, SOURCE_RELIABILITY


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def score_field_confidence(
    source_type: str,
    extraction_method: str,
    company_match: float = 0.5,
    cross_source_agreement: float = 0.0,
    freshness: float = 1.0,
    format_valid: float = 1.0,
) -> float:
    reliability = SOURCE_RELIABILITY.get(source_type, 0.45)
    extraction_quality = (
        0.9 if extraction_method in ('regex', 'egrul_json') else
        0.7 if extraction_method == 'html_parser' else
        0.5 if extraction_method == 'local_llm' else 0.4
    )
    return clamp(
        0.40 * reliability +
        0.25 * extraction_quality +
        0.15 * company_match +
        0.10 * cross_source_agreement +
        0.05 * freshness +
        0.05 * format_valid
    )


def score_lead(contact: dict) -> LeadScore:
    penalties: list[str] = []

    has_inn = bool(contact.get('inn'))
    has_website = bool(contact.get('website'))
    has_name = bool(contact.get('company_name'))
    company_identity = clamp(
        (0.5 if has_name else 0.0) +
        (0.3 if has_inn else 0.0) +
        (0.2 if has_website else 0.0)
    )
    website_score = 0.9 if has_website else 0.0

    personal_email = contact.get('personal_email') or ''
    generic_email = contact.get('generic_email') or ''
    email_score = 0.95 if personal_email else (0.75 if generic_email else 0.0)

    mobile = contact.get('mobile_phone') or ''
    generic_phone = contact.get('generic_phone') or ''
    phone_score = 0.90 if mobile else (0.70 if generic_phone else 0.0)

    person = contact.get('person_name') or ''
    if person and len(person.split()) >= 2:
        lpr_score = 0.85
    elif person:
        lpr_score = 0.50
        penalties.append('lpr_single_word_name')
    else:
        lpr_score = 0.0

    inn_val = re.sub(r'\D', '', contact.get('inn') or '')
    inn_score = 1.0 if len(inn_val) in (10, 12) else 0.0

    all_fields = ['company_name', 'website', 'email', 'phone', 'inn', 'person_name']
    completeness = len([f for f in all_fields if contact.get(f)]) / len(all_fields)

    total = clamp(
        0.18 * company_identity +
        0.14 * website_score +
        0.18 * email_score +
        0.12 * phone_score +
        0.12 * lpr_score +
        0.10 * inn_score +
        0.08 * 1.0 +   # region (pre-validated)
        0.05 * 0.7 +   # source_agreement default
        0.03 * 1.0     # freshness
    )

    return LeadScore(
        total=total,
        company_identity=company_identity,
        website_quality=website_score,
        contact_quality=email_score,
        lpr_quality=lpr_score,
        region_match=1.0,
        segment_match=1.0,
        source_agreement=0.7,
        freshness=1.0,
        completeness=completeness,
        penalties=penalties,
    )


def infer_source_type(source_url: str, pass_name: str = '') -> str:
    url = (source_url or '').lower()
    if 'nalog.ru' in url or 'egrul' in url:
        return 'egrul_nalog'
    if 'rusprofile' in url:
        return 'rusprofile'
    if 'checko' in url:
        return 'checko'
    if 'list-org' in url:
        return 'list_org'
    if 'zachestnyibiznes' in url:
        return 'zachestnyibiznes'
    if '2gis' in url:
        return '2gis'
    if pass_name in ('pass_1', 'pass_2', 'pass_3'):
        return 'official_site_html'
    return 'search_snippet'
