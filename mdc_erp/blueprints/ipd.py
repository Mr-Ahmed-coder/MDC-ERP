"""Inpatient Department (IPD)  (Phase 8, v8.0).

Ward & bed management, admission (incl. hand-off from the ED), nursing/progress
notes, medication administration (MAR), bed transfer, discharge, and inpatient
billing with automatic bed charges. All-new tables; picks up ED 'Admit'
dispositions. Reuses existing invoicing/accounting.
"""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import (Ward, Bed, Admission, IPDNote, MedAdmin, BedTransfer,
                      Patient, Invoice, InvoiceItem, EDVisit)
from ..core.security import (cur_user, can, login_required, log, branch_scope, can_see)
from ..core.helpers import money, today
from ..core.ui import page
from ..core.crud import register, pill

bp = Blueprint('ipd', __name__)

ST_PILL = {'Admitted': 'blue', 'Discharged': 'green'}


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


def _opt_wards():
    return [('', '— ward —')] + [(w.id, w.name) for w in
                                 branch_scope(Ward.query.filter_by(active=True), Ward).order_by(Ward.name).all()]


def _avail_beds(ward_id=None, include=None):
    q = Bed.query.filter_by(active=True)
    beds = q.all()
    out = []
    for b in beds:
        if b.status == 'Available' or b.id == include:
            if not ward_id or b.ward_id == int(ward_id):
                out.append(b)
    return out


# ==================================================================== board
def ipd_board():
    """Inpatient board — App Launcher (mod='ipd')."""
    admits = branch_scope(Admission.query, Admission).filter_by(status='Admitted').order_by(
        Admission.id.desc()).all()

    # bed occupancy summary
    beds = Bed.query.filter_by(active=True).all()
    occ = sum(1 for b in beds if b.status == 'Occupied')
    free = sum(1 for b in beds if b.status == 'Available')

    def kpi(n, label, ac):
        return f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div><div class='v'>{n}</div><div class='s'></div></div>"
    kpis = ("<div class='kpis'>"
            + kpi(len(admits), 'Inpatients', 'var(--blue)')
            + kpi(free, 'Free beds', 'var(--green)')
            + kpi(occ, 'Occupied beds', 'var(--amber-dk)')
            + kpi(len(beds), 'Total beds', 'var(--petrol)') + "</div>")

    rows = ''
    for a in admits:
        bed = f"{a.ward.name if a.ward else '—'} / {a.bed.label if a.bed else '—'}"
        rows += (f"<tr><td><b>{h(a.patient.name if a.patient else '—')}</b></td>"
                 f"<td>{h(bed)}</td><td>{h(a.admitting_doctor or a.attending or '—')}</td>"
                 f"<td>{h(a.diagnosis or '—')}</td>"
                 f"<td>{h(a.admitted_at or '')}</td><td class='num'>{a.days}</td>"
                 f"<td class='num'><a class='btn sm primary' href='{url_for('ipd.admission', aid=a.id)}'>Open</a></td></tr>")
    if not rows:
        rows = "<tr><td colspan='7'><div class='empty'><b>No current inpatients</b>Admit a patient to begin.</div></td></tr>"

    toolbar = (f"<a class='btn' href='{url_for('modules.module', mod='wards')}'>🏥 Wards</a> "
               f"<a class='btn' href='{url_for('modules.module', mod='beds')}'>🛏 Beds</a> "
               f"<a class='btn primary' href='{url_for('ipd.admit')}'>+ Admit Patient</a>")
    body = (kpis + f"""<div class="panel"><div class="ph"><h2>Inpatients · {h(today())}</h2>
      <div class="sp"></div>{toolbar}</div>
      <div class="tw"><table><thead><tr><th>Patient</th><th>Ward / Bed</th><th>Doctor</th>
      <th>Diagnosis</th><th>Admitted</th><th>Days</th><th></th></tr></thead>
      <tbody>{rows}</tbody></table></div></div>""")
    return page('Inpatient', body, 'ipd')


