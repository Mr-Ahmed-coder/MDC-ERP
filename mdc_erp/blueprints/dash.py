"""Main dashboard KPIs and global search."""
from flask import (Blueprint, request, redirect, url_for)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.security import (cur_user, can, login_required, ROLE_LABEL)
from ..core.helpers import money, today, cur_year
from ..core.ui import page, plink, pnamelink

bp = Blueprint('dash', __name__)

@bp.route('/')
@bp.route('/dashboard')
@login_required
def dashboard():
    y = cur_year(); today_s = today()
    # Invoice.total recomputes from line items on every access, so walking the
    # invoice list four times cost ~10s at 12k invoices. Load the items once and
    # compute each total once, then reuse.
    from sqlalchemy.orm import selectinload
    inv = Invoice.query.options(selectinload(Invoice.items), selectinload(Invoice.doctor_ref)).all()
    _tot = {i.id: i.total for i in inv}
    rev_today = sum(_tot[i.id] for i in inv if i.date == today_s)
    rev_year = sum(_tot[i.id] for i in inv if (i.date or '').startswith(str(y)))
    commission_year = sum(i.commission for i in inv if (i.date or '').startswith(str(y)))
    receivable = sum(_tot[i.id] - (i.paid or 0) for i in inv)
    cash_today = sum((i.paid or 0) for i in inv if i.date == today_s)
    n_pat = Patient.query.count()
    pat_today = Patient.query.filter(db.func.date(Patient.created) == today_s).count() if hasattr(Patient, 'created') else 0
    waiting = Appointment.query.filter_by(status='Waiting').count()
    pending_lab = LabOrder.query.filter(LabOrder.status.in_(['Requested','Collected','Received','Resulted'])).count()
    pending_rad = RadOrder.query.filter(RadOrder.status.in_(['Requested','Imaged'])).count()
    done_lab = LabOrder.query.filter_by(status='Approved').count()
    done_rad = RadOrder.query.filter_by(status='Reported').count()
    new_referrals = Referral.query.filter_by(status='New').count()
    exp_year = sum(e.amount for e in Expense.query.all() if (e.date or '').startswith(str(y)))
    payroll = sum(e.gross for e in Employee.query.filter_by(active=True).all()) * 12
    net = rev_year - commission_year - exp_year - payroll
    lowstock = Medicine.query.filter(Medicine.qty <= Medicine.reorder).count()

    # ---- live widget cards (color-coded) ----
    def widget(label, value, icon, ac, link=None, sub=''):
        inner = (f"<div class='wg' style='--ac:{ac}'>"
                 f"<div class='wg-ic'>{icon}</div>"
                 f"<div class='wg-b'><div class='wg-v'>{value}</div>"
                 f"<div class='wg-l'>{label}</div>"
                 f"{f'<div class=wg-s>{sub}</div>' if sub else ''}</div></div>")
        return f"<a href='{link}' class='wg-link'>{inner}</a>" if link else inner

    # ---- role-scoped widgets: each user sees only what their job needs ----
    from ..core.security import ROLE_LABEL as _RL
    from .accounting import acct_balance as _acct_balance
    u = cur_user(); role = u.role if u else ''
    unpaid_count = sum(1 for i in inv if (_tot[i.id] - (i.paid or 0)) > 0.005)
    pending_samples = LabOrder.query.filter(LabOrder.status.in_(['Requested', 'Collected', 'Received'])).count()
    assigned_cases = RadOrder.query.filter(RadOrder.assigned_rad_id.isnot(None), RadOrder.status != 'Reported').count()
    def _bal(code):
        a = Account.query.filter_by(code=code).first()
        return _acct_balance(a) if a else 0
    cash_bal = _bal('1101'); bank_bal = _bal('1102')
    logins_today = LoginHistory.query.filter(db.func.date(LoginHistory.when) == today_s).count()
    audits_today = Audit.query.filter(db.func.date(Audit.ts) == today_s).count()

    W = {
        'today_patients':    lambda: widget("Today's Patients", pat_today, "🧑", "var(--blue)", url_for('modules.module', mod='patients')),
        'waiting':           lambda: widget("Waiting Patients", waiting, "⏳", "var(--amber)", url_for('modules.module', mod='queue')),
        'pending_pay':       lambda: widget("Pending Payments", unpaid_count, "🧾", "var(--amber)" if unpaid_count else "var(--green)", url_for('modules.module', mod='invoices'), sub='invoices'),
        'rev_today':         lambda: widget("Today's Revenue", money(rev_today), "💰", "var(--green)"),
        'unpaid_inv':        lambda: widget("Unpaid Invoices", unpaid_count, "🧾", "var(--amber)" if unpaid_count else "var(--green)", url_for('modules.module', mod='invoices')),
        'pending_samples':   lambda: widget("Pending Samples", pending_samples, "🧪", "var(--teal)", url_for('modules.module', mod='lab')),
        'completed_results': lambda: widget("Completed Results", done_lab, "✅", "var(--green)", url_for('modules.module', mod='lab')),
        'pending_reports':   lambda: widget("Pending Reports", pending_rad, "🕗", "var(--amber)" if pending_rad else "var(--green)", url_for('modules.module', mod='radiology')),
        'assigned_cases':    lambda: widget("Assigned Cases", assigned_cases, "📷", "var(--teal)", url_for('modules.module', mod='radiology')),
        'cash':              lambda: widget("Cash", money(cash_bal), "💵", "var(--green)", url_for('modules.module', mod='acct')),
        'bank':              lambda: widget("Bank", money(bank_bal), "🏦", "var(--teal)", url_for('modules.module', mod='acct')),
        'expenses':          lambda: widget("Expenses (Year)", money(exp_year), "📉", "var(--red)", url_for('modules.module', mod='expenses')),
        'profit':            lambda: widget("Net Profit", money(net), "📈", "var(--petrol)", sub='after expenses & payroll'),
        'user_activity':     lambda: widget("User Activity", logins_today, "👤", "var(--blue)", url_for('modules.module', mod='loginhistory'), sub='logins today'),
        'audit_logs':        lambda: widget("Audit Logs", audits_today, "📜", "var(--muted)", url_for('modules.module', mod='audit'), sub='events today'),
    }
    LAYOUT = {
        'reception':      ['today_patients', 'waiting', 'pending_pay'],
        'cashier':        ['rev_today', 'unpaid_inv'],
        'lab_tech':       ['pending_samples', 'completed_results'],
        'radiologist':    ['pending_reports', 'assigned_cases'],
        'accountant':     ['cash', 'bank', 'expenses', 'profit'],
        'branch_manager': ['cash', 'bank', 'expenses', 'profit'],
        'auditor':        ['audit_logs', 'user_activity', 'profit', 'expenses'],
        'it_admin':       ['user_activity', 'audit_logs', 'today_patients', 'rev_today'],
        'super_admin':    list(W.keys()),   # administrator: all KPIs + activity + audit
    }
    keys = LAYOUT.get(role)
    if keys is None:   # doctor, hr, storekeeper, engineer… — a sensible general view
        keys = ['today_patients', 'waiting', 'pending_samples', 'pending_reports']
    widgets_html = "<div class='wgs'>" + ''.join(W[k]() for k in keys if k in W) + "</div>"

    # ---- quick actions (role-aware) ----
    qa_defs = [
        ('patients',  url_for('modules.module_new', mod='patients'),  '➕', 'Register Patient'),
        ('reqboard',  url_for('modules.module', mod='reqboard'),      '📋', 'Doctor Requests'),
        ('invoices',  url_for('billing.invoice_new'),                 '🧾', 'Create Invoice'),
        ('payalloc',  url_for('modules.module', mod='payalloc'),      '💵', 'Receive Payment'),
        ('lab',       url_for('lab.lab_new'),                         '🧪', 'Lab Order'),
        ('radiology', url_for('rad.rad_new'),                         '📷', 'New Study'),
        ('queue',     url_for('modules.module', mod='queue'),         '🕐', 'Queue'),
        ('findash',   url_for('modules.module', mod='findash'),       '📊', 'Financial Dashboard'),
    ]
    qa_btns = ''.join(f"<a class='qa' href='{u_}'><span class='qa-i'>{ic}</span>{lb}</a>"
                      for k_, u_, ic, lb in qa_defs if can(k_))
    qa = (f"<div class='panel qa-wrap'><div class='pad'>"
          f"<div class='sec-lbl'>Quick Actions · Shaqo Degdeg ah</div>"
          f"<div class='qas'>{qa_btns}</div></div></div>") if qa_btns else ''

    # ---- category cards (Odoo-style module groups) ----
    CATS = [
        ("Patient Management", "🧑‍⚕️", "var(--blue)", [
            ('patients','Registration'), ('queue','Queue'), ('reqboard','Doctor Requests'),
            ('consult','Consultation'), ('referrals','Referrals')]),
        ("Laboratory", "🧪", "var(--teal)", [
            ('lab','Lab Requests'), ('labqc','Quality Control'), ('donors','Blood Bank')]),
        ("Radiology", "📷", "var(--red)", [
            ('radiology','Radiology'), ('doctors','Referring Doctors')]),
        ("Billing & Finance", "💰", "var(--green)", [
            ('invoices','Invoices'), ('acct','Accounting'), ('findash','Financial Dashboard'),
            ('revreport','Revenue Analysis')]),
        ("Inventory & Pharmacy", "📦", "var(--amber)", [
            ('pharmacy','Pharmacy'), ('suppliers','Inventory'), ('batches','Batches'),
            ('stockvalue','Valuation')]),
        ("Human Resources", "👥", "var(--petrol)", [
            ('employees','Employees'), ('contracts','Contracts'), ('users','User Management')]),
        ("Quality & Compliance", "🎯", "var(--teal)", [
            ('sops','SOPs'), ('incidents','Incidents'), ('audits','Internal Audits'),
            ('feedback','Feedback')]),
        ("Administration", "⚙️", "var(--muted)", [
            ('reports','Reports'), ('settings','Settings'), ('audit','Audit Logs'),
            ('loginhistory','Security'), ('backup','Backup'), ('messages','Messages')]),
    ]
    cat_cards = ''
    for title, icon, ac, mods in CATS:
        links = [(mk, ml) for mk, ml in mods if can(mk)]
        if not links:
            continue
        rows = ''.join(f"<a class='cat-link' href='{url_for('modules.module', mod=mk)}'>{ml}</a>" for mk, ml in links)
        cat_cards += (f"<div class='cat' style='--ac:{ac}'>"
                      f"<div class='cat-h'><span class='cat-ic'>{icon}</span><span class='cat-t'>{h(title)}</span></div>"
                      f"<div class='cat-links'>{rows}</div></div>")
    cats_html = f"<div class='sec-lbl' style='margin:18px 4px 8px'>Modules</div><div class='cats'>{cat_cards}</div>"

    # ---- KPI strip (finance) ----
    def kpi(l,v,s,ac,neg=False):
        return f"<div class='kpi' style='--ac:{ac}'><div class='l'>{l}</div><div class='v {'neg' if neg else ''}'>{v}</div><div class='s'>{s}</div></div>"
    # (redundant KPI band removed — the same figures already show in the stat cards above)

    # ---- charts: monthly revenue + top tests ----
    months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    data=[sum(i.total for i in inv if (i.date or '')[:7]==f"{y}-{m:02d}") for m in range(1,13)]
    mx=max([1]+data); W,H,pad,bw=680,190,24,(680-48)/12; bars=''
    for i,v in enumerate(data):
        bh=(v/mx)*(H-pad*2); x=pad+i*bw+bw*0.18; yy=H-pad-bh
        bars+=f"<rect x='{x:.0f}' y='{yy:.0f}' width='{bw*0.64:.0f}' height='{bh:.0f}' rx='3' fill='{'#3FA7B0' if v>0 else '#E4EAEC'}'/><text x='{pad+i*bw+bw/2:.0f}' y='{H-8}' text-anchor='middle'>{months[i]}</text>"
    chart=f"<div class='panel'><div class='ph'><h2>Revenue by Month</h2><span class='so'>{y}</span></div><div class='pad'><svg class='chart' viewBox='0 0 {W} {H}'>{bars}</svg></div></div>"
    # top requested tests (this year)
    tt = {}
    for o in LabOrder.query.all() + RadOrder.query.all():
        if (o.date or '').startswith(str(y)) and o.service:
            tt[o.service.name] = tt.get(o.service.name, 0) + 1
    top = sorted(tt.items(), key=lambda x: -x[1])[:6]
    tmx = max([1] + [n for _, n in top])
    trows = ''.join(f"<div class='tt-row'><span class='tt-n'>{h(nm)}</span>"
                    f"<span class='tt-bar'><span style='width:{n/tmx*100:.0f}%'></span></span>"
                    f"<span class='tt-v'>{n}</span></div>" for nm, n in top) or \
            "<div style='color:var(--muted);padding:10px'>No tests yet this year.</div>"
    toptests = f"<div class='panel'><div class='ph'><h2>Top Requested Tests</h2><span class='so'>{y}</span></div><div class='pad'>{trows}</div></div>"

    # ---- Daily Patients (last 7 days) ----
    import datetime as _dt
    days = [(_dt.date.today() - _dt.timedelta(days=i)) for i in range(6, -1, -1)]
    dlabels = [d.strftime('%a') for d in days]
    if hasattr(Patient, 'created'):
        dcounts = [Patient.query.filter(db.func.date(Patient.created) == d.isoformat()).count() for d in days]
    else:
        dcounts = [0] * 7
    dmx = max([1] + dcounts); dW, dH, dpad = 680, 190, 24
    dbw = (dW - 48) / 7; dbars = ''
    for i, v in enumerate(dcounts):
        bh = (v / dmx) * (dH - dpad * 2); x = dpad + i * dbw + dbw * 0.2; yy = dH - dpad - bh
        dbars += (f"<rect x='{x:.0f}' y='{yy:.0f}' width='{dbw*0.6:.0f}' height='{bh:.0f}' rx='3' fill='{'#1A3E8F' if v>0 else '#E4EAEC'}'/>"
                  f"<text x='{dpad+i*dbw+dbw/2:.0f}' y='{dH-8}' text-anchor='middle'>{dlabels[i]}</text>"
                  f"{f'<text x={dpad+i*dbw+dbw/2:.0f} y={yy-4:.0f} text-anchor=middle font-size=11 fill=#6B7F85>{v}</text>' if v else ''}")
    dchart = f"<div class='panel'><div class='ph'><h2>Daily Patients</h2><span class='so'>last 7 days</span></div><div class='pad'><svg class='chart' viewBox='0 0 {dW} {dH}'>{dbars}</svg></div></div>"

    # ---- Lab & Radiology Workload (by status) ----
    def workload(model, name, statuses, color):
        counts = [(st, model.query.filter_by(status=st).count()) for st in statuses]
        wmx = max([1] + [n for _, n in counts])
        rows = ''.join(f"<div class='tt-row'><span class='tt-n'>{st}</span>"
                       f"<span class='tt-bar'><span style='width:{n/wmx*100:.0f}%;background:{color}'></span></span>"
                       f"<span class='tt-v'>{n}</span></div>" for st, n in counts)
        return f"<div class='panel'><div class='ph'><h2>{name} Workload</h2></div><div class='pad'>{rows}</div></div>"
    lab_wl = workload(LabOrder, 'Laboratory', ['Requested', 'Collected', 'Received', 'Resulted', 'Approved'], 'var(--teal)')
    rad_wl = workload(RadOrder, 'Radiology', ['Requested', 'Imaged', 'Reported'], 'var(--red)')

    # ---- analytics shown below the widgets, scoped to the role ----
    if role in ('accountant', 'branch_manager', 'super_admin', 'auditor'):
        analytics = f"<div class='grid2'>{chart}{toptests}</div><div class='grid2'>{dchart}{lab_wl}</div><div class='grid2'>{rad_wl}<div></div></div>"
    elif role == 'lab_tech':
        analytics = f"<div class='grid2'>{lab_wl}{toptests}</div>"
    elif role == 'radiologist':
        analytics = f"<div class='grid2'>{rad_wl}{toptests}</div>"
    elif role == 'reception':
        analytics = f"<div class='grid2'>{dchart}<div></div></div>"
    else:
        analytics = ''

    alert = ''
    _overdue_n = 0
    if lowstock and can('inventory'):
        alert = f"<div class='panel' style='border-left:3px solid var(--amber)'><div class='pad'>⚠️ <b>{lowstock}</b> supply item(s) at/below reorder level. <a href='{url_for('modules.module',mod='inventory')}' style='color:var(--amber-dk);font-weight:600'>Check inventory →</a></div></div>"

    # Credit / loan accounts whose payment due date has arrived → call the customer.
    if can('invoices'):
        _t = today()
        due_list = [i for i in Invoice.query.filter(
                        Invoice.due_date.isnot(None), Invoice.status != 'Cancelled').all()
                    if i.balance > 0.005 and (i.due_date or '') <= _t]
        due_list.sort(key=lambda i: i.due_date or '')
        _overdue_n = len(due_list)
        if due_list:
            rows = ''.join(
                "<div style='display:flex;justify-content:space-between;align-items:center;gap:10px;"
                "padding:7px 0;border-top:1px solid var(--line);font-size:13px'>"
                f"<span>📞 <b>{h(i.patient.name if i.patient else 'Walk-in')}</b> "
                f"<a href='tel:{h((i.patient.phone or '') if i.patient else '')}' style='color:var(--petrol);font-weight:600'>"
                f"{h((i.patient.phone or '—') if i.patient else '—')}</a> · INV-{i.id:04d}</span>"
                f"<span style='white-space:nowrap'><b>{money(i.balance)}</b> · due {h(i.due_date)} "
                f"<a class='btn gh sm' href='{url_for('billing.invoice_view', iid=i.id)}'>Open</a></span></div>"
                for i in due_list[:15])
            alert += (
                "<div class='panel' style='border-left:3px solid var(--red)'><div class='pad'>"
                f"<b style='color:var(--red)'>📞 {len(due_list)} credit account(s) have reached their due date</b> "
                "— please call the customer to collect the outstanding balance."
                f"{rows}</div></div>")

    # ---- "Needs Attention Today" — actionable chips, only what this role can act on ----
    _pending_leave = Leave.query.filter_by(status='Pending').count() if can('leave') else 0
    _att = []
    def _achip(cond, cls, label, mod):
        if cond and can(mod):
            _att.append(f"<a class='att-chip {cls}' href='{url_for('modules.module', mod=mod)}'>{label}</a>")
    _achip(waiting, 'am', f"⏳ {waiting} waiting", 'queue')
    _achip(unpaid_count, 'am', f"🧾 {unpaid_count} unpaid", 'invoices')
    _achip(_overdue_n, 'rd', f"📞 {_overdue_n} loans overdue", 'invoices')
    _achip(new_referrals, 'bl', f"📨 {new_referrals} new referrals", 'reqboard')
    _achip(pending_lab, 'tl', f"🧪 {pending_lab} lab pending", 'lab')
    _achip(pending_rad, 'am', f"📷 {pending_rad} radiology pending", 'radiology')
    _achip(lowstock, 'am', f"📦 {lowstock} low stock", 'inventory')
    _achip(_pending_leave, 'bl', f"🌴 {_pending_leave} leave to approve", 'leave')
    _ATTCSS = """<style>
    .att-wrap{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:2px 4px 14px}
    .att-lbl{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-right:2px}
    .att-chip{display:inline-block;padding:6px 12px;border-radius:20px;font-size:13px;font-weight:600;text-decoration:none;border:1px solid var(--line)}
    .att-chip.am{background:#FEF3E7;color:#B45309;border-color:#F5C98A}
    .att-chip.rd{background:#FDECEC;color:#C0392B;border-color:#E9B0A8}
    .att-chip.bl{background:#EAF0F7;color:#1A3E8F;border-color:#B9C9E5}
    .att-chip.tl{background:#E6F4F5;color:#0E7C86;border-color:#A9D9DD}
    .att-chip.ok{background:#EAF3EC;color:#1FA66D;border-color:#A9D9BC}
    </style>"""
    if _att:
        attention = _ATTCSS + "<div class='att-wrap'><span class='att-lbl'>Needs attention</span>" + ''.join(_att) + "</div>"
    else:
        attention = _ATTCSS + "<div class='att-wrap'><span class='att-chip ok'>✓ All clear — nothing needs attention right now</span></div>"

    role_name = _RL.get(role, role or 'User')
    intro = f"<div class='sec-lbl' style='margin:2px 4px 12px;font-size:13px'>{h(role_name)} Dashboard</div>"
    return page('Dashboard', intro + attention + alert + qa + widgets_html + analytics + cats_html, 'dashboard')


