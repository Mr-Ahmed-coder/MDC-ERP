"""Emergency Department  (Phase 7, v8.0).

Triage → treatment → disposition tracking for walk-in / ambulance / referral
arrivals, with serial vitals, clinical notes, observation, admission/discharge/
referral, and one-click emergency billing that reuses the existing invoicing.
All-new tables — no changes to existing models.
"""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import EDVisit, EDVital, EDNote, Patient, Invoice
from ..core.security import (cur_user, can, login_required, log, branch_scope, can_see)
from ..core.helpers import today
from ..core.ui import page
from ..core.notify import notify

bp = Blueprint('ed', __name__)

TRIAGE = {                                   # level: (name, colour)
    1: ('Resuscitation', 'red'), 2: ('Emergency', 'amber'), 3: ('Urgent', 'amber'),
    4: ('Less urgent', 'green'), 5: ('Non-urgent', 'teal')}
TRIAGE_HEX = {1: '#e53935', 2: '#fb8c00', 3: '#fdd835', 4: '#43a047', 5: '#26a69a'}
ACTIVE = ('Waiting', 'InTreatment', 'Observation')
ST_PILL = {'Waiting': 'amber', 'InTreatment': 'blue', 'Observation': 'petrol',
           'Admitted': 'teal', 'Discharged': 'green', 'Referred': 'grey',
           'LAMA': 'grey', 'Deceased': 'grey'}


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


