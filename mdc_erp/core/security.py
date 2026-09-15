"""Authentication, roles, permissions, audit logging and CSRF helpers."""
import json
import secrets
from functools import wraps
from flask import session, redirect, url_for, has_request_context
from ..extensions import db
from ..models import User, Setting, Audit

ROLES = ['super_admin','branch_manager','accountant','reception','cashier','doctor','radiologist',
         'lab_tech','lab_supervisor','nurse','hr','storekeeper','engineer','it_admin','auditor']
ROLE_LABEL = {'super_admin':'Super Admin','branch_manager':'Branch Manager','accountant':'Accountant',
              'reception':'Reception','cashier':'Cashier','doctor':'Doctor','radiologist':'Radiologist',
              'lab_tech':'Lab Technician','lab_supervisor':'Laboratory Supervisor','nurse':'Nurse',
              'hr':'HR Manager','storekeeper':'Storekeeper','engineer':'Maintenance Engineer',
              'it_admin':'IT Administrator','auditor':'Auditor'}
PERMS = {
 'dashboard': ROLES,
 'apps': ROLES,
 'chat': ROLES,
 'patients': ['super_admin','reception','doctor','cashier','accountant','radiologist','lab_tech'],
 'appointments': ['super_admin','reception','doctor'],
 'queue': ['super_admin','branch_manager','reception','doctor'],
 'lab': ['super_admin','lab_tech','doctor','reception'],
 'critical': ['super_admin','lab_tech','doctor'],
 'labtests': ['super_admin','lab_tech','lab_supervisor','doctor','reception','accountant','radiologist'],
 'labqc': ['super_admin','lab_tech','doctor','reception'],
 'radiology': ['super_admin','radiologist','doctor','reception'],
 'pacs': ['super_admin','radiologist','doctor','reception','lab_tech','it_admin'],
 'ris': ['super_admin','radiologist','doctor','reception','lab_tech'],
 'modalities': ['super_admin','it_admin','branch_manager','radiologist'],
 'insurance': ['super_admin','accountant','reception','cashier','branch_manager'],
 'insurers': ['super_admin','accountant','branch_manager'],
 'inscards': ['super_admin','accountant','reception','cashier'],
 'coverage': ['super_admin','accountant','branch_manager'],
 'lis': ['super_admin','lab_tech','doctor','reception'],
 'instruments': ['super_admin','lab_tech','it_admin','branch_manager'],
 'tokenq': ['super_admin','reception','doctor','nurse','lab_tech','cashier'],
 'ed': ['super_admin','doctor','nurse','reception'],
 'ipd': ['super_admin','doctor','nurse','reception'],
 'wards': ['super_admin','doctor','nurse','branch_manager','reception'],
 'beds': ['super_admin','doctor','nurse','branch_manager','reception'],
 'ot': ['super_admin','doctor','nurse'],
 'theatres': ['super_admin','doctor','branch_manager'],
 'dialysis': ['super_admin','doctor','nurse'],
 'dmachines': ['super_admin','doctor','nurse','branch_manager'],
 'ambulance': ['super_admin','reception','nurse','doctor','branch_manager'],
 'vehicles': ['super_admin','branch_manager','it_admin'],
 'drivers_amb': ['super_admin','branch_manager','hr'],
 'bloodbank': ['super_admin','lab_tech','doctor','nurse','reception'],
 'analytics': ['super_admin','accountant','branch_manager'],
 'security': ['super_admin','it_admin'],
 'branchhub': ['super_admin','it_admin','auditor','branch_manager'],
 'doctors': ['super_admin','reception','accountant'],
 'commission': ['super_admin','accountant','reception'],
 'payables': ['super_admin','accountant','branch_manager'],
 'paycenter': ['super_admin','accountant','branch_manager','reception'],
 'integrity': ['super_admin','accountant'],
 'inventory': ['super_admin','storekeeper','accountant','reception'],
 'purchases': ['super_admin','storekeeper','accountant','reception'],
 'referrals': ['super_admin','reception','doctor','accountant'],
 'reqboard': ['super_admin','reception','doctor','accountant'],
 'advances': ['super_admin','hr','accountant'],
 'loans': ['super_admin','hr','accountant'],
 'logistics': ['super_admin','storekeeper','reception','accountant'],
 'consult': ['super_admin','doctor','reception'],
 'prescriptions': ['super_admin','doctor','reception','cashier'],
 'pharmacy': ['super_admin','cashier','storekeeper','reception'],
 'radfees': ['super_admin','accountant','radiologist'],
 'summary': ['super_admin','accountant','hr','reception'],
 'revenue': ['super_admin','accountant','reception'],
 'acct': ['super_admin','accountant'],
 'bankrec': ['super_admin','accountant'],
 'acctdash': ['super_admin','accountant','auditor','branch_manager'],
 'accounts': ['super_admin','accountant','reception'],
 'journal': ['super_admin','accountant'],
 'acctguide': ['super_admin','accountant','auditor'],
 'ledger': ['super_admin','accountant','reception'],
 'genledger': ['super_admin','accountant','auditor'],
 'gldash': ['super_admin','accountant','auditor'],
 'jitems': ['super_admin','accountant','auditor'],
 'jentries': ['super_admin','accountant','auditor'],
 'trialbal': ['super_admin','accountant','auditor'],
 'acctbal': ['super_admin','accountant','auditor'],
 'partnerledger': ['super_admin','accountant','reception'],
 'suppliers': ['super_admin','storekeeper','accountant','reception'],
 'invoices': ['super_admin','cashier','accountant','reception'],
 'expenses': ['super_admin','accountant'],
 'finance': ['super_admin','accountant'],
 'services': ['super_admin','accountant'],
 'employees': ['super_admin','hr'],
 'attendance': ['super_admin','hr'],
 'hr': ['super_admin','hr','accountant'],
 'leave': ['super_admin','hr'],
 'payroll': ['super_admin','hr','accountant'],
 'reports': ['super_admin','accountant','hr','reception'],
 'productivity': ['super_admin','accountant','hr'],
 'stockvalue': ['super_admin','storekeeper','accountant'],
 'assets': ['super_admin','branch_manager','storekeeper','accountant','it_admin','engineer'],
 'fa_dash': ['super_admin','it_admin','accountant','branch_manager','storekeeper','engineer','reception'],
 'fa_register': ['super_admin','it_admin','accountant','branch_manager','storekeeper','engineer','reception'],
 'fa_purchase': ['super_admin','it_admin','accountant','branch_manager'],
 'fa_categories': ['super_admin','it_admin','accountant','branch_manager'],
 'fa_depreciation': ['super_admin','it_admin','accountant','branch_manager'],
 'fa_depjournal': ['super_admin','it_admin','accountant','branch_manager'],
 'fa_transfer': ['super_admin','it_admin','accountant','branch_manager','storekeeper'],
 'fa_maintenance': ['super_admin','it_admin','accountant','branch_manager','storekeeper','engineer'],
 'fa_disposal': ['super_admin','it_admin','accountant','branch_manager'],
 'fa_revaluation': ['super_admin','it_admin','accountant','branch_manager'],
 'fa_reports': ['super_admin','it_admin','accountant','branch_manager','reception'],
 'fa_settings': ['super_admin','it_admin','accountant'],
 'maintdash': ['super_admin','branch_manager','storekeeper','accountant','it_admin','engineer'],
 'maintenance': ['super_admin','branch_manager','storekeeper','it_admin','engineer'],
 'branchcmp': ['super_admin','branch_manager','accountant'],
 'cashclose': ['super_admin','branch_manager','cashier','accountant','reception'],
 'dailytx': ['super_admin','branch_manager','cashier','accountant','reception'],
 'reopenday': ['super_admin','branch_manager','accountant'],
 'payalloc': ['super_admin','branch_manager','cashier','accountant'],
 'discounts': ['super_admin','branch_manager','accountant'],
 'creditnotes': ['super_admin','accountant','reception'],
 'debitnotes': ['super_admin','accountant','storekeeper','reception'],
 'banks': ['super_admin','accountant'],
 'bankrecon': ['super_admin','accountant'],
 'budgets': ['super_admin','accountant','branch_manager'],
 'budgetreport': ['super_admin','accountant','branch_manager','auditor'],
 'costcenters': ['super_admin','accountant'],
 'ccreport': ['super_admin','accountant','branch_manager','auditor'],
 'ratios': ['super_admin','accountant','branch_manager','auditor'],
 'fiscal': ['super_admin','accountant'],
 'taxreport': ['super_admin','accountant','auditor'],
 'currencies': ['super_admin','accountant'],
 'araging': ['super_admin','accountant','auditor'],
 'apaging': ['super_admin','accountant','auditor'],
 'cashflow': ['super_admin','accountant','auditor'],
 'stockadj': ['super_admin','storekeeper','accountant','reception'],
 'consume': ['super_admin','storekeeper','accountant','reception'],
 'warehouses': ['super_admin','branch_manager','storekeeper'],
 'transfers': ['super_admin','branch_manager','storekeeper','reception'],
 'consumption': ['super_admin','storekeeper','accountant','branch_manager','reception'],
 'users': ['super_admin'],
 'branches': ['super_admin'],
 'audit': ['super_admin'],
 'errorlog': ['super_admin','it_admin'],
 'syshealth': ['super_admin','it_admin'],
 'recurjournals': ['super_admin','accountant'],
 'revreport': ['super_admin','accountant','branch_manager','auditor'],
 'findash': ['super_admin','accountant','branch_manager','auditor'],
 'radiologists': ['super_admin','it_admin','branch_manager','radiologist'],
 'donors': ['super_admin','lab_tech','doctor','reception'],
 'bloodunits': ['super_admin','lab_tech','doctor','reception'],
 'vaccinations': ['super_admin','reception','doctor','cashier','accountant','radiologist','lab_tech'],
 'sops': ['super_admin','lab_tech','auditor'],
 'incidents': ['super_admin','lab_tech','auditor'],
 'audits': ['super_admin','auditor'],
 'feedback': ['super_admin'],
 'messages': ['super_admin','it_admin','branch_manager','reception'],
 'batches': ['super_admin','storekeeper','accountant','reception'],
 'contracts': ['super_admin','hr'],
 'performance': ['super_admin','hr'],
 'training': ['super_admin','hr'],
 'svccontracts': ['super_admin','branch_manager','storekeeper','accountant','it_admin','engineer'],
 'loginhistory': ['super_admin'],
 'backup': ['super_admin','it_admin'],
 'settings': ['super_admin'],
 'record_options': ['super_admin','it_admin','branch_manager','accountant','auditor'],
 'svcconfig': ['super_admin','it_admin','branch_manager'],
 'svcmgmt': ['super_admin','it_admin','branch_manager'],
}

