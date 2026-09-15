"""Universal Global Search — engine, providers & palette UI  (Phase 16, v8.0).

A permission-aware, branch-scoped search across every module. Each provider
declares the permission it needs and a query function; the engine only runs
providers the current user may access, ranks and highlights matches, and groups
results by category. Substring matching is Unicode-safe (works for Latin,
Arabic and any script); a bounded difflib pass adds typo tolerance on names.

Kept dependency-free and offline-friendly. Designed to answer within the 500 ms
budget by LIMITing every provider query and capping the fuzzy candidate set.
"""
import time
import difflib
import datetime as dt
from flask import url_for
from markupsafe import escape as h
from .security import can, branch_scope
from ..extensions import db

PER_CAT = 6            # results shown per category
CAND = 25             # candidate rows pulled per provider before ranking
FUZZY_POOL = 250      # max names scanned for typo tolerance


# --------------------------------------------------------------- helpers
def _like(term):
    return f"%{term}%"


def _norm(s):
    return (s or '').strip().lower()


def _reg_url(key, oid, fallback_mod=None):
    """Link to a REG record's edit page if that module exists, else its list."""
    from .crud import REG
    try:
        if key in REG:
            return url_for('modules.module_edit', mod=key, oid=oid)
    except Exception:
        pass
    return url_for('modules.module', mod=(fallback_mod or key))


def _dstr(v):
    if not v:
        return ''
    return str(v)[:16]


def _score(hay, q, tokens):
    hay = _norm(hay)
    if not hay:
        return 0
    if hay == q:
        return 100
    if hay.startswith(q):
        return 85
    if q and q in hay:
        return 68
    present = sum(1 for t in tokens if t and t in hay)
    if present:
        return 30 + int(20 * present / len(tokens))
    # fuzzy: best ratio over the whole string and each word (typo tolerance)
    best = difflib.SequenceMatcher(None, hay, q).ratio()
    for w in hay.split():
        if abs(len(w) - len(q)) <= 3:
            best = max(best, difflib.SequenceMatcher(None, w, q).ratio())
    return int(best * 48) if best >= 0.68 else 0


def _hl(text, tokens):
    """Highlight token matches (case-insensitive, Unicode-safe)."""
    s = str(text or '')
    if not s:
        return ''
    low = s.lower()
    marks = []
    for t in tokens:
        if not t:
            continue
        start = 0
        while True:
            i = low.find(t, start)
            if i < 0:
                break
            marks.append((i, i + len(t)))
            start = i + len(t)
    if not marks:
        return str(h(s))
    # merge overlapping spans
    marks.sort()
    merged = [marks[0]]
    for a, b in marks[1:]:
        if a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    out, prev = '', 0
    for a, b in merged:
        out += str(h(s[prev:a])) + '<mark>' + str(h(s[a:b])) + '</mark>'
        prev = b
    out += str(h(s[prev:]))
    return out


# --------------------------------------------------------------- providers
# Each provider: (category label, icon, permission, callable(term)->[hit dicts]).
# A hit dict: {title, desc, module, status, updated, url, id_hint}

def _patients(term):
    from ..models import Patient
    like = _like(term)
    q = branch_scope(Patient.query, Patient).filter(db.or_(
        Patient.name.ilike(like), Patient.mrn.ilike(like), Patient.phone.ilike(like),
        Patient.phone2.ilike(like), Patient.gov_id.ilike(like), Patient.ins_number.ilike(like)))
    rows = q.limit(CAND).all()
    # typo tolerance on names
    if len(rows) < 3 and len(term) >= 3:
        pool = branch_scope(Patient.query, Patient).limit(FUZZY_POOL).all()
        tokmap = {}
        for p in pool:
            for w in (p.name or '').lower().split():
                tokmap.setdefault(w, p)
        for nm in difflib.get_close_matches(term, list(tokmap), n=6, cutoff=0.72):
            if tokmap[nm] not in rows:
                rows.append(tokmap[nm])
    out = []
    for p in rows:
        out.append(dict(title=p.name or f'Patient #{p.id}',
                        desc=f"MRN {p.mrn or '—'} · {p.phone or ''}"
                             + (f" · ID {p.gov_id}" if p.gov_id else ''),
                        module='Patients', status=p.gender or '',
                        updated=_dstr(getattr(p, 'created', None)),
                        url=url_for('patients.patient_detail', pid=p.id),
                        hay=f"{p.name} {p.mrn} {p.phone} {p.phone2} {p.gov_id} {p.ins_number}"))
    return out


