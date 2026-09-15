"""Laboratory workflow: orders, results, approval, printing."""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.security import (cur_user, can, login_required, log)
from ..core.helpers import money
from ..core.ui import page, track_view, plink, pnamelink
from ..core.workflows import transition_target
from ..core.crud import (render_form, opt_patients, opt_services)
from ..core.printing import printable

bp = Blueprint('lab', __name__)

def lab_list():
    from flask import render_template
    from .modules import search_view, hl
    from ..models import Patient
    show_unpaid = request.args.get('unpaid') == '1'
    _base = LabOrder.query.order_by(LabOrder.id.desc())

    def _lab_extra(q):
        conds = [LabOrder.patient.has(Patient.name.ilike(f'%{q}%')),
                 LabOrder.patient.has(Patient.mrn.ilike(f'%{q}%'))]
        digits = ''.join(ch for ch in q if ch.isdigit())
        if digits:
            try:
                conds.append(LabOrder.id == int(digits))
            except ValueError:
                pass
        return conds

    _base, _sq, _fbar = search_view('lab', LabOrder, _base,
                                    search_cols=['sample_no', 'status', 'specimen'], date_field='date',
                                    extra_or=_lab_extra, placeholder='Search patient, MRN, order no…')
    orders_all = _base.all()
    waiting_pay = [o for o in orders_all if o.paid_gate is False]
    orders = orders_all if show_unpaid else [o for o in orders_all if o.paid_gate is not False]
    rows=[]
    for o in orders:
        st={'Requested':'blue','Collected':'amber','Received':'amber','Resulted':'teal','Approved':'green'}
        acts=''
        if o.status=='Requested': acts=f"<a class='btn sm' href='{url_for('lab.lab_action',oid=o.id,act='collect')}'>Collect Sample</a>"
        elif o.status=='Collected':
            acts=(f"<a class='btn sm' href='{url_for('lab.lab_label',oid=o.id)}' target='_blank'>🏷 Label</a> "
                  f"<a class='btn sm' href='{url_for('lab.lab_action',oid=o.id,act='receive')}'>Receive</a>")
        elif o.status=='Received': acts=f"<a class='btn sm' href='{url_for('lab.lab_result',oid=o.id)}'>Enter Result</a>"
        elif o.status=='Resulted':
            acts=f"<a class='btn sm ok' href='{url_for('lab.lab_action',oid=o.id,act='approve')}'>Approve</a> <a class='btn sm' href='{url_for('lab.lab_result',oid=o.id)}'>Edit</a>"
        elif o.status=='Approved': acts=f"<a class='btn sm' href='{url_for('lab.lab_print',oid=o.id)}' data-pdf='{url_for('lab.lab_result_pdf_dl',oid=o.id)}' target='_blank'>Print</a> <a class='btn sm gh' href='{url_for('lab.lab_amend',oid=o.id)}'>Amend</a>"
        cls = st.get(o.status,'grey')
        flags=('<span class="pill red" style="margin-left:4px">⚠ PANIC</span>' if o.panic else '') + \
              ('<span class="pill amber" style="margin-left:4px">Δ</span>' if o.delta_flag else '')
        smp=f"<span style='font-family:monospace;font-size:12px'>{h(o.sample_no)}</span><div style='color:var(--muted);font-size:11px'>{h(o.specimen or '')}</div>" if o.sample_no else '—'
        rows.append([
            h(o.date),
            plink(o.patient),
            h(o.service.name if o.service else '—'),
            smp,
            f"<span class='pill {cls}'>{h(o.status)}</span>{flags}",
            h((o.result or '')[:32]),
            acts,
        ])
    gate_banner = (f"<div class='panel' style='border-left:3px solid var(--amber)'><div class='pad' style='font-size:13px'>"
                   f"⏳ <b>{len(waiting_pay)}</b> request(s) waiting for payment — hidden until paid. "
                   f"<a href='?unpaid=1' style='color:var(--petrol)'>Show them</a></div></div>") if (waiting_pay and not show_unpaid) else (
                   f"<div class='panel' style='border-left:3px solid var(--amber)'><div class='pad' style='font-size:13px'>"
                   f"Showing UNPAID/pending requests. <a href='?' style='color:var(--petrol)'>Back to workable list</a></div></div>" if show_unpaid else '')
    if _sq:
        rows = [[hl(c, _sq) for c in row] for row in rows]
    # ---- Odoo stat band ----
    _all = LabOrder.query.all()
    _tdy = dt.date.today().isoformat()
    def _n(*ss): return sum(1 for o in _all if o.status in ss)
    _css = """<style>
    .lr-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .lr-stat{flex:1;min-width:138px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:11px 14px;box-shadow:var(--shadow)}
    .lr-stat .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
    .lr-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
    .lr-stat.a{border-left:3px solid #2b7de9} .lr-stat.b{border-left:3px solid var(--amber)}
    .lr-stat.c{border-left:3px solid #0E7C86} .lr-stat.d{border-left:3px solid var(--green)}
    .lr-stat.e{border-left:3px solid var(--red)} .lr-stat.f{border-left:3px solid var(--petrol)}
    </style>"""
    def _sc(cls, l, v): return f"<div class='lr-stat {cls}'><div class='l'>{l}</div><div class='v'>{v}</div></div>"
    stats = (_css + "<div class='lr-stats'>"
             + _sc('a', 'Requested', _n('Requested'))
             + _sc('b', 'In Process', _n('Collected', 'Received'))
             + _sc('c', 'Awaiting Approval', _n('Resulted'))
             + _sc('d', 'Approved', _n('Approved'))
             + _sc('e', 'Waiting Payment', sum(1 for o in _all if o.paid_gate is False))
             + _sc('f', 'Today', sum(1 for o in _all if (o.date or '') == _tdy))
             + "</div>")
    toolbar=(f"<a class=\"btn\" href=\"{url_for('modules.module',mod='labqc')}\">QC</a> "
             f"<a class=\"btn primary\" href=\"{url_for('lab.lab_new')}\">+ New Test Request</a>")
    body=render_template('list_page.html', title='Laboratory'+(' · Unpaid' if show_unpaid else ''),
                         prefix=stats+gate_banner, toolbar=toolbar, filterbar=_fbar,
                         headers=['Date','Patient','Test','Sample','Status','Result',''],
                         aligns=['','','','','','','num'], rows=rows,
                         empty="<div class='empty'><b>No lab orders</b>Create a test request.</div>")
    return page('Laboratory', body, 'lab')

