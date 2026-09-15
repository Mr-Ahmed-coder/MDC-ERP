"""Patient chart, printable report and statements."""
from flask import (Blueprint, url_for, abort)
from markupsafe import escape as h
from ..models import *
from ..core.security import (can, login_required, cur_user)
from ..core.helpers import money
from ..core.ui import page, track_view, next_step
from ..core.printing import printable

bp = Blueprint('patients', __name__)

@bp.route('/patient/<int:pid>')
@login_required
def patient_detail(pid):
    if not can('patients'): abort(403)
    p=Patient.query.get_or_404(pid)
    track_view('patient', p.id, f"{p.name} · MRN {p.mrn}", url_for('patients.patient_detail', pid=p.id))
    labs=LabOrder.query.filter_by(patient_id=pid).order_by(LabOrder.id.desc()).all()
    rads=RadOrder.query.filter_by(patient_id=pid).order_by(RadOrder.id.desc()).all()
    invs=Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).all()
    billed=sum(i.total for i in invs); paid=sum(i.paid or 0 for i in invs); bal=billed-paid
    def tbl(title,rows,head):
        return f"<div class='panel'><div class='ph'><h2>{title}</h2></div><div class='tw'><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></div>"
    lab_rows=''.join(f"<tr><td>{h(o.date)}</td><td>{h(o.service.name if o.service else '—')}</td><td><span class='pill {'green' if o.status=='Approved' else 'amber'}'>{h(o.status)}</span></td><td class='num'><a class='btn gh sm' href='{url_for('modules.module',mod='lab')}'>Open</a></td></tr>" for o in labs) or "<tr><td colspan='4' style='color:var(--muted);padding:14px'>No lab orders.</td></tr>"
    rad_rows=''.join(f"<tr><td>{h(o.date)}</td><td>{h(o.modality)} · {h(o.service.name if o.service else '—')}</td><td><span class='pill {'green' if o.status=='Reported' else 'amber'}'>{h(o.status)}</span></td><td class='num'><a class='btn gh sm' href='{url_for('modules.module',mod='radiology')}'>Open</a></td></tr>" for o in rads) or "<tr><td colspan='4' style='color:var(--muted);padding:14px'>No imaging studies.</td></tr>"
    inv_rows=''.join(f"<tr><td><b>INV-{i.id:04d}</b></td><td>{h(i.date)}</td><td class='num'>{money(i.total)}</td><td class='num'>{money(i.paid)}</td><td><span class='pill {'green' if (i.paid or 0)>=i.total and i.total>0 else ('amber' if (i.paid or 0)>0 else 'red')}'>{h(i.status)}</span></td><td class='num'><button class='btn gh sm' data-prev='invoice:{i.id}' title='Quick preview'>👁</button> <a class='btn gh sm' href='{url_for('billing.invoice_view',iid=i.id)}'>Open / Pay</a></td></tr>" for i in invs) or "<tr><td colspan='6' style='color:var(--muted);padding:14px'>No invoices.</td></tr>"
    actions=(f"<div class='o-formbar'><div class='o-formbar-actions'>"
             f"<a class='btn primary' href='{url_for('modules.module_edit',mod='patients',oid=pid)}'>✎ Edit</a>"
             f"<a class='btn' href='{url_for('modules.module_new',mod='consult')}?patient_id={pid}'>+ Consultation</a>"
             f"<a class='btn' href='{url_for('lab.lab_new')}?patient={pid}'>+ Lab Test</a>"
             f"<a class='btn' href='{url_for('rad.rad_new')}?patient={pid}'>+ Radiology</a>"
             f"<a class='btn' href='{url_for('billing.invoice_new')}?patient={pid}'>+ Invoice</a>"
             f"<a class='btn' href='{url_for('ref.referral_new_form')}?patient={pid}'>+ Doctor Request</a>"
             f"<a class='btn ok' href='{url_for('modules.module', mod='payalloc')}?patient={pid}'>💵 Receive Payment</a>"
             f"</div><span style='flex:1'></span><div class='o-formbar-actions'>"
             f"<a class='btn' href='{url_for('modules.module_new',mod='appointments')}?patient_id={pid}'>🕐 Check-in</a>"
             f"<a class='btn' href='{url_for('patients.patient_card',pid=pid)}' target='_blank'>🪪 Card</a>"
             f"<a class='btn' href='{url_for('patients.patient_statement',pid=pid)}' target='_blank'>💳 Statement</a>"
             f"<a class='btn' href='{url_for('patients.patient_report',pid=pid)}' target='_blank'>Report</a>"
             + ((f"<form method='post' action='{url_for('patients.patient_purge',pid=pid)}' style='display:inline' "
                 f"onsubmit=\"var r=prompt('⚠ PERMANENTLY delete this patient AND all their invoices, payments, lab/radiology orders and records? The ledger is reversed. This cannot be undone. Type a reason to confirm:'); if(r===null||r==='')return false; this.reason.value=r; return true\">"
                 f"<input type='hidden' name='reason' value=''>"
                 f"<button class='btn sm' style='color:var(--red)'>🗑 Delete Patient</button></form>")
                if (cur_user() and cur_user().role == 'super_admin') else '')
             + f"</div></div>")
    _ph=f"<img src='{url_for('patients.patient_photo',pid=pid)}' style='width:56px;height:56px;object-fit:cover;border-radius:10px;border:2px solid var(--petrol)'>" if p.photo else ''
    _active = p.active in (True, None)
    _sbar = (f"<div class='o-statusbar'><span class='o-stat {'on' if _active else ''}'>Active</span>"
             f"<span class='o-stat {'' if _active else 'on'}'>Inactive</span></div>")
    def _f(lbl, val): return f"<div class='o-fld'><span class='o-fl'>{lbl}</span><span class='o-fv'>{val}</span></div>"
    _ident = ("<div class='o-fields'>"
              + _f('MRN', h(p.mrn))
              + _f('Gender', h(p.gender or '—'))
              + _f('Age', (f'{p.age} yr' if p.age is not None else '—'))
              + _f('Blood Group', h(p.blood_group or '—'))
              + _f('Phone', h(p.phone or '—'))
              + _f('Insurance', h(p.ins_company or '—'))
              + "</div>")
    _kpis = (f"<div class='o-kpis'>"
             f"<div class='o-kpi'><span>Billed</span><b>{money(billed)}</b></div>"
             f"<div class='o-kpi'><span>Paid</span><b style='color:var(--green)'>{money(paid)}</b></div>"
             f"<div class='o-kpi'><span>Balance</span><b style='color:{'var(--red)' if bal>0 else 'var(--ink)'}'>{money(bal)}</b></div>"
             f"</div>")
    _allerg = (f"<div class='o-alert'>⚠ Allergies: {h(p.allergies[:100])}</div>") if p.allergies else ''
    header=(f"<div class='o-sheet o-record'>{_sbar}"
            f"<div class='o-rec-head'>{_ph}<div><div class='o-rec-title'>{h(p.name)}</div>"
            f"<div class='o-rec-sub'>Patient · MRN {h(p.mrn)}</div></div>{_kpis}</div>"
            f"{_allerg}{_ident}</div>")
    cons=Consultation.query.filter_by(patient_id=pid).order_by(Consultation.id.desc()).all()
    con_rows=''.join(f"<tr><td>{h(c.date)}</td><td>{h(c.doctor or '—')}</td><td>{h((c.diagnosis or '—')[:60])}{' <span class=\"pill blue\">'+h(c.icd_code)+'</span>' if c.icd_code else ''}</td><td class='num'><a class='btn gh sm' href='{url_for('modules.module_edit',mod='consult',oid=c.id)}'>Open</a></td></tr>" for c in cons) or "<tr><td colspan='4' style='color:var(--muted);padding:14px'>No consultations.</td></tr>"
    # ---- rich activity timeline: Registration → Doctor Request → Invoice →
    #      Payment → Lab/Radiology → Report → Print. Each row shows User · Date ·
    #      Time and links to its record. Time/User are enriched from the Audit log.
    from sqlalchemy import or_ as _or
    refs = Referral.query.filter_by(patient_id=pid).order_by(Referral.id.desc()).all()
    _rcs = PayReceipt.query.filter(PayReceipt.invoice_id.in_([i.id for i in invs] or [0])).order_by(PayReceipt.id.desc()).all()

    def _dt_parts(dtobj):
        if dtobj:
            try: return dtobj.strftime('%Y-%m-%d'), dtobj.strftime('%H:%M')
            except Exception: return '', ''
        return '', ''

    _tokens = ([f"INV-{i.id:04d}" for i in invs] + [f"invoice #{i.id}" for i in invs]
               + [f"Lab #{o.id}" for o in labs] + [f"LAB-{o.id:04d}" for o in labs]
               + [f"Rad #{o.id}" for o in rads] + [f"RAD-{o.id:04d}" for o in rads]
               + [f"REF-{r.id:04d}" for r in refs])
    _auds = (Audit.query.filter(_or(*[Audit.action.like(f'%{t}%') for t in _tokens]))
             .order_by(Audit.ts).all()) if _tokens else []

    def _amatch(*needles):
        """Most-recent audit (user, date, time) whose action contains a needle as a
        bounded token (so 'Lab #5' doesn't match 'Lab #50')."""
        best = None
        for a in _auds:
            act = a.action or ''
            for n in needles:
                idx = act.find(n)
                if idx >= 0:
                    nxt = act[idx + len(n): idx + len(n) + 1]
                    if nxt == '' or not nxt.isdigit():
                        best = a
        if best and best.ts:
            return (best.user or '—', best.ts.strftime('%Y-%m-%d'), best.ts.strftime('%H:%M'))
        return None

    ev = []  # (sortkey, icon, cls, title_html, sub, user, date, time)
    def add(date, time, icon, cls, title, sub='', user='—'):
        ev.append((f"{date or '0000-00-00'} {time or '00:00'}", icon, cls, title, sub, user, date, time))

    # Registration
    _rd, _rt = _dt_parts(getattr(p, 'created', None))
    add(_rd, _rt, '🧑', 'blue', f"<a href='{url_for('patients.patient_detail',pid=p.id)}'>Registration — MRN {h(p.mrn)}</a>")
    # Doctor Requests
    for r in refs:
        _d, _t = _dt_parts(getattr(r, 'created', None)); _d = _d or (r.date or '')
        add(_d, _t, '📋', 'blue', f"<a href='{url_for('ref.referral_thread',rid=r.id)}'>Doctor Request REF-{r.id:04d}</a>",
            f"Dr {h(r.doctor_name or '—')}", h(r.doctor_name or '—'))
    # Invoices
    for i in invs:
        m = _amatch(f'INV-{i.id:04d}', f'invoice #{i.id}')
        _u, _d, _t = (m if m else ('—', i.date or '', ''))
        add(_d or (i.date or ''), _t, '🧾', 'amber', f"<a href='{url_for('billing.invoice_view',iid=i.id)}'>Invoice INV-{i.id:04d}</a>",
            f"{money(i.total)} · {h(i.status)}" + (" · 🔒 locked" if getattr(i, 'locked', False) else ''), _u)
    # Payments
    for r in _rcs:
        m = _amatch(f'PAYMENT INV-{r.invoice_id:04d}')
        _t = m[2] if m else ''
        add(r.date or '', _t, '💵', 'green', f"<a href='{url_for('billing.receipt_view',rid=r.id)}'>Payment RCT-{r.id:05d}</a>",
            f"{money(r.amount)} · {h(r.method or 'Cash')}", h(r.cashier or (m[0] if m else '—')))
    # Laboratory + Report
    for o in labs:
        _cd, _ct = _dt_parts(getattr(o, 'collected_at', None))
        add(o.date or '', _ct, '🧪', 'teal', f"<a href='{url_for('lab.lab_result',oid=o.id)}'>Laboratory: {h(o.service.name if o.service else 'Test')}</a>",
            f"Status: {h(o.status)}", h(o.collected_by or '—'))
        if o.status == 'Approved':
            m = _amatch(f'Lab #{o.id}')
            add((m[1] if m else o.date or ''), (m[2] if m else ''), '📄', 'green',
                f"<a href='{url_for('lab.lab_print',oid=o.id)}' target='_blank'>Report: {h(o.service.name if o.service else 'Lab')} approved</a>",
                'Result approved & printable', h(o.approved_by or (m[0] if m else '—')))
    # Radiology + Report
    for o in rads:
        add(o.date or '', '', '📷', 'teal', f"<a href='{url_for('rad.rad_thread',oid=o.id)}'>Radiology: {h(o.modality or '')} {h(o.service.name if o.service else '')}".strip() + "</a>",
            f"Status: {h(o.status)}", h(o.radiologist or '—'))
        if o.status == 'Reported':
            m = _amatch(f'Rad #{o.id}')
            add((m[1] if m else o.date or ''), (m[2] if m else ''), '📄', 'green',
                f"<a href='{url_for('rad.rad_print',oid=o.id)}' target='_blank'>Report: {h(o.service.name if o.service else 'Study')} reported</a>",
                'Report finalized', h(o.reported_by or o.radiologist or (m[0] if m else '—')))
    # Consultations
    for c in cons:
        add(str(c.date or ''), '', '🩺', 'blue', f"<a href='{url_for('modules.module_edit',mod='consult',oid=c.id)}'>Consultation — {h(c.doctor or '—')}</a>",
            h((c.diagnosis or '')[:60]), h(c.doctor or '—'))
    # Prints (from the audit log)
    import re as _re
    for a in _auds:
        act = a.action or ''
        if not act.startswith('PRINT'):
            continue
        link = '#'
        mi = _re.search(r'INV-(\d+)', act); ml = _re.search(r'LAB-(\d+)', act); mr = _re.search(r'RAD-(\d+)', act)
        if mi: link = url_for('billing.invoice_print', iid=int(mi.group(1)))
        elif ml: link = url_for('lab.lab_print', oid=int(ml.group(1)))
        elif mr: link = url_for('rad.rad_print', oid=int(mr.group(1)))
        _d = a.ts.strftime('%Y-%m-%d') if a.ts else ''; _t = a.ts.strftime('%H:%M') if a.ts else ''
        add(_d, _t, '🖨', 'grey', f"<a href='{link}' target='_blank'>{h(act)}</a>", '', h(a.user or '—'))

    ev.sort(key=lambda x: x[0], reverse=True)
    tl_items = ''
    for sk, icon, cls, title, sub, user, date, tim in ev:
        meta = ' · '.join([x for x in [f"👤 {user}" if user and user != '—' else '',
                                       f"📅 {date}" if date else '', f"🕐 {tim}" if tim else ''] if x]) or '—'
        tl_items += f"<div class='tl-i {cls}'><div class='tl-t'>{icon} {title}</div>"
        if sub:
            tl_items += f"<div class='tl-s'>{sub}</div>"
        tl_items += f"<div class='tl-d'>{meta}</div></div>"
    timeline = f"<div class='panel'><div class='ph'><h2>🕒 Activity Timeline</h2><span class='so'>{len(ev)} events</span></div><div class='pad'><div class='tl'>{tl_items}</div></div></div>"
    # ---- no-reload tabs over the patient's related records ----
    panes = {
        'timeline': timeline,
        'consult': tbl('Consultations', con_rows, "<th>Date</th><th>Doctor</th><th>Diagnosis</th><th></th>"),
        'lab': tbl('Laboratory', lab_rows, "<th>Date</th><th>Test</th><th>Status</th><th></th>"),
        'rad': tbl('Radiology', rad_rows, "<th>Date</th><th>Study</th><th>Status</th><th></th>"),
        'inv': tbl('Invoices', inv_rows, "<th>No.</th><th>Date</th><th class='num'>Total</th><th class='num'>Paid</th><th>Status</th><th></th>"),
    }
    tabs_def = [('timeline', '🕒 Timeline'), ('consult', f'Consultations ({len(cons)})'),
                ('lab', f'Laboratory ({len(labs)})'), ('rad', f'Radiology ({len(rads)})'),
                ('inv', f'Invoices ({len(invs)})')]
    tabstrip = "<div class='rtabs'>" + ''.join(
        f"<button class='{'on' if k=='timeline' else ''}' onclick=\"ptab('{k}',this)\">{lb}</button>"
        for k, lb in tabs_def) + "</div>"
    panehtml = ''.join(
        f"<div class='tabpane' id='tp-{k}'{'' if k=='timeline' else ' hidden'}>{panes[k]}</div>"
        for k, _ in tabs_def)
    tabjs = ("<script>function ptab(k,btn){document.querySelectorAll('.tabpane').forEach("
             "function(p){p.hidden=(p.id!='tp-'+k)});document.querySelectorAll('.rtabs button')"
             ".forEach(function(b){b.classList.remove('on')});btn.classList.add('on');}</script>")
    body = actions + header + _patient_next_step(p, invs, labs, rads) + _related_panel(p) + tabstrip + panehtml + tabjs
    crumbs = [('Patients', url_for('modules.module', mod='patients')), (p.name, None)]
    return page(f'Patient · {p.name}', body, 'patients', crumbs=crumbs)