# ==================================================================== admit
@bp.route('/ipd/admit', methods=['GET', 'POST'])
@login_required
def admit():
    if not can('ipd'):
        abort(403)
    ed_id = request.args.get('ed', type=int)
    ed_visit = db.session.get(EDVisit, ed_id) if ed_id else None
    if request.method == 'POST':
        u = cur_user()
        bed_id = request.form.get('bed_id') or None
        a = Admission(
            patient_id=request.form.get('patient_id') or None,
            ward_id=request.form.get('ward_id') or None, bed_id=bed_id,
            ed_visit_id=request.form.get('ed_visit_id') or None,
            admitting_doctor=request.form.get('admitting_doctor'),
            attending=request.form.get('admitting_doctor'),
            diagnosis=request.form.get('diagnosis'), status='Admitted',
            created_by=(u.username if u else None),
            branch_id=(u.branch_id if u else None))
        db.session.add(a)
        if bed_id:
            bed = db.session.get(Bed, int(bed_id))
            if bed:
                bed.status = 'Occupied'
        db.session.commit()
        log(f'IPD admission #{a.id}', entity=f'Admission#{a.id}')
        flash('Patient admitted', 'ok')
        return redirect(url_for('ipd.admission', aid=a.id))

    # prefill patient from ED hand-off
    pre_pid = ed_visit.patient_id if ed_visit else request.args.get('patient', type=int)
    popts = "<option value=''>— patient —</option>" + ''.join(
        f"<option value='{p.id}' {'selected' if pre_pid==p.id else ''}>{h(p.name)} ({h(p.mrn or '')})</option>"
        for p in Patient.query.order_by(Patient.id.desc()).limit(300).all())
    wopts = ''.join(f"<option value='{v}'>{h(lb)}</option>" for v, lb in _opt_wards())
    bopts = "<option value=''>— bed —</option>" + ''.join(
        f"<option value='{b.id}'>{h(b.ward.name if b.ward else '')} / {h(b.label)} ({money(b.daily_rate or 0)}/day)</option>"
        for b in _avail_beds())
    ed_hidden = f"<input type='hidden' name='ed_visit_id' value='{ed_visit.id}'>" if ed_visit else ''
    ed_note = (f"<div class='panel' style='border-left:3px solid var(--red)'><div class='pad' style='font-size:13px'>"
               f"Admitting from ED: <b>{h(ed_visit.display_name)}</b> — {h(ed_visit.chief_complaint or '')}</div></div>") if ed_visit else ''
    diag = h(ed_visit.chief_complaint) if ed_visit else ''
    inner = f"""
    {ed_note}
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      {ed_hidden}
      <div class='fld'><label>Patient</label><select name='patient_id'>{popts}</select></div>
      <div class='fld'><label>Ward</label><select name='ward_id'>{wopts}</select></div>
      <div class='fld'><label>Bed</label><select name='bed_id'>{bopts}</select></div>
      <div class='fld'><label>Admitting doctor</label><input name='admitting_doctor'></div>
      <div class='fld full'><label>Diagnosis / reason</label><input name='diagnosis' value="{diag}"></div>
      <div class='fld full'><button class='btn primary'>Admit</button>
        <a class='btn gh' href="{url_for('modules.module', mod='ipd')}">Cancel</a></div>
    </form>
    <div style='font-size:12px;color:var(--muted);margin-top:6px'>Only available beds are listed. Selecting a bed marks it occupied.</div>
    </div></div>"""
    return page('Admit Patient', inner, 'ipd')


