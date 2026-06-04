"""
Filter service: translates filter requests into SQL WHERE clauses
for the companies table. Supports OKVED hierarchy, industry groups,
regions, channel availability, and quality statuses.
"""
from __future__ import annotations
from database import get_db
from repositories.companies_repo import get_okved_tree


# ── OKVED section → numeric class range ──────────────────────────────────────
_SECTION_RANGES: dict[str, tuple[int, int]] = {
    'A': (1, 3), 'B': (5, 9), 'C': (10, 33), 'D': (35, 35),
    'E': (36, 39), 'F': (41, 43), 'G': (45, 47), 'H': (49, 53),
    'I': (55, 56), 'J': (58, 63), 'K': (64, 66), 'L': (68, 68),
    'M': (69, 75), 'N': (77, 82), 'O': (84, 84), 'P': (85, 85),
    'Q': (86, 88), 'R': (90, 93), 'S': (94, 96), 'T': (97, 98),
    'U': (99, 99),
}


def _expand_code(code: str) -> list[str]:
    """
    Expand a section letter ('C'), class ('26'), or specific code ('26.51')
    into a list of LIKE patterns for matching company_okveds / okved_main_code.
    """
    code = code.strip()
    if not code:
        return []
    # Section letter (e.g. 'C')
    if len(code) == 1 and code.isalpha():
        rng = _SECTION_RANGES.get(code.upper())
        if rng:
            return [f'{n}.%' for n in range(rng[0], rng[1] + 1)] + \
                   [str(n) for n in range(rng[0], rng[1] + 1)]
        return []
    # Class (e.g. '26') — two digits, no dot
    if code.isdigit():
        return [f'{code}.%', code]
    # Specific code like '26.51' — match itself and children
    return [code, f'{code}.%']


def _build_okved_conditions(
    include: list[str],
    exclude: list[str],
    mode: str,      # 'main' | 'all'
) -> tuple[str, list]:
    """
    Returns (sql_fragment, params) for OKVED filtering.
    mode='main' → filter on companies.okved_main_code
    mode='all'  → filter via company_okveds JOIN (includes additional OKVEDs)
    """
    conditions: list[str] = []
    params: list = []

    if not include and not exclude:
        return '', []

    if mode == 'all':
        # EXISTS subquery against company_okveds
        if include:
            inc_patterns = []
            for code in include:
                inc_patterns.extend(_expand_code(code))
            like_sql = ' OR '.join(['co.okved_code LIKE ?' for _ in inc_patterns])
            conditions.append(
                f'EXISTS (SELECT 1 FROM company_okveds co WHERE co.company_id=companies.company_id AND ({like_sql}))'
            )
            params.extend(inc_patterns)
        if exclude:
            exc_patterns = []
            for code in exclude:
                exc_patterns.extend(_expand_code(code))
            like_sql = ' OR '.join(['co.okved_code LIKE ?' for _ in exc_patterns])
            conditions.append(
                f'NOT EXISTS (SELECT 1 FROM company_okveds co WHERE co.company_id=companies.company_id AND ({like_sql}))'
            )
            params.extend(exc_patterns)
    else:
        # Filter on companies.okved_main_code
        if include:
            inc_patterns = []
            for code in include:
                inc_patterns.extend(_expand_code(code))
            like_sql = ' OR '.join(['companies.okved_main_code LIKE ?' for _ in inc_patterns])
            conditions.append(f'({like_sql})')
            params.extend(inc_patterns)
        if exclude:
            exc_patterns = []
            for code in exclude:
                exc_patterns.extend(_expand_code(code))
            like_sql = ' OR '.join(['companies.okved_main_code LIKE ?' for _ in exc_patterns])
            conditions.append(f'NOT ({like_sql})')
            params.extend(exc_patterns)

    return ' AND '.join(conditions), params