@bp.route('/patient/<int:pid>/report')
@login_required
def patient_report(pid):
    if not can('patients'): abort(403)
    p=Patient.query.get_or_404(pid)
    labs=LabOrder.query.filter_by(patient_id=pid).all(); rads=RadOrder.query.filter_by(patient_id=pid).all(); invs=Invoice.query.filter_by(patient_id=pid).all()
    lr=''.join(f"<tr><td>{h(o.date)}</td><td>{h(o.service.name if o.service else '-')}</td><td>{h(o.status)}</td><td>{h((o.result or '')[:70])}</td></tr>" for o in labs) or "<tr><td colspan=4>None</td></tr>"
    rr=''.join(f"<tr><td>{h(o.date)}</td><td>{h(o.modality)} {h(o.service.name if o.service else '')}</td><td>{h(o.status)}</td></tr>" for o in rads) or "<tr><td colspan=3>None</td></tr>"
    ir=''.join(f"<tr><td>INV-{i.id:04d}</td><td>{h(i.date)}</td><td style='text-align:right'>{money(i.total)}</td><td style='text-align:right'>{money(i.paid)}</td></tr>" for i in invs) or "<tr><td colspan=4>None</td></tr>"
    billed=sum(i.total for i in invs); paid=sum(i.paid or 0 for i in invs)
    return printable(f"Patient Report - {p.name}", f"<p><b>Name:</b> {h(p.name)} &nbsp; <b>MRN:</b> {h(p.mrn)}<br><b>Gender:</b> {h(p.gender or '-')} &nbsp; <b>Phone:</b> {h(p.phone or '-')}</p><h3>Laboratory</h3><table style='width:100%;border-collapse:collapse'><thead><tr style='border-bottom:2px solid #333'><th style='text-align:left'>Date</th><th style='text-align:left'>Test</th><th style='text-align:left'>Status</th><th style='text-align:left'>Result</th></tr></thead><tbody>{lr}</tbody></table><h3>Radiology</h3><table style='width:100%;border-collapse:collapse'><thead><tr style='border-bottom:2px solid #333'><th style='text-align:left'>Date</th><th style='text-align:left'>Study</th><th style='text-align:left'>Status</th></tr></thead><tbody>{rr}</tbody></table><h3>Invoices</h3><table style='width:100%;border-collapse:collapse'><thead><tr style='border-bottom:2px solid #333'><th style='text-align:left'>No.</th><th style='text-align:left'>Date</th><th style='text-align:right'>Total</th><th style='text-align:right'>Paid</th></tr></thead><tbody>{ir}</tbody></table><p style='margin-top:12px;text-align:right'><b>Billed:</b> {money(billed)} &nbsp; <b>Paid:</b> {money(paid)} &nbsp; <b>Balance:</b> {money(billed-paid)}</p>", barcode_text=p.mrn)

