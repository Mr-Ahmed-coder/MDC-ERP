"""PACS — DICOM study storage, browser and web viewer  (Phase 1, v8.0).

Upload DICOM (single .dcm or a .zip of a study), organise by patient into a
Study -> Series -> Instance tree, view in an offline canvas viewer with
zoom / pan / rotate / invert / window-level / measurement / cine, download the
original study, and hand off to the existing radiologist reporting workflow.
"""
import os
import io
import json
import shutil
import zipfile
import tempfile
from flask import (Blueprint, request, redirect, url_for, send_file, flash, abort, render_template)
from markupsafe import escape as h
from werkzeug.utils import secure_filename
from ..extensions import db
from ..models import ImgStudy, ImgSeries, ImgInstance, Patient
from ..core.security import (cur_user, can, login_required, log, branch_scope,
                             can_see)
from ..core.helpers import today
from ..core.ui import page
from ..core.crud import opt_patients
from ..core import dicomproc
from ..config import DATA_DIR

bp = Blueprint('pacs', __name__)

PACS_ROOT = os.path.join(DATA_DIR, 'uploads', 'pacs')


# ------------------------------------------------------------------ helpers
def _study_dir(study_id):
    return os.path.join(PACS_ROOT, str(study_id))


def _dir_size_kb(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total // 1024


def _mod_pill(m):
    colors = {'CT': 'blue', 'MR': 'petrol', 'CR': 'teal', 'DX': 'teal',
              'US': 'green', 'XA': 'amber', 'MG': 'red', 'NM': 'amber'}
    return f"<span class='pill {colors.get((m or '').upper(), 'grey')}'>{h(m or '—')}</span>"


# ------------------------------------------------------------------ list
def pacs_list():
    """Study worklist — reachable from the App Launcher (mod='pacs')."""
    q = (request.args.get('q') or '').strip()
    query = branch_scope(ImgStudy.query, ImgStudy).order_by(ImgStudy.id.desc())
    if q:
        like = f'%{q}%'
        query = query.join(Patient, isouter=True).filter(
            db.or_(Patient.name.ilike(like), ImgStudy.description.ilike(like),
                   ImgStudy.accession.ilike(like), ImgStudy.modality.ilike(like)))
    studies = query.limit(400).all()
    rows = []
    for s in studies:
        st = {'New': 'amber', 'Reviewed': 'green'}.get(s.status, 'grey')
        acts = (f"<a class='btn sm primary' href='{url_for('pacs.viewer', sid=s.id)}'>🖥 View</a> "
                f"<a class='btn sm' href='{url_for('pacs.study', sid=s.id)}'>Open</a>")
        rows.append([
            h(s.study_date or s.created.strftime('%Y-%m-%d')),
            h(s.patient.name if s.patient else '—'),
            _mod_pill(s.modality),
            h(s.description or '—'),
            f"{s.num_series or 0} / {s.num_instances or 0}",
            f"<span class='pill {st}'>{h(s.status)}</span>",
            acts,
        ])
    toolbar = f"<a class='btn primary' href='{url_for('pacs.upload')}'>⬆ Upload DICOM</a>"
    body = render_template(
        'list_page.html', title='PACS · Imaging Studies', toolbar=toolbar,
        headers=['Date', 'Patient', 'Modality', 'Study', 'Series/Img', 'Status', ''],
        aligns=['', '', '', '', 'num', '', 'num'], rows=rows,
        empty="<div class='empty'><b>No studies yet</b>Upload a DICOM file or a zipped study to begin.</div>")
    return page('PACS', body, 'pacs')


# ------------------------------------------------------------------ upload
@bp.route('/pacs/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if not can('pacs'):
        abort(403)
    if not dicomproc.available():
        msg = ("<div class='panel' style='border-left:3px solid var(--amber-dk)'><div class='pad'>"
               "<b>DICOM support is not installed on this computer.</b><br>"
               "PACS storage and the viewer work, but importing DICOM files needs three "
               "extra Python packages. Install them once, then restart the app:"
               "<pre style='background:#f5f5f5;padding:8px;border-radius:6px;margin-top:8px'>"
               "pip install pydicom numpy Pillow</pre>"
               "or run <code>pip install -r requirements.txt</code> from the app folder.</div></div>")
        return page('Upload DICOM', msg, 'pacs')
    if request.method == 'POST':
        files = [f for f in request.files.getlist('dicom') if f and f.filename]
        if not files:
            flash('Choose at least one .dcm file or a .zip study', 'error')
            return redirect(url_for('pacs.upload'))
        patient_id = request.form.get('patient_id') or None
        rad_order_id = request.form.get('rad_order_id') or None

        # 1) stage every uploaded file (expanding any zip archives) to a temp dir
        staged = []
        tmp = tempfile.mkdtemp(prefix='pacs_')
        try:
            for f in files:
                name = secure_filename(f.filename) or 'file'
                dest = os.path.join(tmp, name)
                f.save(dest)
                if name.lower().endswith('.zip'):
                    try:
                        with zipfile.ZipFile(dest) as z:
                            z.extractall(os.path.join(tmp, name + '_x'))
                        for root, _d, fs in os.walk(os.path.join(tmp, name + '_x')):
                            staged.extend(os.path.join(root, x) for x in fs)
                    except zipfile.BadZipFile:
                        pass
                else:
                    staged.append(dest)

            dcm_files = list(dicomproc.iter_dicom_files(staged))
            if not dcm_files:
                flash('No valid DICOM images found in the upload', 'error')
                return redirect(url_for('pacs.upload'))

            n = _ingest(dcm_files, patient_id, rad_order_id)
            flash(f'Imported {n} image(s) into a new study', 'ok')
            return redirect(url_for('pacs.study', sid=_LAST['sid']))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    fields = [
        dict(name='patient_id', label='Patient', type='select',
             options=opt_patients(), default=request.args.get('patient', '')),
        dict(name='dicom', label='DICOM file(s) or .zip study', type='file',
             accept='.dcm,.zip,application/dicom,application/zip', multiple=True, full=True),
    ]
    from ..core.crud import render_form
    hint = ("<div class='panel' style='border-left:3px solid var(--blue)'><div class='pad' style='font-size:13px'>"
            "Upload one or more <b>.dcm</b> files, or a single <b>.zip</b> containing a full study. "
            "Images are organised automatically into Study → Series and rendered for the viewer. "
            "Compressed frames whose codec is unavailable are still catalogued.</div></div>")
    ro = request.args.get('rad_order_id', '')
    extra = f"<input type='hidden' name='rad_order_id' value='{h(ro)}'>" if ro else ''
    form = render_form('Upload DICOM Study', url_for('pacs.upload'), fields,
                       back=url_for('modules.module', mod='pacs'),
                       enctype='multipart/form-data')
    return page('Upload DICOM', hint + form.replace('</form>', extra + '</form>'), 'pacs')


_LAST = {'sid': None}   # tiny carry so upload() can redirect to the new study


def _ingest(dcm_files, patient_id, rad_order_id):
    """Create the Study/Series/Instance rows and render frames. Returns count."""
    u = cur_user()
    study = ImgStudy(patient_id=patient_id or None,
                     rad_order_id=rad_order_id or None,
                     branch_id=(u.branch_id if u else None),
                     status='New', uploaded_by=(u.username if u else None),
                     study_date=today())
    db.session.add(study)
    db.session.flush()                       # need study.id for storage paths
    _LAST['sid'] = study.id

    series_map = {}          # series_uid -> ImgSeries
    modalities = set()
    total_instances = 0

    for idx, path in enumerate(sorted(dcm_files)):
        try:
            meta = dicomproc.read_metadata(path)
        except Exception:
            continue
        if not study.study_uid and meta['study_uid']:
            study.study_uid = meta['study_uid'][:120]
            study.accession = meta['accession']
            study.description = meta['study_desc']
            study.body_part = meta['body_part']
            study.referring = meta['referring']
            if meta['study_date']:
                study.study_date = meta['study_date']

        skey = meta['series_uid'] or f'series-{meta["series_no"]}'
        ser = series_map.get(skey)
        if ser is None:
            ser = ImgSeries(study_id=study.id, series_uid=meta['series_uid'][:120],
                            series_number=meta['series_no'] or (len(series_map) + 1),
                            modality=meta['modality'], description=meta['series_desc'],
                            body_part=meta['body_part'], num_instances=0)
            db.session.add(ser)
            db.session.flush()
            series_map[skey] = ser
        modalities.add(meta['modality'])

        inst = ImgInstance(series_id=ser.id, sop_uid=meta['sop_uid'][:120],
                           instance_number=meta['instance_no'] or (ser.num_instances + 1),
                           rows=meta['rows'], cols=meta['cols'],
                           pixel_spacing=meta['pixel_spacing'],
                           orig_name=os.path.basename(path)[:160])
        db.session.add(inst)
        db.session.flush()

        rel = os.path.join(str(ser.id), str(inst.id))
        out_dir = os.path.join(_study_dir(study.id), rel)
        frames, wc, ww = dicomproc.render_frames(path, out_dir)
        inst.frames = frames
        inst.win_center = wc
        inst.win_width = ww
        inst.rel_dir = rel
        # keep the original DICOM for lossless download
        try:
            shutil.copy2(path, os.path.join(out_dir, 'orig.dcm'))
        except Exception:
            pass
        ser.num_instances += 1
        total_instances += 1

    study.num_series = len(series_map)
    study.num_instances = total_instances
    mods = {m for m in modalities if m}
    study.modality = (mods.pop() if len(mods) == 1 else 'MIXED') if mods else 'OT'
    study.size_kb = _dir_size_kb(_study_dir(study.id))
    db.session.commit()
    log(f'PACS study #{study.id} uploaded — {total_instances} image(s)',
        entity=f'ImgStudy#{study.id}')
    return total_instances


# ------------------------------------------------------------------ detail
@bp.route('/pacs/study/<int:sid>')
@login_required
def study(sid):
    if not can('pacs'):
        abort(403)
    s = ImgStudy.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    meta = (f"<div class='panel'><div class='pad'>"
            f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:6px 24px;font-size:13px'>"
            f"<div><b>Patient:</b> {h(s.patient.name if s.patient else '—')}</div>"
            f"<div><b>Study date:</b> {h(s.study_date or '—')}</div>"
            f"<div><b>Modality:</b> {_mod_pill(s.modality)}</div>"
            f"<div><b>Accession:</b> {h(s.accession or '—')}</div>"
            f"<div><b>Description:</b> {h(s.description or '—')}</div>"
            f"<div><b>Body part:</b> {h(s.body_part or '—')}</div>"
            f"<div><b>Series:</b> {s.num_series}</div>"
            f"<div><b>Images:</b> {s.num_instances}</div>"
            f"<div><b>Size:</b> {s.size_kb} KB</div>"
            f"<div><b>Status:</b> <span class='pill {'green' if s.status=='Reviewed' else 'amber'}'>{h(s.status)}</span></div>"
            f"</div></div></div>")

    blocks = ''
    for ser in s.series:
        thumbs = ''
        for inst in ser.instances:
            if inst.frames:
                src = url_for('pacs.thumb', iid=inst.id)
                thumbs += (f"<a href='{url_for('pacs.viewer', sid=s.id)}?inst={inst.id}' title='Instance {inst.instance_number}'>"
                           f"<img src='{src}' style='height:96px;border:1px solid var(--line);border-radius:8px;object-fit:cover'></a>")
            else:
                thumbs += ("<span class='pill grey' style='height:96px;display:inline-flex;align-items:center;"
                           "padding:0 10px;border-radius:8px'>codec N/A</span>")
        blocks += (f"<div class='panel'><div class='pad'>"
                   f"<b>Series {ser.series_number}</b> {_mod_pill(ser.modality)} "
                   f"<span style='color:var(--muted)'>{h(ser.description or '')}</span> "
                   f"<span class='pill grey'>{ser.num_instances} img</span>"
                   f"<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:10px'>{thumbs}</div>"
                   f"</div></div>")

    report = ''
    if s.rad_order_id:
        report = (f"<a class='btn' href='{url_for('rad.rad_report', oid=s.rad_order_id)}'>📝 Radiology Report</a> ")
    elif s.patient_id:
        report = (f"<a class='btn' href='{url_for('rad.rad_new')}?patient={s.patient_id}'>📝 Create Report Request</a> ")

    review = ''
    if s.status != 'Reviewed':
        review = f"<a class='btn' href='{url_for('pacs.mark_reviewed', sid=s.id)}'>✓ Mark Reviewed</a> "
    delbtn = ''
    if cur_user() and cur_user().role in ('super_admin', 'it_admin'):
        delbtn = (f"<a class='btn gh sm' style='color:var(--red)' "
                  f"href='{url_for('pacs.delete', sid=s.id)}' "
                  f"onclick=\"return confirm('Delete this study and all its images?')\">🗑 Delete</a>")
    toolbar = (f"<a class='btn primary' href='{url_for('pacs.viewer', sid=s.id)}'>🖥 Open Viewer</a> "
               f"<a class='btn' href='{url_for('pacs.download', sid=s.id)}'>⬇ Download study</a> "
               f"{report}{review}{delbtn}")
    body = f"<div style='margin-bottom:10px'>{toolbar}</div>{meta}{blocks}"
    return page(f'Study #{s.id}', body, 'pacs',
                crumbs=[('PACS', url_for('modules.module', mod='pacs')), (f'Study #{s.id}', None)])


# ------------------------------------------------------------------ viewer
@bp.route('/pacs/study/<int:sid>/viewer')
@login_required
def viewer(sid):
    if not can('pacs'):
        abort(403)
    s = ImgStudy.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    # flat list of viewable instances for the JS viewer
    seq = []
    for ser in s.series:
        for inst in ser.instances:
            if not inst.frames:
                continue
            seq.append({
                'id': inst.id, 'series': ser.series_number, 'inst': inst.instance_number,
                'frames': inst.frames, 'wc': inst.win_center, 'ww': inst.win_width,
                'spacing': inst.pixel_spacing, 'mod': ser.modality,
                'desc': ser.description or '',
                'base': url_for('pacs.frame', iid=inst.id, n=0).rsplit('/0.png', 1)[0],
            })
    start = request.args.get('inst', type=int)
    start_idx = next((i for i, x in enumerate(seq) if x['id'] == start), 0)
    label = f"{h(s.patient.name if s.patient else 'Study')} · {h(s.description or s.modality or '')}"
    return page('DICOM Viewer',
                _viewer_html(seq, start_idx, label, s.id),
                'pacs')


def _viewer_html(seq, start_idx, label, sid):
    data = json.dumps(seq)
    back = url_for('pacs.study', sid=sid)
    return f"""
<div style='margin-bottom:8px'>
  <a class='btn gh sm' href='{back}'>← Back to study</a>
  <span style='color:var(--muted);margin-left:8px'>{label}</span>
</div>
<div class='panel'><div class='pad' style='padding:10px'>
  <div id='vtools' style='display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;font-size:13px'>
    <button class='btn sm' data-t='prev'>◀ Prev</button>
    <button class='btn sm' data-t='next'>Next ▶</button>
    <button class='btn sm' data-t='cine'>▶ Cine</button>
    <button class='btn sm' data-t='zin'>＋ Zoom</button>
    <button class='btn sm' data-t='zout'>－ Zoom</button>
    <button class='btn sm' data-t='rot'>⟳ Rotate</button>
    <button class='btn sm' data-t='inv'>◐ Invert</button>
    <button class='btn sm' data-t='measure'>📏 Measure</button>
    <button class='btn sm' data-t='reset'>Reset</button>
    <span id='vinfo' style='margin-left:auto;color:var(--muted)'></span>
  </div>
  <div style='display:flex;gap:10px;font-size:12px;color:var(--muted);margin-bottom:6px'>
    <label>Brightness <input id='vbri' type='range' min='-127' max='127' value='0'></label>
    <label>Contrast <input id='vcon' type='range' min='-100' max='100' value='0'></label>
    <span id='vframe'></span>
  </div>
  <canvas id='vcanvas' width='760' height='560'
     style='width:100%;max-width:820px;background:#000;border-radius:8px;cursor:crosshair;touch-action:none'></canvas>
  <div style='font-size:11px;color:var(--muted);margin-top:6px'>
    Drag = pan · Wheel = zoom · Brightness/Contrast approximate window/level on the rendered frame ·
    Measure needs pixel spacing for mm.
  </div>
</div></div>
<script>
(function(){{
  const SEQ = {data}; let ix = {start_idx}; let frame = 0;
  const cv = document.getElementById('vcanvas'), ctx = cv.getContext('2d');
  const info = document.getElementById('vinfo'), finfo = document.getElementById('vframe');
  const bri = document.getElementById('vbri'), con = document.getElementById('vcon');
  let img = new Image(), st = null, cine = null, measuring = false, mA = null, mB = null;
  function fresh(){{ return {{zoom:1, panx:0, pany:0, rot:0, inv:false, bri:0, con:0}}; }}
  function cur(){{ return SEQ[ix]; }}
  function load(){{ const c = cur(); if(!c) return;
    frame = Math.min(frame, c.frames-1); if(frame<0) frame=0;
    img = new Image();
    img.onload = draw;
    img.src = c.base + '/' + frame + '.png';
    info.textContent = 'Series '+c.series+' · Img '+c.inst+' ('+(ix+1)+'/'+SEQ.length+')';
    finfo.textContent = c.frames>1 ? ('Frame '+(frame+1)+'/'+c.frames) : '';
    mA = mB = null;
  }}
  function draw(){{
    if(!img.width) return;
    ctx.save(); ctx.fillStyle='#000'; ctx.fillRect(0,0,cv.width,cv.height); ctx.restore();
    const s = st, cw=cv.width, ch=cv.height;
    ctx.save();
    ctx.translate(cw/2 + s.panx, ch/2 + s.pany);
    ctx.rotate(s.rot*Math.PI/180); ctx.scale(s.zoom, s.zoom);
    const scale = Math.min(cw/img.width, ch/img.height);
    const w = img.width*scale, hh = img.height*scale;
    const b = 1 + s.con/100, br = s.bri;
    ctx.filter = 'brightness('+(1+br/127)+') contrast('+b+')' + (s.inv?' invert(1)':'');
    ctx.drawImage(img, -w/2, -hh/2, w, hh);
    ctx.restore();
    if(mA && mB){{
      ctx.strokeStyle='#F57C00'; ctx.lineWidth=2; ctx.beginPath();
      ctx.moveTo(mA.x,mA.y); ctx.lineTo(mB.x,mB.y); ctx.stroke();
      const dx=mB.x-mA.x, dy=mB.y-mA.y; const dpx=Math.hypot(dx,dy);
      const sp=cur().spacing; const scr=Math.min(cw/img.width,ch/img.height)*st.zoom;
      let lbl = dpx.toFixed(0)+' px';
      if(sp){{ lbl = (dpx/scr*sp).toFixed(1)+' mm'; }}
      ctx.fillStyle='#F57C00'; ctx.font='13px sans-serif';
      ctx.fillText(lbl, (mA.x+mB.x)/2+6, (mA.y+mB.y)/2);
    }}
  }}
  function reset(){{ st = fresh(); bri.value=0; con.value=0; draw(); }}
  st = fresh();
  document.getElementById('vtools').addEventListener('click', e=>{{
    const t = e.target.dataset.t; if(!t) return; const c = cur();
    if(t==='next'){{ if(c && frame<c.frames-1) frame++; else {{ ix=(ix+1)%SEQ.length; frame=0; }} reset(); load(); }}
    if(t==='prev'){{ if(frame>0) frame--; else {{ ix=(ix-1+SEQ.length)%SEQ.length; frame=0; }} reset(); load(); }}
    if(t==='zin') st.zoom*=1.2; if(t==='zout') st.zoom/=1.2;
    if(t==='rot') st.rot=(st.rot+90)%360; if(t==='inv') st.inv=!st.inv;
    if(t==='reset'){{ reset(); }}
    if(t==='measure'){{ measuring=!measuring; e.target.classList.toggle('primary', measuring); mA=mB=null; }}
    if(t==='cine'){{
      if(cine){{ clearInterval(cine); cine=null; e.target.textContent='▶ Cine'; }}
      else if(c && c.frames>1){{ e.target.textContent='⏸ Stop';
        cine=setInterval(()=>{{ frame=(frame+1)%c.frames; load(); }}, 120); }}
    }}
    draw();
  }});
  bri.oninput=()=>{{ st.bri=+bri.value; draw(); }};
  con.oninput=()=>{{ st.con=+con.value; draw(); }};
  cv.addEventListener('wheel', e=>{{ e.preventDefault(); st.zoom*= e.deltaY<0?1.1:0.9; draw(); }}, {{passive:false}});
  let drag=false, lx=0, ly=0;
  function pos(e){{ const r=cv.getBoundingClientRect();
    return {{x:(e.clientX-r.left)*cv.width/r.width, y:(e.clientY-r.top)*cv.height/r.height}}; }}
  cv.addEventListener('pointerdown', e=>{{ const p=pos(e);
    if(measuring){{ mA=p; mB=p; }} else {{ drag=true; lx=e.clientX; ly=e.clientY; }} }});
  cv.addEventListener('pointermove', e=>{{ const p=pos(e);
    if(measuring && mA){{ mB=p; draw(); }}
    else if(drag){{ st.panx+=(e.clientX-lx); st.pany+=(e.clientY-ly); lx=e.clientX; ly=e.clientY; draw(); }} }});
  window.addEventListener('pointerup', ()=>{{ drag=false; }});
  load();
}})();
</script>
"""


# ------------------------------------------------------------------ media
@bp.route('/pacs/inst/<int:iid>/frame/<int:n>.png')
@login_required
def frame(iid, n):
    if not can('pacs'):
        abort(403)
    inst = ImgInstance.query.get_or_404(iid)
    s = ImgStudy.query.get(inst.series.study_id)
    if not can_see(s):
        abort(403)
    fp = os.path.join(_study_dir(s.id), inst.rel_dir, f'frame_{n}.png')
    if not os.path.exists(fp):
        abort(404)
    return send_file(fp, mimetype='image/png')


@bp.route('/pacs/inst/<int:iid>/thumb.png')
@login_required
def thumb(iid):
    if not can('pacs'):
        abort(403)
    inst = ImgInstance.query.get_or_404(iid)
    s = ImgStudy.query.get(inst.series.study_id)
    if not can_see(s):
        abort(403)
    fp = os.path.join(_study_dir(s.id), inst.rel_dir, 'thumb.png')
    if not os.path.exists(fp):
        fp = os.path.join(_study_dir(s.id), inst.rel_dir, 'frame_0.png')
    if not os.path.exists(fp):
        abort(404)
    return send_file(fp, mimetype='image/png')


@bp.route('/pacs/study/<int:sid>/download')
@login_required
def download(sid):
    if not can('pacs'):
        abort(403)
    s = ImgStudy.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        for ser in s.series:
            for inst in ser.instances:
                orig = os.path.join(_study_dir(s.id), inst.rel_dir, 'orig.dcm')
                if os.path.exists(orig):
                    z.write(orig, f'series{ser.series_number}/{inst.orig_name or (str(inst.id)+".dcm")}')
    mem.seek(0)
    log(f'PACS study #{s.id} downloaded', entity=f'ImgStudy#{s.id}')
    return send_file(mem, mimetype='application/zip', as_attachment=True,
                     download_name=f'study_{s.id}.zip')


@bp.route('/pacs/study/<int:sid>/reviewed')
@login_required
def mark_reviewed(sid):
    if not can('pacs'):
        abort(403)
    s = ImgStudy.query.get_or_404(sid)
    if not can_see(s):
        abort(403)
    s.status = 'Reviewed'
    db.session.commit()
    log(f'PACS study #{s.id} marked reviewed', entity=f'ImgStudy#{s.id}')
    flash('Study marked reviewed', 'ok')
    return redirect(url_for('pacs.study', sid=s.id))


@bp.route('/pacs/study/<int:sid>/delete')
@login_required
def delete(sid):
    if not (cur_user() and cur_user().role in ('super_admin', 'it_admin')):
        abort(403)
    s = ImgStudy.query.get_or_404(sid)
    shutil.rmtree(_study_dir(s.id), ignore_errors=True)
    db.session.delete(s)
    db.session.commit()
    log(f'PACS study #{sid} deleted', entity=f'ImgStudy#{sid}')
    flash('Study deleted', 'ok')
    return redirect(url_for('modules.module', mod='pacs'))
