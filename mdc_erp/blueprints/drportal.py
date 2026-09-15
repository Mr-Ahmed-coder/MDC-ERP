"""Doctor Referral Portal — secure portal for external referring doctors.

Doctors log in with portal credentials set on their Doctor record
(Clinical → Referring Doctors). They can register patients, request
laboratory/radiology investigations, track status, read approved
reports and discuss cases — with NO access to prices, billing,
accounting or any staff module (separate session, separate shell).
"""

from flask import (Blueprint, request, redirect, url_for, session, abort, jsonify)
from markupsafe import escape as h
from werkzeug.security import check_password_hash

from ..extensions import db
from ..models import (Doctor, Patient, Referral, RefComment, LabOrder,
                      RadOrder, Service)
from ..core.security import csrf_token
from ..core.ui import public_shell
from ..core.notify import notify

bp = Blueprint('drportal', __name__)

STATUS_LABEL = {  # internal -> doctor-friendly
    'Requested': 'Waiting', 'Collected': 'Sample Collected',
    'Received': 'Under Testing', 'Resulted': 'Under Reporting',
    'Approved': 'Completed', 'Imaged': 'Under Reporting',
    'Reported': 'Completed'}
STATUS_COLOR = {'Waiting': 'amber', 'Sample Collected': 'blue',
                'Under Testing': 'blue', 'Under Reporting': 'teal',
                'Completed': 'green'}


def cur_doctor():
    did = session.get('dr_id')
    return Doctor.query.get(did) if did else None


def _guard():
    d = cur_doctor()
    if not d or not d.active:
        return None
    return d


def _csrf_input():
    return f"<input type='hidden' name='_csrf' value='{csrf_token()}'>"


# ------------------------------------------------------------------ auth
@bp.route('/dr', methods=['GET', 'POST'])
def dr_login():
    err = ''
    if request.method == 'POST':
        u = (request.form.get('username') or '').strip()
        d = Doctor.query.filter_by(portal_user=u).first()
        if d and d.active and d.portal_pw and check_password_hash(
                d.portal_pw, request.form.get('password') or ''):
            session['dr_id'] = d.id
            return redirect(url_for('drportal.dr_home'))
        err = 'Invalid username or password'
    body = f"""<div class='panel' style='max-width:420px;margin:30px auto'>
      <div class='pad'>
      <h2 style='color:var(--petrol);font-family:Space Grotesk;text-align:center'>Doctor Referral Portal</h2>
      <p style='color:var(--muted);font-size:13px;text-align:center'>Modern Diagnostic Center · Gaalkacyo</p>
      {f"<div style='background:var(--red-soft);color:var(--red);border-radius:8px;padding:8px 12px;font-size:13px;margin-bottom:8px'>{h(err)}</div>" if err else ''}
      <form method='post'>{_csrf_input()}<div class='fg'>
        <div class='fld full'><label>Username</label><input name='username' required autofocus></div>
        <div class='fld full'><label>Password</label><input name='password' type='password' required></div>
        <div class='fld full'><button class='btn primary' style='width:100%'>Sign in</button></div>
      </div></form>
      <p style='color:var(--muted);font-size:12px;text-align:center;margin-top:10px'>
        Akoon ma lihid? La xiriir MDC si laguu furo.<br>
        <a href='/refer' style='color:var(--petrol)'>Gudbin degdeg ah oo login la'aan →</a></p>
      </div></div>"""
    return public_shell('Doctor Portal', body)


@bp.route('/dr/logout')
def dr_logout():
    session.pop('dr_id', None)
    return redirect(url_for('drportal.dr_login'))


