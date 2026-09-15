"""MDC Diagnostic ERP — application factory.

Creates and wires the Flask application:
  * environment-based config (SQLite dev / PostgreSQL prod)
  * SQLAlchemy + Alembic migrations
  * all feature blueprints
  * centralised CSRF protection (auto-injected into every POST form)
  * security headers, logging and friendly error pages
  * CLI commands:  flask init-db   /   flask seed-demo
"""
import logging
import os
import re
from logging.handlers import RotatingFileHandler

import click
from flask import Flask, request, session

from .config import pick_config
from .extensions import db, migrate

_FORM_RE = re.compile(r"(<form\b[^>]*method=['\"]?post['\"]?[^>]*>)", re.I)
CSRF_EXEMPT_PREFIXES = ('/api',)


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or pick_config())

    db.init_app(app)
    migrate.init_app(app, db)

    _register_blueprints(app)
    _register_csrf(app)
    _register_security_headers(app)
    _register_error_pages(app)
    _register_logging(app)
    _register_cli(app)
    _register_health(app)
    _register_pw_gate(app)
    _auto_init_db_if_needed(app)
    try:
        from .core.autobackup import start as _start_autobackup
        _start_autobackup(app)
    except Exception:
        pass
    return app


def _auto_init_db_if_needed(app):
    """Pre-flight cloud check: Auto-initialize schema tables & guarantee administrator user exists."""
    if app.config.get('TESTING'):
        return
    with app.app_context():
        try:
            from .bootstrap import init_db
            init_db(app)
        except Exception as err:
            app.logger.warning("Pre-flight database initialization check handled: %s", err)


def _register_pw_gate(app):
    """Force a password change before anything else when the account still
    carries a default/reset password (must_change_pw)."""
    from flask import request, redirect, url_for

    ALLOWED = {'auth.change_password', 'auth.logout', 'auth.login',
               'auth.login_2fa', 'static', '_healthz', '_readyz'}

    @app.before_request
    def _force_pw_change():
        ep = request.endpoint or ''
        if ep in ALLOWED or ep.startswith('static'):
            return None
        try:
            from .core.security import cur_user
            u = cur_user()
        except Exception:
            return None
        if u and getattr(u, 'must_change_pw', False):
            return redirect(url_for('auth.change_password'))
        return None

    @app.before_request
    def _session_timeout():
        """Sliding inactivity timeout: sign out sessions idle longer than
        PERMANENT_SESSION_LIFETIME. Configurable via SESSION_TIMEOUT_MIN."""
        ep = request.endpoint or ''
        if ep in ALLOWED or ep.startswith('static'):
            return None
        if not session.get('uid'):
            return None
        import time as _t
        from flask import flash as _flash
        now = int(_t.time())
        limit = app.config['PERMANENT_SESSION_LIFETIME'].total_seconds()
        last = session.get('_seen')
        if last and (now - last) > limit:
            session.clear()
            _flash('Your session expired due to inactivity. Please sign in again.')
            return redirect(url_for('auth.login'))
        session['_seen'] = now
        session.permanent = True
        return None


def _register_health(app):
    """Liveness/readiness probes for load balancers, Docker, and Kubernetes."""
    from flask import jsonify

    @app.route('/healthz')
    def _healthz():
        # liveness: process is up and serving
        return jsonify(status='ok'), 200

    @app.route('/readyz')
    def _readyz():
        # readiness: can we reach the database?
        from .extensions import db
        from sqlalchemy import text
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify(status='ready', db='ok'), 200
        except Exception as e:
            return jsonify(status='not-ready', db=str(e)[:120]), 503


# --------------------------------------------------------------- blueprints
def _register_blueprints(app):
    from .blueprints import (auth, modules, dash, patients, lab, radiology,
                             pharmacy, billing, accounting, referrals, reports,
                             portal, api, hr, admin, reception, assets, inventory, finexport,
                             drportal, rradportal, fixedassets, pacs, ris, insurance, lis, queueman, fhir, ed, ipd, ot, dialysis, ambulance, bloodbank, analytics, security_center, branchhub, search, genledger, acctdash, bankrec, record_options, chat, expenses)
    for m in (auth, modules, dash, patients, lab, radiology, pharmacy,
              billing, accounting, referrals, reports, portal, api, hr, admin,
              reception, assets, inventory, finexport, drportal, rradportal, fixedassets,
              pacs, ris, insurance, lis, queueman, fhir, ed, ipd, ot, dialysis, ambulance, bloodbank, analytics, security_center, branchhub, search, genledger, acctdash, bankrec, record_options, chat, expenses):
        app.register_blueprint(m.bp)


# --------------------------------------------------------------------- CSRF
def _register_csrf(app):
    """Centralised CSRF protection.

    * a per-session token is auto-injected into every rendered POST form
    * every non-API POST request must carry a matching token
    No view code needs to change: injection happens in after_request.
    """
    from .core.security import csrf_token

    @app.before_request
    def _ip_guard():
        from flask import request as _rq, abort as _ab
        try:
            from .models import Setting
            _s = Setting.query.get('ip_allow')
            allow = (_s.value or '').strip() if _s else ''
        except Exception:
            return
        if not allow:
            return
        ip = _rq.remote_addr or ''
        if ip in ('127.0.0.1', '::1'):
            return
        for pref in [x.strip() for x in allow.split(',') if x.strip()]:
            if ip.startswith(pref):
                return
        _ab(403)

    @app.before_request
    def _csrf_protect():
        if request.method != 'POST':
            return None
        if request.path.startswith(CSRF_EXEMPT_PREFIXES):
            return None  # REST API uses JWT, not cookies
        sent = request.form.get('_csrf', '')
        good = session.get('_csrf', '')
        if not good or sent != good:
            app.logger.warning('CSRF rejected: %s %s', request.method, request.path)
            return ('<h3 style="font-family:sans-serif">Session expired or invalid form token.</h3>'
                    '<p style="font-family:sans-serif">Go back, refresh the page and try again.</p>', 400)
        return None

    @app.after_request
    def _csrf_inject(resp):
        ctype = resp.headers.get('Content-Type', '')
        if resp.status_code == 200 and ctype.startswith('text/html') and not resp.direct_passthrough:
            html = resp.get_data(as_text=True)
            if '<form' in html:
                token = csrf_token()
                field = f'<input type="hidden" name="_csrf" value="{token}">'
                html = _FORM_RE.sub(lambda m: m.group(1) + field, html)
                resp.set_data(html)
        return resp