@bp.route('/lab/new', methods=['GET','POST'])
@login_required
def lab_new():
    if not can('lab'): abort(403)
    if request.method=='POST':
        o=LabOrder(patient_id=request.form['patient_id'] or None, service_id=request.form['service_id'] or None); 
        db.session.add(o); db.session.commit(); log('Lab request created'); flash('Test requested'); return redirect(url_for('modules.module',mod='lab'))
    fields=[dict(name='patient_id',label='Patient',type='select',options=opt_patients(),required=True,default=request.args.get('patient','')),
            dict(name='service_id',label='Lab Test',type='select',options=opt_services('Laboratory'),required=True)]
    if not Service.query.filter_by(department='Laboratory',active=True).count():
        return page('New Test',"<div class='panel'><div class='pad'><b>No lab tests in catalog.</b> Add services with department = Laboratory first.</div></div>",'lab')
    return page('New Test', render_form('New Test Request',url_for('lab.lab_new'),fields,back=url_for('modules.module',mod='lab')),'lab')

@bp.route('/lab/<int:oid>/<act>')
@login_required
def lab_action(oid, act):
    o=LabOrder.query.get_or_404(oid)
    if act in ('collect', 'receive', 'approve'):
        try:
            transition_target('lab', o.status, act, cur_user().role)
        except (ValueError, PermissionError) as exc:
            flash(str(exc))
            return redirect(url_for('modules.module', mod='lab'))
    if act=='collect':
        o.status='Collected'
        o.sample_no=o.sample_no or f'SMP-{o.id:05d}'
        o.specimen=o.specimen or (o.service.specimen if o.service and o.service.specimen else 'Blood')
        o.collected_by=cur_user().username
        o.collected_at=dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    elif act=='receive':
        o.status='Received'
        o.received_at=dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    elif act=='approve':
        o.status='Approved'; o.approved_by=cur_user().username
        o.locked = True   # approved results are locked — corrections require an amendment
        from ..core.notify import notify_event
        notify_event('report_completed',
                     f"Report completed: {o.patient.name if o.patient else '—'} · {o.service.name if o.service else ''} (LAB-{o.id:04d})",
                     link=f'/lab/{o.id}/print')
        if o.ref_id:
            from ..models import Referral, Doctor
            _r = Referral.query.get(o.ref_id)
            _doc = Doctor.query.get(_r.doctor_id) if _r and _r.doctor_id else None
            if _doc and _doc.phone:
                from ..core.messaging import queue_msg as _qm
                _qm(_doc.phone,
                    f"Dr {_doc.name}: report ready for {o.patient.name if o.patient else ''} "
                    f"({o.service.name if o.service else ''}). View: /dr (REF-{o.ref_id:04d})",
                    ref=f'REF-{o.ref_id:04d}')
        if o.patient and o.patient.phone:
            from ..core.messaging import queue_msg
            queue_msg(o.patient.phone,
                      f"{o.patient.name}, natiijadaadii shaybaarka waa diyaar. Kaalay MDC ama portal-ka ka arag. Ref LAB-{o.id:04d}",
                      ref=f'LAB-{o.id:04d}')
    db.session.commit(); log(f'Lab #{oid} {act}')
    if o.status == 'Approved' and getattr(o, 'invoice_id', None):
        from .billing import _maybe_complete
        _inv = Invoice.query.get(o.invoice_id)
        if _inv: _maybe_complete(_inv)
    flash('Updated'); return redirect(url_for('modules.module',mod='lab'))

