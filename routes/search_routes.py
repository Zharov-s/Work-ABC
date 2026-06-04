from flask import Blueprint, request, jsonify, session, render_template
from functools import wraps
from services.external_search_service import search_external
from repositories.external_candidates_repo import (
    list_candidates, get_candidate, update_candidate_status,
    mark_imported, get_stats
)
from database import get_db
import json

search_bp = Blueprint('search', __name__)

def _auth(f):
    @wraps(f)
    def dec(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return dec


@search_bp.route('/search')
def search_page():
    if not session.get('logged_in'):
        from flask import redirect, url_for
        return redirect(url_for('login'))
    return render_template('search.html')


@search_bp.route('/api/search/external', methods=['POST'])
@_auth
def api_search_external():
    data = request.get_json(silent=True) or {}
    filter_req  = data.get('filter', {})
    provider_id = data.get('provider', 'mock')
    limit       = min(int(data.get('limit', 20)), 50)
    result = search_external(filter_req, provider_id, limit)
    return jsonify(result)


@search_bp.route('/api/search/candidates')
@_auth
def api_candidates():
    status  = request.args.get('status') or None
    limit   = min(int(request.args.get('limit', 50)), 200)
    offset  = int(request.args.get('offset', 0))
    rows, total = list_candidates(status, limit, offset)
    return jsonify({'total': total, 'candidates': rows, 'stats': get_stats()})


@search_bp.route('/api/search/candidates/<int:cid>/import', methods=['POST'])
@_auth
def api_import_candidate(cid):
    row = get_candidate(cid)
    if not row:
        return jsonify({'ok': False, 'error': 'Кандидат не найден'}), 404

    conn = get_db()
    # Build company_id
    import hashlib as _h
    company_id = 'ext_' + _h.md5(f"{row['company_name']}_{row['inn']}".encode()).hexdigest()[:10]

    # Check not already in companies
    existing = conn.execute('SELECT id FROM companies WHERE company_id=?', (company_id,)).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO companies
               (company_id, company_name_original, company_name_normalized,
                inn, website, region, city, okved_main_code, industry_group_final,
                match_status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,'manual_review',datetime('now'))""",
            (company_id, row['company_name'],
             row['company_name'].upper() if row['company_name'] else '',
             row['inn'], row['website'], row['region'], row['city'],
             row['okved_main_code'], row['industry_group'])
        )
        # Add channels
        if row['email']:
            conn.execute(
                "INSERT OR IGNORE INTO company_channels (company_id, channel_type, value, value_normalized, status, source_column) VALUES (?,?,?,?,?,?)",
                (company_id, 'email', row['email'], row['email'].lower(), 'active', 'external_import')
            )
        conn.commit()
    conn.close()

    mark_imported(cid)
    return jsonify({'ok': True, 'company_id': company_id})


@search_bp.route('/api/search/candidates/<int:cid>/reject', methods=['POST'])
@_auth
def api_reject_candidate(cid):
    data = request.get_json(silent=True) or {}
    ok = update_candidate_status(cid, 'rejected', data.get('reason', ''))
    return jsonify({'ok': ok})


@search_bp.route('/api/search/candidates/<int:cid>/mark-duplicate', methods=['POST'])
@_auth
def api_mark_duplicate(cid):
    ok = update_candidate_status(cid, 'duplicate')
    return jsonify({'ok': ok})


@search_bp.route('/api/search/stats')
@_auth
def api_search_stats():
    return jsonify(get_stats())
