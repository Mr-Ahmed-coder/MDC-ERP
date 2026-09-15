"""RIS — Radiology Information System  (Phase 2, v8.0).

A scheduling / workflow / sign-off layer over the existing RadOrder, Radiologist
and the PACS study store. It does NOT introduce new RadOrder.status values (so
the Radiology screen keeps working unchanged) — every RIS state is derived from
existing status plus the RIS timestamp columns.

Workflow:  Requested -> Scheduled -> Acquired -> Reported -> Approved (signed)
TAT:       requested_at ............................... approved_at
"""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort,
                   render_template)
from markupsafe import escape as h
from ..extensions import db
from ..models import RadOrder, ImgModality, ImgStudy, Radiologist
from ..core.security import (cur_user, can, login_required, log, doc_sig,
                             branch_scope, can_see)
from ..core.ui import page
from ..core.crud import register, pill

bp = Blueprint('ris', __name__)

PRIORITIES = ('Routine', 'Urgent', 'STAT')


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


# --------------------------------------------------------------- stage model
def _stage(o):
    """Return (label, color) for the RIS pipeline stage of an order."""
    if o.approved_at:
        return ('Approved', 'green')
    if o.status == 'Reported':
        return ('Awaiting sign-off', 'teal')
    if o.status == 'Imaged':
        return ('Acquired', 'blue')
    if o.scheduled_for:
        return ('Scheduled', 'petrol')
    return ('Requested', 'amber')


def _anchor(o):
    return o.requested_at or (f'{o.date} 00:00' if o.date else None)