@bp.route('/lab/<int:oid>/result', methods=['GET','POST'])
@login_required
def lab_result(oid):
    o=LabOrder.query.get_or_404(oid)
    if o.locked or o.status == 'Approved':
        flash('This result is approved and locked. Use "Amend Result" to make a corrected version — the original is preserved.')
        return redirect(url_for('lab.lab_amend', oid=oid))
    try: track_view('lab', o.id, f"LAB-{o.id:04d}"+(' · '+o.patient.name if o.patient else ''), url_for('lab.lab_result', oid=o.id))
    except Exception: pass
    if request.method=='POST':
        try:
            transition_target('lab', o.status, 'result', cur_user().role)
        except (ValueError, PermissionError) as exc:
            flash(str(exc))
            return redirect(url_for('modules.module', mod='lab'))
        o.result=request.form.get('result'); o.status='Resulted'; o.result_by=cur_user().username
        _run_result_checks(o)
        db.session.commit()
        log(f'Lab #{oid} result' + (' PANIC' if o.panic else '') + (' DELTA' if o.delta_flag else ''))
        if o.panic: flash('⚠ PANIC VALUE — critical result, doctor notified')
        elif o.delta_flag: flash('Δ Delta check: large change vs previous result')
        else: flash('Result saved')
        return redirect(url_for('modules.module',mod='lab'))
    svc = o.service
    ref_html = ''
    if svc and (getattr(svc, 'ref_range', None) or getattr(svc, 'unit', None)):
        ref_html = (f" · Reference: <b>{h(svc.ref_range or '—')}</b>"
                    f"{(' ' + h(svc.unit)) if svc.unit else ''}")
    fields=[dict(name='result',label='Test Result' + (f' (unit: {svc.unit})' if svc and getattr(svc,'unit',None) else ''),type='textarea',full=True,default=o.result or '')]
    return page('Enter Result', f"<div class='panel'><div class='pad' style='color:var(--muted)'>Patient: <b>{h(o.patient.name if o.patient else '—')}</b> · Test: <b>{h(o.service.name if o.service else '—')}</b>{ref_html}</div></div>"+
                render_form('Result Entry',url_for('lab.lab_result',oid=oid),fields,back=url_for('modules.module',mod='lab')),'lab')