@bp.route('/favorite/toggle', methods=['POST'])
@login_required
def favorite_toggle():
    """Star/un-star the current page for the logged-in user (Favorites menu)."""
    from ..models import Favorite
    u = cur_user()
    url = (request.form.get('url') or '').strip()[:200]
    label = (request.form.get('label') or '').strip()[:120] or url
    if u and url:
        ex = Favorite.query.filter_by(username=u.username, url=url).first()
        if ex:
            db.session.delete(ex); db.session.commit()
        else:
            db.session.add(Favorite(username=u.username, label=label, url=url)); db.session.commit()
    return redirect(request.form.get('next') or request.referrer or url_for('dash.dashboard'))


@bp.route('/search')
@login_required
def search():
    q=(request.args.get('q') or '').strip()
    pats=[]; invs=[]; labs=[]; rads=[]; docs=[]; emps=[]; sups=[]; pays=[]; reps=[]
    if q:
        like=f"%{q}%"
        from ..models import (LabOrder, RadOrder, Doctor, Radiologist, Employee, Supplier, PayReceipt)
        import re as _re
        _QU=q.upper().strip().replace(' ','')
        _m=_re.match(r'^INV-?0*(\d+)$', _QU)
        if _m and Invoice.query.get(int(_m.group(1))):
            return redirect(url_for('billing.invoice_view', iid=int(_m.group(1))))
        _m=_re.match(r'^RCT-?0*(\d+)$', _QU)
        if _m and PayReceipt.query.get(int(_m.group(1))):
            return redirect(url_for('billing.receipt_view', rid=int(_m.group(1))))
        _m=_re.match(r'^RAD-?0*(\d+)$', _QU)
        if _m and RadOrder.query.get(int(_m.group(1))):
            return redirect(url_for('rad.rad_thread', oid=int(_m.group(1))))
        _m=_re.match(r'^LAB-?0*(\d+)$', _QU)
        if _m and LabOrder.query.get(int(_m.group(1))):
            return redirect(url_for('lab.lab_result', oid=int(_m.group(1))))
        pats=Patient.query.filter(db.or_(Patient.name.ilike(like),Patient.phone.ilike(like),Patient.mrn.ilike(like),Patient.gov_id.ilike(like))).order_by(Patient.name).limit(20).all()
        pat_ids=[p.id for p in pats]
        qn=q.upper().replace('INV-','').lstrip('0'); seen=set()
        if qn.isdigit():
            iv=Invoice.query.get(int(qn))
            if iv: invs.append(iv); seen.add(iv.id)
        # invoices by patient name OR by the guarantor standing behind a credit sale,
        # so searching a partner hospital finds everything it owes
        ql = q.lower()
        for iv in (Invoice.query.filter(Invoice.guarantor.ilike(like))
                   .order_by(Invoice.id.desc()).limit(20).all()):
            if iv.id not in seen:
                invs.append(iv); seen.add(iv.id)
        for iv in Invoice.query.order_by(Invoice.id.desc()).limit(400).all():
            if iv.id in seen: continue
            if iv.patient and ql in (iv.patient.name or '').lower():
                invs.append(iv); seen.add(iv.id)
            if len(invs)>=20: break
        # lab/rad orders by sample no, patient name, or matched patients
        qs=q.upper().replace('LAB-','').replace('SMP-','').lstrip('0')
        for o in LabOrder.query.order_by(LabOrder.id.desc()).limit(300).all():
            if (o.sample_no and q.upper() in o.sample_no.upper()) or o.patient_id in pat_ids or (qs.isdigit() and o.id==int(qs)):
                labs.append(o)
            if len(labs)>=15: break
        qr=q.upper().replace('RAD-','').lstrip('0')
        for o in RadOrder.query.order_by(RadOrder.id.desc()).limit(300).all():
            if o.patient_id in pat_ids or (qr.isdigit() and o.id==int(qr)):
                rads.append(o)
            if len(rads)>=15: break
        docs=Doctor.query.filter(Doctor.name.ilike(like)).limit(10).all()
        rdocs=Radiologist.query.filter(Radiologist.name.ilike(like)).limit(10).all()
        docs=[('Doctor',x) for x in docs]+[('Radiologist',x) for x in rdocs]
        emps=Employee.query.filter(Employee.name.ilike(like)).limit(10).all()
        sups=Supplier.query.filter(Supplier.name.ilike(like)).limit(10).all()
        # payments (receipts) by receipt number, linked invoice, or patient
        qpay=q.upper().replace('RCT-','').lstrip('0')
        if qpay.isdigit():
            _pr=PayReceipt.query.get(int(qpay))
            if _pr: pays.append(_pr)
        _iset=set(i.id for i in invs)
        for r in PayReceipt.query.order_by(PayReceipt.id.desc()).limit(400).all():
            if r in pays: continue
            if r.invoice_id in _iset or (r.invoice and r.invoice.patient_id in pat_ids):
                pays.append(r)
            if len(pays)>=15: break
        # reports = completed lab / radiology matching the query (report number)
        for o in labs:
            if o.status=='Approved': reps.append(('Lab',o))
        for o in rads:
            if o.status=='Reported': reps.append(('Radiology',o))
        # ---- open the record directly when the search uniquely identifies one ----
        if len(pats) == 1 and not docs and not emps and not sups:
            _pid = pats[0].id
            _only_this = (all(getattr(i, 'patient_id', None) == _pid for i in invs)
                          and all(getattr(o, 'patient_id', None) == _pid for o in labs)
                          and all(getattr(o, 'patient_id', None) == _pid for o in rads)
                          and all(r.invoice and r.invoice.patient_id == _pid for r in pays))
            if _only_this:
                return redirect(url_for('patients.patient_detail', pid=_pid))
        if not pats and not docs and not emps and not sups:
            _recs = ([('invoice', i) for i in invs] + [('lab', o) for o in labs]
                     + [('rad', o) for o in rads] + [('pay', r) for r in pays])
            if len(_recs) == 1:
                _k, _o = _recs[0]
                _u = {'invoice': lambda o: url_for('billing.invoice_view', iid=o.id),
                      'lab': lambda o: url_for('lab.lab_result', oid=o.id),
                      'rad': lambda o: url_for('rad.rad_thread', oid=o.id),
                      'pay': lambda o: url_for('billing.receipt_view', rid=o.id)}
                return redirect(_u[_k](_o))
    def sec(title, count, headers, rows):
        if not rows and not q: return ''
        hd=''.join(f"<th>{hh}</th>" for hh in headers)
        return (f"<div class='panel'><div class='ph'><h2>{title}</h2><span class='so'>{count} found</span></div>"
                f"<div class='tw'><table><thead><tr>{hd}</tr></thead><tbody>{rows or f'<tr><td colspan={len(headers)} style=color:var(--muted);padding:14px>None found.</td></tr>'}</tbody></table></div></div>")
    prow=''.join(f"<tr><td><b>{h(p.mrn)}</b></td><td><a href='/patient/{p.id}' style='color:var(--petrol);font-weight:600'>{h(p.name)}</a></td><td>{h(p.phone or '—')}</td><td>{h(p.gender or '—')}</td></tr>" for p in pats)
    irow=''.join(f"<tr><td><a href='/invoice/{i.id}' style='color:var(--petrol);font-weight:600'>INV-{i.id:04d}</a></td><td>{h(i.date)}</td><td>{h(i.patient.name if i.patient else 'Walk-in')}</td>"
                 f"<td>{(f'🤝 <b>{h(i.guarantor)}</b>' + (f'<br><small style=color:var(--muted)>granted by {h(i.guarantor_by)}</small>' if i.guarantor_by else '')) if i.guarantor else '<span style=color:var(--muted)>—</span>'}</td>"
                 f"<td class='num'>{money(i.total)}</td><td class='num'>{money(i.balance)}</td>"
                 f"<td><span class='pill {'green' if i.status=='Paid' else 'amber'}'>{h(i.status)}</span></td></tr>" for i in invs)
    lrow=''.join(f"<tr><td><b>{h(o.sample_no or ('LAB-%04d'%o.id))}</b></td><td>{plink(o.patient)}</td><td>{h(o.service.name if o.service else '—')}</td><td><span class='pill blue'>{h(o.status)}</span></td></tr>" for o in labs)
    rrow=''.join(f"<tr><td><b>RAD-{o.id:04d}</b></td><td>{plink(o.patient)}</td><td>{h(o.modality or '')} {h(o.service.name if o.service else '')}</td><td><span class='pill teal'>{h(o.status)}</span></td></tr>" for o in rads)
    drow=''.join(f"<tr><td>{h(kind)}</td><td>{h(x.name)}</td><td>{h(getattr(x,'specialty','') or getattr(x,'phone','') or '—')}</td></tr>" for kind,x in docs)
    erow=''.join(f"<tr><td>{h(e.name)}</td><td>{h(e.position or e.dept or '—')}</td><td>{h(e.code or '—')}</td></tr>" for e in emps)
    srow=''.join(f"<tr><td>{h(s.name)}</td><td>{h(s.phone or '—')}</td><td>{h(s.address or '—')}</td></tr>" for s in sups)
    payrow=''.join(f"<tr><td><a href='{url_for('billing.receipt_view',rid=r.id)}' style='color:var(--petrol);font-weight:600'>RCT-{r.id:05d}</a></td><td>{h(r.date)}</td>"
                   f"<td>{plink(r.invoice.patient if r.invoice else None)}</td>"
                   f"<td class='num'>{money(r.amount)}</td><td>{h(r.method or 'Cash')}</td></tr>" for r in pays)
    reprow=''.join(f"<tr><td>{('🧪 Lab' if kind=='Lab' else '📷 Radiology')}</td>"
                   f"<td><a href='{(url_for('lab.lab_print',oid=o.id) if kind=='Lab' else url_for('rad.rad_print',oid=o.id))}' target='_blank' style='color:var(--petrol);font-weight:600'>{('LAB-%04d'%o.id) if kind=='Lab' else ('RAD-%04d'%o.id)}</a></td>"
                   f"<td>{plink(o.patient)}</td><td>{h(o.service.name if o.service else '—')}</td></tr>" for kind,o in reps)
    results=(sec('Patients',len(pats),['MRN','Name','Phone','Gender'],prow)
             +sec('Invoices',len(invs),['No.','Date','Patient','Guarantor','Total','Balance','Status'],irow)
             +sec('Payments',len(pays),['Receipt','Date','Patient','Amount','Method'],payrow)
             +sec('Laboratory',len(labs),['Sample/No.','Patient','Test','Status'],lrow)
             +sec('Radiology',len(rads),['No.','Patient','Study','Status'],rrow)
             +sec('Reports',len(reps),['Type','No.','Patient','Name'],reprow)
             +sec('Doctors / Radiologists',len(docs),['Type','Name','Info'],drow)
             +sec('Employees',len(emps),['Name','Position','Code'],erow)
             +sec('Suppliers',len(sups),['Name','Phone','Address'],srow))
    body=f"""<div class='panel'><div class='pad'><form action='{url_for('dash.search')}' method='get' style='display:flex;gap:10px'>
      <input name='q' value='{h(q)}' placeholder='Patient, phone, MRN, invoice, sample, doctor, employee, supplier…' autofocus style='flex:1;border:1px solid var(--line);border-radius:9px;padding:11px 14px;font-size:14px'>
      <button class='btn primary'>Search</button></form></div></div>
      {results if q else "<div class='panel'><div class='pad' style='color:var(--muted)'>Type anything to search across patients, invoices, lab & radiology orders, doctors, employees and suppliers.</div></div>"}"""
    return page('Search' + (f' · "{h(q)}"' if q else ''), body, '')


