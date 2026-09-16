"""Sign-in, sign-out, dark mode and two-factor authentication (TOTP)."""
import os
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, session, flash)
from markupsafe import escape as h
from werkzeug.security import generate_password_hash, check_password_hash
from ..extensions import db
from ..models import *
from ..core.security import (cur_user, login_required, log,
                             setting, pw_policy_error,
                             csrf_token)
from ..core.helpers import cur_year
from ..core.ui import page, CSS, brand_style

bp = Blueprint('auth', __name__)

import hmac as _hmac, hashlib as _hashlib, base64 as _b64, time as _time

@bp.route('/login', methods=['GET','POST'])
def login():
    err = ''
    if request.method == 'POST':
        _uname = request.form.get('username', '').strip()
        # --- brute-force lockout: block after too many recent failures ---
        _max = int(os.environ.get('LOGIN_MAX_FAILS', '5'))
        _lock = int(os.environ.get('LOGIN_LOCK_MIN', '15'))
        _since = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=_lock)
        _fails = 0
        _raw_pw = request.form.get('password', '')
        if _uname:
            _fails = LoginHistory.query.filter(
                db.func.lower(LoginHistory.username) == _uname.lower(), LoginHistory.ok == False,
                LoginHistory.when >= _since).count()
        if _uname and _fails >= _max:
            db.session.add(LoginHistory(username=_uname[:80], ip=request.remote_addr,
                                        ok=False, note='locked out'))
            db.session.commit()
            err = f'Too many failed attempts. Please wait about {_lock} minutes and try again.'
            u = None
        else:
            u = User.query.filter(db.func.lower(User.username) == _uname.lower()).first()
        pw_ok = u and (check_password_hash(u.pw, _raw_pw) or (_raw_pw and check_password_hash(u.pw, _raw_pw.strip())))
        if not err and u and u.active and pw_ok:
            if getattr(u, 'totp_enabled', False) and u.totp_secret:
                session['pre2fa'] = u.id
                return redirect(url_for('auth.login_2fa'))
            session['uid'] = u.id
            db.session.add(Audit(user=u.username, action=f'Login: {u.username} (password)',
                                 action_type='Login',
                                 ip=(request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:64]))
            db.session.add(LoginHistory(username=u.username, ip=request.remote_addr, ok=True, note='password'))
            db.session.commit()
            return redirect(url_for('dash.dashboard'))
        if not err:
            db.session.add(LoginHistory(username=_uname[:80],
                                        ip=request.remote_addr, ok=False, note='bad credentials'))
            db.session.commit()
            err = 'Invalid username or password'
    dark = 'dark' if session.get('dark') else ''
    company = h(setting('company', 'Modern Diagnostic Center'))
    appname = h(setting('appname', 'MDC ERP'))
    year = cur_year()
    fav = f'<link rel="icon" href="{h(setting("favicon","") or "/static/brand/mdc-mark.png")}">'
    _logo = setting('login_logo', '') or setting('logo', '') or '/static/brand/mdc-logo.png'
    mark = f'<img src="{h(_logo)}" alt="logo" class="lg-logo">'
    _bg = setting('login_bg', '')
    brand_bg = (f'background-image:linear-gradient(150deg,rgba(2,48,90,.90),rgba(4,76,140,.80)),url({h(_bg)});'
                f'background-size:cover;background-position:center') if _bg else ''
    err_html = f'<div class="lg-err"><span class="lg-err-i">!</span><span>{h(err)}</span></div>' if err else ''
    note = 'Role-based access &middot; every sign-in is recorded.'
    ECG = ("M0,60 H150 l14,0 l10,-34 l12,66 l13,-78 l11,46 l15,0 "
           "H360 l14,0 l10,-34 l12,66 l13,-78 l11,46 l15,0 "
           "H620 l14,0 l10,-34 l12,66 l13,-78 l11,46 l15,0 "
           "H880 l14,0 l10,-34 l12,66 l13,-78 l11,46 l15,0 "
           "H1140 l14,0 l10,-34 l12,66 l13,-78 l11,46 l15,0 H1400")

    STYLE = """
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0}
.lg-wrap{display:grid;grid-template-columns:1.06fr .94fr;min-height:100vh;min-height:100dvh}

/* ---------- Brand panel ---------- */
.lg-brand{position:relative;overflow:hidden;color:#EAF2F8;padding:46px 48px;
 display:flex;flex-direction:column;justify-content:space-between;
 background:linear-gradient(150deg,#02305A 0%,#044C8C 56%,#0A5E88 100%)}
.lg-brand::after{content:"";position:absolute;inset:0;pointer-events:none;
 background:radial-gradient(115% 75% at 82% -5%,rgba(228,84,36,.22),transparent 60%)}
.lg-brand>*{position:relative;z-index:2}
.lg-top{display:flex;align-items:center;gap:13px}
.lg-m{width:46px;height:46px;border-radius:13px;display:grid;place-items:center;
 background:linear-gradient(135deg,var(--amber),#F2A25B);color:#02305A;
 font-weight:700;font-size:25px;font-family:var(--fd);flex:none}
.lg-logo{height:46px;width:auto;object-fit:contain;background:#fff;border-radius:11px;padding:5px;flex:none}
.lg-org{font-family:var(--fd);font-weight:700;font-size:16px;line-height:1.15;letter-spacing:.2px}
.lg-org small{display:block;font-family:var(--fb);font-weight:500;font-size:11.5px;opacity:.72;letter-spacing:.4px;margin-top:2px}
.lg-hero{max-width:430px}
.lg-hero h2{font-family:var(--fd);font-weight:700;font-size:31px;line-height:1.16;letter-spacing:-.5px;margin:0 0 13px}
.lg-hero p{font-size:14px;line-height:1.65;opacity:.84;margin:0}
.lg-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:24px}
.lg-chip{display:inline-flex;align-items:center;gap:7px;font-size:11.5px;font-weight:600;letter-spacing:.2px;
 padding:7px 12px;border-radius:22px;background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.15)}
.lg-chip i{width:6px;height:6px;border-radius:50%;background:var(--amber);display:block;flex:none}
.lg-legal{font-size:11.5px;opacity:.6;letter-spacing:.2px}
/* ECG monitor signature */
.lg-ecg{position:absolute;left:0;right:0;bottom:128px;height:118px;width:100%;z-index:1;opacity:.9}
.lg-ecg .base{fill:none;stroke:rgba(255,255,255,.24);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.lg-ecg .glow{fill:none;stroke:var(--amber);stroke-width:3;stroke-linecap:round;stroke-linejoin:round;
 filter:drop-shadow(0 0 6px rgba(228,84,36,.85));stroke-dasharray:78 2600;stroke-dashoffset:2678;
 animation:lg-sweep 3.6s cubic-bezier(.55,0,.5,1) infinite}
@keyframes lg-sweep{to{stroke-dashoffset:0}}

/* ---------- Form panel ---------- */
.lg-form{display:flex;align-items:center;justify-content:center;padding:44px 26px;background:var(--surface)}
.lg-card{width:100%;max-width:376px}
.lg-eyebrow{font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--amber-dk)}
.lg-card h1{font-family:var(--fd);font-size:27px;font-weight:700;letter-spacing:-.4px;margin:9px 0 5px;color:var(--ink)}
.lg-sub{color:var(--muted);font-size:13.5px;margin:0 0 24px}
.lg-fld{margin-bottom:16px}
.lg-card label{display:block;font-size:12px;font-weight:600;color:var(--ink);margin:0 0 7px}
.lg-card input{width:100%;font-family:var(--fb);font-size:14px;color:var(--ink);background:var(--surface);
 border:1.5px solid var(--line);border-radius:11px;padding:12px 14px;transition:border-color .15s,box-shadow .15s}
.lg-card input::placeholder{color:var(--muted);opacity:.65}
.lg-card input:focus{outline:none;border-color:var(--petrol);box-shadow:0 0 0 4px rgba(4,76,140,.12)}
.lg-pw{position:relative}
.lg-pw input{padding-right:66px}
.lg-eye{position:absolute;right:5px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;
 color:var(--muted);font-size:12px;font-weight:600;padding:7px 11px;border-radius:8px;font-family:var(--fb)}
.lg-eye:hover{color:var(--petrol);background:var(--canvas)}
.lg-go{width:100%;margin-top:6px;font-family:var(--fb);font-weight:700;font-size:15px;cursor:pointer;
 color:#fff;background:var(--amber);border:none;padding:13px;border-radius:11px;
 box-shadow:0 8px 18px rgba(228,84,36,.28);transition:background .15s,transform .05s,box-shadow .15s}
.lg-go:hover{background:var(--amber-dk);box-shadow:0 10px 22px rgba(228,84,36,.34)}
.lg-go:active{transform:translateY(1px)}
.lg-err{display:flex;align-items:center;gap:9px;margin-bottom:18px;padding:11px 13px;border-radius:10px;
 font-size:13px;font-weight:600;color:var(--red);background:var(--red-soft);border:1px solid rgba(192,57,43,.22)}
.lg-err-i{flex:none;width:19px;height:19px;border-radius:50%;background:var(--red);color:#fff;
 display:grid;place-items:center;font-size:12px;font-weight:700}
.lg-note{margin-top:20px;font-size:11.5px;line-height:1.55;color:var(--muted);text-align:center}
.lg-note b{color:var(--ink);font-weight:700}

/* focus-visible for keyboard users */
.lg-card input:focus-visible,.lg-go:focus-visible,.lg-eye:focus-visible{outline:2px solid var(--petrol);outline-offset:2px}

/* ---------- Responsive ---------- */
@media(max-width:860px){
 .lg-wrap{grid-template-columns:1fr}
 .lg-brand{flex-direction:row;align-items:center;justify-content:space-between;padding:22px 24px}
 .lg-hero,.lg-ecg,.lg-legal{display:none}
 .lg-form{padding:34px 22px}
}
@media(prefers-reduced-motion:reduce){
 .lg-ecg .glow{animation:none;stroke-dashoffset:0;stroke-dasharray:none;opacity:.7}
}
"""

    SCRIPT = ("<script>(function(){var b=document.getElementById('lg-eye'),"
              "i=document.getElementById('lg-pass');if(!b||!i)return;"
              "b.addEventListener('click',function(){var s=i.type==='password';"
              "i.type=s?'text':'password';b.textContent=s?'Hide':'Show';"
              "b.setAttribute('aria-label',s?'Hide password':'Show password');i.focus();});})();</script>")

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in &middot; {appname}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">{fav}{brand_style()}<style>{CSS}{STYLE}</style></head><body class="{dark}">
<div class="lg-wrap">
  <aside class="lg-brand" style="{brand_bg}">
    <div class="lg-top">{mark}<div class="lg-org">{company}<small>{appname}</small></div></div>
    <div class="lg-hero">
      <h2>Clinical operations,<br>unified and secure.</h2>
      <p>Registration, laboratory, radiology, pharmacy, billing and accounting &mdash; one connected platform for {company}.</p>
      <div class="lg-chips"><span class="lg-chip"><i></i>Secure sign-in</span><span class="lg-chip"><i></i>Multi-branch</span><span class="lg-chip"><i></i>Role-based access</span></div>
    </div>
    <svg class="lg-ecg" viewBox="0 0 1400 120" preserveAspectRatio="none" aria-hidden="true"><path class="base" d="{ECG}"></path><path class="glow" d="{ECG}"></path></svg>
    <div class="lg-legal">&copy; {year} {company} &middot; MDC ERP &middot; Developed by Kulmiye</div>
  </aside>
  <main class="lg-form">
    <div class="lg-card">
      <div class="lg-eyebrow">Welcome back</div>
      <h1>Sign in</h1>
      <p class="lg-sub">Enter your credentials to access the workspace.</p>
      {err_html}
      <form method="post" autocomplete="on">
        <div class="lg-fld"><label for="lg-user">Username</label><input id="lg-user" name="username" autofocus autocomplete="username" placeholder="yourname"></div>
        <div class="lg-fld"><label for="lg-pass">Password</label><div class="lg-pw"><input id="lg-pass" name="password" type="password" autocomplete="current-password" placeholder="Your password"><button type="button" id="lg-eye" class="lg-eye" aria-label="Show password">Show</button></div></div>
        <button class="lg-go" type="submit">Sign in</button>
      </form>
      <div class="lg-note">{note}</div>
    </div>
  </main>
