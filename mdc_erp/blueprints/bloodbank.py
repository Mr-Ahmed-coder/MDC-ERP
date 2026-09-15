"""Blood Bank expansion  (Phase 12, v8.0).

Builds on the existing Donor + BloodUnit registries with: an expiry-alert
dashboard, ABO/Rh cross-matching, and transfusion records. All-new tables; the
donor and unit registries stay as they are.
"""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import CrossMatch, Transfusion, BloodUnit, Patient
from ..core.security import (cur_user, can, login_required, log, branch_scope)
from ..core.helpers import today
from ..core.ui import page

bp = Blueprint('bloodbank', __name__)

GROUPS = ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+']
# recipient -> compatible donor groups (packed red cells)
COMPAT = {
    'O-': ['O-'], 'O+': ['O-', 'O+'],
    'A-': ['O-', 'A-'], 'A+': ['O-', 'O+', 'A-', 'A+'],
    'B-': ['O-', 'B-'], 'B+': ['O-', 'O+', 'B-', 'B+'],
    'AB-': ['O-', 'A-', 'B-', 'AB-'], 'AB+': GROUPS,
}
EXPIRY_WARN_DAYS = 7


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


def _days_to(expiry):
    try:
        e = dt.date.fromisoformat((expiry or '')[:10])
        return (e - dt.date.today()).days
    except Exception:
        return None


def _compatible(recipient_group, donor_group):
    return donor_group in COMPAT.get(recipient_group or '', [])


# ==================================================================== dashboard
def bb_dashboard():
    """Blood bank dashboard — App Launcher (mod='bloodbank')."""
    units = branch_scope(BloodUnit.query, BloodUnit).all()
    avail = [u for u in units if u.status == 'Available']
    reserved = [u for u in units if u.status == 'Reserved']
    expiring = [u for u in units if u.status in ('Available', 'Reserved')
                and (_days_to(u.expiry) is not None and 0 <= _days_to(u.expiry) <= EXPIRY_WARN_DAYS)]
    expired = [u for u in units if u.status in ('Available', 'Reserved')
               and (_days_to(u.expiry) is not None and _days_to(u.expiry) < 0)]

    # stock by group
    stock = {g: 0 for g in GROUPS}
    for u in avail:
        if u.blood_group in stock:
            stock[u.blood_group] += 1
    stock_cards = ''.join(
        f"<div class='panel' style='display:inline-block;min-width:80px;margin:3px'><div class='pad' style='text-align:center'>"
        f"<div style='font-size:20px;font-weight:800;color:var(--red)'>{stock[g]}</div>"
        f"<div class='pill red'>{g}</div></div></div>" for g in GROUPS)

    def kpi(n, label, ac):
        return f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div><div class='v'>{n}</div><div class='s'></div></div>"
    kpis = ("<div class='kpis'>"
            + kpi(len(avail), 'Available units', 'var(--green)')
            + kpi(len(reserved), 'Reserved', 'var(--blue)')
            + kpi(len(expiring), 'Expiring ≤7d', 'var(--amber-dk)')
            + kpi(len(expired), 'Expired', 'var(--red)') + "</div>")

    # alert lists
    def unit_rows(lst):
        r = ''
        for u in lst:
            d = _days_to(u.expiry)
            tag = (f"<span class='pill red'>expired {abs(d)}d ago</span>" if (d is not None and d < 0)
                   else f"<span class='pill amber'>in {d}d</span>")
            r += (f"<tr><td><b>{h(u.unit_no or u.id)}</b></td><td>{h(u.blood_group or '')}</td>"
                  f"<td>{h(u.expiry or '—')} {tag}</td><td>{h(u.status)}</td></tr>")
        return r or "<tr><td colspan='4' style='color:var(--muted)'>None</td></tr>"

    alerts = ''
    if expiring or expired:
        sweep = (f"<a class='btn sm' href='{url_for('bloodbank.expire_sweep')}' "
                 f"onclick=\"return confirm('Mark all past-expiry units as Expired?')\">Mark expired</a>" if expired else '')
        alerts = (f"<div class='panel'><div class='ph'><h2>⚠ Expiry alerts</h2><div class='sp'></div>{sweep}</div>"
                  f"<div class='tw'><table><thead><tr><th>Unit</th><th>Group</th><th>Expiry</th><th>Status</th></tr></thead>"
                  f"<tbody>{unit_rows(expired + expiring)}</tbody></table></div></div>")

    toolbar = (f"<a class='btn' href='{url_for('modules.module', mod='donors')}'>🧑 Donors</a> "
               f"<a class='btn' href='{url_for('modules.module', mod='bloodunits')}'>🩸 Stock</a> "
               f"<a class='btn' href='{url_for('bloodbank.crossmatch')}'>🔬 Cross-match</a> "
               f"<a class='btn primary' href='{url_for('bloodbank.transfuse')}'>💉 Transfuse</a>")
    body = (kpis
            + f"<div class='panel'><div class='ph'><h2>Blood Stock by Group · {h(today())}</h2><div class='sp'></div>{toolbar}</div>"
            f"<div class='pad'>{stock_cards}</div></div>"
            + alerts)
    return page('Blood Bank', body, 'bloodbank')