# One authoritative registry is consumed by menus, route guards, search, and
# workflow checks. Fail early if a permission references a role that is not
# defined, rather than silently creating an orphan permission.
UNKNOWN_PERMISSION_ROLES = sorted({role for roles in PERMS.values() for role in roles if role not in ROLES})
if UNKNOWN_PERMISSION_ROLES:
    raise RuntimeError('Permission registry references undefined roles: ' + ', '.join(UNKNOWN_PERMISSION_ROLES))
ROLE_PERMISSIONS = {role: frozenset(permission for permission, roles in PERMS.items() if role in roles)
                    for role in ROLES}


def cur_user():
    if not has_request_context():
        return None
    uid = session.get('uid')
    if uid:
        return User.query.get(uid)
    # API requests carry no session — the JWT-authenticated user is attached to
    # the request by api_auth(). Falling back to it lets branch_scope()/can_see()
    # and can() enforce the same rules for API callers as for web sessions.
    from flask import request as _rq
    return getattr(_rq, 'api_user', None)
def perms_for(mod):
    """Effective role list for a module: admin-saved matrix overrides defaults."""
    s = Setting.query.get('perms_json')
    if s and s.value:
        try:
            data = json.loads(s.value)
            if mod in data:
                return data[mod]
        except Exception:
            pass
    return PERMS.get(mod, [])

