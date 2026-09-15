"""Administration: users, audit log, settings, permissions matrix, backup."""
import os
import json
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, Response,
                   flash, abort, current_app)
from markupsafe import escape as h
from werkzeug.security import generate_password_hash
from ..extensions import db
from ..models import *
from ..core.security import (cur_user, can, login_required, log,
                             setting, ROLES, ROLE_LABEL, PERMS, pw_policy_error, csrf_token)
from ..core.helpers import money, today
from ..core.ui import page
from ..core.crud import (pill)

bp = Blueprint('admin', __name__)

def users_view():
    us=User.query.order_by(User.id).all(); rows=''
    for u in us:
        rows+=f"""<tr><td><div class='av' style='width:28px;height:28px;font-size:12px;display:inline-grid;vertical-align:middle'>{h((u.name or u.username)[:1].upper())}</div> <b>{h(u.name or u.username)}</b></td>
          <td>{h(u.username)}</td><td><span class='pill {'amber' if u.role=='super_admin' else 'blue'}'>{h(ROLE_LABEL.get(u.role,u.role))}</span></td>
          <td>{'<span class=pill green>Active</span>' if u.active else '<span class=pill red>Disabled</span>'}</td>
          <td class='num'><a class='btn gh sm' href='{url_for('admin.user_edit',uid=u.id)}'>Edit</a>{'' if u.id==cur_user().id else f"<a class='btn gh sm' href='{url_for('admin.user_del',uid=u.id)}' onclick=\"return confirm('Delete user?')\">Delete</a>"}</td></tr>"""
    roles_help="<br>".join(f"<b style='color:var(--ink)'>{ROLE_LABEL[r]}</b>" for r in ROLES)
    return page('Users', f"""<div class="panel"><div class="ph"><h2>Users</h2><div class="sp"></div><a class="btn" href="{url_for('admin.permissions')}">Role Permissions</a><a class="btn primary" href="{url_for('admin.user_new')}">+ Add User</a></div>
      <div class="tw"><table><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
      <div class="panel"><div class="pad"><b style="font-family:var(--fd)">Available roles</b><div style="margin-top:8px;color:var(--muted);line-height:1.9;font-size:13px">{roles_help}</div></div></div>""",'users')

def user_form(u=None):
    role_opts=[(r,ROLE_LABEL[r]) for r in ROLES]
    return f"""<div class="fld"><label>Full Name *</label><input name="name" value="{h(u.name if u else '')}"></div>
      <div class="fld"><label>Username *</label><input name="username" value="{h(u.username if u else '')}" {'readonly' if u else ''}></div>
      <div class="fld"><label>Role *</label><select name="role">{''.join(f"<option value='{v}'{' selected' if u and u.role==v else (' selected' if not u and v=='reception' else '')}>{h(l)}</option>" for v,l in role_opts)}</select></div>
      <div class="fld"><label>Branch</label><select name="branch_id">{''.join(f"<option value='{b.id}'{' selected' if (u and u.branch_id==b.id) or (not u and b.id==(Branch.query.first().id if Branch.query.first() else 0)) else ''}>{h(b.name)}</option>" for b in Branch.query.filter_by(active=True).all())}</select></div>
      <div class="fld"><label>Status</label><select name="active"><option value="1"{' selected' if not u or u.active else ''}>Active</option><option value="0"{' selected' if u and not u.active else ''}>Disabled</option></select></div>
      <div class="fld full"><label>{'New Password (blank = keep)' if u else 'Password *'}</label><input name="password" type="password"></div>"""

@bp.route('/users/new', methods=['GET','POST'])
@login_required
def user_new():
    if not can('users'): abort(403)
    if request.method=='POST':
        un=request.form['username'].strip()
        if User.query.filter_by(username=un).first(): flash('Username exists'); return redirect(url_for('admin.user_new'))
        pw=request.form.get('password') or ''
        _pe=pw_policy_error(pw)
        if _pe: flash(_pe); return redirect(url_for('admin.user_new'))
        _b=request.form.get('branch_id')
        db.session.add(User(username=un,name=request.form['name'],role=request.form['role'],active=request.form['active']=='1',pw=generate_password_hash(pw),branch_id=int(_b) if _b else None))
        db.session.commit(); log(f'Created user {un}'); flash('User added'); return redirect(url_for('modules.module',mod='users'))
    return page('New User', f"<div class='panel'><div class='ph'><h2>New User</h2></div><div class='pad'><form method='post'><div class='fg'>{user_form()}</div><div class='fa'><a class='btn' href='{url_for('modules.module',mod='users')}'>Cancel</a><button class='btn primary'>Save</button></div></form></div></div>",'users')

@bp.route('/users/<int:uid>/edit', methods=['GET','POST'])
@login_required
def user_edit(uid):
    if not can('users'): abort(403)
    u=User.query.get_or_404(uid)
    if request.method=='POST':
        u.name=request.form['name']; u.role=request.form['role']; u.active=request.form['active']=='1'
        _b=request.form.get('branch_id'); u.branch_id=int(_b) if _b else u.branch_id
        pw=request.form.get('password')
        if pw:
            _pe=pw_policy_error(pw)
            if _pe: flash(_pe); return redirect(url_for('admin.user_edit',uid=uid))
            u.pw=generate_password_hash(pw)
        db.session.commit(); log(f'Edited user {u.username}'); flash('User updated'); return redirect(url_for('modules.module',mod='users'))
    return page('Edit User', f"<div class='panel'><div class='ph'><h2>Edit User</h2></div><div class='pad'><form method='post'><div class='fg'>{user_form(u)}</div><div class='fa'><a class='btn' href='{url_for('modules.module',mod='users')}'>Cancel</a><button class='btn primary'>Save</button></div></form></div></div>",'users')

@bp.route('/users/<int:uid>/delete')
@login_required
def user_del(uid):
    if not can('users'): abort(403)
    u=User.query.get_or_404(uid)
    if u.id==cur_user().id: flash("Can't delete yourself"); return redirect(url_for('modules.module',mod='users'))
    if u.role=='super_admin' and User.query.filter_by(role='super_admin',active=True).count()<=1:
        flash('Need at least one super admin'); return redirect(url_for('modules.module',mod='users'))
    db.session.delete(u); db.session.commit(); log(f'Deleted user {u.username}'); flash('Deleted'); return redirect(url_for('modules.module',mod='users'))

def _audit_color(t):
    return {'Create': 'green', 'Edit': 'blue', 'Delete': 'red', 'Cancel': 'red',
            'Reset Draft': 'amber', 'Print': 'grey', 'Login': 'teal', 'Logout': 'grey',
            'Payment': 'green', 'Report Approval': 'teal', 'Blocked': 'red'}.get(t, 'grey')


def audit_view():
    from flask import render_template
    fin = request.args.get('fin') == '1'
    ftype = request.args.get('type') or ''
    q = Audit.query.order_by(Audit.id.desc())
    if fin:
        from sqlalchemy import or_
        q = q.filter(or_(Audit.action_type.in_(['Payment', 'Cancel', 'Reset Draft']),
                         Audit.action.like('%efund%'), Audit.action.like('%iscount%'),
                         Audit.action.like('%voucher%'), Audit.action.like('%settlement%')))
    if ftype:
        q = q.filter(Audit.action_type == ftype)
    logs = q.limit(400).all()
    rows = []
    for a in logs:
        when = (f"{a.ts.strftime('%Y-%m-%d')}<div style='color:var(--muted);font-size:11px'>{a.ts.strftime('%H:%M:%S')}</div>"
                if a.ts else '—')
        typ = f"<span class='pill {_audit_color(a.action_type)}'>{h(a.action_type or 'Other')}</span>"
        act = h(a.action) + (f"<div style='color:var(--muted);font-size:11px'>{h(a.entity)}</div>" if a.entity else '')
        change = (f"<span style='color:var(--muted)'>{h(a.old_value or '—')}</span> → <b>{h(a.new_value or '—')}</b>"
                  if (a.old_value or a.new_value) else '<span style="color:var(--muted)">—</span>')
        rows.append([when, h(a.user or '—'), typ, act, change,
                     f"<span style='font-family:monospace;font-size:11px'>{h(a.ip or '—')}</span>", h(a.reason or '—')])
    types = ['Create', 'Edit', 'Delete', 'Reset Draft', 'Cancel', 'Print', 'Login', 'Logout', 'Payment', 'Report Approval']
    tabs = (f"<a class='btn sm {'primary' if not fin and not ftype else ''}' href='?'>All Activity</a> "
            f"<a class='btn sm {'primary' if fin else ''}' href='?fin=1'>💰 Financial</a> &nbsp;"
            + ' '.join(f"<a class='btn gh sm {'primary' if ftype == t else ''}' href='?type={t}'>{t}</a>" for t in types))
    body = render_template('list_page.html', title='Audit Log', subtitle=f'{len(logs)} events',
                           filterbar=f"<div class='pad' style='display:flex;flex-wrap:wrap;gap:6px'>{tabs}</div>",
                           headers=['When', 'User', 'Type', 'Action', 'Old → New', 'IP', 'Reason'],
                           aligns=['', '', '', '', '', '', ''], rows=rows,
                           empty="<div class='empty'><b>No activity yet</b>Actions will appear here as staff use the system.</div>")
    return page('Audit Log', body, 'audit')