# --------------------------------------------------------- security headers
def _register_security_headers(app):
    @app.after_request
    def _headers(resp):
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        resp.headers.setdefault('Referrer-Policy', 'same-origin')
        resp.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "font-src 'self' data: https://fonts.gstatic.com; frame-ancestors 'self'; form-action 'self'"
        )
        # Emit HSTS whenever the secure (production) config is active — this also
        # covers the Postgres-URL auto-production path, not just FLASK_CONFIG=production.
        if app.config.get('SESSION_COOKIE_SECURE') or os.environ.get('FLASK_CONFIG') == 'production':
            resp.headers.setdefault('Strict-Transport-Security',
                                    'max-age=31536000; includeSubDomains')
        return resp


# ---------------------------------------------------------------- err pages
def _register_error_pages(app):
    def _shell(code, title, msg):
        return (f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{code} · MDC ERP</title></head>
<body style="font-family:Inter,system-ui,sans-serif;background:#F5F7F8;display:grid;place-items:center;min-height:100vh;margin:0">
<div style="background:#fff;border:1px solid #E4EAEC;border-radius:14px;padding:34px 40px;text-align:center;max-width:420px">
<div style="font-size:44px;font-weight:700;color:#103D46">{code}</div>
<div style="font-size:16px;font-weight:600;margin-top:6px">{title}</div>
<p style="color:#6B7F85;font-size:13.5px">{msg}</p>
<a href="/" style="display:inline-block;margin-top:8px;background:#E8A33D;color:#0B2E35;font-weight:700;
padding:10px 18px;border-radius:9px;text-decoration:none">← Back to Dashboard</a></div></body></html>""", code)

    @app.errorhandler(404)
    def _404(e):
        return _shell(404, 'Page not found', 'The page you requested does not exist or was moved.')

    @app.errorhandler(403)
    def _403(e):
        return _shell(403, 'Access denied', 'Your role does not permit this action.')

    from .core.posting import PeriodClosedError, UnbalancedJournalError

    @app.errorhandler(PeriodClosedError)
    def _period_closed(e):
        db.session.rollback()
        return _shell(423, 'Fiscal period closed',
                      f'{e} — reopen the period in Accounting → Fiscal Periods, '
                      'or date the document in an open period.')

    @app.errorhandler(UnbalancedJournalError)
    def _unbalanced(e):
        db.session.rollback()
        return _shell(422, 'Transaction rejected — books did not balance',
                      f'{e} Nothing was posted. This protects the ledger; please '
                      'review the amounts and try again. If this keeps happening, '
                      'report it to the administrator (it is recorded in the Error Log).')

    @app.errorhandler(500)
    def _500(e):
        db.session.rollback()
        app.logger.exception('Internal server error')
        # record to the admin-only Error Log (best-effort, never re-raise)
        try:
            import traceback
            from flask import request as _rq, session as _ss
            from .models import ErrorLog, User
            orig = getattr(e, 'original_exception', None) or e
            uname = None
            uid = _ss.get('uid')
            if uid:
                u = User.query.get(uid)
                uname = u.username if u else None
            el = ErrorLog(user=uname or 'anonymous', screen=_rq.path, action=_rq.method,
                          err_type=type(orig).__name__,
                          detail=(str(orig) + '\n\n' + traceback.format_exc())[:4000],
                          ip=_rq.headers.get('X-Forwarded-For', _rq.remote_addr),
                          browser=(_rq.headers.get('User-Agent') or '')[:200])
            db.session.add(el)
            db.session.commit()
            try:
                from .core.notify import notify
                notify(f'⚠ System error ERR-{el.id:04d} ({el.err_type}) on {el.screen}',
                       link='/m/errorlog', role='it_admin')
            except Exception:
                pass
        except Exception:
            db.session.rollback()
        return _shell(500, 'Something went wrong',
                      'The error has been logged and the administrator notified. '
                      'Your data was not saved incompletely — please try again.')


# ------------------------------------------------------------------ logging
def _register_logging(app):
    handler = RotatingFileHandler('mdc_erp.log', maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------- CLI
def _register_cli(app):
    from .bootstrap import init_db

    @app.cli.command('init-db')
    def _init():
        """Create tables, default admin, settings and chart of accounts."""
        init_db(app, demo=False)
        click.echo('Database initialised. The administrator must use the configured INITIAL_ADMIN_PASSWORD.')

    @app.cli.command('seed-demo')
    def _seed():
        """Initialise database and load demo data."""
        init_db(app, demo=True)
        click.echo('Demo data loaded.')

    @app.cli.command('audit-finance')
    def _audit_finance():
        """Report payment, receipt, and duplicate-source inconsistencies."""
        import json
        from .core.reconciliation import summary
        report = summary()
        click.echo(json.dumps(report, indent=2, default=str))
        if not report['ok']:
            raise click.exceptions.Exit(2)
