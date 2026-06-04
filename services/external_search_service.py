"""
External company search with provider architecture.
Providers: mock_provider (default), kontur_provider, dadata_provider.
All providers return a list of candidate dicts.
"""
from __future__ import annotations
import json
import random
import hashlib
from services.dedupe_service import dedupe_candidate
from repositories.external_candidates_repo import save_candidate, candidate_exists


# ── Provider registry ─────────────────────────────────────────────────────────

def _mock_provider(filter_req: dict, limit: int) -> list[dict]:
    """Generate realistic Russian B2B company candidates for demo/dev."""
    import time

    INDUSTRY_NAMES = {
        'C': ['Завод', 'Производство', 'Технологии', 'Системы', 'Приборы', 'Оборудование'],
        'J': ['Дата-центр', 'ИТ-решения', 'Программные системы', 'Цифровые технологии'],
        'M': ['Инжиниринг', 'Консалтинг', 'Лаборатория', 'Научный центр', 'Институт'],
        '_': ['Группа компаний', 'Холдинг', 'Корпорация', 'Центр'],
    }
    CITY_PREFIXES = {
        'Москва': ['Московский', 'Столичный', 'Центральный'],
        'Санкт-Петербург': ['Невский', 'Питерский', 'Балтийский'],
        'Новосибирск': ['Сибирский', 'Новосибирский'],
        'Екатеринбург': ['Уральский', 'Свердловский'],
    }
    TLD = ['.ru', '.com', '.tech', '.systems', '.pro']

    okved_inc = filter_req.get('okved_include') or []
    sect = okved_inc[0][0] if okved_inc and okved_inc[0].isalpha() else '_'
    names = INDUSTRY_NAMES.get(sect, INDUSTRY_NAMES['_'])

    regions = filter_req.get('regions') or ['Москва']
    region = regions[0] if regions else 'Москва'
    prefix = CITY_PREFIXES.get(region, [region[:6]])[0]

    seed = hashlib.md5(json.dumps(filter_req, sort_keys=True).encode()).hexdigest()
    rng = random.Random(seed)

    results = []
    for i in range(min(limit, 25)):
        n1 = rng.choice(names)
        n2 = rng.choice(['Плюс', 'Про', 'Групп', 'Инвест', 'Техно', 'Профи', 'Сервис', 'Инжиниринг'])
        cname = f'ООО «{prefix} {n1} {n2}»'
        domain_raw = f'{prefix.lower()}{n1.lower()}{n2.lower()}'.replace(' ', '').replace('«', '').replace('»', '')[:16]
        domain_raw = ''.join(c for c in domain_raw if c.isalnum())
        tld = rng.choice(TLD)
        domain = f'{domain_raw}{tld}'
        inn_digits = str(rng.randint(7700000000, 7799999999))
        okved = okved_inc[0].replace('C', '26').replace('J', '62').replace('M', '72') if okved_inc else '26.51'
        if okved.isalpha():
            okved = '26.51'

        results.append({
            'company_name':   cname,
            'inn':            inn_digits,
            'website':        f'https://{domain}',
            'website_domain': domain,
            'email':          f'info@{domain}',
            'email_domain':   domain,
            'region':         region,
            'city':           region,
            'okved_main_code': okved,
            'industry_group': filter_req.get('industry_groups', [''])[0] if filter_req.get('industry_groups') else '',
            'external_id':    f'mock_{seed[:6]}_{i}',
        })
    return results


PROVIDERS = {
    'mock':   _mock_provider,
    'kontur': None,   # stub — подключить API-ключ в настройках
    'dadata': None,   # stub
}


# ── Main search function ──────────────────────────────────────────────────────

def search_external(filter_req: dict, provider_id: str = 'mock', limit: int = 20) -> dict:
    """
    Run external search, deduplicate, save candidates.
    Returns summary dict.
    """
    provider_fn = PROVIDERS.get(provider_id)
    if provider_fn is None:
        return {'ok': False, 'error': f'Провайдер «{provider_id}» не подключён. Используйте mock для тестирования.'}

    raw_results = provider_fn(filter_req, limit)
    filter_json = json.dumps(filter_req, ensure_ascii=False)

    saved = 0
    stats = {'new': 0, 'duplicate': 0, 'possible_duplicate': 0, 'needs_review': 0, 'skipped': 0}
    candidates_out = []

    for item in raw_results:
        # Skip already-saved exact duplicates
        if candidate_exists(item['company_name'], item.get('region', ''), provider_id):
            stats['skipped'] += 1
            continue

        # Deduplicate against internal base
        dedup = dedupe_candidate(item)
        status = dedup['status']
        stats[status] = stats.get(status, 0) + 1

        cid = save_candidate({
            **item,
            'external_source':    provider_id,
            'dedupe_status':      status,
            'matched_company_id': dedup['matched_company_id'],
            'dedupe_score':       dedup['score'],
            'dedupe_notes':       dedup['notes'],
            'filter_request_json': filter_json,
            'raw_json':           json.dumps(item, ensure_ascii=False),
        })
        saved += 1
        candidates_out.append({**item, 'id': cid, 'dedupe_status': status,
                                'matched_company_id': dedup['matched_company_id'],
                                'dedupe_notes': dedup['notes']})

    return {
        'ok': True,
        'provider': provider_id,
        'total_found': len(raw_results),
        'saved': saved,
        'stats': stats,
        'candidates': candidates_out,
    }