def settings_view():
    if request.method=='POST': pass
    devinfo = ('' if setting('dev_mode')!='1' else f"<hr style='margin:12px 0;border:none;border-top:1px solid var(--line)'><p style='font-size:12px;color:var(--muted);line-height:1.9'><b>DEV INFO</b><br>Patients: {Patient.query.count()} · Invoices: {Invoice.query.count()} · Referrals: {Referral.query.count()} · Accounts: {Account.query.count()} · Users: {User.query.count()}<br>DB: erp.db (SQLite)</p>")
    return page('Settings', f"""<div class="grid2">
      <div class="panel"><div class="ph"><h2>Company & Finance</h2></div><div class="pad"><form method="post" action="{url_for('admin.settings_save')}"><div class="fg">
        <input type="hidden" name="_form" value="company">
        <div class="fld full"><label>Company Name</label><input name="company" value="{h(setting('company','Modern Diagnostic Center'))}"></div>
        <div class="fld"><label>System Name (short)</label><input name="appname" value="{h(setting('appname','MDC ERP'))}"></div>
        <div class="fld"><label>Currency Symbol</label><input name="currency" value="{h(setting('currency','$'))}"></div>
        <div class="fld"><label>Opening Capital</label><input name="capital" type="number" step="any" value="{h(setting('capital','0'))}"></div>
        <div class="fld"><label>VAT %</label><input name="vat" type="number" step="any" value="{h(setting('vat','0'))}"></div>
        <div class="fld"><label>Contrast Cost ($, deducted before doctor commission)</label><input name="contrast_cost" type="number" step="any" value="{h(setting('contrast_cost','40'))}"></div>
        <div class="fld"><label>Radiologist Fee ($/scan report)</label><input name="rad_fee" type="number" step="any" value="{h(setting('rad_fee','10'))}"></div>
        <div class="fld full"><button class="btn primary">Save Settings</button></div>
      </div></form></div></div>
      <div class="panel"><div class="ph"><h2>Branding &amp; Printing</h2></div><div class="pad"><form method="post" action="{url_for('admin.settings_save')}"><div class="fg">
        <input type="hidden" name="_form" value="branding">
        <div class="fld full"><label>Logo URL (image link)</label><input name="logo" value="{h(setting('logo',''))}" placeholder="https://…/logo.png"></div>
        <div class="fld"><label>Brand Color</label><input name="brand" type="color" value="{h(setting('brand','') or '#103D46')}" style="height:40px;padding:2px;width:100%"></div>
        <div class="fld"><label>Paper Size</label><select name="paper"><option {'selected' if setting('paper','A4')=='A4' else ''}>A4</option><option {'selected' if setting('paper','A4')=='A5' else ''}>A5</option></select></div>
        <div class="fld full"><label>Print Header (address · phone · email)</label><input name="print_header" value="{h(setting('print_header',''))}"></div>
        <div class="fld full"><label>Print Footer</label><input name="print_footer" value="{h(setting('print_footer',''))}"></div>
        <div class="fld"><label>Login Logo URL</label><input name="login_logo" value="{h(setting('login_logo',''))}"></div>
        <div class="fld"><label>Login Background URL</label><input name="login_bg" value="{h(setting('login_bg',''))}"></div>
        <div class="fld"><label>Favicon URL</label><input name="favicon" value="{h(setting('favicon',''))}"></div>
        <div class="fld"><label>Watermark Text (blank = company name)</label><input name="wm_text" value="{h(setting('wm_text',''))}"></div>
        <div class="fld full" style="display:flex;gap:18px;flex-wrap:wrap">
          <label style="font-weight:400;display:flex;gap:6px;align-items:center"><input type="checkbox" name="ph_on" value="1" {'checked' if setting('ph_on','1')=='1' else ''} style="width:auto"> Print Header</label>
          <label style="font-weight:400;display:flex;gap:6px;align-items:center"><input type="checkbox" name="pf_on" value="1" {'checked' if setting('pf_on','1')=='1' else ''} style="width:auto"> Print Footer</label>
          <label style="font-weight:400;display:flex;gap:6px;align-items:center"><input type="checkbox" name="wm_on" value="1" {'checked' if setting('wm_on','1')=='1' else ''} style="width:auto"> Watermark</label>
        </div>
        <div class="fld full"><button class="btn primary">Save Branding</button></div>
      </div></form>
      <p style="font-size:11.5px;color:var(--muted);margin-top:8px">Logo &amp; header/footer waxay ka muuqan doonaan dhammaan waraaqaha la daabaco. Watermark-ku waa magaca shirkadda.</p>
      </div></div>
      <div class="panel"><div class="ph"><h2>System / Developer</h2></div><div class="pad"><form method="post" action="{url_for('admin.settings_save')}"><div class="fg">
        <input type="hidden" name="_form" value="dev">
        <div class="fld full"><label style="font-weight:400;display:flex;align-items:center;gap:8px"><input type="checkbox" name="dev_mode" value="1" {'checked' if setting('dev_mode')=='1' else ''} style="width:auto"> Developer Mode (show technical info &amp; DEV badge)</label></div>
        <div class="fld full"><button class="btn primary">Save</button></div>
      </div></form><div style="margin-top:10px"><a class="btn sm" href="{url_for('auth.security')}">🔐 Two-Factor Authentication (2FA) →</a></div>{devinfo}</div></div>
      <div class="panel"><div class="ph"><h2>Backup & Data</h2></div><div class="pad">
        <p style="color:var(--muted);margin-bottom:12px">Download a full backup of the database, or restore from one.</p>
        <a class="btn" href="{url_for('admin.backup')}">↓ Download Backup (JSON)</a>
        <a class="btn" href="{url_for('admin.backup_now')}">💾 Run Auto-Backup Now</a>
        {_autobackup_list_html()}
        <form method="post" action="{url_for('admin.restore')}" enctype="multipart/form-data" style="margin-top:12px">
          <input type="file" name="file" accept=".json" required style="margin-bottom:10px"><br><button class="btn">↑ Restore Backup</button></form>
        <hr style="margin:14px 0;border:none;border-top:1px solid var(--line)">
        <p style="font-size:12px;color:var(--muted)">Signed in as <b>{h(cur_user().username)}</b> ({h(ROLE_LABEL.get(cur_user().role))}) · Database: erp.db (SQLite)</p>
      </div></div></div>""",'settings')

@bp.route('/settings/save', methods=['POST'])
@login_required
def settings_save():
    if not can('settings'): abort(403)
    form=request.form.get('_form','')
    keys={'company':['company','appname','currency','capital','vat','contrast_cost','rad_fee'],'branding':['logo','brand','paper','print_header','print_footer','login_logo','login_bg','favicon','wm_text']}.get(form, ['company','currency','capital','vat'])
    if form=='branding':
        for _ck in ('ph_on','pf_on','wm_on'):
            s=Setting.query.get(_ck) or Setting(key=_ck); s.value='1' if request.form.get(_ck) else '0'; db.session.add(s)
    for k in keys:
        if k in request.form:
            s=Setting.query.get(k) or Setting(key=k); s.value=request.form.get(k,''); db.session.add(s)
    if form=='dev':
        s=Setting.query.get('dev_mode') or Setting(key='dev_mode'); s.value='1' if request.form.get('dev_mode') else '0'; db.session.add(s)
    db.session.commit()
    from ..core.security import clear_setting_cache
    clear_setting_cache()
    log('Updated settings'); flash('Settings saved'); return redirect(url_for('modules.module',mod='settings'))


# ============================================================ BACKUP
def _all_models_in_fk_order():
    """Every mapped model, ordered so parents come before children.

    Driven by SQLAlchemy's table metadata rather than a hand-written list, so a
    model added later is backed up automatically — the previous hard-coded list
    covered only 18 of 69 tables and silently omitted the whole ledger."""
    by_table = {}
    for mapper in db.Model.registry.mappers:
        cls = mapper.class_
        try:
            by_table[cls.__table__.name] = cls
        except Exception:
            continue
    ordered = []
    for t in db.metadata.sorted_tables:          # FK dependency order
        m = by_table.pop(t.name, None)
        if m is not None:
            ordered.append((t.name, m))
    ordered.extend(sorted(by_table.items()))     # anything not in metadata
    return ordered


def dump_db():
    """Full logical backup: every table, every row."""
    out = {}
    for name, model in _all_models_in_fk_order():
        rows = []
        for o in model.query.all():
            d = {c.name: getattr(o, c.name) for c in model.__table__.columns}
            for k, v in d.items():
                if isinstance(v, (dt.datetime, dt.date)):
                    d[k] = v.isoformat()
            rows.append(d)
        out[name] = rows
    return out


def load_db(data):
    """Restore every table from a logical backup produced by dump_db().
    Clears existing rows then re-inserts (preserving ids). Returns (tables, rows)."""
    from sqlalchemy import text as _text
    order = _all_models_in_fk_order()          # parents first
    try:
        db.session.execute(_text('PRAGMA foreign_keys=OFF'))
    except Exception:
        pass
    # clear children first
    for name, model in reversed(order):
        try:
            db.session.execute(model.__table__.delete())
        except Exception:
            pass
    # insert parents first
    from sqlalchemy import DateTime as _DT, Date as _D
    import datetime as _dt2
    n_tables = n_rows = 0
    for name, model in order:
        rows = data.get(name) or []
        if not rows:
            continue
        coltypes = {c.name: c.type for c in model.__table__.columns}
        clean = []
        for r in rows:
            rr = {}
            for k, v in r.items():
                if k not in coltypes:
                    continue
                t = coltypes[k]
                if isinstance(v, str) and v:
                    if isinstance(t, _DT):
                        try:
                            v = _dt2.datetime.fromisoformat(v)
                        except Exception:
                            pass
                    elif isinstance(t, _D):
                        try:
                            v = _dt2.date.fromisoformat(v[:10])
                        except Exception:
                            pass
                rr[k] = v
            clean.append(rr)
        if clean:
            db.session.execute(model.__table__.insert(), clean)
            n_tables += 1
            n_rows += len(clean)
    db.session.commit()
    # After a restore, re-apply the current version's structural seed so that
    # anything a newer update added (per-provider wallet accounts, and the branch
    # / warehouse / stock levels inventory needs) is not lost when an older backup
    # is loaded. Only missing rows are added; existing data is untouched.
    try:
        from ..bootstrap import ensure_seed
        ensure_seed()
    except Exception:
        db.session.rollback()
    return (n_tables, n_rows)
@bp.route('/backup')
@login_required
def backup():
    if not can('settings'): abort(403)
    data=json.dumps(dump_db(),indent=2,default=str)
    log('Downloaded backup')
    return Response(data,mimetype='application/json',headers={'Content-Disposition':f'attachment;filename=mdc-erp-backup-{today()}.json'})


def _autobackup_list_html():
    from flask import current_app
    try:
        from ..core.autobackup import list_backups
        items = list_backups(current_app)
    except Exception:
        items = []
    if not items:
        return ("<div style='margin-top:14px;color:var(--muted);font-size:13px'>"
                "Automatic on-disk backups run daily once the app is deployed. None yet.</div>")
    rows = ''.join(
        f"<tr><td>{h(b['name'])}</td><td>{b['mtime']}</td>"
        f"<td class='num'>{b['size']//1024} KB</td></tr>" for b in items[:14])
    return (f"<div style='margin-top:16px'><b style='font-size:13px'>Recent automatic backups</b>"
            f"<div style='color:var(--muted);font-size:12px;margin:2px 0 6px'>Runs daily while the app is on. "
            f"Each run also saves a raw <b>db-snapshot-*.db</b> in the <b>instance/backups</b> folder — "
            f"restore it by running <b>RESTORE-BACKUP.bat</b>. Manual backup: <b>BACKUP-NOW.bat</b>.</div>"
            f"<div class='tw' style='margin-top:6px'><table><thead><tr><th>File</th><th>When</th>"
            f"<th class='num'>Size</th></tr></thead><tbody>{rows}</tbody></table></div></div>")


@bp.route('/backup/now')
@login_required
def backup_now():
    if not can('settings'): abort(403)
    from flask import current_app
    from ..core.autobackup import write_backup
    path = write_backup(current_app, reason='manual')
    log('Ran auto-backup manually')
    flash('Backup saved to server: ' + (path.split('/')[-1] if path else 'failed'))
    return redirect(url_for('modules.module', mod='settings'))