# ================================================================== admission
@bp.route('/ipd/<int:aid>')
@login_required
def admission(aid):
    if not can('ipd'):
        abort(403)
    a = Admission.query.get_or_404(aid)
    if not can_see(a):
        abort(403)
    bed = f"{a.ward.name if a.ward else '—'} / {a.bed.label if a.bed else '—'}"
    head = (f"<div class='panel'><div class='pad'>"
            f"<div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px'>"
            f"<div><b style='font-size:18px'>{h(a.patient.name if a.patient else '—')}</b> "
            f"<span class='pill {ST_PILL.get(a.status,'grey')}'>{h(a.status)}</span><br>"
            f"<span style='color:var(--muted);font-size:13px'>{h(bed)} · admitted {h(a.admitted_at or '')} · day {a.days}</span></div>"
            f"<div style='text-align:right;font-size:13px'>Doctor: <b>{h(a.admitting_doctor or '—')}</b></div></div>"
            f"<div style='margin-top:8px'><b>Diagnosis:</b> {h(a.diagnosis or '—')}</div>"
            + (f"<div style='margin-top:4px;color:var(--green)'><b>Discharged:</b> {h(a.discharge_type or '')} — {h(a.discharge_summary or '')}</div>" if a.status == 'Discharged' else '')
            + "</div></div>")

    acts = []
    if a.status == 'Admitted':
        acts.append(f"<a class='btn sm primary' href='{url_for('ipd.note', aid=a.id)}'>+ Note</a>")
        acts.append(f"<a class='btn sm' href='{url_for('ipd.med', aid=a.id)}'>💊 Medication</a>")
        acts.append(f"<a class='btn sm' href='{url_for('ipd.transfer', aid=a.id)}'>🛏 Transfer bed</a>")
        acts.append(f"<a class='btn sm' href='{url_for('ot.schedule', admission=a.id)}'>🔪 Schedule surgery</a>")
        acts.append(f"<a class='btn sm' href='{url_for('ipd.discharge', aid=a.id)}'>➜ Discharge</a>")
    if a.invoice_id:
        acts.append(f"<a class='btn sm' href='{url_for('billing.invoice_view', iid=a.invoice_id)}'>🧾 Invoice #{a.invoice_id}</a>")
    else:
        acts.append(f"<a class='btn sm' href='{url_for('ipd.bill', aid=a.id)}'>🧾 Create bill</a>")
    bar = f"<div style='margin:10px 0;display:flex;gap:6px;flex-wrap:wrap'>{' '.join(acts)}</div>"

    # notes
    nrows = ''
    for n in a.ipd_notes:
        nrows += (f"<div style='border-bottom:1px solid var(--line);padding:6px 0'>"
                  f"<span class='pill grey'>{h(n.category)}</span> "
                  f"<span style='color:var(--muted);font-size:12px'>{h(n.at)} · {h(n.author or '')}</span>"
                  f"<div style='white-space:pre-wrap'>{h(n.text or '')}</div></div>")
    notes_panel = (f"<div class='panel'><div class='ph'><h2>Notes</h2></div><div class='pad'>"
                   f"{nrows or '<span style=color:var(--muted)>No notes yet</span>'}</div></div>")

    # MAR
    mrows = ''
    for m in a.meds:
        mrows += (f"<tr><td>{h(m.at)}</td><td>{h(m.medicine or '')}</td><td>{h(m.dose or '')}</td>"
                  f"<td>{h(m.route or '')}</td><td>{h(m.given_by or '')}</td><td>{h(m.note or '')}</td></tr>")
    mar_panel = (f"<div class='panel'><div class='ph'><h2>Medication Administration</h2></div>"
                 f"<div class='tw'><table><thead><tr><th>Time</th><th>Drug</th><th>Dose</th><th>Route</th>"
                 f"<th>By</th><th>Note</th></tr></thead><tbody>{mrows or '<tr><td colspan=6 style=color:var(--muted)>None recorded</td></tr>'}</tbody></table></div></div>")

    # transfers
    trows = ''
    for t in a.transfers:
        trows += f"<div style='font-size:13px;padding:2px 0'>{h(t.at)} — {h(t.from_bed or '')} → <b>{h(t.to_bed or '')}</b> ({h(t.by or '')}) {h(t.reason or '')}</div>"
    trans_panel = (f"<div class='panel'><div class='pad'><b>Bed transfers:</b><br>{trows or '<span style=color:var(--muted)>None</span>'}</div></div>") if a.transfers else ''

    return page(f'IPD · {a.patient.name if a.patient else aid}',
                head + bar + notes_panel + mar_panel + trans_panel, 'ipd',
                crumbs=[('Inpatient', url_for('modules.module', mod='ipd')),
                        (a.patient.name if a.patient else f'#{aid}', None)])


