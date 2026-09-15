"""Dialysis  (Phase 10, v8.0).

Haemodialysis session scheduling with machine assignment, the treatment record
(pre/post weight & BP, ultrafiltration, blood flow, complications), pre/post lab
monitoring, and billing. All-new tables; reuses existing invoicing.
"""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import DialysisMachine, DialysisSession, DialysisLab, Patient, Invoice
from ..core.security import (cur_user, can, login_required, log, branch_scope, can_see)
from ..core.helpers import today
from ..core.ui import page
from ..core.crud import register, pill

bp = Blueprint('dialysis', __name__)

ST_PILL = {'Scheduled': 'blue', 'InProgress': 'amber', 'Completed': 'green',
           'Cancelled': 'grey', 'Missed': 'red'}


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


def _opt_machines():
    return [('', '— machine —')] + [
        (m.id, m.name) for m in branch_scope(DialysisMachine.query.filter_by(active=True), DialysisMachine).order_by(DialysisMachine.name).all()]


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ==================================================================== board
def dia_board():
    """Dialysis board — App Launcher (mod='dialysis')."""
    sessions = branch_scope(DialysisSession.query, DialysisSession).order_by(
        DialysisSession.status == 'Completed', DialysisSession.scheduled_at.desc()).limit(400).all()
    machines = branch_scope(DialysisMachine.query.filter_by(active=True), DialysisMachine).all()

    def kpi(n, label, ac):
        return f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div><div class='v'>{n}</div><div class='s'></div></div>"
    kpis = ("<div class='kpis'>"
            + kpi(sum(1 for s in sessions if s.status == 'Scheduled'), 'Scheduled', 'var(--blue)')
            + kpi(sum(1 for s in sessions if s.status == 'InProgress'), 'In progress', 'var(--amber-dk)')
            + kpi(sum(1 for m in machines if m.status == 'Available'), 'Free machines', 'var(--green)')
            + kpi(len(machines), 'Total machines', 'var(--petrol)') + "</div>")

    rows = ''
    for s in sessions:
        rows += (f"<tr><td>{h(s.scheduled_at or '—')}</td>"
                 f"<td><b>{h(s.patient.name if s.patient else '—')}</b></td>"
                 f"<td>{h(s.machine.name if s.machine else '—')}</td>"
                 f"<td>{h(s.access_type or '—')}</td>"
                 f"<td class='num'>{(str(s.uf_achieved)+'L') if s.uf_achieved is not None else '—'}</td>"
                 f"<td><span class='pill {ST_PILL.get(s.status,'grey')}'>{h(s.status)}</span></td>"
                 f"<td class='num'><a class='btn sm primary' href='{url_for('dialysis.session', sid=s.id)}'>Open</a></td></tr>")
    if not rows:
        rows = "<tr><td colspan='7'><div class='empty'><b>No dialysis sessions</b>Schedule one to begin.</div></td></tr>"

    toolbar = (f"<a class='btn' href='{url_for('modules.module', mod='dmachines')}'>🩸 Machines</a> "
               f"<a class='btn primary' href='{url_for('dialysis.schedule')}'>+ Schedule Session</a>")
    body = (kpis + f"""<div class="panel"><div class="ph"><h2>Dialysis · {h(today())}</h2>
      <div class="sp"></div>{toolbar}</div>
      <div class="tw"><table><thead><tr><th>When</th><th>Patient</th><th>Machine</th><th>Access</th>
      <th>UF</th><th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>""")
    return page('Dialysis', body, 'dialysis')