@bp.route('/restore', methods=['POST'])
@login_required
def restore():
    if not can('settings'): abort(403)
    # only the top administrator may overwrite the whole database
    if not cur_user() or cur_user().role != 'super_admin':
        flash('Only a super administrator can restore a backup.')
        return redirect(url_for('modules.module', mod='settings'))
    f = request.files.get('file')
    if not f:
        flash('No file selected'); return redirect(url_for('modules.module', mod='settings'))
    try:
        data = json.load(f)
    except Exception:
        flash('Invalid backup file (not valid JSON)')
        return redirect(url_for('modules.module', mod='settings'))
    # backups written by auto-backup wrap the tables under a "data" key
    if isinstance(data, dict) and 'data' in data and isinstance(data['data'], dict):
        data = data['data']
    # Use exactly the same table map dump_db writes with. (These two drifted
    # apart once: dump_db was generalised to real table names while restore
    # still looked for the old section names, so a restore found no rows and
    # emptied the database. They must stay derived from one source.)
    section_model = _all_models_in_fk_order()
    # safety snapshot before we touch anything
    try:
        from ..core.autobackup import write_backup
        write_backup(current_app, reason='pre-restore')
    except Exception:
        pass
    # refuse a backup that matches none of our tables rather than wiping data
    if not any((data.get(name) for name, _m in section_model)):
        flash('That file does not look like an MDC ERP backup — nothing was changed.')
        return redirect(url_for('modules.module', mod='settings'))
    inserted = {}
    try:
        # delete children before parents (reverse of load order)
        for _name, model in reversed(section_model):
            model.query.delete()
        db.session.flush()
        # reload parents before children
        import datetime as _dt
        for name, model in section_model:
            rows = data.get(name) or []
            coltypes = {c.name: str(c.type) for c in model.__table__.columns}
            cols = set(coltypes)
            n = 0
            for row in rows:
                clean = {}
                for k, v in row.items():
                    if k not in cols:
                        continue
                    # dump_db serialised datetimes to ISO strings — turn them back
                    if isinstance(v, str) and 'DATETIME' in coltypes[k].upper():
                        try:
                            v = _dt.datetime.fromisoformat(v)
                        except ValueError:
                            v = None
                    clean[k] = v
                db.session.add(model(**clean))
                n += 1
            inserted[name] = n
        db.session.commit()
        log(f'Database restored from backup ({sum(inserted.values())} rows)')
        flash('Restore complete — ' + ', '.join(f'{k}:{v}' for k, v in inserted.items() if v))
    except Exception as e:
        db.session.rollback()
        log(f'Restore FAILED and rolled back: {e}')
        flash(f'Restore failed and was rolled back — no data changed. ({type(e).__name__})')
    return redirect(url_for('modules.module', mod='settings'))


# --------------------------------------------------- configurable RBAC matrix
@bp.route('/permissions', methods=['GET', 'POST'])
@login_required
def permissions():
    if not cur_user() or cur_user().role != 'super_admin':
        abort(403)
    from ..core.security import perms_for
    mods = sorted(PERMS.keys())
    editable_roles = [r for r in ROLES if r != 'super_admin']
    if request.method == 'POST':
        data = {}
        for m in mods:
            data[m] = [r for r in editable_roles if request.form.get(f'{m}::{r}')]
        st = Setting.query.get('perms_json') or Setting(key='perms_json')
        st.value = json.dumps(data)
        db.session.add(st)
        db.session.commit()
        log('Updated role permissions matrix')
        flash('Permissions saved')
        return redirect(url_for('admin.permissions'))
    head = '<th>Module</th>' + ''.join(f'<th style="text-align:center">{h(ROLE_LABEL[r])}</th>' for r in editable_roles)
    rows = ''
    for m in mods:
        cur = perms_for(m)
        cells = ''.join(
            f"<td style='text-align:center'><input type='checkbox' name='{m}::{r}' value='1'{' checked' if r in cur else ''}></td>"
            for r in editable_roles)
        rows += f"<tr><td><b>{h(m)}</b></td>{cells}</tr>"
    body = f"""<div class="panel"><div class="ph"><h2>Role Permissions</h2>
      <span class="so">Super Admin always has full access · changes apply immediately</span></div>
      <form method="post"><div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>
      <div class="pad"><div class="fa"><a class="btn" href="{url_for('modules.module', mod='users')}">Cancel</a>
      <button class="btn primary">Save Permissions</button></div></div></form></div>"""
    return page('Role Permissions', body, 'users')


def loginhist_view():
    """Security → Login History (success + failed attempts with IPs)."""
    rows = LoginHistory.query.order_by(LoginHistory.id.desc()).limit(200).all()
    body = ''.join(
        f"<tr><td>{r.when.strftime('%d-%b-%y %H:%M') if r.when else '—'}</td>"
        f"<td><b>{h(r.username or '—')}</b></td><td style='font-family:monospace'>{h(r.ip or '—')}</td>"
        f"<td>{'<span class=\"pill green\">OK</span>' if r.ok else '<span class=\"pill red\">FAILED</span>'}</td>"
        f"<td style='color:var(--muted)'>{h(r.note or '')}</td></tr>" for r in rows) or \
        "<tr><td colspan='5' style='color:var(--muted);padding:14px'>No logins recorded yet.</td></tr>"
    ip_allow = setting('ip_allow', '')
    sec = f"""<div class="panel"><div class="ph"><h2>IP Restriction</h2></div><div class="pad">
      <form method="post" action="/security/ipallow"><div class="fg">
        <div class="fld full"><label>Allowed IP prefixes (comma-separated, empty = allow all). 127.0.0.1 is always allowed.</label>
        <input name="ip_allow" value="{h(ip_allow)}" placeholder="192.168.1., 10.0.0."></div>
        <div class="fld full"><button class="btn primary">Save</button></div></div></form>
      <p style="color:var(--muted);font-size:12px">Tusaale: <b>192.168.1.</b> wuxuu oggolaanayaa dhammaan 192.168.1.x — shabakadda xafiiska oo keliya.</p>
    </div></div>"""
    return page('Login History', sec + f"""<div class="panel"><div class="ph"><h2>Login History (last 200)</h2></div>
      <div class="tw"><table><thead><tr><th>When (UTC)</th><th>User</th><th>IP</th><th>Result</th><th>Note</th></tr></thead>
      <tbody>{body}</tbody></table></div></div>""", 'loginhistory')


@bp.route('/security/ipallow', methods=['POST'])
@login_required
def ipallow_save():
    if not can('loginhistory'): abort(403)
    v = (request.form.get('ip_allow') or '').strip()
    s = Setting.query.get('ip_allow')
    if s: s.value = v
    else: db.session.add(Setting(key='ip_allow', value=v))
    db.session.commit(); log(f'IP allowlist set to: {v or "(open)"}')
    flash('IP restriction saved'); return redirect(url_for('modules.module', mod='loginhistory'))


def backup_view():
    """Admin → Backup Manager."""
    import os
    from ..config import DATA_DIR
    dbp = os.path.join(DATA_DIR, 'erp.db')
    sqlite = 'sqlite' in (str(db.engine.url) if db.engine else '')
    if sqlite and not os.path.exists(dbp):
        # dev default location
        dbp = 'erp.db'
    size = f"{os.path.getsize(dbp)/1024:.0f} KB" if sqlite and os.path.exists(dbp) else '—'
    inner = (f"""<p>Database: <b>SQLite</b> · size {size}</p>
      <p style='margin:10px 0'><a class='btn primary' href='/backup/download'>⬇ Download Backup Now</a></p>
      <p style='color:var(--muted);font-size:13px'>Talo: maalin kasta backup soo deji oo meel ammaan ah (USB / cloud) ku kaydi.
      Faylka la soo dejiyo waa nuqul buuxa — dib-u-celin: server-ka jooji, faylka ku beddel <b>erp.db</b>, dib u kici.</p>"""
             if sqlite else
             """<p>Database: <b>PostgreSQL</b> (production).</p>
      <p style='color:var(--muted);font-size:13px'>Backup: <code>docker compose exec db pg_dump -U mdc mdc > backup_$(date +%F).sql</code><br>
      Restore: <code>docker compose exec -T db psql -U mdc mdc &lt; backup_YYYY-MM-DD.sql</code></p>""")
    _danger = ''
    if cur_user() and cur_user().role == 'super_admin':
        import os as _os
        bdir = current_app.config.get('BACKUP_DIR') or _os.path.join(current_app.instance_path, 'backups')
        _jsons = []
        try:
            _jsons = sorted((f for f in _os.listdir(bdir) if f.startswith('auto-backup-') and f.endswith('.json')), reverse=True)
        except Exception:
            _jsons = []
        _opts = ''.join(f"<option value='{h(f)}'>{h(f)}</option>" for f in _jsons[:30]) or "<option value=''>(no saved backups yet)</option>"
        _restore = f"""
        <div class='panel' style='border-left:4px solid var(--petrol);margin-top:16px'>
          <div class='ph'><h2 style='color:var(--petrol)'>↩ Restore from Backup</h2></div>
          <div class='pad'>
            <p>Replace the current data with a saved backup. Choose one of the automatic backups below, <b>or</b> upload a backup file you downloaded earlier.</p>
            <p style='color:var(--muted);font-size:13px'>A full backup of the current data is saved automatically first. After restoring, sign in again if asked. (For a raw database file, stop the server and use <b>RESTORE-BACKUP.bat</b> instead.)</p>
            <form method='post' action='/backup/restore' enctype='multipart/form-data' onsubmit="return confirm('Restore will REPLACE all current data with the chosen backup. A backup of the current data is made first. Continue?')" style='margin-top:8px'>
              <div class='fg'>
                <div class='fld'><label>Choose a saved backup</label><select name='name'>{_opts}</select></div>
                <div class='fld'><label>…or upload a backup file (.json)</label><input type='file' name='file' accept='.json,application/json'></div>
                <div class='fld'><label>Type RESTORE to confirm</label><input name='confirm' placeholder='RESTORE' autocomplete='off' required></div>
                <div class='fld full'><button class='btn primary'>↩ Restore This Backup</button></div>
              </div>
            </form>
          </div></div>"""
        _danger = _restore + """
        <div class='panel' style='border-left:4px solid var(--red);margin-top:16px'>
          <div class='ph'><h2 style='color:var(--red)'>⚠ Danger Zone — Clean Test Data</h2></div>
          <div class='pad'>
            <p>Remove <b>ALL testing activity</b> — invoices, referrals, payments, lab &amp; radiology orders, ledger entries, stock movements, assets, and every other transaction — so you can start real work with a clean system.</p>
            <p style='color:var(--muted);font-size:13px'>Keeps your setup: <b>users, settings, chart of accounts, service catalog, doctors, branches</b>. A full backup is saved automatically first. This cannot be undone (except by restoring the backup).</p>
            <form method='post' action='/backup/reset-zero' onsubmit="return confirm('This clears ALL test data — invoices, referrals and every activity. A backup is made first. Continue?')" style='margin-top:8px'>
              <div class='fg'>
                <div class='fld'><label>Type RESET to confirm</label><input name='confirm' placeholder='RESET' autocomplete='off' required></div>
                <div class='fld full'><button class='btn' style='background:var(--red);color:#fff'>🗑 Clean Test Data — Reset to Zero</button></div>
              </div>
            </form>
          </div></div>"""
    return page('Backup', f"<div class='panel'><div class='ph'><h2>Backup Manager</h2></div><div class='pad'>{inner}{_autobackup_list_html()}</div></div>{_danger}", 'backup')