</div>{SCRIPT}</body></html>"""

@bp.route('/logout')
def logout():
    if cur_user(): log(f'Logout: {cur_user().username}', action_type='Logout')
    session.pop('uid', None); return redirect(url_for('auth.login'))

@bp.route('/toggle-dark')
def toggle_dark():
    session['dark'] = not session.get('dark'); return redirect(request.referrer or url_for('dash.dashboard'))


import struct as _struct, secrets as _secrets

def totp_code(secret_b32, t=None, step=30):
    try:
        key = _b64.b32decode(secret_b32.upper() + '=' * (-len(secret_b32) % 8))
    except Exception:
        return None
    counter = int((t if t is not None else _time.time()) // step)
    msg = _struct.pack('>Q', counter)
    hs = _hmac.new(key, msg, _hashlib.sha1).digest()
    o = hs[-1] & 0x0F
    code = (_struct.unpack('>I', hs[o:o+4])[0] & 0x7FFFFFFF) % 1000000
    return f'{code:06d}'

def totp_verify(secret_b32, code, window=1):
    code = (code or '').strip().replace(' ', '')
    if not (secret_b32 and code.isdigit() and len(code) == 6): return False
    now = _time.time()
    for w in range(-window, window + 1):
        good = totp_code(secret_b32, now + w * 30)
        if good and _hmac.compare_digest(good, code): return True
    return False

def _login_shell(title, inner):
    dark = 'dark' if session.get('dark') else ''
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{h(title)} · MDC ERP</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap" rel="stylesheet"><style>{CSS}
.auth{{position:fixed;inset:0;background:linear-gradient(135deg,var(--petrol7),var(--petrol) 60%,#155059);display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:var(--surface);border-radius:18px;width:100%;max-width:390px;box-shadow:0 30px 70px rgba(0,0,0,.35);overflow:hidden}}
.card .hd{{padding:30px 30px 8px;text-align:center}}.card .mk{{width:52px;height:52px;border-radius:14px;background:linear-gradient(135deg,var(--amber),#F2C063);display:grid;place-items:center;color:var(--petrol7);font-weight:700;font-size:26px;margin:0 auto 12px;font-family:var(--fd)}}
.card h1{{font-family:var(--fd);font-size:21px}}.card p{{color:var(--muted);font-size:13px;margin-top:3px}}.card .bd{{padding:14px 30px 26px}}
.card label{{font-size:12px;font-weight:600;color:var(--petrol);display:block;margin:0 0 5px}}.card input{{width:100%;border:1px solid var(--line);border-radius:9px;padding:11px 13px;margin-bottom:12px;background:var(--surface);color:var(--ink);font-size:18px;text-align:center;letter-spacing:6px}}
.card button{{width:100%;background:var(--amber);color:var(--petrol7);border:none;padding:12px;border-radius:10px;font-weight:700;font-size:15px}}
.err{{background:var(--red-soft);color:var(--red);padding:10px;border-radius:8px;font-size:13px;font-weight:600;margin-bottom:12px;text-align:center;letter-spacing:0}}</style></head><body class="{dark}">
<div class="auth"><div class="card"><div class="hd"><div class="mk" style="background:#fff;padding:6px"><img src="/static/brand/mdc-mark.png" alt="MDC" style="width:100%;height:100%;object-fit:contain"></div><h1>{h(title)}</h1><p>Modern Diagnostic Center · ERP</p></div>{inner}</div></div></body></html>"""

