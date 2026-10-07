"""Public doctor referral form and internal referral management."""
from flask import (Blueprint, request, redirect, url_for, flash, abort, jsonify)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.security import (cur_user, can, login_required, log)
from ..core.helpers import money, today
from ..core.ui import page, public_shell, plink, pnamelink

bp = Blueprint('ref', __name__)


def _test_picker(svcs):
    """Odoo-style 'Add a line' picker: a category-grouped dropdown + an Add
    button that appends each chosen test as a removable row. Submits the same
    `tests` values (service names) as the old checkbox grid, so the POST
    handler is unchanged."""
    if not svcs:
        return "<span style='color:var(--muted);font-size:13px'>No services configured yet.</span>"
    groups = {}
    for s in svcs:
        groups.setdefault(s.department or 'Other', []).append(s)
    optgroups = ''
    for dep, items in groups.items():
        opts = ''.join(f"<option value=\"{h(s.name)}\">{h(s.name)}</option>" for s in items)
        optgroups += f"<optgroup label=\"{h(dep)}\">{opts}</optgroup>"
    html = (
        "<div id='tp-lines'></div>"
        "<div style='display:flex;gap:8px;align-items:center;margin-top:6px'>"
        "<select id='tp-pick' style='flex:1;border:1px solid var(--line);border-radius:8px;padding:9px;background:var(--surface)'>"
        "<option value=''>— Choose category &amp; test… —</option>" + optgroups +
        "</select>"
        "<button type='button' class='btn primary' onclick='tpAdd()'>➕ Add a line</button>"
        "</div>"
        "<div style='color:var(--muted);font-size:12px;margin-top:5px'>Ku dar adeeg kasta oo dhakhtarku rabo — add one line per test.</div>")
    js = """<script>
    function tpAdd(){
      var sel=document.getElementById('tp-pick'), v=sel.value; if(!v) return;
      var lines=document.getElementById('tp-lines');
      var dup=[].slice.call(lines.querySelectorAll('input[name=tests]')).some(function(i){return i.value===v});
      if(dup){ sel.value=''; return; }
      var dep=(sel.options[sel.selectedIndex].parentNode.label)||'';
      var row=document.createElement('div');
      row.style.cssText='display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;margin-bottom:6px;background:var(--surface)';
      var span=document.createElement('span'); span.style.flex='1';
      var b=document.createElement('b'); b.textContent=v; span.appendChild(b);
      if(dep){ var sm=document.createElement('small'); sm.style.color='var(--muted)'; sm.textContent=' · '+dep; span.appendChild(sm); }
      var inp=document.createElement('input'); inp.type='hidden'; inp.name='tests'; inp.value=v;
      var rm=document.createElement('button'); rm.type='button'; rm.className='btn sm'; rm.textContent='✕'; rm.title='Remove';
      rm.onclick=function(){ row.remove(); };
      row.appendChild(span); row.appendChild(inp); row.appendChild(rm);
      lines.appendChild(row); sel.value='';
    }
    document.addEventListener('DOMContentLoaded',function(){
      var p=document.getElementById('tp-pick');
      if(p) p.addEventListener('change',function(){ if(this.value) tpAdd(); });
    });
    </script>"""
    return html + js


def _referral_services(r):
    """Resolve a Doctor Request's requested items to concrete services + prices.
    Works whether the tests were captured as Lab/Rad orders (doctor portal) or as
    plain test names (staff form). The request detail, the list and invoice creation
    all use this so they always agree on the services and the price to quote."""
    from ..models import LabOrder, RadOrder, Service
    out, seen = [], set()
    for kind, model in (('Lab', LabOrder), ('Rad', RadOrder)):
        for o in model.query.filter_by(ref_id=r.id).all():
            svc = o.service if o.service_id else None
            nm = (svc.name if svc else None) or '—'
            out.append({'svc': svc, 'name': nm, 'price': (svc.price if svc else 0) or 0,
                        'order': o, 'kind': kind, 'status': o.status})
            if svc:
                seen.add(svc.id)
            seen.add(nm.strip().lower())
    names = [t.strip() for t in (r.tests or '').replace(';', ',').split(',') if t.strip()]
    catalog = Service.query.filter_by(active=True).all() if names else []
    for nm in names:
        key = nm.strip().lower()
        if key in seen:
            continue
        match = None
        for s in catalog:
            sn = (s.name or '').strip().lower()
            if sn == key or key in sn or sn in key:
                match = s
                break
        if match and match.id in seen:
            continue
        if match:
            is_rad = bool(match.modality) or (match.department or '').lower().startswith('rad') \
                     or (match.workflow or '').lower() == 'radiology'
            kind = 'Rad' if is_rad else ('Svc' if (match.department or '').lower() in ('consultation', 'other') else 'Lab')
        else:
            kind = 'Svc'
        out.append({'svc': match, 'name': (match.name if match else nm),
                    'price': (match.price if match else 0) or 0,
                    'order': None, 'kind': kind, 'status': None})
        seen.add(key)
        if match:
            seen.add(match.id)
    return out