def _invoices(term):
    from ..models import Invoice, Patient
    like = _like(term)
    q = branch_scope(Invoice.query, Invoice).outerjoin(Patient, Invoice.patient_id == Patient.id).filter(
        db.or_(db.cast(Invoice.id, db.String).ilike(like), Invoice.guarantor.ilike(like),
               Invoice.status.ilike(like), Patient.name.ilike(like)))
    rows = q.order_by(Invoice.id.desc()).limit(CAND).all()
    out = []
    for i in rows:
        pn = i.patient.name if getattr(i, 'patient', None) else ''
        out.append(dict(title=f"Invoice #{i.id}",
                        desc=f"{pn} · {i.guarantor or ''}".strip(' ·'),
                        module='Billing', status=i.status or '',
                        updated=_dstr(i.date),
                        url=url_for('billing.invoice_view', iid=i.id),
                        hay=f"{i.id} {i.guarantor} {pn} {i.status}"))
    return out


def _lab(term):
    from ..models import LabOrder, Patient
    like = _like(term)
    q = branch_scope(LabOrder.query, LabOrder).outerjoin(Patient, LabOrder.patient_id == Patient.id).filter(
        db.or_(db.cast(LabOrder.id, db.String).ilike(like), LabOrder.sample_no.ilike(like),
               LabOrder.status.ilike(like), Patient.name.ilike(like)))
    rows = q.order_by(LabOrder.id.desc()).limit(CAND).all()
    out = []
    for o in rows:
        pn = o.patient.name if getattr(o, 'patient', None) else ''
        svc = o.service.name if getattr(o, 'service', None) else 'Lab test'
        out.append(dict(title=f"Lab #{o.id} · {svc}",
                        desc=f"{pn} · sample {o.sample_no or '—'}",
                        module='Laboratory', status=o.status or '',
                        updated=_dstr(o.date),
                        url=url_for('lab.lab_result', oid=o.id),
                        hay=f"{o.id} {o.sample_no} {pn} {svc} {o.status}"))
    return out


def _rad(term):
    from ..models import RadOrder, Patient
    like = _like(term)
    q = branch_scope(RadOrder.query, RadOrder).outerjoin(Patient, RadOrder.patient_id == Patient.id).filter(
        db.or_(db.cast(RadOrder.id, db.String).ilike(like), RadOrder.modality.ilike(like),
               RadOrder.status.ilike(like), Patient.name.ilike(like)))
    rows = q.order_by(RadOrder.id.desc()).limit(CAND).all()
    out = []
    for o in rows:
        pn = o.patient.name if getattr(o, 'patient', None) else ''
        svc = o.service.name if getattr(o, 'service', None) else (o.modality or 'Imaging')
        out.append(dict(title=f"Imaging #{o.id} · {svc}",
                        desc=f"{pn} · {o.modality or ''}",
                        module='Radiology', status=o.status or '',
                        updated=_dstr(o.date),
                        url=url_for('rad.rad_report', oid=o.id),
                        hay=f"{o.id} {o.modality} {pn} {svc} {o.status}"))
    return out