@bp.route('/patient/<int:pid>/statement')
@login_required
def patient_statement(pid):
    if not can('patients'): abort(403)
    p=Patient.query.get_or_404(pid)
    invs=[i for i in Invoice.query.filter_by(patient_id=pid).order_by(Invoice.date, Invoice.id).all() if i.status!='Cancelled']
    rows=''; run=0.0
    for i in invs:
        run+=i.total
        rows+=f"<tr><td>{h(i.date)}</td><td>Invoice INV-{i.id:04d}</td><td style='text-align:right'>{money(i.total)}</td><td style='text-align:right'>—</td><td style='text-align:right'>{money(run)}</td></tr>"
        if (i.paid or 0)>0:
            run-=i.paid
            rows+=f"<tr><td>{h(i.date)}</td><td>Payment ({h(i.pay_method or 'Cash')}) INV-{i.id:04d}</td><td style='text-align:right'>—</td><td style='text-align:right'>{money(i.paid)}</td><td style='text-align:right'>{money(run)}</td></tr>"
    if not rows: rows="<tr><td colspan='5' style='padding:14px;color:#888'>No transactions.</td></tr>"
    body=(f"<h3>Customer Statement</h3><p><b>{h(p.name)}</b> · {h(p.mrn)} · {h(p.phone or '')}</p>"
          f"<table style='width:100%;border-collapse:collapse;font-size:13.5px'><thead><tr>"
          f"<th style='text-align:left;padding:7px 4px;border-bottom:2px solid #444'>Date</th>"
          f"<th style='text-align:left;padding:7px 4px;border-bottom:2px solid #444'>Description</th>"
          f"<th style='text-align:right;padding:7px 4px;border-bottom:2px solid #444'>Charges</th>"
          f"<th style='text-align:right;padding:7px 4px;border-bottom:2px solid #444'>Payments</th>"
          f"<th style='text-align:right;padding:7px 4px;border-bottom:2px solid #444'>Balance</th></tr></thead>"
          f"<tbody>{rows}</tbody></table>"
          f"<p style='text-align:right;font-size:16px;margin-top:12px'>Balance Due: <b>{money(run)}</b></p>")
    return printable(f"Statement · {h(p.mrn)}", body)

