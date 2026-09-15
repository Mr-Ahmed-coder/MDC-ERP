"""Remote Radiologist Portal (/rrad) — teleradiology for MDC.

Radiologists in another city or country log in with credentials set on
their Radiologist record (Radiology → Radiologists), receive assigned
CT/MRI/X-Ray/Ultrasound cases with uploaded files (DICOM/ZIP/RAR/PDF/
images), write reports using templates, save drafts, approve (which
locks the report and releases it to reception, the referring doctor and
the patient), request repeat scans and discuss cases — with no access
to billing, accounting or any staff module.
"""
import datetime as dt

from flask import Blueprint, request, redirect, url_for, session, abort
from markupsafe import escape as h
from werkzeug.security import check_password_hash

from ..extensions import db
from ..models import (Radiologist, RadOrder, RadComment, Referral, Doctor)
from ..core.security import csrf_token
from ..core.ui import public_shell
from ..core.notify import notify

bp = Blueprint('rrad', __name__)

TEMPLATES = {
    'CT Brain': "TECHNIQUE: Non-contrast axial CT of the brain.\n\nFINDINGS:\n- Brain parenchyma: \n- Ventricles & cisterns: \n- No acute hemorrhage / mass effect / midline shift.\n- Bones & sinuses: ",
    'CT Chest': "TECHNIQUE: Axial CT of the chest.\n\nFINDINGS:\n- Lungs: \n- Mediastinum & hila: \n- Pleura: \n- Bones & soft tissues: ",
    'CT Abdomen': "TECHNIQUE: CT abdomen & pelvis.\n\nFINDINGS:\n- Liver / GB / pancreas / spleen: \n- Kidneys & ureters: \n- Bowel: \n- No free fluid / free air.",
    'CT Spine': "TECHNIQUE: CT of the spine.\n\nFINDINGS:\n- Alignment: \n- Vertebral bodies: \n- Discs & canal: ",
    'MRI Brain': "TECHNIQUE: Multiplanar multisequence MRI of the brain.\n\nFINDINGS:\n- Parenchyma & signal: \n- Diffusion: \n- Ventricles: \n- MRA (if done): ",
    'MRI Spine': "TECHNIQUE: MRI of the spine.\n\nFINDINGS:\n- Alignment & vertebrae: \n- Discs (levels): \n- Cord & canal: ",
    'MRI Knee': "TECHNIQUE: MRI of the knee.\n\nFINDINGS:\n- Menisci: \n- Cruciate & collateral ligaments: \n- Cartilage & bone marrow: \n- Effusion: ",
    'X-Ray Chest': "FINDINGS:\n- Lungs clear, no focal consolidation.\n- Cardiomediastinal silhouette: \n- Costophrenic angles: \n- Bones: ",
    'X-Ray Limb': "FINDINGS:\n- Bones & alignment: \n- No fracture / dislocation.\n- Joint spaces: \n- Soft tissues: ",
    'Ultrasound Abdomen': "FINDINGS:\n- Liver: size, echotexture.\n- Gallbladder: \n- CBD / portal vein: \n- Pancreas / spleen / kidneys: \n- No free fluid.",
    'Ultrasound Pelvis': "FINDINGS:\n- Uterus: size, endometrium.\n- Ovaries: \n- Bladder: \n- No free fluid.",
    'Ultrasound Obstetric': "FINDINGS:\n- Single viable intrauterine fetus.\n- FHR: \n- BPD/FL/AC → GA: \n- Placenta & liquor: \n- EDD: ",
}


def cur_rad():
    rid = session.get('rrad_id')
    return Radiologist.query.get(rid) if rid else None


def _csrf_input():
    return f"<input type='hidden' name='_csrf' value='{csrf_token()}'>"


def _my_case(oid):
    r = cur_rad()
    if not r or not r.active:
        return None, None
    o = RadOrder.query.get_or_404(oid)
    if o.assigned_rad_id != r.id:
        abort(403)
    return r, o