@bp.route('/backup/restore', methods=['POST'])
@login_required
def backup_restore():
    """Restore the whole database from a JSON backup — either an uploaded file or one
    of the on-disk auto-backups. Backs up the current data first. super_admin only."""
    u = cur_user()
    if not u or u.role != 'super_admin':
        abort(403)
    if (request.form.get('confirm') or '').strip().upper() != 'RESTORE':
        flash('Type RESTORE to confirm — nothing was changed.')
        return redirect(request.referrer or url_for('modules.module', mod='backup'))
    # read the chosen backup: uploaded file wins, else a named on-disk backup
    raw = None
    up = request.files.get('file')
    if up and up.filename:
        try:
            raw = up.read().decode('utf-8')
        except Exception:
            flash('Could not read the uploaded file.')
            return redirect(request.referrer or url_for('modules.module', mod='backup'))
    else:
        name = (request.form.get('name') or '').strip()
        if name:
            bdir = current_app.config.get('BACKUP_DIR') or os.path.join(current_app.instance_path, 'backups')
            safe = os.path.basename(name)   # prevent path traversal
            p = os.path.join(bdir, safe)
            if os.path.isfile(p):
                with open(p, 'r', encoding='utf-8') as fh:
                    raw = fh.read()
    if not raw:
        flash('No backup selected — choose a saved backup or upload a .json file.')
        return redirect(request.referrer or url_for('modules.module', mod='backup'))
    # parse; accept either {created,reason,data:{...}} or a bare {table:[...]} dump
    try:
        obj = json.loads(raw)
    except Exception:
        flash('That file is not a valid backup (JSON expected).')
        return redirect(request.referrer or url_for('modules.module', mod='backup'))
    data = obj.get('data') if isinstance(obj, dict) and 'data' in obj else obj
    if not isinstance(data, dict):
        flash('That backup has no data to restore.')
        return redirect(request.referrer or url_for('modules.module', mod='backup'))
    # safety: back up the current state before overwriting it
    try:
        from ..core.autobackup import write_backup
        write_backup(current_app, reason='pre-restore')
    except Exception:
        pass
    try:
        n_tables, n_rows = load_db(data)
    except Exception as e:
        db.session.rollback()
        flash(f'Restore failed: {str(e)[:160]}. Your data was not changed (a pre-restore backup was saved).')
        return redirect(request.referrer or url_for('modules.module', mod='backup'))
    log(f'DATABASE RESTORED from backup ({n_tables} tables, {n_rows} rows)',
        action_type='Restore', entity='SYSTEM', new='Restored from backup')
    flash(f'✓ Restore complete — {n_rows} records across {n_tables} tables. Please sign in again if needed.')
    return redirect('/dashboard')


@bp.route('/backup/reset-zero', methods=['POST'])
@login_required
def backup_reset_zero():
    """Clean ALL test data (invoices, referrals, payments, orders, ledger, stock,
    assets, every activity) from inside the app. Keeps setup: users, settings,
    chart of accounts, service catalog, doctors, branches. Backs up first."""
    u = cur_user()
    if not u or u.role != 'super_admin':
        abort(403)
    if (request.form.get('confirm') or '').strip().upper() != 'RESET':
        flash('Type RESET to confirm — nothing was changed.')
        return redirect(request.referrer or url_for('modules.module', mod='backup'))
    # 1) always back up first
    try:
        from flask import current_app
        from ..core.autobackup import write_backup
        write_backup(current_app, reason='pre-reset')
    except Exception:
        pass
    # 2) clear every transactional table (keep config/catalog)
    from sqlalchemy import text
    KEEP = {
        'user', 'setting', 'currency', 'account', 'cost_center', 'fiscal_period',
        'service', 'doctor', 'radiologist', 'branch', 'warehouse', 'supplier',
        'asset_category', 'insurer', 'coverage_rule', 'svc_contract',
        'lab_param', 'lab_instrument', 'img_modality',
        'ambulance', 'ambulance_driver', 'dialysis_machine', 'dialysis_lab',
        'theatre', 'ward', 'bed',
    }
    try:
        db.session.execute(text('PRAGMA foreign_keys=OFF'))
    except Exception:
        pass
    all_tables = [t.name for t in db.metadata.sorted_tables]
    cleared = 0
    for name in reversed(all_tables):
        if name in KEEP:
            continue
        try:
            db.session.execute(text(f'DELETE FROM "{name}"'))
            cleared += 1
        except Exception:
            pass
    for stmt in ('UPDATE account SET opening=0', "UPDATE bed SET status='Available'"):
        try:
            db.session.execute(text(stmt))
        except Exception:
            pass
    db.session.commit()
    log(f'SYSTEM CLEANED — test data reset to zero ({cleared} tables cleared)',
        action_type='Reset', entity='SYSTEM', new='All activity cleared')
    flash('✓ Test data cleared — invoices, referrals and all activity removed. The system now reads 0. A backup was saved first.')
    return redirect(url_for('dash.dashboard') if False else '/dashboard')


@bp.route('/backup/download')
@login_required
def backup_download():
    if not can('backup'): abort(403)
    import os
    import datetime as _dt
    from flask import send_file
    from ..config import DATA_DIR
    dbp = os.path.join(DATA_DIR, 'erp.db')
    if not os.path.exists(dbp): dbp = os.path.abspath('erp.db')
    if not os.path.exists(dbp): abort(404)
    log('Backup downloaded')
    return send_file(dbp, as_attachment=True,
                     download_name=f'mdc-erp-backup-{_dt.date.today().isoformat()}.db')


def messages_view():
    """Admin → Messages: gateway settings + outbox."""
    from ..models import OutMsg
    rows = OutMsg.query.order_by(OutMsg.id.desc()).limit(150).all()
    stc = {'Sent': 'green', 'Pending': 'amber', 'Failed': 'red'}
    body = ''.join(
        f"<tr><td>{m.created.strftime('%d-%b %H:%M') if m.created else '—'}</td>"
        f"<td>{h(m.channel)}</td><td style='font-family:monospace'>{h(m.to)}</td>"
        f"<td>{h((m.body or '')[:60])}</td>"
        f"<td><span class='pill {stc.get(m.status,'grey')}'>{h(m.status)}</span>"
        f"<div style='color:var(--muted);font-size:11px'>{h(m.info or '')}</div></td>"
        f"<td class='num'>{'' if m.status=='Sent' else f'<a class=btn-sm-gh href=/msg/{m.id}/retry class=\"btn gh sm\">Retry</a>'.replace('btn-sm-gh','btn gh sm')}</td></tr>"
        for m in rows) or "<tr><td colspan='6' style='color:var(--muted);padding:14px'>No messages yet. They are queued automatically (lab results ready, appointment reminders).</td></tr>"
    pend = OutMsg.query.filter_by(status='Pending').count()
    fail = OutMsg.query.filter_by(status='Failed').count()
    gw = f"""<div class="panel"><div class="ph"><h2>Gateway (SMS / WhatsApp)</h2></div><div class="pad">
      <form method="post" action="/msg/settings"><div class="fg">
        <div class="fld full"><label>Gateway URL (JSON POST endpoint — Hormuud / Twilio bridge / local gateway)</label>
          <input name="sms_url" value="{h(setting('sms_url',''))}" placeholder="https://gateway.example/send"></div>
        <div class="fld"><label>API Key</label><input name="sms_key" value="{h(setting('sms_key',''))}"></div>
        <div class="fld"><label>Sender ID</label><input name="sms_sender" value="{h(setting('sms_sender','MDC'))}"></div>
        <div class="fld full"><button class="btn primary">Save Gateway</button>
          {f"<a class='btn' style='margin-left:8px' href='/msg/retryall'>↻ Retry all Pending/Failed ({pend+fail})</a>" if pend+fail else ''}</div>
      </div></form>
      <p style="color:var(--muted);font-size:12px">URL la'aan fariimuhu waxay ku sugnaadaan <b>Pending</b> — waxba ma lumaan; markaad gateway geliso Retry All guji.</p>
    </div></div>"""
    return page('Messages', gw + f"""<div class="panel"><div class="ph"><h2>Outbox (last 150)</h2></div>
      <div class="tw"><table><thead><tr><th>When</th><th>Ch.</th><th>To</th><th>Message</th><th>Status</th><th></th></tr></thead>
      <tbody>{body}</tbody></table></div></div>""", 'messages')


@bp.route('/msg/settings', methods=['POST'])
@login_required
def msg_settings():
    if not can('messages'): abort(403)
    for k in ('sms_url', 'sms_key', 'sms_sender'):
        v = (request.form.get(k) or '').strip()
        s = Setting.query.get(k)
        if s: s.value = v
        else: db.session.add(Setting(key=k, value=v))
    db.session.commit(); log('Messaging gateway updated')
    flash('Gateway saved'); return redirect(url_for('modules.module', mod='messages'))


@bp.route('/msg/<int:mid>/retry')
@login_required
def msg_retry(mid):
    if not can('messages'): abort(403)
    from ..models import OutMsg
    from ..core.messaging import try_send
    m = OutMsg.query.get_or_404(mid)
    try_send(m)
    flash(f'Message → {m.status}'); return redirect(url_for('modules.module', mod='messages'))


@bp.route('/msg/retryall')
@login_required
def msg_retryall():
    if not can('messages'): abort(403)
    from ..models import OutMsg
    from ..core.messaging import try_send
    n = 0
    for m in OutMsg.query.filter(OutMsg.status.in_(('Pending', 'Failed'))).all():
        if try_send(m): n += 1
    flash(f'{n} message(s) sent'); return redirect(url_for('modules.module', mod='messages'))


def errorlog_view():
    """Administrator-only application error log."""
    if not can('errorlog'):
        return page('Denied', '<div class="panel"><div class="pad"><b>Administrators only.</b></div></div>')
    from ..models import ErrorLog
    from flask import render_template
    show = request.args.get('show') or 'open'
    q = ErrorLog.query.order_by(ErrorLog.id.desc())
    if show == 'open':
        q = q.filter_by(resolved=False)
    errs = q.limit(200).all()
    rows = []
    for e in errs:
        resolve_cell = ('<span class="pill green">Resolved</span>' if e.resolved
                        else f"<a class='btn gh sm' href='/errorlog/{e.id}/resolve'>Mark resolved</a>")
        rows.append([
            f"ERR-{e.id:04d}",
            h(e.ts.strftime('%Y-%m-%d %H:%M') if e.ts else ''),
            h(e.user or '—'),
            f"<code style='font-size:11px'>{h(e.action or '')} {h(e.screen or '')}</code>",
            f"<span class='pill red'>{h(e.err_type or 'Error')}</span>",
            h(e.ip or '—'),
            resolve_cell,
            f"<a class='btn gh sm' href='/errorlog/{e.id}'>Details</a>",
        ])
    tabs = (f"<a class='btn sm {'primary' if show=='open' else ''}' href='?show=open'>Open</a> "
            f"<a class='btn sm {'primary' if show=='all' else ''}' href='?show=all'>All</a>")
    body = render_template(
        'list_page.html', title='Error Log', toolbar=tabs,
        note=('Application errors are captured here automatically for administrator review. '
              'Users never see technical details — only a friendly message.'),
        headers=['ID', 'When', 'User', 'Screen', 'Type', 'IP', 'Status', ''],
        rows=rows, empty='No errors logged. 🎉')
    return page('Error Log', body, 'errorlog')