@bp.route('/supplier/<int:sid>/statement')
@login_required
def supplier_statement(sid):
    if not can('suppliers'): abort(403)
    s=Supplier.query.get_or_404(sid)
    purs=Purchase.query.filter_by(supplier_id=sid).order_by(Purchase.date, Purchase.id).all()
    rows=''; run=0.0
    for pch in purs:
        run+=(pch.total or 0)
        rows+=f"<tr><td>{h(pch.date)}</td><td>Bill · {h(pch.item or '')}</td><td style='text-align:right'>{money(pch.total)}</td><td style='text-align:right'>—</td><td style='text-align:right'>{money(run)}</td></tr>"
        if (pch.paid or 0)>0:
            run-=pch.paid
            rows+=f"<tr><td>{h(pch.date)}</td><td>Payment</td><td style='text-align:right'>—</td><td style='text-align:right'>{money(pch.paid)}</td><td style='text-align:right'>{money(run)}</td></tr>"
    if not rows: rows="<tr><td colspan='5' style='padding:14px;color:#888'>No transactions.</td></tr>"
    body=(f"<h3>Supplier Statement</h3><p><b>{h(s.name)}</b> · {h(s.phone or '')}</p>"
          f"<table style='width:100%;border-collapse:collapse;font-size:13.5px'><thead><tr>"
          f"<th style='text-align:left;padding:7px 4px;border-bottom:2px solid #444'>Date</th>"
          f"<th style='text-align:left;padding:7px 4px;border-bottom:2px solid #444'>Description</th>"
          f"<th style='text-align:right;padding:7px 4px;border-bottom:2px solid #444'>Bills</th>"
          f"<th style='text-align:right;padding:7px 4px;border-bottom:2px solid #444'>Payments</th>"
          f"<th style='text-align:right;padding:7px 4px;border-bottom:2px solid #444'>Balance</th></tr></thead>"
          f"<tbody>{rows}</tbody></table>"
          f"<p style='text-align:right;font-size:16px;margin-top:12px'>Balance Payable: <b>{money(run)}</b></p>")
    return printable(f"Supplier Statement · {h(s.name)}", body)