# ------------------------------------------------------------------ dashboard
@bp.route('/dr/home')
def dr_home():
    d = _guard()
    if not d: return redirect(url_for('drportal.dr_login'))
    refs = (Referral.query.filter_by(doctor_id=d.id)
            .order_by(Referral.id.desc()).all())
    q = (request.args.get('q') or '').strip().lower()

    def ref_state(r):
        orders = (LabOrder.query.filter_by(ref_id=r.id).all()
                  + RadOrder.query.filter_by(ref_id=r.id).all())
        if not orders:
            return 'Waiting', 0, 0
        done = sum(1 for o in orders if o.status in ('Approved', 'Reported'))
        if done == len(orders):
            return 'Completed', done, len(orders)
        return STATUS_LABEL.get(
            sorted((o.status for o in orders),
                   key=lambda s_: list(STATUS_LABEL).index(s_) if s_ in STATUS_LABEL else 0)[0],
            'Waiting'), done, len(orders)

    rows = ''
    pend = comp = 0
    for r in refs:
        st, done, tot = ref_state(r)
        if st == 'Completed': comp += 1
        else: pend += 1
        if q and q not in (r.patient_name or '').lower() and q not in (r.patient_phone or ''):
            continue
        pr = ("<span class='pill red'>STAT</span>" if r.priority == 'STAT'
              else "<span class='pill amber'>Urgent</span>" if r.priority == 'Urgent' else '')
        rows += (f"<tr><td><b>REF-{r.id:04d}</b><div style='color:var(--muted);font-size:11px'>{h(r.date)}</div></td>"
                 f"<td><b>{h(r.patient_name or '—')}</b><div style='color:var(--muted);font-size:11px'>{h(r.patient_phone or '')}</div></td>"
                 f"<td style='font-size:12.5px'>{h((r.tests or '—')[:60])}</td><td>{pr}</td>"
                 f"<td><span class='pill {STATUS_COLOR.get(st,'grey')}'>{h(st)}</span>"
                 f"<div style='color:var(--muted);font-size:11px'>{done}/{tot} report(s)</div></td>"
                 f"<td class='num'><a class='btn sm primary' href='/dr/req/{r.id}'>Open</a></td></tr>")
    rows = rows or "<tr><td colspan='6' style='color:var(--muted);padding:16px'>No referrals yet — press “New Referral”.</td></tr>"
    k = lambda n, v, c='var(--petrol)': (f"<div class='panel' style='flex:1;min-width:130px'><div class='pad'>"
        f"<div style='font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase'>{n}</div>"
        f"<div style='font-family:Space Grotesk;font-weight:700;font-size:26px;color:{c}'>{v}</div></div></div>")
    body = f"""
    <div class='panel'><div class='pad' style='display:flex;align-items:center;gap:12px;flex-wrap:wrap'>
      <div><div style='font-family:Space Grotesk;font-weight:700;font-size:18px;color:var(--petrol)'>Dr {h(d.name)}</div>
      <div style='color:var(--muted);font-size:12.5px'>{h(d.specialty or 'Referring Doctor')}</div></div>
      <div class='sp'></div>
      <a class='btn primary' style='padding:12px 22px;font-size:15px' href='/dr/new'>➕ New Referral</a>
      <a class='btn sm' href='/dr/logout'>Logout</a></div></div>
    <div style='display:flex;gap:12px;flex-wrap:wrap'>{k('My Referrals', len(refs))}{k('Pending', pend, 'var(--amber)' if pend else 'var(--green)')}{k('Completed Reports', comp, 'var(--green)')}</div>
    <div class='panel'><div class='ph'><h2>My Requests</h2><div class='sp'></div>
      <form method='get'><input name='q' value='{h(q)}' placeholder='Search my patients…' style='border:1px solid var(--line);border-radius:9px;padding:7px 12px;font-size:13px'></form></div>
      <div class='tw'><table><thead><tr><th>Request</th><th>Patient</th><th>Investigations</th><th></th><th>Status</th><th></th></tr></thead>
      <tbody>{rows}</tbody></table></div></div>"""
    return public_shell('Doctor Portal', body)


