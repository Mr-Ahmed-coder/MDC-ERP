"""Ambulance  (Phase 11, v8.0).

Vehicle & driver registries, dispatch with a timestamped status flow, location
tracking (manual entry + a token-protected endpoint a GPS device / phone can
push coordinates to), map links, and billing. All-new tables.

Note on "GPS tracking": the ERP provides the ingest endpoint and map links — a
device or a phone running a tracker app in the vehicle posts its coordinates to
POST /api/ambulance/<id>/location. There is no built-in telematics network.
"""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort, jsonify)
from markupsafe import escape as h
from ..extensions import db
from ..models import (Ambulance, AmbulanceDriver, Dispatch, DispatchLocation,
                      Patient, Invoice)
from ..core.security import (cur_user, can, login_required, log, setting, branch_scope, can_see)
from ..core.helpers import today
from ..core.ui import page
from ..core.crud import register, pill

bp = Blueprint('ambulance', __name__)

ST_PILL = {'Requested': 'amber', 'Dispatched': 'blue', 'OnScene': 'petrol',
           'Transporting': 'amber', 'Completed': 'green', 'Cancelled': 'grey'}
FLOW = ['Requested', 'Dispatched', 'OnScene', 'Transporting', 'Completed']
NEXT_LABEL = {'Requested': ('Dispatch', 'Dispatched'), 'Dispatched': ('On scene', 'OnScene'),
              'OnScene': ('Start transport', 'Transporting'), 'Transporting': ('Complete', 'Completed')}
STAMP = {'Dispatched': 'dispatched_at', 'OnScene': 'onscene_at',
         'Transporting': 'transporting_at', 'Completed': 'completed_at'}


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


def _opt_vehicles():
    return [('', '— vehicle —')] + [
        (v.id, f'{v.label} ({v.plate or ""})') for v in
        branch_scope(Ambulance.query.filter_by(active=True), Ambulance).order_by(Ambulance.label).all()]


def _opt_drivers():
    return [('', '— driver —')] + [
        (d.id, d.name) for d in
        branch_scope(AmbulanceDriver.query.filter_by(active=True), AmbulanceDriver).order_by(AmbulanceDriver.name).all()]


def _maplink(lat, lng):
    return f"https://maps.google.com/?q={lat},{lng}" if (lat is not None and lng is not None) else None


# ==================================================================== board
def amb_board():
    """Dispatch board — App Launcher (mod='ambulance')."""
    dispatches = branch_scope(Dispatch.query, Dispatch).order_by(
        Dispatch.status.in_(['Completed', 'Cancelled']), Dispatch.id.desc()).limit(400).all()
    vehicles = branch_scope(Ambulance.query.filter_by(active=True), Ambulance).all()
    active = [d for d in dispatches if d.status not in ('Completed', 'Cancelled')]

    def kpi(n, label, ac):
        return f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div><div class='v'>{n}</div><div class='s'></div></div>"
    kpis = ("<div class='kpis'>"
            + kpi(len(active), 'Active calls', 'var(--amber-dk)')
            + kpi(sum(1 for d in active if d.priority == 'Emergency'), 'Emergency', 'var(--red)')
            + kpi(sum(1 for v in vehicles if v.status == 'Available'), 'Available units', 'var(--green)')
            + kpi(len(vehicles), 'Total units', 'var(--petrol)') + "</div>")

    rows = ''
    for d in dispatches:
        prio = "<span class='pill red'>Emergency</span> " if d.priority == 'Emergency' else ''
        who = d.patient.name if d.patient else (d.caller_name or '—')
        rows += (f"<tr><td>{h(d.requested_at or '—')}</td>"
                 f"<td><b>{h(who)}</b></td>"
                 f"<td>{prio}{h(d.pickup or '—')} → {h(d.destination or '—')}</td>"
                 f"<td>{h(d.vehicle.label if d.vehicle else '—')}</td>"
                 f"<td>{h(d.driver.name if d.driver else '—')}</td>"
                 f"<td><span class='pill {ST_PILL.get(d.status,'grey')}'>{h(d.status)}</span></td>"
                 f"<td class='num'><a class='btn sm primary' href='{url_for('ambulance.dispatch_view', did=d.id)}'>Open</a></td></tr>")
    if not rows:
        rows = "<tr><td colspan='7'><div class='empty'><b>No dispatches</b>Create one to begin.</div></td></tr>"

    toolbar = (f"<a class='btn' href='{url_for('modules.module', mod='vehicles')}'>🚐 Vehicles</a> "
               f"<a class='btn' href='{url_for('modules.module', mod='drivers_amb')}'>🧑 Drivers</a> "
               f"<a class='btn primary' href='{url_for('ambulance.new')}'>+ New Dispatch</a>")
    body = (kpis + f"""<div class="panel"><div class="ph"><h2>Ambulance Dispatch · {h(today())}</h2>
      <div class="sp"></div>{toolbar}</div>
      <div class="tw"><table><thead><tr><th>Requested</th><th>Patient / Caller</th><th>Route</th>
      <th>Unit</th><th>Driver</th><th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>""")
    return page('Ambulance', body, 'ambulance')