@bp.route('/notifications')
@login_required
def notifications():
    from ..core.notify import visible_for, mark_seen
    from flask import render_template
    u = cur_user()
    items = visible_for(u)
    seen_before = {n.id for n in items if str(u.id) in (n.seen_by or '').split(',')}
    unread = sum(1 for n in items if n.id not in seen_before)
    mark_seen(u)

    def _aud(role):
        if not role:
            return "<span class='pill grey'>All staff</span>"
        return ' '.join(f"<span class='pill blue'>{h(ROLE_LABEL.get(r, r))}</span>" for r in role.split(','))

    rows = []
    for n in items:
        fresh = n.id not in seen_before
        dot = ("<span style='display:inline-block;width:8px;height:8px;border-radius:50%;"
               "background:var(--amber);margin-right:8px'></span>") if fresh else ''
        label = f"{dot}{h(n.text)}"
        title = f"<a class='idlink' href='{h(n.link)}'>{label}</a>" if n.link else label
        rows.append([h(n.ts.strftime('%d-%b %H:%M') if n.ts else '—'), title, _aud(n.role)])

    body = render_template(
        'list_page.html', title='Notification Center',
        subtitle=(f'{unread} unread' if unread else 'all caught up ✓'),
        headers=['When', 'Event', 'Audience'], aligns=['', '', ''], rows=rows,
        empty=("<div class='empty'><b>No notifications yet</b>Registrations, payments, completed "
               "reports, cancellations, low stock and backup alerts will appear here.</div>"))
    return page('Notification Center', body, '')


