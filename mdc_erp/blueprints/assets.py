"""Assets & Maintenance overview: KPIs, calibration/warranty alerts, open jobs."""
import datetime as dt
from flask import Blueprint, url_for
from markupsafe import escape as h
from ..models import Asset, MaintenanceJob
from ..core.helpers import money, today
from ..core.ui import page
from ..core.crud import pill, expiry_pill

bp = Blueprint('assets', __name__)


def _days_until(iso):
    try:
        return (dt.date.fromisoformat(iso) - dt.date.today()).days
    except (TypeError, ValueError):
        return None


def maintdash_view():
    assets = Asset.query.all()
    jobs = MaintenanceJob.query.all()
    active = [a for a in assets if a.status != 'Retired']
    repair = [a for a in assets if a.status == 'Under Repair']
    open_jobs = [j for j in jobs if j.status != 'Done']
    cal_due = sorted([a for a in active if (d := _days_until(a.calibration_due)) is not None and d <= 30],
                     key=lambda a: a.calibration_due or '')
    war_exp = sorted([a for a in active if (d := _days_until(a.warranty_expiry)) is not None and d <= 60],
                     key=lambda a: a.warranty_expiry or '')
    from ..models import SvcContract
    sc_exp = sorted([c for c in SvcContract.query.all()
                     if (d := _days_until(c.end)) is not None and d <= 60],
                    key=lambda c: c.end or '')
    total_cost = sum(a.cost or 0 for a in active)
    total_book = sum(a.book_value for a in active)
    maint_cost = sum((j.parts_cost or 0) + (j.labor_cost or 0) for j in jobs
                     if (j.date or '').startswith(str(dt.date.today().year)))

    def kpi(label, value, sub, ac):
        return (f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div>"
                f"<div class='v'>{value}</div><div class='s'>{sub}</div></div>")

    kpis = ('<div class="kpis">'
            + kpi('Assets', len(active), f'{len(repair)} under repair', 'var(--teal)')
            + kpi('Book Value', money(total_book), f'cost {money(total_cost)}', 'var(--blue)')
            + kpi('Calibration ≤ 30d', len(cal_due), 'needs scheduling', 'var(--amber)')
            + kpi('Open Jobs', len(open_jobs), f'{money(maint_cost)} maint. cost this year', 'var(--red)')
            + '</div>')

    def asset_rows(items, date_attr):
        rows = ''
        for a in items:
            rows += (f"<tr><td><b>{h(a.code or '')}</b></td><td>{h(a.name)}</td>"
                     f"<td>{pill(a.category or '—', 'grey')}</td>"
                     f"<td>{expiry_pill(getattr(a, date_attr))}</td>"
                     f"<td class='num'><a class='btn gh sm' href='{url_for('modules.module_edit', mod='assets', oid=a.id)}'>Open</a></td></tr>")
        return rows or "<tr><td colspan='5'><div class='empty'><b>Nothing due</b>All clear.</div></td></tr>"

    job_rows = ''
    for j in sorted(open_jobs, key=lambda x: (x.status != 'Open', x.date or '')):
        job_rows += (f"<tr><td>{h(j.date)}</td>"
                     f"<td>{h(f'{j.asset.code} · {j.asset.name}' if j.asset else '—')}</td>"
                     f"<td>{pill(j.type, {'Preventive': 'blue', 'Corrective': 'amber'})}</td>"
                     f"<td>{h(j.engineer or '—')}</td>"
                     f"<td>{pill(j.status, {'Open': 'red', 'In Progress': 'amber'})}</td>"
                     f"<td class='num'>"
                     f"<a class='btn sm ok' href='{url_for('assets.job_done', jid=j.id)}'>Mark Done</a> "
                     f"<a class='btn gh sm' href='{url_for('modules.module_edit', mod='maintenance', oid=j.id)}'>Edit</a>"
                     f"</td></tr>")
    if not job_rows:
        job_rows = ("<tr><td colspan='6'><div class='empty'><b>No open jobs</b>"
                    f"<a href='{url_for('modules.module_new', mod='maintenance')}' "
                    "style='color:var(--amber-dk);font-weight:600'>Create a work order →</a></div></td></tr>")

    body = kpis + f"""
      <div class="panel"><div class="ph"><h2>Open Maintenance Jobs</h2><div class="sp"></div>
        <a class="btn primary" href="{url_for('modules.module_new', mod='maintenance')}">+ Work Order</a></div>
        <div class="tw"><table><thead><tr><th>Date</th><th>Asset</th><th>Type</th><th>Engineer</th><th>Status</th><th></th></tr></thead>
        <tbody>{job_rows}</tbody></table></div></div>
      <div class="grid2">
      <div class="panel"><div class="ph"><h2>Calibration Due (30 days)</h2></div>
        <div class="tw"><table><thead><tr><th>Code</th><th>Asset</th><th>Category</th><th>Due</th><th></th></tr></thead>
        <tbody>{asset_rows(cal_due, 'calibration_due')}</tbody></table></div></div>
      <div class="panel"><div class="ph"><h2>Warranty Expiring (60 days)</h2></div>
        <div class="tw"><table><thead><tr><th>Code</th><th>Asset</th><th>Category</th><th>Expiry</th><th></th></tr></thead>
        <tbody>{asset_rows(war_exp, 'warranty_expiry')}</tbody></table></div></div>
      </div>
      <div class="panel"><div class="ph"><h2>Service Contracts Ending (60 days)</h2><div class="sp"></div><a class="btn sm" href="/m/svccontracts">All contracts</a></div>
        <div class="tw"><table><thead><tr><th>Asset</th><th>Vendor</th><th>Phone</th><th>Ends</th></tr></thead>
        <tbody>{''.join(f"<tr><td>{h(c.asset.name if c.asset else '—')}</td><td>{h(c.vendor or '—')}</td><td>{h(c.phone or '—')}</td><td><span class='pill amber'>{h(c.end)}</span></td></tr>" for c in sc_exp) or "<tr><td colspan='4' style='color:var(--muted);padding:12px'>None ending soon.</td></tr>"}</tbody></table></div></div>"""
    return page('Assets & Maintenance', body, 'maintdash')


@bp.route('/maintenance/<int:jid>/done')
def job_done(jid):
    from flask import redirect, flash, abort
    from ..extensions import db
    from ..core.security import cur_user, can, log
    if not cur_user() or not can('maintenance'):
        abort(403)
    j = MaintenanceJob.query.get_or_404(jid)
    j.status = 'Done'
    j.completed = today()
    if j.asset and j.asset.status == 'Under Repair':
        j.asset.status = 'Active'
    db.session.commit()
    log(f'Maintenance job #{jid} completed')
    flash('Job completed')
    return redirect(url_for('modules.module', mod='maintdash'))