def _render_referral_form_html(errors=None, values=None, is_staff=False):
    from ..core.security import csrf_token
    errors = errors or {}
    values = values or {}

    docs = Doctor.query.filter_by(active=True).order_by(Doctor.name).all()
    cur_doc_id = str(values.get('doctor_id') or '')
    dopts = f"<option value='' {'selected' if not cur_doc_id else ''}>— Other (type name below) —</option>" + "".join(
        f"<option value='{d.id}' {'selected' if str(d.id)==cur_doc_id else ''}>{h(d.name)}{(' · '+h(d.specialty)) if d.specialty else ''}</option>" for d in docs)

    svcs = Service.query.filter_by(active=True).order_by(Service.department, Service.name).all()

    val_tests = values.get('tests') or []
    if isinstance(val_tests, str):
        val_tests = [val_tests]

    lines_html = ""
    for t_item in val_tests:
        t_clean = h(str(t_item).strip())
        if t_clean:
            lines_html += (
                f"<div style='display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;margin-bottom:6px;background:var(--surface)'>"
                f"<span style='flex:1'><b>{t_clean}</b></span>"
                f"<input type='hidden' name='tests' value=\"{t_clean}\">"
                f"<button type='button' class='btn sm' onclick='this.parentNode.remove()' title='Remove'>✕</button>"
                f"</div>"
            )

    if not svcs:
        picker_html = "<span style='color:var(--muted);font-size:13px'>No services configured yet.</span>"
    else:
        groups = {}
        for s in svcs:
            groups.setdefault(s.department or 'Other', []).append(s)
        optgroups = ''
        for dep, items in groups.items():
            opts = ''.join(f"<option value=\"{h(s.name)}\">{h(s.name)}</option>" for s in items)
            optgroups += f"<optgroup label=\"{h(dep)}\">{opts}</optgroup>"
        picker_html = (
            f"<div id='tp-lines'>{lines_html}</div>"
            "<div style='display:flex;gap:8px;align-items:center;margin-top:6px'>"
            "<select id='tp-pick' style='flex:1;border:1px solid var(--line);border-radius:8px;padding:9px;background:var(--surface)'>"
            "<option value=''>— Choose category &amp; test… —</option>" + optgroups +
            "</select>"
            "<button type='button' class='btn primary' onclick='tpAdd()'>➕ Add a line</button>"
            "</div>"
            "<div style='color:var(--muted);font-size:12px;margin-top:5px'>Ku dar adeeg kasta oo dhakhtarku rabo — add one line per test.</div>"
        )
        picker_js = """<script>
        function tpAdd(){
          var sel=document.getElementById('tp-pick'), v=sel.value; if(!v) return;
          var lines=document.getElementById('tp-lines');
          var dup=[].slice.call(lines.querySelectorAll('input[name=tests]')).some(function(i){return i.value===v});
          if(dup){ sel.value=''; return; }
          var dep=(sel.options[sel.selectedIndex].parentNode.label)||'';
          var row=document.createElement('div');
          row.style.cssText='display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;margin-bottom:6px;background:var(--surface)';
          var span=document.createElement('span'); span.style.flex='1';
          var b=document.createElement('b'); b.textContent=v; span.appendChild(b);
          if(dep){ var sm=document.createElement('small'); sm.style.color='var(--muted)'; sm.textContent=' · '+dep; span.appendChild(sm); }
          var inp=document.createElement('input'); inp.type='hidden'; inp.name='tests'; inp.value=v;
          var rm=document.createElement('button'); rm.type='button'; rm.className='btn sm'; rm.textContent='✕'; rm.title='Remove';
          rm.onclick=function(){ row.remove(); };
          row.appendChild(span); row.appendChild(inp); row.appendChild(rm);
          lines.appendChild(row); sel.value='';
        }
        document.addEventListener('DOMContentLoaded',function(){
          var p=document.getElementById('tp-pick');
          if(p) p.addEventListener('change',function(){ if(this.value) tpAdd(); });
        });
        </script>"""
        picker_html += picker_js

    val_doc_name = h(values.get('doctor_name') or '')
    val_hospital = h(values.get('hospital') or '')
    val_pid = h(str(values.get('patient_id') or ''))
    val_pname = h(values.get('patient_name') or '')
    val_phone = h(values.get('patient_phone') or '')
    val_age = h(str(values.get('patient_age') if values.get('patient_age') is not None else ''))
    val_gender = values.get('patient_gender') or ''
    val_other_tests = h(values.get('other_tests') or '')
    val_notes = h(values.get('notes') or '')

    summary_html = ""
    if errors:
        err_items = "".join(f"<li>{h(msg)}</li>" for msg in errors.values())
        summary_html = (
            f"<div class='panel' id='error-summary' tabIndex='-1' style='border-left:4px solid var(--red);background:var(--red-soft);margin-bottom:16px'>"
            f"<div class='pad'>"
            f"<div style='font-weight:700;color:var(--red);font-size:14px;margin-bottom:6px'>⚠️ Please fix the following errors before submitting:</div>"
            f"<ul style='margin-left:20px;color:var(--ink);font-size:13px'>{err_items}</ul>"
            f"</div></div>"
        )

    def err_div(key):
        if key in errors:
            return f"<div class='field-error-msg' style='color:var(--red);font-size:12px;font-weight:600;margin-top:4px'>⚠️ {h(errors[key])}</div>"
        return ""

    def field_sty(key):
        return "border:1px solid var(--red);" if key in errors else ""

    def field_cls(key):
        return "is-invalid" if key in errors else ""

    _gopts = "".join(f"<option {'selected' if val_gender==g else ''}>{g}</option>" for g in ('Male', 'Female'))

    form = f"""
    {summary_html}
    <div class='panel'><div class='pad'>
      {"<p style='color:var(--muted);font-size:13px;margin-bottom:6px'>Buuxi foomkan si aad bukaan ugu soo dirto xarunta baaritaanka. (Login uma baahna.)</p>" if not is_staff else ""}
      <form method='post' action='/refer' onsubmit='return validateDoctorRequestForm(this)'>
      <input type='hidden' name='_csrf' value='{csrf_token()}'>
      <div class='secttl'>Referring Doctor · Dhakhtarka gudbiya</div>
      <div class='fld'>
        <label>Select registered doctor <span style='color:var(--red)'>*</span></label>
        <select name='doctor_id' class='{field_cls("doctor_id")}' style='{field_sty("doctor_id")}'>{dopts}</select>
        {err_div("doctor_id")}
      </div>
      <div class='g2'>
        <div class='fld'>
          <label>Doctor name <span style='color:var(--muted);font-weight:400'>(required if not listed)</span> <span style='color:var(--red)'>*</span></label>
          <input name='doctor_name' value="{val_doc_name}" class='{field_cls("doctor_name")}' style='{field_sty("doctor_name")}'>
          {err_div("doctor_name")}
        </div>
        <div class='fld'>
          <label>Hospital / Clinic <span style='color:var(--muted);font-weight:400'>(required for external doctor)</span> <span style='color:var(--red)'>*</span></label>
          <input name='hospital' value="{val_hospital}" class='{field_cls("hospital")}' style='{field_sty("hospital")}'>
          {err_div("hospital")}
        </div>
      </div>
      <div class='secttl'>Patient · Bukaanka</div>
      <input type='hidden' name='patient_id' id='refPid' value="{val_pid}">
    """

    if is_staff:
        form += f"""
        <div class='fld' style='position:relative'>
          <label>🔎 Find returning patient (ID / name / phone) · Raadi bukaan hore</label>
          <input id='refPatSearch' autocomplete='off' placeholder='Type MRN, name or phone to reuse an existing patient…'>
          <div id='refPatResults' style='display:none;position:absolute;z-index:20;left:0;right:0;background:var(--surface);border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,.12);max-height:240px;overflow:auto'></div>
          <div id='refPatChosen' style='{"display:block" if val_pid else "display:none"};margin-top:6px;font-size:12.5px;color:var(--green)'>
            {"✓ Using existing patient — no duplicate will be created." if val_pid else ""}
          </div>
        </div>
        """

    form += f"""
      <div class='g2'>
        <div class='fld'>
          <label>Patient name <span style='color:var(--red)'>*</span></label>
          <input name='patient_name' id='refName' value="{val_pname}" class='{field_cls("patient_name")}' style='{field_sty("patient_name")}' required aria-required='true'>
          {err_div("patient_name")}
        </div>
        <div class='fld'>
          <label>Phone <span style='color:var(--red)'>*</span></label>
          <input name='patient_phone' id='refPhone' value="{val_phone}" class='{field_cls("patient_phone")}' style='{field_sty("patient_phone")}'>
          {err_div("patient_phone")}
        </div>
        <div class='fld'>
          <label>Age <span style='color:var(--red)'>*</span></label>
          <input name='patient_age' id='refAge' value="{val_age}" class='{field_cls("patient_age")}' style='{field_sty("patient_age")}'>
          {err_div("patient_age")}
        </div>
        <div class='fld'>
          <label>Gender <span style='color:var(--red)'>*</span></label>
          <select name='patient_gender' id='refGender' class='{field_cls("patient_gender")}' style='{field_sty("patient_gender")}'>
            <option value=''>—</option>
            {_gopts}
          </select>
          {err_div("patient_gender")}
        </div>
      </div>
      <div class='secttl'>Requested Tests / Scans · Baaritaannada <span style='color:var(--red)'>*</span></div>
      {picker_html}
      {err_div("tests")}
      <div class='fld' style='margin-top:8px'>
        <label>Other tests <span style='color:var(--muted);font-weight:400'>(required if no configured services selected)</span></label>
        <input name='other_tests' value="{val_other_tests}" placeholder='e.g. MRI Brain' class='{field_cls("other_tests")}' style='{field_sty("other_tests")}'>
        {err_div("other_tests")}
      </div>
      <div class='fld'>
        <label>Clinical notes <span style='color:var(--red)'>*</span></label>
        <textarea name='notes' rows='2' placeholder='Reason for referral, symptoms...' class='{field_cls("notes")}' style='{field_sty("notes")}' required aria-required='true'>{val_notes}</textarea>
        {err_div("notes")}
      </div>
      <div style='text-align:right;margin-top:14px'>
        <button type='submit' class='btn primary' style='padding:12px 26px;font-size:15px'>
          {"Create Doctor Request" if is_staff else "Send Referral"}
        </button>
      </div>
      </form></div></div>
    """

    js_validation = f"""
    <script>
    function validateDoctorRequestForm(form) {{
      var oldSum = document.getElementById('client-error-summary');
      if (oldSum) oldSum.remove();

      var oldMsgs = form.querySelectorAll('.client-field-error');
      oldMsgs.forEach(function(el) {{ el.remove(); }});

      var inputs = form.querySelectorAll('.is-invalid');
      inputs.forEach(function(el) {{ el.style.borderColor = ''; el.classList.remove('is-invalid'); }});

      var errs = [];
      var firstErrEl = null;

      function markErr(el, msg) {{
        errs.push(msg);
        if (el) {{
          el.classList.add('is-invalid');
          el.style.borderColor = 'var(--red)';
          el.setAttribute('aria-invalid', 'true');
          var d = document.createElement('div');
          d.className = 'client-field-error';
          d.style.cssText = 'color:var(--red);font-size:12px;font-weight:600;margin-top:4px';
          d.textContent = '⚠️ ' + msg;
          if (el.parentNode) el.parentNode.appendChild(d);
          if (!firstErrEl) firstErrEl = el;
        }}
      }}

      // Doctor validation
      var docSel = form.querySelector('[name=doctor_id]');
      var docName = form.querySelector('[name=doctor_name]');
      var hosp = form.querySelector('[name=hospital]');
      if (!docSel || !docSel.value) {{
        if (!docName || !docName.value.trim()) {{
          markErr(docName, "Doctor Name is required when 'Other' is selected.");
        }}
        if (!hosp || !hosp.value.trim()) {{
          markErr(hosp, "Hospital / Clinic is required for external doctors.");
        }}
      }}

      // Patient validation
      var pid = form.querySelector('[name=patient_id]');
      var pName = form.querySelector('[name=patient_name]');
      var pPhone = form.querySelector('[name=patient_phone]');
      var pAge = form.querySelector('[name=patient_age]');
      var pGender = form.querySelector('[name=patient_gender]');

      if (!pid || !pid.value) {{
        if (!pName || !pName.value.trim()) {{
          markErr(pName, "Patient Name cannot be blank or contain only spaces.");
        }}
        if (!pPhone || !pPhone.value.trim()) {{
          markErr(pPhone, "Phone number is required for new patients.");
        }}
        var ageVal = pAge ? pAge.value.trim() : '';
        var numAge = Number(ageVal);
        if (!ageVal || isNaN(ageVal) || !Number.isInteger(numAge) || numAge < 0 || numAge > 150) {{
          markErr(pAge, "Age must be a valid non-negative integer (0 to 150).");
        }}
        if (!pGender || !pGender.value || pGender.value === '—' || pGender.value === '') {{
          markErr(pGender, "Please select a valid Gender (Male or Female).");
        }}
      }}

      // Tests validation
      var testInputs = form.querySelectorAll('input[name=tests]');
      var otherTests = form.querySelector('[name=other_tests]');
      var hasTests = testInputs.length > 0 || (otherTests && otherTests.value.trim().length > 0);
      if (!hasTests) {{
        markErr(otherTests || form.querySelector('#tp-pick'), "At least one requested test/scan or 'Other tests' description is required.");
      }}

      // Clinical notes validation
      var notes = form.querySelector('[name=notes]');
      if (!notes || !notes.value.trim()) {{
        markErr(notes, "Clinical Notes are required and cannot be blank.");
      }}

      if (errs.length > 0) {{
        var sumDiv = document.createElement('div');
        sumDiv.id = 'client-error-summary';
        sumDiv.className = 'panel';
        sumDiv.style.cssText = 'border-left:4px solid var(--red);background:var(--red-soft);margin-bottom:16px';
        var ulHtml = errs.map(function(m) {{ return '<li>' + m + '</li>'; }}).join('');
        sumDiv.innerHTML = "<div class='pad'>"
          + "<div style='font-weight:700;color:var(--red);font-size:14px;margin-bottom:6px'>⚠️ Please fix the following errors before submitting:</div>"
          + "<ul style='margin-left:20px;color:var(--ink);font-size:13px'>" + ulHtml + "</ul></div>";

        form.parentNode.insertBefore(sumDiv, form);

        if (firstErrEl) {{
          firstErrEl.focus();
        }}
        return false;
      }}

      var btn = form.querySelector('button[type=submit], button.primary');
      if (btn) {{
        btn.disabled = true;
        btn.textContent = 'Submitting...';
      }}
      return true;
    }}
    </script>
    """

    if is_staff:
        search_js = f"""
        <script>
        (function(){{
          var box=document.getElementById('refPatSearch'), res=document.getElementById('refPatResults'),
              chosen=document.getElementById('refPatChosen'), t=null;
          function clearPid(){{document.getElementById('refPid').value=''; chosen.style.display='none';}}
          if(box){{
            box.addEventListener('input', function(){{
              clearPid();
              var q=this.value.trim();
              if(q.length<2){{res.style.display='none'; return;}}
              clearTimeout(t);
              t=setTimeout(function(){{
                fetch('{url_for('ref.referral_patient_search')}?q='+encodeURIComponent(q))
                .then(function(r){{return r.json();}}).then(function(list){{
                  if(!list.length){{res.innerHTML="<div style='padding:8px 12px;color:#888;font-size:12.5px'>No match — a new patient will be created.</div>"; res.style.display='block'; return;}}
                  res.innerHTML=list.map(function(p){{
                    return "<div class='refpat' data-id='"+p.id+"' data-name='"+encodeURIComponent(p.name)+"' data-phone='"+encodeURIComponent(p.phone)+"' data-age='"+p.age+"' data-gender='"+p.gender+"' style='padding:8px 12px;cursor:pointer;border-bottom:1px solid #eee'>"
                      +"<b>"+p.name+"</b> <span style='color:#888;font-size:12px'>· "+p.mrn+" · "+(p.phone||'—')+"</span></div>";
                  }}).join('');
                  res.style.display='block';
                  Array.prototype.forEach.call(res.querySelectorAll('.refpat'), function(el){{
                    el.addEventListener('mousedown', function(){{
                      document.getElementById('refPid').value=el.getAttribute('data-id');
                      document.getElementById('refName').value=decodeURIComponent(el.getAttribute('data-name'));
                      document.getElementById('refPhone').value=decodeURIComponent(el.getAttribute('data-phone'));
                      var ag=el.getAttribute('data-age'); document.getElementById('refAge').value=(ag&&ag!=='None'?ag:'');
                      var g=el.getAttribute('data-gender'); if(g){{document.getElementById('refGender').value=g;}}
                      chosen.textContent='✓ Using existing patient — no duplicate will be created.'; chosen.style.display='block';
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
        """
        form += search_js

    if errors:
        focus_js = "<script>document.addEventListener('DOMContentLoaded', function(){ var el = document.querySelector('.is-invalid'); if(el) el.focus(); });</script>"
        form += focus_js

    return form + js_validation