def _pharmacy(term):
    from ..models import Prescription, Patient, Medicine
    like = _like(term)
    out = []
    q = branch_scope(Prescription.query, Prescription).outerjoin(
        Patient, Prescription.patient_id == Patient.id).filter(
        db.or_(db.cast(Prescription.id, db.String).ilike(like), Prescription.doctor.ilike(like),
               Patient.name.ilike(like)))
    for pr in q.order_by(Prescription.id.desc()).limit(CAND).all():
        pn = pr.patient.name if getattr(pr, 'patient', None) else ''
        out.append(dict(title=f"Rx #{pr.id}", desc=f"{pn} · {pr.dosage or ''}",
                        module='Pharmacy', status=pr.status or '', updated=_dstr(pr.date),
                        url=url_for('patients.patient_detail', pid=pr.patient_id) if pr.patient_id
                        else url_for('modules.module', mod='pharmacy'),
                        hay=f"{pr.id} {pr.doctor} {pn}"))
    for m in Medicine.query.filter(db.or_(Medicine.name.ilike(like), Medicine.batch.ilike(like))).limit(CAND).all():
        out.append(dict(title=m.name, desc=f"Batch {m.batch or '—'} · stock {m.qty}",
                        module='Pharmacy', status=('low' if (m.qty or 0) <= (m.reorder or 0) else 'ok'),
                        updated=_dstr(m.expiry), url=_reg_url('medicines', m.id, 'pharmacy'),
                        hay=f"{m.name} {m.batch}"))
    return out


def _appointments(term):
    from ..models import Appointment, Patient
    like = _like(term)
    q = branch_scope(Appointment.query, Appointment).outerjoin(Patient, Appointment.patient_id == Patient.id).filter(
        db.or_(Appointment.doctor.ilike(like), Appointment.department.ilike(like),
               Appointment.status.ilike(like), Patient.name.ilike(like)))
    rows = q.order_by(Appointment.id.desc()).limit(CAND).all()
    out = []
    for a in rows:
        pn = a.patient.name if getattr(a, 'patient', None) else ''
        out.append(dict(title=f"{pn or 'Appointment'} · {a.department or ''}".strip(' ·'),
                        desc=f"{a.date or ''} {a.time or ''} · {a.doctor or ''}".strip(),
                        module='Appointments', status=a.status or '',
                        updated=f"{a.date or ''}",
                        url=url_for('patients.patient_detail', pid=a.patient_id) if a.patient_id
                        else url_for('modules.module', mod='queue'),
                        hay=f"{pn} {a.doctor} {a.department} {a.status}"))
    return out


def _staff(term):
    from ..models import Doctor, Employee, User
    like = _like(term)
    out = []
    for d in Doctor.query.filter(db.or_(Doctor.name.ilike(like), Doctor.specialty.ilike(like),
                                        Doctor.phone.ilike(like))).limit(CAND).all():
        out.append(dict(title=d.name, desc=f"Doctor · {d.specialty or ''} · {d.phone or ''}".strip(' ·'),
                        module='Staff', status='active' if d.active in (True, None) else 'inactive',
                        updated='', url=_reg_url('doctors', d.id), hay=f"{d.name} {d.specialty} {d.phone}"))
    for e in Employee.query.filter(db.or_(Employee.name.ilike(like), Employee.code.ilike(like),
                                          Employee.position.ilike(like))).limit(CAND).all():
        out.append(dict(title=e.name, desc=f"{e.position or 'Staff'} · {e.dept or ''} · ID {e.code or '—'}".strip(' ·'),
                        module='Staff', status='active' if e.active in (True, None) else 'inactive',
                        updated='', url=_reg_url('employees', e.id, 'employees'),
                        hay=f"{e.name} {e.code} {e.position} {e.dept}"))
    if can('users'):
        for us in User.query.filter(db.or_(User.username.ilike(like), User.name.ilike(like))).limit(CAND).all():
            out.append(dict(title=us.username, desc=f"User · {us.name or ''} · {us.role}",
                            module='Staff', status='active' if us.active else 'disabled',
                            updated='', url=_reg_url('users', us.id, 'users'),
                            hay=f"{us.username} {us.name} {us.role}"))
    return out