# ================================================================== cross-match
@bp.route('/bloodbank/crossmatch', methods=['GET', 'POST'])
@login_required
def crossmatch():
    if not can('bloodbank'):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        pid = request.form.get('patient_id') or None
        uid = request.form.get('unit_id') or None
        result = request.form.get('result') or 'Compatible'
        cm = CrossMatch(patient_id=pid, unit_id=uid, result=result,
                        technician=(u.username if u else None), note=request.form.get('note'),
                        branch_id=(u.branch_id if u else None))
        db.session.add(cm)
        # a compatible cross-match reserves the unit for this patient
        if result == 'Compatible' and uid:
            unit = db.session.get(BloodUnit, int(uid))
            if unit and unit.status == 'Available':
                unit.status = 'Reserved'
                unit.issued_to = int(pid) if pid else None
        db.session.commit()
        log(f'Cross-match #{cm.id} — {result}', entity=f'CrossMatch#{cm.id}')
        flash(f'Cross-match recorded: {result}', 'ok')
        return redirect(url_for('modules.module', mod='bloodbank'))

    patients = Patient.query.order_by(Patient.id.desc()).limit(300).all()
    popts = "<option value=''>— patient —</option>" + ''.join(
        f"<option value='{p.id}' data-group='{h(p.blood_group or '')}'>{h(p.name)} ({h(p.blood_group or '?')})</option>"
        for p in patients)
    units = branch_scope(BloodUnit.query.filter_by(status='Available'), BloodUnit).all()
    uopts = "<option value=''>— unit —</option>" + ''.join(
        f"<option value='{u.id}' data-group='{h(u.blood_group or '')}'>{h(u.unit_no or u.id)} · {h(u.blood_group or '')} (exp {h(u.expiry or '?')})</option>"
        for u in units)
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Recipient patient</label><select name='patient_id' id='pt'>{popts}</select></div>
      <div class='fld'><label>Donor unit</label><select name='unit_id' id='un'>{uopts}</select></div>
      <div class='fld full'><div id='compat' style='font-size:13px'></div></div>
      <div class='fld'><label>Result</label><select name='result'><option>Compatible</option><option>Incompatible</option></select></div>
      <div class='fld full'><label>Note</label><input name='note'></div>
      <div class='fld full'><button class='btn primary'>Record cross-match</button>
        <a class='btn gh' href="{url_for('modules.module', mod='bloodbank')}">Cancel</a></div>
    </form>
    <div style='font-size:12px;color:var(--muted);margin-top:6px'>A Compatible result reserves the unit for the patient. ABO/Rh guidance is advisory — always confirm serologically.</div>
    </div></div>
    <script>
    var COMPAT={{'O-':['O-'],'O+':['O-','O+'],'A-':['O-','A-'],'A+':['O-','O+','A-','A+'],'B-':['O-','B-'],'B+':['O-','O+','B-','B+'],'AB-':['O-','A-','B-','AB-'],'AB+':['O-','O+','A-','A+','B-','B+','AB-','AB+']}};
    function chk(){{
      var pg=document.querySelector('#pt option:checked').dataset.group||'';
      var ug=document.querySelector('#un option:checked').dataset.group||'';
      var el=document.getElementById('compat'); if(!pg||!ug){{el.textContent='';return;}}
      var ok=(COMPAT[pg]||[]).indexOf(ug)>=0;
      el.innerHTML = ok ? "<span class='pill green'>ABO/Rh compatible</span> ("+pg+" ← "+ug+")"
                        : "<span class='pill red'>⚠ ABO/Rh INCOMPATIBLE</span> ("+pg+" ← "+ug+")";
    }}
    document.getElementById('pt').onchange=chk; document.getElementById('un').onchange=chk;
    </script>"""
    return page('Cross-match', inner, 'bloodbank')


# ================================================================== transfusion
@bp.route('/bloodbank/transfuse', methods=['GET', 'POST'])
@login_required
def transfuse():
    if not can('bloodbank'):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        pid = request.form.get('patient_id') or None
        uid = request.form.get('unit_id') or None
        t = Transfusion(patient_id=pid, unit_id=uid,
                        volume_ml=request.form.get('volume_ml') or None,
                        reaction=request.form.get('reaction') or 'None',
                        by=(u.username if u else None), note=request.form.get('note'),
                        ended_at=_now(), branch_id=(u.branch_id if u else None))
        db.session.add(t)
        # mark the unit used / issued
        if uid:
            unit = db.session.get(BloodUnit, int(uid))
            if unit:
                unit.status = 'Used'
                unit.issued_to = int(pid) if pid else None
                unit.issued_date = today()
        db.session.commit()
        log(f'Transfusion #{t.id} recorded', entity=f'Transfusion#{t.id}')
        flash('Transfusion recorded', 'ok')
        return redirect(url_for('modules.module', mod='bloodbank'))

    popts = "<option value=''>— patient —</option>" + ''.join(
        f"<option value='{p.id}'>{h(p.name)} ({h(p.blood_group or '?')})</option>"
        for p in Patient.query.order_by(Patient.id.desc()).limit(300).all())
    # units that are Reserved or Available can be transfused
    units = branch_scope(BloodUnit.query.filter(BloodUnit.status.in_(['Reserved', 'Available'])), BloodUnit).all()
    uopts = "<option value=''>— unit —</option>" + ''.join(
        f"<option value='{u.id}'>{h(u.unit_no or u.id)} · {h(u.blood_group or '')} ({h(u.status)})</option>"
        for u in units)
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Patient</label><select name='patient_id'>{popts}</select></div>
      <div class='fld'><label>Unit</label><select name='unit_id'>{uopts}</select></div>
      <div class='fld'><label>Volume (ml)</label><input name='volume_ml' type='number' value='450'></div>
      <div class='fld'><label>Reaction</label><input name='reaction' value='None'></div>
      <div class='fld full'><label>Note</label><input name='note'></div>
      <div class='fld full'><button class='btn primary'>Record transfusion</button>
        <a class='btn gh' href="{url_for('modules.module', mod='bloodbank')}">Cancel</a></div>
    </form>
    <div style='font-size:12px;color:var(--muted);margin-top:6px'>Recording a transfusion marks the unit as Used and issued to the patient.</div>
    </div></div>"""
    return page('Transfusion', inner, 'bloodbank')


@bp.route('/bloodbank/expire')
@login_required
def expire_sweep():
    if not can('bloodbank'):
        abort(403)
    units = branch_scope(BloodUnit.query.filter(BloodUnit.status.in_(['Available', 'Reserved'])), BloodUnit).all()
    n = 0
    for u in units:
        d = _days_to(u.expiry)
        if d is not None and d < 0:
            u.status = 'Expired'
            n += 1
    db.session.commit()
    log(f'Blood bank: {n} unit(s) marked expired', entity='BloodBank')
    flash(f'{n} unit(s) marked expired', 'ok')
    return redirect(url_for('modules.module', mod='bloodbank'))