@bp.route('/refer', methods=['GET','POST'])
def refer():
    if request.method == 'POST':
        if cur_user() and not (can('referrals') or can('reqboard')):
            abort(403)

        errors = {}

        did_raw = (request.form.get('doctor_id') or '').strip()
        did = int(did_raw) if did_raw.isdigit() else None
        doc_name = (request.form.get('doctor_name') or '').strip()
        hospital = (request.form.get('hospital') or '').strip()

        pid_raw = (request.form.get('patient_id') or '').strip()
        linked_pid = int(pid_raw) if pid_raw.isdigit() else None
        pat_name = (request.form.get('patient_name') or '').strip()
        pat_phone = (request.form.get('patient_phone') or '').strip()
        pat_age_raw = (request.form.get('patient_age') or '').strip()
        pat_gender = (request.form.get('patient_gender') or '').strip()

        chosen = [t.strip() for t in request.form.getlist('tests') if t.strip()]
        other = (request.form.get('other_tests') or '').strip()
        notes = (request.form.get('notes') or '').strip()

        # Rule A: Referring Doctor
        if did:
            doc_obj = Doctor.query.get(did)
            if not doc_obj or not doc_obj.active:
                errors['doctor_id'] = "Selected registered doctor is invalid or inactive."
            else:
                if not doc_name:
                    doc_name = doc_obj.name
        else:
            if not doc_name:
                errors['doctor_name'] = "Doctor Name is required when 'Other' is selected."
            if not hospital:
                errors['hospital'] = "Hospital / Clinic is required for external doctors."

        # Rule B: Patient
        if linked_pid:
            existing_pat = Patient.query.get(linked_pid)
            if not existing_pat:
                errors['patient_id'] = "Selected existing patient record was not found."
            else:
                pat_name = existing_pat.name or pat_name
                pat_phone = existing_pat.phone or pat_phone
                pat_age_raw = str(existing_pat.age) if existing_pat.age is not None else pat_age_raw
                pat_gender = existing_pat.gender or pat_gender
        else:
            if pat_phone:
                ex_pat = Patient.query.filter_by(phone=pat_phone).first()
                if ex_pat:
                    linked_pid = ex_pat.id
                    pat_name = ex_pat.name or pat_name
                    pat_phone = ex_pat.phone or pat_phone
                    pat_age_raw = str(ex_pat.age) if ex_pat.age is not None else pat_age_raw
                    pat_gender = ex_pat.gender or pat_gender

            if not linked_pid:
                if not pat_name:
                    errors['patient_name'] = "Patient Name cannot be blank or contain only spaces."
                if not pat_phone:
                    errors['patient_phone'] = "Phone number is required for new patients."

                if not pat_age_raw:
                    errors['patient_age'] = "Age is required."
                else:
                    try:
                        age_val = int(pat_age_raw)
                        if age_val < 0 or age_val > 150:
                            errors['patient_age'] = "Age must be a valid non-negative number (0 to 150)."
                    except ValueError:
                        errors['patient_age'] = "Age must be a valid number."

                if not pat_gender or pat_gender not in ('Male', 'Female'):
                    errors['patient_gender'] = "Please select a valid Gender (Male or Female)."

        # Rule C: Requested Test or Scan
        all_tests = list(chosen)
        if other:
            all_tests.append(other)

        if not all_tests:
            errors['tests'] = "At least one requested test/scan or 'Other tests' description is required."

        # Rule D: Clinical Notes
        if not notes:
            errors['notes'] = "Clinical Notes are required and cannot be blank."

        if errors:
            db.session.rollback()
            values = {
                'doctor_id': did_raw,
                'doctor_name': doc_name,
                'hospital': hospital,
                'patient_id': pid_raw,
                'patient_name': pat_name,
                'patient_phone': pat_phone,
                'patient_age': pat_age_raw,
                'patient_gender': pat_gender,
                'tests': chosen,
                'other_tests': other,
                'notes': notes,
            }
            is_staff_user = bool(cur_user())
            form_html = _render_referral_form_html(errors=errors, values=values, is_staff=is_staff_user)
            if is_staff_user:
                n_new = Referral.query.filter_by(status='New').count()
                head = (f"<div class='panel'><div class='pad' style='display:flex;align-items:center;gap:12px;flex-wrap:wrap'>"
                        f"<div><div style='font-weight:700;color:var(--petrol);font-family:Space Grotesk;font-size:16px'>New Doctor Request · Codsi cusub</div>"
                        f"<div style='color:var(--muted);font-size:12.5px'>Buuxi foomka si aad u abuurto codsi cusub oo dhakhtar.</div></div>"
                        f"<div class='sp' style='flex:1'></div>"
                        f"<a class='btn' href='{url_for('modules.module', mod='referrals')}'>← Back to Doctor Requests{f' ({n_new} new)' if n_new else ''}</a></div></div>")
                return page('Doctor Request', head + form_html, 'referrals'), 400
            else:
                return public_shell('Doctor Referral', form_html), 400

        r = Referral(
            patient_id=linked_pid,
            patient_name=pat_name,
            patient_phone=pat_phone,
            patient_age=pat_age_raw,
            patient_gender=pat_gender,
            doctor_id=did if did else None,
            doctor_name=doc_name,
            hospital=hospital,
            tests=', '.join([t for t in all_tests if t]),
            notes=notes,
            status='New'
        )
        db.session.add(r)
        db.session.commit()

        from ..core.notify import notify
        notify(f"New doctor referral: {r.patient_name} ({r.tests[:60]})",
               link='/m/referrals', role='reception')

        if cur_user():
            flash(f'Doctor Request created for {r.patient_name}')
            return redirect(url_for('modules.module', mod='reqboard'))

        return public_shell('Referral Sent',
            "<div class='panel'><div class='pad' style='text-align:center;padding:44px 20px'>"
            "<div style='font-size:46px'>✅</div>"
            "<h2 style='color:var(--green);font-family:Space Grotesk;margin:8px 0'>Referral sent successfully</h2>"
            "<p style='color:var(--muted);max-width:420px;margin:0 auto 16px'>Waan helnay gudbintaada. Xarunta baaritaanka ayaa la xiriiri doonta bukaanka.</p>"
            "<a class='btn primary' href='/refer'>Send another referral</a></div></div>")

    is_staff_user = bool(cur_user())
    form_html = _render_referral_form_html(is_staff=is_staff_user)
    return public_shell('Doctor Referral', form_html)

