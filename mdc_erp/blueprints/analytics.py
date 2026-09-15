"""Advanced Analytics Dashboard  (Phase 13, v8.0).

A read-only, hospital-wide executive overview that aggregates KPIs across every
module — clinical (ED, IPD, OT, dialysis, ambulance, blood bank, lab, imaging)
and financial (revenue, receivables, insurance) — with dependency-free inline
SVG charts (offline-friendly, no external chart libraries). No new tables.
"""
import datetime as dt
from flask import Blueprint
from markupsafe import escape as h
from sqlalchemy.orm import selectinload
from ..models import (Patient, Invoice, LabOrder, RadOrder, EDVisit, Admission, Bed,
                      Surgery, DialysisSession, Dispatch, BloodUnit, Claim)
from ..core.security import log, branch_scope
from ..core.helpers import money, today
from ..core.ui import page

bp = Blueprint('analytics', __name__)


def _d(s):
    """First 10 chars (YYYY-MM-DD) of a date/datetime string or object."""
    if not s:
        return ''
    return str(s)[:10]


def _bar_chart(labels, values, color='var(--petrol)', fmt=str, height=120):
    """Dependency-free inline SVG bar chart."""
    if not values:
        return ''
    mx = max(values) or 1
    n = len(values)
    bw = 100.0 / n
    bars = ''
    for i, v in enumerate(values):
        bh = (v / mx) * (height - 24) if mx else 0
        x = i * bw
        y = height - bh - 16
        bars += (f"<rect x='{x + bw*0.15:.2f}' y='{y:.2f}' width='{bw*0.7:.2f}' height='{bh:.2f}' "
                 f"rx='1.5' fill='{color}'></rect>"
                 f"<text x='{x + bw*0.5:.2f}' y='{height-4:.2f}' font-size='3.2' text-anchor='middle' fill='var(--muted)'>{h(labels[i])}</text>"
                 f"<text x='{x + bw*0.5:.2f}' y='{y-1.5:.2f}' font-size='3' text-anchor='middle' fill='var(--ink)'>{h(fmt(v))}</text>")
    return (f"<svg viewBox='0 0 100 {height}' preserveAspectRatio='none' "
            f"style='width:100%;height:{height}px'>{bars}</svg>")