@bp.route('/ipd/<int:aid>/note', methods=['GET', 'POST'])
@login_required
def note(aid):
    if not can('ipd'):
        abort(403)
    a = Admission.query.get_or_404(aid)
    if not can_see(a):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        txt = (request.form.get('text') or '').strip()
        if txt:
            db.session.add(IPDNote(admission_id=a.id, category=request.form.get('category') or 'Nursing',
                                   author=(u.username if u else None), text=txt))
            db.session.commit()
            log(f'IPD #{aid} note', entity=f'Admission#{aid}')
        return redirect(url_for('ipd.admission', aid=aid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Type</label><select name='category'><option>Nursing</option><option>Doctor</option><option>Vitals</option></select></div>
      <div class='fld full'><label>Note</label><textarea name='text' rows='5'></textarea></div>
      <div class='fld full'><button class='btn primary'>Add note</button>
        <a class='btn gh' href="{url_for('ipd.admission', aid=aid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Add Note', inner, 'ipd')


@bp.route('/ipd/<int:aid>/med', methods=['GET', 'POST'])
@login_required
def med(aid):
    if not can('ipd'):
        abort(403)
    a = Admission.query.get_or_404(aid)
    if not can_see(a):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        drug = (request.form.get('medicine') or '').strip()
        if drug:
            db.session.add(MedAdmin(admission_id=a.id, medicine=drug,
                                    dose=request.form.get('dose'), route=request.form.get('route'),
                                    given_by=(u.username if u else None), note=request.form.get('note')))
            db.session.commit()
            log(f'IPD #{aid} med administered', entity=f'Admission#{aid}')
        return redirect(url_for('ipd.admission', aid=aid))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Drug</label><input name='medicine'></div>
      <div class='fld'><label>Dose</label><input name='dose' placeholder='500 mg'></div>
      <div class='fld'><label>Route</label><select name='route'><option>PO</option><option>IV</option><option>IM</option><option>SC</option><option>PR</option><option>Topical</option></select></div>
      <div class='fld full'><label>Note</label><input name='note'></div>
      <div class='fld full'><button class='btn primary'>Record administration</button>
        <a class='btn gh' href="{url_for('ipd.admission', aid=aid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Medication Administration', inner, 'ipd')


@bp.route('/ipd/<int:aid>/transfer', methods=['GET', 'POST'])
@login_required
def transfer(aid):
    if not can('ipd'):
        abort(403)
    a = Admission.query.get_or_404(aid)
    if not can_see(a):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        new_bed_id = request.form.get('bed_id')
        if new_bed_id:
            old = a.bed
            new = db.session.get(Bed, int(new_bed_id))
            db.session.add(BedTransfer(
                admission_id=a.id,
                from_bed=(f"{old.ward.name}/{old.label}" if old and old.ward else (old.label if old else '')),
                to_bed=(f"{new.ward.name}/{new.label}" if new and new.ward else ''),
                by=(u.username if u else None), reason=request.form.get('reason')))
            if old:
                old.status = 'Available'
            if new:
                new.status = 'Occupied'
                a.bed_id = new.id
                a.ward_id = new.ward_id
            db.session.commit()
            log(f'IPD #{aid} bed transfer', entity=f'Admission#{aid}')
            flash('Bed transferred', 'ok')
        return redirect(url_for('ipd.admission', aid=aid))
    bopts = "<option value=''>— bed —</option>" + ''.join(
        f"<option value='{b.id}'>{h(b.ward.name if b.ward else '')} / {h(b.label)}</option>"
        for b in _avail_beds())
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>New bed</label><select name='bed_id'>{bopts}</select></div>
      <div class='fld full'><label>Reason</label><input name='reason'></div>
      <div class='fld full'><button class='btn primary'>Transfer</button>
        <a class='btn gh' href="{url_for('ipd.admission', aid=aid)}">Cancel</a></div>
    </form></div></div>"""
    return page('Transfer Bed', inner, 'ipd')


@bp.route('/ipd/<int:aid>/discharge', methods=['GET', 'POST'])
@login_required
def discharge(aid):
    if not can('ipd'):
        abort(403)
    a = Admission.query.get_or_404(aid)
    if not can_see(a):
        abort(403)
    if request.method == 'POST':
        a.status = 'Discharged'
        a.discharge_type = request.form.get('discharge_type') or 'Home'
        a.discharge_summary = request.form.get('summary')
        a.discharge_at = _now()
        if a.bed:
            a.bed.status = 'Available'
        db.session.commit()
        log(f'IPD #{aid} discharged ({a.discharge_type})', entity=f'Admission#{aid}')
        flash('Patient discharged, bed freed', 'ok')
        return redirect(url_for('modules.module', mod='ipd'))
    opts = ''.join(f"<option>{t}</option>" for t in ('Home', 'Referred', 'LAMA', 'Deceased'))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Discharge type</label><select name='discharge_type'>{opts}</select></div>
      <div class='fld full'><label>Discharge summary</label><textarea name='summary' rows='4'></textarea></div>
      <div class='fld full'><button class='btn primary'>Confirm discharge</button>
        <a class='btn gh' href="{url_for('ipd.admission', aid=aid)}">Cancel</a></div>
    </form>
    <div style='font-size:12px;color:var(--muted);margin-top:6px'>Discharging frees the bed. Settle the invoice separately.</div>
    </div></div>"""
    return page('Discharge', inner, 'ipd')


@bp.route('/ipd/<int:aid>/bill')
@login_required
def bill(aid):
    if not can('ipd'):
        abort(403)
    a = Admission.query.get_or_404(aid)
    if not can_see(a):
        abort(403)
    if a.invoice_id:
        return redirect(url_for('billing.invoice_view', iid=a.invoice_id))
    if not a.patient_id:
        flash('Link a registered patient before billing.', 'error')
        return redirect(url_for('ipd.admission', aid=aid))
    u = cur_user()
    inv = Invoice(patient_id=a.patient_id, date=today(), branch_id=(u.branch_id if u else None))
    db.session.add(inv)
    db.session.commit()
    # auto-add bed charge (days × daily rate)
    if a.bed and (a.bed.daily_rate or 0) > 0:
        days = a.days
        db.session.add(InvoiceItem(invoice_id=inv.id,
                                   desc=f"Bed charge — {a.ward.name if a.ward else ''} {a.bed.label} ({days} day(s))",
                                   qty=days, price=a.bed.daily_rate))
    a.invoice_id = inv.id
    db.session.commit()
    log(f'IPD #{aid} invoice #{inv.id}', entity=f'Admission#{aid}')
    flash('Invoice created with bed charge — add services & settle', 'ok')
    return redirect(url_for('billing.invoice_view', iid=inv.id))


# ==================================================== ward / bed CRUD (REG)
register('wards', Ward, 'Wards',
         columns=[('Name', lambda o: f"<b>{h(o.name)}</b>"),
                  ('Type', lambda o: pill(o.kind or '—', 'grey')),
                  ('Status', lambda o: pill('Active' if o.active in (True, None) else 'Inactive',
                                            'green' if o.active in (True, None) else 'grey'))],
         fields=[dict(name='name', label='Ward Name', required=True),
                 dict(name='kind', label='Type', type='select',
                      options=[(k, k) for k in ('General', 'Private', 'ICU', 'Maternity', 'Pediatric', 'Isolation')]),
                 dict(name='active', label='Status', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: Ward.query.order_by(Ward.name), search=['name', 'kind'])

register('beds', Bed, 'Beds',
         columns=[('Bed', lambda o: f"<b>{h(o.label)}</b>"),
                  ('Ward', lambda o: h(o.ward.name if o.ward else '—')),
                  ('Rate/day', lambda o: money(o.daily_rate or 0)),
                  ('Status', lambda o: pill(o.status or 'Available',
                                            'green' if o.status == 'Available' else ('amber' if o.status == 'Occupied' else 'grey')))],
         fields=[dict(name='label', label='Bed Label/Number', required=True),
                 dict(name='ward_id', label='Ward', type='select', options_fn=_opt_wards, required=True),
                 dict(name='daily_rate', label='Daily Rate', type='number'),
                 dict(name='status', label='Status', type='select',
                      options=[(s, s) for s in ('Available', 'Occupied', 'Maintenance')]),
                 dict(name='active', label='Active', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True)],
         order=lambda: Bed.query.order_by(Bed.ward_id, Bed.label), search=['label'])
