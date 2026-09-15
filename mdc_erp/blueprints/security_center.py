"""Security Center  (Phase 14, v8.0).

A consolidated security-posture dashboard for administrators, built on the
existing hardened auth (TOTP 2FA, brute-force lockout, password policy, login
history). Surfaces 2FA adoption, default-password accounts, failed logins and
current lockouts, and adds admin recovery actions (require password change,
clear a lockout, reset a lost 2FA). No new tables.
"""
import os
import datetime as dt
from flask import Blueprint, redirect, url_for, flash, abort
from markupsafe import escape as h
from ..extensions import db
from ..models import User, LoginHistory
from ..core.security import can, cur_user, log, setting
from ..core.ui import page

bp = Blueprint('security_center', __name__)

LOGIN_MAX_FAILS = int(os.environ.get('LOGIN_MAX_FAILS', '5'))
LOGIN_LOCK_MIN = int(os.environ.get('LOGIN_LOCK_MIN', '15'))


def _recent_fail_counts(within_min):
    since = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=within_min)
    rows = (db.session.query(LoginHistory.username, db.func.count(LoginHistory.id))
            .filter(LoginHistory.ok == False, LoginHistory.when >= since)  # noqa: E712
            .group_by(LoginHistory.username).all())
    return {u: c for u, c in rows}


def _last_logins():
    rows = (db.session.query(LoginHistory.username, db.func.max(LoginHistory.when))
            .filter(LoginHistory.ok == True)  # noqa: E712
            .group_by(LoginHistory.username).all())
    return {u: w for u, w in rows}


def sec_board():
    """Security Center — App Launcher (mod='security')."""
    users = User.query.order_by(User.username).all()
    active_users = [u for u in users if u.active]
    twofa = [u for u in active_users if getattr(u, 'totp_enabled', False)]
    default_pw = [u for u in active_users if getattr(u, 'must_change_pw', False)]
    inactive = [u for u in users if not u.active]

    locks = _recent_fail_counts(LOGIN_LOCK_MIN)
    locked_now = {un: c for un, c in locks.items() if c >= LOGIN_MAX_FAILS}
    fails_24h = sum(_recent_fail_counts(24 * 60).values())
    last_login = _last_logins()

    twofa_pct = round(100 * len(twofa) / len(active_users)) if active_users else 0

    def kpi(label, val, ac, sub=''):
        return (f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div>"
                f"<div class='v'>{val}</div><div class='s'>{sub}</div></div>")
    kpis = ("<div class='kpis'>"
            + kpi('2FA enabled', f'{len(twofa)}/{len(active_users)}',
                  'var(--green)' if twofa_pct >= 80 else 'var(--amber-dk)', f'{twofa_pct}% of active')
            + kpi('Default password', len(default_pw),
                  'var(--red)' if default_pw else 'var(--green)', 'must change')
            + kpi('Locked out now', len(locked_now),
                  'var(--red)' if locked_now else 'var(--green)', f'≥{LOGIN_MAX_FAILS} fails')
            + kpi('Failed logins 24h', fails_24h, 'var(--amber-dk)', 'attempts')
            + kpi('Inactive accounts', len(inactive), 'var(--petrol)', 'disabled') + "</div>")

    # policy panel (reflects the live configuration)
    policy = (f"<div class='panel'><div class='ph'><h2>Active policy</h2></div><div class='pad' style='font-size:13px'>"
              f"<b>Passwords:</b> min 4 characters · must contain a number · common passwords blocked<br>"
              f"<b>Lockout:</b> {LOGIN_MAX_FAILS} failed attempts locks an account for ~{LOGIN_LOCK_MIN} minutes<br>"
              f"<b>Two-factor:</b> TOTP (authenticator app) available per user<br>"
              f"<b>Session timeout:</b> {h(str(setting('session_timeout_min', '30')))} minutes idle"
              f"</div></div>")

    # recent failed logins
    since7 = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=7)
    fails = (LoginHistory.query.filter(LoginHistory.ok == False, LoginHistory.when >= since7)  # noqa: E712
             .order_by(LoginHistory.id.desc()).limit(30).all())
    frows = ''.join(
        f"<tr><td>{h(str(x.when)[:16])}</td><td>{h(x.username or '—')}</td>"
        f"<td>{h(x.ip or '—')}</td><td>{h(x.note or '')}</td></tr>" for x in fails)
    fails_panel = (f"<div class='panel'><div class='ph'><h2>Failed logins · 7 days</h2></div>"
                   f"<div class='tw'><table><thead><tr><th>When</th><th>Username</th><th>IP</th><th>Note</th></tr></thead>"
                   f"<tbody>{frows or '<tr><td colspan=4 style=color:var(--muted)>None — clean</td></tr>'}</tbody></table></div></div>")

    # users & posture
    may_act = can('users') or (cur_user() and cur_user().role in ('super_admin', 'it_admin'))
    urows = ''
    for u in users:
        badges = ''
        badges += ("<span class='pill green'>2FA</span> " if getattr(u, 'totp_enabled', False)
                   else "<span class='pill grey'>no 2FA</span> ")
        if getattr(u, 'must_change_pw', False):
            badges += "<span class='pill red'>default pw</span> "
        if not u.active:
            badges += "<span class='pill grey'>inactive</span> "
        if u.username in locked_now:
            badges += "<span class='pill red'>LOCKED</span> "
        ll = last_login.get(u.username)
        acts = ''
        if may_act:
            if not getattr(u, 'must_change_pw', False):
                acts += (f"<a class='btn sm' href='{url_for('security_center.require_change', uid=u.id)}' "
                         f"onclick=\"return confirm('Require {h(u.username)} to change password at next login?')\">Require pw change</a> ")
            if u.username in locked_now:
                acts += (f"<a class='btn sm' href='{url_for('security_center.clear_lockout', uid=u.id)}'>Clear lockout</a> ")
            if getattr(u, 'totp_enabled', False):
                acts += (f"<a class='btn sm gh' href='{url_for('security_center.reset_2fa', uid=u.id)}' "
                         f"onclick=\"return confirm('Reset 2FA for {h(u.username)}? They will re-enrol.')\">Reset 2FA</a>")
        urows += (f"<tr><td><b>{h(u.username)}</b><br><span style='font-size:12px;color:var(--muted)'>{h(u.name or '')}</span></td>"
                  f"<td>{h(u.role or '')}</td><td>{badges}</td>"
                  f"<td>{h(str(ll)[:16]) if ll else '—'}</td><td class='num'>{acts}</td></tr>")
    users_panel = (f"<div class='panel'><div class='ph'><h2>Accounts &amp; posture</h2></div>"
                   f"<div class='tw'><table><thead><tr><th>User</th><th>Role</th><th>Security</th>"
                   f"<th>Last login</th><th></th></tr></thead><tbody>{urows}</tbody></table></div></div>")

    body = kpis + policy + fails_panel + users_panel
    log('Viewed security center', action_type='view', entity='Security')
    return page('Security Center', body, 'security')