@bp.route('/errorlog/<int:eid>')
@login_required
def errorlog_detail(eid):
    if not can('errorlog'): abort(403)
    from ..models import ErrorLog
    e = ErrorLog.query.get_or_404(eid)
    body = (f"<div class='panel'><div class='ph'><h2>ERR-{e.id:04d}</h2><div class='sp'></div>"
            f"<a class='btn sm' href='{url_for('modules.module', mod='errorlog')}'>← Error Log</a></div>"
            f"<div class='pad' style='font-size:13.5px'>"
            f"<b>When:</b> {h(e.ts.strftime('%Y-%m-%d %H:%M:%S') if e.ts else '')} · "
            f"<b>User:</b> {h(e.user or '—')} · <b>IP:</b> {h(e.ip or '—')}<br>"
            f"<b>Screen:</b> {h(e.action or '')} {h(e.screen or '')}<br>"
            f"<b>Type:</b> {h(e.err_type or '')}<br>"
            f"<b>Browser:</b> <span style='font-size:12px;color:var(--muted)'>{h(e.browser or '—')}</span></div>"
            f"<div class='pad'><b style='font-size:13px'>Technical details</b>"
            f"<pre style='white-space:pre-wrap;font-size:11.5px;background:var(--canvas);padding:12px;border-radius:8px;overflow:auto;max-height:400px'>{h(e.detail or '')}</pre></div></div>")
    return page(f'ERR-{e.id:04d}', body, 'errorlog')


@bp.route('/errorlog/<int:eid>/resolve')
@login_required
def errorlog_resolve(eid):
    if not can('errorlog'): abort(403)
    from ..models import ErrorLog
    e = ErrorLog.query.get_or_404(eid)
    e.resolved = True; db.session.commit()
    log(f'Error ERR-{eid:04d} marked resolved')
    flash(f'ERR-{eid:04d} marked resolved')
    return redirect(url_for('modules.module', mod='errorlog'))


# ============================ Service Management (dynamic config, no coding) ============================
SVC_DEPARTMENTS = ['Laboratory', 'CT Scan', 'MRI', 'X-Ray', 'Ultrasound', 'ECG',
                   'Echocardiography', 'Endoscopy', 'Consultation', 'Procedures',
                   'Vaccination', 'Other']
SVC_WORKFLOWS = ['Laboratory', 'Radiology', 'Consultation', 'Procedure', 'Cashier Only']
SVC_EQUIPMENT = ['', 'CT Scanner', 'MRI Scanner', 'X-Ray Machine', 'Ultrasound Machine',
                 'ECG Machine', 'Laboratory Analyzer', 'Endoscope', 'None']
# department -> the actual routing bucket used by the rest of the system
DEPT_TO_CORE = {'Laboratory': 'Laboratory', 'CT Scan': 'Radiology', 'MRI': 'Radiology',
                'X-Ray': 'Radiology', 'Ultrasound': 'Radiology', 'ECG': 'Radiology',
                'Echocardiography': 'Radiology', 'Endoscopy': 'Radiology',
                'Consultation': 'Consultation', 'Procedures': 'Other',
                'Vaccination': 'Other', 'Other': 'Other'}


def svcconfig_view():
    """Service Management — searchable list of configurable services."""
    if not can('svcconfig'):
        return page('Denied', '<div class="panel"><div class="pad"><b>Administrators and managers only.</b></div></div>')
    q = (request.args.get('q') or '').strip().lower()
    dep = request.args.get('dep') or ''
    stat = request.args.get('status') or ''
    equip = request.args.get('equip') or ''
    svcs = Service.query.order_by(Service.department, Service.name).all()
    rows = ''
    shown = 0
    for s in svcs:
        if q and q not in (s.name or '').lower() and q not in (s.code or '').lower() \
           and q not in (s.category or '').lower():
            continue
        if dep and (s.department or '') != dep:
            continue
        if stat == 'active' and not s.active: continue
        if stat == 'inactive' and s.active: continue
        if equip and (s.equipment or '') != equip:
            continue
        shown += 1
        wf = s.workflow or DEPT_TO_CORE.get(s.department, '—')
        rows += (f"<tr><td><b>{h(s.code or '—')}</b></td>"
                 f"<td><b>{h(s.name)}</b>{f'<div style=color:var(--muted);font-size:11px>{h(s.category)}</div>' if s.category else ''}</td>"
                 f"<td>{pill(s.department or '—', 'grey')}</td>"
                 f"<td>{pill(wf, 'blue')}</td>"
                 f"<td class='num'>{money(s.price)}</td>"
                 f"<td>{h(s.equipment or '—')}</td>"
                 f"<td>{pill('Active','green') if s.active else pill('Inactive','grey')}</td>"
                 f"<td class='num'><a class='btn gh sm' href='{url_for('admin.svcconfig_edit', sid=s.id)}'>Configure</a></td></tr>")
    rows = rows or "<tr><td colspan='8' style='color:var(--muted);padding:16px'>No services match.</td></tr>"
    depopts = "<option value=''>All Departments</option>" + ''.join(
        f"<option {'selected' if dep==d else ''}>{d}</option>" for d in SVC_DEPARTMENTS)
    eqopts = "<option value=''>All Equipment</option>" + ''.join(
        f"<option {'selected' if equip==e else ''}>{e or '—'}</option>" for e in SVC_EQUIPMENT if e)
    statopts = ''.join(f"<option value='{v}' {'selected' if stat==v else ''}>{l}</option>"
                       for v, l in [('', 'All'), ('active', 'Active'), ('inactive', 'Inactive')])
    toolbar = (f"<div class='pad' style='border-bottom:1px solid var(--line)'><form method='get' class='listbar'>"
               f"<input name='q' value='{h(q)}' placeholder='Search name / code / category…' class='lb-input'>"
               f"<select name='dep' class='lb-input'>{depopts}</select>"
               f"<select name='equip' class='lb-input'>{eqopts}</select>"
               f"<select name='status' class='lb-input'>{statopts}</select>"
               f"<button class='btn sm'>Filter</button>"
               f"<span class='lb-count'>{shown} service(s)</span></form></div>")
    body = (f"<div class='panel'><div class='ph'><h2>Service Management</h2><div class='sp'></div>"
            f"<a class='btn primary' href='{url_for('admin.svcconfig_edit', sid=0)}'>+ New Service</a></div>"
            f"<div class='pad' style='font-size:13px;color:var(--muted)'>Configure any diagnostic, laboratory, radiology, "
            f"consultation or procedure service — prices, commissions, workflow routing, equipment and timing — with no coding. "
            f"New services appear automatically across Doctor Requests, Billing, Lab/Radiology and Reports.</div>"
            f"{toolbar}"
            f"<div class='tw'><table><thead><tr><th>Code</th><th>Service</th><th>Department</th>"
            f"<th>Workflow</th><th class='num'>Price</th><th>Equipment</th><th>Status</th><th></th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></div>")
    return page('Service Management', body, 'svcconfig')


