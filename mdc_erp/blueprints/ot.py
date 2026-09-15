"""Operation Theatre (OT)  (Phase 9, v8.0).

Surgery scheduling, surgeon/anaesthetist assignment, the WHO Surgical Safety
Checklist (Sign-in / Time-out / Sign-out), operative & anaesthesia notes,
instrument/swab safety counts, and OT billing. All-new tables; links to IPD
admissions and reuses existing invoicing.
"""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import (Theatre, Surgery, OTChecklistItem, SurgicalNote, SurgeryItem,
                      Patient, Invoice, Admission)
from ..core.security import (cur_user, can, login_required, log, branch_scope, can_see)
from ..core.helpers import today
from ..core.ui import page
from ..core.crud import register, pill

bp = Blueprint('ot', __name__)

ST_PILL = {'Scheduled': 'blue', 'InProgress': 'amber', 'Completed': 'green', 'Cancelled': 'grey'}

# WHO Surgical Safety Checklist (abbreviated standard items)
WHO_CHECKLIST = {
    'SignIn': ['Patient identity, site, procedure & consent confirmed',
               'Surgical site marked', 'Anaesthesia safety check completed',
               'Pulse oximeter on patient and functioning', 'Known allergy?',
               'Difficult airway / aspiration risk?', 'Risk of >500ml blood loss?'],
    'TimeOut': ['Team members introduced by name and role',
                'Surgeon, anaesthetist & nurse confirm patient/site/procedure',
                'Antibiotic prophylaxis given within last 60 min',
                'Anticipated critical events reviewed', 'Essential imaging displayed'],
    'SignOut': ['Name of procedure recorded', 'Instrument, sponge & needle counts correct',
                'Specimen labelled (incl. patient name)', 'Equipment problems addressed',
                'Key recovery & management concerns reviewed'],
}
PHASE_LABEL = {'SignIn': 'Sign In (before anaesthesia)',
               'TimeOut': 'Time Out (before incision)',
               'SignOut': 'Sign Out (before leaving theatre)'}


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


def _seed_checklist(surgery):
    for phase, items in WHO_CHECKLIST.items():
        for it in items:
            db.session.add(OTChecklistItem(surgery_id=surgery.id, phase=phase, item=it, checked=False))


def _opt_theatres():
    return [('', '— theatre —')] + [
        (t.id, t.name) for t in branch_scope(Theatre.query.filter_by(active=True), Theatre).order_by(Theatre.name).all()]


# ==================================================================== board
def ot_board():
    """Surgery schedule board — App Launcher (mod='ot')."""
    surgeries = branch_scope(Surgery.query, Surgery).order_by(
        Surgery.status == 'Completed', Surgery.status == 'Cancelled',
        Surgery.scheduled_at.desc()).limit(400).all()

    active = [s for s in surgeries if s.status in ('Scheduled', 'InProgress')]

    def kpi(n, label, ac):
        return f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div><div class='v'>{n}</div><div class='s'></div></div>"
    kpis = ("<div class='kpis'>"
            + kpi(sum(1 for s in active if s.status == 'Scheduled'), 'Scheduled', 'var(--blue)')
            + kpi(sum(1 for s in active if s.status == 'InProgress'), 'In progress', 'var(--amber-dk)')
            + kpi(sum(1 for s in active if s.priority == 'Emergency'), 'Emergency', 'var(--red)')
            + kpi(sum(1 for s in surgeries if s.status == 'Completed'), 'Completed', 'var(--green)') + "</div>")

    rows = ''
    for s in surgeries:
        prio = "<span class='pill red'>Emergency</span> " if s.priority == 'Emergency' else ''
        done = sum(1 for c in s.checklist if c.checked)
        tot = len(s.checklist) or len(sum(WHO_CHECKLIST.values(), []))
        rows += (f"<tr><td>{h(s.scheduled_at or '—')}</td>"
                 f"<td><b>{h(s.patient.name if s.patient else '—')}</b></td>"
                 f"<td>{prio}{h(s.procedure or '—')}</td>"
                 f"<td>{h(s.surgeon or '—')}</td><td>{h(s.theatre.name if s.theatre else '—')}</td>"
                 f"<td class='num'>{done}/{tot}</td>"
                 f"<td><span class='pill {ST_PILL.get(s.status,'grey')}'>{h(s.status)}</span></td>"
                 f"<td class='num'><a class='btn sm primary' href='{url_for('ot.surgery', sid=s.id)}'>Open</a></td></tr>")
    if not rows:
        rows = "<tr><td colspan='8'><div class='empty'><b>No surgeries</b>Schedule one to begin.</div></td></tr>"

    toolbar = (f"<a class='btn' href='{url_for('modules.module', mod='theatres')}'>🏥 Theatres</a> "
               f"<a class='btn primary' href='{url_for('ot.schedule')}'>+ Schedule Surgery</a>")
    body = (kpis + f"""<div class="panel"><div class="ph"><h2>Operation Theatre · {h(today())}</h2>
      <div class="sp"></div>{toolbar}</div>
      <div class="tw"><table><thead><tr><th>When</th><th>Patient</th><th>Procedure</th><th>Surgeon</th>
      <th>Theatre</th><th>Checklist</th><th>Status</th><th></th></tr></thead>
      <tbody>{rows}</tbody></table></div></div>""")
    return page('Operation Theatre', body, 'ot')