def can(mod):
    u = cur_user()
    return bool(u and (u.role == 'super_admin' or u.role in perms_for(mod)))
def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not cur_user(): return redirect(url_for('auth.login'))
        return f(*a, **k)
    return w
def perm_required(mod):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if not cur_user(): return redirect(url_for('auth.login'))
            if not can(mod):
                from .ui import page
                return page('Access denied', "<div class='panel'><div class='pad'><b>No access.</b> Your role does not permit this section.</div></div>")
            return f(*a, **k)
        return w
    return deco
def _audit_type(action):
    """Classify a free-text action into one of the tracked categories."""
    a = (action or '').lower()
    if a.startswith('added') or a.startswith('created') or 'registered' in a: return 'Create'
    if a.startswith('edited') or a.startswith('updated'): return 'Edit'
    if a.startswith('deleted') or a.startswith('removed'): return 'Delete'
    if 'reset to draft' in a: return 'Reset Draft'
    if a.startswith('cancel') or 'cancelled' in a or 'voided' in a: return 'Cancel'
    if a.startswith('print'): return 'Print'
    if a.startswith('logout') or 'logged out' in a: return 'Logout'
    if a.startswith('login') or 'logged in' in a or 'signed in' in a: return 'Login'
    if 'payment' in a: return 'Payment'
    if 'approve' in a or 'reported' in a or 'workflow complete' in a: return 'Report Approval'
    if a.startswith('blocked') or a.startswith('denied'): return 'Blocked'
    return 'Other'


