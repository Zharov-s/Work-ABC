"""CRUD for external_company_candidates table."""
from __future__ import annotations
from database import get_db


def save_candidate(data: dict) -> int:
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO external_company_candidates
           (external_source, external_id, company_name, inn, ogrn, website,
            website_domain, email, email_domain, region, city,
            okved_main_code, industry_group, raw_json,
            dedupe_status, matched_company_id, dedupe_score, dedupe_notes,
            filter_request_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get('external_source', 'mock'),
            data.get('external_id', ''),
            data.get('company_name', ''),
            data.get('inn', ''),
            data.get('ogrn', ''),
            data.get('website', ''),
            data.get('website_domain', ''),
            data.get('email', ''),
            data.get('email_domain', ''),
            data.get('region', ''),
            data.get('city', ''),
            data.get('okved_main_code', ''),
            data.get('industry_group', ''),
            data.get('raw_json', ''),
            data.get('dedupe_status', 'new'),
            data.get('matched_company_id'),
            data.get('dedupe_score', 0.0),
            data.get('dedupe_notes', ''),
            data.get('filter_request_json', ''),
        )
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def list_candidates(status: str | None = None, limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    conn = get_db()
    where = 'WHERE dedupe_status=?' if status else ''
    params = [status] if status else []
    total = conn.execute(f'SELECT COUNT(*) FROM external_company_candidates {where}', params).fetchone()[0]
    rows = conn.execute(
        f'SELECT * FROM external_company_candidates {where} ORDER BY id DESC LIMIT ? OFFSET ?',
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_candidate(cid: int) -> dict | None:
    conn = get_db()
    row = conn.execute('SELECT * FROM external_company_candidates WHERE id=?', (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_candidate_status(cid: int, status: str, reason: str = '') -> bool:
    conn = get_db()
    row = conn.execute('SELECT id FROM external_company_candidates WHERE id=?', (cid,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        'UPDATE external_company_candidates SET dedupe_status=? WHERE id=?',
        (status, cid)
    )
    conn.commit()
    conn.close()
    return True


def mark_imported(cid: int) -> bool:
    conn = get_db()
    row = conn.execute('SELECT * FROM external_company_candidates WHERE id=?', (cid,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE external_company_candidates SET dedupe_status='imported', imported_at=datetime('now') WHERE id=?",
        (cid,)
    )
    conn.commit()
    conn.close()
    return True


def candidate_exists(company_name: str, region: str, source: str) -> bool:
    conn = get_db()
    row = conn.execute(
        'SELECT id FROM external_company_candidates WHERE company_name=? AND region=? AND external_source=?',
        (company_name, region, source)
    ).fetchone()
    conn.close()
    return row is not None


def get_stats() -> dict:
    conn = get_db()
    total      = conn.execute('SELECT COUNT(*) FROM external_company_candidates').fetchone()[0]
    new        = conn.execute("SELECT COUNT(*) FROM external_company_candidates WHERE dedupe_status='new'").fetchone()[0]
    dupes      = conn.execute("SELECT COUNT(*) FROM external_company_candidates WHERE dedupe_status='duplicate'").fetchone()[0]
    possible   = conn.execute("SELECT COUNT(*) FROM external_company_candidates WHERE dedupe_status='possible_duplicate'").fetchone()[0]
    review     = conn.execute("SELECT COUNT(*) FROM external_company_candidates WHERE dedupe_status='needs_review'").fetchone()[0]
    imported   = conn.execute("SELECT COUNT(*) FROM external_company_candidates WHERE dedupe_status='imported'").fetchone()[0]
    rejected   = conn.execute("SELECT COUNT(*) FROM external_company_candidates WHERE dedupe_status='rejected'").fetchone()[0]
    conn.close()
    return {'total':total,'new':new,'duplicate':dupes,'possible_duplicate':possible,'needs_review':review,'imported':imported,'rejected':rejected}