def _suppliers(term):
    from ..models import Supplier
    like = _like(term)
    out = []
    for s in Supplier.query.filter(db.or_(Supplier.name.ilike(like), Supplier.phone.ilike(like),
                                          Supplier.contact_person.ilike(like))).limit(CAND).all():
        out.append(dict(title=s.name, desc=f"{s.category or 'Supplier'} · {s.phone or ''}".strip(' ·'),
                        module='Suppliers', status='', updated='',
                        url=_reg_url('suppliers', s.id, 'suppliers'), hay=f"{s.name} {s.phone} {s.contact_person}"))
    return out


def _assets(term):
    from ..models import Asset
    like = _like(term)
    out = []
    for a in branch_scope(Asset.query, Asset).filter(db.or_(
            Asset.name.ilike(like), Asset.code.ilike(like), Asset.serial.ilike(like))).limit(CAND).all():
        out.append(dict(title=a.name, desc=f"{a.category or 'Asset'} · {a.code or ''} · SN {a.serial or '—'}".strip(' ·'),
                        module='Assets', status=a.status or '', updated=_dstr(a.purchase_date),
                        url=_reg_url('assets', a.id, 'assets'), hay=f"{a.name} {a.code} {a.serial}"))
    return out


def _vehicles(term):
    from ..models import Ambulance
    like = _like(term)
    out = []
    for v in branch_scope(Ambulance.query, Ambulance).filter(db.or_(
            Ambulance.label.ilike(like), Ambulance.plate.ilike(like))).limit(CAND).all():
        out.append(dict(title=v.label, desc=f"Ambulance · {v.plate or ''} · {v.kind or ''}".strip(' ·'),
                        module='Vehicles', status=v.status or '', updated='',
                        url=_reg_url('vehicles', v.id, 'vehicles'), hay=f"{v.label} {v.plate}"))
    return out


def _insurance(term):
    from ..models import Insurer, Claim
    like = _like(term)
    out = []
    for ins in branch_scope(Insurer.query, Insurer).filter(db.or_(
            Insurer.name.ilike(like), Insurer.code.ilike(like))).limit(CAND).all():
        out.append(dict(title=ins.name, desc=f"Insurer · {ins.code or ''}".strip(' ·'),
                        module='Insurance', status='active' if ins.active in (True, None) else 'inactive',
                        updated='', url=_reg_url('insurers', ins.id, 'insurance'), hay=f"{ins.name} {ins.code}"))
    for c in Claim.query.filter(db.or_(Claim.claim_no.ilike(like), Claim.status.ilike(like))).limit(CAND).all():
        out.append(dict(title=f"Claim {c.claim_no or c.id}", desc=f"claimed {c.claimed or 0}",
                        module='Insurance', status=c.status or '', updated=_dstr(c.submitted_at),
                        url=url_for('modules.module', mod='claims') if _has_reg('claims') else url_for('modules.module', mod='insurance'),
                        hay=f"{c.claim_no} {c.status}"))
    return out


def _has_reg(k):
    try:
        from .crud import REG
        return k in REG
    except Exception:
        return False


def _navigation(term):
    """Match module names (English + Somali) so 'settings', 'reports', 'audit',
    'accounting', 'hr' etc. jump straight to the screen. Reuses the launcher
    catalog and is gated by the same per-module permission."""
    try:
        from ..blueprints.dash import APP_CATALOG
    except Exception:
        return []
    out = []
    seen = set()
    for cat in APP_CATALOG:
        items = cat[3] if len(cat) > 3 else []
        for it in items:
            mod = it[0]
            en = it[1] if len(it) > 1 else mod
            so = it[2] if len(it) > 2 else ''
            if mod in seen:
                continue
            if not can(mod):
                continue
            hay = f"{mod} {en} {so}".lower()
            if term in hay or difflib.SequenceMatcher(None, en.lower(), term).ratio() >= 0.7:
                seen.add(mod)
                out.append(dict(title=en, desc=so or 'Open module', module='Navigate',
                                status='', updated='', url=url_for('modules.module', mod=mod),
                                hay=hay))
    return out