@bp.route('/svcconfig/<int:sid>', methods=['GET', 'POST'])
@login_required
def svcconfig_edit(sid):
    if not can('svcconfig'): abort(403)
    s = Service.query.get(sid) if sid else None
    if request.method == 'POST':
        f = request.form
        if not s:
            s = Service()
            code = (f.get('code') or '').strip()
            if not code:  # auto-generate (count before add to avoid premature autoflush)
                dep = f.get('department') or 'GEN'
                prefix = ''.join(w[0] for w in dep.split()[:2]).upper() or 'SVC'
                n = Service.query.count() + 1
                code = f'{prefix}{n:04d}'
            s.code = code
            s.name = f.get('name') or 'Unnamed Service'
            db.session.add(s)
        # general
        for attr in ('name', 'short_name', 'category', 'subcategory', 'description',
                     'department', 'workflow', 'report_template', 'equipment', 'modality',
                     'ref_range', 'unit', 'specimen', 'loinc', 'cpt'):
            setattr(s, attr, f.get(attr) or None)
        s.active = f.get('active') == '1'
        s.discount_allowed = f.get('discount_allowed') == '1'
        # auto modality from department for radiology sub-types
        if s.department in ('CT Scan', 'MRI', 'X-Ray', 'Ultrasound', 'ECG') and not s.modality:
            s.modality = {'CT Scan': 'CT', 'MRI': 'MRI', 'X-Ray': 'X-Ray',
                          'Ultrasound': 'Ultrasound', 'ECG': 'ECG'}.get(s.department)
        # auto workflow from department if not chosen
        if not s.workflow:
            s.workflow = DEPT_TO_CORE.get(s.department, 'Cashier Only')
            if s.workflow == 'Other': s.workflow = 'Procedure'
        # numeric fields
        def fnum(k):
            try: return float(f.get(k) or 0)
            except ValueError: return 0
        def inum(k):
            try: return int(f.get(k) or 0) or None
            except ValueError: return None
        for attr in ('price', 'price_insurance', 'price_corporate', 'price_vip',
                     'price_contract', 'price_emergency', 'price_home', 'cost',
                     'max_discount', 'panic_low', 'panic_high', 'supply_qty',
                     'comm_doctor_val', 'comm_radiologist_val', 'comm_tech_val', 'comm_report_val'):
            setattr(s, attr, fnum(attr))
        for attr in ('time_collection', 'time_processing', 'time_reporting'):
            setattr(s, attr, inum(attr))
        for attr in ('comm_doctor_type', 'comm_radiologist_type', 'comm_tech_type', 'comm_report_type'):
            setattr(s, attr, f.get(attr) or 'Percent')
        sup = f.get('supply_id')
        s.supply_id = int(sup) if sup and sup.isdigit() else None
        s.avail_branches = f.get('avail_branches') or None
        db.session.commit()
        log(f'Service configured: {s.code} · {s.name}')
        flash(f'Service “{s.name}” saved — now available across the system')
        return redirect(url_for('modules.module', mod='svcconfig'))

    # ---- build the configuration form ----
    v = lambda a, d='': h(getattr(s, a, d) if s and getattr(s, a, None) is not None else d)
    nv = lambda a: (getattr(s, a, 0) or 0) if s else 0
    def sel(name, options, cur, blank=None):
        opts = ''
        if blank is not None:
            opts += f"<option value=''>{blank}</option>"
        for o in options:
            val, lab = (o, o) if isinstance(o, str) else o
            opts += f"<option value='{h(val)}' {'selected' if str(cur)==str(val) else ''}>{h(lab)}</option>"
        return f"<select name='{name}' class='cf-in'>{opts}</select>"
    def txt(name, val='', ph=''):
        return f"<input name='{name}' value='{h(val)}' placeholder='{h(ph)}' class='cf-in'>"
    def num(name, val=0, step='any'):
        return f"<input name='{name}' type='number' step='{step}' value='{val or ''}' class='cf-in'>"

    cur_dep = getattr(s, 'department', '') if s else ''
    cur_wf = getattr(s, 'workflow', '') if s else ''
    cur_eq = getattr(s, 'equipment', '') if s else ''
    comm_type_opts = ['Percent', 'Fixed']

    def comm_row(label, tname, vname):
        ct = getattr(s, tname, 'Percent') if s else 'Percent'
        return (f"<div class='cf-row'><label>{label}</label>"
                f"<div style='display:flex;gap:8px'>{sel(tname, comm_type_opts, ct)}"
                f"{num(vname, nv(vname))}</div></div>")

    supopts = [('', '— none —')] + [(str(m.id), m.name) for m in Medicine.query.order_by(Medicine.name).all()]
    tpl_opts = ['', 'CT Brain', 'CT Chest', 'CT Abdomen', 'CT Spine', 'MRI Brain', 'MRI Spine',
                'MRI Knee', 'X-Ray Chest', 'X-Ray Limb', 'Ultrasound Abdomen',
                'Ultrasound Pelvis', 'Ultrasound Obstetric']
    branches = Branch.query.filter_by(active=True).all() if hasattr(Branch, 'active') else Branch.query.all()

    def section(title, inner):
        return (f"<div class='panel'><div class='ph'><h2>{title}</h2></div><div class='pad'><div class='cf-grid'>{inner}</div></div></div>")

    barcode_preview = ''
    if s and s.code:
        barcode_preview = (f"<div class='cf-row'><label>Service Barcode / QR</label>"
                           f"<div style='display:flex;gap:14px;align-items:center'>"
                           f"<img src='/svcconfig/{s.id}/barcode' style='height:54px'>"
                           f"<img src='/svcconfig/{s.id}/qr' style='height:70px'>"
                           f"<span style='color:var(--muted);font-size:12px'>Auto-generated from code <b>{h(s.code)}</b></span></div></div>")
    else:
        barcode_preview = "<div class='cf-row'><label>Barcode / QR</label><span style='color:var(--muted);font-size:12px'>Generated automatically after you save (from the service code).</span></div>"

    general = section("General Information",
        f"<div class='cf-row'><label>Service Code (blank = auto)</label>{txt('code', v('code'), 'auto-generated if blank')}</div>"
        f"<div class='cf-row'><label>Service Name *</label>{txt('name', v('name'))}</div>"
        f"<div class='cf-row'><label>Short Name</label>{txt('short_name', v('short_name'))}</div>"
        f"<div class='cf-row'><label>Department *</label>{sel('department', SVC_DEPARTMENTS, cur_dep, 'Select…')}</div>"
        f"<div class='cf-row'><label>Category</label>{txt('category', v('category'), 'e.g. CT Scan, Hematology')}</div>"
        f"<div class='cf-row'><label>Subcategory</label>{txt('subcategory', v('subcategory'))}</div>"
        f"<div class='cf-row cf-full'><label>Description</label><textarea name='description' class='cf-in' rows='2'>{v('description')}</textarea></div>"
        f"<div class='cf-row'><label>Active</label>{sel('active', [('1','Active'),('0','Inactive')], '1' if (not s or s.active) else '0')}</div>")

    pricing = section("Pricing",
        f"<div class='cf-row'><label>Standard (Cash)</label>{num('price', nv('price'))}</div>"
        f"<div class='cf-row'><label>Corporate</label>{num('price_corporate', nv('price_corporate'))}</div>"
        f"<div class='cf-row'><label>Insurance</label>{num('price_insurance', nv('price_insurance'))}</div>"
        f"<div class='cf-row'><label>Emergency</label>{num('price_emergency', nv('price_emergency'))}</div>"
        f"<div class='cf-row'><label>VIP</label>{num('price_vip', nv('price_vip'))}</div>"
        f"<div class='cf-row'><label>Home Service</label>{num('price_home', nv('price_home'))}</div>"
        f"<div class='cf-row'><label>Contract</label>{num('price_contract', nv('price_contract'))}</div>"
        f"<div class='cf-row'><label>Direct Cost</label>{num('cost', nv('cost'))}</div>"
        f"<div class='cf-row'><label>Discount Allowed</label>{sel('discount_allowed', [('1','Yes'),('0','No')], '1' if (not s or s.discount_allowed) else '0')}</div>"
        f"<div class='cf-row'><label>Max Discount (%)</label>{num('max_discount', nv('max_discount'))}</div>")

    commission = section("Commission (auto-calculated after payment)",
        comm_row('Referring Doctor', 'comm_doctor_type', 'comm_doctor_val')
        + comm_row('Radiologist', 'comm_radiologist_type', 'comm_radiologist_val')
        + comm_row('Laboratory Technician', 'comm_tech_type', 'comm_tech_val')
        + comm_row('Report Writer', 'comm_report_type', 'comm_report_val'))

    workflow = section("Workflow & Routing",
        f"<div class='cf-row'><label>Route To</label>{sel('workflow', SVC_WORKFLOWS, cur_wf, 'Auto (from department)')}</div>"
        f"<div class='cf-row'><label>Equipment</label>{sel('equipment', [e for e in SVC_EQUIPMENT if e], cur_eq, '— none —')}</div>"
        f"<div class='cf-row'><label>Report Template</label>{sel('report_template', [t for t in tpl_opts if t], v('report_template'), '— none —')}</div>"
        f"<div class='cf-row'><label>Modality (radiology)</label>{txt('modality', v('modality'), 'CT / MRI / X-Ray…')}</div>")

    labcfg = section("Laboratory / Clinical Details",
        f"<div class='cf-row'><label>Reference Range</label>{txt('ref_range', v('ref_range'), 'e.g. 4.0 – 11.0')}</div>"
        f"<div class='cf-row'><label>Unit</label>{txt('unit', v('unit'), 'e.g. x10⁹/L')}</div>"
        f"<div class='cf-row'><label>Specimen</label>{txt('specimen', v('specimen'), 'e.g. Serum, EDTA')}</div>"
        f"<div class='cf-row'><label>Panic Low</label>{num('panic_low', nv('panic_low'))}</div>"
        f"<div class='cf-row'><label>Panic High</label>{num('panic_high', nv('panic_high'))}</div>"
        f"<div class='cf-row'><label>LOINC</label>{txt('loinc', v('loinc'))}</div>"
        f"<div class='cf-row'><label>CPT</label>{txt('cpt', v('cpt'))}</div>")

    timing = section("Estimated Time (minutes) & Inventory",
        f"<div class='cf-row'><label>Sample Collection</label>{num('time_collection', nv('time_collection'), '1')}</div>"
        f"<div class='cf-row'><label>Processing</label>{num('time_processing', nv('time_processing'), '1')}</div>"
        f"<div class='cf-row'><label>Reporting</label>{num('time_reporting', nv('time_reporting'), '1')}</div>"
        f"<div class='cf-row'><label>Supply Consumed</label>{sel('supply_id', supopts, str(getattr(s,'supply_id','') or ''), None)}</div>"
        f"<div class='cf-row'><label>Qty per Service</label>{num('supply_qty', nv('supply_qty'))}</div>")

    availability = section("Availability & Barcode",
        f"<div class='cf-row cf-full'><label>Available Branches (blank = all)</label>{txt('avail_branches', v('avail_branches'), 'e.g. Main, Branch 2')}</div>"
        + barcode_preview)

    title = f"Configure · {h(s.name)}" if s else "New Service"
    body = (f"<form method='post'>"
            f"<div class='panel'><div class='pad' style='display:flex;align-items:center;gap:10px'>"
            f"<div style='font-family:var(--fd);font-size:19px;font-weight:700;color:var(--petrol)'>{title}</div>"
            f"<div class='sp' style='flex:1'></div>"
            f"<a class='btn sm' href='{url_for('modules.module', mod='svcconfig')}'>← Cancel</a>"
            f"<button class='btn primary'>💾 Save Service</button></div></div>"
            + general + pricing + commission + workflow + labcfg + timing + availability
            + f"<div class='panel'><div class='pad' style='text-align:right'>"
            f"<button class='btn primary' style='padding:12px 28px'>💾 Save Service</button></div></div>"
            f"</form>")
    return page(title, body, 'svcconfig')


@bp.route('/svcconfig/<int:sid>/barcode')
@login_required
def svcconfig_barcode(sid):
    if not can('svcconfig'): abort(403)
    s = Service.query.get_or_404(sid)
    from ..core.barcodes import code128_svg
    from flask import Response
    svg = code128_svg(s.code or f'SVC{sid}')
    return Response(svg, mimetype='image/svg+xml')


@bp.route('/svcconfig/<int:sid>/qr')
@login_required
def svcconfig_qr(sid):
    if not can('svcconfig'): abort(403)
    s = Service.query.get_or_404(sid)
    from ..core.barcodes import qr_svg
    from flask import Response
    svg = qr_svg(f'SERVICE:{s.code}:{s.name}')
    return Response(svg, mimetype='image/svg+xml')




# ==================== Simple Service Management (Settings → Service Management) ====================

SVC_DEPARTMENTS = ['Laboratory', 'CT Scan', 'MRI', 'X-Ray', 'Ultrasound', 'ECG',
                   'Echocardiography', 'Endoscopy', 'Consultation', 'Procedures',
                   'Vaccination', 'Other']


def _comm_pick(field, s):
    """Type selector shared by the doctor-commission and radiologist-fee rows."""
    cur = (getattr(s, field, '') or '') if s else ''
    opts = [('', '— none (use default) —'), ('Fixed', 'Fixed $ per service'),
            ('Percent', '% of service price')]
    return ("<select name='" + field + "'>"
            + ''.join(f"<option value='{v}' {'selected' if cur == v else ''}>{h(lb)}</option>"
                      for v, lb in opts) + '</select>')