@bp.route('/lab/<int:oid>/amend', methods=['GET', 'POST'])
@login_required
def lab_amend(oid):
    """Amend an APPROVED (locked) lab result. The previous result is preserved in a
    ResultAmendment record; nothing in clinical history is overwritten. Requires a
    reason and is limited to authorized roles."""
    from ..models import ResultAmendment
    o = LabOrder.query.get_or_404(oid)
    _role = cur_user().role
    if _role not in ('super_admin', 'lab_tech', 'doctor'):
        flash('You are not authorized to amend an approved result.')
        return redirect(url_for('modules.module', mod='lab'))
    if o.status != 'Approved' and not o.locked:
        flash('Only an approved, locked result can be amended.')
        return redirect(url_for('lab.lab_result', oid=oid))
    if request.method == 'POST':
        new_result = request.form.get('result') or ''
        reason = (request.form.get('reason') or '').strip()
        if not reason:
            flash('A reason is required to amend a result.')
            return redirect(url_for('lab.lab_amend', oid=oid))
        prev = o.result or ''
        db.session.add(ResultAmendment(
            kind='lab', order_id=o.id, prev_result=prev, new_result=new_result,
            reason=reason[:300], amended_by=cur_user().username,
            amended_at=dt.datetime.now().strftime('%Y-%m-%d %H:%M')))
        o.result = new_result
        o.result_by = cur_user().username
        # stays Approved + locked; re-run panic/delta checks on the new value
        _run_result_checks(o)
        db.session.commit()
        log(f'Lab #{oid} AMENDED by {cur_user().username} · reason: {reason}',
            action_type='Result Amendment', entity=f'LAB-{oid:04d}',
            old=prev[:120], new=new_result[:120], reason=reason)
        flash('Result amended — the previous version is preserved in the history.')
        return redirect(url_for('lab.lab_print', oid=oid))
    # GET — show current result + amendment history
    hist = ResultAmendment.query.filter_by(kind='lab', order_id=oid).order_by(ResultAmendment.id.desc()).all()
    hrows = ''.join(
        f"<tr><td>{h(a.amended_at)}</td><td>{h(a.amended_by)}</td>"
        f"<td><i>{h((a.prev_result or '')[:80])}</i></td><td><b>{h((a.new_result or '')[:80])}</b></td>"
        f"<td>{h(a.reason or '')}</td></tr>" for a in hist)
    hist_panel = (f"<div class='panel'><div class='ph'><h2>Amendment History</h2>"
                  f"<span class='so'>every prior version is preserved</span></div>"
                  f"<div class='tw'><table><thead><tr><th>When</th><th>By</th><th>Was</th><th>Amended to</th><th>Reason</th></tr></thead>"
                  f"<tbody>{hrows}</tbody></table></div></div>") if hrows else ''
    fields = [
        dict(name='result', label='Amended Result', type='textarea', full=True, default=o.result or ''),
        dict(name='reason', label='Reason for amendment (required)', type='text', full=True, default=''),
    ]
    warn = (f"<div class='panel' style='border-left:3px solid var(--amber)'><div class='pad' style='font-size:13px'>"
            f"<b style='color:var(--amber)'>🔒 Approved &amp; locked result</b> — LAB-{oid:04d} · "
            f"Patient <b>{h(o.patient.name if o.patient else '—')}</b> · Test <b>{h(o.service.name if o.service else '—')}</b>. "
            f"Amending creates a corrected version; the current result below is kept in history.</div></div>")
    return page('Amend Result', warn +
                render_form('Amend Approved Result', url_for('lab.lab_amend', oid=oid), fields,
                            back=url_for('lab.lab_print', oid=oid)) + hist_panel, 'lab')


@bp.route('/lab/<int:oid>/pdf')
@login_required
def lab_result_pdf_dl(oid):
    if not (can('lab') or can('labresults')):
        abort(403)
    o = LabOrder.query.get_or_404(oid)
    from flask import Response
    from ..core.pdfgen import lab_result_pdf, available
    from ..core.helpers import setting as _setting
    if not available():
        flash('Server PDF is unavailable on this deployment — use Print / Save PDF from the print view.')
        return redirect(url_for('lab.lab_print', oid=oid))
    data = lab_result_pdf(o, company=_setting('company', 'Modern Diagnostic Center'),
                          currency=_setting('currency', '$'))
    _dl = request.args.get('dl')
    _disp = 'attachment' if _dl else 'inline'
    log(f'{"Downloaded" if _dl else "Opened"} PDF LAB-{oid:04d}')
    return Response(data, mimetype='application/pdf',
                    headers={'Content-Disposition': f'{_disp};filename=LAB-{oid:04d}.pdf'})