def analytics_board():
    """Executive analytics — App Launcher (mod='analytics')."""
    t = today()
    month = t[:7]
    days = [(dt.date.today() - dt.timedelta(days=i)) for i in range(6, -1, -1)]
    day_iso = [d.isoformat() for d in days]
    day_lbl = [d.strftime('%a') for d in days]

    # ---- financial (reuse the dashboard's invoice-walk pattern) ----
    inv = branch_scope(Invoice.query, Invoice).options(selectinload(Invoice.items)).all()
    tot = {i.id: i.total for i in inv}
    receivable = sum(tot[i.id] - (i.paid or 0) for i in inv)
    collected_today = sum((i.paid or 0) for i in inv if _d(i.date) == t)
    collected_month = sum((i.paid or 0) for i in inv if _d(i.date).startswith(month))
    billed_month = sum(tot[i.id] for i in inv if _d(i.date).startswith(month))
    collect_series = [sum((i.paid or 0) for i in inv if _d(i.date) == d) for d in day_iso]

    # insurance outstanding (approved but not paid)
    claims = branch_scope(Claim.query, Claim).all() if hasattr(Claim, 'query') else []
    ins_out = 0
    for c in claims:
        if (getattr(c, 'status', '') or '') not in ('Paid', 'Rejected', 'Draft'):
            ins_out += max((getattr(c, 'approved', 0) or 0) - (getattr(c, 'paid', 0) or 0), 0)

    # ---- clinical volumes ----
    pts = branch_scope(Patient.query, Patient).all()
    pt_today = sum(1 for p in pts if _d(p.created) == t)
    pt_series = [sum(1 for p in pts if _d(p.created) == d) for d in day_iso]

    ed = branch_scope(EDVisit.query, EDVisit).all()
    ed_active = sum(1 for v in ed if v.status in ('Waiting', 'InTreatment', 'Observation'))
    ed_today = sum(1 for v in ed if _d(v.arrival_at) == t)

    adm = branch_scope(Admission.query, Admission).all()
    inpatients = sum(1 for a in adm if a.status == 'Admitted')
    beds = branch_scope(Bed.query.filter_by(active=True), Bed).all()
    free_beds = sum(1 for b in beds if b.status == 'Available')
    occ_pct = round(100 * sum(1 for b in beds if b.status == 'Occupied') / len(beds)) if beds else 0

    surg = branch_scope(Surgery.query, Surgery).all()
    surg_today = sum(1 for s in surg if _d(s.scheduled_at) == t)
    surg_upcoming = sum(1 for s in surg if s.status == 'Scheduled')

    dia = branch_scope(DialysisSession.query, DialysisSession).all()
    dia_today = sum(1 for s in dia if _d(s.scheduled_at) == t or _d(s.started_at) == t)

    disp = branch_scope(Dispatch.query, Dispatch).all()
    amb_active = sum(1 for d in disp if d.status not in ('Completed', 'Cancelled'))

    units = branch_scope(BloodUnit.query, BloodUnit).all()
    blood_avail = sum(1 for u in units if u.status == 'Available')

    labs = branch_scope(LabOrder.query, LabOrder).all()
    lab_today = sum(1 for o in labs if _d(o.date) == t)
    lab_pending = sum(1 for o in labs if o.status in ('Pending', 'Collected', 'InProgress'))
    lab_series = [sum(1 for o in labs if _d(o.date) == d) for d in day_iso]

    rads = branch_scope(RadOrder.query, RadOrder).all()
    rad_today = sum(1 for o in rads if _d(o.date) == t)
    rad_series = [sum(1 for o in rads if _d(o.date) == d) for d in day_iso]

    # ---- render ----
    def kpi(label, val, ac, sub=''):
        return (f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div>"
                f"<div class='v'>{val}</div><div class='s'>{sub}</div></div>")

    fin = ("<div class='kpis'>"
           + kpi('Collected today', money(collected_today), 'var(--green)', 'cash in')
           + kpi('Collected (month)', money(collected_month), 'var(--green)', month)
           + kpi('Billed (month)', money(billed_month), 'var(--blue)', month)
           + kpi('Receivable', money(receivable), 'var(--amber-dk)', 'outstanding')
           + kpi('Insurance due', money(ins_out), 'var(--petrol)', 'claims') + "</div>")

    clin = ("<div class='kpis'>"
            + kpi('Patients today', pt_today, 'var(--blue)', f'{len(pts)} total')
            + kpi('ED active', ed_active, 'var(--red)', f'{ed_today} today')
            + kpi('Inpatients', inpatients, 'var(--petrol)', f'{free_beds} free beds')
            + kpi('Bed occupancy', f'{occ_pct}%', 'var(--amber-dk)', f'{len(beds)} beds')
            + kpi('Surgeries today', surg_today, 'var(--blue)', f'{surg_upcoming} scheduled')
            + kpi('Dialysis today', dia_today, 'var(--teal)', 'sessions')
            + kpi('Ambulance active', amb_active, 'var(--amber-dk)', 'dispatches')
            + kpi('Blood units', blood_avail, 'var(--red)', 'available')
            + kpi('Lab orders today', lab_today, 'var(--teal)', f'{lab_pending} pending')
            + kpi('Imaging today', rad_today, 'var(--petrol)', 'orders') + "</div>")

    def chart_panel(title, labels, series, color, fmt=str):
        return (f"<div class='panel' style='display:inline-block;width:calc(50% - 6px);vertical-align:top'>"
                f"<div class='ph'><h2>{h(title)}</h2></div><div class='pad'>{_bar_chart(labels, series, color, fmt)}</div></div>")

    charts = ("<div style='display:flex;gap:12px;flex-wrap:wrap'>"
              + chart_panel('Cash collected · 7 days', day_lbl, collect_series, 'var(--green)', lambda v: money(v))
              + chart_panel('New patients · 7 days', day_lbl, pt_series, 'var(--blue)')
              + chart_panel('Lab orders · 7 days', day_lbl, lab_series, 'var(--teal)')
              + chart_panel('Imaging orders · 7 days', day_lbl, rad_series, 'var(--petrol)')
              + "</div>")

    body = (f"<div class='panel'><div class='pad' style='color:var(--muted);font-size:13px'>"
            f"Hospital-wide overview · {h(today())} · read-only</div></div>"
            f"<h2 style='margin:14px 0 4px'>Financial</h2>{fin}"
            f"<h2 style='margin:14px 0 4px'>Clinical & Operational</h2>{clin}"
            f"<h2 style='margin:14px 0 4px'>Trends</h2>{charts}")
    log('Viewed analytics dashboard', action_type='view', entity='Analytics')
    return page('Analytics', body, 'analytics')