def log(action, action_type=None, entity=None, old=None, new=None, reason=None):
    """Write an audit record. Backward-compatible: log('some text') still works.
    Captures the acting user and request IP automatically, classifies the action,
    and optionally stores the before/after value and a reason."""
    u = cur_user()
    ip = None
    try:
        from flask import request, has_request_context
        if has_request_context():
            ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:64]
    except Exception:
        ip = None
    rec = Audit(user=(u.username if u else '—'), action=action,
                action_type=(action_type or _audit_type(action)),
                entity=(str(entity)[:60] if entity else None), ip=ip,
                old_value=(str(old)[:255] if old is not None else None),
                new_value=(str(new)[:255] if new is not None else None),
                reason=(str(reason)[:255] if reason else None))
    db.session.add(rec); db.session.commit()
def setting(key, default=''):
    """Read a setting, cached for the lifetime of one request.

    money() asks for the currency symbol on every amount it formats, so an
    uncached lookup meant ~100 SELECTs on a single invoice list. The cache
    lives on flask.g, so it can never go stale across requests."""
    try:
        from flask import g, has_request_context
        if has_request_context():
            cache = getattr(g, '_setting_cache', None)
            if cache is None:
                cache = {}
                g._setting_cache = cache
            if key in cache:
                v = cache[key]
                return default if v is None else v
            s = Setting.query.get(key)
            cache[key] = s.value if s else None
            return s.value if s else default
    except Exception:
        pass
    s = Setting.query.get(key)
    return s.value if s else default


def clear_setting_cache():
    """Call after writing settings so the rest of the request sees new values."""
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, '_setting_cache'):
            g._setting_cache.clear()
    except Exception:
        pass


def csrf_token():
    """Per-session CSRF token; created lazily on first HTML render."""
    tok = session.get('_csrf')
    if not tok:
        tok = secrets.token_urlsafe(24)
        session['_csrf'] = tok
    return tok


def doc_sig(ref):
    """Short HMAC signature for printed-document verification QR codes."""
    import hmac, hashlib
    from flask import current_app
    key = current_app.config['SECRET_KEY'].encode()
    return hmac.new(key, str(ref).encode(), hashlib.sha256).hexdigest()[:16]


