"""LIS — Laboratory Information System / instrument integration  (Phase 4, v8.0).

Adds a structured-result layer over the existing lab module: HL7/analyzer result
import matched to barcoded samples, manual verification & release, critical-value
alerts, sample tracking and barcode labels. Reuses the existing QC module
(labqc) and LabParam reference ranges.
"""
import csv
import io
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort,
                   render_template, Response)
from markupsafe import escape as h
from ..extensions import db
from ..models import (LabOrder, LabParam, LabResultValue, LabInstrument)
from ..core.security import (cur_user, can, login_required, log, setting,
                             branch_scope, can_see)
from ..core.helpers import today
from ..core.ui import page, public_shell
from ..core.crud import register, pill
from ..core.notify import notify
from ..core import hl7 as hl7mod
from ..core.barcodes import code128_svg

bp = Blueprint('lis', __name__)


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


def _num(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None


def _parse_ref(ref):
    """'4.0-11.0' -> (4.0, 11.0); tolerant of blanks/one-sided ranges."""
    if not ref:
        return None, None
    r = ref.replace('–', '-')
    for sep in ('-', ' to '):
        if sep in r:
            a, _, b = r.partition(sep)
            return _num(a), _num(b)
    return None, None


def _evaluate(order, name, value, ref, analyzer_flag):
    """Return (flag, ref_low, ref_high, is_critical) for one analyte."""
    lo, hi = _parse_ref(ref)
    param = None
    if order and order.service_id:
        param = LabParam.query.filter_by(service_id=order.service_id).filter(
            LabParam.name.ilike(name)).first()
    if lo is None and param:
        lo = param.low
    if hi is None and param:
        hi = param.high
    val = _num(value)
    flag = ''
    critical = False
    af = (analyzer_flag or '').upper()
    # analyzer-declared criticality takes precedence and sets the flag
    if 'LL' in af:
        flag, critical = 'LL', True
    elif 'HH' in af:
        flag, critical = 'HH', True
    elif any(x in af for x in ('CC', 'C*', '*', 'PANIC')):
        critical = True
    if not flag and val is not None:
        if hi is not None and val > hi:
            flag = 'H'
        elif lo is not None and val < lo:
            flag = 'L'
    # critical thresholds from the Service (panic_low/high) override to HH/LL
    if val is not None:
        svc = order.service if order else None
        if svc is not None:
            if svc.panic_high is not None and val >= svc.panic_high:
                flag, critical = 'HH', True
            if svc.panic_low is not None and val <= svc.panic_low:
                flag, critical = 'LL', True
    if not flag and af in ('H', 'L', 'A'):
        flag = af
    return flag, lo, hi, critical


def _flag_pill(flag):
    if flag in ('HH', 'LL'):
        return f"<span class='pill red'>{h(flag)} ⚠</span>"
    if flag in ('H', 'L', 'A'):
        return f"<span class='pill amber'>{h(flag)}</span>"
    return "<span class='pill green'>N</span>"


# ==================================================================== dashboard
def lis_dashboard():
    """LIS worklist — App Launcher (mod='lis')."""
    orders = branch_scope(LabOrder.query, LabOrder).order_by(LabOrder.id.desc()).limit(400).all()
    awaiting_verify = [o for o in orders if o.values and any(not v.verified for v in o.values)]
    critical = [o for o in orders if o.panic and not o.panic_ack]
    in_lab = [o for o in orders if o.status in ('Collected', 'Received')]

    def card(n, label, color, link):
        return (f"<a href='{link}' style='text-decoration:none'>"
                f"<div class='panel' style='display:inline-block;min-width:150px;margin:4px'><div class='pad'>"
                f"<div style='font-size:22px;font-weight:700;color:{color}'>{n}</div>"
                f"<div style='font-size:12px;color:var(--muted)'>{label}</div></div></div></a>")
    cards = (card(len(critical), 'Critical alerts', 'var(--red)', url_for('lis.critical'))
             + card(len(awaiting_verify), 'Awaiting verification', 'var(--amber-dk)', '#verify')
             + card(len(in_lab), 'In lab (samples)', 'var(--blue)', url_for('lis.samples')))

    rows = []
    for o in awaiting_verify[:100]:
        rows.append([
            h(o.sample_no or f'#{o.id}'),
            h(o.patient.name if o.patient else '—'),
            h(o.service.name if o.service else '—'),
            f"{sum(1 for v in o.values if v.verified)}/{len(o.values)} verified",
            ("<span class='pill red'>CRITICAL</span>" if o.panic else ''),
            f"<a class='btn sm primary' href='{url_for('lis.verify', oid=o.id)}'>Verify</a>",
        ])
    toolbar = (f"<a class='btn' href='{url_for('modules.module', mod='instruments')}'>🔬 Instruments</a> "
               f"<a class='btn' href='{url_for('modules.module', mod='labqc')}'>📊 QC</a> "
               f"<a class='btn' href='{url_for('lis.samples')}'>🧫 Samples</a> "
               f"<a class='btn primary' href='{url_for('lis.import_results')}'>⬇ Import Results</a>")
    body = render_template(
        'list_page.html', title='LIS · Laboratory', prefix=f"<div id='verify' style='margin-bottom:8px'>{cards}</div>",
        toolbar=toolbar, headers=['Sample', 'Patient', 'Test', 'Progress', '', ''],
        aligns=['', '', '', '', '', 'num'], rows=rows,
        empty="<div class='empty'><b>Nothing awaiting verification</b>Import analyzer results to begin.</div>")
    return page('LIS', body, 'lis')


# ============================================================ analyzer import
def _apply_results(order, results, source, instrument_id=None):
    """Create/refresh LabResultValue rows on an order; returns (n, critical)."""
    any_critical = False
    # clear previous unverified values from the same source to avoid duplicates
    for v in list(order.values):
        if v.source == source and not v.verified:
            db.session.delete(v)
    for r in results:
        flag, lo, hi, crit = _evaluate(order, r['name'], r.get('value'), r.get('ref'), r.get('flag'))
        any_critical = any_critical or crit
        db.session.add(LabResultValue(
            order_id=order.id, name=r['name'][:80], value=(r.get('value') or '')[:40],
            unit=(r.get('unit') or '')[:20], ref_low=lo, ref_high=hi,
            ref_text=(r.get('ref') or '')[:40], flag=flag, source=source,
            instrument_id=instrument_id, verified=False))
    if order.status in ('Requested', 'Collected'):
        order.status = 'Received'
    if any_critical:
        order.panic = True
        order.panic_ack = False
    return len(results), any_critical


def _match_order(sample_id):
    if not sample_id:
        return None
    return branch_scope(LabOrder.query, LabOrder).filter(
        LabOrder.sample_no == sample_id).order_by(LabOrder.id.desc()).first()


@bp.route('/lis/import', methods=['GET', 'POST'])
@login_required
def import_results():
    if not can('lis'):
        abort(403)
    if request.method == 'POST':
        raw = (request.form.get('payload') or '').strip()
        up = request.files.get('file')
        if up and up.filename:
            raw = up.read().decode('utf-8', 'replace').strip()
        fmt = request.form.get('fmt') or 'hl7'
        matched, unmatched, crit_orders = 0, [], 0
        if fmt == 'hl7':
            parsed = hl7mod.parse_oru(raw)
            if not parsed:
                flash('Not a valid HL7 ORU message', 'error')
                return redirect(url_for('lis.import_results'))
            order = _match_order(parsed['sample_id'])
            if not order:
                unmatched.append(parsed['sample_id'] or '(no sample id)')
            else:
                n, crit = _apply_results(order, parsed['results'], 'Analyzer')
                matched += 1
                crit_orders += 1 if crit else 0
                if crit:
                    notify(f'CRITICAL lab value — sample {order.sample_no}',
                           url_for('lis.verify', oid=order.id), role=['lab_tech', 'doctor', 'reception'])
        else:  # CSV: sample_no,test,value,unit,ref,flag
            reader = csv.reader(io.StringIO(raw))
            groups = {}
            for row in reader:
                if len(row) < 3 or row[0].lower().strip() in ('sample', 'sample_no'):
                    continue
                sid = row[0].strip()
                groups.setdefault(sid, []).append({
                    'name': row[1].strip(), 'value': row[2].strip(),
                    'unit': row[3].strip() if len(row) > 3 else '',
                    'ref': row[4].strip() if len(row) > 4 else '',
                    'flag': row[5].strip() if len(row) > 5 else ''})
            for sid, results in groups.items():
                order = _match_order(sid)
                if not order:
                    unmatched.append(sid)
                    continue
                n, crit = _apply_results(order, results, 'Analyzer')
                matched += 1
                crit_orders += 1 if crit else 0
                if crit:
                    notify(f'CRITICAL lab value — sample {order.sample_no}',
                           url_for('lis.verify', oid=order.id), role=['lab_tech', 'doctor', 'reception'])
        db.session.commit()
        log(f'LIS import: {matched} matched, {len(unmatched)} unmatched, {crit_orders} critical',
            entity='LIS')
        msg = f'Imported results for {matched} sample(s).'
        if crit_orders:
            msg += f' ⚠ {crit_orders} with CRITICAL values.'
        if unmatched:
            msg += f' Unmatched samples: {", ".join(h(u) for u in unmatched[:10])}.'
        flash(msg, 'ok' if matched else 'error')
        return redirect(url_for('modules.module', mod='lis'))

    sample_hint = ''
    example = ("MSH|^~\\&|SYSMEX|LAB|LIS|MDC|20260201090000||ORU^R01|MSG001|P|2.3.1\n"
               "PID|1||MRN123||DOE^JOHN\n"
               "OBR|1|ORD1|SMP-00001|CBC^Complete Blood Count\n"
               "OBX|1|NM|WBC^White Blood Cell||7.2|x10^9/L|4.0-11.0|N|||F\n"
               "OBX|2|NM|HGB^Hemoglobin||6.5|g/dL|13.0-17.0|LL|||F")
    inner = f"""
    <div class='panel'><div class='pad'>
      <form method='post' enctype='multipart/form-data'>
        <div class='fld'><label>Format</label>
          <select name='fmt'><option value='hl7'>HL7 ORU (analyzer)</option>
          <option value='csv'>CSV (sample_no,test,value,unit,ref,flag)</option></select></div>
        <div class='fld full'><label>Paste message / data</label>
          <textarea name='payload' rows='9' style='font-family:monospace;font-size:12px' placeholder="{h(example)}"></textarea></div>
        <div class='fld full'><label>…or upload a file</label><input type='file' name='file' accept='.hl7,.txt,.csv'></div>
        <div class='fld full'><button class='btn primary'>Import &amp; match to samples</button>
          <a class='btn gh' href="{url_for('modules.module', mod='lis')}">Cancel</a></div>
      </form>
      <div style='font-size:12px;color:var(--muted);margin-top:6px'>
        Results are matched to open lab orders by <b>sample barcode</b> (OBR-3 / first CSV column).
        Critical values raise an alert automatically. Imported values are unverified until released.</div>
    </div></div>"""
    return page('Import Results', inner, 'lis')


# --------- analyzer/middleware endpoint (CSRF-exempt via /api prefix) ---------
@bp.route('/api/lis/hl7', methods=['POST'])
def api_hl7():
    """Receive an HL7 ORU from an analyzer/middleware. Auth: shared token in the
    'X-LIS-Token' header (or ?token=) matched against setting 'lis_hl7_token'."""
    token = setting('lis_hl7_token', '')
    sent = request.headers.get('X-LIS-Token') or request.args.get('token') or ''
    if not token or sent != token:
        return Response(hl7mod.build_ack('', 'AR', 'auth'), status=401, mimetype='text/plain')
    raw = request.get_data(as_text=True) or ''
    parsed = hl7mod.parse_oru(raw)
    if not parsed:
        return Response(hl7mod.build_ack('', 'AE', 'not ORU'), status=400, mimetype='text/plain')
    order = _match_order(parsed['sample_id'])
    if not order:
        return Response(hl7mod.build_ack(parsed['msg_id'], 'AE', 'sample not found'),
                        status=404, mimetype='text/plain')
    n, crit = _apply_results(order, parsed['results'], 'Analyzer')
    db.session.commit()
    log(f'LIS HL7 API: sample {order.sample_no}, {n} results{" CRITICAL" if crit else ""}', entity='LIS')
    if crit:
        notify(f'CRITICAL lab value — sample {order.sample_no}',
               url_for('lis.verify', oid=order.id), role=['lab_tech', 'doctor', 'reception'])
    return Response(hl7mod.build_ack(parsed['msg_id'], 'AA'), mimetype='text/plain')


# ==================================================================== verify
@bp.route('/lis/order/<int:oid>/verify', methods=['GET', 'POST'])
@login_required
def verify(oid):
    if not can('lis'):
        abort(403)
    o = LabOrder.query.get_or_404(oid)
    if not can_see(o):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        for v in o.values:
            newval = request.form.get(f'val_{v.id}')
            if newval is not None and newval != v.value:
                v.value = newval[:40]
                v.flag, v.ref_low, v.ref_high, _crit = _evaluate(o, v.name, v.value, v.ref_text, '')
                if v.source == 'Manual':
                    v.source = 'Manual'
            v.verified = True
            v.verified_by = (u.username if u else None)
        # recompute panic from verified values
        o.panic = any(vv.flag in ('HH', 'LL') for vv in o.values)
        # write a human summary into the existing free-text result (keeps lab print working)
        lines = [f"{vv.name}: {vv.value} {vv.unit or ''}".strip()
                 + (f"  [{vv.flag}]" if vv.flag and vv.flag != 'N' else '')
                 + (f"  (ref {vv.ref_text})" if vv.ref_text else '') for vv in o.values]
        o.result = "\n".join(lines)
        o.result_by = (u.username if u else None)
        if o.status in ('Requested', 'Collected', 'Received'):
            o.status = 'Resulted'
        db.session.commit()
        log(f'LIS #{oid} results verified & released', entity=f'LabOrder#{oid}')
        flash('Results verified and released', 'ok')
        return redirect(url_for('modules.module', mod='lis'))

    if not o.values:
        return page('Verify', "<div class='panel'><div class='pad'>No structured results on this order yet. "
                    f"<a href='{url_for('lis.import_results')}'>Import analyzer results</a>.</div></div>", 'lis')
    vrows = ''
    for v in o.values:
        ref = v.ref_text or (f"{v.ref_low}-{v.ref_high}" if (v.ref_low is not None or v.ref_high is not None) else '—')
        vrows += (f"<tr><td>{h(v.name)}</td>"
                  f"<td><input name='val_{v.id}' value=\"{h(v.value or '')}\" style='width:90px'></td>"
                  f"<td>{h(v.unit or '')}</td><td style='color:var(--muted)'>{h(ref)}</td>"
                  f"<td>{_flag_pill(v.flag)}</td>"
                  f"<td><span class='pill {'teal' if v.source=='Analyzer' else 'grey'}'>{h(v.source)}</span></td></tr>")
    crit_banner = ("<div class='panel' style='border-left:3px solid var(--red)'><div class='pad'>"
                   "⚠ <b>Critical value present.</b> Notify the clinician before releasing.</div></div>"
                   if o.panic else '')
    inner = f"""
    {crit_banner}
    <div class='panel'><div class='pad'>
      <b>{h(o.patient.name if o.patient else '')}</b> · {h(o.service.name if o.service else '')} · sample {h(o.sample_no or '—')}
      <form method='post'>
        <table class='tbl' style='margin-top:10px;width:100%'>
          <thead><tr><th>Analyte</th><th>Value</th><th>Unit</th><th>Reference</th><th>Flag</th><th>Source</th></tr></thead>
          <tbody>{vrows}</tbody>
        </table>
        <div style='margin-top:12px'><button class='btn primary'>✓ Verify &amp; release</button>
          <a class='btn gh' href="{url_for('modules.module', mod='lis')}">Cancel</a></div>
      </form>
    </div></div>"""
    return page('Verify Results', inner, 'lis',
                crumbs=[('LIS', url_for('modules.module', mod='lis')), (f'Sample {o.sample_no or o.id}', None)])


# ============================================================ critical alerts
@bp.route('/lis/critical')
@login_required
def critical():
    if not can('lis'):
        abort(403)
    orders = [o for o in branch_scope(LabOrder.query, LabOrder).order_by(LabOrder.id.desc()).all()
              if o.panic and not o.panic_ack]
    rows = []
    for o in orders:
        crit_vals = ', '.join(f"{v.name} {v.value}" for v in o.values if v.flag in ('HH', 'LL'))
        rows.append([
            h(o.sample_no or f'#{o.id}'),
            h(o.patient.name if o.patient else '—'),
            h(o.service.name if o.service else '—'),
            f"<span class='pill red'>{h(crit_vals or 'critical')}</span>",
            (f"<a class='btn sm' href='{url_for('lis.verify', oid=o.id)}'>Review</a> "
             f"<a class='btn sm primary' href='{url_for('lis.ack', oid=o.id)}'>Acknowledge</a>"),
        ])
    body = render_template(
        'list_page.html', title='Critical Value Alerts',
        headers=['Sample', 'Patient', 'Test', 'Critical', ''],
        aligns=['', '', '', '', 'num'], rows=rows,
        empty="<div class='empty'><b>No unacknowledged critical alerts</b> 🎉</div>")
    return page('Critical Alerts', body, 'lis',
                crumbs=[('LIS', url_for('modules.module', mod='lis')), ('Critical', None)])


@bp.route('/lis/order/<int:oid>/ack')
@login_required
def ack(oid):
    if not can('lis'):
        abort(403)
    o = LabOrder.query.get_or_404(oid)
    if not can_see(o):
        abort(403)
    o.panic_ack = True
    db.session.commit()
    log(f'LIS #{oid} critical alert acknowledged', entity=f'LabOrder#{oid}')
    flash('Critical alert acknowledged', 'ok')
    return redirect(url_for('lis.critical'))


# ============================================================ sample tracking
@bp.route('/lis/samples')
@login_required
def samples():
    if not can('lis'):
        abort(403)
    orders = branch_scope(LabOrder.query, LabOrder).filter(
        LabOrder.status.in_(['Requested', 'Collected', 'Received', 'Resulted'])
    ).order_by(LabOrder.id.desc()).limit(300).all()
    colors = {'Requested': 'grey', 'Collected': 'blue', 'Received': 'amber', 'Resulted': 'teal'}
    rows = []
    for o in orders:
        rows.append([
            h(o.sample_no or '—'),
            h(o.patient.name if o.patient else '—'),
            h(o.service.name if o.service else '—'),
            h(o.specimen or '—'),
            f"<span class='pill {colors.get(o.status,'grey')}'>{h(o.status)}</span>",
            h(o.collected_at or '—'),
            (f"<a class='btn gh sm' href='{url_for('lis.label', oid=o.id)}' target='_blank'>🏷 Label</a>"
             if o.sample_no else ''),
        ])
    body = render_template(
        'list_page.html', title='Sample Tracking',
        headers=['Sample', 'Patient', 'Test', 'Specimen', 'Status', 'Collected', ''],
        aligns=['', '', '', '', '', '', 'num'], rows=rows,
        empty="<div class='empty'><b>No active samples</b></div>")
    return page('Samples', body, 'lis',
                crumbs=[('LIS', url_for('modules.module', mod='lis')), ('Samples', None)])


@bp.route('/lis/order/<int:oid>/label')
@login_required
def label(oid):
    if not can('lis'):
        abort(403)
    o = LabOrder.query.get_or_404(oid)
    if not can_see(o):
        abort(403)
    bc = code128_svg(o.sample_no or f'LAB{o.id}')
    inner = f"""
    <div style='width:60mm;padding:4mm;border:1px solid #000;font-family:sans-serif'>
      <div style='font-weight:700;font-size:13px'>{h(o.patient.name if o.patient else '')}</div>
      <div style='font-size:11px'>{h(o.service.name if o.service else '')} · {h(o.specimen or '')}</div>
      <div style='margin:4px 0'>{bc}</div>
      <div style='font-size:12px;letter-spacing:1px'>{h(o.sample_no or '')}</div>
      <div style='font-size:10px;color:#555'>{h(o.date or today())}</div>
    </div>
    <script>window.onload=function(){{window.print()}}</script>"""
    return public_shell(f'Label {o.sample_no}', inner)


# =================================================== instrument registry (REG)
register('instruments', LabInstrument, 'Lab Instruments',
         columns=[('Name', lambda o: f"<b>{h(o.name)}</b>"),
                  ('Code', lambda o: h(o.code or '—')),
                  ('Type', lambda o: pill(o.kind or '—', 'grey')),
                  ('Connection', lambda o: h(o.connection or '—')),
                  ('Status', lambda o: pill('Active' if o.active in (True, None) else 'Inactive',
                                            'green' if o.active in (True, None) else 'grey'))],
         fields=[dict(name='name', label='Instrument Name', required=True),
                 dict(name='code', label='Code (HL7 sending app)'),
                 dict(name='kind', label='Type', type='select',
                      options=[(k, k) for k in ('Hematology', 'Chemistry', 'Immunoassay',
                                                'Coagulation', 'Urinalysis', 'Microbiology', 'Other')]),
                 dict(name='connection', label='Connection (host:port / serial)'),
                 dict(name='active', label='Status', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: LabInstrument.query.order_by(LabInstrument.name),
         search=['name', 'code', 'kind'])