@bp.route('/patient/<int:pid>/photo')
@login_required
def patient_photo(pid):
    if not can('patients'): abort(403)
    import os
    from flask import send_from_directory
    from ..config import DATA_DIR
    p = Patient.query.get_or_404(pid)
    if not p.photo: abort(404)
    return send_from_directory(os.path.join(DATA_DIR, 'uploads', 'pat'), p.photo)


@bp.route('/patient/<int:pid>/card')
@login_required
def patient_card(pid):
    if not can('patients'): abort(403)
    from ..core.printing import printable
    p = Patient.query.get_or_404(pid)
    photo = f"<img src='{url_for('patients.patient_photo', pid=pid)}' style='width:86px;height:86px;object-fit:cover;border-radius:10px;border:2px solid #1A3E8F'>" if p.photo else \
            "<div style='width:86px;height:86px;border-radius:10px;background:#EAF0FB;display:flex;align-items:center;justify-content:center;font-size:34px;color:#1A3E8F;font-weight:700'>" + h((p.name or '?')[:1].upper()) + "</div>"
    def row(l, v): return f"<tr><td style='color:#666;padding:3px 10px 3px 0;white-space:nowrap'>{l}</td><td style='font-weight:600'>{h(v or '—')}</td></tr>"
    body = f"""
    <div style='border:2px solid #1A3E8F;border-radius:14px;padding:16px;max-width:430px'>
      <div style='display:flex;gap:14px;align-items:center'>{photo}
        <div><div style='font-size:19px;font-weight:800;color:#1A3E8F'>{h(p.name)}</div>
          <div style='color:#F57C00;font-weight:700;letter-spacing:1px'>{h(p.mrn)}</div>
          <div style='color:#666;font-size:12px'>{h(p.gender or '—')} · {(str(p.age)+' yr') if p.age is not None else '—'} · Blood {h(p.blood_group or '—')}</div>
        </div></div>
      <table style='margin-top:12px;font-size:13px;border-collapse:collapse'>
        {row('Phone', p.phone)}{row('Address', p.address)}{row('Emergency', (p.emerg_name or '') + (' · ' + p.emerg_phone if p.emerg_phone else ''))}
        {row('Insurance', (p.ins_company or '') + (' · ' + p.ins_number if p.ins_number else ''))}
        {row('Allergies', p.allergies)}
      </table>
    </div>"""
    return printable(f'Patient Card · {p.mrn}', body, doc_ref=f'PAT-{p.id:05d}', barcode_text=p.mrn)