# category label, icon, permission, fn
PROVIDERS = [
    ('Patients', '👤', 'patients', _patients),
    ('Appointments', '📅', 'queue', _appointments),
    ('Laboratory', '🧪', 'lab', _lab),
    ('Radiology', '🩻', 'radiology', _rad),
    ('Pharmacy', '💊', 'pharmacy', _pharmacy),
    ('Billing', '💰', 'invoices', _invoices),
    ('Insurance', '🛡️', 'insurance', _insurance),
    ('Suppliers', '🚚', 'suppliers', _suppliers),
    ('Assets', '🏷️', 'assets', _assets),
    ('Vehicles', '🚑', 'vehicles', _vehicles),
    ('Staff', '👨‍⚕️', 'doctors', _staff),
    ('Navigate', '🧭', None, _navigation),
]


def run_search(query, per_cat=PER_CAT):
    """Return (groups, took_ms). Groups: [{cat,icon,hits:[...]}] permission-filtered."""
    t0 = time.time()
    q = _norm(query)
    tokens = [t for t in q.split() if t]
    groups = []
    if not q:
        return groups, 0
    for label, icon, perm, fn in PROVIDERS:
        if perm and not can(perm):
            continue
        try:
            hits = fn(q)
        except Exception:
            continue
        scored = []
        for hdct in hits:
            sc = _score(hdct.get('hay', ''), q, tokens) or _score(hdct['title'], q, tokens)
            if sc <= 0:
                continue
            scored.append((sc, hdct))
        if not scored:
            continue
        scored.sort(key=lambda x: (-x[0], -_recency(x[1].get('updated'))))
        top = []
        for sc, hdct in scored[:per_cat]:
            top.append(dict(icon=icon, cat=label,
                            title=_hl(hdct['title'], tokens), desc=_hl(hdct['desc'], tokens),
                            module=hdct.get('module', label), status=hdct.get('status', ''),
                            updated=hdct.get('updated', ''), url=hdct['url']))
        groups.append(dict(cat=label, icon=icon, hits=top, total=len(scored)))
    # order: categories with best/most hits first, Navigate last
    groups.sort(key=lambda g: (g['cat'] == 'Navigate', -len(g['hits'])))
    return groups, int((time.time() - t0) * 1000)


def _recency(s):
    try:
        return dt.datetime.fromisoformat(str(s)[:16].replace(' ', 'T')).timestamp()
    except Exception:
        return 0