@bp.route('/login/2fa', methods=['GET', 'POST'])
def login_2fa():
    uid = session.get('pre2fa')
    if not uid: return redirect(url_for('auth.login'))
    u = User.query.get(uid)
    if not u: session.pop('pre2fa', None); return redirect(url_for('auth.login'))
    err = ''
    if request.method == 'POST':
        if totp_verify(u.totp_secret, request.form.get('code')):
            session.pop('pre2fa', None); session['uid'] = u.id
            db.session.add(Audit(user=u.username, action=f'Login: {u.username} (2FA)', action_type='Login',
                                 ip=(request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:64]))
            db.session.add(LoginHistory(username=u.username, ip=request.remote_addr, ok=True, note='2FA')); db.session.commit()
            db.session.add(Audit(user=u.username, action='Signed in (2FA)')); db.session.commit()
            return redirect(url_for('dash.dashboard'))
        err = 'Invalid code — try again'
    inner = f"""<form method="post" class="bd">{f'<div class="err">{h(err)}</div>' if err else ''}
    <p style="text-align:center;margin-bottom:12px;color:var(--muted);font-size:13px">Geli 6-lambar ka muuqda <b>Google Authenticator</b></p>
    <label>Authentication code</label><input name="code" inputmode="numeric" pattern="[0-9]*" maxlength="6" autofocus autocomplete="one-time-code">
    <button>Verify</button></form>
    <div style="text-align:center;padding:0 30px 22px"><a href="{url_for('auth.login')}" style="font-size:12px;color:var(--muted)">← Back to sign in</a></div>"""
    return _login_shell('Two-Factor Code', inner)