# ================================================================== dispatch
@bp.route('/ambulance/new', methods=['GET', 'POST'])
@login_required
def new():
    if not can('ambulance'):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        veh_id = request.form.get('vehicle_id') or None
        d = Dispatch(
            vehicle_id=veh_id, driver_id=request.form.get('driver_id') or None,
            patient_id=request.form.get('patient_id') or None,
            caller_name=request.form.get('caller_name'), caller_phone=request.form.get('caller_phone'),
            pickup=request.form.get('pickup'), destination=request.form.get('destination'),
            priority=request.form.get('priority') or 'Emergency', reason=request.form.get('reason'),
            status='Requested', created_by=(u.username if u else None),
            branch_id=(u.branch_id if u else None))
        db.session.add(d)
        db.session.commit()
        log(f'Ambulance dispatch #{d.id} created', entity=f'Dispatch#{d.id}')
        flash('Dispatch created', 'ok')
        return redirect(url_for('ambulance.dispatch_view', did=d.id))
    popts = "<option value=''>— patient (optional) —</option>" + ''.join(
        f"<option value='{p.id}'>{h(p.name)} ({h(p.mrn or '')})</option>"
        for p in Patient.query.order_by(Patient.id.desc()).limit(300).all())
    vopts = ''.join(f"<option value='{v}'>{h(lb)}</option>" for v, lb in _opt_vehicles())
    dopts = ''.join(f"<option value='{v}'>{h(lb)}</option>" for v, lb in _opt_drivers())
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Patient</label><select name='patient_id'>{popts}</select></div>
      <div class='fld'><label>Priority</label><select name='priority'><option>Emergency</option><option>Non-emergency</option></select></div>
      <div class='fld'><label>Caller name</label><input name='caller_name'></div>
      <div class='fld'><label>Caller phone</label><input name='caller_phone'></div>
      <div class='fld full'><label>Pickup location</label><input name='pickup'></div>
      <div class='fld full'><label>Destination</label><input name='destination'></div>
      <div class='fld'><label>Vehicle</label><select name='vehicle_id'>{vopts}</select></div>
      <div class='fld'><label>Driver</label><select name='driver_id'>{dopts}</select></div>
      <div class='fld full'><label>Reason / notes</label><input name='reason'></div>
      <div class='fld full'><button class='btn primary'>Create dispatch</button>
        <a class='btn gh' href="{url_for('modules.module', mod='ambulance')}">Cancel</a></div>
    </form></div></div>"""
    return page('New Dispatch', inner, 'ambulance')


@bp.route('/ambulance/<int:did>')
@login_required
def dispatch_view(did):
    if not can('ambulance'):
        abort(403)
    d = Dispatch.query.get_or_404(did)
    if not can_see(d):
        abort(403)
    who = d.patient.name if d.patient else (d.caller_name or '—')
    times = ''
    for st in ('Dispatched', 'OnScene', 'Transporting', 'Completed'):
        ts = getattr(d, STAMP[st])
        if ts:
            times += f"<span class='pill grey'>{h(st)}: {h(ts)}</span> "
    head = (f"<div class='panel'><div class='pad'>"
            f"<b style='font-size:18px'>{h(who)}</b> "
            + ("<span class='pill red'>Emergency</span> " if d.priority == 'Emergency' else '')
            + f"<span class='pill {ST_PILL.get(d.status,'grey')}'>{h(d.status)}</span>"
            f"<div style='margin-top:6px;font-size:13px'>"
            f"<b>Route:</b> {h(d.pickup or '—')} → {h(d.destination or '—')}<br>"
            f"<b>Unit:</b> {h(d.vehicle.label if d.vehicle else '—')} · "
            f"<b>Driver:</b> {h(d.driver.name if d.driver else '—')} · "
            f"<b>Caller:</b> {h(d.caller_phone or '—')}<br>"
            f"<b>Reason:</b> {h(d.reason or '—')}</div>"
            f"<div style='margin-top:6px'>{times or '<span style=color:var(--muted)>Not yet dispatched</span>'}</div>"
            f"</div></div>")

    acts = []
    if d.status in NEXT_LABEL:
        label, nxt = NEXT_LABEL[d.status]
        acts.append(f"<a class='btn sm primary' href='{url_for('ambulance.advance', did=d.id, to=nxt)}'>▶ {label}</a>")
    if d.status not in ('Completed', 'Cancelled'):
        acts.append(f"<a class='btn sm gh' style='color:var(--red)' href='{url_for('ambulance.advance', did=d.id, to='Cancelled')}'>Cancel</a>")
        acts.append(f"<a class='btn sm' href='{url_for('ambulance.locate', did=d.id)}'>📍 Update location</a>")
    if d.invoice_id:
        acts.append(f"<a class='btn sm' href='{url_for('billing.invoice_view', iid=d.invoice_id)}'>🧾 Invoice #{d.invoice_id}</a>")
    else:
        acts.append(f"<a class='btn sm' href='{url_for('ambulance.bill', did=d.id)}'>🧾 Create bill</a>")
    bar = f"<div style='margin:10px 0;display:flex;gap:6px;flex-wrap:wrap'>{' '.join(acts)}</div>"

    # location panel
    link = _maplink(d.last_lat, d.last_lng)
    loc_head = (f"Last known: <b>{d.last_lat}, {d.last_lng}</b> ({h(d.last_loc_at or '')}) "
                f"<a class='btn sm' href='{link}' target='_blank'>🗺 Open in Maps</a>"
                if link else "<span style='color:var(--muted)'>No location reported yet</span>")
    crumbs = ''
    for b in reversed(d.breadcrumbs[-10:]):
        bl = _maplink(b.lat, b.lng)
        crumbs += (f"<div style='font-size:13px;padding:2px 0'>{h(b.at)} · "
                   f"<a href='{bl}' target='_blank'>{b.lat}, {b.lng}</a> "
                   f"<span class='pill {'teal' if b.source=='GPS' else 'grey'}'>{h(b.source)}</span> {h(b.note or '')}</div>")
    loc_panel = (f"<div class='panel'><div class='ph'><h2>Location</h2></div><div class='pad'>"
                 f"{loc_head}<div style='margin-top:8px'>{crumbs}</div></div></div>")

    return page(f'Dispatch #{d.id}', head + bar + loc_panel, 'ambulance',
                crumbs=[('Ambulance', url_for('modules.module', mod='ambulance')), (f'#{d.id}', None)])


@bp.route('/ambulance/<int:did>/advance/<to>')
@login_required
def advance(did, to):
    if not can('ambulance'):
        abort(403)
    d = Dispatch.query.get_or_404(did)
    if not can_see(d):
        abort(403)
    d.status = to
    if to in STAMP:
        setattr(d, STAMP[to], _now())
    # vehicle status sync
    if d.vehicle:
        if to in ('Dispatched', 'OnScene', 'Transporting'):
            d.vehicle.status = 'OnTrip'
        elif to in ('Completed', 'Cancelled'):
            d.vehicle.status = 'Available'
    db.session.commit()
    log(f'Ambulance dispatch #{did} → {to}', entity=f'Dispatch#{did}')
    return redirect(url_for('ambulance.dispatch_view', did=did))


@bp.route('/ambulance/<int:did>/locate', methods=['GET', 'POST'])
@login_required
def locate(did):
    if not can('ambulance'):
        abort(403)
    d = Dispatch.query.get_or_404(did)
    if not can_see(d):
        abort(403)
    if request.method == 'POST':
        try:
            lat = float(request.form.get('lat'))
            lng = float(request.form.get('lng'))
        except (TypeError, ValueError):
            flash('Enter valid latitude and longitude', 'error')
            return redirect(url_for('ambulance.locate', did=did))
        _record_location(d, lat, lng, request.form.get('note'), 'Manual')
        db.session.commit()
        log(f'Ambulance dispatch #{did} location updated', entity=f'Dispatch#{did}')
        return redirect(url_for('ambulance.dispatch_view', did=did))
    inner = f"""
    <div class='panel'><div class='pad'><form method='post' class='formwrap'>
      <div class='fld'><label>Latitude</label><input name='lat' placeholder='6.7699'></div>
      <div class='fld'><label>Longitude</label><input name='lng' placeholder='47.4308'></div>
      <div class='fld full'><label>Note</label><input name='note' placeholder='e.g. en route to hospital'></div>
      <div class='fld full'><button class='btn primary'>Save location</button>
        <a class='btn gh' href="{url_for('ambulance.dispatch_view', did=did)}">Cancel</a></div>
    </form>
    <div style='font-size:12px;color:var(--muted);margin-top:6px'>A GPS device or phone can update this automatically — see the API endpoint in docs.</div>
    </div></div>"""
    return page('Update Location', inner, 'ambulance')


def _record_location(d, lat, lng, note, source):
    d.last_lat, d.last_lng, d.last_loc_at = lat, lng, _now()
    db.session.add(DispatchLocation(dispatch_id=d.id, lat=lat, lng=lng, note=note, source=source))


# ------------- GPS device / phone push (token-protected, CSRF-exempt /api) ---
@bp.route('/api/ambulance/<int:did>/location', methods=['POST'])
def api_location(did):
    token = setting('amb_gps_token', '')
    sent = request.headers.get('X-AMB-Token') or request.args.get('token') or ''
    if not token or sent != token:
        return jsonify({'ok': False, 'error': 'auth'}), 401
    d = db.session.get(Dispatch, did)
    if not d:
        return jsonify({'ok': False, 'error': 'not found'}), 404
    data = request.get_json(silent=True) or request.form
    try:
        lat = float(data.get('lat'))
        lng = float(data.get('lng'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'lat/lng required'}), 400
    _record_location(d, lat, lng, data.get('note'), 'GPS')
    db.session.commit()
    return jsonify({'ok': True, 'dispatch': did, 'lat': lat, 'lng': lng})


@bp.route('/ambulance/<int:did>/bill')
@login_required
def bill(did):
    if not can('ambulance'):
        abort(403)
    d = Dispatch.query.get_or_404(did)
    if not can_see(d):
        abort(403)
    if d.invoice_id:
        return redirect(url_for('billing.invoice_view', iid=d.invoice_id))
    if not d.patient_id:
        flash('Link a registered patient before billing.', 'error')
        return redirect(url_for('ambulance.dispatch_view', did=did))
    u = cur_user()
    inv = Invoice(patient_id=d.patient_id, date=today(), branch_id=(u.branch_id if u else None))
    db.session.add(inv)
    db.session.commit()
    d.invoice_id = inv.id
    db.session.commit()
    log(f'Ambulance dispatch #{did} invoice #{inv.id}', entity=f'Dispatch#{did}')
    flash('Invoice created — add the ambulance charge', 'ok')
    return redirect(url_for('billing.invoice_view', iid=inv.id))


# ==================================================== vehicle / driver CRUD
register('vehicles', Ambulance, 'Ambulances',
         columns=[('Unit', lambda o: f"<b>{h(o.label)}</b>"),
                  ('Plate', lambda o: h(o.plate or '—')),
                  ('Type', lambda o: pill(o.kind or '—', 'grey')),
                  ('Status', lambda o: pill(o.status or 'Available',
                                            'green' if o.status == 'Available' else ('amber' if o.status == 'OnTrip' else 'grey')))],
         fields=[dict(name='label', label='Unit Name (e.g. Ambulance 1)', required=True),
                 dict(name='plate', label='Plate Number'),
                 dict(name='kind', label='Type', type='select',
                      options=[(k, k) for k in ('BLS', 'ALS', 'Patient transport')]),
                 dict(name='status', label='Status', type='select',
                      options=[(s, s) for s in ('Available', 'OnTrip', 'Maintenance')]),
                 dict(name='active', label='Active', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: Ambulance.query.order_by(Ambulance.label), search=['label', 'plate'])

register('drivers_amb', AmbulanceDriver, 'Ambulance Drivers',
         columns=[('Name', lambda o: f"<b>{h(o.name)}</b>"),
                  ('Phone', lambda o: h(o.phone or '—')),
                  ('License', lambda o: h(o.license_no or '—')),
                  ('Status', lambda o: pill('Active' if o.active in (True, None) else 'Inactive',
                                            'green' if o.active in (True, None) else 'grey'))],
         fields=[dict(name='name', label='Driver Name', required=True),
                 dict(name='phone', label='Phone'),
                 dict(name='license_no', label='License Number'),
                 dict(name='active', label='Status', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: AmbulanceDriver.query.order_by(AmbulanceDriver.name), search=['name', 'phone'])