@bp.route('/referral/new')
@login_required
def referral_new_form():
    return referrals_view()


@bp.route('/referral/patient-search')
@login_required
def referral_patient_search():
    """Find existing patients by MRN, name, or phone so a returning patient's
    record is reused instead of creating a duplicate."""
    if not can('referrals'):
        abort(403)
    q = (request.args.get('q') or '').strip()
    out = []
    if len(q) >= 2:
        like = f'%{q}%'
        rows = (Patient.query
                .filter(db.or_(Patient.name.ilike(like), Patient.phone.ilike(like),
                               Patient.mrn.ilike(like)))
                .order_by(Patient.id.desc()).limit(12).all())
        for p in rows:
            out.append({'id': p.id, 'mrn': p.mrn or '', 'name': p.name or '',
                        'phone': p.phone or '', 'gender': p.gender or '',
                        'age': p.age if p.age is not None else ''})
    return jsonify(out)


def referrals_view():
    """Staff-facing NEW doctor request form (opened from the list's + button, or
    from a patient page with ?patient=<id> to pre-fill that patient's details)."""
    from flask import request as _rq
    _pre_name = _pre_phone = _pre_age = _pre_gender = ''
    _pid = _rq.args.get('patient')
    _pre_pid = ''
    if _pid and str(_pid).isdigit():
        _pp = Patient.query.get(int(_pid))
        if _pp:
            _pre_pid = str(_pp.id)
            _pre_name = _pp.name or ''
            _pre_phone = _pp.phone or ''
            _pre_age = str(_pp.age) if _pp.age is not None else ''
            _pre_gender = _pp.gender or ''

    values = {
        'patient_id': _pre_pid,
        'patient_name': _pre_name,
        'patient_phone': _pre_phone,
        'patient_age': _pre_age,
        'patient_gender': _pre_gender,
    }
    n_new = Referral.query.filter_by(status='New').count()
    head = (f"<div class='panel'><div class='pad' style='display:flex;align-items:center;gap:12px;flex-wrap:wrap'>"
            f"<div><div style='font-weight:700;color:var(--petrol);font-family:Space Grotesk;font-size:16px'>New Doctor Request · Codsi cusub</div>"
            f"<div style='color:var(--muted);font-size:12.5px'>Buuxi foomka si aad u abuurto codsi cusub oo dhakhtar.</div></div>"
            f"<div class='sp' style='flex:1'></div>"
            f"<a class='btn' href='{url_for('modules.module', mod='referrals')}'>← Back to Doctor Requests{f' ({n_new} new)' if n_new else ''}</a></div></div>")
    form_html = _render_referral_form_html(values=values, is_staff=True)
    return page('Doctor Request', head + form_html, 'referrals')