# ------------------------------------------------------------------ new referral
@bp.route('/dr/patient-lookup')
def dr_patient_lookup():
    """Portal-safe returning-patient lookup for the doctor request form.
    To protect privacy, an external doctor can only match by EXACT phone or EXACT
    MRN (details they already hold for their own patient) — not browse by name."""
    d = _guard()
    if not d:
        return jsonify({'error': 'unauthorized'}), 401
    q = (request.args.get('q') or '').strip()
    if len(q) < 4:
        return jsonify([])
    rows = (Patient.query
            .filter(db.or_(Patient.phone == q, Patient.mrn == q,
                           Patient.mrn == q.upper()))
            .limit(5).all())
    out = [{'id': p.id, 'mrn': p.mrn or '', 'name': p.name or '',
            'phone': p.phone or '', 'gender': p.gender or '',
            'age': p.age if p.age is not None else ''} for p in rows]
    return jsonify(out)


@bp.route('/dr/new', methods=['GET', 'POST'])
def dr_new():
    d = _guard()
    if not d: return redirect(url_for('drportal.dr_login'))
    if request.method == 'POST':
        sids = [int(x) for x in request.form.getlist('svc') if x.isdigit()]
        if not sids:
            return redirect(url_for('drportal.dr_new', err='notest'))
        phone = (request.form.get('phone') or '').strip()
        # parse the entered age → whole number of years (accepts "45", "45 yrs", "45y")
        _age_raw = (request.form.get('age') or '').strip()
        _age_num = None
        if _age_raw:
            import re as _re
            _m = _re.search(r'\d+', _age_raw)
            if _m:
                try:
                    _v = int(_m.group())
                    if 0 <= _v <= 130:
                        _age_num = _v
                except Exception:
                    _age_num = None
        # A returning patient may have been picked from the lookup (exact record),
        # else fall back to matching by phone — either way, no duplicate.
        p = None
        _sel = request.form.get('patient_id')
        if _sel and str(_sel).isdigit():
            p = Patient.query.get(int(_sel))
        if not p and phone:
            p = Patient.query.filter_by(phone=phone).first()
        if not p:
            p = Patient(mrn='MRN' + str((Patient.query.count() or 0) + 1001),
                        name=request.form.get('name'), phone=phone,
                        gender=request.form.get('gender'),
                        age_years=_age_num,
                        address=request.form.get('address'),
                        allergies=request.form.get('allergies'),
                        med_history=request.form.get('history'),
                        notes=f'Referred by Dr {d.name}',
                        reg_by=f'Dr {d.name} (portal)')
            db.session.add(p); db.session.flush()
        elif _age_num is not None and p.age is None:
            # existing patient with no age on file → fill it from this request
            p.age_years = _age_num
            db.session.flush()
        r = Referral(patient_name=p.name, patient_phone=p.phone,
                     patient_age=request.form.get('age'),
                     patient_gender=p.gender, doctor_id=d.id,
                     doctor_name=d.name, patient_id=p.id,
                     complaint=request.form.get('complaint'),
                     prov_dx=request.form.get('prov_dx'),
                     priority=request.form.get('priority') or 'Routine',
                     instructions=request.form.get('instructions'),
                     notes=request.form.get('history'), status='Accepted')
        db.session.add(r); db.session.flush()
        names = []
        lab = rad = 0
        for sid in sids:
            svc = Service.query.get(sid)
            if not svc: continue
            names.append(svc.name)
            if svc.department == 'Radiology':
                db.session.add(RadOrder(patient_id=p.id, service_id=svc.id, ref_id=r.id, paid_gate=False)); rad += 1
            else:
                db.session.add(LabOrder(patient_id=p.id, service_id=svc.id, ref_id=r.id, paid_gate=False)); lab += 1
        r.tests = ', '.join(names)
        db.session.commit()
        pr = f' [{r.priority}]' if r.priority != 'Routine' else ''
        notify(f'Doctor portal referral{pr}: {p.name} by Dr {d.name} ({r.tests[:50]})',
               '/m/referrals', role='reception')
        if lab: notify(f'Referral tests{pr}: {p.name} · Dr {d.name}', '/m/lab', role='lab_tech')
        if rad: notify(f'Referral imaging{pr}: {p.name} · Dr {d.name}', '/m/radiology', role='radiologist')
        return redirect(url_for('drportal.dr_req', rid=r.id))
    labs = Service.query.filter_by(active=True, department='Laboratory').order_by(Service.name).all()
    rads = Service.query.filter_by(active=True, department='Radiology').order_by(Service.name).all()
    box = lambda items: ''.join(
        f"<label class='chk'><input type='checkbox' name='svc' value='{s_.id}'> {h(s_.name)}</label>"
        for s_ in items) or "<span style='color:var(--muted);font-size:13px'>None configured.</span>"
    err_banner = ("<div class='panel' style='border-left:3px solid var(--red);margin-bottom:12px'>"
                  "<div class='pad' style='color:#B3261E;font-weight:600'>⚠ Codsi lama diri karo test la'aan — fadlan door ugu yaraan HAL test.</div></div>"
                  if request.args.get('err') == 'notest' else '')
    body = f"""{err_banner}<div class='panel'><div class='ph'><h2>New Referral</h2><div class='sp'></div><a class='btn sm' href='/dr/home'>← Back</a></div>
      <div class='pad'><form method='post' onsubmit="return drReqValidate()">{_csrf_input()}<div class='fg'>
      <div class='fld full' style='font-weight:700;color:var(--petrol)'>Patient</div>
      <input type='hidden' name='patient_id' id='drPid'>
      <div class='fld full' style='position:relative'>
        <label>🔎 Returning patient? Search by ID or phone · Raadi bukaan hore</label>
        <input id='drPatSearch' autocomplete='off' placeholder='Geli MRN ama telefoon si aad u isticmaasho diiwaankii hore…'>
        <div id='drPatResults' style='display:none;position:absolute;z-index:20;left:0;right:0;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,.14);max-height:220px;overflow:auto'></div>
        <div id='drPatChosen' style='display:none;margin-top:6px;font-size:12.5px;color:var(--green)'></div>
      </div>
      <div class='fld'><label>Patient Name *</label><input name='name' id='drName' required></div>
      <div class='fld'><label>Phone</label><input name='phone' id='drPhone' placeholder='haddii uu jiro, diiwaankiisii ayaa la isticmaalayaa'></div>
      <div class='fld'><label>Age</label><input name='age' id='drAge'></div>
      <div class='fld'><label>Gender</label><select name='gender' id='drGender'><option value=''>—</option><option>Male</option><option>Female</option></select></div>
      <div class='fld full'><label>Address</label><input name='address'></div>
      <div class='fld full'><label>Allergies</label><input name='allergies'></div>
      <div class='fld full' style='font-weight:700;color:var(--petrol);margin-top:6px'>Clinical Information</div>
      <div class='fld full'><label>Chief Complaint</label><input name='complaint'></div>
      <div class='fld full'><label>Clinical History</label><textarea name='history' rows='2'></textarea></div>
      <div class='fld'><label>Provisional Diagnosis</label><input name='prov_dx'></div>
      <div class='fld'><label>Priority</label><select name='priority'><option>Routine</option><option>Urgent</option><option>STAT</option></select></div>
      <div class='fld full'><label>Special Instructions</label><input name='instructions'></div>
      <div class='fld full' style='font-weight:700;color:var(--petrol);margin-top:6px'>Tests Requested <span style='color:#B3261E'>*</span> <span style='font-weight:400;color:var(--muted);font-size:12px'>(door ugu yaraan hal)</span></div>
      <div class='fld full' id='dr-test-err' style='display:none;color:#B3261E;font-weight:600;background:#FDECEC;border:1px solid #F3B4AE;border-radius:8px;padding:10px 12px'>⚠ Fadlan door ugu yaraan HAL test (Laboratory ama Radiology) — codsi la'aan test lama diri karo.</div>
      <div class='fld full' style='font-weight:700;color:var(--petrol);margin-top:2px'>Laboratory</div>
      <div class='fld full'><div class='chkgrid'>{box(labs)}</div></div>
      <div class='fld full' style='font-weight:700;color:var(--petrol);margin-top:6px'>Radiology</div>
      <div class='fld full'><div class='chkgrid'>{box(rads)}</div></div>
      <div class='fld full' style='text-align:right'><button class='btn primary' style='padding:12px 26px;font-size:15px'>Submit Referral</button></div>
      </div></form></div></div>
      <script>
      (function(){{
        var box=document.getElementById('drPatSearch'), res=document.getElementById('drPatResults'),
            chosen=document.getElementById('drPatChosen'), t=null;
        function clearPid(){{document.getElementById('drPid').value=''; chosen.style.display='none';}}
        if(box){{
          box.addEventListener('input', function(){{
            clearPid(); var q=this.value.trim();
            if(q.length<4){{res.style.display='none'; return;}}
            clearTimeout(t);
            t=setTimeout(function(){{
              fetch('/dr/patient-lookup?q='+encodeURIComponent(q))
              .then(function(r){{return r.json();}}).then(function(list){{
                if(!list.length){{res.innerHTML="<div style='padding:8px 12px;color:#888;font-size:12.5px'>Lama helin — bukaan cusub ayaa la abuurayaa.</div>"; res.style.display='block'; return;}}
                res.innerHTML=list.map(function(p){{
                  return "<div class='drpat' data-id='"+p.id+"' data-name='"+encodeURIComponent(p.name)+"' data-phone='"+encodeURIComponent(p.phone)+"' data-age='"+p.age+"' data-gender='"+p.gender+"' style='padding:8px 12px;cursor:pointer;border-bottom:1px solid #eee'>"
                    +"<b>"+p.name+"</b> <span style='color:#888;font-size:12px'>· "+p.mrn+" · "+(p.phone||'—')+"</span></div>";
                }}).join('');
                res.style.display='block';
                Array.prototype.forEach.call(res.querySelectorAll('.drpat'), function(el){{
                  el.addEventListener('mousedown', function(){{
                    document.getElementById('drPid').value=el.getAttribute('data-id');
                    document.getElementById('drName').value=decodeURIComponent(el.getAttribute('data-name'));
                    document.getElementById('drPhone').value=decodeURIComponent(el.getAttribute('data-phone'));
                    var ag=el.getAttribute('data-age'); document.getElementById('drAge').value=(ag&&ag!=='None'?ag:'');
                    var g=el.getAttribute('data-gender'); if(g){{document.getElementById('drGender').value=g;}}
                    chosen.textContent='✓ Bukaankii hore — diiwaan cusub lama abuurayo.'; chosen.style.display='block';
                    res.style.display='none'; box.value='';
                  }});
                }});
              }});
            }}, 220);
          }});
          box.addEventListener('blur', function(){{ setTimeout(function(){{res.style.display='none';}}, 200); }});
        }}
      }})();
      </script>
      <script>
      function drReqValidate(){{
        var any=document.querySelectorAll("input[name='svc']:checked").length>0;
        var err=document.getElementById('dr-test-err');
        if(!any){{ if(err){{err.style.display='block'; err.scrollIntoView({{block:'center'}});}} return false; }}
        return true;
      }}
      document.addEventListener('change',function(e){{
        if(e.target && e.target.name==='svc'){{
          var err=document.getElementById('dr-test-err');
          if(err && document.querySelectorAll("input[name='svc']:checked").length>0) err.style.display='none';
        }}
      }});
      </script>"""
    return public_shell('New Referral', body)