def _target(uid):
    if not (can('users') or (cur_user() and cur_user().role in ('super_admin', 'it_admin'))):
        abort(403)
    return User.query.get_or_404(uid)


@bp.route('/security/user/<int:uid>/require-change')
def require_change(uid):
    u = _target(uid)
    u.must_change_pw = True
    db.session.commit()
    log(f'Required password change for {u.username}', action_type='security', entity=f'User#{u.id}')
    flash(f'{u.username} must change password at next login', 'ok')
    return redirect(url_for('modules.module', mod='security'))


@bp.route('/security/user/<int:uid>/clear-lockout')
def clear_lockout(uid):
    u = _target(uid)
    since = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=LOGIN_LOCK_MIN)
    n = (LoginHistory.query.filter(LoginHistory.username == u.username,
                                   LoginHistory.ok == False,  # noqa: E712
                                   LoginHistory.when >= since).delete())
    db.session.commit()
    log(f'Cleared lockout for {u.username} ({n} entries)', action_type='security', entity=f'User#{u.id}')
    flash(f'Lockout cleared for {u.username}', 'ok')
    return redirect(url_for('modules.module', mod='security'))


@bp.route('/security/user/<int:uid>/reset-2fa')
def reset_2fa(uid):
    u = _target(uid)
    u.totp_enabled = False
    u.totp_secret = None
    db.session.commit()
    log(f'Reset 2FA for {u.username}', action_type='security', entity=f'User#{u.id}')
    flash(f'2FA reset for {u.username} — they will re-enrol on next login', 'ok')
    return redirect(url_for('modules.module', mod='security'))