@bp.route('/lab/<int:oid>/print')
@login_required
def lab_print(oid):
    o=LabOrder.query.get_or_404(oid)
    log(f'PRINT lab LAB-{oid:04d}')
    svc = o.service
    ref_line = ''
    if svc and (getattr(svc, 'ref_range', None) or getattr(svc, 'unit', None) or getattr(svc, 'loinc', None)):
        ref_line = (f"<p style='color:#555;font-size:13px'><b>Reference Range:</b> {h(svc.ref_range or '—')}"
                    f"{(' ' + h(svc.unit)) if svc.unit else ''}"
                    f"{(' · LOINC ' + h(svc.loinc)) if getattr(svc, 'loinc', None) else ''}</p>")
    panic_line = "<p style='color:#C62828;font-weight:700;border:1.5px solid #C62828;border-radius:6px;padding:6px 10px;display:inline-block'>⚠ CRITICAL / PANIC VALUE — clinician notified</p>" if o.panic else ''
    smp_line = f"<b>Sample:</b> {h(o.sample_no)} · {h(o.specimen or '—')} · collected {h(o.collected_at or '—')}<br>" if o.sample_no else ''
    from ..models import ResultAmendment
    _amn = ResultAmendment.query.filter_by(kind='lab', order_id=o.id).order_by(ResultAmendment.id.desc()).all()
    amend_line = ''
    if _amn:
        _last = _amn[0]
        amend_line = (f"<p style='color:#8A5A00;font-size:12.5px;border:1px solid #E7A100;border-radius:6px;padding:6px 10px'>"
                      f"<b>Amended report</b> — this result was corrected on {h(_last.amended_at or '')} by {h(_last.amended_by or '')} "
                      f"({len(_amn)} amendment{'s' if len(_amn)>1 else ''}). Reason: {h(_last.reason or '')}.</p>")
    return printable("Laboratory Report", f"""
      <p><b>Patient:</b> {h(o.patient.name if o.patient else '—')} ({h(o.patient.mrn if o.patient else '')})<br>
      {smp_line}<b>Test:</b> {h(o.service.name if o.service else '—')} · <b>Date:</b> {h(o.date)}</p>
      {panic_line}
      {amend_line}
      <h3>Result</h3><pre style="white-space:pre-wrap;font-family:inherit">{h(o.result or '')}</pre>
      {ref_line}
      <table style='margin-top:34px;width:100%;font-size:13px'><tr>
        <td>Performed by<br><b>{h(o.result_by or '—')}</b><br><span style='color:#888'>Lab Technician</span></td>
        <td>Verified &amp; Approved<br><b>{h(o.approved_by or '—')}</b><br><span style='color:#888'>Authorized Signatory</span></td>
      </tr></table>""",
      doc_ref=f"LAB-{o.id:04d}", barcode_text=(o.sample_no or (o.patient.mrn if o.patient else None)),
      signature=({'name': o.approved_by, 'title': 'Laboratory — Verified & Approved'} if o.status == 'Approved' and o.approved_by else None))


def _first_number(text):
    import re as _re
    m = _re.search(r'-?\d+(?:\.\d+)?', text or '')
    return float(m.group(0)) if m else None