@bp.route('/svcmgmt/<int:sid>/consumables', methods=['GET', 'POST'])
@login_required
def svcmgmt_consumables(sid):
    if not can('svcmgmt'):
        abort(403)
    svc = Service.query.get_or_404(sid)
    if request.method == 'POST':
        act = request.form.get('act')
        if act == 'add':
            mid = request.form.get('medicine_id', type=int)
            try:
                qty = float(request.form.get('qty') or 1)
            except ValueError:
                qty = 1
            if mid and qty > 0:
                db.session.add(ServiceConsumable(service_id=sid, medicine_id=mid, qty=qty)); db.session.commit()
                flash('Consumable added.')
        elif act == 'del':
            scid = request.form.get('scid', type=int)
            sc = ServiceConsumable.query.get(scid)
            if sc and sc.service_id == sid:
                db.session.delete(sc); db.session.commit(); flash('Removed.')
        return redirect(url_for('admin.svcmgmt_consumables', sid=sid))
    meds = Medicine.query.order_by(Medicine.name).all()
    scs = ServiceConsumable.query.filter_by(service_id=sid).all()
    trows = ''
    for sc in scs:
        m = sc.item
        trows += (f"<tr><td>{h(m.name if m else '—')}</td><td class='num'>{sc.qty:g}</td>"
                  f"<td class='num'>{(m.qty if m else '—')}</td>"
                  f"<td class='num'><form method='post' style='display:inline' onsubmit=\"return confirm('Remove this consumable?')\">"
                  f"<input type='hidden' name='act' value='del'><input type='hidden' name='scid' value='{sc.id}'>"
                  f"<button class='btn gh sm' style='color:var(--red)'>Remove</button></form></td></tr>")
    if not trows:
        trows = "<tr><td colspan='4'><div class='empty'><b>No consumables linked yet</b>Ku dar agabka adeeggan isticmaalo (contrast, gloves, cannula…).</div></td></tr>"
    opts = "<option value=''>— choose item —</option>" + "".join(
        f"<option value='{m.id}'>{h(m.name)} · stock {m.qty}</option>" for m in meds)
    add_form = (f"<form method='post' style='display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:14px'>"
                f"<input type='hidden' name='act' value='add'>"
                f"<div><label style='display:block;font-size:12px;color:var(--muted)'>Item</label>"
                f"<select name='medicine_id' data-search required style='min-width:240px;border:1px solid var(--line);border-radius:8px;padding:8px'>{opts}</select></div>"
                f"<div><label style='display:block;font-size:12px;color:var(--muted)'>Qty used per service</label>"
                f"<input name='qty' type='number' step='any' min='0' value='1' style='width:120px;border:1px solid var(--line);border-radius:8px;padding:8px'></div>"
                f"<button class='btn primary'>+ Add Consumable</button></form>"
                if meds else "<div class='empty'><b>No inventory items yet</b>Ku dar agab (Pharmacy/Inventory) marka hore.</div>")
    body = (f"<div class='panel'><div class='ph'><h2>Consumables · {h(svc.name)}</h2>"
            f"<span class='so'>Agabka adeeggan isticmaalo — marka invoice la bixiyo si toos ah ayaa stock-ga looga jaraa</span>"
            f"<div class='sp'></div><a class='btn' href='{url_for('modules.module', mod='svcmgmt')}'>← Back to Services</a></div>"
            f"<div class='pad'>{add_form}"
            f"<div class='tw'><table><thead><tr><th>Item</th><th class='num'>Qty / service</th><th class='num'>In stock</th><th></th></tr></thead>"
            f"<tbody>{trows}</tbody></table></div>"
            f"<div style='color:var(--muted);font-size:12.5px;margin-top:10px'>Tusaale: <b>Brain CT-Scan (With Contrast)</b> → Contrast bottle ×1, Gloves ×2, Cannula ×1. "
            f"Marka baaritaanku la bixiyo, agabkaas si toos ah ayaa stock-ga looga jaraa (StockAdj) oo lagu diiwaan geliyaa Consumption Report.</div>"
            f"</div></div>")
    return page(f'Consumables · {svc.name}', body, 'svcmgmt')


