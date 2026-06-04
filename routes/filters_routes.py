from flask import Blueprint, request, jsonify
from services.filters_service import build_filter_where, count_preview
from repositories.companies_repo import (
    list_companies, get_okved_tree, get_industry_groups, get_regions
)
from database import get_db

filters_bp = Blueprint('filters', __name__)


@filters_bp.route('/api/filters/okved-tree')
def api_okved_tree():
    return jsonify(get_okved_tree())


@filters_bp.route('/api/filters/industry-groups')
def api_industry_groups():
    return jsonify(get_industry_groups())


@filters_bp.route('/api/filters/regions')
def api_regions():
    return jsonify(get_regions())


@filters_bp.route('/api/filters/count-preview', methods=['POST'])
def api_count_preview():
    req = request.get_json(silent=True) or {}
    return jsonify(count_preview(req))


@filters_bp.route('/api/filters/save-preset', methods=['POST'])
def api_save_preset():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Введите название пресета'})
    import json as _json
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO saved_filter_presets (name, filter_json, scope) VALUES (?,?,?)",
        (name, _json.dumps(data.get('filter', {}), ensure_ascii=False),
         data.get('scope', 'internal'))
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return jsonify({'ok': True, 'id': pid})


@filters_bp.route('/api/filters/presets')
def api_filter_presets():
    conn = get_db()
    rows = conn.execute(
        'SELECT id, name, filter_json, scope, created_at FROM saved_filter_presets ORDER BY id DESC'
    ).fetchall()
    conn.close()
    import json as _json
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['filter'] = _json.loads(d.pop('filter_json'))
        except Exception:
            d['filter'] = {}
        result.append(d)
    return jsonify(result)


@filters_bp.route('/api/companies/filter', methods=['POST'])
def api_companies_filter():
    req  = request.get_json(silent=True) or {}
    page     = max(1, int(req.get('page', 1)))
    per_page = min(int(req.get('per_page', 50)), 200)

    where, params = build_filter_where(req)
    rows, total   = list_companies(where, params, page, per_page)

    return jsonify({
        'total':      total,
        'page':       page,
        'per_page':   per_page,
        'total_pages': max(1, (total + per_page - 1) // per_page),
        'companies':  rows,
    })