def _run_result_checks(o):
    """Panic-value and delta checks on a freshly entered result."""
    o.panic = False; o.delta_flag = False
    v = _first_number(o.result)
    svc = o.service
    if v is None or not svc:
        return
    lo, hi = svc.panic_low, svc.panic_high
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        o.panic = True
        from ..core.notify import notify
        notify(f'⚠ PANIC {svc.name}: {v:g} {svc.unit or ""} · '
               f'{o.patient.name if o.patient else "—"} (LAB-{o.id:04d})',
               link='/m/lab', role='doctor')
        # Structured critical-result alert (acknowledgement workflow). Only one
        # open alert per order — refreshed if the value changes on amendment.
        from ..models import CriticalAlert
        import datetime as _dtm
        _rng = []
        if lo is not None: _rng.append(f'low {lo:g}')
        if hi is not None: _rng.append(f'high {hi:g}')
        ex = CriticalAlert.query.filter_by(lab_order_id=o.id, acknowledged=False).first()
        if not ex:
            ex = CriticalAlert(lab_order_id=o.id); db.session.add(ex)
        ex.patient_id = o.patient_id
        ex.patient_name = o.patient.name if o.patient else '—'
        ex.test_name = svc.name
        ex.value = f'{v:g} {svc.unit or ""}'.strip()
        ex.critical_range = ' / '.join(_rng)
        ex.raised_at = _dtm.datetime.now().strftime('%Y-%m-%d %H:%M')
        try:
            ex.raised_by = cur_user().username
        except Exception:
            ex.raised_by = 'system'
        ex.notified_role = 'doctor'
    prev = (LabOrder.query.filter(LabOrder.patient_id == o.patient_id,
                                  LabOrder.service_id == o.service_id,
                                  LabOrder.id < o.id,
                                  LabOrder.status.in_(('Resulted', 'Approved')))
            .order_by(LabOrder.id.desc()).first())
    pv = _first_number(prev.result) if prev else None
    if pv not in (None, 0) and abs(v - pv) / abs(pv) > 0.5:
        o.delta_flag = True


def critical_alerts_view():
    """Critical-result board: every panic value, its alert, and its acknowledgement
    trail (who / when / action). Open alerts sit at the top until acknowledged."""
    from ..models import CriticalAlert
    if not (can('lab') or can('lis') or can('labresults')):
        return page('Denied', "<div class='panel'><div class='pad'><b>No access.</b></div></div>")
    alerts = CriticalAlert.query.order_by(CriticalAlert.acknowledged.asc(), CriticalAlert.id.desc()).all()
    _open = [a for a in alerts if not a.acknowledged]
    _done = [a for a in alerts if a.acknowledged]

    def _row(a, open_):
        if open_:
            ack = (f"<a class='btn sm primary' href='{url_for('lab.critical_ack', aid=a.id)}' "
                   f"onclick=\"var r=prompt('Action taken / comment (required to acknowledge):'); "
                   f"if(!r)return false; this.href=this.href.split('?')[0]+'?action='+encodeURIComponent(r); return true;\">Acknowledge</a>")
            ackcell = ack
        else:
            ackcell = (f"<span class='pill green'>✓ {h(a.ack_by or '—')}</span><div style='font-size:11px;color:var(--muted)'>"
                       f"{h(a.ack_at or '')}<br>{h(a.action or '')}</div>")
        return (f"<tr><td>{h(a.raised_at or '')}</td>"
                f"<td><b>{h(a.patient_name or '—')}</b></td>"
                f"<td>{h(a.test_name or '—')}</td>"
                f"<td class='num' style='color:var(--red);font-weight:700'>{h(a.value or '')}</td>"
                f"<td>{h(a.critical_range or '')}</td>"
                f"<td><a href='/lab/{a.lab_order_id}/print' target='_blank'>LAB-{a.lab_order_id:04d}</a></td>"
                f"<td>{ackcell}</td></tr>")

    open_rows = ''.join(_row(a, True) for a in _open) or "<tr><td colspan='7'><div class='empty'><b>No unacknowledged critical results</b>All clear.</div></td></tr>"
    done_rows = ''.join(_row(a, False) for a in _done)
    open_panel = (f"<div class='panel' style='border-left:3px solid var(--red)'><div class='ph'><h2>⚠ Unacknowledged Critical Results</h2>"
                  f"<span class='so'>{len(_open)} awaiting clinician acknowledgement</span></div>"
                  f"<div class='tw'><table><thead><tr><th>Raised</th><th>Patient</th><th>Test</th><th class='num'>Value</th>"
                  f"<th>Critical Range</th><th>Order</th><th>Acknowledge</th></tr></thead><tbody>{open_rows}</tbody></table></div></div>")
    done_panel = (f"<div class='panel'><div class='ph'><h2>Acknowledged</h2><span class='so'>audit trail</span></div>"
                  f"<div class='tw'><table><thead><tr><th>Raised</th><th>Patient</th><th>Test</th><th class='num'>Value</th>"
                  f"<th>Critical Range</th><th>Order</th><th>Acknowledgement</th></tr></thead><tbody>{done_rows}</tbody></table></div></div>") if done_rows else ''
    return page('Critical Results', open_panel + done_panel, 'critical')


