"""Patient portal: results, invoices and printable documents for patients."""
from flask import (Blueprint, request, redirect, url_for, session, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.helpers import money
from ..core.ui import public_shell
from ..core.printing import printable

bp = Blueprint('portal', __name__)

def portal_patient():
    pid = session.get('portal_pid')
    return Patient.query.get(pid) if pid else None

@bp.route('/portal', methods=['GET','POST'])
def portal():
    err = ''
    if request.method == 'POST':
        mrn = (request.form.get('mrn') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        p = Patient.query.filter(Patient.mrn.ilike(mrn)).first()
        if p and phone and (p.phone or '').replace(' ', '').endswith(phone.replace(' ', '')[-6:]) and len(phone) >= 4:
            session['portal_pid'] = p.id
            return redirect(url_for('portal.portal_home'))
        err = "<div style='background:#FDECEA;color:#B3261E;border-radius:9px;padding:11px 14px;font-size:13.5px;margin-bottom:12px'>MRN ama telefoonku ma is-waafaqsana. Fadlan hubi — ama xarunta wac.</div>"
    if portal_patient():
        return redirect(url_for('portal.portal_home'))
    form = f"""<div class='panel' style='max-width:440px;margin:0 auto'><div class='pad'>
      <h2 style='font-family:Space Grotesk;color:var(--petrol);margin-bottom:4px'>Patient Portal</h2>
      <p style='color:var(--muted);font-size:13px;margin-bottom:14px'>Ku gal MRN-kaaga iyo lambarka telefoonka aad iska diiwaan gelisay.</p>
      {err}
      <form method='post'>
      <div class='fld'><label>MRN (Medical Record Number)</label><input name='mrn' placeholder='MRN1001' required autofocus></div>
      <div class='fld'><label>Phone number</label><input name='phone' placeholder='61xxxxxxx' required></div>
      <div style='margin-top:14px'><button class='btn primary' style='width:100%;padding:12px'>Sign in · Gal</button></div>
      </form></div></div>"""
    return public_shell('Patient Portal', form)

@bp.route('/portal/logout')
def portal_logout():
    session.pop('portal_pid', None)
    return redirect(url_for('portal.portal'))

@bp.route('/portal/home')
def portal_home():
    p = portal_patient()
    if not p: return redirect(url_for('portal.portal'))
    labs = LabOrder.query.filter_by(patient_id=p.id).order_by(LabOrder.id.desc()).all()
    rads = RadOrder.query.filter_by(patient_id=p.id).order_by(RadOrder.id.desc()).all()
    invs = Invoice.query.filter_by(patient_id=p.id).order_by(Invoice.id.desc()).all()
    LS = {'Requested':'amber','Collected':'blue','Resulted':'teal','Approved':'green'}
    RS = {'Requested':'amber','Imaged':'blue','Reported':'green'}
    lrows = ''.join(
        f"<tr><td>{h(o.date)}</td><td>{h(o.service.name if o.service else 'Lab Test')}</td>"
        f"<td><span class='pill {LS.get(o.status,'grey')}'>{h(o.status)}</span></td>"
        f"<td class='num'>{('<a class=btn_gh href=/portal/lab/'+str(o.id)+' style=\"color:var(--petrol);font-weight:600\">View Result</a>') if o.status=='Approved' and o.result else '<span style=color:var(--muted)>Pending</span>'}</td></tr>"
        for o in labs) or "<tr><td colspan='4' style='color:var(--muted);padding:14px'>No lab tests yet.</td></tr>"
    rrows = ''.join(
        f"<tr><td>{h(o.date)}</td><td>{h(o.modality or '')} · {h(o.service.name if o.service else 'Imaging')}</td>"
        f"<td><span class='pill {RS.get(o.status,'grey')}'>{h(o.status)}</span></td>"
        f"<td class='num'>{('<a href=/portal/rad/'+str(o.id)+' style=\"color:var(--petrol);font-weight:600\">View Report</a>') if o.status=='Reported' and o.report else '<span style=color:var(--muted)>Pending</span>'}</td></tr>"
        for o in rads) or "<tr><td colspan='4' style='color:var(--muted);padding:14px'>No imaging yet.</td></tr>"
    irows = ''.join(
        f"<tr><td>INV-{i.id:04d}</td><td>{h(i.date)}</td><td class='num'>{money(i.total)}</td>"
        f"<td class='num'>{money(i.paid or 0)}</td>"
        f"<td><span class='pill {'green' if i.status=='Paid' else ('blue' if i.status=='Partial' else 'amber')}'>{h(i.status)}</span></td>"
        f"<td class='num'><a href='/portal/invoice/{i.id}' style='color:var(--petrol);font-weight:600'>View</a></td></tr>"
        for i in invs) or "<tr><td colspan='6' style='color:var(--muted);padding:14px'>No invoices yet.</td></tr>"
    due = sum(i.total - (i.paid or 0) for i in invs)
    body = f"""<div class='panel'><div class='pad' style='display:flex;align-items:center;gap:12px;flex-wrap:wrap'>
      <div><div style='font-family:Space Grotesk;font-weight:700;font-size:18px;color:var(--petrol)'>{h(p.name)}</div>
      <div style='color:var(--muted);font-size:12.5px'>{h(p.mrn)} · {h(p.phone or '')}</div></div>
      <div class='sp'></div>
      <div style='text-align:right'><div style='font-size:11px;color:var(--muted)'>BALANCE DUE</div>
      <div style='font-family:Space Grotesk;font-weight:700;font-size:20px;color:{"var(--green)" if due<=0 else "#B3261E"}'>{money(due)}</div></div>
      <a class='btn sm primary' href='{url_for('portal.portal_book')}'>🕐 Book Appointment</a>
      <a class='btn sm' href='{url_for('portal.portal_feedback')}'>⭐ Feedback</a>
      <a class='btn sm' href='{url_for('portal.portal_logout')}'>Logout</a></div></div>
      <div class='panel'><div class='ph'><h2>Laboratory Results</h2></div><div class='tw'><table><thead><tr><th>Date</th><th>Test</th><th>Status</th><th></th></tr></thead><tbody>{lrows}</tbody></table></div></div>
      <div class='panel'><div class='ph'><h2>Radiology Reports</h2></div><div class='tw'><table><thead><tr><th>Date</th><th>Study</th><th>Status</th><th></th></tr></thead><tbody>{rrows}</tbody></table></div></div>
      <div class='panel'><div class='ph'><h2>Invoices</h2></div><div class='tw'><table><thead><tr><th>No.</th><th>Date</th><th class='num'>Total</th><th class='num'>Paid</th><th>Status</th><th></th></tr></thead><tbody>{irows}</tbody></table></div></div>"""
    return public_shell('My Results', body)

@bp.route('/portal/lab/<int:oid>')
def portal_lab(oid):
    p = portal_patient()
    if not p: return redirect(url_for('portal.portal'))
    o = LabOrder.query.get_or_404(oid)
    if o.patient_id != p.id or o.status != 'Approved': abort(403)
    body = (f"<h3>Laboratory Result</h3><p><b>Patient:</b> {h(p.name)} · {h(p.mrn)}<br>"
            f"<b>Test:</b> {h(o.service.name if o.service else 'Lab Test')} &nbsp; <b>Date:</b> {h(o.date)}</p>"
            f"<div style='border:1px solid #ddd;border-radius:8px;padding:14px;white-space:pre-wrap;font-size:14px'>{h(o.result or '')}</div>"
            f"<p style='margin-top:16px'>Result by: {h(o.result_by or '—')} · Approved by: <b>{h(o.approved_by or '—')}</b></p>")
    return printable(f"Lab Result · {h(p.mrn)}", body)

@bp.route('/portal/rad/<int:oid>')
def portal_rad(oid):
    p = portal_patient()
    if not p: return redirect(url_for('portal.portal'))
    o = RadOrder.query.get_or_404(oid)
    if o.patient_id != p.id or o.status != 'Reported': abort(403)
    body = (f"<h3>Radiology Report</h3><p><b>Patient:</b> {h(p.name)} · {h(p.mrn)}<br>"
            f"<b>Study:</b> {h(o.modality or '')} · {h(o.service.name if o.service else '')} &nbsp; <b>Date:</b> {h(o.date)}</p>"
            f"<div style='border:1px solid #ddd;border-radius:8px;padding:14px;white-space:pre-wrap;font-size:14px'>{h(o.report or '')}</div>"
            f"<p style='margin-top:30px'>Radiologist: <b>{h(o.radiologist or o.reported_by or '—')}</b><br>"
            f"<span style='color:#888;font-size:12px'>Signature: ____________________</span></p>")
    return printable(f"Radiology Report · {h(p.mrn)}", body)

@bp.route('/portal/invoice/<int:iid>')
def portal_invoice(iid):
    p = portal_patient()
    if not p: return redirect(url_for('portal.portal'))
    inv = Invoice.query.get_or_404(iid)
    if inv.patient_id != p.id: abort(403)
    rows = ''.join(f"<tr><td style='padding:7px 4px;border-bottom:1px solid #eee'>{h(it.desc)}</td>"
                   f"<td style='text-align:right;padding:7px 4px;border-bottom:1px solid #eee'>{it.qty:g}</td>"
                   f"<td style='text-align:right;padding:7px 4px;border-bottom:1px solid #eee'>{money(it.price)}</td>"
                   f"<td style='text-align:right;padding:7px 4px;border-bottom:1px solid #eee'>{money(it.qty*it.price)}</td></tr>" for it in inv.items)
    body = (f"<h3>Invoice INV-{inv.id:04d}</h3><p><b>Patient:</b> {h(p.name)} · {h(p.mrn)} &nbsp; <b>Date:</b> {h(inv.date)}</p>"
            f"<table style='width:100%;border-collapse:collapse;font-size:14px'><thead><tr>"
            f"<th style='text-align:left;padding:7px 4px;border-bottom:2px solid #444'>Description</th>"
            f"<th style='text-align:right;padding:7px 4px;border-bottom:2px solid #444'>Qty</th>"
            f"<th style='text-align:right;padding:7px 4px;border-bottom:2px solid #444'>Price</th>"
            f"<th style='text-align:right;padding:7px 4px;border-bottom:2px solid #444'>Amount</th></tr></thead><tbody>{rows}</tbody></table>"
            f"<p style='text-align:right;margin-top:12px;font-size:14.5px'>Subtotal: <b>{money(inv.subtotal)}</b> &nbsp; Discount: {money(inv.discount or 0)} &nbsp; VAT: {money(inv.vat or 0)}<br>"
            f"<span style='font-size:17px'>TOTAL: <b>{money(inv.total)}</b></span><br>"
            f"Paid: {money(inv.paid or 0)} · <b>Balance: {money(inv.total-(inv.paid or 0))}</b> · {h(inv.status)}</p>")
    return printable(f"Invoice INV-{inv.id:04d}", body)



# ------------------------------------------------- printed-document verification
@bp.route('/verify')
def verify_document():
    """Public QR-code target: confirms a printed document was issued by this system."""
    from ..core.security import doc_sig
    ref = (request.args.get('ref') or '').strip().upper()
    sig = (request.args.get('sig') or '').strip()
    ok = bool(ref) and sig == doc_sig(ref)
    detail = ''
    if ok:
        kind, _, num = ref.partition('-')
        try:
            oid = int(num)
        except ValueError:
            oid, ok = 0, False
        if kind == 'INV':
            d = Invoice.query.get(oid)
            if d: detail = (f"Invoice INV-{d.id:04d} · {h(d.date)} · Patient: "
                            f"{h(d.patient.name if d.patient else 'Walk-in')} · Total {money(d.total)} · {h(d.status or 'Unpaid')}")
        elif kind == 'LAB':
            d = LabOrder.query.get(oid)
            if d: detail = (f"Laboratory Report LAB-{d.id:04d} · {h(d.date)} · "
                            f"{h(d.service.name if d.service else '')} · Status: {h(d.status)}")
        elif kind == 'RAD':
            d = RadOrder.query.get(oid)
            if d: detail = (f"Radiology Report RAD-{d.id:04d} · {h(d.date)} · "
                            f"{h(d.modality or '')} {h(d.service.name if d.service else '')} · Status: {h(d.status)}")
        if not detail:
            ok = False
    color = 'var(--green)' if ok else 'var(--red)'
    icon = '✓' if ok else '✕'
    title = 'Document Verified · Waa Sax' if ok else 'Not Verified · Lama Xaqiijin'
    msg = detail if ok else 'This reference/signature does not match any document issued by this system.'
    inner = f"""<div class="panel"><div class="pad" style="text-align:center;padding:34px">
      <div style="width:64px;height:64px;border-radius:50%;background:{color};color:#fff;display:grid;place-items:center;font-size:30px;margin:0 auto 14px">{icon}</div>
      <h2 style="font-family:var(--fd)">{title}</h2>
      <p style="color:var(--muted);margin-top:10px;font-size:14px">{msg}</p></div></div>"""
    return public_shell('Verify Document', inner)


@bp.route('/portal/book', methods=['GET', 'POST'])
def portal_book():
    """Online appointment booking from the patient portal."""
    p = portal_patient()
    if not p: return redirect(url_for('portal.portal'))
    import datetime as _dt
    if request.method == 'POST':
        d = request.form.get('date') or ''
        try:
            if _dt.date.fromisoformat(d) < _dt.date.today():
                raise ValueError
        except Exception:
            return redirect(url_for('portal.portal_book'))
        a = Appointment(patient_id=p.id, date=d, time=request.form.get('time') or '',
                        department=request.form.get('department') or 'Consultation',
                        visit_type=request.form.get('visit_type') or 'New',
                        status='Scheduled',
                        notes=('Online booking · ' + (request.form.get('notes') or ''))[:200])
        db.session.add(a); db.session.commit()
        from ..core.notify import notify
        notify(f'Online booking: {p.name} · {a.date} {a.time} · {a.department}',
               '/m/appointments', role='reception')
        body = f"""<div class='panel'><div class='pad' style='text-align:center'>
          <div style='font-size:40px'>✅</div>
          <h2 style='color:var(--petrol);margin:8px 0'>Ballantaadu waa la diiwaan-geliyay</h2>
          <p style='color:var(--muted)'>{h(a.date)} {h(a.time or '')} · {h(a.department)}<br>
          Waxaan kula soo xiriiri doonnaa haddii isbeddel jiro. Fadlan waqtiga kaalay.</p>
          <a class='btn primary' href='{url_for('portal.portal_home')}'>← Back to My Results</a></div></div>"""
        return public_shell('Booked', body)
    mind = _dt.date.today().isoformat()
    body = f"""<div class='panel'><div class='ph'><h2>Book Appointment · Ballan Qabso</h2></div><div class='pad'>
      <form method='post'><div class='fg'>
        <div class='fld'><label>Date · Taariikhda</label><input name='date' type='date' min='{mind}' required></div>
        <div class='fld'><label>Time · Waqtiga</label><input name='time' type='time'></div>
        <div class='fld'><label>Department</label><select name='department'>
          <option>Consultation</option><option>Laboratory</option><option>Radiology</option></select></div>
        <div class='fld'><label>Visit Type</label><select name='visit_type'>
          <option>New</option><option>Follow-up</option></select></div>
        <div class='fld full'><label>Notes (optional)</label><input name='notes' maxlength='150'></div>
        <div class='fld full'><button class='btn primary'>Book · Qabso</button>
          <a class='btn' style='margin-left:8px' href='{url_for('portal.portal_home')}'>Cancel</a></div>
      </div></form></div></div>"""
    return public_shell('Book Appointment', body)


@bp.route('/portal/feedback', methods=['GET', 'POST'])
def portal_feedback():
    p = portal_patient()
    if not p: return redirect(url_for('portal.portal'))
    from ..models import Feedback
    if request.method == 'POST':
        try: rating = max(1, min(5, int(request.form.get('rating') or 5)))
        except ValueError: rating = 5
        db.session.add(Feedback(patient_id=p.id, rating=rating,
                                comment=(request.form.get('comment') or '')[:400]))
        db.session.commit()
        from ..core.notify import notify
        notify(f'Feedback {"★"*rating} · {p.name}', '/m/feedback', role='branch_manager')
        body = """<div class='panel'><div class='pad' style='text-align:center'>
          <div style='font-size:40px'>🙏</div><h2 style='color:var(--petrol)'>Mahadsanid!</h2>
          <p style='color:var(--muted)'>Ra'yigaaga waa muhiim — waan horumarinaynaa adeegga.</p>
          <a class='btn primary' href='/portal/home'>← Back</a></div></div>"""
        return public_shell('Thank you', body)
    stars = ''.join(f"<label style='font-size:26px;cursor:pointer'><input type='radio' name='rating' value='{i}' {'checked' if i==5 else ''} style='margin-right:4px'>{'★'*i}</label><br>" for i in (5,4,3,2,1))
    body = f"""<div class='panel'><div class='ph'><h2>Feedback · Ra'yi</h2></div><div class='pad'>
      <form method='post'><div class='fg'>
        <div class='fld full'><label>Sidee ayaan kuugu adeegnay?</label>{stars}</div>
        <div class='fld full'><label>Faallo (ikhtiyaari)</label><textarea name='comment' rows='3' maxlength='400'></textarea></div>
        <div class='fld full'><button class='btn primary'>Send · Dir</button>
          <a class='btn' style='margin-left:8px' href='/portal/home'>Cancel</a></div>
      </div></form></div></div>"""
    return public_shell('Feedback', body)