# ------------------------------------------------------------------ auth
@bp.route('/rrad', methods=['GET', 'POST'])
def rrad_login():
    err = ''
    if request.method == 'POST':
        u = (request.form.get('username') or '').strip()
        r = Radiologist.query.filter_by(portal_user=u).first()
        if r and r.active and r.portal_pw and check_password_hash(
                r.portal_pw, request.form.get('password') or ''):
            session['rrad_id'] = r.id
            return redirect(url_for('rrad.rrad_home'))
        err = 'Invalid username or password'
    body = f"""<div class='panel' style='max-width:420px;margin:30px auto'><div class='pad'>
      <h2 style='color:var(--petrol);font-family:Space Grotesk;text-align:center'>Radiologist Portal</h2>
      <p style='color:var(--muted);font-size:13px;text-align:center'>Modern Diagnostic Center · Teleradiology</p>
      {f"<div style='background:var(--red-soft);color:var(--red);border-radius:8px;padding:8px 12px;font-size:13px;margin-bottom:8px'>{h(err)}</div>" if err else ''}
      <form method='post'>{_csrf_input()}<div class='fg'>
        <div class='fld full'><label>Username</label><input name='username' required autofocus></div>
        <div class='fld full'><label>Password</label><input name='password' type='password' required></div>
        <div class='fld full'><button class='btn primary' style='width:100%'>Sign in</button></div>
      </div></form></div></div>"""
    return public_shell('Radiologist Portal', body)


@bp.route('/rrad/logout')
def rrad_logout():
    session.pop('rrad_id', None)
    return redirect(url_for('rrad.rrad_login'))


# ------------------------------------------------------------------ dashboard
@bp.route('/rrad/home')
def rrad_home():
    r = cur_rad()
    if not r or not r.active: return redirect(url_for('rrad.rrad_login'))
    cases = (RadOrder.query.filter_by(assigned_rad_id=r.id)
             .order_by(RadOrder.id.desc()).all())
    q = (request.args.get('q') or '').strip().lower()
    fl = request.args.get('f') or ''
    new = [o for o in cases if o.status == 'Imaged' and not o.draft]
    prog = [o for o in cases if o.status == 'Imaged' and o.draft]
    done = [o for o in cases if o.status == 'Reported']
    rows = ''
    for o in cases:
        st = ('Completed' if o.status == 'Reported'
              else 'Draft' if o.draft else 'New')
        if fl and fl != st: continue
        if q and q not in (o.patient.name or '').lower() if o.patient else q:
            continue
        pr = ''
        if o.ref_id:
            _r = Referral.query.get(o.ref_id)
            if _r and _r.priority == 'STAT': pr = "<span class='pill red'>STAT</span>"
            elif _r and _r.priority == 'Urgent': pr = "<span class='pill amber'>Urgent</span>"
        rows += (f"<tr><td><b>RAD-{o.id:04d}</b><div style='color:var(--muted);font-size:11px'>{h(o.date)}</div></td>"
                 f"<td><b>{h(o.patient.name if o.patient else '—')}</b></td>"
                 f"<td><span class='pill grey'>{h(o.modality or '')}</span> {h(o.service.name if o.service else '')}</td>"
                 f"<td>{pr}</td>"
                 f"<td><span class='pill {'green' if st=='Completed' else ('teal' if st=='Draft' else 'amber')}'>{st}</span></td>"
                 f"<td class='num'><a class='btn sm primary' href='/rrad/case/{o.id}'>Open</a></td></tr>")
    rows = rows or "<tr><td colspan='6' style='color:var(--muted);padding:16px'>No cases.</td></tr>"
    k = lambda n, v, c='var(--petrol)': (f"<div class='panel' style='flex:1;min-width:120px'><div class='pad'>"
        f"<div style='font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase'>{n}</div>"
        f"<div style='font-family:Space Grotesk;font-weight:700;font-size:26px;color:{c}'>{v}</div></div></div>")
    body = f"""
    <div class='panel'><div class='pad' style='display:flex;align-items:center;gap:12px;flex-wrap:wrap'>
      <div><div style='font-family:Space Grotesk;font-weight:700;font-size:18px;color:var(--petrol)'>Dr {h(r.name)}</div>
      <div style='color:var(--muted);font-size:12.5px'>{h(r.specialty or 'Radiologist')} · Teleradiology</div></div>
      <div class='sp'></div><a class='btn sm' href='/rrad/logout'>Logout</a></div></div>
    <div style='display:flex;gap:12px;flex-wrap:wrap'>{k('New Cases', len(new), 'var(--amber)' if new else 'var(--green)')}{k('In Progress (Drafts)', len(prog), 'var(--petrol)')}{k('Completed', len(done), 'var(--green)')}</div>
    <div class='panel'><div class='ph'><h2>My Cases</h2><div class='sp'></div>
      <form method='get' style='display:flex;gap:6px'>
        <select name='f' onchange='this.form.submit()' style='border:1px solid var(--line);border-radius:9px;padding:7px'>
          <option value=''>All</option><option {'selected' if fl=='New' else ''}>New</option>
          <option {'selected' if fl=='Draft' else ''}>Draft</option>
          <option {'selected' if fl=='Completed' else ''}>Completed</option></select>
        <input name='q' value='{h(q)}' placeholder='Search patient…' style='border:1px solid var(--line);border-radius:9px;padding:7px 12px;font-size:13px'>
      </form></div>
      <div class='tw'><table><thead><tr><th>Case</th><th>Patient</th><th>Study</th><th></th><th>Status</th><th></th></tr></thead>
      <tbody>{rows}</tbody></table></div></div>"""
    return public_shell('Radiologist Portal', body)