# ================================================================== schedule
@bp.route('/ot/schedule', methods=['GET', 'POST'])
@login_required
def schedule():
    if not can('ot'):
        abort(403)
    adm_id = request.args.get('admission', type=int)
    adm = db.session.get(Admission, adm_id) if adm_id else None
    if request.method == 'POST':
        u = cur_user()
        s = Surgery(
            patient_id=request.form.get('patient_id') or None,
            admission_id=request.form.get('admission_id') or None,
            theatre_id=request.form.get('theatre_id') or None,
            procedure=request.form.get('procedure'), surgeon=request.form.get('surgeon'),
            assistant=request.form.get('assistant'), anesthetist=request.form.get('anesthetist'),
            anesthesia_type=request.form.get('anesthesia_type'),
            priority=request.form.get('priority') or 'Elective',
            scheduled_at=(request.form.get('scheduled_at') or '').replace('T', ' ')[:16] or None,
            diagnosis=request.form.get('diagnosis'), status='Scheduled',
            created_by=(u.username if u else None), branch_id=(u.branch_id if u else None))
        db.session.add(s)
        db.session.flush()
        _seed_checklist(s)
        db.session.commit()
        log(f'Surgery #{s.id} scheduled', entity=f'Surgery#{s.id}')
        flash('Surgery scheduled', 'ok')
        return redirect(url_for('ot.surgery', sid=s.id))

    pre_pid = adm.patient_id if adm else request.args.get('patient', type=int)
    popts = "<option value=''>— patient —</option>" + ''.join(
        f"<option value='{p.id}' {'selected' if pre_pid==p.id else ''}>{h(p.name)} ({h(p.mrn or '')})</option>"
        for p in Patient.query.order_by(Patient.id.desc()).limit(300).all())
    topts = ''.join(f"<option value='{v}'>{h(lb)}</option>" for v, lb in _opt_theatres())
    adm_hidden = f"<input type='hidden' name='admission_id' value='{adm.id}'>" if adm else ''
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      {adm_hidden}
      <div class='fld'><label>Patient</label><select name='patient_id'>{popts}</select></div>
      <div class='fld'><label>Theatre</label><select name='theatre_id'>{topts}</select></div>
      <div class='fld full'><label>Procedure</label><input name='procedure' required></div>
      <div class='fld'><label>Surgeon</label><input name='surgeon'></div>
      <div class='fld'><label>Assistant</label><input name='assistant'></div>
      <div class='fld'><label>Anaesthetist</label><input name='anesthetist'></div>
      <div class='fld'><label>Anaesthesia</label><select name='anesthesia_type'><option></option><option>GA</option><option>Spinal</option><option>Epidural</option><option>Local</option><option>Sedation</option></select></div>
      <div class='fld'><label>Priority</label><select name='priority'><option>Elective</option><option>Emergency</option></select></div>
      <div class='fld'><label>Scheduled time</label><input type='datetime-local' name='scheduled_at'></div>
      <div class='fld full'><label>Diagnosis</label><input name='diagnosis'></div>
      <div class='fld full'><button class='btn primary'>Schedule</button>
        <a class='btn gh' href="{url_for('modules.module', mod='ot')}">Cancel</a></div>
    </form></div></div>"""
    return page('Schedule Surgery', inner, 'ot')


# ==================================================================== surgery
@bp.route('/ot/<int:sid>')
@login_required
def surgery(sid):
    if not can('ot'):
        abort(403)
    s = Surgery.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    dur = ''
    if s.started_at and s.ended_at:
        try:
            a = dt.datetime.strptime(s.started_at[:16], '%Y-%m-%d %H:%M')
            b = dt.datetime.strptime(s.ended_at[:16], '%Y-%m-%d %H:%M')
            m = int((b - a).total_seconds() // 60)
            dur = f" · duration {m//60}h {m%60}m"
        except Exception:
            pass
    head = (f"<div class='panel'><div class='pad'>"
            f"<div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px'>"
            f"<div><b style='font-size:18px'>{h(s.patient.name if s.patient else '—')}</b> "
            + ("<span class='pill red'>Emergency</span> " if s.priority == 'Emergency' else '')
            + f"<span class='pill {ST_PILL.get(s.status,'grey')}'>{h(s.status)}</span><br>"
            f"<span style='color:var(--muted);font-size:13px'>{h(s.procedure or '')} · "
            f"{h(s.theatre.name if s.theatre else '')} · {h(s.scheduled_at or '')}{dur}</span></div>"
            f"<div style='text-align:right;font-size:13px'>Surgeon: <b>{h(s.surgeon or '—')}</b><br>"
            f"Anaesthetist: {h(s.anesthetist or '—')} ({h(s.anesthesia_type or '—')})</div></div>"
            f"<div style='margin-top:6px'><b>Diagnosis:</b> {h(s.diagnosis or '—')}</div></div></div>")

    acts = []
    if s.status == 'Scheduled':
        acts.append(f"<a class='btn sm primary' href='{url_for('ot.status', sid=s.id, do='start')}'>▶ Start</a>")
        acts.append(f"<a class='btn sm gh' style='color:var(--red)' href='{url_for('ot.status', sid=s.id, do='cancel')}'>Cancel</a>")
    elif s.status == 'InProgress':
        acts.append(f"<a class='btn sm primary' href='{url_for('ot.status', sid=s.id, do='complete')}'>✓ Complete</a>")
    acts.append(f"<a class='btn sm' href='{url_for('ot.note', sid=s.id)}'>+ Note</a>")
    acts.append(f"<a class='btn sm' href='{url_for('ot.item', sid=s.id)}'>🔧 Instruments</a>")
    if s.invoice_id:
        acts.append(f"<a class='btn sm' href='{url_for('billing.invoice_view', iid=s.invoice_id)}'>🧾 Invoice #{s.invoice_id}</a>")
    else:
        acts.append(f"<a class='btn sm' href='{url_for('ot.bill', sid=s.id)}'>🧾 Create bill</a>")
    bar = f"<div style='margin:10px 0;display:flex;gap:6px;flex-wrap:wrap'>{' '.join(acts)}</div>"

    # WHO checklist by phase
    cl = ''
    for phase in ('SignIn', 'TimeOut', 'SignOut'):
        items = [c for c in s.checklist if c.phase == phase]
        lis = ''
        for c in items:
            mark = '✅' if c.checked else '⬜'
            lis += (f"<a href='{url_for('ot.check', sid=s.id, cid=c.id)}' "
                    f"style='display:block;text-decoration:none;color:inherit;padding:3px 0'>"
                    f"{mark} {h(c.item)}"
                    + (f" <span style='color:var(--muted);font-size:11px'>({h(c.by or '')})</span>" if c.checked else '')
                    + "</a>")
        cl += (f"<div class='panel'><div class='pad'><b>{h(PHASE_LABEL[phase])}</b> "
               f"<span class='pill grey'>{sum(1 for c in items if c.checked)}/{len(items)}</span>"
               f"<div style='margin-top:6px;font-size:14px'>{lis}</div></div></div>")

    # notes
    nrows = ''
    for n in s.op_notes:
        nrows += (f"<div style='border-bottom:1px solid var(--line);padding:6px 0'>"
                  f"<span class='pill grey'>{h(n.kind)}</span> "
                  f"<span style='color:var(--muted);font-size:12px'>{h(n.at)} · {h(n.author or '')}</span>"
                  f"<div style='white-space:pre-wrap'>{h(n.text or '')}</div></div>")
    notes_panel = (f"<div class='panel'><div class='ph'><h2>Operative &amp; Anaesthesia Notes</h2></div>"
                   f"<div class='pad'>{nrows or '<span style=color:var(--muted)>No notes yet</span>'}</div></div>")

    # instrument counts
    irows = ''
    for it in s.items:
        mismatch = (it.count_before is not None and it.count_after is not None
                    and it.count_before != it.count_after)
        flag = " <span class='pill red'>COUNT MISMATCH</span>" if mismatch else ''
        irows += (f"<tr><td>{h(it.name or '')}</td><td class='num'>{it.count_before if it.count_before is not None else '—'}</td>"
                  f"<td class='num'>{it.count_after if it.count_after is not None else '—'}{flag}</td><td>{h(it.note or '')}</td></tr>")
    items_panel = (f"<div class='panel'><div class='ph'><h2>Instrument / Swab Counts</h2></div>"
                   f"<div class='tw'><table><thead><tr><th>Item</th><th class='num'>Count in</th>"
                   f"<th class='num'>Count out</th><th>Note</th></tr></thead>"
                   f"<tbody>{irows or '<tr><td colspan=4 style=color:var(--muted)>None recorded</td></tr>'}</tbody></table></div></div>")

    return page(f'Surgery · {s.patient.name if s.patient else sid}',
                head + bar + cl + notes_panel + items_panel, 'ot',
                crumbs=[('Operation Theatre', url_for('modules.module', mod='ot')),
                        (s.patient.name if s.patient else f'#{sid}', None)])


@bp.route('/ot/<int:sid>/check/<int:cid>')
@login_required
def check(sid, cid):
    if not can('ot'):
        abort(403)
    s = Surgery.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    c = db.session.get(OTChecklistItem, cid)
    if c and c.surgery_id == s.id:
        u = cur_user()
        c.checked = not c.checked
        c.by = (u.username if u else None) if c.checked else None
        c.at = _now() if c.checked else None
        db.session.commit()
    return redirect(url_for('ot.surgery', sid=sid) + '#checklist')


@bp.route('/ot/<int:sid>/note', methods=['GET', 'POST'])
@login_required
def note(sid):
    if not can('ot'):
        abort(403)
    s = Surgery.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        txt = (request.form.get('text') or '').strip()
        if txt:
            db.session.add(SurgicalNote(surgery_id=s.id, kind=request.form.get('kind') or 'Operative',
                                        author=(u.username if u else None), text=txt))
            db.session.commit()
            log(f'Surgery #{sid} note', entity=f'Surgery#{sid}')
        return redirect(url_for('ot.surgery', sid=sid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Type</label><select name='kind'><option>Operative</option><option>Anesthesia</option><option>PostOp</option><option>Nursing</option></select></div>
      <div class='fld full'><label>Note</label><textarea name='text' rows='6'></textarea></div>
      <div class='fld full'><button class='btn primary'>Add note</button>
        <a class='btn gh' href="{url_for('ot.surgery', sid=sid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Add Note', inner, 'ot')


@bp.route('/ot/<int:sid>/item', methods=['GET', 'POST'])
@login_required
def item(sid):
    if not can('ot'):
        abort(403)
    s = Surgery.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if name:
            db.session.add(SurgeryItem(
                surgery_id=s.id, name=name,
                count_before=request.form.get('count_before') or None,
                count_after=request.form.get('count_after') or None,
                note=request.form.get('note')))
            db.session.commit()
            log(f'Surgery #{sid} instrument recorded', entity=f'Surgery#{sid}')
        return redirect(url_for('ot.surgery', sid=sid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Item (instrument / swab / gauze)</label><input name='name'></div>
      <div class='fld'><label>Count in</label><input name='count_before' type='number'></div>
      <div class='fld'><label>Count out</label><input name='count_after' type='number'></div>
      <div class='fld full'><label>Note</label><input name='note'></div>
      <div class='fld full'><button class='btn primary'>Record</button>
        <a class='btn gh' href="{url_for('ot.surgery', sid=sid)}">Cancel</a></div>
    </form>
    <div style='font-size:12px;color:var(--muted);margin-top:6px'>A mismatch between count-in and count-out is flagged in red.</div>
    </div></div>"""
    return page('Instrument Count', inner, 'ot')