# --------------------------------------------------------------- palette UI
def palette_html():
    """The Ctrl/Cmd-K command palette markup + styles + script (dark/light via
    the app's CSS variables; mobile responsive). Injected into every page."""
    api = url_for('search.api_search')
    ctx = url_for('search.api_context')
    pin = url_for('search.api_pin')
    return """
<div id="gsp" class="gsp" hidden aria-hidden="true">
  <div class="gsp-back" onclick="GS.close()"></div>
  <div class="gsp-box" role="dialog" aria-label="Global search">
    <div class="gsp-in">
      <span class="gsp-ic">🔍</span>
      <input id="gsp-q" type="text" autocomplete="off" spellcheck="false"
             placeholder="Search patients, invoices, lab, imaging, staff…  (Esc to close)">
      <span class="gsp-kbd">Ctrl K</span>
    </div>
    <div id="gsp-res" class="gsp-res"></div>
    <div class="gsp-foot"><span>↑↓ navigate · ↵ open · Esc close</span><span id="gsp-took"></span></div>
  </div>
</div>
<style>
.gsp{position:fixed;inset:0;z-index:9999;display:flex;align-items:flex-start;justify-content:center}
.gsp[hidden]{display:none}
.gsp-back{position:absolute;inset:0;background:rgba(15,23,42,.45);backdrop-filter:blur(2px)}
.gsp-box{position:relative;margin-top:9vh;width:min(680px,94vw);background:var(--surface,#fff);color:var(--ink,#0f172a);
  border:1px solid var(--line,#e5e7eb);border-radius:14px;box-shadow:0 24px 64px rgba(0,0,0,.28);overflow:hidden}
.gsp-in{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--line,#e5e7eb)}
.gsp-ic{font-size:18px;opacity:.7}
#gsp-q{flex:1;border:0;outline:0;background:transparent;color:inherit;font-size:17px}
.gsp-kbd{font-size:11px;color:var(--muted,#64748b);border:1px solid var(--line,#e5e7eb);border-radius:6px;padding:2px 6px}
.gsp-res{max-height:56vh;overflow:auto}
.gsp-cat{font-size:11px;letter-spacing:.5px;text-transform:uppercase;color:var(--muted,#64748b);padding:10px 16px 4px}
.gsp-row{display:flex;align-items:center;gap:12px;padding:9px 16px;cursor:pointer;text-decoration:none;color:inherit}
.gsp-row.sel,.gsp-row:hover{background:var(--canvas,#f1f5f9)}
.gsp-row .ic{font-size:19px;width:24px;text-align:center;flex:none}
.gsp-row .tx{flex:1;min-width:0}
.gsp-row .tt{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gsp-row .ds{font-size:12px;color:var(--muted,#64748b);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gsp-row .mt{font-size:11px;color:var(--muted,#64748b);text-align:right;flex:none}
.gsp-row .pill{font-size:10px;padding:1px 6px;border-radius:20px;background:var(--canvas,#eef2f7);border:1px solid var(--line,#e5e7eb)}
.gsp-row mark{background:var(--amber,#fde68a);color:inherit;border-radius:2px;padding:0 1px}
.gsp-pin{margin-left:8px;opacity:.4;font-size:13px}
.gsp-pin:hover{opacity:1}
.gsp-foot{display:flex;justify-content:space-between;font-size:11px;color:var(--muted,#64748b);padding:8px 16px;border-top:1px solid var(--line,#e5e7eb)}
.gsp-empty{padding:26px 16px;text-align:center;color:var(--muted,#64748b);font-size:13px}
@media(max-width:640px){.gsp-box{margin-top:0;width:100vw;height:100vh;border-radius:0}.gsp-res{max-height:calc(100vh - 120px)}}
</style>
<script>
(function(){
  var API=%r, CTX=%r, PIN=%r;
  var el=function(id){return document.getElementById(id)};
  var box, q, res, took, items=[], sel=-1, timer=null, lastq='';
  window.GS={
    open:function(seed){
      box=el('gsp'); q=el('gsp-q'); res=el('gsp-res'); took=el('gsp-took');
      box.hidden=false; box.setAttribute('aria-hidden','false');
      if(seed){q.value=seed}
      q.focus(); q.select();
      if(q.value.trim()){run()}else{context()}
    },
    close:function(){ if(box){box.hidden=true;box.setAttribute('aria-hidden','true')} sel=-1; },
    pin:function(ev,url,title,icon,module){ ev.preventDefault();ev.stopPropagation();
      fetch(PIN,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({url:url,title:title,icon:icon,module:module})}).then(function(){ context&&0; });
      ev.target.textContent='📌'; }
  };
  function esc(s){return s==null?'':s}
  function render(groups, took_ms, header){
    items=[]; sel=-1; var html='';
    if(header){html+=header}
    if(!groups||!groups.length){ if(!header){html+="<div class='gsp-empty'>No matches. Try a name, MRN, phone, invoice # or barcode.</div>"} }
    groups=groups||[];
    for(var g=0;g<groups.length;g++){
      html+="<div class='gsp-cat'>"+esc(groups[g].icon)+" "+esc(groups[g].cat)+"</div>";
      var hs=groups[g].hits||[];
      for(var i=0;i<hs.length;i++){
        var it=hs[i]; var idx=items.length; items.push(it.url);
        var st=it.status?("<span class='pill'>"+esc(it.status)+"</span> "):"";
        html+="<a class='gsp-row' data-i='"+idx+"' href='"+esc(it.url)+"'>"+
              "<span class='ic'>"+esc(it.icon)+"</span>"+
              "<span class='tx'><div class='tt'>"+esc(it.title)+"</div>"+
              "<div class='ds'>"+esc(it.desc)+"</div></span>"+
              "<span class='mt'>"+st+esc(it.module)+(it.updated?("<br>"+esc(it.updated)):"")+"</span>"+
              "<span class='gsp-pin' title='Pin' onclick='GS.pin(event,\""+esc(it.url)+"\",\""+jsstr(it.rawtitle||it.title)+"\",\""+esc(it.icon)+"\",\""+esc(it.module)+"\")'>📌</span>"+
              "</a>";
      }
    }
    if(took_ms!=null){took.textContent=took_ms+' ms'}
    res.innerHTML=html;
    Array.prototype.forEach.call(res.querySelectorAll('.gsp-row'),function(r){
      r.addEventListener('mouseenter',function(){setSel(+r.dataset.i)});
    });
    if(items.length){setSel(0)}
  }
  function jsstr(s){return String(s).replace(/[<>"']/g,'')}
  function setSel(i){ sel=i;
    Array.prototype.forEach.call(res.querySelectorAll('.gsp-row'),function(r){
      r.classList.toggle('sel', +r.dataset.i===sel); });
    var cur=res.querySelector('.gsp-row.sel'); if(cur){cur.scrollIntoView({block:'nearest'})}
  }
  function go(){ if(sel>=0&&items[sel]){location.assign(items[sel])} }
  function context(){
    fetch(CTX).then(function(r){return r.json()}).then(function(d){
      var html=''; 
      function sec(title,arr,pinnable){ if(!arr||!arr.length)return;
        html+="<div class='gsp-cat'>"+title+"</div>";
        for(var i=0;i<arr.length;i++){var a=arr[i];
          if(a.url){html+="<a class='gsp-row' href='"+esc(a.url)+"'><span class='ic'>"+(a.icon||'📌')+"</span><span class='tx'><div class='tt'>"+esc(a.title)+"</div><div class='ds'>"+esc(a.module||'')+"</div></span></a>";}
          else{html+="<a class='gsp-row' href='#' onclick='GS.open(\""+jsstr(a.q)+"\");return false'><span class='ic'>🕘</span><span class='tx'><div class='tt'>"+esc(a.q)+"</div></span></a>";}
        }
      }
      sec('📌 Pinned', d.pinned, true); sec('🕘 Recent', d.recent); sec('⭐ Frequent', d.frequent);
      if(!html){html="<div class='gsp-empty'>Type to search across every module.<br>Tip: MRN, phone, invoice #, or scan a barcode.</div>"}
      render(null,null,html);
    }).catch(function(){res.innerHTML="<div class='gsp-empty'>Type to search…</div>"});
  }
  function run(){
    var v=q.value.trim(); lastq=v;
    if(!v){context();return}
    fetch(API+'?q='+encodeURIComponent(v)).then(function(r){return r.json()}).then(function(d){
      if(q.value.trim()!==lastq)return;   // stale
      render(d.groups, d.took_ms);
    }).catch(function(){res.innerHTML="<div class='gsp-empty'>Search error</div>"});
  }
  document.addEventListener('keydown',function(e){
    var k=(e.key||'').toLowerCase();
    if((e.ctrlKey||e.metaKey)&&k==='k'){e.preventDefault();GS.open();return}
    if(box&&!box.hidden){
      if(k==='escape'){e.preventDefault();GS.close()}
      else if(k==='arrowdown'){e.preventDefault();setSel(Math.min(sel+1,items.length-1))}
      else if(k==='arrowup'){e.preventDefault();setSel(Math.max(sel-1,0))}
      else if(k==='enter'){e.preventDefault();go()}
    }
  });
  document.addEventListener('input',function(e){
    if(e.target && e.target.id==='gsp-q'){clearTimeout(timer);timer=setTimeout(run,140)}
  });
})();
</script>
""" % (api, ctx, pin)