# ------------------------------------------------------------------ case
def _files(o):
    return [f for f in (o.images or '').split(',') if f]


@bp.route('/rrad/case/<int:oid>', methods=['GET', 'POST'])
def rrad_case(oid):
    r, o = _my_case(oid)
    if not r: return redirect(url_for('rrad.rrad_login'))
    locked = o.status == 'Reported'
    if request.method == 'POST' and not locked:
        act = request.form.get('act')
        if act == 'comment':
            txt = (request.form.get('text') or '').strip()[:500]
            if txt:
                db.session.add(RadComment(rad_id=oid, author=f'Dr {r.name}',
                                          is_remote=True, text=txt))
                db.session.commit()
                notify(f'Dr {r.name} on RAD-{oid:04d}: {txt[:60]}',
                       f'/rad/{oid}/thread', role='radiologist')
        elif act == 'repeat':
            o.status = 'Requested'
            db.session.add(RadComment(rad_id=oid, author=f'Dr {r.name}', is_remote=True,
                                      text='REPEAT SCAN REQUESTED: ' + (request.form.get('text') or '')[:400]))
            db.session.commit()
            notify(f'⚠ Repeat scan requested RAD-{oid:04d} by Dr {r.name}',
                   f'/rad/{oid}/thread', role='radiologist')
        elif act in ('draft', 'approve'):
            parts = []
            for label, fld in (('FINDINGS', 'findings'), ('IMPRESSION', 'impression'),
                               ('RECOMMENDATIONS', 'recommendations'), ('NOTES', 'notes')):
                v = (request.form.get(fld) or '').strip()
                if v: parts.append(f'{label}:\n{v}')
            text = '\n\n'.join(parts)
            if act == 'draft':
                o.draft = text
                db.session.commit()
            else:
                o.report = text
                o.draft = None
                o.status = 'Reported'
                o.reported_by = f'Dr {r.name}'
                o.radiologist = r.name
                o.rad_approved_at = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
                db.session.commit()
                notify(f'Radiology report ready: {o.patient.name if o.patient else "—"} '
                       f'({o.modality or ""}) — RAD-{oid:04d} · Dr {r.name}',
                       f'/rad/{oid}/print', role='reception')
                from ..core.messaging import queue_msg
                if o.ref_id:
                    _ref = Referral.query.get(o.ref_id)
                    _doc = Doctor.query.get(_ref.doctor_id) if _ref and _ref.doctor_id else None
                    if _doc and _doc.phone:
                        queue_msg(_doc.phone, f"Dr {_doc.name}: your patient's radiology report "
                                              f"is available (REF-{o.ref_id:04d}). Portal: /dr",
                                  ref=f'RAD-{oid:04d}')
                if o.patient and o.patient.phone:
                    queue_msg(o.patient.phone,
                              f'{o.patient.name}, warbixintaadii raajada waa diyaar. MDC.',
                              ref=f'RAD-{oid:04d}')
        return redirect(url_for('rrad.rrad_case', oid=oid))

    # clinical context
    ref = Referral.query.get(o.ref_id) if o.ref_id else None
    hist = ''
    if ref:
        hist = (f"<b>Referring Doctor:</b> Dr {h(ref.doctor_name or '—')} · "
                f"<b>Priority:</b> {h(ref.priority or 'Routine')}<br>"
                f"<b>Complaint:</b> {h(ref.complaint or '—')} · "
                f"<b>History:</b> {h(ref.notes or '—')} · "
                f"<b>Prov. Dx:</b> {h(ref.prov_dx or '—')}")
    prev = (RadOrder.query.filter(RadOrder.patient_id == o.patient_id,
                                  RadOrder.status == 'Reported',
                                  RadOrder.id != o.id)
            .order_by(RadOrder.id.desc()).limit(5).all()) if o.patient_id else []
    prev_html = ''.join(f"<div style='font-size:13px'>📄 {h(p_.date)} · {h(p_.modality or '')} "
                        f"{h(p_.service.name if p_.service else '')} — Dr {h(p_.radiologist or p_.reported_by or '')}"
                        f" <a href='/rrad/prev/{p_.id}' target='_blank' style='color:var(--petrol)'>view</a></div>"
                        for p_ in prev) or "<span style='color:var(--muted);font-size:13px'>None.</span>"
    files = _files(o)
    fhtml = ''
    for i, f_ in enumerate(files):
        ext = f_.rsplit('.', 1)[-1].lower()
        if ext in ('jpg', 'jpeg', 'png', 'webp', 'bmp', 'gif'):
            fhtml += (f"<a href='/rad/{o.id}/img/{i}' target='_blank'>"
                      f"<img src='/rad/{o.id}/img/{i}' style='width:130px;height:110px;object-fit:cover;"
                      f"border-radius:8px;border:1px solid var(--line);margin:3px'></a>")
        else:
            fhtml += (f"<a class='btn sm' style='margin:3px' href='/rad/{o.id}/img/{i}'>"
                      f"⬇ {h(f_.split('_',2)[-1][:28])}</a>")
    fhtml = fhtml or "<span style='color:var(--muted);font-size:13px'>No files uploaded.</span>"
    # editor prefill: draft (parse loose) or template
    tpl = request.args.get('tpl')
    src = TEMPLATES.get(tpl, '') if tpl else (o.draft or '')

    def sect(name):
        import re as _re
        m = _re.search(name + r':\n(.*?)(?=\n\n[A-Z]+:|\Z)', src, _re.S)
        return m.group(1).strip() if m else ''
    if tpl and src:
        findings = src            # whole template skeleton goes into Findings
        imp = rec = nts = ''
    else:
        findings = sect('FINDINGS') or (src if src and 'FINDINGS' not in src else '')
        imp, rec, nts = sect('IMPRESSION'), sect('RECOMMENDATIONS'), sect('NOTES')
    tpl_opts = ''.join(f"<option {'selected' if tpl==t else ''}>{t}</option>" for t in TEMPLATES)
    cmts = ''.join(
        f"<div style='margin:6px 0;padding:8px 12px;border-radius:10px;background:{'#FFF6EC' if c.is_remote else 'var(--canvas)'}'>"
        f"<b style='font-size:12.5px;color:var(--petrol)'>{h(c.author)}</b> "
        f"<span style='color:var(--muted);font-size:11px'>{c.created.strftime('%d-%b %H:%M') if c.created else ''}</span>"
        f"<div style='font-size:13.5px'>{h(c.text)}</div></div>"
        for c in sorted(o.case_comments, key=lambda x: x.id)) or \
        "<p style='color:var(--muted);font-size:13px'>No messages.</p>"
    p = o.patient
    editor = (f"""
    <div class='panel'><div class='ph'><h2>Report Editor</h2><div class='sp'></div>
      <form method='get' style='display:flex;gap:6px;align-items:center'>
        <label style='font-size:12px;color:var(--muted)'>Template</label>
        <select name='tpl' onchange='this.form.submit()' style='border:1px solid var(--line);border-radius:9px;padding:6px'>
          <option value=''>—</option>{tpl_opts}</select></form></div>
      <div class='pad'><form method='post'>{_csrf_input()}<input type='hidden' name='act' value='draft' id='actf'>
        <div class='fg'>
        <div class='fld full'><label>Findings</label><textarea name='findings' rows='7'>{h(findings)}</textarea></div>
        <div class='fld full'><label>Impression</label><textarea name='impression' rows='3'>{h(imp)}</textarea></div>
        <div class='fld full'><label>Recommendations</label><textarea name='recommendations' rows='2'>{h(rec)}</textarea></div>
        <div class='fld full'><label>Additional Notes</label><textarea name='notes' rows='2'>{h(nts)}</textarea></div>
        <div class='fld full' style='display:flex;gap:8px;flex-wrap:wrap'>
          <button class='btn' onclick="document.getElementById('actf').value='draft'">💾 Save Draft</button>
          <button class='btn primary' onclick="document.getElementById('actf').value='approve';return confirm('Approve & lock this report?')">✅ Approve Report</button>
        </div></div></form>
      <form method='post' style='margin-top:6px'>{_csrf_input()}<input type='hidden' name='act' value='repeat'>
        <div style='display:flex;gap:8px'><input name='text' placeholder='Reason for repeat scan…' style='flex:1;border:1px solid var(--line);border-radius:9px;padding:8px 12px'>
        <button class='btn' style='color:var(--red)'>↺ Request Repeat Scan</button></div></form>
      </div></div>""" if not locked else
      f"""<div class='panel'><div class='ph'><h2>Approved Report 🔒</h2></div><div class='pad'>
        <pre style='white-space:pre-wrap;font-family:inherit;font-size:13.5px'>{h(o.report or '')}</pre>
        <p style='color:var(--muted);font-size:12.5px'>Approved by <b>Dr {h(r.name)}</b> · {h(o.rad_approved_at or '')} — locked.</p>
      </div></div>""")
    body = f"""
    <div class='panel'><div class='ph'><h2>RAD-{o.id:04d} · {h(p.name if p else '—')}</h2><div class='sp'></div>
      <a class='btn sm' href='/rrad/home'>← My Cases</a></div>
      <div class='pad' style='font-size:13.5px'>
        <b>{h(p.name if p else '—')}</b> · {(str(p.age)+' yr') if p and p.age is not None else '—'} · {h(p.gender if p else '—')}<br>
        <b>Study:</b> {h(o.modality or '')} · {h(o.service.name if o.service else '—')} · {h(o.date)}<br>
        {hist}
      </div></div>
    <div class='panel'><div class='ph'><h2>Study Files ({len(files)})</h2></div><div class='pad'>{fhtml}</div></div>
    <div class='panel'><div class='ph'><h2>Previous Reports</h2></div><div class='pad'>{prev_html}</div></div>
    {editor}
    <div class='panel'><div class='ph'><h2>Case Discussion</h2></div><div class='pad'>{cmts}
      <form method='post' style='margin-top:10px'>{_csrf_input()}<input type='hidden' name='act' value='comment'>
      <div style='display:flex;gap:8px'>
        <input name='text' maxlength='500' placeholder='Message the technician / center…' style='flex:1;border:1px solid var(--line);border-radius:9px;padding:9px 12px'>
        <button class='btn primary'>Send</button></div></form></div></div>"""
    return public_shell(f'RAD-{o.id:04d}', body)


@bp.route('/rrad/prev/<int:oid>')
def rrad_prev(oid):
    """A prior approved report of the same patient (context for comparison)."""
    r = cur_rad()
    if not r: return redirect(url_for('rrad.rrad_login'))
    o = RadOrder.query.get_or_404(oid)
    mine = RadOrder.query.filter_by(assigned_rad_id=r.id, patient_id=o.patient_id).first()
    if not mine or o.status != 'Reported': abort(403)
    body = f"""<div class='panel'><div class='ph'><h2>Previous Report · RAD-{o.id:04d}</h2></div>
      <div class='pad'><p style='font-size:13px;color:var(--muted)'>{h(o.date)} · {h(o.modality or '')} · {h(o.service.name if o.service else '')} · Dr {h(o.radiologist or o.reported_by or '')}</p>
      <pre style='white-space:pre-wrap;font-family:inherit;font-size:13.5px'>{h(o.report or '')}</pre></div></div>"""
    return public_shell('Previous Report', body)