def referrals_list_view():
    from .modules import search_view, hl
    status_f = request.args.get('status', '')
    base = Referral.query
    base, _sq, _fbar = search_view('referrals', Referral, base,
                                   search_cols=['patient_name', 'doctor_name', 'tests',
                                                'status', 'hospital', 'patient_phone'],
                                   date_field='date')
    refs = base.order_by(Referral.id.desc()).all()
    SC = {'New':'amber','Accepted':'blue','Completed':'green','Rejected':'red'}
    def row(r):
        who = (r.doctor_ref.name if r.doctor_ref else r.doctor_name) or '—'
        hosp = f" · {h(r.hospital)}" if r.hospital else ''
        est = sum(d['price'] for d in _referral_services(r))
        inv = Invoice.query.filter(Invoice.referral_id == r.id, Invoice.status != 'Cancelled').first()
        acts = [f"<a class='btn gh sm' href='{url_for('ref.referral_detail', rid=r.id)}'>Open</a>"]
        if r.status == 'New':
            acts.append(f"<a class='btn gh sm' href='{url_for('ref.referral_accept', rid=r.id)}'>Accept</a>")
            acts.append(f"<a class='btn gh sm' href='{url_for('ref.referral_status', rid=r.id, st='Rejected')}' onclick=\"return confirm('Reject this referral?')\">Reject</a>")
        elif r.status == 'Accepted' and r.patient_id:
            acts.append(f"<a class='btn gh sm' href='/patient/{r.patient_id}'>Patient</a>")
            acts.append(f"<a class='btn gh sm' href='{url_for('ref.referral_status', rid=r.id, st='Completed')}'>Complete</a>")
        elif r.status not in ('New', 'Accepted'):
            acts.append(f"<a class='btn gh sm' href='{url_for('ref.referral_status', rid=r.id, st='New')}'>Reopen</a>")
        if can('invoices') and r.status != 'Rejected':
            if inv:
                acts.append(f"<a class='btn sm' href='{url_for('billing.invoice_view', iid=inv.id)}'>INV-{inv.id:04d}</a>")
            else:
                acts.append(f"<a class='btn primary sm' href='{url_for('ref.referral_invoice', rid=r.id)}'>+ Invoice</a>")
        return (f"<tr><td>{h(r.date)}</td>"
                f"<td><b>{hl(h(r.patient_name or '—'), _sq)}</b><br><small>{h(r.patient_phone or '')}{(' · '+h(r.patient_gender)) if r.patient_gender else ''}{(' · '+h(r.patient_age)+'y') if r.patient_age else ''}</small></td>"
                f"<td>{hl(h(who), _sq)}{hosp}</td>"
                f"<td style='max-width:230px;white-space:normal'><small>{hl(h(r.tests or '—'), _sq)}</small></td>"
                f"<td class='num'><b>{money(est)}</b></td>"
                f"<td><span class='pill {SC.get(r.status,'grey')}'>{h(r.status)}</span></td>"
                f"<td class='num' style='white-space:nowrap'>{''.join(acts)}</td></tr>")
    body = ''.join(row(r) for r in refs) or "<tr><td colspan='7'><div class='empty'><b>No referrals yet</b>Gujin '+ New Doctor Request' si aad u abuurto.</div></td></tr>"
    tabs = ''.join(f"<a class='{'on' if status_f==s else ''}' href='?status={s}'>{s or 'All'}</a>" for s in ['','New','Accepted','Completed','Rejected'])
    n_new = Referral.query.filter_by(status='New').count()
    newbtn = f"<a class='btn primary' href='{url_for('ref.referral_new_form')}'>+ New Doctor Request</a>"
    subnav = f"<div class='subnav' style='margin-bottom:14px'><span class='subnav-t'>Status</span>{tabs}</div>"
    panel = (f"<div class='panel'><div class='ph'><h2>Incoming Referrals</h2>"
             f"<span class='so'>{n_new} new · Gudbinta dhakhaatiirta</span><div class='sp'></div>{newbtn}</div>"
             f"{_fbar}"
             f"<div class='tw'><table><thead><tr><th>Date</th><th>Patient</th><th>Referred by</th><th>Tests</th><th class='num'>Est. Total</th><th>Status</th><th></th></tr></thead>"
             f"<tbody>{body}</tbody></table></div></div>")
    return page('Referrals', subnav + panel, 'referrals')

@bp.route('/referral/<int:rid>/accept')
@login_required
def referral_accept(rid):
    if not can('referrals'): abort(403)
    r = Referral.query.get_or_404(rid)
    if not r.patient_id:
        # Reuse an existing patient (returning patient) before creating a new record:
        # match by phone first, then by exact name — avoids duplicates.
        ex = None
        if (r.patient_phone or '').strip():
            ex = Patient.query.filter_by(phone=r.patient_phone.strip()).first()
        if not ex and (r.patient_name or '').strip():
            ex = Patient.query.filter(Patient.name.ilike(r.patient_name.strip())).first()
        if ex:
            r.patient_id = ex.id
        else:
            p = Patient(mrn='MRN' + str((Patient.query.count() or 0) + 1001),
                        name=r.patient_name or 'Referral Patient', phone=r.patient_phone, gender=r.patient_gender,
                        notes=f"Referred by {(r.doctor_ref.name if r.doctor_ref else r.doctor_name) or '—'}"
                              f"{(' ('+r.hospital+')') if r.hospital else ''}. Requested: {r.tests or '—'}")
            db.session.add(p); db.session.flush(); r.patient_id = p.id
    r.status = 'Accepted'; db.session.commit(); log(f"Accepted referral for {r.patient_name}")
    flash('Referral accepted — ' + ('linked to existing patient' if Patient.query.get(r.patient_id) else 'patient created'))
    return redirect(url_for('modules.module', mod='referrals'))

@bp.route('/referral/<int:rid>/status/<st>')
@login_required
def referral_status(rid, st):
    if not can('referrals'): abort(403)
    r = Referral.query.get_or_404(rid); r.status = st; db.session.commit(); log(f"Referral {rid} -> {st}")
    flash('Referral updated')
    return redirect(url_for('modules.module', mod='referrals'))



