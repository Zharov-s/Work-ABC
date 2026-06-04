"""
search_routes.py — two-mode search:
  Mode 1: internal DB filter (/api/companies/filter — already exists)
  Mode 2: AI-powered external search via Ollama + Tavily (new)
"""
from flask import Blueprint, request, jsonify, session, render_template
from functools import wraps
from services.external_search_service import search_external
from repositories.external_candidates_repo import (
    list_candidates, get_candidate, update_candidate_status,
    mark_imported, get_stats, candidate_exists
)
from services.dedupe_service import dedupe_candidate
from database import get_db
import json, os

search_bp = Blueprint('search', __name__)

# ── Auth helper ────────────────────────────────────────────────────────────────
def _auth(f):
    from functools import wraps
    @wraps(f)
    def dec(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return dec


# ── Pages ──────────────────────────────────────────────────────────────────────
@search_bp.route('/search')
def search_page():
    if not session.get('logged_in'):
        from flask import redirect, url_for
        return redirect(url_for('login'))
    return render_template('search.html')


# ── Internal DB search — served by /api/companies/filter (already registered) ─


# ── AI search: start run ───────────────────────────────────────────────────────
@search_bp.route('/api/search/ai-start', methods=['POST'])
@_auth
def api_ai_search_start():
    from researcher import start_research, SEGMENT_LABELS, REGION_SUFFIX
    data = request.get_json(silent=True) or {}

    okved_include  = data.get('okved_include') or []
    regions_names  = data.get('regions') or ['Москва']
    industry_groups= data.get('industry_groups') or []
    count          = max(1, min(50, int(data.get('count', 10))))
    ollama_model   = data.get('model', os.getenv('OLLAMA_MODEL', 'llama3.1:8b'))
    contact_reqs   = data.get('contact_requirements', ['company_name', 'website', 'generic_email'])

    # Map region Russian names → researcher keys
    _region_map = {
        'Москва': 'moscow', 'Московская область': 'mo', 'Россия': 'russia',
        'москва': 'moscow', 'московская область': 'mo',
    }
    region_keys = []
    for r in regions_names:
        key = _region_map.get(r, _region_map.get(r.lower(), 'moscow'))
        if key not in region_keys:
            region_keys.append(key)
    if not region_keys:
        region_keys = ['moscow']

    # Build keywords from OKVED codes + industry groups
    keywords_parts = []
    for code in okved_include:
        keywords_parts.append(code)
    for ig in industry_groups:
        keywords_parts.append(ig)

    # Map OKVED sections to researcher segments
    _okved_to_segs = {
        'C': ['electronics', 'light_industrial'],
        'J': ['it_hardware'],
        'M': ['rd_nii'],
        'B': ['light_industrial'],
        'D': ['light_industrial'],
        'Q': ['medtech'],
        'A': ['light_industrial'],
    }
    segments = []
    for code in okved_include:
        sect = code[0].upper() if len(code) >= 1 else ''
        for seg in _okved_to_segs.get(sect, ['electronics']):
            if seg not in segments:
                segments.append(seg)
    if not segments:
        segments = ['electronics']

    # Override Ollama model via env temporarily — not ideal but non-destructive
    old_model = os.environ.get('OLLAMA_MODEL', '')

    config = {
        'segments':              segments,
        'industries':            industry_groups,
        'regions':               region_keys,
        'region':                region_keys[0],
        'count':                 count,
        'keywords':              ' '.join(keywords_parts),
        'company_scales':        ['any'],
        'company_scale':         'any',
        'contact_requirements':  contact_reqs,
        'require_email':         'generic_email' in contact_reqs,
        'require_phone':         False,
        'active_only':           True,
        '_search_mode':          'candidates',   # marker — results go to external_candidates
        '_okved_filter':         okved_include,
        '_ollama_model':         ollama_model,
    }

    # Temporarily set model
    if ollama_model:
        os.environ['OLLAMA_MODEL'] = ollama_model

    run_id = start_research(config)

    # Restore
    if old_model:
        os.environ['OLLAMA_MODEL'] = old_model
    elif 'OLLAMA_MODEL' in os.environ and ollama_model:
        pass  # keep for duration of run

    return jsonify({'ok': True, 'run_id': run_id})


# ── AI search: get run status ─────────────────────────────────────────────────
@search_bp.route('/api/search/ai-status/<int:run_id>')
@_auth
def api_ai_status(run_id):
    from researcher import get_run_status
    run = get_run_status(run_id)
    if not run:
        conn = get_db()
        row = conn.execute('SELECT * FROM research_runs WHERE id=?', (run_id,)).fetchone()
        conn.close()
        if row:
            cfg = json.loads(row['config_json']) if row['config_json'] else {}
            return jsonify({'status': row['status'], 'log': row['log_text'].split('\n') if row['log_text'] else [],
                            'found_count': row['found_count'],
                            'target_count': int(cfg.get('count', 0))})
        return jsonify({'status': 'not_found', 'log': [], 'found_count': 0, 'target_count': 0})
    return jsonify({'status': run['status'], 'log': run['log'],
                    'found_count': run['found_count'],
                    'target_count': run.get('target_count', 0)})


# ── AI search: finalize run → deduplicate → save candidates ───────────────────
@search_bp.route('/api/search/ai-finalize/<int:run_id>', methods=['POST'])
@_auth
def api_ai_finalize(run_id):
    conn = get_db()
    run_row = conn.execute('SELECT config_json FROM research_runs WHERE id=?', (run_id,)).fetchone()
    contacts = conn.execute(
        'SELECT * FROM contacts WHERE run_id=?', (run_id,)
    ).fetchall()
    conn.close()

    filter_json = ''
    if run_row and run_row['config_json']:
        try:
            cfg = json.loads(run_row['config_json'])
            filter_json = json.dumps({'okved_include': cfg.get('_okved_filter', []),
                                      'regions': cfg.get('regions', [])},
                                     ensure_ascii=False)
        except Exception:
            pass

    saved = 0
    stats = {'new': 0, 'duplicate': 0, 'possible_duplicate': 0, 'skipped': 0}
    candidates_out = []

    from repositories.external_candidates_repo import save_candidate as _save
    from services.dedupe_service import dedupe_candidate as _dedup

    for row in contacts:
        r = dict(row)
        name   = r.get('company_name', '')
        region = r.get('region', '')

        if candidate_exists(name, region, 'ollama'):
            stats['skipped'] += 1
            continue

        candidate = {
            'company_name': name,
            'inn':          r.get('inn', ''),
            'website':      r.get('website', ''),
            'email':        r.get('email', '') or r.get('generic_email', '') or r.get('personal_email', ''),
            'region':       region,
            'city':         region,
            'okved_main_code': r.get('okved', ''),
        }
        # Extract domains
        from services.dedupe_service import _extract_domain
        if candidate['website']:
            candidate['website_domain'] = _extract_domain(candidate['website'])
        if candidate['email']:
            candidate['email_domain'] = _extract_domain(candidate['email'])

        dedup = _dedup(candidate)
        status = dedup['status']
        stats[status] = stats.get(status, 0) + 1

        cid = _save({
            **candidate,
            'external_source':    'ollama',
            'external_id':        f'run_{run_id}_{r.get("id", "")}',
            'dedupe_status':      status,
            'matched_company_id': dedup['matched_company_id'],
            'dedupe_score':       dedup['score'],
            'dedupe_notes':       dedup['notes'],
            'filter_request_json': filter_json,
            'raw_json':           json.dumps(candidate, ensure_ascii=False),
        })
        saved += 1
        candidates_out.append({**candidate, 'id': cid, 'dedupe_status': status,
                                'dedupe_notes': dedup['notes']})

    return jsonify({'ok': True, 'saved': saved, 'stats': stats, 'candidates': candidates_out})


# ── Candidate management ───────────────────────────────────────────────────────
@search_bp.route('/api/search/candidates')
@_auth
def api_candidates():
    status = request.args.get('status') or None
    limit  = min(int(request.args.get('limit', 50)), 200)
    offset = int(request.args.get('offset', 0))
    rows, total = list_candidates(status, limit, offset)
    return jsonify({'total': total, 'candidates': rows, 'stats': get_stats()})


@search_bp.route('/api/search/candidates/<int:cid>/import', methods=['POST'])
@_auth
def api_import_candidate(cid):
    row = get_candidate(cid)
    if not row:
        return jsonify({'ok': False, 'error': 'Кандидат не найден'}), 404

    import hashlib as _h
    company_id = 'ext_' + _h.md5(f"{row['company_name']}_{row['inn']}".encode()).hexdigest()[:10]

    conn = get_db()
    if not conn.execute('SELECT id FROM companies WHERE company_id=?', (company_id,)).fetchone():
        conn.execute(
            """INSERT INTO companies
               (company_id, company_name_original, company_name_normalized,
                inn, website, region, city, okved_main_code, industry_group_final,
                match_status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,'manual_review',datetime('now'))""",
            (company_id, row['company_name'],
             (row['company_name'] or '').upper(),
             row['inn'], row['website'], row['region'], row['city'],
             row['okved_main_code'], row['industry_group'])
        )
        if row['email']:
            conn.execute(
                'INSERT OR IGNORE INTO company_channels (company_id,channel_type,value,value_normalized,status,source_column) VALUES (?,?,?,?,?,?)',
                (company_id,'email',row['email'],row['email'].lower(),'active','external_import')
            )
        conn.commit()
    conn.close()
    mark_imported(cid)
    return jsonify({'ok': True, 'company_id': company_id})


@search_bp.route('/api/search/candidates/<int:cid>/reject', methods=['POST'])
@_auth
def api_reject_candidate(cid):
    data = request.get_json(silent=True) or {}
    return jsonify({'ok': update_candidate_status(cid, 'rejected', data.get('reason', ''))})


@search_bp.route('/api/search/candidates/<int:cid>/mark-duplicate', methods=['POST'])
@_auth
def api_mark_duplicate(cid):
    return jsonify({'ok': update_candidate_status(cid, 'duplicate')})


@search_bp.route('/api/search/stats')
@_auth
def api_search_stats():
    return jsonify(get_stats())
