"""Main dashboard KPIs, role-specific views, and global search."""
from flask import (Blueprint, request, redirect, url_for)
from markupsafe import escape as h
from sqlalchemy.orm import selectinload
import datetime as dt

from ..extensions import db
from ..models import (
    Invoice, Patient, Appointment, LabOrder, RadOrder, Referral,
    Expense, Employee, Medicine, Leave, Audit, LoginHistory, Account, Service
)
from ..core.security import (cur_user, can, login_required, ROLE_LABEL, branch_scope, effective_branch)
from ..core.helpers import money, today, cur_year
from ..core.ui import page, plink, pnamelink

bp = Blueprint('dash', __name__)

# SVG Icon System for Dashboards (Replacing Emojis)
SVG = {
    'user': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>',
    'users': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>',
    'clock': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
    'invoice': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>',
    'dollar': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>',
    'flask': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M10 2v7.5L4.5 18A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-3L14 9.5V2"></path><line x1="8.5" y1="2" x2="15.5" y2="2"></line></svg>',
    'camera': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>',
    'package': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><line x1="16.5" y1="9.4" x2="7.5" y2="4.21"></line><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>',
    'check-circle': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>',
    'alert-triangle': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
    'phone': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>',
    'calendar': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>',
    'plus-circle': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="16"></line><line x1="8" y1="12" x2="16" y2="12"></line></svg>',
    'bar-chart': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>',
    'trending-up': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg>',
    'trending-down': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"></polyline><polyline points="17 18 23 18 23 12"></polyline></svg>',
    'shield': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>',
    'file': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>',
    'bank': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><line x1="3" y1="21" x2="21" y2="21"></line><line x1="3" y1="10" x2="21" y2="10"></line><polyline points="12 3 2 10 22 10"></polyline><line x1="6" y1="10" x2="6" y2="21"></line><line x1="10" y1="10" x2="10" y2="21"></line><line x1="14" y1="10" x2="14" y2="21"></line><line x1="18" y1="10" x2="18" y2="21"></line></svg>',
    'heart': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>',
    'settings': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>',
    'target': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg>'
}