def _mins_since(ts):
    try:
        a = dt.datetime.strptime((ts or '')[:16], '%Y-%m-%d %H:%M')
        return int((dt.datetime.now() - a).total_seconds() // 60)
    except Exception:
        return None


def _dur(mins):
    if mins is None:
        return '—'
    return f'{mins}m' if mins < 60 else f'{mins//60}h {mins%60}m'


def _triage_pill(level):
    if not level:
        return "<span class='pill grey'>untriaged</span>"
    name, col = TRIAGE.get(level, ('?', 'grey'))
    return f"<span class='pill {col}'>L{level} · {name}</span>"


# ==================================================================== board
def ed_board():
    """ED tracking board — App Launcher (mod='ed')."""
    show_all = request.args.get('all') == '1'
    q = branch_scope(EDVisit.query, EDVisit).order_by(
        EDVisit.triage_level.is_(None), EDVisit.triage_level, EDVisit.id.desc())
    visits = q.limit(500).all()
    if not show_all:
        visits = [v for v in visits if v.status in ACTIVE]

    waiting = [v for v in visits if v.status == 'Waiting']
    treat = [v for v in visits if v.status == 'InTreatment']
    obs = [v for v in visits if v.status == 'Observation']

    def kpi(n, label, ac):
        return (f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div>"
                f"<div class='v'>{n}</div><div class='s'>patients</div></div>")
    resus = sum(1 for v in waiting if v.triage_level == 1)
    kpis = ("<div class='kpis'>"
            + kpi(len(waiting), 'Waiting', 'var(--amber-dk)')
            + kpi(len(treat), 'In treatment', 'var(--blue)')
            + kpi(len(obs), 'Observation', 'var(--petrol)')
            + kpi(resus, 'Resuscitation', 'var(--red)') + "</div>")

    rows = ''
    for v in visits:
        wait = _dur(_mins_since(v.arrival_at))
        acts = (f"<a class='btn sm primary' href='{url_for('ed.visit', vid=v.id)}'>Open</a>")
        rows += (f"<tr style='border-left:4px solid {TRIAGE_HEX.get(v.triage_level, '#cbd5e1')}'>"
                 f"<td>{_triage_pill(v.triage_level)}</td>"
                 f"<td><b>{h(v.display_name)}</b><br><span style='color:var(--muted);font-size:12px'>{h(v.chief_complaint or '')}</span></td>"
                 f"<td>{h(v.mode or '—')}</td>"
                 f"<td>{h(v.attending or '—')}</td>"
                 f"<td>{h(v.bed or '—')}</td>"
                 f"<td>{wait}</td>"
                 f"<td><span class='pill {ST_PILL.get(v.status,'grey')}'>{h(v.status)}</span></td>"
                 f"<td class='num'>{acts}</td></tr>")
    if not rows:
        rows = ("<tr><td colspan='8'><div class='empty'><b>No active ED patients</b>"
                "Register an arrival to begin.</div></td></tr>")

    toggle = (f"<a class='btn' href='{url_for('modules.module', mod='ed')}'>Active only</a>"
              if show_all else f"<a class='btn' href='{url_for('modules.module', mod='ed', all='1')}'>Show all today</a>")
    body = (kpis + f"""<div class="panel"><div class="ph"><h2>Emergency Department · {h(today())}</h2>
      <span class="so">Sorted by triage priority · time = since arrival</span><div class="sp"></div>
      {toggle} <a class="btn" href="{url_for('modules.module', mod='ed')}">↻</a>
      <a class="btn primary" href="{url_for('ed.new')}">+ New Arrival</a></div>
      <div class="tw"><table><thead><tr><th>Triage</th><th>Patient / Complaint</th><th>Arrival</th>
      <th>Attending</th><th>Bed</th><th>In ED</th><th>Status</th><th></th></tr></thead>
      <tbody>{rows}</tbody></table></div></div>""")
    return page('Emergency', body, 'ed')


# ==================================================================== arrival
@bp.route('/ed/new', methods=['GET', 'POST'])
@login_required
def new():
    if not can('ed'):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        lvl = request.form.get('triage_level')
        v = EDVisit(
            patient_id=request.form.get('patient_id') or None,
            unknown_name=(request.form.get('unknown_name') or '').strip() or None,
            age=request.form.get('age'), gender=request.form.get('gender'),
            mode=request.form.get('mode') or 'Walk-in',
            chief_complaint=request.form.get('chief_complaint'),
            triage_level=int(lvl) if lvl else None,
            triage_by=(u.username if u else None), triage_at=_now(),
            status='Waiting', attending=request.form.get('attending') or None,
            bp=request.form.get('bp'), pulse=request.form.get('pulse') or None,
            temp_c=request.form.get('temp_c') or None, spo2=request.form.get('spo2') or None,
            resp=request.form.get('resp') or None, gcs=request.form.get('gcs') or None,
            pain=request.form.get('pain') or None,
            created_by=(u.username if u else None),
            branch_id=(u.branch_id if u else None))
        db.session.add(v)
        db.session.commit()
        log(f'ED arrival #{v.id} · triage L{v.triage_level or "?"}', entity=f'EDVisit#{v.id}')
        if v.triage_level == 1:
            notify(f'🔴 RESUSCITATION in ED — {v.display_name}', url_for('ed.visit', vid=v.id),
                   role=['doctor', 'nurse'])
        flash('Arrival registered', 'ok')
        return redirect(url_for('ed.visit', vid=v.id))

    popts = "<option value=''>— unknown / walk-in —</option>" + ''.join(
        f"<option value='{p.id}'>{h(p.name)} ({h(p.mrn or '')})</option>"
        for p in Patient.query.order_by(Patient.id.desc()).limit(300).all())
    topts = ''.join(f"<option value='{lv}'>L{lv} · {nm}</option>" for lv, (nm, _c) in TRIAGE.items())
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Registered patient</label><select name='patient_id'>{popts}</select></div>
      <div class='fld'><label>…or unknown name</label><input name='unknown_name' placeholder='e.g. Unknown male'></div>
      <div class='fld'><label>Age</label><input name='age'></div>
      <div class='fld'><label>Gender</label><select name='gender'><option></option><option>Male</option><option>Female</option></select></div>
      <div class='fld'><label>Mode of arrival</label><select name='mode'><option>Walk-in</option><option>Ambulance</option><option>Referral</option></select></div>
      <div class='fld'><label>Triage level</label><select name='triage_level' required><option value=''>— select —</option>{topts}</select></div>
      <div class='fld full'><label>Chief complaint</label><input name='chief_complaint'></div>
      <div class='fld'><label>BP</label><input name='bp' placeholder='120/80'></div>
      <div class='fld'><label>Pulse</label><input name='pulse' type='number'></div>
      <div class='fld'><label>Temp °C</label><input name='temp_c' type='number' step='0.1'></div>
      <div class='fld'><label>SpO₂ %</label><input name='spo2' type='number'></div>
      <div class='fld'><label>Resp rate</label><input name='resp' type='number'></div>
      <div class='fld'><label>GCS</label><input name='gcs' type='number'></div>
      <div class='fld'><label>Pain (0–10)</label><input name='pain' type='number'></div>
      <div class='fld'><label>Attending</label><input name='attending'></div>
      <div class='fld full'><button class='btn primary'>Register &amp; triage</button>
        <a class='btn gh' href="{url_for('modules.module', mod='ed')}">Cancel</a></div>
    </form></div></div>"""
    return page('New ED Arrival', inner, 'ed')


# ==================================================================== visit
@bp.route('/ed/<int:vid>')
@login_required
def visit(vid):
    if not can('ed'):
        abort(403)
    v = EDVisit.query.get_or_404(vid)
    if not can_see(v):
        abort(403)

    vitset = (f"BP {v.bp or '—'} · HR {v.pulse or '—'} · T {v.temp_c or '—'} · "
              f"SpO₂ {v.spo2 or '—'} · RR {v.resp or '—'} · GCS {v.gcs or '—'} · Pain {v.pain if v.pain is not None else '—'}")
    head = (f"<div class='panel'><div class='pad'>"
            f"<div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px'>"
            f"<div><b style='font-size:18px'>{h(v.display_name)}</b> "
            f"{_triage_pill(v.triage_level)} <span class='pill {ST_PILL.get(v.status,'grey')}'>{h(v.status)}</span><br>"
            f"<span style='color:var(--muted);font-size:13px'>{h(v.gender or '')} {h(v.age or '')} · "
            f"{h(v.mode or '')} · arrived {h(v.arrival_at or '')} ({_dur(_mins_since(v.arrival_at))} ago)</span></div>"
            f"<div style='text-align:right;font-size:13px'>Attending: <b>{h(v.attending or '—')}</b><br>Bed: <b>{h(v.bed or '—')}</b></div>"
            f"</div>"
            f"<div style='margin-top:8px'><b>Complaint:</b> {h(v.chief_complaint or '—')}</div>"
            f"<div style='margin-top:4px;font-size:13px'><b>Triage vitals:</b> {h(vitset)}</div>"
            + (f"<div style='margin-top:4px;color:var(--red)'><b>Disposition:</b> {h(v.disposition)} — {h(v.disposition_note or '')}</div>" if v.disposition else '')
            + "</div></div>")

    # action bar
    a = []
    if v.status in ACTIVE:
        if v.status == 'Waiting':
            a.append(f"<a class='btn primary' href='{url_for('ed.act', vid=v.id, do='treat')}'>▶ Start treatment</a>")
        if v.status != 'Observation':
            a.append(f"<a class='btn' href='{url_for('ed.act', vid=v.id, do='observe')}'>👁 Observation</a>")
        a.append(f"<a class='btn' href='{url_for('ed.assign', vid=v.id)}'>👤 Assign / Bed</a>")
        a.append(f"<a class='btn' href='{url_for('ed.disposition', vid=v.id)}'>➜ Disposition</a>")
    if v.invoice_id:
        a.append(f"<a class='btn' href='{url_for('billing.invoice_view', iid=v.invoice_id)}'>🧾 Invoice #{v.invoice_id}</a>")
    else:
        a.append(f"<a class='btn' href='{url_for('ed.bill', vid=v.id)}'>🧾 Create bill</a>")
    bar = f"<div style='margin:10px 0;display:flex;gap:6px;flex-wrap:wrap'>{' '.join(a)}</div>"

    # vitals timeline
    vrows = (f"<tr><td>{h(v.arrival_at)}</td><td>{h(v.bp or '—')}</td><td>{v.pulse or '—'}</td>"
             f"<td>{v.temp_c or '—'}</td><td>{v.spo2 or '—'}</td><td>{v.resp or '—'}</td>"
             f"<td>{v.gcs or '—'}</td><td>{v.pain if v.pain is not None else '—'}</td><td>triage</td></tr>")
    for x in v.vitals:
        vrows += (f"<tr><td>{h(x.at)}</td><td>{h(x.bp or '—')}</td><td>{x.pulse or '—'}</td>"
                  f"<td>{x.temp_c or '—'}</td><td>{x.spo2 or '—'}</td><td>{x.resp or '—'}</td>"
                  f"<td>{x.gcs or '—'}</td><td>{x.pain if x.pain is not None else '—'}</td><td>{h(x.by or '')}</td></tr>")
    vitals_panel = (f"<div class='panel'><div class='ph'><h2>Vitals</h2><div class='sp'></div>"
                    f"<a class='btn sm primary' href='{url_for('ed.add_vitals', vid=v.id)}'>+ Vitals</a></div>"
                    f"<div class='tw'><table><thead><tr><th>Time</th><th>BP</th><th>HR</th><th>Temp</th>"
                    f"<th>SpO₂</th><th>RR</th><th>GCS</th><th>Pain</th><th>By</th></tr></thead><tbody>{vrows}</tbody></table></div></div>")

    # notes
    nrows = ''
    for n in v.notes:
        nrows += (f"<div style='border-bottom:1px solid var(--line);padding:6px 0'>"
                  f"<span class='pill grey'>{h(n.category)}</span> "
                  f"<span style='color:var(--muted);font-size:12px'>{h(n.at)} · {h(n.author or '')}</span>"
                  f"<div style='white-space:pre-wrap'>{h(n.text or '')}</div></div>")
    notes_panel = (f"<div class='panel'><div class='ph'><h2>Notes</h2><div class='sp'></div>"
                   f"<a class='btn sm primary' href='{url_for('ed.add_note', vid=v.id)}'>+ Note</a></div>"
                   f"<div class='pad'>{nrows or '<span style=color:var(--muted)>No notes yet</span>'}</div></div>")

    return page(f'ED · {v.display_name}', head + bar + vitals_panel + notes_panel, 'ed',
                crumbs=[('Emergency', url_for('modules.module', mod='ed')), (v.display_name, None)])


@bp.route('/ed/<int:vid>/vitals', methods=['GET', 'POST'])
@login_required
def add_vitals(vid):
    if not can('ed'):
        abort(403)
    v = EDVisit.query.get_or_404(vid)
    if not can_see(v):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        db.session.add(EDVital(
            visit_id=v.id, bp=request.form.get('bp'), pulse=request.form.get('pulse') or None,
            temp_c=request.form.get('temp_c') or None, spo2=request.form.get('spo2') or None,
            resp=request.form.get('resp') or None, gcs=request.form.get('gcs') or None,
            pain=request.form.get('pain') or None, by=(u.username if u else None)))
        db.session.commit()
        log(f'ED #{vid} vitals recorded', entity=f'EDVisit#{vid}')
        return redirect(url_for('ed.visit', vid=vid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>BP</label><input name='bp' placeholder='120/80'></div>
      <div class='fld'><label>Pulse</label><input name='pulse' type='number'></div>
      <div class='fld'><label>Temp °C</label><input name='temp_c' type='number' step='0.1'></div>
      <div class='fld'><label>SpO₂ %</label><input name='spo2' type='number'></div>
      <div class='fld'><label>Resp rate</label><input name='resp' type='number'></div>
      <div class='fld'><label>GCS</label><input name='gcs' type='number'></div>
      <div class='fld'><label>Pain (0–10)</label><input name='pain' type='number'></div>
      <div class='fld full'><button class='btn primary'>Save vitals</button>
        <a class='btn gh' href="{url_for('ed.visit', vid=vid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Record Vitals', inner, 'ed')


@bp.route('/ed/<int:vid>/note', methods=['GET', 'POST'])
@login_required
def add_note(vid):
    if not can('ed'):
        abort(403)
    v = EDVisit.query.get_or_404(vid)
    if not can_see(v):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        txt = (request.form.get('text') or '').strip()
        if txt:
            db.session.add(EDNote(visit_id=v.id, category=request.form.get('category') or 'Doctor',
                                  author=(u.username if u else None), text=txt))
            db.session.commit()
            log(f'ED #{vid} note added', entity=f'EDVisit#{vid}')
        return redirect(url_for('ed.visit', vid=vid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Type</label><select name='category'><option>Doctor</option><option>Nursing</option><option>Procedure</option></select></div>
      <div class='fld full'><label>Note</label><textarea name='text' rows='5'></textarea></div>
      <div class='fld full'><button class='btn primary'>Add note</button>
        <a class='btn gh' href="{url_for('ed.visit', vid=vid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Add Note', inner, 'ed')


@bp.route('/ed/<int:vid>/assign', methods=['GET', 'POST'])
@login_required
def assign(vid):
    if not can('ed'):
        abort(403)
    v = EDVisit.query.get_or_404(vid)
    if not can_see(v):
        abort(403)
    if request.method == 'POST':
        v.attending = request.form.get('attending') or v.attending
        v.bed = request.form.get('bed') or v.bed
        db.session.commit()
        log(f'ED #{vid} assigned {v.attending}/{v.bed}', entity=f'EDVisit#{vid}')
        return redirect(url_for('ed.visit', vid=vid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Attending clinician</label><input name='attending' value="{h(v.attending or '')}"></div>
      <div class='fld'><label>Bed / bay</label><input name='bed' value="{h(v.bed or '')}"></div>
      <div class='fld full'><button class='btn primary'>Save</button>
        <a class='btn gh' href="{url_for('ed.visit', vid=vid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Assign', inner, 'ed')


@bp.route('/ed/<int:vid>/act/<do>')
@login_required
def act(vid, do):
    if not can('ed'):
        abort(403)
    v = EDVisit.query.get_or_404(vid)
    if not can_see(v):
        abort(403)
    if do == 'treat':
        v.status = 'InTreatment'
    elif do == 'observe':
        v.status = 'Observation'
    db.session.commit()
    log(f'ED #{vid} → {v.status}', entity=f'EDVisit#{vid}')
    return redirect(url_for('ed.visit', vid=vid))


@bp.route('/ed/<int:vid>/disposition', methods=['GET', 'POST'])
@login_required
def disposition(vid):
    if not can('ed'):
        abort(403)
    v = EDVisit.query.get_or_404(vid)
    if not can_see(v):
        abort(403)
    if request.method == 'POST':
        disp = request.form.get('disposition') or 'Discharged'
        v.disposition = disp
        v.disposition_note = request.form.get('note')
        v.disposition_at = _now()
        v.status = {'Admit': 'Admitted', 'Discharge': 'Discharged', 'Refer': 'Referred',
                    'LAMA': 'LAMA', 'Death': 'Deceased'}.get(disp, disp)
        db.session.commit()
        log(f'ED #{vid} disposition {v.status}', entity=f'EDVisit#{vid}')
        flash(f'Patient {v.status.lower()}', 'ok')
        if v.status == 'Admitted':
            return redirect(url_for('ipd.admit', ed=v.id))
        return redirect(url_for('modules.module', mod='ed'))
    opts = ''.join(f"<option value='{k}'>{lbl}</option>" for k, lbl in
                   [('Discharge', 'Discharge home'), ('Admit', 'Admit (inpatient)'),
                    ('Refer', 'Refer out'), ('LAMA', 'Left against medical advice'),
                    ('Death', 'Deceased')])
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Disposition</label><select name='disposition'>{opts}</select></div>
      <div class='fld full'><label>Note</label><textarea name='note' rows='3'></textarea></div>
      <div class='fld full'><button class='btn primary'>Confirm disposition</button>
        <a class='btn gh' href="{url_for('ed.visit', vid=vid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Disposition', inner, 'ed')


@bp.route('/ed/<int:vid>/bill')
@login_required
def bill(vid):
    if not can('ed'):
        abort(403)
    v = EDVisit.query.get_or_404(vid)
    if not can_see(v):
        abort(403)
    if v.invoice_id:
        return redirect(url_for('billing.invoice_view', iid=v.invoice_id))
    if not v.patient_id:
        flash('Link a registered patient before billing (unknown patient has no account).', 'error')
        return redirect(url_for('ed.visit', vid=vid))
    u = cur_user()
    inv = Invoice(patient_id=v.patient_id, date=today(),
                  branch_id=(u.branch_id if u else None))
    db.session.add(inv)
    db.session.commit()
    v.invoice_id = inv.id
    db.session.commit()
    log(f'ED #{vid} invoice #{inv.id} created', entity=f'EDVisit#{vid}')
    flash('Invoice created — add emergency services & charges', 'ok')
    return redirect(url_for('billing.invoice_view', iid=inv.id))