@bp.route('/vacc/<int:vid>/cert')
@login_required
def vacc_cert(vid):
    if not can('vaccinations'): abort(403)
    from ..core.printing import printable
    from ..models import Vaccination
    v = Vaccination.query.get_or_404(vid)
    p = v.patient
    body = f"""
    <div style='border:2px solid #1A3E8F;border-radius:14px;padding:22px;max-width:520px'>
      <div style='text-align:center;color:#F57C00;font-weight:800;letter-spacing:2px;font-size:15px'>VACCINATION CERTIFICATE</div>
      <table style='margin-top:14px;font-size:14px;border-collapse:collapse;width:100%'>
        <tr><td style='color:#666;padding:4px 0;width:160px'>Patient</td><td style='font-weight:700'>{h(p.name if p else '—')} · {h(p.mrn if p else '')}</td></tr>
        <tr><td style='color:#666;padding:4px 0'>Date of Birth</td><td>{h(p.dob if p else '—')}</td></tr>
        <tr><td style='color:#666;padding:4px 0'>Vaccine</td><td style='font-weight:700'>{h(v.vaccine or '—')} — Dose #{v.dose_no or 1}</td></tr>
        <tr><td style='color:#666;padding:4px 0'>Date Given</td><td>{h(v.date)}</td></tr>
        <tr><td style='color:#666;padding:4px 0'>Batch / Lot</td><td>{h(v.batch or '—')}</td></tr>
        <tr><td style='color:#666;padding:4px 0'>Next Dose Due</td><td>{h(v.next_due or '—')}</td></tr>
        <tr><td style='color:#666;padding:4px 0'>Administered By</td><td>{h(v.given_by or '—')}</td></tr>
      </table>
      <div style='margin-top:26px;display:flex;justify-content:space-between;font-size:13px'>
        <div>_____________________<br>Authorized Signature</div>
        <div style='text-align:right;color:#666'>Modern Diagnostic Center<br>Gaalkacyo</div>
      </div>
    </div>"""
    return printable(f'Vaccination Certificate · VAC-{v.id:04d}', body,
                     doc_ref=f'VAC-{v.id:04d}', barcode_text=(p.mrn if p else None))


# ============================ Related Records ============================
_RR_KINDS = [('invoices', '🧾', 'Invoices'), ('payments', '💵', 'Payments'),
             ('lab', '🧪', 'Laboratory'), ('radiology', '📷', 'Radiology'),
             ('reports', '📄', 'Reports'), ('accounting', '📒', 'Accounting'),
             ('requests', '📋', 'Doctor Requests'), ('appointments', '📅', 'Appointment')]


def _patient_next_step(p, invs, labs, rads):
    """Contextual Next Step for this patient's workflow (registration → request →
    invoice → payment → lab/radiology → report), so staff advance in one click."""
    unpaid = next((i for i in invs if i.status != 'Cancelled' and i.balance > 0.005), None)
    pend_lab = next((o for o in labs if o.status in ('Requested', 'Collected', 'Received')), None)
    pend_rad = next((o for o in rads if o.status in ('Requested', 'Imaged')), None)
    result_lab = next((o for o in labs if o.status == 'Resulted'), None)
    if unpaid:
        return next_step(url_for('billing.invoice_view', iid=unpaid.id), 'Register Payment',
                         f'INV-{unpaid.id:04d} · balance {money(unpaid.balance)}')
    if result_lab:
        return next_step(url_for('lab.lab_action', oid=result_lab.id, act='approve'), 'Approve Lab Result',
                         f'{result_lab.service.name if result_lab.service else "Test"} awaiting approval')
    if pend_lab:
        _u = url_for('lab.lab_result', oid=pend_lab.id) if pend_lab.status == 'Received' else url_for('modules.module', mod='lab')
        return next_step(_u, 'Continue Laboratory', f'{pend_lab.service.name if pend_lab.service else "Test"} · {pend_lab.status}')
    if pend_rad:
        _u = url_for('rad.rad_report', oid=pend_rad.id) if pend_rad.status == 'Imaged' else url_for('modules.module', mod='radiology')
        return next_step(_u, 'Continue Radiology', f'{pend_rad.modality or ""} · {pend_rad.status}')
    if not invs:
        return next_step(url_for('billing.invoice_new') + f'?patient={p.id}', 'Create Invoice',
                         'Start billing & order tests for this patient')
    return ''


def _related_panel(p):
    """Odoo-style Related Records panel: one tile per record type linked to this
    patient, each showing a live count and opening that patient's records."""
    invs = Invoice.query.filter_by(patient_id=p.id).all()
    inv_ids = [i.id for i in invs]
    refs = [f'INV-{i:04d}' for i in inv_ids] + [f'PAY-{i:04d}' for i in inv_ids]
    counts = {
        'invoices': len(invs),
        'payments': PayReceipt.query.filter(PayReceipt.invoice_id.in_(inv_ids or [0])).count(),
        'lab': LabOrder.query.filter_by(patient_id=p.id).count(),
        'radiology': RadOrder.query.filter_by(patient_id=p.id).count(),
        'reports': (LabOrder.query.filter_by(patient_id=p.id, status='Approved').count()
                    + RadOrder.query.filter_by(patient_id=p.id, status='Reported').count()),
        'accounting': JournalEntry.query.filter(JournalEntry.ref.in_(refs)).count() if refs else 0,
        'requests': Referral.query.filter_by(patient_id=p.id).count(),
        'appointments': Appointment.query.filter_by(patient_id=p.id).count(),
    }
    tiles = ''
    for kind, icon, label in _RR_KINDS:
        tiles += (f"<a class='rr-tile' href='{url_for('patients.patient_related', pid=p.id, kind=kind)}'>"
                  f"<span class='rr-ic'>{icon}</span>"
                  f"<span><span class='rr-c'>{counts.get(kind, 0)}</span> <span class='rr-l'>{label}</span></span></a>")
    return f"<div class='panel'><div class='ph'><h2>🔗 Related Records</h2></div><div class='pad'><div class='rr-grid'>{tiles}</div></div></div>"