# ================================================================== schedule
@bp.route('/dialysis/schedule', methods=['GET', 'POST'])
@login_required
def schedule():
    if not can('dialysis'):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        s = DialysisSession(
            patient_id=request.form.get('patient_id') or None,
            machine_id=request.form.get('machine_id') or None,
            scheduled_at=(request.form.get('scheduled_at') or '').replace('T', ' ')[:16] or None,
            access_type=request.form.get('access_type'), dialyzer=request.form.get('dialyzer'),
            dry_weight=_fnum(request.form.get('dry_weight')), uf_goal=_fnum(request.form.get('uf_goal')),
            status='Scheduled', created_by=(u.username if u else None),
            branch_id=(u.branch_id if u else None))
        db.session.add(s)
        db.session.commit()
        log(f'Dialysis session #{s.id} scheduled', entity=f'DialysisSession#{s.id}')
        flash('Session scheduled', 'ok')
        return redirect(url_for('dialysis.session', sid=s.id))
    pre_pid = request.args.get('patient', type=int)
    popts = "<option value=''>— patient —</option>" + ''.join(
        f"<option value='{p.id}' {'selected' if pre_pid==p.id else ''}>{h(p.name)} ({h(p.mrn or '')})</option>"
        for p in Patient.query.order_by(Patient.id.desc()).limit(300).all())
    mopts = ''.join(f"<option value='{v}'>{h(lb)}</option>" for v, lb in _opt_machines())
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Patient</label><select name='patient_id'>{popts}</select></div>
      <div class='fld'><label>Machine</label><select name='machine_id'>{mopts}</select></div>
      <div class='fld'><label>Scheduled time</label><input type='datetime-local' name='scheduled_at'></div>
      <div class='fld'><label>Access</label><select name='access_type'><option></option><option>AV Fistula</option><option>AV Graft</option><option>Catheter</option></select></div>
      <div class='fld'><label>Dialyzer</label><input name='dialyzer'></div>
      <div class='fld'><label>Dry weight (kg)</label><input name='dry_weight' type='number' step='0.1'></div>
      <div class='fld'><label>UF goal (L)</label><input name='uf_goal' type='number' step='0.1'></div>
      <div class='fld full'><button class='btn primary'>Schedule</button>
        <a class='btn gh' href="{url_for('modules.module', mod='dialysis')}">Cancel</a></div>
    </form></div></div>"""
    return page('Schedule Dialysis', inner, 'dialysis')


# ==================================================================== session
@bp.route('/dialysis/<int:sid>')
@login_required
def session(sid):
    if not can('dialysis'):
        abort(403)
    s = DialysisSession.query.get_or_404(sid)
    if not can_see(s):
        abort(403)

    def rowline(label, val):
        return f"<div><b>{label}:</b> {h(str(val)) if val not in (None,'') else '—'}</div>"
    grid = (f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:4px 24px;font-size:13px;margin-top:8px'>"
            + rowline('Machine', s.machine.name if s.machine else None)
            + rowline('Access', s.access_type) + rowline('Dialyzer', s.dialyzer)
            + rowline('Dry weight', f'{s.dry_weight} kg' if s.dry_weight else None)
            + rowline('Pre weight', f'{s.pre_weight} kg' if s.pre_weight else None)
            + rowline('Post weight', f'{s.post_weight} kg' if s.post_weight else None)
            + rowline('Pre BP', s.pre_bp) + rowline('Post BP', s.post_bp)
            + rowline('UF goal', f'{s.uf_goal} L' if s.uf_goal else None)
            + rowline('UF achieved', f'{s.uf_achieved} L' if s.uf_achieved is not None else None)
            + rowline('Blood flow', f'{s.blood_flow} ml/min' if s.blood_flow else None)
            + rowline('Duration', f'{s.duration_min} min' if s.duration_min else None)
            + rowline('Heparin', s.heparin) + rowline('Complications', s.complications)
            + "</div>")
    head = (f"<div class='panel'><div class='pad'>"
            f"<b style='font-size:18px'>{h(s.patient.name if s.patient else '—')}</b> "
            f"<span class='pill {ST_PILL.get(s.status,'grey')}'>{h(s.status)}</span> "
            f"<span style='color:var(--muted);font-size:13px'>{h(s.scheduled_at or '')}</span>"
            f"{grid}</div></div>")

    acts = []
    if s.status == 'Scheduled':
        acts.append(f"<a class='btn sm primary' href='{url_for('dialysis.start', sid=s.id)}'>▶ Start</a>")
        acts.append(f"<a class='btn sm gh' style='color:var(--red)' href='{url_for('dialysis.cancel', sid=s.id)}'>Cancel</a>")
    elif s.status == 'InProgress':
        acts.append(f"<a class='btn sm primary' href='{url_for('dialysis.complete', sid=s.id)}'>✓ Complete</a>")
    acts.append(f"<a class='btn sm' href='{url_for('dialysis.lab', sid=s.id)}'>🧪 Add lab</a>")
    if s.invoice_id:
        acts.append(f"<a class='btn sm' href='{url_for('billing.invoice_view', iid=s.invoice_id)}'>🧾 Invoice #{s.invoice_id}</a>")
    else:
        acts.append(f"<a class='btn sm' href='{url_for('dialysis.bill', sid=s.id)}'>🧾 Create bill</a>")
    bar = f"<div style='margin:10px 0;display:flex;gap:6px;flex-wrap:wrap'>{' '.join(acts)}</div>"

    # lab monitoring (Pre vs Post)
    lrows = ''
    for x in s.labs:
        lrows += (f"<tr><td>{h(x.name or '')}</td><td>{h(x.phase or '')}</td>"
                  f"<td>{h(x.value or '')} {h(x.unit or '')}</td></tr>")
    labs_panel = (f"<div class='panel'><div class='ph'><h2>Lab Monitoring</h2></div>"
                  f"<div class='tw'><table><thead><tr><th>Test</th><th>Phase</th><th>Value</th></tr></thead>"
                  f"<tbody>{lrows or '<tr><td colspan=3 style=color:var(--muted)>None recorded</td></tr>'}</tbody></table></div></div>")
    notes_panel = (f"<div class='panel'><div class='pad'><b>Notes:</b><div style='white-space:pre-wrap'>{h(s.notes or '—')}</div></div></div>")

    return page(f'Dialysis · {s.patient.name if s.patient else sid}',
                head + bar + labs_panel + notes_panel, 'dialysis',
                crumbs=[('Dialysis', url_for('modules.module', mod='dialysis')),
                        (s.patient.name if s.patient else f'#{sid}', None)])


@bp.route('/dialysis/<int:sid>/start', methods=['GET', 'POST'])
@login_required
def start(sid):
    if not can('dialysis'):
        abort(403)
    s = DialysisSession.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        s.status = 'InProgress'
        s.started_at = _now()
        s.pre_weight = _fnum(request.form.get('pre_weight'))
        s.pre_bp = request.form.get('pre_bp')
        s.blood_flow = request.form.get('blood_flow') or None
        s.heparin = request.form.get('heparin')
        s.nurse = (u.username if u else None)
        if s.machine:
            s.machine.status = 'InUse'
        db.session.commit()
        log(f'Dialysis #{sid} started', entity=f'DialysisSession#{sid}')
        return redirect(url_for('dialysis.session', sid=sid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Pre weight (kg)</label><input name='pre_weight' type='number' step='0.1'></div>
      <div class='fld'><label>Pre BP</label><input name='pre_bp' placeholder='140/90'></div>
      <div class='fld'><label>Blood flow (ml/min)</label><input name='blood_flow' type='number'></div>
      <div class='fld'><label>Heparin</label><input name='heparin'></div>
      <div class='fld full'><button class='btn primary'>Start session</button>
        <a class='btn gh' href="{url_for('dialysis.session', sid=sid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Start Dialysis', inner, 'dialysis')


@bp.route('/dialysis/<int:sid>/complete', methods=['GET', 'POST'])
@login_required
def complete(sid):
    if not can('dialysis'):
        abort(403)
    s = DialysisSession.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    if request.method == 'POST':
        s.status = 'Completed'
        s.ended_at = _now()
        s.post_weight = _fnum(request.form.get('post_weight'))
        s.post_bp = request.form.get('post_bp')
        s.uf_achieved = _fnum(request.form.get('uf_achieved'))
        s.duration_min = request.form.get('duration_min') or None
        s.complications = request.form.get('complications')
        s.notes = request.form.get('notes')
        if s.machine:
            s.machine.status = 'Available'
        db.session.commit()
        log(f'Dialysis #{sid} completed', entity=f'DialysisSession#{sid}')
        flash('Session completed', 'ok')
        return redirect(url_for('dialysis.session', sid=sid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Post weight (kg)</label><input name='post_weight' type='number' step='0.1'></div>
      <div class='fld'><label>Post BP</label><input name='post_bp' placeholder='130/80'></div>
      <div class='fld'><label>UF achieved (L)</label><input name='uf_achieved' type='number' step='0.1'></div>
      <div class='fld'><label>Duration (min)</label><input name='duration_min' type='number'></div>
      <div class='fld full'><label>Complications</label><input name='complications'></div>
      <div class='fld full'><label>Notes</label><textarea name='notes' rows='3'></textarea></div>
      <div class='fld full'><button class='btn primary'>Complete session</button>
        <a class='btn gh' href="{url_for('dialysis.session', sid=sid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Complete Dialysis', inner, 'dialysis')


@bp.route('/dialysis/<int:sid>/lab', methods=['GET', 'POST'])
@login_required
def lab(sid):
    if not can('dialysis'):
        abort(403)
    s = DialysisSession.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if name:
            db.session.add(DialysisLab(session_id=s.id, phase=request.form.get('phase') or 'Pre',
                                       name=name, value=request.form.get('value'),
                                       unit=request.form.get('unit')))
            db.session.commit()
            log(f'Dialysis #{sid} lab recorded', entity=f'DialysisSession#{sid}')
        return redirect(url_for('dialysis.session', sid=sid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Phase</label><select name='phase'><option>Pre</option><option>Post</option></select></div>
      <div class='fld'><label>Test</label><input name='name' placeholder='Hb / K+ / Urea / Creatinine'></div>
      <div class='fld'><label>Value</label><input name='value'></div>
      <div class='fld'><label>Unit</label><input name='unit'></div>
      <div class='fld full'><button class='btn primary'>Add</button>
        <a class='btn gh' href="{url_for('dialysis.session', sid=sid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Add Lab', inner, 'dialysis')


@bp.route('/dialysis/<int:sid>/cancel')
@login_required
def cancel(sid):
    if not can('dialysis'):
        abort(403)
    s = DialysisSession.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    if s.status == 'Scheduled':
        s.status = 'Cancelled'
        db.session.commit()
        log(f'Dialysis #{sid} cancelled', entity=f'DialysisSession#{sid}')
    return redirect(url_for('modules.module', mod='dialysis'))


@bp.route('/dialysis/<int:sid>/bill')
@login_required
def bill(sid):
    if not can('dialysis'):
        abort(403)
    s = DialysisSession.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    if s.invoice_id:
        return redirect(url_for('billing.invoice_view', iid=s.invoice_id))
    if not s.patient_id:
        flash('Link a registered patient before billing.', 'error')
        return redirect(url_for('dialysis.session', sid=sid))
    u = cur_user()
    inv = Invoice(patient_id=s.patient_id, date=today(), branch_id=(u.branch_id if u else None))
    db.session.add(inv)
    db.session.commit()
    s.invoice_id = inv.id
    db.session.commit()
    log(f'Dialysis #{sid} invoice #{inv.id}', entity=f'DialysisSession#{sid}')
    flash('Invoice created — add the dialysis session charge', 'ok')
    return redirect(url_for('billing.invoice_view', iid=inv.id))


# ==================================================== machine CRUD (REG)
register('dmachines', DialysisMachine, 'Dialysis Machines',
         columns=[('Name', lambda o: f"<b>{h(o.name)}</b>"),
                  ('Status', lambda o: pill(o.status or 'Available',
                                            'green' if o.status == 'Available' else ('amber' if o.status == 'InUse' else 'grey'))),
                  ('Active', lambda o: pill('Active' if o.active in (True, None) else 'Inactive',
                                            'green' if o.active in (True, None) else 'grey'))],
         fields=[dict(name='name', label='Machine Name (e.g. HD-1)', required=True),
                 dict(name='status', label='Status', type='select',
                      options=[(s, s) for s in ('Available', 'InUse', 'Maintenance')]),
                 dict(name='active', label='Active', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: DialysisMachine.query.order_by(DialysisMachine.name), search=['name'])