# ---- friendly labels & icons for every reachable module (one place to find everything) ----
APP_CATALOG = [
    ("Patient Management", "🧑‍⚕️", "var(--blue)", [
        ('patients', 'Patient Registration', 'Diiwaangelin bukaan'),
        ('queue', 'Reception Queue', 'Safka qaabilaadda'),
        ('tokenq', 'Token Queue &amp; Display', 'Safka tigidhada'),
        ('reqboard', 'Doctor Requests', 'Codsiyada dhakhtarka'),
        ('referrals', 'New Doctor Request', 'Gudbin cusub'),
        ('consult', 'Consultation', 'La-tashi'),
        ('doctors', 'Referring Doctors', 'Dhakhtarrada gudbiya'),
    ]),
    ("Emergency &amp; Wards", "🚑", "var(--red)", [
        ('ed', 'Emergency Department', 'Gargaarka degdegga'),
        ('ipd', 'Inpatient / Admissions', 'Bukaan-jiifka'),
        ('ot', 'Operation Theatre', 'Qolka qalliinka'),
        ('dialysis', 'Dialysis', 'Dialysis-ka'),
        ('wards', 'Wards', 'Qolalka'),
        ('beds', 'Beds', 'Sariiraha'),
        ('theatres', 'Operating Theatres', 'Qolalka qalliinka'),
        ('dmachines', 'Dialysis Machines', 'Mashiinnada dialysis'),
    ]),
    ("Ambulance", "🚑", "var(--amber-dk)", [
        ('ambulance', 'Ambulance Dispatch', 'Ambalaas'),
        ('vehicles', 'Ambulances (fleet)', 'Gaadiidka'),
        ('drivers_amb', 'Drivers', 'Darawallada'),
    ]),
    ("Laboratory", "🧪", "var(--teal)", [
        ('lab', 'Laboratory Requests', 'Codsiyada shaybaarka'),
        ('labtests', 'Laboratory Tests', 'Baaritaannada shaybaarka'),
        ('lis', 'LIS · Analyzer & Results', 'Natiijada shaybaarka'),
        ('critical', 'Critical Results', 'Natiijooyinka halista ah'),
        ('labqc', 'Quality Control', 'Tayada QC'),
        ('instruments', 'Lab Instruments', 'Qalabka shaybaarka'),
        ('bloodbank', 'Blood Bank', 'Bangiga dhiigga'),
        ('donors', 'Blood Donors', 'Deeq-bixiyeyaasha'),
        ('vaccinations', 'Vaccination', 'Tallaalka'),
    ]),
    ("Radiology", "📷", "var(--red)", [
        ('radiology', 'Radiology / Imaging', 'Raajada'),
        ('ris', 'RIS · Imaging Worklist', 'Liiska raajada'),
        ('pacs', 'PACS / DICOM Viewer', 'Sawirrada DICOM'),
        ('modalities', 'Imaging Modalities', 'Qalabka raajada'),
    ]),
    ("Billing & Cashier", "💵", "var(--green)", [
        ('invoices', 'Invoices', 'Biilasha'),
        ('dailytx', 'Daily Transactions', 'Dhaqdhaqaaqa maalinlaha'),
        ('payalloc', 'Receive Payment', 'Lacag qaad'),
        ('creditnotes', 'Credit Notes', 'Warqadaha deynta'),
        ('cashclose', 'Daily Cash Closing', 'Xir maalinta'),
        ('commission', 'Doctor Commission', 'Kaalmada dhakhtarka'),
        ('services', 'Service Catalog', 'Liiska adeegyada'),
    ]),
    ("Insurance", "🛡️", "var(--teal)", [
        ('insurance', 'Claims', 'Sheegashooyinka'),
        ('insurers', 'Insurance Companies', 'Shirkadaha caymiska'),
        ('inscards', 'Insurance Cards', 'Kaararka caymiska'),
        ('coverage', 'Coverage Rules', 'Xeerarka daboolka'),
    ]),
    ("Accounting", "📊", "var(--petrol)", [
        ('acct', 'Accounting Dashboard', 'Xisaabaadka'),
        ('acctguide', 'Accounting Guide · Step by step', 'Hage tallaabo-tallaabo'),
        ('acctdash', 'Accounting Dashboard (New)', 'Dashboard xisaabeed'),
        ('analytics', 'Analytics Dashboard', 'Falanqaynta guud'),
        ('findash', 'Financial Dashboard', 'Dashboard maaliyadeed'),
        ('accounts', 'Chart of Accounts', 'Jaantuska akoonnada'),
        ('journal', 'Journal Entries', 'Gelitaanka joornaalka'),
        ('recurjournals', 'Recurring Journals', 'Joornaal soo noqnoqda'),
        ('gldash', 'GL · Dashboard', 'GL Dashboard'),
        ('genledger', 'GL · General Ledger', 'Xisaabta guud (GL)'),
        ('jitems', 'GL · Journal Items', 'Shayada joornaalka'),
        ('jentries', 'GL · Journal Entries', 'Gelitaanka joornaalka'),
        ('trialbal', 'GL · Trial Balance', 'Miisaanka tijaabada'),
        ('acctbal', 'GL · Account Balances', 'Balance-ka akoonnada'),
        ('expenses', 'Expenses', 'Kharashaadka'),
        ('cashflow', 'Cash Flow', 'Socodka lacagta'),
        ('araging', 'AR Aging', 'Da\'da la-sugayaasha'),
        ('apaging', 'AP Aging', 'Da\'da la-bixinayaasha'),
        ('banks', 'Bank Accounts', 'Akoonnada bangiga'),
        ('bankrec', 'Bank Reconciliation', 'Isku-dheelitir bangi'),
        ('bankrecon', 'Bank Reconciliation (Simple)', 'Isku-dheelitir fudud'),
        ('budgets', 'Budgets', 'Miisaaniyadaha'),
        ('costcenters', 'Cost Centers', 'Xarumaha kharashka'),
        ('ratios', 'Financial Ratios', 'Saamiyada maaliyadeed'),
        ('revreport', 'Revenue Analysis', 'Falanqaynta dakhliga'),
        ('taxreport', 'Tax Report', 'Warbixinta canshuurta'),
        ('fiscal', 'Fiscal Periods', 'Xilliyada maaliyadeed'),
        ('currencies', 'Currencies', 'Lacagaha'),
        ('finance', 'Financial Statements', 'Bayaannada maaliyadeed'),
    ]),
    ("Inventory & Pharmacy", "📦", "var(--amber)", [
        ('pharmacy', 'Pharmacy', 'Farmashiga'),
        ('suppliers', 'Suppliers', 'Alaab-qeybiyayaasha'),
        ('inventory', 'Supplies / Stock', 'Alaabta'),
        ('purchases', 'Purchase Orders', 'Dalabaadka iibsiga'),
        ('batches', 'Batches (FEFO)', 'Dufcadaha'),
        ('warehouses', 'Warehouses', 'Bakhaarrada'),
        ('transfers', 'Stock Transfers', 'Wareejinta alaabta'),
        ('consume', 'Consume / Use Supplies', 'Isticmaalka alaabta'),
        ('stockadj', 'Stock Adjustments', 'Hagaajinta alaabta'),
        ('stockvalue', 'Inventory Valuation', 'Qiimaynta alaabta'),
        ('consumption', 'Consumption Report', 'Warbixinta isticmaalka'),
    ]),
    ("Human Resources", "👥", "var(--blue)", [
        ('hr', 'HR Dashboard', 'HR-ka guud'),
        ('employees', 'Employees', 'Shaqaalaha'),
        ('attendance', 'Attendance', 'Xaadirinta'),
        ('leave', 'Leave', 'Fasaxa'),
        ('payroll', 'Payroll', 'Mushaharka'),
        ('contracts', 'Contracts', 'Qandaraasyada'),
    ]),
    ("Assets & Maintenance", "🔧", "var(--teal)", [
        ('maintdash', 'Maintenance Overview', 'Guud ahaan dayactirka'),
        ('assets', 'Asset Register', 'Diiwaanka hantida'),
        ('maintenance', 'Maintenance Jobs', 'Hawlaha dayactirka'),
    ]),
    ("Quality & Compliance", "🎯", "var(--teal)", [
        ('sops', 'SOPs & Documents', 'Hab-raacyada'),
        ('incidents', 'Incidents', 'Dhacdooyinka'),
        ('audits', 'Internal Audits', 'Hubinta gudaha'),
        ('feedback', 'Patient Feedback', 'Ra\'yiga bukaanka'),
    ]),
    ("Reports", "📈", "var(--green)", [
        ('reports', 'Reports Overview', 'Warbixinnada'),
        ('summary', 'Summary (date range)', 'Kooban'),
        ('revenue', 'Revenue Analysis', 'Dakhliga'),
        ('productivity', 'Productivity', 'Wax-soo-saarka'),
        ('radfees', 'Radiologist Fees', 'Kharashka raajada'),
        ('branchcmp', 'Branch Comparison', 'Isbarbardhig laamaha'),
    ]),
    ("Administration", "⚙️", "var(--muted)", [
        ('users', 'User Management', 'Maamulka isticmaalayaasha'),
        ('security', 'Security Center', 'Xarunta amniga'),
        ('branches', 'Branches', 'Laamaha'),
        ('branchhub', 'Branch Hub &amp; Focus', 'Xarunta laamaha'),
        ('settings', 'Settings', 'Dejinta'),
        ('svcmgmt', 'Service Management', 'Maamulka adeegyada'),
        ('audit', 'Audit Log', 'Diiwaanka hawlaha'),
        ('errorlog', 'Error Log', 'Diiwaanka khaladaadka'),
        ('syshealth', 'System Health', 'Caafimaadka nidaamka'),
        ('loginhistory', 'Login Security', 'Amniga gelitaanka'),
        ('backup', 'Backup & Restore', 'Kaydinta'),
        ('messages', 'Messages / SMS', 'Fariimaha'),
    ]),
]