COMMON_PW = {'12345678','password','admin123','qwerty123','11111111','password1'}

def pw_policy_error(pw):
    """Return an error string if the password violates policy, else None.

    Minimum length is configurable via the 'pw_min_len' setting (default 4)."""
    pw = pw or ''
    try:
        _min = int(setting('pw_min_len', '4') or 4)
    except Exception:
        _min = 4
    if len(pw) < _min:
        return f'Password must be at least {_min} characters'
    if pw.lower() in COMMON_PW:
        return 'Password is too common'
    if not any(c.isdigit() for c in pw):
        return 'Password must contain a number'
    return None


# ---------------------------------------------------------------- record scope
# Route permissions answer "may this role open this screen?". They do not answer
# "which rows may this person see?". Without the second question a cashier who
# can open Billing sees every branch's invoices. These helpers add that layer.

# roles that legitimately need to see every branch
CROSS_BRANCH_ROLES = {'super_admin', 'it_admin', 'auditor'}

# ---------------------------------------------------------------------------
# BRANCH ISOLATION SCOPE (#17)
# Branch-scoped models carry a `branch_id`; branch_scope()/can_see() below
# confine a branch user to their own rows on both list and detail routes.
# Financial + operational records ARE branch-scoped: Invoice, Expense, Asset,
# QueueTicket, Ward, Theatre, Surgery, Admission, EDVisit, DialysisSession,
# Ambulance/Dispatch, Insurer/Claim/PreAuth, Warehouse, LabInstrument,
# ImgModality/ImgStudy, User.
#
# DELIBERATELY NOT branch-scoped: the Patient master record and its clinical
# orders (LabOrder, RadOrder, Consultation, Appointment, PharmacySale). A
# patient may legitimately be seen at more than one branch, so the patient
# identity is shared organisation-wide; the *financial* consequences of each
# visit (the Invoice) are what get pinned to a branch. Making Patient
# branch-exclusive is a data-model policy decision (which branch "owns" a
# shared patient, how existing rows are back-filled) and must be made
# explicitly rather than assumed — it is intentionally left shared here.
# ---------------------------------------------------------------------------


def _is_cross(u):
    return bool(u) and (u.role in CROSS_BRANCH_ROLES or not u.branch_id)


def focus_branch():
    """The branch a cross-branch user has chosen to focus on (None = all).

    Only meaningful for cross-branch roles; branch-scoped users always see
    their own branch and ignore this. Defaults to None so behaviour is
    unchanged unless a focus is explicitly selected."""
    from flask import has_request_context
    if not has_request_context():
        return None
    try:
        v = session.get('focus_branch')
        return int(v) if v else None
    except Exception:
        return None


def effective_branch(u=None):
    """The branch whose rows the user should see right now."""
    u = u or cur_user()
    if not u:
        return None
    if _is_cross(u):
        return focus_branch()          # None = all branches
    return u.branch_id


def sees_all_branches(u=None):
    u = u or cur_user()
    if not u:
        return False
    if _is_cross(u):
        return focus_branch() is None  # a chosen focus narrows even admins
    return not u.branch_id


def branch_scope(query, model):
    """Limit a query to the signed-in user's branch (or chosen focus).

    Rows with no branch (legacy data written before branches existed, and
    shared reference data) stay visible to everyone so existing installs do
    not suddenly lose records."""
    u = cur_user()
    if not u or sees_all_branches(u) or not hasattr(model, 'branch_id'):
        return query
    eff = effective_branch(u)
    if eff is None:
        return query
    col = getattr(model, 'branch_id')
    return query.filter((col == eff) | (col.is_(None)))


def can_see(obj):
    """Row-level check for detail pages, so a direct URL cannot cross branches."""
    if obj is None:
        return False
    u = cur_user()
    if not u or sees_all_branches(u) or not hasattr(obj, 'branch_id'):
        return True
    eff = effective_branch(u)
    if eff is None:
        return True
    b = getattr(obj, 'branch_id', None)
    return b is None or b == eff