def build_filter_where(req: dict) -> tuple[str, list]:
    """
    Build SQL WHERE clause from a filter request dict.

    Supported keys:
      okved_include  list[str]  — OKVED codes/sections to include
      okved_exclude  list[str]  — OKVED codes/sections to exclude
      okved_mode     str        — 'main' | 'all'
      regions        list[str]
      industry_groups list[str]
      has_email      bool
      has_phone      bool
      has_website    bool
      match_statuses list[str]  — filter by companies.match_status
      okved_statuses list[str]  — filter by companies.okved_status
      q              str        — full-text search
      exclude_bounced bool
      exclude_unsubscribed bool
    """
    conditions: list[str] = []
    params: list = []

    # OKVED
    okved_inc = req.get('okved_include') or []
    okved_exc = req.get('okved_exclude') or []
    okved_mode = req.get('okved_mode', 'main')
    if okved_inc or okved_exc:
        sql, p = _build_okved_conditions(okved_inc, okved_exc, okved_mode)
        if sql:
            conditions.append(sql)
            params.extend(p)

    # Regions
    regions = req.get('regions') or []
    if regions:
        placeholders = ','.join('?' * len(regions))
        conditions.append(f'companies.region IN ({placeholders})')
        params.extend(regions)

    # Industry groups (by name)
    industries = req.get('industry_groups') or []
    if industries:
        placeholders = ','.join('?' * len(industries))
        conditions.append(f'companies.industry_group_final IN ({placeholders})')
        params.extend(industries)

    # Channel filters via subquery
    if req.get('has_email'):
        conditions.append(
            "EXISTS (SELECT 1 FROM company_channels cc "
            "WHERE cc.company_id=companies.company_id AND cc.channel_type='email' AND cc.status='active')"
        )
    if req.get('has_phone'):
        conditions.append(
            "EXISTS (SELECT 1 FROM company_channels cc "
            "WHERE cc.company_id=companies.company_id AND cc.channel_type IN ('mobile_phone','landline_phone') AND cc.status='active')"
        )
    if req.get('has_website'):
        conditions.append("companies.website IS NOT NULL AND companies.website != ''")

    # Quality statuses
    match_statuses = req.get('match_statuses') or []
    if match_statuses:
        placeholders = ','.join('?' * len(match_statuses))
        conditions.append(f'companies.match_status IN ({placeholders})')
        params.extend(match_statuses)

    okved_statuses = req.get('okved_statuses') or []
    if okved_statuses:
        placeholders = ','.join('?' * len(okved_statuses))
        conditions.append(f'companies.okved_status IN ({placeholders})')
        params.extend(okved_statuses)

    # Search
    q = (req.get('q') or '').strip()
    if q:
        conditions.append(
            '(companies.company_name_original LIKE ? OR companies.inn LIKE ? OR companies.website LIKE ?)'
        )
        like = f'%{q}%'
        params.extend([like, like, like])

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    return where, params


def count_preview(req: dict) -> dict:
    """Return quick count stats for a filter request."""
    where, params = build_filter_where(req)
    conn = get_db()

    total = conn.execute(f'SELECT COUNT(*) FROM companies {where}', params).fetchone()[0]

    # With active email channel
    email_cond = (
        "EXISTS (SELECT 1 FROM company_channels cc "
        "WHERE cc.company_id=companies.company_id AND cc.channel_type='email' AND cc.status='active')"
    )
    email_where = ('WHERE ' + ' AND '.join(
        ([c for c in (where.replace('WHERE ', '', 1).split(' AND ') if where else [])]) + [email_cond]
    )) if where else f'WHERE {email_cond}'
    # Simpler: just append
    if where:
        email_where = where + f' AND {email_cond}'
    else:
        email_where = f'WHERE {email_cond}'

    with_email = conn.execute(
        f'SELECT COUNT(*) FROM companies {email_where}', params
    ).fetchone()[0]

    conn.close()
    return {
        'total': total,
        'with_email': with_email,
        'mailing_ready': with_email,
    }