@bp.route('/apps')
@login_required
def apps():
    """Consolidated launcher: top level shows one app per area (Odoo-style); opening
    an app reveals its modules. ?cat=<slug> drills into a single area."""
    import re as _re
    def _slug(t):
        return _re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')

    visible = []
    for title, icon, ac, mods in APP_CATALOG:
        links = [(k, en, so) for k, en, so in mods if can(k)]
        if links:
            visible.append((title, icon, ac, links))

    cat = request.args.get('cat', '').strip()
    sel = next((c for c in visible if _slug(c[0]) == cat), None) if cat else None

    # ---------- LEVEL 2: modules inside one app ----------
    if sel:
        title, icon, ac, links = sel
        items = ''
        for k, en, so in links:
            items += (f"<a class='app-item' href='{url_for('modules.module', mod=k)}' data-name='{h((en+' '+so).lower())}'>"
                      f"<span class='app-ic' style='background:var(--canvas);background:color-mix(in srgb,{ac} 16%,var(--surface))'>{icon}</span>"
                      f"<span class='app-txt'><b>{h(en)}</b><small>{h(so)}</small></span></a>")
        body = f"""
    <div class='panel'><div class='pad' style='display:flex;align-items:center;gap:14px;flex-wrap:wrap'>
      <span class='app-ic' style='width:46px;height:46px;font-size:24px;background:color-mix(in srgb,{ac} 16%,var(--surface))'>{icon}</span>
      <div style='flex:1'><div style='font-family:var(--fd);font-size:20px;font-weight:700;color:var(--petrol)'>{h(title)}</div>
      <div style='color:var(--muted);font-size:13px'>{len(links)} qaybood</div></div>
      <a class='btn' href='{url_for('dash.apps')}'>← All Apps</a>
    </div></div>
    <div class='app-grid'>{items}</div>"""
        return page(title, body, 'apps',
                    crumbs=[('All Modules', url_for('dash.apps')), (title, None)])

    # ---------- LEVEL 1: one tile per app (area) ----------
    tiles = ''
    for title, icon, ac, links in visible:
        allnames = ' '.join((en + ' ' + so) for _, en, so in links).lower()
        tiles += (f"<a class='cat-tile' href='{url_for('dash.apps')}?cat={_slug(title)}' "
                  f"data-name='{h((title + ' ' + allnames))}'>"
                  f"<span class='cat-ic' style='background:var(--canvas);background:color-mix(in srgb,{ac} 18%,var(--surface))'>{icon}</span>"
                  f"<span class='cat-tx'><b>{h(title)}</b><small>{len(links)} qaybood</small></span>"
                  f"<span class='cat-arrow'>→</span></a>")
    body = f"""
    <div class='panel'><div class='pad'>
      <div><div style='font-family:var(--fd);font-size:20px;font-weight:700;color:var(--petrol)'>All Apps · Qaybaha</div>
      <div style='color:var(--muted);font-size:13px'>Guji app si aad u furto qaybaheeda — ama qor magaca si aad u raadiso ({len(visible)} app)</div></div>
      <input id='appq' placeholder='🔎 Search… (tusaale: invoice, bukaan, raajo, journal)' autofocus
        style='width:100%;margin-top:12px;border:1px solid var(--line);border-radius:10px;padding:12px 16px;font-size:15px;background:var(--surface);color:var(--ink)'
        oninput='filterApps(this.value)'>
    </div>
    <div id='catwrap' class='cat-grid'>{tiles}</div>
    <div id='appempty' style='display:none;text-align:center;color:var(--muted);padding:30px'>No app matches your search.</div>
    <script>
    function filterApps(q){{
      q=(q||'').trim().toLowerCase(); var any=false;
      document.querySelectorAll('.cat-tile').forEach(function(t){{
        var m=!q||t.dataset.name.indexOf(q)>-1; t.style.display=m?'':'none'; if(m)any=true;
      }});
      document.getElementById('appempty').style.display=any?'none':'block';
    }}
    </script>"""
    return page('All Modules', body, 'apps')