def svcmgmt_view():
    """Simple, user-friendly service list with New/Edit/Activate/Deactivate/Delete."""
    q = (request.args.get('q') or '').strip().lower()
    svcs = Service.query.order_by(Service.department, Service.name).all()
    if q:
        svcs = [s for s in svcs if q in (s.name or '').lower() or q in (s.code or '').lower()
                or q in (s.department or '').lower() or q in (s.category or '').lower()]
    rows = ''
    for s in svcs:
        used = InvoiceItem.query.filter_by(service_id=s.id).count()
        st = "<span class='pill green'>Active</span>" if s.active else "<span class='pill grey'>Inactive</span>"
        toggle = (f"<a class='btn gh sm' href='/svcmgmt/{s.id}/toggle'>"
                  f"{'Deactivate' if s.active else 'Activate'}</a>")
        if used:
            delbtn = f"<span class='so' title='Used on {used} invoice(s) — deactivate instead'>in use</span>"
        else:
            delbtn = (f"<a class='btn gh sm' href='/svcmgmt/{s.id}/delete' "
                      f"onclick=\"return confirm('Delete this service permanently?')\">Delete</a>")
        rows += (f"<tr><td><b>{h(s.code or '—')}</b></td><td>{h(s.name)}</td>"
                 f"<td>{h(s.department or '—')}</td><td>{h(s.category or '—')}</td>"
                 f"<td class='num'>{money(s.price)}</td><td class='num'>{money(s.cost or 0)}</td>"
                 f"<td>{st}</td>"
                 f"<td class='num'><a class='btn gh sm' href='/svcmgmt/{s.id}/consumables' title='Supplies used (contrast, gloves, cannula…)'>🧪 Consumables</a> <a class='btn gh sm' href='/svcmgmt/{s.id}/edit'>Edit</a> {toggle} {delbtn}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='8'><div class='empty'><b>No services yet</b>Gujin '+ New Service'.</div></td></tr>"
    bar = (f"<div class='panel'><div class='pad'><form method='get' class='listbar'>"
           f"<input name='q' value='{h(q)}' placeholder='Search name, code, department...' class='lb-input' style='min-width:260px'>"
           f"<button class='btn sm'>Search</button><div class='sp'></div>"
           f"<a class='btn' href='/svcmgmt/load-ct-catalog' onclick=\"return confirm('Add the CT-Scan catalog — 20 scans × (Non-Contrast $150 / With Contrast $180)? Services already present are skipped.')\">🩻 Load CT-Scan Catalog</a>"
           f"<a class='btn primary' href='/svcmgmt/new'>+ New Service</a>"
           f"</form></div></div>")
    panel = (f"<div class='panel'><div class='ph'><h2>Service Management</h2>"
             f"<span class='so'>{len(svcs)} services · foom fudud</span></div>"
             f"<div class='tw'><table><thead><tr><th>Code</th><th>Service Name</th><th>Department</th>"
             f"<th>Category</th><th class='num'>Sale Price</th><th class='num'>Cost Price</th>"
             f"<th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>")
    return page('Service Management', bar + panel, 'svcmgmt')


CT_SCAN_TYPES = ['Brain', 'Cervical Spine', 'Neck', 'Lumbar Spine', 'Thoracic Spine',
                 'Chest', 'Abdomen', 'Pelvic', 'Shoulder', 'Elbow', 'Arm', 'Wrist',
                 'Femur', 'Knee', 'Tibia', 'Paranasal (PNS)', 'Foot', 'Orbital',
                 'Mandible', 'Facial']


@bp.route('/svcmgmt/load-ct-catalog')
@login_required
def svcmgmt_load_ct():
    if not can('svcmgmt'):
        abort(403)

    def _uniq_code():
        n = Service.query.count() + 1
        code = f'R{n:04d}'
        while Service.query.filter_by(code=code).first():
            n += 1
            code = f'R{n:04d}'
        return code

    added = skipped = 0
    for t in CT_SCAN_TYPES:
        for variant, price in (('Non-Contrast', 150), ('With Contrast', 180)):
            name = f'{t} CT-Scan ({variant})'
            if Service.query.filter_by(name=name).first():
                skipped += 1
                continue
            db.session.add(Service(code=_uniq_code(), name=name, department='Radiology',
                                   modality='CT', category='CT Scan', price=price, active=True))
            db.session.flush()   # visible to the next code/name check within this run
            added += 1
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        from ..core.helpers import log_error
        log_error('svcmgmt_load_ct')
        flash('Could not load the CT-Scan catalog — please try again.')
        return redirect(url_for('modules.module', mod='svcmgmt'))
    log(f'Loaded CT-Scan catalog: +{added} services ({skipped} already present)')
    flash(f'CT-Scan catalog loaded — added {added} services, skipped {skipped} already present. '
          'Waxay ka muuqan doonaan Radiology, Billing iyo Doctor Request.')
    return redirect(url_for('modules.module', mod='svcmgmt'))


@bp.route('/svcmgmt/new', methods=['GET', 'POST'])
@bp.route('/svcmgmt/<int:sid>/edit', methods=['GET', 'POST'])
@login_required
def svcmgmt_form(sid=None):
    if not can('svcmgmt'): abort(403)
    s = Service.query.get_or_404(sid) if sid else None
    if request.method == 'POST':
        f = request.form
        new = s is None
        if new:
            s = Service()
            dep = f.get('department') or 'GEN'
            prefix = ''.join(w[0] for w in dep.split()[:2]).upper() or 'SVC'
            # Guaranteed-unique code: step past any existing code (count()+1 alone
            # collides when a service was deleted or two departments share a prefix,
            # and a rolled-back failure keeps regenerating the same clashing code).
            n = Service.query.count() + 1
            code = f'{prefix}{n:04d}'
            while Service.query.filter_by(code=code).first():
                n += 1
                code = f'{prefix}{n:04d}'
            s.code = code
            db.session.add(s)
        s.name = (f.get('name') or '').strip() or 'Unnamed Service'
        s.department = f.get('department') or s.department
        s.category = f.get('category') or ''
        s.price = float(f.get('price') or 0)
        s.cost = float(f.get('cost') or 0)
        # commission / fee rules for this service — same idea for both payees
        def _num(x):
            try: return float(x or 0)
            except (TypeError, ValueError): return 0.0
        for who in ('doctor', 'radiologist'):
            t = f.get(f'comm_{who}_type') or ''
            setattr(s, f'comm_{who}_type', t if t in ('Fixed', 'Percent') else '')
            setattr(s, f'comm_{who}_val', _num(f.get(f'comm_{who}_val')) if t in ('Fixed', 'Percent') else 0)
        s.active = f.get('active') == '1'
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            from ..core.helpers import log_error
            log_error('svcmgmt_form save')
            flash('Could not save the service — the code may already be in use. Please try again.')
            return redirect('/svcmgmt/new' if new else f'/svcmgmt/{sid}/edit')
        log(f"Service {'created' if new else 'updated'} (simple): {s.code} {s.name}")
        flash(f"Service '{s.name}' saved — waa laga heli karaa Billing, Doctor Request, Lab/Radiology iyo Reports.")
        if f.get('save_new'):
            return redirect('/svcmgmt/new')
        return redirect(url_for('modules.module', mod='svcmgmt'))
    v = lambda a, d='': h(getattr(s, a, None) or d) if s else h(d)
    dopts = ''.join(f"<option {'selected' if s and s.department==d else ''}>{d}</option>" for d in SVC_DEPARTMENTS)
    body = f"""<div class='panel'><div class='ph'><h2>{'Edit Service' if s else 'New Service'}</h2>
      <div class='sp'></div><a class='btn' href='{url_for('modules.module', mod='svcmgmt')}'>← Cancel</a></div>
      <div class='pad'><form method='post'>
      <input type='hidden' name='_csrf' value='{csrf_token()}'>
      <div class='g2'>
        <div class='fld'><label>🆔 Service Code</label><input value='{v("code","(auto-generated)")}' disabled style='background:var(--canvas)'></div>
        <div class='fld'><label>🏥 Service Name *</label><input name='name' value='{v("name")}' required autofocus></div>
        <div class='fld'><label>📂 Department *</label><select name='department' required><option value=''>Select...</option>{dopts}</select></div>
        <div class='fld'><label>📑 Category</label><input name='category' value='{v("category")}' placeholder='e.g. Hematology, CT Scan'></div>
        <div class='fld'><label>💰 Sale Price *</label><input name='price' type='number' step='0.01' value='{s.price if s else ""}' required></div>
        <div class='fld'><label>💵 Cost Price</label><input name='cost' type='number' step='0.01' value='{(s.cost or 0) if s else ""}'></div>
        <div class='fld'><label>📋 Status</label><select name='active'><option value='1' {'selected' if (s is None or s.active) else ''}>Active</option><option value='0' {'selected' if (s is not None and not s.active) else ''}>Inactive</option></select></div>
      </div>
      <div style='margin:18px 0 8px;font-weight:700;color:var(--petrol);font-family:Space Grotesk'>Commission &amp; Fees <span style='font-weight:500;color:var(--muted);font-size:12.5px'>— si toos ah ayaa loo xisaabiyaa marka biilka la bixiyo</span></div>
      <div class='g2'>
        <div class='fld'><label>🩺 Doctor Commission</label>{_comm_pick('comm_doctor_type', s)}</div>
        <div class='fld'><label>Value ($ ama %)</label><input name='comm_doctor_val' type='number' step='0.01' value='{(s.comm_doctor_val or 0) if s else 0}'></div>
        <div class='fld'><label>🔬 Radiologist Fee</label>{_comm_pick('comm_radiologist_type', s)}</div>
        <div class='fld'><label>Value ($ ama %)</label><input name='comm_radiologist_val' type='number' step='0.01' value='{(s.comm_radiologist_val or 0) if s else 0}'></div>
      </div>
      <div style='color:var(--muted);font-size:12.5px;margin-top:6px'>
        Tusaale CT $150: Doctor <b>Percent 20</b> → $30 · Radiologist <b>Fixed 10</b> → $10 per warbixin.
        Faaruq/None = qaanuunka radiologist-ka gaarka ah ama <b>rad_fee</b> ee guud ($10) ayaa la isticmaalaa.
      </div>
      <div style='text-align:right;margin-top:14px;display:flex;gap:8px;justify-content:flex-end'>
        <a class='btn' href='{url_for('modules.module', mod='svcmgmt')}'>Cancel</a>
        <button class='btn' name='save_new' value='1'>Save &amp; New</button>
        <button class='btn primary'>💾 Save</button>
      </div></form></div></div>"""
    return page('Service Management', body, 'svcmgmt')


@bp.route('/svcmgmt/<int:sid>/toggle')
@login_required
def svcmgmt_toggle(sid):
    if not can('svcmgmt'): abort(403)
    s = Service.query.get_or_404(sid)
    s.active = not s.active
    db.session.commit()
    log(f"Service {'activated' if s.active else 'deactivated'}: {s.code} {s.name}")
    flash(f"'{s.name}' is now {'Active' if s.active else 'Inactive'}")
    return redirect(url_for('modules.module', mod='svcmgmt'))


@bp.route('/svcmgmt/<int:sid>/delete')
@login_required
def svcmgmt_delete(sid):
    if not can('svcmgmt'): abort(403)
    s = Service.query.get_or_404(sid)
    if InvoiceItem.query.filter_by(service_id=s.id).count():
        flash('Service is used on invoices — deactivate it instead of deleting.')
        return redirect(url_for('modules.module', mod='svcmgmt'))
    log(f'Service deleted: {s.code} {s.name}')
    db.session.delete(s); db.session.commit()
    flash('Service deleted.')
    return redirect(url_for('modules.module', mod='svcmgmt'))


# ============================ System Health ============================
APP_VERSION = '7.9'


def _health_card(title, value, sub='', accent='var(--petrol)', bar=None):
    """A metric card; if `bar` (0-100) is given, render a colored usage bar."""
    barhtml = ''
    if bar is not None:
        col = 'var(--green)' if bar < 60 else ('var(--amber)' if bar < 85 else 'var(--red)')
        barhtml = (f"<div style='height:8px;background:var(--line);border-radius:6px;margin-top:8px;overflow:hidden'>"
                   f"<div style='height:100%;width:{min(bar,100):.0f}%;background:{col};border-radius:6px'></div></div>")
    return (f"<div class='panel' style='padding:0'><div class='pad'>"
            f"<div style='font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;font-weight:600'>{title}</div>"
            f"<div style='font-size:24px;font-weight:700;color:{accent};font-family:var(--fd);margin-top:3px'>{value}</div>"
            f"{f'<div style=\"font-size:11.5px;color:var(--muted);margin-top:2px\">{sub}</div>' if sub else ''}"
            f"{barhtml}</div></div>")


@bp.route('/system/health')
@login_required
def system_health():
    if not can('syshealth'):
        return page('Denied', "<div class='panel'><div class='pad'><b>Administrators only.</b></div></div>")
    import shutil, platform
    from sqlalchemy import text as _text
    import flask as _flask

    # --- CPU / RAM / Disk (psutil, with graceful fallback) ---
    cpu = ram = disk = None
    ram_txt = disk_txt = cpu_txt = 'n/a'
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.3)
        cpu_txt = f'{cpu:.0f}%'
        vm = psutil.virtual_memory()
        ram = vm.percent
        ram_txt = f'{vm.used/1e9:.1f} / {vm.total/1e9:.1f} GB'
    except Exception:
        try:
            la = os.getloadavg()[0]; cpu = min(la * 25, 100); cpu_txt = f'load {la:.2f}'
        except Exception:
            pass
    try:
        du = shutil.disk_usage('/')
        disk = du.used / du.total * 100
        disk_txt = f'{du.used/1e9:.1f} / {du.total/1e9:.1f} GB'
    except Exception:
        pass

    # --- Database size + health ---
    dburl = str(db.engine.url)
    is_sqlite = db.engine.url.get_backend_name() == 'sqlite'
    db_size_txt = 'n/a'; db_health = 'Unknown'; db_health_ok = True; db_engine = db.engine.url.get_backend_name()
    try:
        if is_sqlite and db.engine.url.database:
            _p = db.engine.url.database
            _sz = os.path.getsize(_p) if os.path.exists(_p) else 0
            for _ext in ('-wal', '-shm'):
                if os.path.exists(_p + _ext): _sz += os.path.getsize(_p + _ext)
            db_size_txt = f'{_sz/1e6:.1f} MB'
            _ic = db.session.execute(_text('PRAGMA integrity_check')).scalar()
            _jm = db.session.execute(_text('PRAGMA journal_mode')).scalar()
            db_health_ok = (str(_ic).lower() == 'ok')
            db_health = f'{"Healthy" if db_health_ok else "CHECK FAILED"} · {str(_jm).upper()}'
        else:
            db.session.execute(_text('SELECT 1'))
            db_health = 'Healthy (PostgreSQL)'
    except Exception as _e:
        db_health = 'Error'; db_health_ok = False

    _ntables = 0
    try:
        _ntables = len(db.inspect(db.engine).get_table_names())
    except Exception:
        pass

    # --- API status (DB reachable => online) ---
    try:
        db.session.execute(_text('SELECT 1')); api_ok = True
    except Exception:
        api_ok = False

    # --- Backups ---
    from ..core import autobackup
    backup_txt = 'No backups yet'; backup_ok = False
    try:
        _bks = autobackup.list_backups(current_app)
        if _bks:
            _newest = _bks[0]
            _mt = _newest.get('mtime') if isinstance(_newest, dict) else None
            if _mt:
                try:
                    _when = dt.datetime.fromisoformat(_mt)
                except Exception:
                    _when = None
                if _when:
                    _age = dt.datetime.now() - _when
                    _hrs = _age.total_seconds() / 3600
                    backup_ok = _hrs < 48
                    _ago = (f'{_age.days}d ago' if _age.days else (f'{int(_hrs)}h ago' if _hrs >= 1 else f'{int(_age.seconds/60)}m ago'))
                    backup_txt = f'{len(_bks)} kept · last {_ago}'
                else:
                    backup_txt = f'{len(_bks)} backup file(s)'; backup_ok = True
            else:
                backup_txt = f'{len(_bks)} backup file(s)'; backup_ok = True
    except Exception:
        backup_txt = 'Unavailable'

    # --- Users / logins / errors ---
    _today = today()
    _cutoff = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=30)
    try:
        active_users = db.session.query(LoginHistory.username).filter(
            LoginHistory.ok == True, LoginHistory.when >= _cutoff).distinct().count()
    except Exception:
        active_users = 0
    try:
        failed_logins = LoginHistory.query.filter(
            LoginHistory.ok == False, db.func.date(LoginHistory.when) == _today).count()
    except Exception:
        failed_logins = 0
    try:
        open_errors = ErrorLog.query.filter_by(resolved=False).count()
        errors_today = ErrorLog.query.filter(db.func.date(ErrorLog.ts) == _today).count()
    except Exception:
        open_errors = errors_today = 0
    total_users = User.query.filter_by(active=True).count()

    # --- assemble ---
    cards = [
        _health_card('CPU', cpu_txt, 'processor load', bar=cpu),
        _health_card('RAM', f'{ram:.0f}%' if ram is not None else 'n/a', ram_txt, bar=ram),
        _health_card('Disk', f'{disk:.0f}%' if disk is not None else 'n/a', disk_txt, bar=disk),
        _health_card('Database Size', db_size_txt, f'{_ntables} tables · {db_engine}'),
        _health_card('Database Health', ('✓ ' + db_health) if db_health_ok else ('⚠ ' + db_health),
                     'integrity & journal mode', accent=('var(--green)' if db_health_ok else 'var(--red)')),
        _health_card('Backup Status', ('✓ OK' if backup_ok else '⚠ Check'), backup_txt,
                     accent=('var(--green)' if backup_ok else 'var(--amber)')),
        _health_card('API Status', ('● Online' if api_ok else '● Offline'), 'application & database',
                     accent=('var(--green)' if api_ok else 'var(--red)')),
        _health_card('Active Users', active_users, f'last 30 min · {total_users} enabled', accent='var(--blue)'),
        _health_card('Failed Logins', failed_logins, 'today', accent=('var(--red)' if failed_logins else 'var(--green)')),
        _health_card('Errors', open_errors, f'{errors_today} today · unresolved',
                     accent=('var(--red)' if open_errors else 'var(--green)')),
        _health_card('System Version', f'v{APP_VERSION}', f'Python {platform.python_version()} · Flask {_flask.__version__}', accent='var(--petrol)'),
    ]
    grid = ("<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px'>"
            + ''.join(cards) + "</div>")
    refreshed = f"<div style='color:var(--muted);font-size:12px;margin:2px 4px 12px'>Live snapshot · {dt.datetime.now().strftime('%d-%b-%Y %H:%M:%S')} · <a href='{url_for('admin.system_health')}' style='color:var(--petrol)'>↻ Refresh</a></div>"
    return page('System Health', refreshed + grid, 'syshealth')
