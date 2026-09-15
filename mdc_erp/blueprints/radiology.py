"""Radiology workflow: orders, reporting, printing."""
import os
from flask import (Blueprint, request, redirect, url_for, session, send_file, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.security import (cur_user, can, login_required, log,
                             setting)
from ..core.ui import page, track_view, plink, pnamelink
from ..core.workflows import transition_target
from ..core.crud import (render_form, opt_patients, opt_services)
from ..core.printing import printable

bp = Blueprint('rad', __name__)

from werkzeug.utils import secure_filename
from ..config import DATA_DIR

RAD_UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads', 'rad')
ALLOWED_IMG = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
ALLOWED_FILES = ALLOWED_IMG | {'.dcm', '.zip', '.rar', '.pdf'}  # teleradiology uploads


def _order_images(o):
    return [f for f in (o.images or '').split(',') if f]


def _thumbs(o, portal=False):
    imgs = _order_images(o)
    if not imgs:
        return ''
    cells = ''.join(
        f"<a href='{url_for('rad.rad_image', oid=o.id, idx=i)}' target='_blank'>"
        f"<img src='{url_for('rad.rad_image', oid=o.id, idx=i)}' "
        f"style='height:110px;border:1px solid var(--line);border-radius:8px;object-fit:cover'></a>"
        for i in range(len(imgs)))
    return f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin:10px 0'>{cells}</div>"


def rad_list():
    from flask import render_template
    from .modules import search_view, hl
    from ..models import Patient
    show_unpaid = request.args.get('unpaid') == '1'
    _base = RadOrder.query.order_by(RadOrder.id.desc())

    def _rad_extra(q):
        conds = [RadOrder.patient.has(Patient.name.ilike(f'%{q}%')),
                 RadOrder.patient.has(Patient.mrn.ilike(f'%{q}%'))]
        digits = ''.join(ch for ch in q if ch.isdigit())
        if digits:
            try:
                conds.append(RadOrder.id == int(digits))
            except ValueError:
                pass
        return conds

    _base, _sq, _fbar = search_view('radiology', RadOrder, _base,
                                    search_cols=['modality', 'status', 'accession'], date_field='date',
                                    extra_or=_rad_extra, placeholder='Search patient, MRN, order no…')
    orders_all = _base.all()
    waiting_pay = [o for o in orders_all if o.paid_gate is False]
    orders = orders_all if show_unpaid else [o for o in orders_all if o.paid_gate is not False]
    rows=[]
    for o in orders:
        st={'Requested':'blue','Imaged':'amber','Draft':'amber','Reported':'green'}
        acts=''
        if o.status=='Requested': acts=f"<a class='btn sm' href='{url_for('rad.rad_action',oid=o.id,act='image')}'>Mark Imaged</a>"
        elif o.status=='Imaged': acts=f"<a class='btn sm' data-nodoc href='{url_for('rad.rad_report',oid=o.id)}'>Write Report</a>"
        elif o.status=='Draft': acts=f"<a class='btn sm primary' data-nodoc href='{url_for('rad.rad_report',oid=o.id)}'>✎ Edit Draft</a>"
        elif o.status=='Reported': acts=f"<a class='btn sm gh' data-nodoc href='{url_for('rad.rad_amend',oid=o.id)}'>Amend</a>"
        if o.status=='Imaged': acts+=f" <a class='btn sm primary' href='{url_for('rad.rad_dispatch',oid=o.id)}'>📤 Dispatch</a>"
        if o.assigned_rad_id and o.status!='Reported': acts+=f" <span class='pill teal'>→ {h(o.assigned_rad.name if o.assigned_rad else '')}</span>"
        acts+=f" <a class='btn gh sm' href='{url_for('rad.rad_thread',oid=o.id)}'>💬</a>"
        if o.status=='Reported': acts+=f" <a class='btn sm' href='{url_for('rad.rad_print',oid=o.id)}' target='_blank'>Print</a>"
        rows.append([
            h(o.date),
            plink(o.patient),
            f"<span class='pill grey'>{h(o.modality)}</span>",
            h(o.service.name if o.service else '—'),
            f"<span class='pill {st.get(o.status,'grey')}'>{h(o.status)}</span>",
            acts,
        ])
    gate_banner = (f"<div class='panel' style='border-left:3px solid var(--amber)'><div class='pad' style='font-size:13px'>"
                   f"⏳ <b>{len(waiting_pay)}</b> study request(s) waiting for payment — hidden until paid. "
                   f"<a href='?unpaid=1' style='color:var(--petrol)'>Show them</a></div></div>") if (waiting_pay and not show_unpaid) else (
                   f"<div class='panel' style='border-left:3px solid var(--amber)'><div class='pad' style='font-size:13px'>"
                   f"Showing UNPAID/pending studies. <a href='?' style='color:var(--petrol)'>Back to workable list</a></div></div>" if show_unpaid else '')
    if _sq:
        rows = [[hl(c, _sq) for c in row] for row in rows]
    # ---- Odoo stat band ----
    from datetime import date as _date
    _all = RadOrder.query.all()
    _tdy = _date.today().isoformat()
    def _n(*ss): return sum(1 for o in _all if o.status in ss)
    _css = """<style>
    .lr-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .lr-stat{flex:1;min-width:140px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:11px 14px;box-shadow:var(--shadow)}
    .lr-stat .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
    .lr-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
    .lr-stat.a{border-left:3px solid #2b7de9} .lr-stat.b{border-left:3px solid var(--amber)}
    .lr-stat.d{border-left:3px solid var(--green)} .lr-stat.e{border-left:3px solid var(--red)}
    .lr-stat.f{border-left:3px solid var(--petrol)}
    </style>"""
    def _sc(cls, l, v): return f"<div class='lr-stat {cls}'><div class='l'>{l}</div><div class='v'>{v}</div></div>"
    stats = (_css + "<div class='lr-stats'>"
             + _sc('a', 'Requested', _n('Requested'))
             + _sc('b', 'Imaged · Awaiting Report', _n('Imaged'))
             + _sc('d', 'Reported', _n('Reported'))
             + _sc('e', 'Waiting Payment', sum(1 for o in _all if o.paid_gate is False))
             + _sc('f', 'Today', sum(1 for o in _all if (o.date or '') == _tdy))
             + "</div>")
    toolbar=(f"<a class=\"btn\" href=\"{url_for('modules.module', mod='radiologists')}/new\">+ New Radiologist</a>"
             f"<a class=\"btn primary\" href=\"{url_for('rad.rad_new')}\">+ New Study</a>")
    body=render_template('list_page.html', title='Radiology'+(' · Unpaid' if show_unpaid else ''),
                         prefix=stats+gate_banner, toolbar=toolbar, filterbar=_fbar,
                         headers=['Date','Patient','Modality','Study','Status',''],
                         aligns=['','','','','','num'], rows=rows,
                         empty="<div class='empty'><b>No studies</b>Create an imaging request.</div>")
    return page('Radiology', body, 'radiology')

@bp.route('/rad/new', methods=['GET','POST'])
@login_required
def rad_new():
    if not can('radiology'): abort(403)
    if request.method=='POST':
        o=RadOrder(patient_id=request.form['patient_id'] or None, service_id=request.form['service_id'] or None, modality=request.form['modality'])
        db.session.add(o); db.session.commit(); log('Radiology study created'); flash('Study requested'); return redirect(url_for('modules.module',mod='radiology'))
    fields=[dict(name='patient_id',label='Patient',type='select',options=opt_patients(),required=True,default=request.args.get('patient','')),
            dict(name='modality',label='Modality',type='select',options=[('CT','CT Scan'),('MRI','MRI'),('X-Ray','X-Ray'),('Ultrasound','Ultrasound')]),
            dict(name='service_id',label='Study / Service',type='select',options=opt_services('Radiology'))]
    return page('New Study', render_form('New Imaging Request',url_for('rad.rad_new'),fields,back=url_for('modules.module',mod='radiology')),'radiology')

@bp.route('/rad/<int:oid>/<act>')
@login_required
def rad_action(oid, act):
    o=RadOrder.query.get_or_404(oid)
    if act == 'image':
        try:
            transition_target('radiology', o.status, act, cur_user().role)
        except (ValueError, PermissionError) as exc:
            flash(str(exc))
            return redirect(url_for('modules.module', mod='radiology'))
        o.status='Imaged'
    db.session.commit(); log(f'Rad #{oid} {act}'); flash('Updated'); return redirect(url_for('modules.module',mod='radiology'))

@bp.route('/rad/<int:oid>/report', methods=['GET','POST'])
@login_required
def rad_report(oid):
    o=RadOrder.query.get_or_404(oid)
    if o.locked or o.status == 'Reported':
        flash('This report is finalized and locked. Use "Amend Report" to issue a corrected version — the original is preserved.')
        return redirect(url_for('rad.rad_amend', oid=oid))
    if request.method=='POST':
        _finalize = (request.form.get('finalize') == '1')   # only Finalize locks the report
        if _finalize:
            try:
                # a draft that was already saved sits in 'Draft'; treat it as
                # 'Imaged' for the workflow transition check so finalize is allowed.
                _from = 'Imaged' if (o.status or '') == 'Draft' else o.status
                transition_target('radiology', _from, 'report', cur_user().role)
            except (ValueError, PermissionError) as exc:
                flash(str(exc))
                return redirect(url_for('modules.module', mod='radiology'))
        o.report=request.form.get('report'); o.image_note=request.form.get('image_note')
        o.technique=request.form.get('technique'); o.impression=request.form.get('impression'); o.clinical_data=request.form.get('clinical_data')
        o.radiologist=request.form.get('radiologist') or cur_user().username; o.fee=float(setting('rad_fee','10') or 10)
        if _finalize:
            o.status='Reported'; o.reported_by=cur_user().username
            o.locked = True   # finalized report is locked — corrections require an amendment
        else:
            # Save Draft: keep it editable so an accidental save is NOT locked.
            if o.status not in ('Reported',):
                o.status = 'Draft'
            o.locked = False
        # Link the report to the actual Radiologist record so the radiologist FEE
        # accrues to the right person. Match by the name entered, else by the
        # logged-in user's name/username (the radiologist writing the report).
        from ..models import Radiologist
        _rn = (o.radiologist or '').strip()
        _rad = (Radiologist.query.filter(Radiologist.name.ilike(_rn)).first() if _rn else None)
        if not _rad:
            _u = cur_user()
            _rad = Radiologist.query.filter(db.or_(
                Radiologist.name.ilike((_u.name or '').strip() or '\0'),
                Radiologist.name.ilike((_u.username or '').strip() or '\0'))).first()
        if _rad:
            o.assigned_rad_id = _rad.id
            o.radiologist = _rad.name   # normalise to the record's name
        # --- study image upload (Phase 2) ---
        saved = _order_images(o)
        os.makedirs(RAD_UPLOAD_DIR, exist_ok=True)
        for f in request.files.getlist('images'):
            if not f or not f.filename: continue
            ext = os.path.splitext(f.filename)[1].lower()
            if ext not in ALLOWED_IMG:
                flash(f'Skipped {f.filename}: only image files allowed'); continue
            name = secure_filename(f'rad{oid}_{len(saved)+1}_{f.filename}')
            f.save(os.path.join(RAD_UPLOAD_DIR, name)); saved.append(name)
        o.images = ','.join(saved)
        db.session.commit()
        if _finalize:
            log(f'Rad #{oid} finalized ({len(saved)} image(s))')
            from ..core.notify import notify_event
            notify_event('report_completed',
                         f'Report completed: {o.patient.name if o.patient else ""} · {o.service.name if o.service else "Study"} (RAD-{oid:04d})',
                         link=url_for('rad.rad_print', oid=oid))
            if getattr(o, 'invoice_id', None):
                from .billing import _maybe_complete
                _inv = Invoice.query.get(o.invoice_id)
                if _inv: _maybe_complete(_inv)
            flash('✓ Report finalized and locked. Use "Amend Report" if a correction is needed.')
            return redirect(url_for('modules.module',mod='radiology'))
        log(f'Rad #{oid} draft saved')
        flash('📝 Draft saved — you can still edit it. Click "Finalize Report" when it is ready.')
        return redirect(url_for('rad.rad_report', oid=oid))
    from ..models import Radiologist
    _rads = Radiologist.query.filter_by(active=True).order_by(Radiologist.name).all()
    _cur = o.radiologist or (o.reported_by or '')
    _ropts = [('', '— select radiologist —')] + [(r.name, f"{r.name}{(' · '+r.specialty) if r.specialty else ''}") for r in _rads]
    if _cur and _cur not in [r.name for r in _rads]:
        _ropts.append((_cur, f'{_cur} (current)'))
    fields=[dict(name='radiologist',label='Radiologist / Report reader',type='select',options=_ropts,default=_cur),
            dict(name='clinical_data',label='Clinical data / Indication',default=o.clinical_data or (o.ref.tests if getattr(o,'ref',None) else '')),
            dict(name='image_note',label='Image reference / DICOM note',default=o.image_note or ''),
            dict(name='images',label='Attach Study Images (JPG/PNG, multiple)',type='file',multiple=True,full=True),
            dict(name='technique',label='Technique',type='textarea',full=True,default=o.technique or ''),
            dict(name='report',label='Findings',type='textarea',full=True,default=o.report or ''),
            dict(name='impression',label='Impression / Conclusion',type='textarea',full=True,default=o.impression or '')]
    existing = _thumbs(o)
    existing_html = f"<div class='panel'><div class='ph'><h2>Attached Images ({len(_order_images(o))})</h2></div><div class='pad'>{existing}</div></div>" if existing else ''
    _is_draft = (o.status or '') not in ('Reported',)
    draft_banner = ("<div class='panel'><div class='pad' style='background:#FFF7E6;border-left:3px solid var(--amber)'>"
                    "📝 <b>Draft</b> — this report is still editable. Use <b>Save Draft</b> to keep working "
                    "(so an accidental save won't lock it), and <b>Finalize Report</b> only when it is ready. "
                    "Once finalized it locks, and any correction is done via <b>Amend</b>.</div></div>") if _is_draft else ''
    # Two-button footer: Save Draft (editable) vs Finalize (locks). JS sets the
    # hidden 'finalize' flag on the report form before submitting.
    two_btns = """
    <div class="panel"><div class="pad" style="display:flex;gap:10px;justify-content:flex-end">
      <a class="btn gh" href="%s">Cancel</a>
      <button type="button" class="btn" onclick="_radSubmit(0)">💾 Save Draft</button>
      <button type="button" class="btn primary" onclick="if(confirm('Finalize this report? It will be locked; later changes need an Amendment.'))_radSubmit(1)">✔ Finalize Report</button>
    </div></div>
    <script>
    function _radSubmit(fin){
      var form=document.querySelector('form[action*="/rad/"]') || document.querySelector('form');
      if(!form) return;
      var h=form.querySelector('input[name=finalize]');
      if(!h){ h=document.createElement('input'); h.type='hidden'; h.name='finalize'; form.appendChild(h); }
      h.value=fin?'1':'0';
      // hide the template's default submit so only our two buttons are used
      form.submit();
    }
    // hide the default single submit button from render_form
    document.addEventListener('DOMContentLoaded',function(){
      var f=document.querySelector('form[action*="/rad/"]') || document.querySelector('form');
      if(f){ f.querySelectorAll('button[type=submit],input[type=submit]').forEach(function(b){b.style.display='none';}); }
    });
    </script>""" % url_for('modules.module', mod='radiology')
    return page('Write Report', f"<div class='panel'><div class='pad' style='color:var(--muted)'>Patient: <b>{h(o.patient.name if o.patient else '—')}</b> · {h(o.modality)}</div></div>"+draft_banner+existing_html+
                render_form('Radiology Report',url_for('rad.rad_report',oid=oid),fields,back=url_for('modules.module',mod='radiology'),enctype='multipart/form-data')+two_btns,'radiology')

@bp.route('/rad/<int:oid>/amend', methods=['GET', 'POST'])
@login_required
def rad_amend(oid):
    """Amend a FINALIZED (locked) radiology report. The previous findings/impression
    are preserved in a ResultAmendment; clinical history is never overwritten.
    Requires a reason and is limited to authorized roles."""
    from ..models import ResultAmendment
    import datetime as dt
    o = RadOrder.query.get_or_404(oid)
    _role = cur_user().role
    if _role not in ('super_admin', 'radiologist', 'doctor', 'rad_tech'):
        flash('You are not authorized to amend a finalized report.')
        return redirect(url_for('modules.module', mod='radiology'))
    if o.status != 'Reported' and not o.locked:
        flash('Only a finalized, locked report can be amended.')
        return redirect(url_for('rad.rad_report', oid=oid))

    def _combined(order):
        parts = []
        if order.technique: parts.append(f'Technique: {order.technique}')
        if order.report: parts.append(f'Findings: {order.report}')
        if order.impression: parts.append(f'Impression: {order.impression}')
        return '\n'.join(parts)

    if request.method == 'POST':
        reason = (request.form.get('reason') or '').strip()
        if not reason:
            flash('A reason is required to amend a report.')
            return redirect(url_for('rad.rad_amend', oid=oid))
        prev = _combined(o)
        o.technique = request.form.get('technique')
        o.report = request.form.get('report')
        o.impression = request.form.get('impression')
        o.reported_by = cur_user().username
        new = _combined(o)
        db.session.add(ResultAmendment(
            kind='rad', order_id=o.id, prev_result=prev, new_result=new,
            reason=reason[:300], amended_by=cur_user().username,
            amended_at=dt.datetime.now().strftime('%Y-%m-%d %H:%M')))
        db.session.commit()
        log(f'Rad #{oid} report AMENDED by {cur_user().username} · reason: {reason}',
            action_type='Report Amendment', entity=f'RAD-{oid:04d}',
            old=prev[:120], new=new[:120], reason=reason)
        flash('Report amended — the previous version is preserved in the history.')
        return redirect(url_for('rad.rad_print', oid=oid))

    hist = ResultAmendment.query.filter_by(kind='rad', order_id=oid).order_by(ResultAmendment.id.desc()).all()
    hrows = ''.join(
        f"<tr><td>{h(a.amended_at)}</td><td>{h(a.amended_by)}</td>"
        f"<td><i>{h((a.prev_result or '')[:70])}</i></td><td><b>{h((a.new_result or '')[:70])}</b></td>"
        f"<td>{h(a.reason or '')}</td></tr>" for a in hist)
    hist_panel = (f"<div class='panel'><div class='ph'><h2>Amendment History</h2>"
                  f"<span class='so'>every prior version is preserved</span></div>"
                  f"<div class='tw'><table><thead><tr><th>When</th><th>By</th><th>Was</th><th>Amended to</th><th>Reason</th></tr></thead>"
                  f"<tbody>{hrows}</tbody></table></div></div>") if hrows else ''
    fields = [
        dict(name='technique', label='Technique', type='textarea', full=True, default=o.technique or ''),
        dict(name='report', label='Findings', type='textarea', full=True, default=o.report or ''),
        dict(name='impression', label='Impression / Conclusion', type='textarea', full=True, default=o.impression or ''),
        dict(name='reason', label='Reason for amendment (required)', type='text', full=True, default=''),
    ]
    warn = (f"<div class='panel' style='border-left:3px solid var(--amber)'><div class='pad' style='font-size:13px'>"
            f"<b style='color:var(--amber)'>🔒 Finalized &amp; locked report</b> — RAD-{oid:04d} · "
            f"Patient <b>{h(o.patient.name if o.patient else '—')}</b> · {h(o.modality or '')} "
            f"<b>{h(o.service.name if o.service else '')}</b>. Amending issues a corrected version; "
            f"the current report is kept in history.</div></div>")
    return page('Amend Report', warn +
                render_form('Amend Finalized Report', url_for('rad.rad_amend', oid=oid), fields,
                            back=url_for('rad.rad_print', oid=oid)) + hist_panel, 'radiology')


@bp.route('/rad/<int:oid>/print')
@login_required
def rad_print(oid):
    o=RadOrder.query.get_or_404(oid)
    log(f'PRINT radiology RAD-{oid:04d}')
    imgs=_order_images(o)
    img_html=('<h3 style="color:#103D46;margin:18px 0 6px">Images</h3><div style="display:flex;gap:8px;flex-wrap:wrap">'+
              ''.join(f"<img src='{url_for('rad.rad_image',oid=o.id,idx=i)}' style='max-height:160px;border:1px solid #ccc;border-radius:6px'>" for i in range(len(imgs)))+'</div>') if imgs else ''
    p = o.patient
    # patient age from DOB when available
    age = '—'
    _dob = getattr(p, 'dob', None) if p else None
    if _dob:
        try:
            import datetime as _dt
            b = _dt.date.fromisoformat(str(_dob)[:10]); t = _dt.date.today()
            age = f'{t.year - b.year - ((t.month, t.day) < (b.month, b.day))} yrs'
        except Exception:
            age = '—'
    requested_by = (o.ref.doctor_name if getattr(o, 'ref', None) and getattr(o.ref, 'doctor_name', None)
                    else (o.referring_doctor.name if getattr(o, 'referring_doctor', None) else '—'))
    clinical = h(o.clinical_data or (o.ref.tests if getattr(o, 'ref', None) and getattr(o.ref, 'tests', None) else '') or '—')
    study = h(o.service.name if o.service else '')
    _st = (o.service.name if o.service else '').strip()
    _mod = (o.modality or '').strip()
    if _st and _mod and _mod.lower() in _st.lower():
        title_line = h(_st.upper() + " REPORT")
    elif _st:
        title_line = h(f"{_mod} {_st}".strip().upper() + " REPORT")
    else:
        title_line = h((f"{_mod} REPORT").strip().upper() or "RADIOLOGY REPORT")

    # radiologist credentials (from the Radiologist record if linked by name)
    from ..models import Radiologist
    _rad = Radiologist.query.filter_by(name=o.radiologist).first() if o.radiologist else None
    creds = 'CONSULTANT RADIOLOGIST'
    if _rad:
        bits = []
        if _rad.specialty: bits.append(_rad.specialty)
        else: bits.append('MD, Consultant Radiologist')
        if _rad.license_no: bits.append(f'License {_rad.license_no}')
        creds = ' · '.join(bits)

    def _section(label, text):
        if not (text or '').strip():
            return ''
        return (f"<h3 style='color:#103D46;margin:9px 0 3px;font-size:15px'>{label}</h3>"
                f"<div style='white-space:pre-wrap;line-height:1.5'>{h(text)}</div>")

    from ..models import ResultAmendment
    _amn = ResultAmendment.query.filter_by(kind='rad', order_id=o.id).order_by(ResultAmendment.id.desc()).all()
    amend_line = ''
    if _amn:
        _last = _amn[0]
        amend_line = (f"<p style='color:#8A5A00;font-size:12.5px;border:1px solid #E7A100;border-radius:6px;padding:6px 10px;text-align:center'>"
                      f"<b>AMENDED REPORT</b> — corrected on {h(_last.amended_at or '')} by {h(_last.amended_by or '')} "
                      f"({len(_amn)} amendment{'s' if len(_amn)>1 else ''}). Reason: {h(_last.reason or '')}.</p>")

    body = f"""
      <table style="width:100%;border-collapse:collapse;margin:4px 0 10px;font-size:13.5px">
        <tr>
          <td style="border:1px solid #cfd9db;padding:7px 10px;width:50%"><b>Client Name:</b> {h(p.name if p else '—')}</td>
          <td style="border:1px solid #cfd9db;padding:7px 10px"><b>Clinical data:</b> {clinical}</td>
        </tr>
        <tr>
          <td style="border:1px solid #cfd9db;padding:7px 10px"><b>Sex:</b> {h(p.gender if p else '—')} &nbsp;·&nbsp; <b>Age:</b> {h(age)}</td>
          <td style="border:1px solid #cfd9db;padding:7px 10px"><b>Requested by:</b> {h(requested_by)}</td>
        </tr>
        <tr>
          <td style="border:1px solid #cfd9db;padding:7px 10px"><b>MRN:</b> {h(p.mrn if p else '—')} &nbsp;·&nbsp; <b>Study No:</b> RAD-{o.id:04d}</td>
          <td style="border:1px solid #cfd9db;padding:7px 10px"><b>Date:</b> {h(o.date)}</td>
        </tr>
      </table>
      <h2 style="text-align:center;color:#103D46;font-family:'Space Grotesk';letter-spacing:.5px;margin:6px 0 3px">{title_line}</h2>
      {amend_line}
      {_section('Technique:', o.technique)}
      {_section('Findings:', o.report)}
      {_section('Impression:', o.impression)}
      {img_html}
      <div style="margin-top:20px">
        <div style="font-weight:700;color:#103D46;font-size:15px">DR. {h((o.radiologist or o.reported_by or '').upper())}</div>
        <div style="color:#555;font-size:12.5px;text-transform:uppercase;letter-spacing:.5px">{h(creds)}</div>
      </div>"""
    return printable("Radiology Report", body,
                     doc_ref=f"RAD-{o.id:04d}", barcode_text=(o.patient.mrn if o.patient else None),
                     signature=({'name': o.radiologist or o.reported_by, 'title': creds.title()} if o.status == 'Reported' and (o.radiologist or o.reported_by) else None))


@bp.route('/rad/<int:oid>/img/<int:idx>')
def rad_image(oid, idx):
    """Serve a study image to staff (radiology access) or the owning portal patient."""
    o = RadOrder.query.get_or_404(oid)
    staff_ok = cur_user() is not None and can('radiology')
    portal_ok = session.get('portal_pid') and session.get('portal_pid') == o.patient_id
    dr_ok = False
    if session.get('dr_id') and o.ref_id:
        from ..models import Referral
        _r = Referral.query.get(o.ref_id)
        dr_ok = bool(_r and _r.doctor_id == session['dr_id'])
    rrad_ok = bool(session.get('rrad_id') and o.assigned_rad_id == session.get('rrad_id'))
    if not (staff_ok or portal_ok or dr_ok or rrad_ok):
        abort(403)
    imgs = _order_images(o)
    if idx < 0 or idx >= len(imgs):
        abort(404)
    return send_file(os.path.join(RAD_UPLOAD_DIR, imgs[idx]))


@bp.route('/rad/<int:oid>/dispatch', methods=['GET', 'POST'])
@login_required
def rad_dispatch(oid):
    """Technician uploads study files and assigns a remote radiologist."""
    if not can('radiology'): abort(403)
    from ..models import Radiologist
    o = RadOrder.query.get_or_404(oid)
    if request.method == 'POST':
        saved = _order_images(o)
        os.makedirs(RAD_UPLOAD_DIR, exist_ok=True)
        for f in request.files.getlist('files'):
            if not f or not f.filename: continue
            ext = os.path.splitext(f.filename)[1].lower()
            if ext not in ALLOWED_FILES:
                flash(f'Skipped {f.filename}: type not allowed'); continue
            name = secure_filename(f'rad{oid}_{len(saved)+1}_{f.filename}')
            f.save(os.path.join(RAD_UPLOAD_DIR, name)); saved.append(name)
        o.images = ','.join(saved)
        rid = request.form.get('radiologist_id')
        if not rid and not o.assigned_rad_id:
            flash('Radiologist not assigned. Please select a radiologist before dispatching this study.')
            return redirect(url_for('rad.rad_dispatch', oid=oid))
        if rid:
            o.assigned_rad_id = int(rid)
            r = Radiologist.query.get(int(rid))
            if r and r.phone:
                from ..core.messaging import queue_msg
                queue_msg(r.phone, f'Dr {r.name}: new {o.modality or ""} case assigned '
                                   f'({o.patient.name if o.patient else ""}). Portal: /rrad',
                          ref=f'RAD-{oid:04d}')
        db.session.commit()
        log(f'Rad #{oid} dispatched ({len(saved)} file(s))')
        flash('Case dispatched to radiologist')
        return redirect(url_for('modules.module', mod='radiology'))
    rads = Radiologist.query.filter_by(active=True).order_by(Radiologist.name).all()
    opts = ''.join(f"<option value='{r.id}' {'selected' if o.assigned_rad_id==r.id else ''}>"
                   f"{h(r.name)}{(' · '+h(r.specialty)) if r.specialty else ''}</option>" for r in rads)
    files = _order_images(o)
    flist = ''.join(f"<div style='font-size:13px;padding:2px 0'>📎 {h(f_)}</div>" for f_ in files) or \
            "<span style='color:var(--muted);font-size:13px'>No files yet.</span>"
    body = f"""<div class='panel'><div class='ph'><h2>Dispatch RAD-{o.id:04d} · {h(o.patient.name if o.patient else '—')}</h2>
      <div class='sp'></div><a class='btn sm' href='{url_for('modules.module', mod='radiology')}'>← Back</a></div>
      <div class='pad'>
      <p style='color:var(--muted);font-size:13px'>{h(o.modality or '')} · {h(o.service.name if o.service else '—')}</p>
      <div style='margin:8px 0'>{flist}</div>
      <form method='post' enctype='multipart/form-data'><div class='fg'>
        <div class='fld full'><label>Upload study files (DICOM .dcm, ZIP, RAR, PDF, JPG, PNG — multiple)</label>
          <input type='file' name='files' multiple accept='.dcm,.zip,.rar,.pdf,image/*'></div>
        <div class='fld full'><label>Assign to Remote Radiologist</label>
          <select name='radiologist_id'><option value=''>—</option>{opts}</select></div>
        <div class='fld full'><button class='btn primary'>📤 Dispatch Case</button></div>
      </div></form></div></div>"""
    return page('Dispatch Case', body, 'radiology')


@bp.route('/rad/<int:oid>/thread', methods=['GET', 'POST'])
@login_required
def rad_thread(oid):
    if not can('radiology'): abort(403)
    from ..models import RadComment
    o = RadOrder.query.get_or_404(oid)
    try: track_view('radiology', o.id, f"RAD-{o.id:04d}"+(' · '+o.patient.name if o.patient else ''), url_for('rad.rad_thread', oid=o.id))
    except Exception: pass
    if request.method == 'POST':
        txt = (request.form.get('text') or '').strip()[:500]
        if txt:
            db.session.add(RadComment(rad_id=oid, author=cur_user().name or cur_user().username,
                                      is_remote=False, text=txt))
            db.session.commit(); log(f'Comment on RAD-{oid:04d}')
        return redirect(url_for('rad.rad_thread', oid=oid))
    cmts = ''.join(
        f"<div style='margin:6px 0;padding:8px 12px;border-radius:10px;background:{'#FFF6EC' if c.is_remote else 'var(--canvas)'}'>"
        f"<b style='font-size:12.5px;color:var(--petrol)'>{h(c.author)}</b> "
        f"<span style='color:var(--muted);font-size:11px'>{c.created.strftime('%d-%b %H:%M') if c.created else ''}</span>"
        f"<div style='font-size:13.5px'>{h(c.text)}</div></div>"
        for c in sorted(o.case_comments, key=lambda x: x.id)) or \
        "<p style='color:var(--muted);font-size:13px'>No comments yet.</p>"
    body = f"""<div class='panel'><div class='ph'><h2>RAD-{o.id:04d} · {h(o.patient.name if o.patient else '—')} — Case Thread</h2>
      <div class='sp'></div><a class='btn sm' href='{url_for('modules.module', mod='radiology')}'>← Radiology</a></div>
      <div class='pad'>{cmts}
      <form method='post' style='margin-top:10px'><div style='display:flex;gap:8px'>
        <input name='text' maxlength='500' placeholder='Message to the radiologist…' style='flex:1;border:1px solid var(--line);border-radius:9px;padding:9px 12px'>
        <button class='btn primary'>Send</button></div></form></div></div>"""
    return page(f'RAD-{o.id:04d}', body, 'radiology')
