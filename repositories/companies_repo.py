"""Repository for querying companies table. All SQL, no business logic."""
from __future__ import annotations
from database import get_db


def get_company_by_id(company_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute('SELECT * FROM companies WHERE company_id=?', (company_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_companies(where: str, params: list, page: int, per_page: int) -> tuple[list[dict], int]:
    conn = get_db()
    total = conn.execute(f'SELECT COUNT(*) FROM companies {where}', params).fetchone()[0]
    rows  = conn.execute(
        f'SELECT * FROM companies {where} ORDER BY company_name_original COLLATE NOCASE LIMIT ? OFFSET ?',
        params + [per_page, (page - 1) * per_page]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_company_channels(company_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM company_channels WHERE company_id=? ORDER BY is_primary DESC, channel_type',
        (company_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_company_okveds(company_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM company_okveds WHERE company_id=? ORDER BY CASE okved_role WHEN 'main' THEN 0 ELSE 1 END, okved_code",
        (company_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_okved_tree() -> list[dict]:
    """Build OKVED tree from okved_nodes table."""
    conn = get_db()
    nodes = conn.execute(
        'SELECT level, code, name, parent_code, company_count FROM okved_nodes ORDER BY code'
    ).fetchall()
    conn.close()

    sections: dict[str, dict] = {}
    classes:  dict[str, dict] = {}

    for n in nodes:
        if n['level'] == 'section':
            sections[n['code']] = {
                'section': n['code'], 'name': n['name'],
                'company_count': n['company_count'], 'classes': []
            }

    for n in nodes:
        if n['level'] == 'class':
            entry = {'code': n['code'], 'name': n['name'],
                     'company_count': n['company_count'], 'codes': []}
            classes[n['code']] = entry
            if n['parent_code'] in sections:
                sections[n['parent_code']]['classes'].append(entry)

    for n in nodes:
        if n['level'] == 'code' and n['parent_code'] in classes:
            classes[n['parent_code']]['codes'].append({
                'code': n['code'], 'name': n['name'],
                'company_count': n['company_count']
            })

    return list(sections.values())


def get_industry_groups() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        'SELECT group_id, name, company_count FROM industry_groups ORDER BY company_count DESC'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_regions() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT region, COUNT(*) AS company_count FROM companies "
        "WHERE region IS NOT NULL AND region != '' "
        "GROUP BY region ORDER BY company_count DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
