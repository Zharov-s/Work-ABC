from flask import Blueprint, request, jsonify, session
from functools import wraps
from services.contacts_service import (
    handle_bounce, add_contact_from_reply, confirm_contact,
    replace_contact, add_channel_manual, get_needs_review, get_contact_stats
)

contacts_bp = Blueprint('contacts_api', __name__)

def _auth(f):
    @wraps(f)
    def d(*a, **kw):
        if not session.get('logged_in'):
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*a, **kw)
    return d

@contacts_bp.route('/api/contacts/stats')
@_auth
def api_stats():
    return jsonify(get_contact_stats())

@contacts_bp.route('/api/contacts/needs-review')
@_auth
def api_needs_review():
    limit = min(int(request.args.get('limit', 50)), 200)
    return jsonify(get_needs_review(limit))

@contacts_bp.route('/api/channels/<int:cid>/bounce', methods=['POST'])
@_auth
def api_bounce(cid):
    data = request.get_json(silent=True) or {}
    return jsonify(handle_bounce(cid, data.get('reason', '')))

@contacts_bp.route('/api/channels/<int:cid>/confirm', methods=['POST'])
@_auth
def api_confirm(cid):
    return jsonify(confirm_contact(cid))

@contacts_bp.route('/api/channels/<int:cid>/replace', methods=['POST'])
@_auth
def api_replace(cid):
    data = request.get_json(silent=True) or {}
    new_val = (data.get('new_value') or '').strip()
    if not new_val:
        return jsonify({'ok': False, 'error': 'new_value required'}), 400
    return jsonify(replace_contact(cid, new_val, data.get('reason', '')))

@contacts_bp.route('/api/companies/<company_id>/channels/add', methods=['POST'])
@_auth
def api_add_channel(company_id):
    data = request.get_json(silent=True) or {}
    return jsonify(add_channel_manual(
        company_id,
        data.get('channel_type', 'email'),
        (data.get('value') or '').strip(),
        data.get('status', 'active'),
    ))

@contacts_bp.route('/api/contacts/add-from-reply', methods=['POST'])
@_auth
def api_add_from_reply():
    data = request.get_json(silent=True) or {}
    return jsonify(add_contact_from_reply(
        data.get('company_id', ''),
        data.get('channel_type', 'email'),
        (data.get('value') or '').strip(),
        data.get('contact_name', ''),
        data.get('source_email', ''),
    ))