@bp.route('/referral/<int:rid>/thread', methods=['GET', 'POST'])
@login_required
def referral_thread(rid):
    if not can('referrals'): abort(403)
    from ..models import RefComment
    r = Referral.query.get_or_404(rid)
    if request.method == 'POST':
        txt = (request.form.get('text') or '').strip()[:500]
        if txt:
            db.session.add(RefComment(referral_id=rid, author=cur_user().name or cur_user().username,
                                      is_doctor=False, text=txt))
            db.session.commit(); log(f'Comment on REF-{rid:04d}')
        return redirect(url_for('ref.referral_thread', rid=rid))
    cmts = ''.join(
        f"<div style='margin:6px 0;padding:8px 12px;border-radius:10px;background:{'#FFF6EC' if c.is_doctor else 'var(--canvas)'}'>"
        f"<b style='font-size:12.5px;color:var(--petrol)'>{h(c.author)}</b> "
        f"<span style='color:var(--muted);font-size:11px'>{c.created.strftime('%d-%b %H:%M') if c.created else ''}</span>"
        f"<div style='font-size:13.5px'>{h(c.text)}</div></div>"
        for c in sorted(r.comments, key=lambda x: x.id)) or \
        "<p style='color:var(--muted);font-size:13px'>No comments yet.</p>"
    body = f"""<div class='panel'><div class='ph'><h2>REF-{r.id:04d} · {h(r.patient_name)} — Thread</h2>
      <div class='sp'></div><a class='btn sm' href='{url_for('modules.module', mod='referrals')}'>← Referrals</a></div>
      <div class='pad' style='font-size:13.5px'><b>Doctor:</b> {h(r.doctor_name or '—')} · <b>Priority:</b> {h(r.priority or 'Routine')}<br>
      <b>Complaint:</b> {h(r.complaint or '—')} · <b>Prov. Dx:</b> {h(r.prov_dx or '—')}<br>
      <b>Tests:</b> {h(r.tests or '—')}</div></div>
      <div class='panel'><div class='pad'>{cmts}
      <form method='post' style='margin-top:10px'><div style='display:flex;gap:8px'>
        <input name='text' maxlength='500' placeholder='Reply to the referring doctor…' style='flex:1;border:1px solid var(--line);border-radius:9px;padding:9px 12px'>
        <button class='btn primary'>Send</button></div></form></div></div>"""
    return page(f'REF-{r.id:04d}', body, 'referrals')


@bp.route('/referral/<int:rid>/invoice')
@login_required
def referral_invoice(rid):
    """Create an invoice from a Doctor Request, pulling its lab/rad orders."""
    if not can('invoices'): abort(403)
    from ..models import Invoice, InvoiceItem, LabOrder, RadOrder, Service, Patient
    from ..core.posting import repost_invoice, repost_payment
    r = Referral.query.get_or_404(rid)
    existing = Invoice.query.filter(Invoice.referral_id == rid, Invoice.status != 'Cancelled').first()
    if existing:
        flash(f'Invoice already exists for this Doctor Request (INV-{existing.id:04d}). Opening it instead of creating a duplicate.')
        log(f'BLOCKED duplicate invoice for REF-{rid:04d} (exists INV-{existing.id:04d})')
        return redirect(url_for('billing.invoice_view', iid=existing.id))
    if not r.patient_id:
        # auto-register the patient from the request so the receptionist isn't
        # dead-ended — same record Accept would have created.
        p = Patient(mrn='MRN' + str((Patient.query.count() or 0) + 1001),
                    name=r.patient_name or 'Referral Patient', phone=r.patient_phone,
                    gender=r.patient_gender,
                    notes=f"Referred by {(r.doctor_ref.name if r.doctor_ref else r.doctor_name) or '—'}. "
                          f"Requested: {r.tests or '—'}")
        db.session.add(p); db.session.flush(); r.patient_id = p.id
        if r.status == 'New':
            r.status = 'Accepted'
    inv = Invoice(patient_id=r.patient_id, referral_id=rid,
                  referring_doctor_id=r.doctor_id, date=today())
    db.session.add(inv); db.session.flush()
    n = 0
    for d in _referral_services(r):
        svc = d['svc']
        if not svc:
            # requested test with no catalog match — keep the line so nothing is
            # lost; cashier can set the price. (desc carries the requested name.)
            db.session.add(InvoiceItem(invoice_id=inv.id, service_id=None,
                                       desc=d['name'], qty=1, price=0))
            n += 1
            continue
        it = InvoiceItem(invoice_id=inv.id, service_id=svc.id, desc=svc.name,
                         qty=1, price=svc.price or 0)
        order = d['order']
        if order is None and d['kind'] in ('Lab', 'Rad'):
            # create the lab/rad order now so the lab/radiology worklist + paid-gate work
            if d['kind'] == 'Rad':
                order = RadOrder(patient_id=r.patient_id, service_id=svc.id, ref_id=r.id,
                                 modality=svc.modality, status='Requested', paid_gate=False)
            else:
                order = LabOrder(patient_id=r.patient_id, service_id=svc.id, ref_id=r.id,
                                 status='Requested', paid_gate=False)
            db.session.add(order); db.session.flush()
        if order is not None:
            if isinstance(order, LabOrder):
                it.lab_order_id = order.id
            else:
                it.rad_order_id = order.id
            order.invoice_id = inv.id
        db.session.add(it)
        n += 1
    db.session.commit()
    try:
        repost_invoice(inv); repost_payment(inv)
    except Exception:
        db.session.rollback()
    log(f'Invoice #{inv.id} created from REF-{rid:04d} ({n} services)')
    flash(f'Invoice created from Doctor Request with {n} service(s)')
    return redirect(url_for('billing.invoice_view', iid=inv.id))


def _release_gate(inv):
    """Release lab/rad orders for work once their invoice is paid/approved."""
    from ..models import LabOrder, RadOrder
    ok = (inv.status == 'Paid') or (inv.paid or 0) >= (inv.total or 0) - 0.005
    if not ok:
        return
    for o in LabOrder.query.filter_by(invoice_id=inv.id).all():
        o.paid_gate = True
    for o in RadOrder.query.filter_by(invoice_id=inv.id).all():
        o.paid_gate = True
    db.session.commit()


