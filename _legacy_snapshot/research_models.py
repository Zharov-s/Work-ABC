"""Core dataclasses for evidence-first research architecture."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CandidateCompany:
    raw_name: str
    normalized_name: str
    legal_form: str | None = None
    inn: str | None = None
    ogrn: str | None = None
    website: str | None = None
    region: str | None = None
    address: str | None = None
    segment: str = ''
    discovery_sources: list[str] = field(default_factory=list)
    discovery_score: float = 0.5
    priority_score: float = 0.5
    status: Literal['new', 'queued', 'processing', 'accepted', 'rejected', 'duplicate'] = 'new'


@dataclass
class EvidenceItem:
    run_id: int
    company_key: str
    field_name: str
    value: str
    source_url: str
    source_type: str       # official_site, egrul, 2gis, aggregator, search_snippet
    extraction_method: str # regex, html_parser, local_llm, egrul_json, manual_rule
    confidence: float
    reliability: float
    accepted: bool = True
    reject_reason: str | None = None
    evidence_snippet: str = ''
    collected_at: str = ''


@dataclass
class FieldConfidence:
    value: str
    field_name: str
    confidence: float
    sources: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    reject_reason: str | None = None


@dataclass
class LeadScore:
    total: float
    company_identity: float = 0.0
    website_quality: float = 0.0
    contact_quality: float = 0.0
    lpr_quality: float = 0.0
    region_match: float = 0.0
    segment_match: float = 0.0
    source_agreement: float = 0.0
    freshness: float = 1.0
    completeness: float = 0.0
    penalties: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    accepted: bool
    reason: str = ''
    notes: list[str] = field(default_factory=list)


SOURCE_RELIABILITY: dict[str, float] = {
    'egrul_nalog':        0.95,
    'official_site_html': 0.90,
    'official_site_pdf':  0.88,
    '2gis':               0.75,
    'rusprofile':         0.72,
    'checko':             0.72,
    'list_org':           0.65,
    'zachestnyibiznes':   0.65,
    'technopark':         0.70,
    'association':        0.65,
    'search_snippet':     0.45,
    'local_llm':          0.00,
}

REJECT_REASONS = {
    'duplicate_company', 'duplicate_email', 'duplicate_inn',
    'low_lead_score', 'low_field_confidence',
    'no_required_email', 'no_required_phone', 'no_required_website', 'no_required_inn',
    'website_is_aggregator', 'website_confidence_low',
    'email_invalid_format', 'email_freemail_not_corporate', 'email_domain_mismatch',
    'email_generic_but_personal_required', 'phone_invalid',
    'mobile_phone_without_lpr_context', 'director_invalid', 'director_conflict',
    'region_mismatch', 'segment_mismatch', 'source_unavailable', 'captcha_required',
    'low_priority_before_enrichment',
}