@bp.route('/ot/<int:sid>/status/<do>')
@login_required
def status(sid, do):
    if not can('ot'):
        abort(403)
    s = Surgery.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    if do == 'start' and s.status == 'Scheduled':
        s.status = 'InProgress'
        s.started_at = _now()
    elif do == 'complete' and s.status == 'InProgress':
        s.status = 'Completed'
        s.ended_at = _now()
    elif do == 'cancel' and s.status == 'Scheduled':
        s.status = 'Cancelled'
    db.session.commit()
    log(f'Surgery #{sid} → {s.status}', entity=f'Surgery#{sid}')
    return redirect(url_for('ot.surgery', sid=sid))


@bp.route('/ot/<int:sid>/bill')
@login_required
def bill(sid):
    if not can('ot'):
        abort(403)
    s = Surgery.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    if s.invoice_id:
        return redirect(url_for('billing.invoice_view', iid=s.invoice_id))
    if not s.patient_id:
        flash('Link a registered patient before billing.', 'error')
        return redirect(url_for('ot.surgery', sid=sid))
    u = cur_user()
    inv = Invoice(patient_id=s.patient_id, date=today(), branch_id=(u.branch_id if u else None))
    db.session.add(inv)
    db.session.commit()
    s.invoice_id = inv.id
    db.session.commit()
    log(f'Surgery #{sid} invoice #{inv.id}', entity=f'Surgery#{sid}')
    flash('Invoice created — add theatre & surgical charges', 'ok')
    return redirect(url_for('billing.invoice_view', iid=inv.id))


# ==================================================== theatre CRUD (REG)
register('theatres', Theatre, 'Operating Theatres',
         columns=[('Name', lambda o: f"<b>{h(o.name)}</b>"),
                  ('Status', lambda o: pill('Active' if o.active in (True, None) else 'Inactive',
                                            'green' if o.active in (True, None) else 'grey'))],
         fields=[dict(name='name', label='Theatre Name (e.g. OT-1)', required=True),
                 dict(name='active', label='Status', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: Theatre.query.order_by(Theatre.name), search=['name'])