@bp.route('/security', methods=['GET', 'POST'])
@login_required
def security():
    u = cur_user()
    msg = ''
    if request.method == 'POST':
        act = request.form.get('act')
        if act == 'enable':
            secret = session.get('tmp_totp')
            if secret and totp_verify(secret, request.form.get('code')):
                u.totp_secret = secret; u.totp_enabled = True; db.session.commit()
                session.pop('tmp_totp', None); log('Enabled 2FA'); flash('Two-Factor Authentication enabled ✓')
                return redirect(url_for('auth.security'))
            msg = "<div style='background:var(--red-soft);color:var(--red);padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:12px'>Code-ku waa khalad — isku day mar kale.</div>"
        elif act == 'disable':
            if totp_verify(u.totp_secret, request.form.get('code')):
                u.totp_enabled = False; u.totp_secret = None; db.session.commit()
                log('Disabled 2FA'); flash('Two-Factor Authentication disabled')
                return redirect(url_for('auth.security'))
            msg = "<div style='background:var(--red-soft);color:var(--red);padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:12px'>Code-ku waa khalad.</div>"
    if u.totp_enabled:
        body = f"""<div class="panel" style="max-width:560px"><div class="ph"><h2>Security · Two-Factor Authentication</h2></div><div class="pad">
        {msg}<p style="margin-bottom:14px"><span class="pill green">Enabled ✓</span> &nbsp; Akoonkaagu wuxuu leeyahay ilaalin dheeri ah — login kasta wuxuu u baahan yahay code ka yimaada telefoonkaaga.</p>
        <form method="post"><input type="hidden" name="act" value="disable">
        <div class="fld"><label>Si aad u damiso, geli code-ka hadda (Authenticator)</label><input name="code" maxlength="6" style="max-width:180px;letter-spacing:5px;text-align:center"></div>
        <button class="btn" style="margin-top:8px">Disable 2FA</button></form></div></div>"""
    else:
        secret = session.get('tmp_totp')
        if not secret:
            secret = _b64.b32encode(_secrets.token_bytes(10)).decode().rstrip('=')
            session['tmp_totp'] = secret
        issuer = setting('appname', 'MDC ERP').replace(' ', '%20')
        uri = f"otpauth://totp/{issuer}:{u.username}?secret={secret}&issuer={issuer}"
        body = f"""<div class="panel" style="max-width:560px"><div class="ph"><h2>Security · Two-Factor Authentication</h2></div><div class="pad">
        {msg}<p style="color:var(--muted);font-size:13.5px;margin-bottom:14px"><span class="pill amber">Disabled</span> &nbsp; Ku dar lakab ammaan dheeri ah: password + code telefoonka.</p>
        <p style="font-weight:600;color:var(--petrol);margin-bottom:8px">1. Ku scan-garee QR-kan <b>Google Authenticator</b> (ama Authy):</p>
        <div id="qr" style="background:#fff;padding:14px;border:1px solid var(--line);border-radius:12px;width:fit-content;margin-bottom:10px"></div>
        <p style="font-size:12.5px;color:var(--muted);margin-bottom:14px">Ama gacanta ku geli furahan: <b style="color:var(--petrol);letter-spacing:2px">{secret}</b></p>
        <p style="font-weight:600;color:var(--petrol);margin-bottom:8px">2. Geli 6-lambarka uu app-ku muujinayo:</p>
        <form method="post"><input type="hidden" name="act" value="enable">
        <div style="display:flex;gap:10px"><input name="code" maxlength="6" placeholder="000000" style="max-width:180px;letter-spacing:5px;text-align:center;border:1px solid var(--line);border-radius:9px;padding:10px"><button class="btn primary">Enable 2FA</button></div></form>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
        <script>new QRCode(document.getElementById('qr'),{{text:"{uri}",width:170,height:170}});</script>
        </div></div>"""
    return page('Security', body, 'settings')