@bp.route('/critical/<int:aid>/ack')
@login_required
def critical_ack(aid):
    """Acknowledge a critical result — requires an action/comment, recorded with
    the clinician and timestamp for audit."""
    from ..models import CriticalAlert
    if not (can('lab') or can('lis') or can('labresults')):
        abort(403)
    a = CriticalAlert.query.get_or_404(aid)
    action = (request.args.get('action') or '').strip()
    if not action:
        flash('An action / comment is required to acknowledge a critical result.')
        return redirect(url_for('modules.module', mod='critical'))
    a.acknowledged = True
    a.ack_by = cur_user().username
    a.ack_at = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    a.action = action[:400]
    # keep the LabOrder's quick flag in sync for LIS views
    o = LabOrder.query.get(a.lab_order_id)
    if o:
        o.panic_ack = True
    db.session.commit()
    log(f'Critical result LAB-{a.lab_order_id:04d} acknowledged by {a.ack_by} · action: {action}',
        action_type='Critical Ack', entity=f'LAB-{a.lab_order_id:04d}', new=action, reason=action)
    flash('Critical result acknowledged — recorded for audit.')
    return redirect(url_for('modules.module', mod='critical'))


@bp.route('/lab/<int:oid>/label')
@login_required
def lab_label(oid):
    """Small printable specimen label (barcode + patient + test)."""
    o = LabOrder.query.get_or_404(oid)
    if not o.sample_no: abort(404)
    body = f"""
    <div style='border:1.5px solid #1A3E8F;border-radius:8px;padding:10px;max-width:300px;font-size:12px'>
      <b style='font-size:14px'>{h(o.patient.name if o.patient else '—')}</b> · {h(o.patient.mrn if o.patient else '')}<br>
      {h(o.service.name if o.service else '—')} · {h(o.specimen or '')}<br>
      Collected: {h(o.collected_at or '')} by {h(o.collected_by or '')}
    </div>"""
    return printable(f'Specimen {o.sample_no}', body,
                     doc_ref=o.sample_no, barcode_text=o.sample_no)


# ---------------------------------------------------------------------------
# Laboratory Tests catalog (Odoo "Tests"-style). A read-only reference list of
# tests for lab staff. Price is HIDDEN from lab technicians and lab supervisors.
# ---------------------------------------------------------------------------
def lab_tests_catalog():
    from .modules import search_view, hl
    from flask import render_template
    u = cur_user()
    role = u.role if u else ''
    show_price = role not in ('lab_tech', 'lab_supervisor')

    base = Service.query.filter(Service.active == True)  # noqa: E712
    base, _sq, _fbar = search_view('labtests', Service, base,
                                   search_cols=['name', 'code', 'department', 'short_name'],
                                   date_field=None, basic=not show_price)
    tests = base.order_by(Service.department, Service.name).all()

    _tc = {'Laboratory': 'blue', 'Radiology': 'teal', 'Consultation': 'amber', 'Service': 'grey'}
    headers = ['Name', 'Code', 'Test Type'] + (['Price'] if show_price else [])
    aligns = ['', '', ''] + (['num'] if show_price else [])
    rows = []
    for s in tests:
        tt = s.department or 'Service'
        row = [
            f"<b>{hl(h(s.name), _sq)}</b>" + (f"<br><small style='color:var(--muted)'>{hl(h(s.short_name), _sq)}</small>" if s.short_name else ''),
            hl(h(s.code or '—'), _sq),
            f"<span class='pill {_tc.get(tt,'grey')}'>{h(tt)}</span>",
        ]
        if show_price:
            row.append(money(s.price))
        rows.append(row)

    note = ('' if show_price else
            "<div class='pad' style='color:var(--muted);font-size:12px'>Prices are hidden for your role.</div>")
    body = render_template('list_page.html', title=f'Tests ({len(tests)})',
                           toolbar='', headers=headers, aligns=aligns, rows=rows, filterbar=_fbar,
                           empty="<div class='empty'><b>No tests</b>No active tests in the catalog yet.</div>")
    return page('Laboratory Tests', note + body, 'labtests')