# ------------------------------------------------------------------ tracking + reports
def _my_ref(rid):
    d = _guard()
    if not d: return None, None
    r = Referral.query.get_or_404(rid)
    if r.doctor_id != d.id: abort(403)
    return d, r


@bp.route('/dr/req/<int:rid>', methods=['GET', 'POST'])
def dr_req(rid):
    d, r = _my_ref(rid)
    if not d: return redirect(url_for('drportal.dr_login'))
    if request.method == 'POST':
        txt = (request.form.get('text') or '').strip()[:500]
        if txt:
            db.session.add(RefComment(referral_id=rid, author=f'Dr {d.name}',
                                      is_doctor=True, text=txt))
            db.session.commit()
            notify(f'Dr {d.name} commented on REF-{rid:04d}: {txt[:60]}',
                   f'/referral/{rid}/thread', role='reception')
        return redirect(url_for('drportal.dr_req', rid=rid))
    orders = ([('LAB', o) for o in LabOrder.query.filter_by(ref_id=rid).all()]
              + [('RAD', o) for o in RadOrder.query.filter_by(ref_id=rid).all()])
    rows = ''
    for kind, o in orders:
        st = STATUS_LABEL.get(o.status, o.status)
        link = ''
        if kind == 'LAB' and o.status == 'Approved':
            link = f"<a class='btn sm primary' href='/dr/lab/{o.id}' target='_blank'>View / Print Report</a>"
        if kind == 'RAD' and o.status == 'Reported':
            link = f"<a class='btn sm primary' href='/dr/rad/{o.id}' target='_blank'>View Report & Images</a>"
        rows += (f"<tr><td><span class='pill {'blue' if kind=='LAB' else 'teal'}'>{kind}</span></td>"
                 f"<td><b>{h(o.service.name if o.service else '—')}</b></td>"
                 f"<td><span class='pill {STATUS_COLOR.get(st,'grey')}'>{h(st)}</span></td>"
                 f"<td class='num'>{link}</td></tr>")
    cmts = ''.join(
        f"<div style='margin:6px 0;padding:8px 12px;border-radius:10px;background:{'var(--canvas)' if c.is_doctor else '#EAF0FB'}'>"
        f"<b style='font-size:12.5px;color:var(--petrol)'>{h(c.author)}</b> "
        f"<span style='color:var(--muted);font-size:11px'>{c.created.strftime('%d-%b %H:%M') if c.created else ''}</span>"
        f"<div style='font-size:13.5px'>{h(c.text)}</div></div>"
        for c in sorted(r.comments, key=lambda x: x.id)) or \
        "<p style='color:var(--muted);font-size:13px'>No comments yet.</p>"
    pr = ("<span class='pill red'>STAT</span>" if r.priority == 'STAT'
          else "<span class='pill amber'>Urgent</span>" if r.priority == 'Urgent'
          else "<span class='pill grey'>Routine</span>")
    body = f"""<div class='panel'><div class='ph'><h2>REF-{r.id:04d} · {h(r.patient_name)}</h2><div class='sp'></div>
      <a class='btn sm' href='/dr/home'>← My Requests</a></div>
      <div class='pad' style='font-size:13.5px'>
        <b>Date:</b> {h(r.date)} · <b>Priority:</b> {pr}<br>
        <b>Complaint:</b> {h(r.complaint or '—')} · <b>Provisional Dx:</b> {h(r.prov_dx or '—')}<br>
        {f"<b>Instructions:</b> {h(r.instructions)}<br>" if r.instructions else ''}
      </div></div>
    <div class='panel'><div class='ph'><h2>Investigations & Status</h2></div>
      <div class='tw'><table><thead><tr><th></th><th>Investigation</th><th>Status</th><th></th></tr></thead>
      <tbody>{rows or "<tr><td colspan='4' style='color:var(--muted);padding:14px'>No orders.</td></tr>"}</tbody></table></div></div>
    <div class='panel'><div class='ph'><h2>Comments & Follow-up</h2></div><div class='pad'>
      {cmts}
      <form method='post' style='margin-top:10px'>{_csrf_input()}
        <div style='display:flex;gap:8px'>
        <input name='text' maxlength='500' placeholder='Add a comment, treatment note or question…' style='flex:1;border:1px solid var(--line);border-radius:9px;padding:9px 12px'>
        <button class='btn primary'>Send</button></div></form>
    </div></div>"""
    return public_shell(f'REF-{r.id:04d}', body)


