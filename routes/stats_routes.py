from flask import Blueprint, request, jsonify, session, render_template
from functools import wraps
from services.stats_service import get_dashboard_stats, get_filter_stats

stats_bp = Blueprint('stats', __name__)

def _auth(f):
    @wraps(f)
    def d(*a,**kw):
        if not session.get('logged_in'):
            return jsonify({'ok':False,'error':'Unauthorized'}),401
        return f(*a,**kw)
    return d

@stats_bp.route('/stats')
def stats_page():
    if not session.get('logged_in'):
        from flask import redirect, url_for
        return redirect(url_for('login'))
    return render_template('stats.html')

@stats_bp.route('/api/stats/dashboard')
@_auth
def api_dashboard_stats():
    return jsonify(get_dashboard_stats())

@stats_bp.route('/api/stats/filter', methods=['POST'])
@_auth
def api_filter_stats():
    req = request.get_json(silent=True) or {}
    return jsonify(get_filter_stats(req))
