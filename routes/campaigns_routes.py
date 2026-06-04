"""
campaigns_routes.py — new campaign API endpoints.
Complements existing campaigns routes in app.py.
"""
from flask import Blueprint, request, jsonify, session
from functools import wraps
from services.mailer_service import (
    build_audience_from_filter, validate_before_send,
    get_templates, send_campaign, send_pending_campaign,
)
from services.campaigns_service import get_summary_stats, get_campaign_list
from database import get_mailing_stats

campaigns_bp = Blueprint('campaigns_api', __name__)

def _auth(f):
    @wraps(f)
    def dec(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return dec


@campaigns_bp.route('/api/campaigns/audience-from-filter', methods=['POST'])
@_auth
def api_audience_from_filter():
    """Build mailing audience from companies OKVED/region filter."""
    data = request.get_json(silent=True) or {}
    filter_req   = data.get('filter', {})
    template_key = data.get('template', 'mitino')
    result = build_audience_from_filter(filter_req, template_key)
    return jsonify(result)


@campaigns_bp.route('/api/campaigns/validate', methods=['POST'])
@_auth
def api_validate():
    """Pre-send checklist validation."""
    data        = request.get_json(silent=True) or {}
    emails      = data.get('emails', [])
    template_key= data.get('template', 'mitino')
    test_sent   = bool(data.get('test_sent', False))
    result = validate_before_send(emails, template_key, test_sent)
    return jsonify(result)


@campaigns_bp.route('/api/campaigns/send-from-filter', methods=['POST'])
@_auth
def api_send_from_filter():
    """Send campaign to audience built from OKVED/region filter."""
    data         = request.get_json(silent=True) or {}
    filter_req   = data.get('filter', {})
    template_key = data.get('template', 'mitino')
    test_only    = bool(data.get('test_only', False))

    audience = build_audience_from_filter(filter_req, template_key)
    if not audience['emails']:
        return jsonify({'ok': False, 'error': 'Нет получателей', 'audience': audience})

    if test_only:
        return jsonify({'ok': True, 'audience': audience, 'test_only': True})

    # Build address string for mailer
    raw = '\n'.join(e['email'] for e in audience['emails'])
    result = send_campaign(template_key, raw)
    result['audience'] = audience
    result['mailing_stats'] = get_mailing_stats()
    return jsonify(result)


@campaigns_bp.route('/api/campaigns/stats')
@_auth
def api_campaign_stats():
    return jsonify(get_summary_stats())


@campaigns_bp.route('/api/campaigns/templates')
@_auth
def api_templates():
    meta = get_templates()
    return jsonify([{'key': k, **v} for k, v in meta.items()])