@bp.route('/dr/lab/<int:oid>')
def dr_lab(oid):
    d = _guard()
    if not d: return redirect(url_for('drportal.dr_login'))
    o = LabOrder.query.get_or_404(oid)
    r = Referral.query.get(o.ref_id) if o.ref_id else None
    if not r or r.doctor_id != d.id: abort(403)
    if o.status != 'Approved': abort(404)
    from ..core.printing import printable
    svc = o.service
    ref_line = (f"<p style='color:#555;font-size:13px'><b>Reference Range:</b> {h(svc.ref_range or '—')}"
                f"{(' ' + h(svc.unit)) if svc and svc.unit else ''}</p>") if svc and (svc.ref_range or svc.unit) else ''
    body = f"""
      <p><b>Patient:</b> {h(o.patient.name if o.patient else '—')} ({h(o.patient.mrn if o.patient else '')})<br>
      <b>Test:</b> {h(svc.name if svc else '—')} · <b>Date:</b> {h(o.date)}<br>
      <b>Referring Doctor:</b> Dr {h(d.name)}</p>
      <h3>Result</h3><pre style="white-space:pre-wrap;font-family:inherit">{h(o.result or '')}</pre>
      {ref_line}
      <p style='margin-top:26px'>Verified &amp; Approved: <b>{h(o.approved_by or '—')}</b></p>"""
    return printable('Laboratory Report', body, doc_ref=f'LAB-{o.id:04d}',
                     barcode_text=(o.sample_no or None),
                     signature=({'name': o.approved_by, 'title': 'Laboratory — Verified & Approved'} if o.status == 'Approved' and o.approved_by else None))