# ==================== Forced password change (first sign-in / admin reset) ====================

@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Self-service password change. Also the landing page when a user still
    carries the default password (must_change_pw)."""
    u = cur_user()
    forced = bool(getattr(u, 'must_change_pw', False))
    err = ''
    ok = ''
    if request.method == 'POST':
        cur = request.form.get('current') or ''
        new = request.form.get('new') or ''
        again = request.form.get('again') or ''
        if not check_password_hash(u.pw, cur):
            err = 'Current password is incorrect'
        elif new != again:
            err = 'New passwords do not match'
        elif check_password_hash(u.pw, new):
            err = 'New password must be different from the current one'
        else:
            err = pw_policy_error(new) or ''
            if not err:
                u.pw = generate_password_hash(new)
                u.must_change_pw = False
                db.session.commit()
                log('Changed own password')
                if forced:
                    return redirect(url_for('dash.dashboard'))
                ok = 'Password updated.'
                forced = False
    banner = ''
    if forced:
        banner = ("<div style='background:var(--amber-soft,#FDF3E0);border-left:4px solid var(--amber);"
                  "padding:12px 14px;border-radius:8px;margin-bottom:14px;font-size:13.5px'>"
                  "<b>Change your password to continue.</b><br>"
                  "This account still uses the default password. For security you must set a new one "
                  "before using the system.</div>")
    msg = ''
    if err:
        msg = f"<div style='background:var(--red-soft);color:var(--red);padding:10px;border-radius:8px;margin-bottom:12px;font-weight:600;font-size:13px'>{h(err)}</div>"
    elif ok:
        msg = f"<div style='background:var(--green-soft,#E7F6EC);color:var(--green);padding:10px;border-radius:8px;margin-bottom:12px;font-weight:600;font-size:13px'>{h(ok)}</div>"
    body = f"""<div class='panel' style='max-width:520px'>
      <div class='ph'><h2>Change Password</h2><span class='so'>{h(u.username)}</span></div>
      <div class='pad'>{banner}{msg}
      <form method='post'><input type='hidden' name='_csrf' value='{csrf_token()}'>
        <div class='fld full'><label>Current Password</label><input name='current' type='password' required autofocus></div>
        <div class='fld full'><label>New Password</label><input name='new' type='password' required>
          <small style='color:var(--muted)'>At least 4 characters and must contain a number.</small></div>
        <div class='fld full'><label>Repeat New Password</label><input name='again' type='password' required></div>
        <div style='text-align:right;margin-top:12px'><button class='btn primary'>Update Password</button></div>
      </form></div></div>"""
    return page('Change Password', body, 'dashboard')