@bp.route('/patient/<int:pid>/related/<kind>')
@login_required
def patient_related(pid, kind):
    """Patient-scoped list for any related record type — one click from the panel."""
    if not can('patients'): abort(403)
    from flask import render_template
    p = Patient.query.get_or_404(pid)
    invs = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).all()
    inv_ids = [i.id for i in invs]
    title, headers, aligns, rows = '', [], [], []

    if kind == 'invoices':
        title, headers, aligns = 'Invoices', ['No.', 'Date', 'Total', 'Paid', 'Status'], ['', '', 'num', 'num', '']
        for i in invs:
            rows.append([f"<a class='idlink' href='{url_for('billing.invoice_view', iid=i.id)}'>INV-{i.id:04d}</a>",
                         h(i.date), money(i.total), money(i.paid),
                         f"<span class='pill'>{h(i.status)}</span>" + (' 🔒' if getattr(i, 'locked', False) else '')])
    elif kind == 'payments':
        title, headers, aligns = 'Payments', ['Receipt', 'Date', 'Amount', 'Method'], ['', '', 'num', '']
        for r in PayReceipt.query.filter(PayReceipt.invoice_id.in_(inv_ids or [0])).order_by(PayReceipt.id.desc()).all():
            rows.append([f"<a class='idlink' href='{url_for('billing.receipt_view', rid=r.id)}'>RCT-{r.id:05d}</a>",
                         h(r.date), money(r.amount), h(r.method or 'Cash')])
    elif kind == 'lab':
        title, headers, aligns = 'Laboratory', ['Date', 'Test', 'Status'], ['', '', '']
        for o in LabOrder.query.filter_by(patient_id=pid).order_by(LabOrder.id.desc()).all():
            rows.append([h(o.date), f"<a class='idlink' href='{url_for('lab.lab_result', oid=o.id)}'>{h(o.service.name if o.service else 'Test')}</a>",
                         f"<span class='pill'>{h(o.status)}</span>"])
    elif kind == 'radiology':
        title, headers, aligns = 'Radiology', ['Date', 'Modality', 'Study', 'Status'], ['', '', '', '']
        for o in RadOrder.query.filter_by(patient_id=pid).order_by(RadOrder.id.desc()).all():
            rows.append([h(o.date), h(o.modality or ''),
                         f"<a class='idlink' href='{url_for('rad.rad_thread', oid=o.id)}'>{h(o.service.name if o.service else 'Study')}</a>",
                         f"<span class='pill'>{h(o.status)}</span>"])
    elif kind == 'reports':
        title, headers, aligns = 'Reports', ['Date', 'Type', 'Name', 'Status'], ['', '', '', '']
        for o in LabOrder.query.filter_by(patient_id=pid, status='Approved').order_by(LabOrder.id.desc()).all():
            rows.append([h(o.date), '🧪 Lab', f"<a class='idlink' href='{url_for('lab.lab_print', oid=o.id)}' target='_blank'>{h(o.service.name if o.service else 'Lab')}</a>",
                         "<span class='pill green'>Approved</span>"])
        for o in RadOrder.query.filter_by(patient_id=pid, status='Reported').order_by(RadOrder.id.desc()).all():
            rows.append([h(o.date), '📷 Radiology', f"<a class='idlink' href='{url_for('rad.rad_print', oid=o.id)}' target='_blank'>{h(o.service.name if o.service else 'Study')}</a>",
                         "<span class='pill green'>Reported</span>"])
    elif kind == 'accounting':
        title, headers, aligns = 'Accounting', ['Date', 'Ref', 'Memo', 'Debit', 'Credit'], ['', '', '', 'num', 'num']
        refs = [f'INV-{i:04d}' for i in inv_ids] + [f'PAY-{i:04d}' for i in inv_ids]
        entries = JournalEntry.query.filter(JournalEntry.ref.in_(refs)).order_by(JournalEntry.id.desc()).all() if refs else []
        for e in entries:
            rows.append([h(e.date), f"<a class='idlink' href='{url_for('acct.journal_entry', eid=e.id)}'>{h(e.ref or '')}</a>",
                         h(e.memo or ''), money(e.total_debit), money(e.total_credit)])
    elif kind == 'requests':
        title, headers, aligns = 'Doctor Requests', ['Ref', 'Date', 'Doctor', 'Status'], ['', '', '', '']
        for r in Referral.query.filter_by(patient_id=pid).order_by(Referral.id.desc()).all():
            rows.append([f"<a class='idlink' href='{url_for('ref.referral_thread', rid=r.id)}'>REF-{r.id:04d}</a>",
                         h(r.date), h(r.doctor_name or '—'), f"<span class='pill'>{h(r.status)}</span>"])
    elif kind == 'appointments':
        title, headers, aligns = 'Appointments', ['Date', 'Time', 'Department', 'Doctor', 'Status'], ['', '', '', '', '']
        for a in Appointment.query.filter_by(patient_id=pid).order_by(Appointment.id.desc()).all():
            rows.append([h(a.date), h(a.time or ''), h(a.department or ''), h(a.doctor or ''),
                         f"<span class='pill'>{h(a.status or '')}</span>"])
    else:
        abort(404)

    crumbs = [('Patients', url_for('modules.module', mod='patients')),
              (p.name, url_for('patients.patient_detail', pid=pid)), (title, None)]
    body = render_template('list_page.html', title=f'{title} — {h(p.name)}',
                           toolbar=f"<a class=\"btn\" href=\"{url_for('patients.patient_detail', pid=pid)}\">← Back to Patient</a>",
                           headers=headers, aligns=aligns, rows=rows,
                           empty=f"<div class='empty'><b>No {title.lower()}</b>None recorded for this patient yet.</div>")
    return page(f'{title} · {p.name}', body, 'patients', crumbs=crumbs)