def _tat_minutes(o):
    start = _anchor(o)
    if not start:
        return None
    end = o.approved_at or _now()
    try:
        a = dt.datetime.strptime(start[:16], '%Y-%m-%d %H:%M')
        b = dt.datetime.strptime(end[:16], '%Y-%m-%d %H:%M')
        return int((b - a).total_seconds() // 60)
    except Exception:
        return None


def _fmt_tat(mins):
    if mins is None:
        return '—'
    if mins < 60:
        return f'{mins}m'
    if mins < 1440:
        return f'{mins // 60}h {mins % 60}m'
    return f'{mins // 1440}d {(mins % 1440) // 60}h'


def _prio_pill(p):
    return {'STAT': "<span class='pill red'>STAT</span>",
            'Urgent': "<span class='pill amber'>Urgent</span>"}.get(p, "<span class='pill grey'>Routine</span>")


# ------------------------------------------------------------------ worklist
def ris_worklist():
    """The RIS board — reachable from the App Launcher (mod='ris')."""
    fmod = (request.args.get('modality') or '').strip()
    fstage = (request.args.get('stage') or '').strip()
    mine = request.args.get('mine') == '1'
    u = cur_user()

    q = branch_scope(RadOrder.query, RadOrder)
    if fmod:
        q = q.filter(RadOrder.modality == fmod)
    orders = q.order_by(RadOrder.id.desc()).limit(500).all()

    rows = []
    counts = {}
    for o in orders:
        label, color = _stage(o)
        counts[label] = counts.get(label, 0) + 1
        if fstage and label != fstage:
            continue
        if mine and u and o.assigned_rad_id and getattr(u, 'rrad_id', None) != o.assigned_rad_id:
            # 'mine' is best-effort: only remote radiologists carry rrad linkage
            pass
        study = ImgStudy.query.filter_by(rad_order_id=o.id).first()
        acts = _row_actions(o, label, study)
        rows.append([
            _prio_pill(o.priority),
            h(o.patient.name if o.patient else '—'),
            f"<span class='pill grey'>{h(o.modality or '—')}</span>",
            h(o.service.name if o.service else '—'),
            h(o.scheduled_for or '—'),
            h(o.assigned_rad.name if o.assigned_rad else '—'),
            f"<span class='pill {color}'>{h(label)}</span>",
            _fmt_tat(_tat_minutes(o)),
            acts,
        ])

    # stage summary chips
    order_stages = ['Requested', 'Scheduled', 'Acquired', 'Awaiting sign-off', 'Approved']
    chips = ''.join(
        f"<a href='?stage={s}' class='pill {'green' if s=='Approved' else 'grey'}' "
        f"style='text-decoration:none;margin-right:6px'>{s}: <b>{counts.get(s,0)}</b></a>"
        for s in order_stages)
    mod_opts = ['CT', 'MRI', 'X-Ray', 'Ultrasound', 'ECG']
    filt = ("<div class='panel'><div class='pad' style='font-size:13px'>"
            f"{chips} &nbsp;·&nbsp; "
            "<form method='get' style='display:inline'>"
            "<select name='modality' onchange='this.form.submit()' style='padding:4px'>"
            f"<option value=''>All modalities</option>"
            + ''.join(f"<option value='{m}' {'selected' if fmod==m else ''}>{m}</option>" for m in mod_opts)
            + "</select></form>"
            + (f" &nbsp;<a href='{url_for('modules.module', mod='ris')}' style='color:var(--petrol)'>clear</a>" if (fmod or fstage) else '')
            + "</div></div>")

    toolbar = (f"<a class='btn' href='{url_for('modules.module', mod='modalities')}'>⚙ Modalities</a> "
               f"<a class='btn' href='{url_for('ris.tat')}'>📈 Turnaround</a> "
               f"<a class='btn primary' href='{url_for('rad.rad_new')}'>+ New Request</a>")
    body = render_template(
        'list_page.html', title='RIS · Imaging Worklist', prefix=filt, toolbar=toolbar,
        headers=['Priority', 'Patient', 'Modality', 'Study', 'Scheduled', 'Radiologist', 'Stage', 'TAT', ''],
        aligns=['', '', '', '', '', '', '', 'num', 'num'], rows=rows,
        empty="<div class='empty'><b>No imaging requests</b>Create one from Radiology.</div>")
    return page('RIS', body, 'ris')


def _row_actions(o, label, study):
    a = []
    if label == 'Requested':
        a.append(f"<a class='btn sm primary' href='{url_for('ris.schedule', oid=o.id)}'>📅 Schedule</a>")
    elif label == 'Scheduled':
        a.append(f"<a class='btn sm primary' href='{url_for('ris.acquire', oid=o.id)}'>📷 Acquire</a>")
    elif label == 'Acquired':
        a.append(f"<a class='btn sm' href='{url_for('rad.rad_report', oid=o.id)}'>📝 Report</a>")
        a.append(f"<a class='btn sm' href='{url_for('ris.assign', oid=o.id)}'>👤 Assign</a>")
    elif label == 'Awaiting sign-off':
        a.append(f"<a class='btn sm primary' href='{url_for('ris.approve', oid=o.id)}'>✍ Sign off</a>")
    elif label == 'Approved':
        a.append(f"<a class='btn sm' href='{url_for('rad.rad_print', oid=o.id)}' target='_blank'>🖨 Print</a>")
    if study:
        a.append(f"<a class='btn gh sm' href='{url_for('pacs.viewer', sid=study.id)}'>🖥 Images</a>")
    elif label in ('Acquired', 'Awaiting sign-off', 'Approved'):
        a.append(f"<a class='btn gh sm' href='{url_for('pacs.upload')}?patient={o.patient_id or ''}&rad_order_id={o.id}'>⬆ Link DICOM</a>")
    return ' '.join(a)


# ------------------------------------------------------------------ schedule
@bp.route('/ris/<int:oid>/schedule', methods=['GET', 'POST'])
@login_required
def schedule(oid):
    if not can('ris'):
        abort(403)
    o = RadOrder.query.get_or_404(oid)
    if not can_see(o):
        abort(403)
    if request.method == 'POST':
        o.modality_id = request.form.get('modality_id') or None
        o.scheduled_for = (request.form.get('scheduled_for') or '').replace('T', ' ')[:16] or None
        o.priority = request.form.get('priority') or 'Routine'
        if not o.requested_at:
            o.requested_at = _anchor(o) or _now()
        o.scheduled_at = _now()
        db.session.commit()
        log(f'RIS #{oid} scheduled ({o.scheduled_for or "no slot"})', entity=f'RadOrder#{oid}')
        flash('Study scheduled', 'ok')
        return redirect(url_for('modules.module', mod='ris'))

    mods = branch_scope(ImgModality.query.filter_by(active=True), ImgModality).all()
    mopts = "<option value=''>—</option>" + ''.join(
        f"<option value='{m.id}' {'selected' if o.modality_id==m.id else ''}>{h(m.name)} ({h(m.modality or '')})</option>"
        for m in mods)
    popts = ''.join(f"<option value='{p}' {'selected' if o.priority==p else ''}>{p}</option>" for p in PRIORITIES)
    cur_slot = (o.scheduled_for or '').replace(' ', 'T')
    inner = f"""
    <form method='post' class='formwrap'>
      <div class='fld'><label>Patient</label><input value="{h(o.patient.name if o.patient else '')}" disabled></div>
      <div class='fld'><label>Study</label><input value="{h(o.service.name if o.service else o.modality or '')}" disabled></div>
      <div class='fld'><label>Imaging resource</label><select name='modality_id'>{mopts}</select></div>
      <div class='fld'><label>Scheduled slot</label><input type='datetime-local' name='scheduled_for' value="{h(cur_slot)}"></div>
      <div class='fld'><label>Priority</label><select name='priority'>{popts}</select></div>
      <div class='fld full'><button class='btn primary'>Save schedule</button>
        <a class='btn gh' href="{url_for('modules.module', mod='ris')}">Cancel</a></div>
    </form>"""
    return page('Schedule Study', f"<div class='panel'><div class='pad'>{inner}</div></div>", 'ris')


# ------------------------------------------------------------------ acquire
@bp.route('/ris/<int:oid>/acquire', methods=['GET', 'POST'])
@login_required
def acquire(oid):
    if not can('ris'):
        abort(403)
    o = RadOrder.query.get_or_404(oid)
    if not can_see(o):
        abort(403)
    if request.method == 'POST':
        o.technician = (request.form.get('technician') or (cur_user().username if cur_user() else ''))[:60]
        o.acquired_at = _now()
        if o.status == 'Requested':
            o.status = 'Imaged'      # reuse existing status so Radiology screen agrees
        elif o.status not in ('Imaged', 'Reported'):
            o.status = 'Imaged'
        if not o.requested_at:
            o.requested_at = _anchor(o) or _now()
        db.session.commit()
        log(f'RIS #{oid} images acquired by {o.technician}', entity=f'RadOrder#{oid}')
        flash('Marked acquired — you can now link DICOM images and report', 'ok')
        # send the tech straight to DICOM upload for this order
        return redirect(f"{url_for('pacs.upload')}?patient={o.patient_id or ''}&rad_order_id={o.id}")

    tech = cur_user().username if cur_user() else ''
    inner = f"""
    <form method='post' class='formwrap'>
      <div class='fld'><label>Patient</label><input value="{h(o.patient.name if o.patient else '')}" disabled></div>
      <div class='fld'><label>Technician</label><input name='technician' value="{h(tech)}"></div>
      <div class='fld full'><button class='btn primary'>Confirm acquisition</button>
        <a class='btn gh' href="{url_for('modules.module', mod='ris')}">Cancel</a></div>
    </form>
    <div style='font-size:12px;color:var(--muted);margin-top:6px'>After confirming you'll be taken to DICOM upload, pre-linked to this request.</div>"""
    return page('Acquire Images', f"<div class='panel'><div class='pad'>{inner}</div></div>", 'ris')


# ------------------------------------------------------------------ assign
@bp.route('/ris/<int:oid>/assign', methods=['GET', 'POST'])
@login_required
def assign(oid):
    if not can('ris'):
        abort(403)
    o = RadOrder.query.get_or_404(oid)
    if not can_see(o):
        abort(403)
    if request.method == 'POST':
        rid = request.form.get('rad_id')
        o.assigned_rad_id = int(rid) if rid else None
        db.session.commit()
        log(f'RIS #{oid} assigned to radiologist #{rid}', entity=f'RadOrder#{oid}')
        flash('Radiologist assigned', 'ok')
        return redirect(url_for('modules.module', mod='ris'))
    rads = Radiologist.query.filter_by(active=True).order_by(Radiologist.name).all()
    opts = "<option value=''>— unassigned —</option>" + ''.join(
        f"<option value='{r.id}' {'selected' if o.assigned_rad_id==r.id else ''}>{h(r.name)}</option>" for r in rads)
    inner = f"""
    <form method='post' class='formwrap'>
      <div class='fld full'><label>Radiologist</label><select name='rad_id'>{opts}</select></div>
      <div class='fld full'><button class='btn primary'>Assign</button>
        <a class='btn gh' href="{url_for('modules.module', mod='ris')}">Cancel</a></div>
    </form>"""
    return page('Assign Radiologist', f"<div class='panel'><div class='pad'>{inner}</div></div>", 'ris')


# ------------------------------------------------------------------ sign off
@bp.route('/ris/<int:oid>/approve', methods=['GET', 'POST'])
@login_required
def approve(oid):
    u = cur_user()
    if not (u and (u.role in ('super_admin', 'radiologist') or can('ris'))):
        abort(403)
    o = RadOrder.query.get_or_404(oid)
    if not can_see(o):
        abort(403)
    if o.status != 'Reported':
        flash('Report must be written before it can be signed off', 'error')
        return redirect(url_for('modules.module', mod='ris'))
    if request.method == 'POST':
        o.approved_at = _now()
        o.approved_by = (u.username if u else '')[:60]
        o.reported_at = o.reported_at or _now()
        o.signature = doc_sig(f'radorder:{o.id}:{(o.impression or o.report or "")[:200]}')
        o.rad_approved_at = o.approved_at     # also engage the existing print lock
        db.session.commit()
        log(f'RIS #{oid} report signed off by {o.approved_by}',
            action_type='Report Approval', entity=f'RadOrder#{oid}')
        flash('Report signed off', 'ok')
        return redirect(url_for('modules.module', mod='ris'))
    preview = h((o.impression or o.report or '(no findings text)')[:600])
    inner = f"""
    <div class='panel'><div class='pad'>
      <b>{h(o.patient.name if o.patient else '')}</b> · {h(o.modality or '')} · {h(o.service.name if o.service else '')}
      <div style='margin:10px 0;padding:10px;background:var(--bg2,#f7f7f7);border-radius:8px;white-space:pre-wrap;font-size:13px'>{preview}</div>
      <form method='post'>
        <p style='font-size:13px'>Signing as <b>{h(u.username if u else '')}</b>. This locks the report and stamps a verification signature.</p>
        <button class='btn primary'>✍ Sign &amp; approve</button>
        <a class='btn gh' href="{url_for('ris.approve', oid=o.id)}" onclick="history.back();return false;">Cancel</a>
      </form>
    </div></div>"""
    return page('Sign off Report', inner, 'ris')


# ------------------------------------------------------------------ TAT report
@bp.route('/ris/tat')
@login_required
def tat():
    if not can('ris'):
        abort(403)
    orders = branch_scope(RadOrder.query, RadOrder).all()
    by_mod = {}
    stage_counts = {}
    for o in orders:
        label, _c = _stage(o)
        stage_counts[label] = stage_counts.get(label, 0) + 1
        if o.approved_at:
            m = _tat_minutes(o)
            if m is not None:
                by_mod.setdefault(o.modality or '—', []).append(m)
    rows = []
    for mod, mins in sorted(by_mod.items()):
        avg = sum(mins) // len(mins)
        rows.append([h(mod), str(len(mins)), _fmt_tat(min(mins)), _fmt_tat(avg), _fmt_tat(max(mins))])
    scards = ''.join(
        f"<div class='panel' style='display:inline-block;min-width:120px;margin:4px'><div class='pad'>"
        f"<div style='font-size:22px;font-weight:700'>{v}</div>"
        f"<div style='font-size:12px;color:var(--muted)'>{h(k)}</div></div></div>"
        for k, v in stage_counts.items())
    board = f"<div style='margin-bottom:10px'>{scards}</div>"
    tbl = render_template(
        'list_page.html', title='Turnaround by Modality (signed studies)',
        headers=['Modality', 'Signed', 'Fastest', 'Average', 'Slowest'],
        aligns=['', 'num', 'num', 'num', 'num'], rows=rows,
        empty="<div class='empty'><b>No signed studies yet</b>TAT appears once reports are signed off.</div>")
    return page('Turnaround', board + tbl, 'ris',
                crumbs=[('RIS', url_for('modules.module', mod='ris')), ('Turnaround', None)])


# ------------------------------------------------------ imaging-resource CRUD
register('modalities', ImgModality, 'Imaging Modalities',
         columns=[('Name', lambda o: f"<b>{h(o.name)}</b>"),
                  ('Type', lambda o: pill(o.modality or '—', 'grey')),
                  ('Room', lambda o: h(o.room or '—')),
                  ('Status', lambda o: pill('Active' if o.active in (True, None) else 'Inactive',
                                            'green' if o.active in (True, None) else 'grey'))],
         fields=[dict(name='name', label='Name (e.g. CT Scanner 1)', required=True),
                 dict(name='modality', label='Modality', type='select',
                      options=[('', '—')] + [(m, m) for m in ('CT', 'MRI', 'X-Ray', 'Ultrasound', 'ECG', 'Mammography')]),
                 dict(name='room', label='Room / Location'),
                 dict(name='active', label='Status', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: ImgModality.query.order_by(ImgModality.name),
         search=['name', 'modality', 'room'])
