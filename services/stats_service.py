"""Aggregated statistics for dashboard and stats page."""
from __future__ import annotations
from database import get_db


def get_dashboard_stats() -> dict:
    conn = get_db()

    # Companies
    total_co   = conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0]
    with_email = conn.execute("SELECT COUNT(DISTINCT company_id) FROM company_channels WHERE channel_type='email' AND status='active'").fetchone()[0]
    with_phone = conn.execute("SELECT COUNT(DISTINCT company_id) FROM company_channels WHERE channel_type IN ('mobile_phone','landline_phone') AND status='active'").fetchone()[0]
    with_site  = conn.execute("SELECT COUNT(*) FROM companies WHERE website IS NOT NULL AND website!=''").fetchone()[0]
    with_okved = conn.execute("SELECT COUNT(*) FROM companies WHERE okved_main_code IS NOT NULL AND okved_main_code NOT IN ('','NOT_FOUND')").fetchone()[0]
    no_okved   = total_co - with_okved
    manual_rev = conn.execute("SELECT COUNT(*) FROM companies WHERE match_status='manual_review'").fetchone()[0]
    bounced_ch = conn.execute("SELECT COUNT(DISTINCT company_id) FROM company_channels WHERE status='bounced'").fetchone()[0]

    # Channels
    ch_active  = conn.execute("SELECT COUNT(*) FROM company_channels WHERE status='active'").fetchone()[0]
    ch_bounced = conn.execute("SELECT COUNT(*) FROM company_channels WHERE status='bounced'").fetchone()[0]
    ch_unsub   = conn.execute("SELECT COUNT(*) FROM company_channels WHERE status='unsubscribed'").fetchone()[0]
    ch_review  = conn.execute("SELECT COUNT(*) FROM company_channels WHERE status='needs_review'").fetchone()[0]

    # External candidates
    ext_total  = conn.execute('SELECT COUNT(*) FROM external_company_candidates').fetchone()[0]
    ext_new    = conn.execute("SELECT COUNT(*) FROM external_company_candidates WHERE dedupe_status='new'").fetchone()[0]
    ext_poss   = conn.execute("SELECT COUNT(*) FROM external_company_candidates WHERE dedupe_status='possible_duplicate'").fetchone()[0]
    ext_imp    = conn.execute("SELECT COUNT(*) FROM external_company_candidates WHERE dedupe_status='imported'").fetchone()[0]

    # Campaigns
    n_campaigns = conn.execute('SELECT COUNT(*) FROM send_history').fetchone()[0]
    n_sent      = conn.execute('SELECT COALESCE(SUM(total_sent),0) FROM send_history').fetchone()[0]
    n_failed    = conn.execute('SELECT COALESCE(SUM(total_failed),0) FROM send_history').fetchone()[0]
    n_opens     = conn.execute('SELECT COUNT(DISTINCT token) FROM email_opens').fetchone()[0]
    n_clicks    = conn.execute('SELECT COUNT(DISTINCT token) FROM email_clicks WHERE is_unsubscribe=0').fetchone()[0]
    n_unsubs    = conn.execute('SELECT COUNT(DISTINCT token) FROM email_clicks WHERE is_unsubscribe=1').fetchone()[0]

    # Recent campaigns
    recent = [dict(r) for r in conn.execute(
        'SELECT id, template, subject, sent_at, total_sent, total_failed, status FROM send_history ORDER BY id DESC LIMIT 5'
    ).fetchall()]

    # Top regions
    top_regions = [dict(r) for r in conn.execute(
        "SELECT region, COUNT(*) AS n FROM companies WHERE region IS NOT NULL AND region!='' GROUP BY region ORDER BY n DESC LIMIT 10"
    ).fetchall()]

    # Top OKVED sections
    top_okved = [dict(r) for r in conn.execute(
        """SELECT okved_section, COUNT(*) AS n FROM companies
           WHERE okved_section IS NOT NULL AND okved_section NOT IN ('','ОКВЭД не найден')
           GROUP BY okved_section ORDER BY n DESC LIMIT 10"""
    ).fetchall()]

    # Top industries
    top_industries = [dict(r) for r in conn.execute(
        """SELECT industry_group_final AS name, COUNT(*) AS n FROM companies
           WHERE industry_group_final IS NOT NULL AND industry_group_final!=''
           GROUP BY industry_group_final ORDER BY n DESC LIMIT 10"""
    ).fetchall()]

    conn.close()
    return {
        'companies': {
            'total': total_co, 'with_email': with_email, 'with_phone': with_phone,
            'with_website': with_site, 'with_okved': with_okved, 'without_okved': no_okved,
            'manual_review': manual_rev, 'has_bounce': bounced_ch,
        },
        'channels': {
            'active': ch_active, 'bounced': ch_bounced,
            'unsubscribed': ch_unsub, 'needs_review': ch_review,
        },
        'external': {
            'total': ext_total, 'new': ext_new,
            'possible_duplicate': ext_poss, 'imported': ext_imp,
        },
        'campaigns': {
            'total': n_campaigns, 'sent': n_sent, 'failed': n_failed,
            'opens': n_opens, 'clicks': n_clicks, 'unsubs': n_unsubs,
            'open_rate':  round(n_opens  / n_sent * 100, 1) if n_sent else 0.0,
            'click_rate': round(n_clicks / n_sent * 100, 1) if n_sent else 0.0,
        },
        'recent_campaigns': recent,
        'top_regions':      top_regions,
        'top_okved':        top_okved,
        'top_industries':   top_industries,
    }


def get_filter_stats(filter_req: dict) -> dict:
    """Stats for a specific filter request."""
    from services.filters_service import build_filter_where
    conn = get_db()
    where, params = build_filter_where(filter_req)

    total       = conn.execute(f'SELECT COUNT(*) FROM companies {where}', params).fetchone()[0]
    email_cond  = "EXISTS (SELECT 1 FROM company_channels cc WHERE cc.company_id=companies.company_id AND cc.channel_type='email' AND cc.status='active')"
    bounce_cond = "EXISTS (SELECT 1 FROM company_channels cc WHERE cc.company_id=companies.company_id AND cc.status IN ('bounced','unsubscribed'))"

    wp  = params + []
    with_email = conn.execute(
        f'SELECT COUNT(*) FROM companies {where}{"AND" if where else "WHERE"} {email_cond}',
        wp
    ).fetchone()[0] if where else conn.execute(f'SELECT COUNT(*) FROM companies WHERE {email_cond}').fetchone()[0]

    excluded = conn.execute(
        f'SELECT COUNT(*) FROM companies {where}{"AND" if where else "WHERE"} {bounce_cond}',
        wp
    ).fetchone()[0] if where else conn.execute(f'SELECT COUNT(*) FROM companies WHERE {bounce_cond}').fetchone()[0]

    # Region distribution
    region_dist = [dict(r) for r in conn.execute(
        f"""SELECT region, COUNT(*) AS n FROM companies {where}
            {"AND" if where else "WHERE"} region IS NOT NULL AND region!=''
            GROUP BY region ORDER BY n DESC LIMIT 10""",
        wp
    ).fetchall()] if where else [dict(r) for r in conn.execute(
        "SELECT region, COUNT(*) AS n FROM companies WHERE region IS NOT NULL AND region!='' GROUP BY region ORDER BY n DESC LIMIT 10"
    ).fetchall()]

    conn.close()
    return {
        'total': total,
        'with_email': with_email,
        'mailing_ready': with_email - excluded if with_email > excluded else with_email,
        'excluded_bounce': excluded,
        'region_dist': region_dist,
    }