def reqboard_view():
    """Doctor Requests status board with search + status buckets."""
    from ..models import Invoice, LabOrder, RadOrder
    q = (request.args.get('q') or '').strip().lower()
    fstat = request.args.get('s') or ''
    if q:
        try:
            db.session.add(SearchLog(username=cur_user().username, q=q[:120], module='reqboard'))
            db.session.commit()
            log(f'Search reqboard: "{q[:80]}"', action_type='search', entity='reqboard')
        except Exception:
            db.session.rollback()
    refs = Referral.query.order_by(Referral.id.desc()).all()

    def state(r):
        inv = Invoice.query.filter_by(referral_id=r.id).first()
        orders = LabOrder.query.filter_by(ref_id=r.id).all() + RadOrder.query.filter_by(ref_id=r.id).all()
        if r.status == 'Cancelled':
            return 'Cancelled'
        if not r.patient_id:
            return 'Waiting Registration'
        if not inv:
            return 'Waiting Invoice'
        if inv.status != 'Paid' and (inv.paid or 0) < (inv.total or 0) - 0.005:
            return 'Waiting Payment'
        if orders and all(o.status in ('Approved', 'Reported') for o in orders):
            return 'Completed'
        if any(getattr(o, 'modality', None) or o.__class__.__name__ == 'RadOrder' for o in orders) and \
           any(o.__class__.__name__ == 'RadOrder' and o.status != 'Reported' for o in orders):
            return 'Under Radiology'
        if any(o.__class__.__name__ == 'LabOrder' and o.status != 'Approved' for o in orders):
            return 'Under Laboratory'
        return 'Paid'

    buckets = ['New', 'Waiting Registration', 'Waiting Invoice', 'Waiting Payment',
               'Paid', 'Under Laboratory', 'Under Radiology', 'Completed', 'Cancelled']
    counts = {b: 0 for b in buckets}
    rows = ''
    for r in refs:
        stt = state(r)
        if stt == 'Paid' and r.status == 'New':
            pass
        counts[stt] = counts.get(stt, 0) + 1
        if fstat and stt != fstat:
            continue
        if q and q not in (r.patient_name or '').lower() and q not in (r.doctor_name or '').lower() \
           and q not in f'ref-{r.id:04d}' and q not in (r.date or ''):
            continue
        inv = Invoice.query.filter_by(referral_id=r.id).first()
        pr = ("<span class='pill red'>STAT</span>" if r.priority == 'STAT'
              else "<span class='pill amber'>Urgent</span>" if r.priority == 'Urgent' else '')
        stc = {'Completed': 'green', 'Cancelled': 'grey', 'Waiting Payment': 'red',
               'Paid': 'teal', 'Under Laboratory': 'blue', 'Under Radiology': 'blue'}.get(stt, 'amber')
        inv_link = (f"<a class='btn gh sm' href='{url_for('billing.invoice_view', iid=inv.id)}'>INV-{inv.id:04d}</a>"
                    if inv else f"<a class='btn sm primary' href='{url_for('ref.referral_invoice', rid=r.id)}'>+ Invoice</a>"
                    if r.patient_id else '<span style="color:var(--muted);font-size:12px">register first</span>')
        inv_link = f"<a class='btn sm' href='{url_for('ref.referral_detail', rid=r.id)}'>Open</a> " + inv_link
        _pl = (f"<a href='/patient/{r.patient_id}' style='color:var(--petrol);font-weight:700'>{h(r.patient_name or '—')}</a>"
               if r.patient_id else pnamelink(r.patient_name))
        rows += (f"<tr><td><b>REF-{r.id:04d}</b><div style='color:var(--muted);font-size:11px'>{h(r.date)}</div></td>"
                 f"<td>{_pl}<div style='color:var(--muted);font-size:11px'>{h(r.patient_phone or '')}</div></td>"
                 f"<td>{h(r.doctor_name or '—')}</td><td style='font-size:12px'>{h((r.tests or '—')[:44])}</td><td>{pr}</td>"
                 f"<td><span class='pill {stc}'>{h(stt)}</span></td><td class='num'>{inv_link}</td></tr>")
    rows = rows or "<tr><td colspan='7' style='color:var(--muted);padding:16px'>No requests match.</td></tr>"
    if q:
        from .modules import hl
        rows = hl(rows, q)
    chips = ''.join(
        f"<a href='?s={b}' class='pill {'blue' if fstat==b else 'grey'}' style='margin:2px;text-decoration:none'>{b} · {counts.get(b,0)}</a>"
        for b in buckets)
    chips = f"<a href='?' class='pill {'blue' if not fstat else 'grey'}' style='margin:2px;text-decoration:none'>All · {len(refs)}</a>" + chips
    body = f"""<div class='panel'><div class='pad'>{chips}</div></div>
      <div class='panel'><div class='ph'><h2>Doctor Requests Board</h2><div class='sp'></div>
      <form method='get'><input name='q' value='{h(q)}' placeholder='Req #, patient, doctor, date…' style='border:1px solid var(--line);border-radius:9px;padding:7px 12px;font-size:13px'>
      {f"<input type='hidden' name='s' value='{h(fstat)}'>" if fstat else ''}</form></div>
      <div class='tw'><table><thead><tr><th>Request</th><th>Patient</th><th>Doctor</th><th>Services</th><th></th><th>Status</th><th>Invoice</th></tr></thead>
      <tbody>{rows}</tbody></table></div></div>"""
    return page('Doctor Requests', body, 'reqboard')


# ---- Odoo-style status chevron order for a doctor request ----
REQ_STAGES = ['Draft', 'Submitted', 'Invoiced', 'Paid', 'Sample Collected',
              'Processing', 'Completed']


def _req_stage(r):
    """Compute the current workflow stage of a referral for the progress bar."""
    from ..models import Invoice, LabOrder, RadOrder
    if r.status == 'Cancelled':
        return 'Cancelled'
    inv = Invoice.query.filter_by(referral_id=r.id).first()
    orders = LabOrder.query.filter_by(ref_id=r.id).all() + RadOrder.query.filter_by(ref_id=r.id).all()
    if orders and all(o.status in ('Approved', 'Reported') for o in orders):
        return 'Completed'
    if any(getattr(o, 'sample_no', None) or o.status not in ('Requested',) for o in orders) and \
       any(o.paid_gate is not False for o in orders):
        # work has started
        if any(getattr(o, 'sample_no', None) for o in orders):
            return 'Sample Collected' if all(o.status in ('Collected', 'Received', 'Requested') for o in orders) else 'Processing'
        return 'Processing'
    if inv and (inv.status == 'Paid' or (inv.paid or 0) >= (inv.total or 0) - 0.005 and (inv.total or 0) > 0):
        return 'Paid'
    if inv:
        return 'Invoiced'
    if r.patient_id:
        return 'Submitted'
    return 'Draft'


