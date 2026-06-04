from flask import Blueprint, request, jsonify, session
from functools import wraps
from services.companies_service import (
    get_company_card, update_company, add_channel, update_channel_status
)

companies_bp = Blueprint('companies_api', __name__)

def _auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

@companies_bp.route('/api/companies/<company_id>/card')
@_auth
def api_company_card(company_id):
    card = get_company_card(company_id)
    if not card:
        return jsonify({'error': 'Компания не найдена'}), 404
    return jsonify(card)

@companies_bp.route('/api/companies/<company_id>', methods=['PATCH'])
@_auth
def api_update_company(company_id):
    data = request.get_json(silent=True) or {}
    if update_company(company_id, data):
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Компания не найдена'}), 404

@companies_bp.route('/api/companies/<company_id>/channels', methods=['POST'])
@_auth
def api_add_channel(company_id):
    data = request.get_json(silent=True) or {}
    result = add_channel(
        company_id,
        data.get('channel_type', ''),
        (data.get('value') or '').strip(),
        data.get('source', 'manual')
    )
    return jsonify(result), (200 if result['ok'] else 400)

@companies_bp.route('/api/channels/<int:channel_id>/status', methods=['PATCH'])
@_auth
def api_channel_status(channel_id):
    data = request.get_json(silent=True) or {}
    status = data.get('status', '')
    if not status:
        return jsonify({'ok': False, 'error': 'status required'}), 400
    ok = update_channel_status(channel_id, status, data.get('reason', ''))
    return jsonify({'ok': ok})