@bp.route('/dr/rad/<int:oid>')
def dr_rad(oid):
    d = _guard()
    if not d: return redirect(url_for('drportal.dr_login'))
    o = RadOrder.query.get_or_404(oid)
    r = Referral.query.get(o.ref_id) if o.ref_id else None
    if not r or r.doctor_id != d.id: abort(403)
    if o.status != 'Reported': abort(404)
    from ..core.printing import printable
    imgs = ''
    n = len([f for f in (o.images or '').split(',') if f])
    if n:
        imgs = "<h3>Images</h3>" + ''.join(
            f"<img src='/rad/{o.id}/img/{i}' style='max-width:46%;margin:4px;border-radius:8px;border:1px solid #ddd'>"
            for i in range(n))
    body = f"""
      <p><b>Patient:</b> {h(o.patient.name if o.patient else '—')} ({h(o.patient.mrn if o.patient else '')})<br>
      <b>Study:</b> {h(o.modality or '')} · {h(o.service.name if o.service else '—')} · <b>Date:</b> {h(o.date)}<br>
      <b>Referring Doctor:</b> Dr {h(d.name)}</p>
      <h3>Report</h3><pre style="white-space:pre-wrap;font-family:inherit">{h(o.report or '')}</pre>
      {imgs}
      <p style='margin-top:26px'>Radiologist: <b>{h(o.reported_by or '—')}</b></p>"""
    return printable('Radiology Report', body, doc_ref=f'RAD-{o.id:04d}',
                     barcode_text=(o.patient.mrn if o.patient else None),
                     signature=({'name': o.reported_by, 'title': 'Consultant Radiologist'} if o.status == 'Reported' and o.reported_by else None))