def _purge_patient(pid):
    """Delete a patient AND every record tied to them, reversing the ledger.
    Children are removed first (GL lines + journals, invoice items, receipts,
    credit notes, commission accruals, lab values, imaging studies, referral
    comments), then all patient-linked rows, then the patient. Returns a summary."""
    from ..extensions import db
    inv_ids = [r[0] for r in db.session.query(Invoice.id).filter(Invoice.patient_id == pid).all()]
    lab_ids = [r[0] for r in db.session.query(LabOrder.id).filter(LabOrder.patient_id == pid).all()]
    rad_ids = [r[0] for r in db.session.query(RadOrder.id).filter(RadOrder.patient_id == pid).all()]
    ref_ids = [r[0] for r in db.session.query(Referral.id).filter(Referral.patient_id == pid).all()]

    try:
        db.session.execute(db.text('PRAGMA foreign_keys=OFF'))
    except Exception:
        pass

    # 1) reverse/remove the ledger for this patient's invoices (journals + their lines)
    refs = [f'{p}-{i:04d}' for i in inv_ids for p in ('INV', 'PAY', 'COMM')]
    n_gl = 0
    if refs:
        je_ids = [r[0] for r in db.session.query(JournalEntry.id).filter(JournalEntry.ref.in_(refs)).all()]
        if je_ids:
            JournalLine.query.filter(JournalLine.entry_id.in_(je_ids)).delete(synchronize_session=False)
            n_gl = JournalEntry.query.filter(JournalEntry.id.in_(je_ids)).delete(synchronize_session=False)

    def _del(model, col, ids):
        if ids:
            try:
                model.query.filter(getattr(model, col).in_(ids)).delete(synchronize_session=False)
            except Exception:
                db.session.rollback()

    # 2) children of invoices / orders / referrals
    for M in (InvoiceItem, CreditNote, PayReceipt, CommissionAccrual):
        _del(M, 'invoice_id', inv_ids)
    _del(InvoiceItem, 'lab_order_id', lab_ids)
    _del(InvoiceItem, 'rad_order_id', rad_ids)
    _del(LabResultValue, 'order_id', lab_ids)
    _del(ImgStudy, 'rad_order_id', rad_ids)
    _del(RefComment, 'referral_id', ref_ids)

    # 3) every table that directly references the patient
    n_rows = 0
    for M in (Appointment, LabOrder, RadOrder, PharmacySale, Referral, Consultation, Prescription,
              Invoice, QueueTicket, Feedback, Vaccination, ImgStudy, InsuranceCard, PreAuth, Claim,
              EDVisit, Admission, Surgery, DialysisSession, Dispatch, CrossMatch, Transfusion):
        try:
            n_rows += M.query.filter(M.patient_id == pid).delete(synchronize_session=False) or 0
        except Exception:
            db.session.rollback()

    # 4) the patient
    Patient.query.filter(Patient.id == pid).delete(synchronize_session=False)
    try:
        db.session.execute(db.text('PRAGMA foreign_keys=ON'))
    except Exception:
        pass
    db.session.commit()
    return {'invoices': len(inv_ids), 'gl_entries': n_gl, 'related_rows': n_rows}


@bp.route('/patient/<int:pid>/purge', methods=['POST'])
@login_required
def patient_purge(pid):
    from flask import request, redirect, flash
    from ..core.security import cur_user, log
    p = Patient.query.get_or_404(pid)
    u = cur_user()
    if not (u and u.role == 'super_admin'):
        flash('Only an administrator can permanently delete a patient and all their data.')
        log(f'DENIED patient purge #{pid} by {u.username if u else "?"}')
        return redirect(url_for('patients.patient_detail', pid=pid))
    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash('A reason is required to delete a patient.')
        return redirect(url_for('patients.patient_detail', pid=pid))
    name = p.name; mrn = p.mrn
    try:
        res = _purge_patient(pid)
    except Exception:
        from ..extensions import db
        db.session.rollback()
        from ..core.helpers import log_error
        log_error(f'patient_purge #{pid}')
        flash('Could not delete the patient — nothing was removed. Please try again or contact support.')
        return redirect(url_for('patients.patient_detail', pid=pid))
    log(f'PATIENT PURGED: {name} (MRN {mrn}) — {res["invoices"]} invoice(s), {res["gl_entries"]} ledger entr(ies), {res["related_rows"]} related record(s) deleted',
        action_type='Delete', entity=f'Patient#{pid}', old=f'{name} · MRN {mrn}', new='Deleted (all data purged)', reason=reason)
    flash(f'🗑 Patient "{name}" and all their data were permanently deleted '
          f'({res["invoices"]} invoice(s), {res["related_rows"]} related record(s), ledger reversed).')
    return redirect(url_for('modules.module', mod='patients'))