@bp.route('/referral/<int:rid>/detail')
@login_required
def referral_detail(rid):
    """Odoo-style Doctor Request detail: chevron progress, linked records, timeline."""
    if not can('referrals') and not can('reqboard'):
        abort(403)
    from ..models import Invoice, LabOrder, RadOrder, Audit, Patient
    r = Referral.query.get_or_404(rid)
    stage = _req_stage(r)
    inv = Invoice.query.filter_by(referral_id=rid).first()
    labs = LabOrder.query.filter_by(ref_id=rid).all()
    rads = RadOrder.query.filter_by(ref_id=rid).all()
    pat = Patient.query.get(r.patient_id) if r.patient_id else None

    # ---- chevron progress bar ----
    cur_idx = REQ_STAGES.index(stage) if stage in REQ_STAGES else -1
    chev = ''
    if stage == 'Cancelled':
        chev = "<div class='chev-wrap'><span class='chev done' style='--c:var(--red)'>Cancelled</span></div>"
    else:
        cells = []
        for i, st in enumerate(REQ_STAGES):
            cls = 'done' if i < cur_idx else ('active' if i == cur_idx else '')
            cells.append(f"<span class='chev {cls}'>{st}</span>")
        chev = "<div class='chev-wrap'>" + ''.join(cells) + "</div>"

    # ---- linked-record smart buttons ----
    btns = []
    if inv:
        btns.append(f"<a class='sbtn' href='{url_for('billing.invoice_view', iid=inv.id)}'>"
                    f"<span class='sbtn-v'>INV-{inv.id:04d}</span><span class='sbtn-l'>Invoice · {h(inv.status)}</span></a>")
    elif r.patient_id and can('invoices'):
        btns.append(f"<a class='sbtn sbtn-cta' href='{url_for('ref.referral_invoice', rid=rid)}'>"
                    f"<span class='sbtn-v'>+ Create</span><span class='sbtn-l'>Invoice</span></a>")
    if inv:
        paid = inv.paid or 0
        btns.append(f"<a class='sbtn' href='{url_for('billing.invoice_view', iid=inv.id)}'>"
                    f"<span class='sbtn-v'>{money(paid)}</span><span class='sbtn-l'>Paid of {money(inv.total)}</span></a>")
    if pat:
        btns.append(f"<a class='sbtn' href='/patient/{pat.id}'>"
                    f"<span class='sbtn-v'>{h(pat.mrn)}</span><span class='sbtn-l'>Patient Hub</span></a>")
    if labs:
        done = sum(1 for o in labs if o.status == 'Approved')
        btns.append(f"<a class='sbtn' href='{url_for('modules.module', mod='lab')}'>"
                    f"<span class='sbtn-v'>{done}/{len(labs)}</span><span class='sbtn-l'>Lab Results</span></a>")
    if rads:
        done = sum(1 for o in rads if o.status == 'Reported')
        btns.append(f"<a class='sbtn' href='{url_for('modules.module', mod='radiology')}'>"
                    f"<span class='sbtn-v'>{done}/{len(rads)}</span><span class='sbtn-l'>Radiology</span></a>")
    smart = "<div class='sbtns'>" + ''.join(btns) + "</div>" if btns else ''

    # ---- services table (prices always shown, from orders or requested names) ----
    resolved = _referral_services(r)
    def _svc_row(d):
        kind = d['kind']
        kc = {'Lab': 'blue', 'Rad': 'teal'}.get(kind, 'grey')
        klabel = {'Lab': 'Lab', 'Rad': 'Rad', 'Svc': 'Service'}.get(kind, kind)
        if d['status']:
            stc = {'Approved': 'green', 'Reported': 'green', 'Requested': 'blue',
                   'Collected': 'amber', 'Received': 'amber', 'Resulted': 'teal',
                   'Imaged': 'teal'}.get(d['status'], 'grey')
            o = d['order']
            gate = '' if (o is None or o.paid_gate is not False) else " <span class='pill red'>unpaid</span>"
            status_cell = f"<span class='pill {stc}'>{h(d['status'])}</span>{gate}"
        else:
            status_cell = "<span class='pill amber'>Requested</span>"
        price = d['price']
        pcell = money(price) if (d['svc'] or price) else "<span style='color:var(--muted)'>— set at cashier</span>"
        return (f"<tr><td><span class='pill {kc}'>{klabel}</span></td>"
                f"<td><b>{h(d['name'])}</b></td><td class='num'>{pcell}</td>"
                f"<td>{status_cell}</td></tr>")
    svc_rows = ''.join(_svc_row(d) for d in resolved)
    est_total = sum(d['price'] for d in resolved)
    total_row = (f"<tr><td></td><td style='text-align:right;color:var(--muted)'>Estimated total</td>"
                 f"<td class='num'><b style='color:var(--petrol);font-size:15px'>{money(est_total)}</b></td><td></td></tr>"
                 if resolved else '')
    quote_hint = ("<div class='pad' style='border-top:1px solid var(--line);color:var(--muted);font-size:12.5px'>"
                  "💬 Tell the customer this estimate before payment. Create the invoice to confirm and collect."
                  if resolved else '')
    svc_table = (f"<div class='panel'><div class='ph'><h2>Requested Services</h2>"
                 f"<div class='sp'></div>"
                 + (f"<a class='btn primary sm' href='{url_for('ref.referral_invoice', rid=rid)}'>+ Create Invoice</a>"
                    if (not inv and can('invoices')) else
                    (f"<a class='btn sm' href='{url_for('billing.invoice_view', iid=inv.id)}'>Open INV-{inv.id:04d}</a>" if inv else ''))
                 + f"</div>"
                 f"<div class='tw'><table><thead><tr><th></th><th>Service</th><th class='num'>Price</th><th>Status</th></tr></thead>"
                 f"<tbody>{svc_rows or '<tr><td colspan=4 style=color:var(--muted);padding:14px>No services requested.</td></tr>'}"
                 f"{total_row}</tbody></table></div>{quote_hint}</div>")

    # ---- timeline from audit log + record timestamps ----
    events = []
    if r.created:
        events.append((r.created.strftime('%Y-%m-%d %H:%M'), 'Request created', r.doctor_name or '—'))
    if r.patient_id:
        events.append((r.date or '', 'Patient registered / submitted', r.doctor_name or 'Reception'))
    if inv:
        events.append((inv.date or '', f'Invoice INV-{inv.id:04d} created', 'Reception'))
        if (inv.paid or 0) > 0:
            events.append((inv.date or '', f'Payment {money(inv.paid)} received', inv.pay_method or 'Cash'))
    for o in labs:
        if o.collected_at:
            events.append((o.collected_at, f'Sample collected ({o.service.name if o.service else "lab"})', o.collected_by or '—'))
        if o.status == 'Approved':
            events.append((o.date or '', f'Lab approved ({o.service.name if o.service else ""})', o.approved_by or '—'))
    for o in rads:
        if o.status == 'Reported':
            events.append((o.rad_approved_at or o.date or '', f'Radiology reported ({o.service.name if o.service else ""})', o.radiologist or o.reported_by or '—'))
    # pull related audit lines
    for a in Audit.query.filter(Audit.action.like(f'%REF-{rid:04d}%')).order_by(Audit.id).all():
        events.append((a.ts.strftime('%Y-%m-%d %H:%M') if a.ts else '', a.action, a.user or '—'))
    events = [e for e in events if e[0]]
    events.sort(key=lambda x: x[0])
    tl = ''.join(f"<div class='tl-row'><div class='tl-dot'></div><div class='tl-body'>"
                 f"<div class='tl-when'>{h(str(when))}</div><div class='tl-what'>{h(what)}</div>"
                 f"<div class='tl-who'>by {h(who)}</div></div></div>" for when, what, who in events) or \
         "<div style='color:var(--muted);padding:10px'>No events yet.</div>"
    timeline = f"<div class='panel'><div class='ph'><h2>Timeline</h2></div><div class='pad'><div class='tl'>{tl}</div></div></div>"

    pr = {'STAT': 'red', 'Urgent': 'amber'}.get(r.priority, 'grey')
    header = (f"<div class='panel'><div class='pad'>"
              f"<div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;align-items:center'>"
              f"<div><div style='font-family:var(--fd);font-size:20px;font-weight:700;color:var(--petrol)'>REF-{r.id:04d}</div>"
              f"<div style='color:var(--muted);font-size:13px'>{h(r.patient_name or '—')} · {h(r.patient_gender or '')} "
              f"{('· '+str(r.patient_age)+' yr') if r.patient_age else ''} · {h(r.date)}</div></div>"
              f"<div style='text-align:right'><span class='pill {pr}'>{h(r.priority or 'Routine')}</span> "
              f"<span class='pill blue' style='margin-left:4px'>{h(stage)}</span></div></div>"
              f"<div style='margin-top:10px;font-size:13px'><b>Referring Doctor:</b> {h(r.doctor_name or '—')}"
              f"{(' · '+h(r.hospital)) if r.hospital else ''} · <b>Complaint:</b> {h(r.complaint or '—')} · "
              f"<b>Prov. Dx:</b> {h(r.prov_dx or '—')}</div></div></div>")

    body = header + chev + smart + f"<div class='grid2'>{svc_table}{timeline}</div>"
    return page(f'REF-{r.id:04d}', body, 'reqboard')