@bp.route('/')
@bp.route('/dashboard')
@login_required
def dashboard():
    u = cur_user()
    role = u.role if u else ''
    role_name = ROLE_LABEL.get(role, role or 'User')
    y = cur_year()
    today_s = today()
    eff_b = effective_branch(u)

    # ---- Scoped Database Queries (Branch Isolation Enforced) ----
    inv_query = branch_scope(Invoice.query, Invoice)
    inv = inv_query.options(selectinload(Invoice.items), selectinload(Invoice.doctor_ref)).all()
    _tot = {i.id: i.total for i in inv}
    rev_today = sum(_tot[i.id] for i in inv if i.date == today_s)
    rev_year = sum(_tot[i.id] for i in inv if (i.date or '').startswith(str(y)))
    commission_year = sum(i.commission for i in inv if (i.date or '').startswith(str(y)))
    receivable = sum(_tot[i.id] - (i.paid or 0) for i in inv if i.status != 'Cancelled')
    cash_today = sum((i.paid or 0) for i in inv if i.date == today_s)
    unpaid_invoices = [i for i in inv if (_tot[i.id] - (i.paid or 0)) > 0.005 and i.status != 'Cancelled']
    unpaid_count = len(unpaid_invoices)

    pat_query = branch_scope(Patient.query, Patient)
    n_pat = pat_query.count()
    pat_today = pat_query.filter(db.func.date(Patient.created) == today_s).count() if hasattr(Patient, 'created') else 0

    app_query = branch_scope(Appointment.query, Appointment)
    waiting = app_query.filter_by(status='Waiting').count()
    waiting_list = app_query.filter_by(status='Waiting').order_by(Appointment.id.desc()).limit(10).all()

    lab_query = branch_scope(LabOrder.query, LabOrder)
    pending_lab = lab_query.filter(LabOrder.status.in_(['Requested','Collected','Received','Resulted'])).count()
    pending_samples = lab_query.filter(LabOrder.status.in_(['Requested', 'Collected', 'Received'])).count()
    done_lab = lab_query.filter_by(status='Approved').count()
    pending_lab_list = lab_query.filter(LabOrder.status.in_(['Requested', 'Collected', 'Received'])).order_by(LabOrder.id.desc()).limit(10).all()

    rad_query = branch_scope(RadOrder.query, RadOrder)
    pending_rad = rad_query.filter(RadOrder.status.in_(['Requested','Imaged'])).count()
    assigned_cases = rad_query.filter(RadOrder.assigned_rad_id.isnot(None), RadOrder.status != 'Reported').count()
    done_rad = rad_query.filter_by(status='Reported').count()
    pending_rad_list = rad_query.filter(RadOrder.status.in_(['Requested', 'Imaged'])).order_by(RadOrder.id.desc()).limit(10).all()

    ref_query = branch_scope(Referral.query, Referral)
    new_referrals = ref_query.filter_by(status='New').count()
    new_referrals_list = ref_query.filter_by(status='New').order_by(Referral.id.desc()).limit(10).all()

    exp_query = branch_scope(Expense.query, Expense)
    exp_year = sum(e.amount for e in exp_query.all() if (e.date or '').startswith(str(y)))

    emp_query = branch_scope(Employee.query, Employee)
    active_emps = emp_query.filter_by(active=True).count()
    payroll = sum(e.gross for e in emp_query.filter_by(active=True).all()) * 12

    net = rev_year - commission_year - exp_year - payroll

    med_query = branch_scope(Medicine.query, Medicine)
    lowstock = med_query.filter(Medicine.qty <= Medicine.reorder).count() if hasattr(Medicine, 'qty') else 0
    lowstock_list = med_query.filter(Medicine.qty <= Medicine.reorder).limit(10).all() if hasattr(Medicine, 'qty') else []

    if can('leave'):
        leave_query = branch_scope(Leave.query, Leave) if hasattr(Leave, 'branch_id') else Leave.query
        pending_leave = leave_query.filter_by(status='Pending').count()
        pending_leave_list = leave_query.filter_by(status='Pending').order_by(Leave.id.desc()).limit(10).all()
    else:
        pending_leave = 0
        pending_leave_list = []

    from .accounting import acct_balance as _acct_balance
    def _bal(code):
        a = Account.query.filter_by(code=code).first()
        return _acct_balance(a) if a else 0
    cash_bal = _bal('1101')
    bank_bal = _bal('1102')

    logins_today = LoginHistory.query.filter(db.func.date(LoginHistory.when) == today_s).count()
    audits_today = Audit.query.filter(db.func.date(Audit.ts) == today_s).count()
    recent_audits = Audit.query.order_by(Audit.id.desc()).limit(10).all()

    # ---- Live Widget Cards Generator (Using Clean SVG Icons) ----
    def widget(label, value, icon_key, ac, link=None, sub=''):
        ic_svg = SVG.get(icon_key, SVG['file'])
        inner = (f"<div class='wg' style='--ac:{ac}'>"
                 f"<div class='wg-ic'>{ic_svg}</div>"
                 f"<div class='wg-b'><div class='wg-v'>{value}</div>"
                 f"<div class='wg-l'>{label}</div>"
                 f"{f'<div class=wg-s>{sub}</div>' if sub else ''}</div></div>")
        return f"<a href='{link}' class='wg-link'>{inner}</a>" if link else inner

    W = {
        'today_patients':    lambda: widget("Today's Patients", pat_today, 'user', "var(--blue)", url_for('modules.module', mod='patients') if can('patients') else None),
        'waiting':           lambda: widget("Waiting Patients", waiting, 'clock', "var(--amber)", url_for('modules.module', mod='queue') if can('queue') else None),
        'pending_pay':       lambda: widget("Pending Payments", unpaid_count, 'invoice', "var(--amber)" if unpaid_count else "var(--green)", url_for('modules.module', mod='invoices') if can('invoices') else None, sub='invoices'),
        'rev_today':         lambda: widget("Today's Revenue", money(rev_today), 'dollar', "var(--green)"),
        'unpaid_inv':        lambda: widget("Unpaid Invoices", unpaid_count, 'invoice', "var(--amber)" if unpaid_count else "var(--green)", url_for('modules.module', mod='invoices') if can('invoices') else None),
        'pending_samples':   lambda: widget("Pending Samples", pending_samples, 'flask', "var(--teal)", url_for('modules.module', mod='lab') if can('lab') else None),
        'completed_results': lambda: widget("Completed Results", done_lab, 'check-circle', "var(--green)", url_for('modules.module', mod='lab') if can('lab') else None),
        'pending_reports':   lambda: widget("Pending Reports", pending_rad, 'clock', "var(--amber)" if pending_rad else "var(--green)", url_for('modules.module', mod='radiology') if can('radiology') else None),
        'assigned_cases':    lambda: widget("Assigned Cases", assigned_cases, 'camera', "var(--teal)", url_for('modules.module', mod='radiology') if can('radiology') else None),
        'cash':              lambda: widget("Cash", money(cash_bal), 'dollar', "var(--green)", url_for('modules.module', mod='acct') if can('acct') else None),
        'bank':              lambda: widget("Bank", money(bank_bal), 'bank', "var(--teal)", url_for('modules.module', mod='acct') if can('acct') else None),
        'expenses':          lambda: widget("Expenses (Year)", money(exp_year), 'trending-down', "var(--red)", url_for('modules.module', mod='expenses') if can('expenses') else None),
        'profit':            lambda: widget("Net Profit", money(net), 'trending-up', "var(--petrol)", sub='after expenses & payroll'),
        'user_activity':     lambda: widget("User Activity", logins_today, 'user', "var(--blue)", url_for('modules.module', mod='loginhistory') if can('security') or can('loginhistory') else None, sub='logins today'),
        'audit_logs':        lambda: widget("Audit Logs", audits_today, 'file', "var(--muted)", url_for('modules.module', mod='audit') if can('audit') else None, sub='events today'),
        'active_emps':       lambda: widget("Active Employees", active_emps, 'users', "var(--blue)", url_for('modules.module', mod='employees') if can('employees') or can('hr') else None),
        'pending_leave':     lambda: widget("Pending Leave", pending_leave, 'calendar', "var(--amber)", url_for('modules.module', mod='leave') if can('leave') else None),
        'lowstock':          lambda: widget("Low Stock Alerts", lowstock, 'package', "var(--amber)" if lowstock else "var(--green)", url_for('modules.module', mod='inventory') if can('inventory') else None),
        'new_referrals':     lambda: widget("Doctor Requests", new_referrals, 'file', "var(--teal)", url_for('modules.module', mod='reqboard') if can('reqboard') else None),
    }

    # Strict maximum 6 KPIs per role
    LAYOUT = {
        'super_admin':    ['today_patients', 'waiting', 'rev_today', 'unpaid_inv', 'pending_samples', 'pending_reports'],
        'branch_manager': ['rev_today', 'today_patients', 'waiting', 'unpaid_inv', 'profit'],
        'accountant':     ['cash', 'bank', 'unpaid_inv', 'expenses', 'profit'],
        'reception':      ['today_patients', 'waiting', 'new_referrals', 'pending_pay'],
        'cashier':        ['rev_today', 'unpaid_inv', 'pending_pay', 'today_patients'],
        'doctor':         ['waiting', 'new_referrals', 'pending_samples', 'pending_reports'],
        'lab_tech':       ['pending_samples', 'completed_results', 'today_patients'],
        'lab_supervisor': ['pending_samples', 'completed_results', 'lowstock', 'audit_logs'],
        'radiologist':    ['pending_reports', 'assigned_cases', 'completed_results'],
        'nurse':          ['waiting', 'today_patients', 'pending_samples'],
        'hr':             ['active_emps', 'pending_leave', 'user_activity'],
        'storekeeper':    ['lowstock', 'expenses', 'pending_pay'],
        'engineer':       ['lowstock', 'user_activity', 'audit_logs'],
        'it_admin':       ['user_activity', 'audit_logs', 'today_patients', 'rev_today'],
        'auditor':        ['audit_logs', 'user_activity', 'profit', 'expenses'],
    }

    keys = LAYOUT.get(role)
    if keys is None:
        candidate_keys = ['today_patients', 'waiting', 'new_referrals', 'pending_samples', 'pending_reports', 'unpaid_inv']
        keys = candidate_keys

    widgets_html = "<div class='wgs'>" + ''.join(W[k]() for k in keys[:6] if k in W) + "</div>"

    # ---- Quick Actions (Strict maximum 6 per role) ----
    QA_MAP = {
        'patients':    (url_for('modules.module_new', mod='patients'), SVG['plus-circle'], 'Register Patient'),
        'queue':       (url_for('modules.module', mod='queue'), SVG['clock'], 'Queue'),
        'reqboard':    (url_for('modules.module', mod='reqboard'), SVG['file'], 'Doctor Requests'),
        'invoices':    (url_for('billing.invoice_new'), SVG['invoice'], 'Create Invoice'),
        'payalloc':    (url_for('modules.module', mod='payalloc'), SVG['dollar'], 'Receive Payment'),
        'lab':         (url_for('modules.module', mod='lab'), SVG['flask'], 'Laboratory Worklist'),
        'radiology':   (url_for('modules.module', mod='radiology'), SVG['camera'], 'Radiology Worklist'),
        'syshealth':   (url_for('modules.module', mod='syshealth'), SVG['settings'], 'System Health'),
        'inventory':   (url_for('modules.module', mod='inventory'), SVG['package'], 'Inventory Stock'),
        'employees':   (url_for('modules.module', mod='employees'), SVG['users'], 'Employees'),
        'findash':     (url_for('modules.module', mod='findash'), SVG['bar-chart'], 'Financial Dashboard'),
        'audit':       (url_for('modules.module', mod='audit'), SVG['shield'], 'Audit Logs'),
        'acct':        (url_for('modules.module', mod='acct'), SVG['bank'], 'Accounting'),
        'labqc':       (url_for('modules.module', mod='labqc'), SVG['flask'], 'Quality Control'),
        'pacs':        (url_for('modules.module', mod='pacs'), SVG['camera'], 'PACS Viewer'),
        'ris':         (url_for('modules.module', mod='ris'), SVG['camera'], 'RIS Worklist'),
        'ed':          (url_for('modules.module', mod='ed'), SVG['heart'], 'Emergency Dept'),
        'ipd':         (url_for('modules.module', mod='ipd'), SVG['user'], 'Inpatient Wards'),
        'hr':          (url_for('modules.module', mod='hr'), SVG['users'], 'HR Dashboard'),
        'leave':       (url_for('modules.module', mod='leave'), SVG['calendar'], 'Leave Approvals'),
        'payroll':     (url_for('modules.module', mod='payroll'), SVG['dollar'], 'Payroll'),
        'suppliers':   (url_for('modules.module', mod='suppliers'), SVG['package'], 'Suppliers'),
        'purchases':   (url_for('modules.module', mod='purchases'), SVG['package'], 'Purchase Orders'),
        'assets':      (url_for('modules.module', mod='assets'), SVG['settings'], 'Asset Register'),
        'maintenance': (url_for('modules.module', mod='maintenance'), SVG['settings'], 'Maintenance Jobs'),
        'security':    (url_for('modules.module', mod='security'), SVG['shield'], 'Security Center'),
        'users':       (url_for('modules.module', mod='users'), SVG['users'], 'User Management'),
        'gldash':      (url_for('modules.module', mod='gldash'), SVG['bar-chart'], 'GL Dashboard'),
    }

    LAYOUT_QA = {
        'super_admin':    ['patients', 'invoices', 'payalloc', 'lab', 'radiology', 'syshealth'],
        'branch_manager': ['patients', 'invoices', 'payalloc', 'queue', 'findash'],
        'accountant':     ['invoices', 'payalloc', 'findash', 'acct', 'audit'],
        'reception':      ['patients', 'queue', 'reqboard', 'invoices', 'payalloc'],
        'cashier':        ['payalloc', 'invoices', 'queue', 'findash'],
        'doctor':         ['queue', 'reqboard', 'lab', 'radiology'],
        'lab_tech':       ['lab', 'inventory', 'labqc'],
        'lab_supervisor': ['lab', 'inventory', 'labqc', 'audit'],
        'radiologist':    ['radiology', 'pacs', 'ris'],
        'nurse':          ['queue', 'ed', 'ipd'],
        'hr':             ['employees', 'hr', 'leave', 'payroll'],
        'storekeeper':    ['inventory', 'suppliers', 'purchases'],
        'engineer':       ['assets', 'maintenance', 'syshealth'],
        'it_admin':       ['security', 'audit', 'users', 'syshealth'],
        'auditor':        ['audit', 'acct', 'findash', 'gldash'],
    }

    role_qa_keys = LAYOUT_QA.get(role)
    if role_qa_keys is None:
        role_qa_keys = ['patients', 'queue', 'invoices', 'payalloc', 'lab', 'radiology']

    qa_btns = ''.join(f"<a class='qa' href='{u_}'><span class='qa-i'>{ic}</span>{lb}</a>"
                      for k_ in role_qa_keys[:6] if k_ in QA_MAP and can(k_)
                      for u_, ic, lb in [QA_MAP[k_]])
    qa = (f"<div class='panel qa-wrap'><div class='pad'>"
          f"<div class='sec-lbl'>Quick Actions · Shaqo Degdeg ah</div>"
          f"<div class='qas'>{qa_btns}</div></div></div>") if qa_btns else ''

    # ---- "Needs Attention Today" (Dynamic Actionable Chips with SVG Icons) ----
    due_list = []
    _overdue_n = 0
    if can('invoices'):
        due_list = [i for i in inv if i.balance > 0.005 and i.due_date and i.due_date <= today_s and i.status != 'Cancelled']
        due_list.sort(key=lambda i: i.due_date or '')
        _overdue_n = len(due_list)

    _att = []
    def _achip(cond, cls, icon_key, label, mod):
        if cond and can(mod):
            ic_s = SVG.get(icon_key, '')
            _att.append(f"<a class='att-chip {cls}' href='{url_for('modules.module', mod=mod)}'>{ic_s} {label}</a>")

    _achip(waiting, 'am', 'clock', f"{waiting} waiting", 'queue')
    _achip(unpaid_count, 'am', 'invoice', f"{unpaid_count} unpaid", 'invoices')
    _achip(_overdue_n, 'rd', 'phone', f"{_overdue_n} loans overdue", 'invoices')
    _achip(new_referrals, 'bl', 'file', f"{new_referrals} new referrals", 'reqboard')
    _achip(pending_lab, 'tl', 'flask', f"{pending_lab} lab pending", 'lab')
    _achip(pending_rad, 'am', 'camera', f"{pending_rad} radiology pending", 'radiology')
    _achip(lowstock, 'am', 'package', f"{lowstock} low stock", 'inventory')
    _achip(pending_leave, 'bl', 'calendar', f"{pending_leave} leave to approve", 'leave')

    _ATTCSS = """<style>
    .att-wrap{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:2px 4px 14px}
    .att-lbl{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-right:2px}
    .att-chip{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:20px;font-size:13px;font-weight:600;text-decoration:none;border:1px solid var(--line)}
    .att-chip.am{background:#FEF3E7;color:#B45309;border-color:#F5C98A}
    .att-chip.rd{background:#FDECEC;color:#C0392B;border-color:#E9B0A8}
    .att-chip.bl{background:#EAF0F7;color:#1A3E8F;border-color:#B9C9E5}
    .att-chip.tl{background:#E6F4F5;color:#0E7C86;border-color:#A9D9DD}
    .att-chip.ok{background:#EAF3EC;color:#1FA66D;border-color:#A9D9BC}
    </style>"""
    if _att:
        attention = _ATTCSS + "<div class='att-wrap'><span class='att-lbl'>Needs attention</span>" + ''.join(_att) + "</div>"
    else:
        attention = _ATTCSS + f"<div class='att-wrap'><span class='att-chip ok'>{SVG['check-circle']} All clear — nothing needs attention right now</span></div>"

    # ---- Alerts (Overdue Loans / Credit Call Alerts) ----
    alert = ''
    if lowstock and can('inventory'):
        alert += f"<div class='panel' style='border-left:3px solid var(--amber);margin-bottom:12px'><div class='pad'>{SVG['alert-triangle']} <b>{lowstock}</b> supply item(s) at/below reorder level. <a href='{url_for('modules.module',mod='inventory')}' style='color:var(--amber-dk);font-weight:600'>Check inventory →</a></div></div>"

    if due_list and can('invoices'):
        rows = ''.join(
            "<div style='display:flex;justify-content:space-between;align-items:center;gap:10px;"
            "padding:7px 0;border-top:1px solid var(--line);font-size:13px'>"
            f"<span>{SVG['phone']} <b>{h(i.patient.name if i.patient else 'Walk-in')}</b> "
            f"<a href='tel:{h((i.patient.phone or '') if i.patient else '')}' style='color:var(--petrol);font-weight:600'>"
            f"{h((i.patient.phone or '—') if i.patient else '—')}</a> · INV-{i.id:04d}</span>"
            f"<span style='white-space:nowrap'><b>{money(i.balance)}</b> · due {h(i.due_date)} "
            f"<a class='btn gh sm' href='{url_for('billing.invoice_view', iid=i.id)}'>Open</a></span></div>"
            for i in due_list[:15])
        alert += (
            "<div class='panel' style='border-left:3px solid var(--red);margin-bottom:12px'><div class='pad'>"
            f"<b style='color:var(--red)'>{SVG['phone']} {len(due_list)} credit account(s) have reached their due date</b> "
            "— please call the customer to collect the outstanding balance."
            f"{rows}</div></div>")

    # ---- Primary Worklist Section (Role-Specific Worktable) ----
    worklist_html = ''
    if role in ('reception', 'nurse'):
        q_rows = ''.join(
            f"<tr><td><b>{h(a.patient.mrn if a.patient else '—')}</b></td>"
            f"<td>{plink(a.patient)}</td>"
            f"<td>{h(a.type or 'Consultation')}</td>"
            f"<td><span class='pill amber'>{h(a.status)}</span></td>"
            f"<td><a class='btn sm primary' href='{url_for('modules.module', mod='queue')}'>Process</a></td></tr>"
            for a in waiting_list
        )
        worklist_html = (
            f"<div class='panel'><div class='ph'><h2>Active Waiting Queue</h2><span class='so'>{waiting} waiting</span></div>"
            f"<div class='tw'><table><thead><tr><th>MRN</th><th>Patient</th><th>Type</th><th>Status</th><th>Action</th></tr></thead>"
            f"<tbody>{q_rows or '<tr><td colspan=5 style=color:var(--muted);padding:14px>No patients in waiting queue.</td></tr>'}</tbody></table></div></div>"
        )
    elif role == 'cashier':
        inv_rows = ''.join(
            f"<tr><td><a href='{url_for('billing.invoice_view', iid=i.id)}' style='color:var(--petrol);font-weight:600'>INV-{i.id:04d}</a></td>"
            f"<td>{h(i.date)}</td>"
            f"<td>{h(i.patient.name if i.patient else 'Walk-in')}</td>"
            f"<td class='num'>{money(i.total)}</td>"
            f"<td class='num' style='color:var(--red);font-weight:600'>{money(i.balance)}</td>"
            f"<td><a class='btn sm primary' href='{url_for('billing.invoice_view', iid=i.id)}'>Receive Payment</a></td></tr>"
            for i in unpaid_invoices[:10]
        )
        worklist_html = (
            f"<div class='panel'><div class='ph'><h2>Pending Payment Invoices</h2><span class='so'>{unpaid_count} unpaid</span></div>"
            f"<div class='tw'><table><thead><tr><th>Invoice</th><th>Date</th><th>Patient</th><th>Total</th><th>Balance</th><th>Action</th></tr></thead>"
            f"<tbody>{inv_rows or '<tr><td colspan=6 style=color:var(--muted);padding:14px>No unpaid invoices pending.</td></tr>'}</tbody></table></div></div>"
        )
    elif role == 'doctor':
        doc_rows = ''.join(
            f"<tr><td><b>REF-{r.id:04d}</b></td>"
            f"<td>{h(r.date)}</td>"
            f"<td>{plink(r.patient)}</td>"
            f"<td>{h(r.notes or 'Doctor Request')}</td>"
            f"<td><span class='pill teal'>{h(r.status)}</span></td>"
            f"<td><a class='btn sm primary' href='{url_for('modules.module', mod='reqboard')}'>Examine</a></td></tr>"
            for r in new_referrals_list
        )
        worklist_html = (
            f"<div class='panel'><div class='ph'><h2>Pending Doctor Requests</h2><span class='so'>{new_referrals} requests</span></div>"
            f"<div class='tw'><table><thead><tr><th>Ref ID</th><th>Date</th><th>Patient</th><th>Details</th><th>Status</th><th>Action</th></tr></thead>"
            f"<tbody>{doc_rows or '<tr><td colspan=6 style=color:var(--muted);padding:14px>No pending requests right now.</td></tr>'}</tbody></table></div></div>"
        )
    elif role in ('lab_tech', 'lab_supervisor'):
        l_rows = ''.join(
            f"<tr><td><b>{h(o.sample_no or ('LAB-%04d'%o.id))}</b></td>"
            f"<td>{plink(o.patient)}</td>"
            f"<td>{h(o.service.name if o.service else '—')}</td>"
            f"<td><span class='pill blue'>{h(o.status)}</span></td>"
            f"<td><a class='btn sm primary' href='{url_for('lab.lab_result', oid=o.id)}'>Process Result</a></td></tr>"
            for o in pending_lab_list
        )
        worklist_html = (
            f"<div class='panel'><div class='ph'><h2>Pending Laboratory Worklist</h2><span class='so'>{pending_samples} samples</span></div>"
            f"<div class='tw'><table><thead><tr><th>Sample / Order</th><th>Patient</th><th>Test Service</th><th>Status</th><th>Action</th></tr></thead>"
            f"<tbody>{l_rows or '<tr><td colspan=5 style=color:var(--muted);padding:14px>No pending laboratory orders.</td></tr>'}</tbody></table></div></div>"
        )
    elif role == 'radiologist':
        r_rows = ''.join(
            f"<tr><td><b>RAD-{o.id:04d}</b></td>"
            f"<td>{plink(o.patient)}</td>"
            f"<td>{h(o.modality or '')} {h(o.service.name if o.service else '')}</td>"
            f"<td><span class='pill teal'>{h(o.status)}</span></td>"
            f"<td><a class='btn sm primary' href='{url_for('rad.rad_thread', oid=o.id)}'>Write Report</a></td></tr>"
            for o in pending_rad_list
        )
        worklist_html = (
            f"<div class='panel'><div class='ph'><h2>Unreported Radiology Worklist</h2><span class='so'>{pending_rad} pending</span></div>"
            f"<div class='tw'><table><thead><tr><th>Rad ID</th><th>Patient</th><th>Modality / Study</th><th>Status</th><th>Action</th></tr></thead>"
            f"<tbody>{r_rows or '<tr><td colspan=5 style=color:var(--muted);padding:14px>No pending radiology studies.</td></tr>'}</tbody></table></div></div>"
        )
    elif role in ('accountant', 'branch_manager'):
        due_rows = ''.join(
            f"<tr><td><a href='{url_for('billing.invoice_view', iid=i.id)}' style='color:var(--petrol);font-weight:600'>INV-{i.id:04d}</a></td>"
            f"<td>{h(i.patient.name if i.patient else 'Walk-in')}</td>"
            f"<td>{h(i.guarantor or '—')}</td>"
            f"<td class='num'>{money(i.total)}</td>"
            f"<td class='num' style='color:var(--red);font-weight:600'>{money(i.balance)}</td>"
            f"<td>{h(i.due_date or '—')}</td>"
            f"<td><a class='btn sm gh' href='{url_for('billing.invoice_view', iid=i.id)}'>View Invoice</a></td></tr>"
            for i in (due_list if due_list else unpaid_invoices[:10])
        )
        worklist_html = (
            f"<div class='panel'><div class='ph'><h2>Overdue & Unpaid Credit Accounts</h2><span class='so'>{len(due_list) or unpaid_count} records</span></div>"
            f"<div class='tw'><table><thead><tr><th>Invoice</th><th>Patient</th><th>Guarantor</th><th>Total</th><th>Balance</th><th>Due Date</th><th>Action</th></tr></thead>"
            f"<tbody>{due_rows or '<tr><td colspan=7 style=color:var(--muted);padding:14px>No overdue credit accounts.</td></tr>'}</tbody></table></div></div>"
        )
    elif role == 'hr':
        leave_rows = ''.join(
            f"<tr><td><b>{h(l.emp.name if hasattr(l, 'emp') and l.emp else ('Emp #%s'%l.employee_id))}</b></td>"
            f"<td>{h(l.type or 'Leave')}</td>"
            f"<td>{h(l.start_date)} to {h(l.end_date)}</td>"
            f"<td><span class='pill amber'>{h(l.status)}</span></td>"
            f"<td><a class='btn sm primary' href='{url_for('modules.module', mod='leave')}'>Review</a></td></tr>"
            for l in pending_leave_list
        )
        worklist_html = (
            f"<div class='panel'><div class='ph'><h2>Pending Leave Requests</h2><span class='so'>{pending_leave} pending</span></div>"
            f"<div class='tw'><table><thead><tr><th>Employee</th><th>Type</th><th>Dates</th><th>Status</th><th>Action</th></tr></thead>"
            f"<tbody>{leave_rows or '<tr><td colspan=5 style=color:var(--muted);padding:14px>No pending leave requests.</td></tr>'}</tbody></table></div></div>"
        )
    elif role == 'storekeeper':
        med_rows = ''.join(
            f"<tr><td><b>{h(m.name)}</b></td>"
            f"<td>{h(getattr(m, 'category', 'Supply'))}</td>"
            f"<td class='num' style='color:var(--red);font-weight:600'>{m.qty}</td>"
            f"<td class='num'>{m.reorder}</td>"
            f"<td><a class='btn sm primary' href='{url_for('modules.module', mod='inventory')}'>Restock</a></td></tr>"
            for m in lowstock_list
        )
        worklist_html = (
            f"<div class='panel'><div class='ph'><h2>Low Stock Items Needing Reorder</h2><span class='so'>{lowstock} items</span></div>"
            f"<div class='tw'><table><thead><tr><th>Item Name</th><th>Category</th><th>Current Stock</th><th>Reorder Level</th><th>Action</th></tr></thead>"
            f"<tbody>{med_rows or '<tr><td colspan=5 style=color:var(--muted);padding:14px>All inventory items are well stocked.</td></tr>'}</tbody></table></div></div>"
        )
    elif role in ('it_admin', 'auditor'):
        aud_rows = ''.join(
            f"<tr><td>{h(a.ts.strftime('%d-%b %H:%M:%S') if a.ts else '—')}</td>"
            f"<td><b>{h(a.user)}</b></td>"
            f"<td><span class='pill blue'>{h(a.action_type or 'Event')}</span></td>"
            f"<td>{h(a.action)}</td>"
            f"<td><small style='color:var(--muted)'>{h(a.ip or '—')}</small></td></tr>"
            for a in recent_audits
        )
        worklist_html = (
            f"<div class='panel'><div class='ph'><h2>Recent System Security & Audit Events</h2><span class='so'>{audits_today} today</span></div>"
            f"<div class='tw'><table><thead><tr><th>Timestamp</th><th>User</th><th>Type</th><th>Action</th><th>IP Address</th></tr></thead>"
            f"<tbody>{aud_rows or '<tr><td colspan=5 style=color:var(--muted);padding:14px>No audit events recorded today.</td></tr>'}</tbody></table></div></div>"
        )

    # ---- Charts & Analytics Section ----
    months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    data = [sum(i.total for i in inv if (i.date or '')[:7] == f"{y}-{m:02d}") for m in range(1,13)]
    mx = max([1] + data); W_w, H_h, pad, bw = 680, 190, 24, (680 - 48) / 12; bars = ''
    for i_m, v in enumerate(data):
        bh = (v / mx) * (H_h - pad * 2); x = pad + i_m * bw + bw * 0.18; yy = H_h - pad - bh
        bars += f"<rect x='{x:.0f}' y='{yy:.0f}' width='{bw*0.64:.0f}' height='{bh:.0f}' rx='3' fill='{'#1E7FB8' if v>0 else '#E4EAEC'}'/><text x='{pad+i_m*bw+bw/2:.0f}' y='{H_h-8}' text-anchor='middle'>{months[i_m]}</text>"
    chart = f"<div class='panel'><div class='ph'><h2>Revenue Trend</h2><span class='so'>{y}</span></div><div class='pad'><svg class='chart' viewBox='0 0 {W_w} {H_h}'>{bars}</svg></div></div>"

    days = [(dt.date.today() - dt.timedelta(days=i_d)) for i_d in range(6, -1, -1)]
    dlabels = [d.strftime('%a') for d in days]
    dcounts = [pat_query.filter(db.func.date(Patient.created) == d.isoformat()).count() for d in days] if hasattr(Patient, 'created') else [0]*7
    dmx = max([1] + dcounts); dW, dH, dpad = 680, 190, 24
    dbw = (dW - 48) / 7; dbars = ''
    for i_d, v in enumerate(dcounts):
        bh = (v / dmx) * (dH - dpad * 2); x = dpad + i_d * dbw + dbw * 0.2; yy = dH - dpad - bh
        dbars += (f"<rect x='{x:.0f}' y='{yy:.0f}' width='{dbw*0.6:.0f}' height='{bh:.0f}' rx='3' fill='{'#044C8C' if v>0 else '#E4EAEC'}'/>"
                  f"<text x='{dpad+i_d*dbw+dbw/2:.0f}' y='{dH-8}' text-anchor='middle'>{dlabels[i_d]}</text>"
                  f"{f'<text x={dpad+i_d*dbw+dbw/2:.0f} y={yy-4:.0f} text-anchor=middle font-size=11 fill=#66757F>{v}</text>' if v else ''}")
    dchart = f"<div class='panel'><div class='ph'><h2>Daily Patient Registrations</h2><span class='so'>last 7 days</span></div><div class='pad'><svg class='chart' viewBox='0 0 {dW} {dH}'>{dbars}</svg></div></div>"

    def workload(model, name, statuses, color):
        m_query = branch_scope(model.query, model)
        counts = [(st, m_query.filter_by(status=st).count()) for st in statuses]
        wmx = max([1] + [n for _, n in counts])
        rows = ''.join(f"<div class='tt-row'><span class='tt-n'>{st}</span>"
                       f"<span class='tt-bar'><span style='width:{n/wmx*100:.0f}%;background:{color}'></span></span>"
                       f"<span class='tt-v'>{n}</span></div>" for st, n in counts)
        return f"<div class='panel'><div class='ph'><h2>{name} Workload</h2></div><div class='pad'>{rows}</div></div>"
    lab_wl = workload(LabOrder, 'Laboratory', ['Requested', 'Collected', 'Received', 'Resulted', 'Approved'], 'var(--teal)')
    rad_wl = workload(RadOrder, 'Radiology', ['Requested', 'Imaged', 'Reported'], 'var(--amber)')

    analytics = ''
    if role in ('accountant', 'branch_manager', 'super_admin', 'auditor'):
        analytics = f"<div class='grid2'>{chart}{dchart}</div><div class='grid2'>{lab_wl}{rad_wl}</div>"
    elif role in ('lab_tech', 'lab_supervisor'):
        analytics = f"<div class='grid2'>{lab_wl}{dchart}</div>"
    elif role == 'radiologist':
        analytics = f"<div class='grid2'>{rad_wl}{dchart}</div>"
    elif role in ('reception', 'cashier'):
        analytics = f"<div class='grid2'>{dchart}<div></div></div>"

    # ---- Category Module Launcher Cards (Odoo-Style Groups with Clean SVG Icons) ----
    CATS = [
        ("Patient Management", SVG['user'], "var(--blue)", [
            ('patients','Registration'), ('queue','Queue'), ('reqboard','Doctor Requests'),
            ('consult','Consultation'), ('referrals','Referrals')]),
        ("Laboratory", SVG['flask'], "var(--teal)", [
            ('lab','Lab Requests'), ('labqc','Quality Control'), ('donors','Blood Bank')]),
        ("Radiology", SVG['camera'], "var(--red)", [
            ('radiology','Radiology'), ('doctors','Referring Doctors')]),
        ("Billing & Finance", SVG['dollar'], "var(--green)", [
            ('invoices','Invoices'), ('acct','Accounting'), ('findash','Financial Dashboard'),
            ('revreport','Revenue Analysis')]),
        ("Inventory & Pharmacy", SVG['package'], "var(--amber)", [
            ('pharmacy','Pharmacy'), ('suppliers','Inventory'), ('batches','Batches'),
            ('stockvalue','Valuation')]),
        ("Human Resources", SVG['users'], "var(--petrol)", [
            ('employees','Employees'), ('contracts','Contracts'), ('users','User Management')]),
        ("Quality & Compliance", SVG['target'], "var(--teal)", [
            ('sops','SOPs'), ('incidents','Incidents'), ('audits','Internal Audits'),
            ('feedback','Feedback')]),
        ("Administration", SVG['settings'], "var(--muted)", [
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
    cats_html = f"<div class='sec-lbl' style='margin:18px 4px 8px'>Modules</div><div class='cats'>{cat_cards}</div>" if cat_cards else ""

    intro = f"<div class='sec-lbl' style='margin:2px 4px 12px;font-size:13px'>{h(role_name)} Dashboard</div>"
    return page('Dashboard', intro + attention + alert + qa + widgets_html + worklist_html + analytics + cats_html, 'dashboard')


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
        pats=branch_scope(Patient.query.filter(db.or_(Patient.name.ilike(like),Patient.phone.ilike(like),Patient.mrn.ilike(like),Patient.gov_id.ilike(like))), Patient).order_by(Patient.name).limit(20).all()
        pat_ids=[p.id for p in pats]
        qn=q.upper().replace('INV-','').lstrip('0'); seen=set()
        if qn.isdigit():
            iv=branch_scope(Invoice.query, Invoice).filter_by(id=int(qn)).first()
            if iv: invs.append(iv); seen.add(iv.id)
        ql = q.lower()
        for iv in (branch_scope(Invoice.query.filter(Invoice.guarantor.ilike(like)), Invoice)
                   .order_by(Invoice.id.desc()).limit(20).all()):
            if iv.id not in seen:
                invs.append(iv); seen.add(iv.id)
        for iv in branch_scope(Invoice.query, Invoice).order_by(Invoice.id.desc()).limit(400).all():
            if iv.id in seen: continue
            if iv.patient and ql in (iv.patient.name or '').lower():
                invs.append(iv); seen.add(iv.id)
            if len(invs)>=20: break
        qs=q.upper().replace('LAB-','').replace('SMP-','').lstrip('0')
        for o in branch_scope(LabOrder.query, LabOrder).order_by(LabOrder.id.desc()).limit(300).all():
            if (o.sample_no and q.upper() in o.sample_no.upper()) or o.patient_id in pat_ids or (qs.isdigit() and o.id==int(qs)):
                labs.append(o)
            if len(labs)>=15: break
        qr=q.upper().replace('RAD-','').lstrip('0')
        for o in branch_scope(RadOrder.query, RadOrder).order_by(RadOrder.id.desc()).limit(300).all():
            if o.patient_id in pat_ids or (qr.isdigit() and o.id==int(qr)):
                rads.append(o)
            if len(rads)>=15: break
        docs=Doctor.query.filter(Doctor.name.ilike(like)).limit(10).all()
        rdocs=Radiologist.query.filter(Radiologist.name.ilike(like)).limit(10).all()
        docs=[('Doctor',x) for x in docs]+[('Radiologist',x) for x in rdocs]
        emps=branch_scope(Employee.query.filter(Employee.name.ilike(like)), Employee).limit(10).all()
        sups=Supplier.query.filter(Supplier.name.ilike(like)).limit(10).all()
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
        for o in labs:
            if o.status=='Approved': reps.append(('Lab',o))
        for o in rads:
            if o.status=='Reported': reps.append(('Radiology',o))
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


APP_CATALOG = [
    ("Patient Management", SVG['user'], "var(--blue)", [
        ('patients', 'Patient Registration', 'Diiwaangelin bukaan'),
        ('queue', 'Reception Queue', 'Safka qaabilaadda'),
        ('tokenq', 'Token Queue &amp; Display', 'Safka tigidhada'),
        ('reqboard', 'Doctor Requests', 'Codsiyada dhakhtarka'),
        ('referrals', 'New Doctor Request', 'Gudbin cusub'),
        ('consult', 'Consultation', 'La-tashi'),
        ('doctors', 'Referring Doctors', 'Dhakhtarrada gudbiya'),
    ]),
    ("Emergency &amp; Wards", SVG['user'], "var(--red)", [
        ('ed', 'Emergency Department', 'Gargaarka degdegga'),
        ('ipd', 'Inpatient / Admissions', 'Bukaan-jiifka'),
        ('ot', 'Operation Theatre', 'Qolka qalliinka'),
        ('dialysis', 'Dialysis', 'Dialysis-ka'),
        ('wards', 'Wards', 'Qolalka'),
        ('beds', 'Beds', 'Sariiraha'),
        ('theatres', 'Operating Theatres', 'Qolalka qalliinka'),
        ('dmachines', 'Dialysis Machines', 'Mashiinnada dialysis'),
    ]),
    ("Ambulance", SVG['user'], "var(--amber-dk)", [
        ('ambulance', 'Ambulance Dispatch', 'Ambalaas'),
        ('vehicles', 'Ambulances (fleet)', 'Gaadiidka'),
        ('drivers_amb', 'Drivers', 'Darawallada'),
    ]),
    ("Laboratory", SVG['flask'], "var(--teal)", [
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
    ("Radiology", SVG['camera'], "var(--red)", [
        ('radiology', 'Radiology / Imaging', 'Raajada'),
        ('ris', 'RIS · Imaging Worklist', 'Liiska raajada'),
        ('pacs', 'PACS / DICOM Viewer', 'Sawirrada DICOM'),
        ('modalities', 'Imaging Modalities', 'Qalabka raajada'),
    ]),
    ("Billing & Cashier", SVG['dollar'], "var(--green)", [
        ('invoices', 'Invoices', 'Biilasha'),
        ('dailytx', 'Daily Transactions', 'Dhaqdhaqaaqa maalinlaha'),
        ('payalloc', 'Receive Payment', 'Lacag qaad'),
        ('creditnotes', 'Credit Notes', 'Warqadaha deynta'),
        ('cashclose', 'Daily Cash Closing', 'Xir maalinta'),
        ('commission', 'Doctor Commission', 'Kaalmada dhakhtarka'),
        ('services', 'Service Catalog', 'Liiska adeegyada'),
    ]),
    ("Insurance", SVG['shield'], "var(--teal)", [
        ('insurance', 'Claims', 'Sheegashooyinka'),
        ('insurers', 'Insurance Companies', 'Shirkadaha caymiska'),
        ('inscards', 'Insurance Cards', 'Kaararka caymiska'),
        ('coverage', 'Coverage Rules', 'Xeerarka daboolka'),
    ]),
    ("Accounting", SVG['bar-chart'], "var(--petrol)", [
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
    ("Inventory & Pharmacy", SVG['package'], "var(--amber)", [
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
    ("Human Resources", SVG['users'], "var(--blue)", [
        ('hr', 'HR Dashboard', 'HR-ka guud'),
        ('employees', 'Employees', 'Shaqaalaha'),
        ('attendance', 'Attendance', 'Xaadirinta'),
        ('leave', 'Leave', 'Fasaxa'),
        ('payroll', 'Payroll', 'Mushaharka'),
        ('contracts', 'Contracts', 'Qandaraasyada'),
    ]),
    ("Assets & Maintenance", SVG['settings'], "var(--teal)", [
        ('maintdash', 'Maintenance Overview', 'Guud ahaan dayactirka'),
        ('assets', 'Asset Register', 'Diiwaanka hantida'),
        ('maintenance', 'Maintenance Jobs', 'Hawlaha dayactirka'),
    ]),
    ("Quality & Compliance", SVG['target'], "var(--teal)", [
        ('sops', 'SOPs & Documents', 'Hab-raacyada'),
        ('incidents', 'Incidents', 'Dhacdooyinka'),
        ('audits', 'Internal Audits', 'Hubinta gudaha'),
        ('feedback', 'Patient Feedback', 'Ra\'yiga bukaanka'),
    ]),
    ("Reports", SVG['bar-chart'], "var(--green)", [
        ('reports', 'Reports Overview', 'Warbixinnada'),
        ('summary', 'Summary (date range)', 'Kooban'),
        ('revenue', 'Revenue Analysis', 'Dakhliga'),
        ('productivity', 'Productivity', 'Wax-soo-saarka'),
        ('radfees', 'Radiologist Fees', 'Kharashka raajada'),
        ('branchcmp', 'Branch Comparison', 'Isbarbardhig laamaha'),
    ]),
    ("Administration", SVG['settings'], "var(--muted)", [
        ('users', 'User Management', 'Maamulka isticmaalayaasha'),
        ('settings', 'Settings', 'Dejinta'),
        ('audit', 'Audit Logs', 'Diiwaanka hawlaha'),
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
