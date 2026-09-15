"""Enterprise Fixed Assets Management — depreciation, accounting, maintenance,
transfers, revaluation, disposal, reports and dashboard, fully integrated with
the existing accounting engine and audit log. Backward compatible: the legacy
/m/assets register keeps working; this module adds the enterprise layer."""
import datetime as dt
from flask import Blueprint, request, redirect, url_for, flash, abort, render_template
from markupsafe import escape as h
from ..extensions import db
from ..models import (Asset, AssetCategory, AssetDepreciation, AssetTransfer,
                      AssetRevaluation, AssetDisposal, MaintenanceJob)
from ..core.security import cur_user, can, login_required, log
from ..core.helpers import money, today
from ..core.ui import page, smartbar, next_step
from ..core.posting import post_journal, acc_ensure

bp = Blueprint('fa', __name__)


def _sb(items):
    """smartbar wrapper: (label,url,style) with style=='hide' → skip."""
    out = []
    for it in items:
        lb, u = it[0], it[1]
        sty = it[2] if len(it) > 2 else ''
        if sty == 'hide' or not u:
            continue
        out.append((lb, u, sty, False))
    return smartbar(out)

FA_ODOO_CSS = """<style>
.oform{max-width:960px;margin:0 auto}
.osb{display:inline-flex;align-items:stretch;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.osb .s{padding:6px 15px 6px 20px;font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);background:var(--surface);display:flex;align-items:center;position:relative;white-space:nowrap}
.osb .s:first-child{padding-left:15px}
.osb .s:not(:first-child)::before{content:"";position:absolute;left:0;top:50%;width:9px;height:9px;transform:translate(-55%,-50%) rotate(45deg);background:var(--surface);border-right:1px solid var(--line);border-top:1px solid var(--line);z-index:1}
.osb .s.done{color:var(--petrol)}
.osb .s.cur{background:var(--petrol);color:#fff}.osb .s.cur::before{background:var(--petrol);border-color:var(--petrol)}
.osb .s.cur.run{background:var(--green)}.osb .s.cur.run::before{background:var(--green);border-color:var(--green)}
.osb .s.cur.closed{background:#8494a1}.osb .s.cur.closed::before{background:#8494a1;border-color:#8494a1}
.o-sheet{position:relative;overflow:hidden;background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:0 6px 24px rgba(2,48,90,.07);padding:24px 28px 28px}
.o-title{font-family:var(--fd);font-size:26px;font-weight:800;letter-spacing:-.4px;color:var(--ink);line-height:1.06}
.o-title small{display:block;font-size:12.5px;font-weight:600;color:var(--muted);margin-top:3px}
.o-stat{position:absolute;top:22px;right:26px;text-align:right}
.o-stat .l{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.o-stat .v{font-size:26px;font-weight:800;font-family:var(--fd);color:var(--green);line-height:1}
.o-head{display:grid;grid-template-columns:1fr 1fr;gap:6px 44px;margin:20px 0 4px}
@media(max-width:680px){.o-head{grid-template-columns:1fr}}
.o-row{display:flex;gap:10px;font-size:13.5px;padding:4px 0;align-items:baseline;border-bottom:1px dotted var(--line)}
.o-row .k{color:var(--muted);min-width:140px;flex:none}
.o-row .v{color:var(--ink);font-weight:600}
.o-sech{margin:20px 0 8px;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--petrol);border-bottom:2px solid var(--line);padding-bottom:6px}
.o-board{width:100%;border-collapse:collapse;font-size:13px}
.o-board thead th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--petrol);font-weight:700;padding:8px 10px;border-bottom:1px solid var(--line)}
.o-board th.num,.o-board td.num{text-align:right}
.o-board tbody td{padding:8px 10px;border-bottom:1px solid #eef0f2}
.o-board tr.posted{background:rgba(31,166,109,.07)}
.o-board tr.now{box-shadow:inset 3px 0 0 var(--amber)}
</style>"""


def _fa_statusbar(a):
    closed = a.status in ('Disposed', 'Sold', 'Retired')
    running = (a.status == 'Active' and getattr(a, 'activated', False)) and not closed
    idx = 2 if closed else (1 if running else 0)
    labels = ['Draft', 'Running', 'Closed']
    out = []
    for i, lab in enumerate(labels):
        if i == idx:
            extra = 'cur closed' if i == 2 else ('cur run' if i == 1 else 'cur')
            if i == 2:
                lab = a.status  # Disposed / Sold / Retired
            out.append(f"<span class='s {extra}'>{h(lab)}</span>")
        elif i < idx:
            out.append(f"<span class='s done'>{h(lab)}</span>")
        else:
            out.append(f"<span class='s'>{h(lab)}</span>")
    return "<span class='osb'>" + ''.join(out) + "</span>"


def _depreciation_schedule(a):
    """Full straight-line-style board: list of (period, amount, accumulated, book_value, posted)."""
    base = a.depreciable_base
    monthly = base / a.life_months if a.life_months else 0
    acc = 0.0
    bv = (a.cost or 0) + (a.reval_adjust or 0)
    try:
        start = dt.date.fromisoformat((a.in_service_date or a.purchase_date or today())[:10])
    except Exception:
        start = dt.date.today()
    now_period = dt.date.today().strftime('%Y-%m')
    out = []
    for i in range(a.life_months or 0):
        m = start.month - 1 + i
        yr = start.year + m // 12
        mo = m % 12 + 1
        amt = min(monthly, bv - (a.residual_value or 0))
        if amt <= 0.005:
            break
        acc += amt
        bv -= amt
        period = f'{yr}-{mo:02d}'
        posted = AssetDepreciation.query.filter_by(asset_id=a.id, period=period).first()
        out.append((period, round(amt, 2), round(acc, 2), round(bv, 2), bool(posted), period == now_period))
    return out


def _depreciation_board(a):
    sched = _depreciation_schedule(a)
    if not sched:
        return ("<div class='o-sech'>Depreciation Board</div>"
                "<div style='color:var(--muted);font-size:13px;padding:6px 0'>"
                "No schedule — set a purchase cost, useful life and acquisition date, then activate the asset.</div>")
    n_posted = sum(1 for r in sched if r[4])
    CAP = 60
    shown = sched[:CAP]
    rows = ''.join(
        f"<tr class='{'posted ' if r[4] else ''}{'now' if r[5] else ''}'>"
        f"<td>{h(r[0])}</td><td class='num'>{money(r[1])}</td>"
        f"<td class='num'>{money(r[2])}</td><td class='num'>{money(r[3])}</td>"
        f"<td>{'<span class=\"pill green\">Posted</span>' if r[4] else '<span class=\"pill grey\">Draft</span>'}</td></tr>"
        for r in shown)
    more = (f"<tr><td colspan='5' style='text-align:center;color:var(--muted);padding:10px'>"
            f"… {len(sched)-CAP} more periods — <a href='{url_for('fa.fa_schedule', aid=a.id)}' style='color:var(--petrol);font-weight:600'>view full schedule</a></td></tr>"
            if len(sched) > CAP else '')
    return (f"<div class='o-sech'>Depreciation Board <span style='color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0'>· "
            f"{h(a.depreciation_method or 'Straight Line')} · {len(sched)} periods · {n_posted} posted</span></div>"
            f"<table class='o-board'><thead><tr><th>Date</th><th class='num'>Depreciation</th>"
            f"<th class='num'>Cumulative</th><th class='num'>Book Value</th><th>Status</th></tr></thead>"
            f"<tbody>{rows}{more}</tbody></table>")


DEFAULT_CATEGORIES = [
    ('Medical Equipment', 8), ('CT Scanner', 10), ('MRI', 12), ('Ultrasound', 8),
    ('X-Ray', 10), ('Dental Equipment', 8), ('Laboratory Equipment', 7),
    ('Office Equipment', 5), ('Furniture', 8), ('Computers', 4), ('Printers', 4),
    ('Networking Equipment', 5), ('Vehicles', 6), ('Buildings', 25), ('Land', 0),
    ('UPS', 4), ('Generators', 10), ('Air Conditioners', 8), ('Other Assets', 5),
]
METHODS = ['Straight Line', 'Declining Balance', 'Units of Production']
DISPOSAL_METHODS = ['Sale', 'Retirement', 'Donation', 'Write-Off']


# ----------------------------- setup / helpers -----------------------------
def ensure_fa_setup():
    """Idempotently ensure the FA chart-of-accounts nodes and default categories."""
    acc_ensure('1510', 'Equipment', 'Asset', '1500')
    acc_ensure('1520', 'Accumulated Depreciation', 'Asset', '1500')
    acc_ensure('6400', 'Depreciation', 'Expense', '6000')
    acc_ensure('6450', 'Repairs & Maintenance', 'Expense', '6000')
    acc_ensure('4900', 'Gain on Asset Disposal', 'Income', '4000')
    acc_ensure('6600', 'Loss on Asset Disposal', 'Expense', '6000')
    acc_ensure('3300', 'Revaluation Surplus', 'Equity', '3000')
    if not AssetCategory.query.first():
        for name, life in DEFAULT_CATEGORIES:
            db.session.add(AssetCategory(name=name, useful_life=life,
                                         method='Straight Line', residual_pct=0))
        db.session.commit()


def _can_manage():
    u = cur_user()
    return bool(u and u.role in ('super_admin', 'it_admin', 'accountant', 'branch_manager'))


def _can_admin():
    u = cur_user()
    return bool(u and u.role in ('super_admin', 'it_admin'))


def _guard_view():
    u = cur_user()
    if not (u and (can('assets') or u.role == 'reception')):
        abort(403)


def _guard_manage():
    if not _can_manage():
        abort(403)


def _next_code():
    n = (Asset.query.count() or 0) + 1
    while Asset.query.filter_by(code=f'FA-{n:04d}').first():
        n += 1
    return f'FA-{n:04d}'


def _cat_accounts(a):
    """Resolve the asset/accum/expense account codes from the asset's category."""
    c = a.cat
    return (getattr(c, 'asset_account', None) or '1510',
            getattr(c, 'accum_account', None) or '1520',
            getattr(c, 'expense_account', None) or '6400')


# ----------------------------- depreciation engine -----------------------------
def period_depreciation(a):
    """Depreciation for ONE month given the asset's method and current book value."""
    if (a.status in ('Disposed', 'Sold', 'Retired', 'Draft')) or not a.activated:
        return 0.0
    base = a.depreciable_base
    if base <= 0:
        return 0.0
    method = a.depreciation_method or 'Straight Line'
    residual = a.residual_value or 0
    nbv = a.nbv
    if nbv <= residual + 0.005:
        return 0.0
    if method == 'Declining Balance':
        yrs = max((a.life_months / 12.0), 0.5)
        annual_rate = min(2.0 / yrs, 1.0)          # double-declining
        amt = nbv * annual_rate / 12.0
    elif method == 'Units of Production' and (a.units_total or 0) > 0:
        # GENUINE usage-based depreciation:
        #   rate per unit    = depreciable_base / estimated_total_units
        #   accumulated target = units_used_so_far * rate_per_unit  (capped at base)
        #   this period       = accumulated_target - already_accumulated
        # This reflects ACTUAL usage rather than an even monthly spread; if the
        # asset was not used this period, units_used is unchanged and the charge
        # is zero.
        rate = base / a.units_total
        target = min(rate * (a.units_used or 0), base)
        amt = target - (a.accumulated_dep or 0)
        if amt < 0:
            amt = 0.0
    else:  # Straight Line
        amt = base / a.life_months
    # never depreciate below residual value
    amt = min(amt, nbv - residual)
    return round(max(amt, 0), 2)


def run_depreciation(period=None, only_asset=None):
    """Post one month of depreciation for all active assets (or one asset).
    Creates AssetDepreciation rows + Dr Expense / Cr Accum journal entries.
    Idempotent per (asset, period). Returns (count, total)."""
    period = period or dt.date.today().strftime('%Y-%m')
    d = period + '-28'
    q = Asset.query.filter(Asset.status == 'Active', Asset.activated == True)
    if only_asset:
        q = q.filter(Asset.id == only_asset)
    count = 0; total = 0.0
    for a in q.all():
        if AssetDepreciation.query.filter_by(asset_id=a.id, period=period).first():
            continue
        amt = period_depreciation(a)
        if amt <= 0:
            continue
        _asset_acc, accum_acc, exp_acc = _cat_accounts(a)
        a.accumulated_dep = round((a.accumulated_dep or 0) + amt, 2)
        ref = f'DEP-{a.code}-{period.replace("-", "")}'
        post_journal(d, ref, f'Depreciation {a.code} · {a.name} · {period}',
                     [(exp_acc, amt, 0), (accum_acc, 0, amt)])
        rec = AssetDepreciation(asset_id=a.id, period=period, date=d, amount=amt,
                                accumulated=a.accumulated_dep, book_value=a.nbv,
                                journal_ref=ref, posted=True)
        db.session.add(rec)
        count += 1; total += amt
    db.session.commit()
    return count, round(total, 2)


# =============================== DASHBOARD ===============================
@bp.route('/fa')
@bp.route('/fa/dashboard')
@login_required
def fa_dashboard():
    _guard_view()
    ensure_fa_setup()
    q = (request.args.get('q') or '').strip()
    f = (request.args.get('f') or 'all')
    assets = Asset.query.order_by(Asset.code).all()
    if q:
        ql = q.lower()
        assets = [a for a in assets if ql in (a.code or '').lower() or ql in (a.name or '').lower()
                  or ql in ((a.cat.name if a.cat else a.category) or '').lower()
                  or ql in (a.department or '').lower() or ql in (a.location or '').lower()]

    live = [a for a in assets if a.status not in ('Disposed', 'Sold', 'Retired')]
    running = [a for a in assets if a.status == 'Active' and a.activated]
    draft = [a for a in assets if not a.activated and a.status not in ('Disposed', 'Sold', 'Retired')]
    near_eol = [a for a in running if 0 <= a.remaining_months <= 6 and a.nbv > (a.residual_value or 0) + 0.5]
    repair = [a for a in assets if a.status == 'Under Repair']
    disposed = [a for a in assets if a.status in ('Disposed', 'Sold', 'Retired')]

    total_cost = sum((a.cost or 0) + (a.reval_adjust or 0) for a in live)
    accum = sum(a.accumulated_dep or 0 for a in live)
    nbv = sum(a.nbv for a in live)
    month_dep = sum(period_depreciation(a) for a in running)

    view = assets
    if f == 'running': view = running
    elif f == 'draft': view = draft
    elif f == 'eol': view = near_eol
    elif f == 'repair': view = repair
    elif f == 'disposed': view = disposed

    def _fa_state(a):
        if a.status in ('Disposed', 'Sold', 'Retired'):
            return (a.status, 'grey' if a.status == 'Retired' else 'red')
        if a.status == 'Under Repair':
            return ('Under Repair', 'amber')
        if a.status == 'Active' and a.activated:
            return ('Running', 'green')
        return ('Draft', 'grey')

    CSS = """<style>
    .fa-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .fa-stat{flex:1;min-width:148px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
    .fa-stat .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
    .fa-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
    .fa-stat.a{border-left:3px solid var(--petrol)} .fa-stat.b{border-left:3px solid var(--green)}
    .fa-stat.c{border-left:3px solid var(--amber)} .fa-stat.d{border-left:3px solid var(--red)} .fa-stat.e{border-left:3px solid #2b7de9}
    .fa-chip{display:inline-block;padding:5px 12px;border:1px solid var(--line);border-radius:20px;font-size:12.5px;font-weight:600;color:var(--muted);margin-right:6px;margin-bottom:6px;text-decoration:none}
    .fa-chip.on{background:var(--petrol);color:#fff;border-color:var(--petrol)}
    </style>"""

    def card(cls, label, val):
        return f"<div class='fa-stat {cls}'><div class='l'>{label}</div><div class='v'>{val}</div></div>"
    stats = ("<div class='fa-stats'>"
             + card('a', 'Assets', str(len(live)))
             + card('a', 'Asset Value', money(total_cost))
             + card('b', 'Book Value', money(nbv))
             + card('c', 'Accum. Depreciation', money(accum))
             + card('e', 'Monthly Depreciation', money(month_dep))
             + card('d', 'Near End of Life', str(len(near_eol)))
             + "</div>")

    def chip(key, label, n=None):
        on = 'on' if f == key else ''
        cnt = f" ({n})" if n is not None else ''
        url = url_for('fa.fa_dashboard', f=key) + (f'&q={h(q)}' if q else '')
        return f"<a class='fa-chip {on}' href='{url}'>{label}{cnt}</a>"
    chips = ("<div style='margin-bottom:10px'>"
             + chip('all', 'All', len(assets)) + chip('running', 'Running', len(running))
             + chip('draft', 'Draft', len(draft)) + chip('eol', 'Near EOL', len(near_eol))
             + chip('repair', 'Under Repair', len(repair)) + chip('disposed', 'Disposed', len(disposed))
             + "</div>")

    search = (f"<form method='get' style='margin-bottom:10px'><input type='hidden' name='f' value='{h(f)}'>"
              f"<input name='q' value='{h(q)}' placeholder='🔍  Search code, asset, category, department…' "
              f"style='width:min(430px,100%);padding:7px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px'></form>")

    hdr = ("<tr><th>Code</th><th>Asset</th><th>Category</th><th>Acquired</th>"
           "<th class='num'>Cost</th><th class='num'>Accum. Dep</th><th class='num'>Book Value</th>"
           "<th>Life Left</th><th>Dept</th><th>Status</th><th></th></tr>")
    rws = ''
    for a in view:
        st, sc = _fa_state(a)
        dep_btn = (f"<a class='btn gh sm' href='{url_for('fa.fa_depreciation')}'>Depreciate</a>"
                   if (a.status == 'Active' and a.activated and _can_manage()) else '')
        rws += (f"<tr><td><a class='idlink' href='{url_for('fa.fa_asset', aid=a.id)}'>{h(a.code or '')}</a></td>"
                f"<td><b>{h(a.name)}</b></td><td>{h(a.cat.name if a.cat else (a.category or '—'))}</td>"
                f"<td>{h(a.purchase_date or '—')}</td>"
                f"<td class='num'>{money(a.cost)}</td><td class='num'>{money(a.accumulated_dep or 0)}</td>"
                f"<td class='num'><b>{money(a.nbv)}</b></td>"
                f"<td>{(str(a.remaining_months) + ' mo') if a.activated else '—'}</td>"
                f"<td>{h(a.department or '—')}</td>"
                f"<td><span class='pill {sc}'>{h(st)}</span></td>"
                f"<td style='text-align:right;white-space:nowrap'><a class='btn gh sm' href='{url_for('fa.fa_asset', aid=a.id)}'>Open</a> {dep_btn}</td></tr>")
    if not rws:
        rws = "<tr><td colspan='11'><div class='empty' style='padding:26px;text-align:center;color:var(--muted)'><b>No assets</b><br>Purchase an asset to begin.</div></td></tr>"
    table = f"<div class='panel'><div class='tw'><table><thead>{hdr}</thead><tbody>{rws}</tbody></table></div></div>"

    tb = _sb([('+ Purchase Asset', url_for('fa.fa_purchase'), 'primary' if _can_manage() else 'hide'),
              ('\u2b06 Import from Excel', url_for('fa.fa_import'), '' if _can_manage() else 'hide'),
              ('▶ Run Depreciation', url_for('fa.fa_depreciation'), '' if _can_manage() else 'hide'),
              ('⬇ Report (CSV)', url_for('fa.fa_report_csv', kind='register'), ''),
              ('⚙ Settings', url_for('fa.fa_settings'), '')])
    return page('Fixed Assets', CSS + tb + stats + chips + search + table, 'fa_dash',
                crumbs=[('Accounting', url_for('modules.module', mod='acct')), ('Fixed Assets', None)])


# =============================== ASSET REGISTER ===============================
@bp.route('/fa/register')
@login_required
def fa_register():
    _guard_view()
    ensure_fa_setup()
    from ..core.security import branch_scope
    from .modules import search_view, hl
    q = branch_scope(Asset.query, Asset)
    # full Odoo-style search view (search + chips + advanced + favorites + recent)
    q, _sq, _fbar = search_view('fa_register', Asset, q,
                                search_cols=['code', 'name', 'category', 'serial',
                                             'department', 'location', 'status'],
                                date_field='purchase_date')
    assets = q.order_by(Asset.code).all()
    headers = ['Code', 'Asset', 'Category', 'Purchase', 'Cost', 'Accum. Dep', 'Book Value',
               'Residual', 'Life Left', 'Dept', 'Location', 'Status']
    aligns = ['', '', '', '', 'num', 'num', 'num', 'num', '', '', '', '']
    _stcol = {'Active': 'green', 'Draft': 'grey', 'Disposed': 'red', 'Sold': 'red',
              'Retired': 'grey', 'Under Repair': 'amber'}
    rows = []
    for a in assets:
        rows.append([
            f"<a class='idlink' href='{url_for('fa.fa_asset', aid=a.id)}'>{hl(h(a.code or ''), _sq)}</a>",
            hl(h(a.name), _sq), hl(h(a.cat.name if a.cat else (a.category or '—')), _sq), h(a.purchase_date or '—'),
            money(a.cost), money(a.accumulated_dep or 0), money(a.nbv), money(a.residual_value or 0),
            (f'{a.remaining_months} mo' if a.activated else '—'), hl(h(a.department or '—'), _sq), hl(h(a.location or '—'), _sq),
            f"<span class='pill {_stcol.get(a.status,'grey')}'>{h(a.status)}</span>"])
    tb = _sb([('+ Purchase Asset', url_for('fa.fa_purchase'), 'primary' if _can_manage() else 'hide'),
                   ('▶ Run Depreciation', url_for('fa.fa_depreciation'), '' if _can_manage() else 'hide'),
                   ('⬇ Report (CSV)', url_for('fa.fa_report_csv', kind='register'), ''),
                   ('◱ Dashboard', url_for('fa.fa_dashboard'), '')])
    body = render_template('list_page.html', title=f'Asset Register ({len(assets)})',
                           toolbar='', headers=headers, aligns=aligns, rows=rows, filterbar=_fbar,
                           empty="<div class='empty'><b>No assets</b>Purchase an asset to begin.</div>")
    return page('Asset Register', tb + body, 'fa_register',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), ('Asset Register', None)])


# =============================== PURCHASE ASSET ===============================
@bp.route('/fa/purchase', methods=['GET', 'POST'])
@login_required
def fa_purchase():
    _guard_manage()
    ensure_fa_setup()
    cats = AssetCategory.query.filter_by(active=True).order_by(AssetCategory.name).all()
    if request.method == 'POST':
        f = request.form
        cat = AssetCategory.query.get(int(f.get('category_id'))) if f.get('category_id') else None
        life_y = f.get('useful_life') or (cat.useful_life if cat else 5)
        a = Asset(
            code=(f.get('code') or _next_code()).strip(),
            name=(f.get('name') or '').strip(),
            category_id=cat.id if cat else None,
            category=cat.name if cat else (f.get('category') or ''),
            supplier=f.get('supplier'), purchase_invoice=f.get('purchase_invoice'),
            purchase_date=f.get('purchase_date') or today(),
            in_service_date=f.get('in_service_date') or None,
            capitalization_date=f.get('capitalization_date') or None,
            cost=float(f.get('cost') or 0), residual_value=float(f.get('residual_value') or 0),
            useful_life=int(float(life_y or 5)),
            useful_life_months=int(f.get('useful_life_months')) if f.get('useful_life_months') else None,
            depreciation_method=f.get('depreciation_method') or (cat.method if cat else 'Straight Line'),
            department=f.get('department'), custodian=f.get('custodian'),
            location=f.get('location'), serial=f.get('serial'),
            warranty_expiry=f.get('warranty_expiry'),
            units_total=int(f.get('units_total')) if f.get('units_total') else None,
            status='Draft', activated=False)
        # pre-existing asset owned before the system: record depreciation already taken
        _opening = bool(f.get('opening'))
        a.opening = _opening
        _accum = float(f.get('accumulated_dep') or 0)
        if _accum > 0:
            a.accumulated_dep = round(min(_accum, max((a.cost or 0) - (a.residual_value or 0), 0)), 2)
        db.session.add(a); db.session.commit()
        log(f'Fixed asset {"registered (opening)" if _opening else "purchased"}: {a.code} · {a.name} ({money(a.cost)})',
            action_type='Create', entity=f'Asset {a.code}')
        flash(f'Asset {a.code} created as Draft. Approve & activate to '
              + ('bring it onto the books.' if _opening else 'start depreciation.'))
        return redirect(url_for('fa.fa_asset', aid=a.id))

    catopts = ''.join(f"<option value='{c.id}'>{h(c.name)}</option>" for c in cats)
    metopts = ''.join(f"<option value='{h(m)}'>{h(m)}</option>" for m in METHODS)
    body = f"""
    <form method="post" class="panel"><div class="pad" style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <label>Asset Code<input name="code" placeholder="Auto (FA-####)"></label>
      <label>Asset Name *<input name="name" required></label>
      <label>Category<select name="category_id">{catopts}</select></label>
      <label>Supplier<input name="supplier"></label>
      <label>Purchase Invoice<input name="purchase_invoice"></label>
      <label>Purchase Date<input type="date" name="purchase_date" value="{today()}"></label>
      <label>In-Service Date <span style="color:#888;font-weight:400">(depreciation starts here; blank = purchase date)</span><input type="date" name="in_service_date"></label>
      <label>Capitalization Date <span style="color:#888;font-weight:400">(optional)</span><input type="date" name="capitalization_date"></label>
      <label>Purchase Cost *<input type="number" step="0.01" name="cost" required></label>
      <label>Residual Value<input type="number" step="0.01" name="residual_value" value="0"></label>
      <label>Useful Life (Years)<input type="number" name="useful_life" placeholder="from category"></label>
      <label>Useful Life (Months, optional)<input type="number" name="useful_life_months"></label>
      <label>Depreciation Method<select name="depreciation_method">{metopts}</select></label>
      <label>Units Total (for Units of Production)<input type="number" name="units_total"></label>
      <label>Department<input name="department"></label>
      <label>Custodian<input name="custodian"></label>
      <label>Location / Room<input name="location"></label>
      <label>Serial Number<input name="serial"></label>
      <label>Warranty Expiry<input type="date" name="warranty_expiry"></label>
      <div class="fld full" style="border:1px solid var(--line);border-left:3px solid var(--amber);border-radius:8px;padding:10px 12px;background:#fffaf6">
        <label style="display:flex;align-items:center;gap:8px;font-weight:600;margin:0">
          <input type="checkbox" name="opening" value="1" style="width:auto"> This asset was already owned <b>before</b> the system started (opening balance)</label>
        <div style="font-size:12px;color:var(--muted);margin:4px 0 8px">Tick this for equipment you already had. Enter the depreciation already taken so the book value is correct — activating it books the asset against Retained Earnings (not a new supplier bill), and depreciation continues on the remaining value.</div>
        <label style="margin:0">Accumulated Depreciation to date (already taken)
          <input type="number" step="0.01" name="accumulated_dep" value="0" placeholder="e.g. 20000"></label>
      </div>
      <div class="fld full"><button class="btn primary">Create Asset (Draft)</button>
        <a class="btn" href="{url_for('fa.fa_register')}">Cancel</a></div>
    </div></form>"""
    return page('Purchase Asset', body, 'fa_purchase',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), ('Purchase Asset', None)])


# =============================== ASSET DETAIL ===============================
_FA_IMPORT_HEADERS = [
    'Asset Name*', 'Category', 'Serial No', 'Location', 'Department', 'Custodian',
    'Supplier', 'Purchase Invoice', 'Purchase Date (YYYY-MM-DD)', 'Cost*',
    'Residual Value', 'Useful Life (Years)', 'Depreciation Method',
    'Accumulated Depreciation', 'Asset Code (optional)', 'Notes']

_FA_IMPORT_MAP = [
    ('name', ['asset name', 'name']),
    ('category', ['category']),
    ('serial', ['serial']),
    ('location', ['location']),
    ('department', ['department']),
    ('custodian', ['custodian']),
    ('supplier', ['supplier']),
    ('purchase_invoice', ['purchase invoice', 'invoice']),
    ('purchase_date', ['purchase date', 'date']),
    ('cost', ['cost']),
    ('residual_value', ['residual']),
    ('useful_life', ['useful life', 'life']),
    ('depreciation_method', ['depreciation method', 'method']),
    ('accumulated_dep', ['accumulated']),
    ('code', ['asset code', 'code']),
    ('notes', ['notes']),
]


def _fa_num(v):
    try:
        if v is None or v == '':
            return 0.0
        return float(str(v).replace(',', '').replace('$', '').strip())
    except (TypeError, ValueError):
        return None


def _fa_date(v):
    if v is None or v == '':
        return None
    try:
        if hasattr(v, 'strftime'):
            return v.strftime('%Y-%m-%d')
    except Exception:
        pass
    return str(v).strip()[:12]


@bp.route('/fa/import/template')
@login_required
def fa_import_template():
    _guard_manage()
    import io
    from flask import Response
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = Workbook(); ws = wb.active; ws.title = 'Fixed Assets'
    ws.append(_FA_IMPORT_HEADERS)
    hf = Font(bold=True, color='FFFFFF'); fill = PatternFill('solid', fgColor='044C8C')
    for c in ws[1]:
        c.font = hf; c.fill = fill; c.alignment = Alignment(vertical='center')
    ws.append(['CT Scanner GE', 'Medical Equipment', 'SN-12345', 'Radiology Room 1',
               'Radiology', 'Eng. Cabdi', 'GE Healthcare', 'PINV-2023-08', '2023-02-15',
               85000, 5000, 8, 'Straight Line', 20000, '', 'Owned since 2023'])
    widths = [24, 18, 14, 18, 14, 14, 18, 16, 22, 12, 14, 16, 20, 22, 18, 24]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return Response(buf.read(),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment;filename=MDC-FixedAssets-Template.xlsx'})


@bp.route('/fa/import', methods=['GET', 'POST'])
@login_required
def fa_import():
    _guard_manage()
    ensure_fa_setup()
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename:
            flash('Please choose an Excel (.xlsx) file to import.')
            return redirect(url_for('fa.fa_import'))
        if not file.filename.lower().endswith(('.xlsx', '.xlsm')):
            flash('Please upload a .xlsx file (the template download is the easiest way).')
            return redirect(url_for('fa.fa_import'))
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file.stream, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
        except Exception:
            from ..core.helpers import log_error
            log_error('fa_import read')
            flash('Could not read that file - make sure it is a valid .xlsx workbook.')
            return redirect(url_for('fa.fa_import'))
        if not rows or len(rows) < 2:
            flash('The sheet has no data rows below the header.')
            return redirect(url_for('fa.fa_import'))

        headers = [(str(c).strip().lower() if c is not None else '') for c in rows[0]]
        colmap = {}; used = set()
        for field, keys in _FA_IMPORT_MAP:
            for idx, hdr in enumerate(headers):
                if idx in used or not hdr:
                    continue
                if any(k in hdr for k in keys):
                    colmap[field] = idx; used.add(idx); break
        if 'name' not in colmap or 'cost' not in colmap:
            flash('Missing required columns. The sheet must have at least "Asset Name" and "Cost" '
                  '(download the template to get the right headers).')
            return redirect(url_for('fa.fa_import'))

        def cell(row, field):
            i = colmap.get(field)
            return row[i] if (i is not None and i < len(row)) else None

        cats = {c.name.strip().lower(): c for c in AssetCategory.query.all()}
        added = skipped = 0; errors = []
        for rn, row in enumerate(rows[1:], start=2):
            if row is None or all(v is None or str(v).strip() == '' for v in row):
                continue
            name = (str(cell(row, 'name') or '')).strip()
            if not name:
                errors.append(f'Row {rn}: missing Asset Name'); continue
            cost = _fa_num(cell(row, 'cost'))
            if cost is None:
                errors.append(f'Row {rn}: Cost is not a number'); continue
            code_in = (str(cell(row, 'code') or '')).strip()
            serial = (str(cell(row, 'serial') or '')).strip() or None
            if code_in and Asset.query.filter_by(code=code_in).first():
                skipped += 1; continue
            if serial and Asset.query.filter_by(name=name, serial=serial).first():
                skipped += 1; continue
            cat_name = (str(cell(row, 'category') or '')).strip()
            cat = cats.get(cat_name.lower()) if cat_name else None
            method = (str(cell(row, 'depreciation_method') or '')).strip()
            if method not in METHODS:
                method = (cat.method if cat else 'Straight Line')
            life = _fa_num(cell(row, 'useful_life')) or (cat.useful_life if cat else 5)
            residual = _fa_num(cell(row, 'residual_value')) or 0
            accum = _fa_num(cell(row, 'accumulated_dep')) or 0
            code = code_in or _next_code()
            while Asset.query.filter_by(code=code).first():
                code = _next_code()
            a = Asset(
                code=code, name=name,
                category_id=cat.id if cat else None,
                category=cat.name if cat else cat_name,
                serial=serial,
                location=(str(cell(row, 'location') or '')).strip() or None,
                department=(str(cell(row, 'department') or '')).strip() or None,
                custodian=(str(cell(row, 'custodian') or '')).strip() or None,
                supplier=(str(cell(row, 'supplier') or '')).strip() or None,
                purchase_invoice=(str(cell(row, 'purchase_invoice') or '')).strip() or None,
                purchase_date=_fa_date(cell(row, 'purchase_date')) or today(),
                cost=cost, residual_value=residual,
                useful_life=int(float(life or 5)),
                depreciation_method=method,
                notes=(str(cell(row, 'notes') or '')).strip() or None,
                opening=True, status='Draft', activated=False)
            if accum > 0:
                a.accumulated_dep = round(min(accum, max((a.cost or 0) - (a.residual_value or 0), 0)), 2)
            db.session.add(a); db.session.flush()
            added += 1
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            from ..core.helpers import log_error
            log_error('fa_import commit')
            flash('Import failed while saving - please check the file and try again.')
            return redirect(url_for('fa.fa_import'))
        log(f'Fixed-asset Excel import: +{added} assets, {skipped} skipped, {len(errors)} errors')
        msg = (f'Imported {added} asset(s) as Draft (opening). Skipped {skipped} already present.'
               + (f' {len(errors)} row(s) had problems.' if errors else ''))
        flash(msg + ' Review them in the register, then Approve & Activate to bring them onto the books.')
        if errors:
            flash('Issues: ' + ' - '.join(errors[:12]) + (' ...' if len(errors) > 12 else ''))
        return redirect(url_for('fa.fa_register'))

    body = f"""
    <div class="panel"><div class="ph"><h2>Import Fixed Assets from Excel</h2>
      <span class="so">Bring your existing asset register into the system</span></div>
      <div class="pad">
        <ol style="line-height:1.9;margin:0 0 14px 18px;padding:0">
          <li><b>Download</b> the Excel template below (it has the exact columns).</li>
          <li><b>Fill</b> one row per asset. Required: <b>Asset Name</b> and <b>Cost</b>. For equipment you
              already owned, put the <b>Accumulated Depreciation to date</b> so the book value is correct.</li>
          <li><b>Upload</b> the file here. Assets come in as <b>Draft (opening)</b> - review them in the
              register, then Approve &amp; Activate to book them against Retained Earnings.</li>
        </ol>
        <a class="btn" href="{url_for('fa.fa_import_template')}">\u2b07 Download Excel Template</a>
        <form method="post" enctype="multipart/form-data" style="margin-top:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <input type="file" name="file" accept=".xlsx,.xlsm" required
                 style="border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:var(--surface)">
          <button class="btn primary">\u2b06 Import Assets</button>
          <a class="btn" href="{url_for('fa.fa_dashboard')}">Cancel</a>
        </form>
        <div style="color:var(--muted);font-size:12.5px;margin-top:12px">
          Re-importing the same file is safe - assets already present (same Code, or same Name + Serial) are skipped.
        </div>
      </div></div>"""
    return page('Import Fixed Assets', body, 'fa_register',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), ('Import from Excel', None)])


@bp.route('/fa/asset/<int:aid>')
@login_required
def fa_asset(aid):
    _guard_view()
    a = Asset.query.get_or_404(aid)
    deps = AssetDepreciation.query.filter_by(asset_id=aid).order_by(AssetDepreciation.period.desc()).all()
    # ── Odoo asset form ───────────────────────────────────────────────────────
    _closed = a.status in ('Disposed', 'Sold', 'Retired')
    # state-dependent header buttons (Odoo order)
    _hdr = []
    if a.status == 'Draft' and _can_manage():
        _hdr.append(f"<a class='btn primary sm' href='{url_for('fa.fa_activate', aid=a.id)}'>✓ Confirm / Activate</a>")
    if a.status == 'Active' and a.activated and _can_manage():
        _hdr.append(f"<a class='btn primary sm' href='{url_for('fa.fa_depreciation')}'>▶ Run Depreciation</a>")
        if a.depreciation_method == 'Units of Production':
            _hdr.append(f"<a class='btn sm' href='{url_for('fa.fa_log_usage', aid=a.id)}' "
                        f"onclick=\"var u=prompt('Units used this period (added to total used):'); "
                        f"if(!u)return false; this.href=this.href.split('?')[0]+'?units='+encodeURIComponent(u); return true;\">📊 Log Usage</a>")
    if _can_manage() and not _closed:
        _hdr.append(f"<a class='btn sm' href='{url_for('fa.fa_dispose', aid=a.id)}'>⊘ Dispose / Sell</a>")
    if _can_manage():
        _hdr.append(f"<a class='btn sm' href='{url_for('fa.fa_edit', aid=a.id)}'>✎ Edit</a>")
        _hdr.append(f"<a class='btn sm' href='{url_for('fa.fa_transfer', aid=a.id)}'>⇄ Transfer</a>")
        _hdr.append(f"<a class='btn sm' href='{url_for('fa.fa_maintenance', aid=a.id)}'>🔧 Maintenance</a>")
        _hdr.append(f"<a class='btn sm' href='{url_for('fa.fa_revalue', aid=a.id)}'>↑↓ Revalue</a>")
    _hdr.append(f"<a class='btn sm' href='{url_for('fa.fa_print', aid=a.id)}'>🖨 Print</a>")
    _hdr.append(f"<a class='btn sm' href='{url_for('fa.fa_register')}'>← Register</a>")
    actionbar = FA_ODOO_CSS + (
        "<div class='panel' style='position:sticky;top:8px;z-index:40'>"
        "<div class='pad' style='display:flex;align-items:center;gap:9px;flex-wrap:wrap'>"
        f"<b style='font-family:var(--fd);font-size:15px;color:var(--petrol)'>{h(a.code)}</b>"
        f"{_fa_statusbar(a)}<div class='sp' style='flex:1'></div>{''.join(_hdr)}"
        "</div></div>")

    def orow(k, v):
        return f"<div class='o-row'><span class='k'>{k}</span><span class='v'>{v}</span></div>"
    depreciated = round((a.cost or 0) + (a.reval_adjust or 0) - a.nbv, 2)
    head = (
        "<div class='o-head'><div>"
        + orow('Category', h(a.cat.name if a.cat else a.category or '—'))
        + orow('Original Value', money(a.cost))
        + orow('Salvage / Residual', money(a.residual_value or 0))
        + orow('Acquisition Date', h(a.purchase_date or '—'))
        + orow('Supplier', h(a.supplier or '—'))
        + orow('Purchase Invoice', h(a.purchase_invoice or '—'))
        + "</div><div>"
        + orow('Depreciation Method', h(a.depreciation_method or 'Straight Line'))
        + orow('Duration', f'{a.life_months} months ({a.life_months//12}y {a.life_months%12}m)')
        + orow('Depreciated', money(depreciated))
        + orow('Book Value', f"<b style='color:var(--green)'>{money(a.nbv)}</b>")
        + orow('Life Remaining', f'{a.remaining_months} months' if a.activated else '—')
        + orow('Department / Custodian', f"{h(a.department or '—')} · {h(a.custodian or '—')}")
        + "</div></div>")
    other = (
        "<div class='o-head' style='margin-top:2px'><div>"
        + orow('Location', h(a.location or '—')) + orow('Serial No.', h(a.serial or '—'))
        + "</div><div>"
        + orow('Warranty Expiry', h(a.warranty_expiry or '—')) + orow('Calibration Due', h(a.calibration_due or '—'))
        + "</div></div>")

    sheet = (f"<div class='o-sheet'>"
             f"<div class='o-stat'><div class='l'>Book Value</div><div class='v'>{money(a.nbv)}</div></div>"
             f"<div class='o-title'>{h(a.name)}<small>{h(a.code)}</small></div>"
             f"{head}<div class='o-sech'>Details</div>{other}"
             f"{_depreciation_board(a)}</div>")

    # extra histories (transfers / revaluations / disposal) kept below the sheet
    extra = ''
    trs = AssetTransfer.query.filter_by(asset_id=aid).order_by(AssetTransfer.id.desc()).all()
    if trs:
        extra += "<div class='panel'><div class='ph'><h2>Transfer History</h2></div><div class='pad'>" + ''.join(
            f"<div style='padding:4px 0;border-bottom:1px solid var(--line)'>{h(t.date)} — "
            f"{h(t.from_dept or t.from_location or '—')} → <b>{h(t.to_dept or t.to_location or '—')}</b> "
            f"<span style='color:var(--muted)'>by {h(t.by or '')}</span></div>" for t in trs) + "</div></div>"
    revs = AssetRevaluation.query.filter_by(asset_id=aid).order_by(AssetRevaluation.id.desc()).all()
    if revs:
        extra += "<div class='panel'><div class='ph'><h2>Revaluation History</h2></div><div class='pad'>" + ''.join(
            f"<div style='padding:4px 0;border-bottom:1px solid var(--line)'>{h(r.date)} — {money(r.old_value)} → "
            f"<b>{money(r.new_value)}</b> ({'+' if r.delta>=0 else ''}{money(r.delta)}) "
            f"<span style='color:var(--muted)'>{h(r.journal_ref or '')}</span></div>" for r in revs) + "</div></div>"
    disp = AssetDisposal.query.filter_by(asset_id=aid).first()
    if disp:
        gl = 'Gain' if disp.gain_loss >= 0 else 'Loss'
        extra += (f"<div class='panel' style='border-left:3px solid var(--red)'><div class='pad'>"
                  f"<b>Disposed</b> — {h(disp.method)} on {h(disp.date)} · Proceeds {money(disp.proceeds)} · "
                  f"NBV {money(disp.book_value)} · <b>{gl} {money(abs(disp.gain_loss))}</b> · {h(disp.journal_ref or '')}</div></div>")

    return page(f'Asset {a.code}',
                f"<div class='oform'>{actionbar}{sheet}{extra}</div>", 'fa_register',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')),
                        ('Asset Register', url_for('fa.fa_register')), (a.code, None)])


@bp.route('/fa/asset/<int:aid>/activate', methods=['GET', 'POST'])
@login_required
def fa_activate(aid):
    _guard_manage()
    a = Asset.query.get_or_404(aid)
    if a.status == 'Draft':
        a.status = 'Active'; a.activated = True
        asset_acc, accum_acc, _ = _cat_accounts(a)
        if a.opening:
            # already owned before the system → opening balance, NOT a new purchase.
            # Dr Asset (gross cost) / Cr Accum. Depreciation (to date) / Cr Retained Earnings (net book value)
            _accum = a.accumulated_dep or 0
            _net = round((a.cost or 0) - _accum, 2)
            _lines = [(asset_acc, a.cost, 0)]
            if _accum > 0:
                _lines.append((accum_acc, 0, _accum))
            if _net > 0:
                _lines.append(('3200', 0, _net))   # Retained Earnings / opening equity
            if (a.cost or 0) > 0:
                post_journal(a.purchase_date or today(), f'OPEN-{a.code}',
                             f'Opening balance — asset {a.code} · {a.name}', _lines)
        else:
            # capitalize a new purchase: Dr Asset account, Cr Accounts Payable (on account)
            if (a.cost or 0) > 0:
                post_journal(a.purchase_date or today(), f'ASSET-{a.code}',
                             f'Capitalize asset {a.code} · {a.name}',
                             [(asset_acc, a.cost, 0), ('2100', 0, a.cost)])
        db.session.commit()
        log(f'Asset activated: {a.code}', action_type='Edit', entity=f'Asset {a.code}',
            old='Draft', new='Active')
        flash(f'Asset {a.code} activated — depreciation will run monthly.')
    return redirect(url_for('fa.fa_asset', aid=aid))


@bp.route('/fa/asset/<int:aid>/edit', methods=['GET', 'POST'])
@login_required
def fa_edit(aid):
    _guard_manage()
    a = Asset.query.get_or_404(aid)
    cats = AssetCategory.query.order_by(AssetCategory.name).all()
    if request.method == 'POST':
        f = request.form
        before = {k: getattr(a, k) for k in ('name', 'department', 'custodian', 'location', 'serial', 'residual_value')}
        a.name = f.get('name') or a.name
        a.department = f.get('department'); a.custodian = f.get('custodian')
        a.location = f.get('location'); a.serial = f.get('serial')
        a.warranty_expiry = f.get('warranty_expiry')
        if f.get('residual_value'):
            a.residual_value = float(f.get('residual_value'))
        if f.get('accumulated_dep') is not None and f.get('accumulated_dep') != '':
            a.accumulated_dep = round(min(float(f.get('accumulated_dep')), max((a.cost or 0) - (a.residual_value or 0), 0)), 2)
        a.opening = bool(f.get('opening'))
        if f.get('category_id'):
            a.category_id = int(f.get('category_id')); a.category = (a.cat.name if a.cat else a.category)
        db.session.commit()
        chg = [k for k in before if str(before[k]) != str(getattr(a, k))]
        log(f'Asset edited: {a.code}', action_type='Edit', entity=f'Asset {a.code}',
            old='; '.join(f'{k}={before[k]}' for k in chg), new='; '.join(f'{k}={getattr(a,k)}' for k in chg))
        flash('Asset updated'); return redirect(url_for('fa.fa_asset', aid=aid))
    catopts = ''.join(f"<option value='{c.id}' {'selected' if a.category_id==c.id else ''}>{h(c.name)}</option>" for c in cats)
    body = f"""<form method="post" class="panel"><div class="pad" style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <label>Asset Name<input name="name" value="{h(a.name)}"></label>
      <label>Category<select name="category_id">{catopts}</select></label>
      <label>Department<input name="department" value="{h(a.department or '')}"></label>
      <label>Custodian<input name="custodian" value="{h(a.custodian or '')}"></label>
      <label>Location<input name="location" value="{h(a.location or '')}"></label>
      <label>Serial<input name="serial" value="{h(a.serial or '')}"></label>
      <label>Residual Value<input type="number" step="0.01" name="residual_value" value="{a.residual_value or 0}"></label>
      <label>Warranty Expiry<input type="date" name="warranty_expiry" value="{h(a.warranty_expiry or '')}"></label>
      <div class="fld full" style="border:1px solid var(--line);border-left:3px solid var(--amber);border-radius:8px;padding:10px 12px;background:#fffaf6">
        <label style="display:flex;align-items:center;gap:8px;font-weight:600;margin:0">
          <input type="checkbox" name="opening" value="1" {'checked' if a.opening else ''} style="width:auto"> Owned before the system (opening balance)</label>
        <label style="margin:6px 0 0">Accumulated Depreciation to date<input type="number" step="0.01" name="accumulated_dep" value="{a.accumulated_dep or 0}"></label>
        <div style="font-size:12px;color:var(--muted);margin-top:4px">Correct the depreciation already taken. Book value = cost − this. (For an already-activated asset this adjusts the carrying value directly.)</div>
      </div>
      <div class="fld full"><button class="btn primary">Save</button>
        <a class="btn" href="{url_for('fa.fa_asset', aid=aid)}">Cancel</a></div></div></form>"""
    return page(f'Edit {a.code}', body, 'fa_register',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), (a.code, url_for('fa.fa_asset', aid=aid)), ('Edit', None)])


# =============================== DEPRECIATION (run + journal) ===============================
@bp.route('/fa/<int:aid>/log-usage')
@login_required
def fa_log_usage(aid):
    """Record additional units used for a Units-of-Production asset. Next time
    depreciation runs, the charge reflects the actual usage since last time."""
    _guard_manage()
    a = Asset.query.get_or_404(aid)
    if a.depreciation_method != 'Units of Production':
        flash('Usage logging applies only to Units-of-Production assets.')
        return redirect(url_for('fa.fa_asset', aid=aid))
    try:
        add = float(request.args.get('units') or 0)
    except ValueError:
        add = 0
    if add <= 0:
        flash('Enter a positive number of units used.')
        return redirect(url_for('fa.fa_asset', aid=aid))
    new_used = (a.units_used or 0) + add
    if a.units_total:
        new_used = min(new_used, a.units_total)   # cannot exceed the estimated total
    a.units_used = new_used
    db.session.commit()
    log(f'FA {a.code}: logged {add:g} units used (total {a.units_used:g}/{a.units_total or "?"})',
        action_type='Asset Usage', entity=f'ASSET-{a.code}')
    flash(f'Recorded {add:g} units — total used now {a.units_used:g}. Run depreciation to post the usage-based charge.')
    return redirect(url_for('fa.fa_asset', aid=aid))


@bp.route('/fa/depreciation', methods=['GET', 'POST'])
@login_required
def fa_depreciation():
    _guard_manage()
    ensure_fa_setup()
    if request.method == 'POST':
        period = request.form.get('period') or dt.date.today().strftime('%Y-%m')
        n, total = run_depreciation(period=period)
        log(f'Depreciation run for {period}: {n} asset(s), {money(total)}',
            action_type='Payment', entity=f'Depreciation {period}')
        flash(f'Depreciation posted for {period}: {n} asset(s), total {money(total)}.' if n
              else f'No depreciation due for {period} (already posted or nothing to depreciate).')
        return redirect(url_for('fa.fa_depreciation'))
    # preview + recent journals
    active = Asset.query.filter_by(status='Active', activated=True).all()
    period = dt.date.today().strftime('%Y-%m')
    prows = ''
    due = 0
    for a in active:
        if AssetDepreciation.query.filter_by(asset_id=a.id, period=period).first():
            continue
        amt = period_depreciation(a)
        if amt <= 0:
            continue
        due += amt
        prows += (f"<tr><td><a class='idlink' href='{url_for('fa.fa_asset', aid=a.id)}'>{h(a.code)}</a></td>"
                  f"<td>{h(a.name)}</td><td>{h(a.depreciation_method or 'Straight Line')}</td>"
                  f"<td class='num'>{money(a.nbv)}</td><td class='num'>{money(amt)}</td></tr>")
    preview = (f"<div class='panel'><div class='ph'><h2>Depreciation Due — {period}</h2>"
               f"<span class='so'>{money(due)} across {len([1 for a in active if not AssetDepreciation.query.filter_by(asset_id=a.id,period=period).first() and period_depreciation(a)>0])} assets</span></div>"
               f"<div class='tw'><table><thead><tr><th>Code</th><th>Asset</th><th>Method</th>"
               f"<th class='num'>Book Value</th><th class='num'>This Month</th></tr></thead>"
               f"<tbody>{prows or '<tr><td colspan=5 style=color:var(--muted);padding:12px>Nothing due — all posted for this period.</td></tr>'}</tbody></table></div></div>")
    runform = (f"<div class='panel'><div class='pad' style='display:flex;gap:10px;align-items:center;flex-wrap:wrap'>"
               f"<form method='post' style='display:flex;gap:10px;align-items:center'>"
               f"<label style='margin:0'>Period <input type='month' name='period' value='{period}'></label>"
               f"<button class='btn primary'>▶ Run &amp; Post Depreciation</button></form>"
               f"<span style='color:var(--muted);font-size:12.5px'>Dr Depreciation Expense · Cr Accumulated Depreciation</span></div></div>")
    # recent depreciation journal
    recent = AssetDepreciation.query.order_by(AssetDepreciation.id.desc()).limit(30).all()
    jrows = ''.join(f"<tr><td>{h(d.period)}</td><td><a class='idlink' href='{url_for('fa.fa_asset', aid=d.asset_id)}'>{h(d.asset.code if d.asset else d.asset_id)}</a></td>"
                    f"<td class='num'>{money(d.amount)}</td><td>{h(d.journal_ref or '')}</td></tr>" for d in recent)
    journal = (f"<div class='panel'><div class='ph'><h2>Depreciation Journal</h2></div>"
               f"<div class='tw'><table><thead><tr><th>Period</th><th>Asset</th><th class='num'>Amount</th><th>Journal Ref</th></tr></thead>"
               f"<tbody>{jrows or '<tr><td colspan=4 style=color:var(--muted);padding:12px>No depreciation posted yet.</td></tr>'}</tbody></table></div></div>")
    return page('Depreciation', runform + preview + journal, 'fa_depreciation',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), ('Depreciation', None)])


@bp.route('/fa/asset/<int:aid>/schedule')
@login_required
def fa_schedule(aid):
    _guard_view()
    a = Asset.query.get_or_404(aid)
    # projected straight-line-style schedule from purchase over the life
    rows = ''
    base = a.depreciable_base
    monthly = base / a.life_months if a.life_months else 0
    acc = 0; bv = (a.cost or 0) + (a.reval_adjust or 0)
    try:
        start = dt.date.fromisoformat((a.in_service_date or a.purchase_date or today())[:10])
    except Exception:
        start = dt.date.today()
    for i in range(a.life_months):
        m = start.month - 1 + i
        yr = start.year + m // 12
        mo = m % 12 + 1
        amt = min(monthly, bv - (a.residual_value or 0))
        if amt <= 0:
            break
        acc += amt; bv -= amt
        posted = AssetDepreciation.query.filter_by(asset_id=aid, period=f'{yr}-{mo:02d}').first()
        rows += (f"<tr style='{'background:rgba(31,166,109,.06)' if posted else ''}'><td>{yr}-{mo:02d}</td>"
                 f"<td class='num'>{money(amt)}</td><td class='num'>{money(acc)}</td><td class='num'>{money(bv)}</td>"
                 f"<td>{'✓ posted' if posted else ''}</td></tr>")
    body = (f"<div class='panel'><div class='ph'><h2>Depreciation Schedule — {h(a.code)} · {h(a.name)}</h2>"
            f"<span class='so'>{h(a.depreciation_method or 'Straight Line')}</span></div>"
            f"<div class='tw'><table><thead><tr><th>Period</th><th class='num'>Depreciation</th>"
            f"<th class='num'>Accumulated</th><th class='num'>Book Value</th><th>Status</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></div>")
    return page(f'Schedule · {a.code}', body, 'fa_register',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), (a.code, url_for('fa.fa_asset', aid=aid)), ('Schedule', None)])


# =============================== TRANSFER ===============================
@bp.route('/fa/asset/<int:aid>/transfer', methods=['GET', 'POST'])
@login_required
def fa_transfer(aid):
    _guard_manage()
    a = Asset.query.get_or_404(aid)
    if request.method == 'POST':
        f = request.form
        t = AssetTransfer(asset_id=aid, date=f.get('date') or today(),
                          from_dept=a.department, to_dept=f.get('to_dept'),
                          from_location=a.location, to_location=f.get('to_location'),
                          reason=f.get('reason'), by=cur_user().username)
        a.department = f.get('to_dept') or a.department
        a.location = f.get('to_location') or a.location
        db.session.add(t); db.session.commit()
        log(f'Asset transferred: {a.code}', action_type='Edit', entity=f'Asset {a.code}',
            old=f'{t.from_dept or "—"} / {t.from_location or "—"}',
            new=f'{t.to_dept or "—"} / {t.to_location or "—"}', reason=t.reason)
        flash('Asset transferred and audit history updated.')
        return redirect(url_for('fa.fa_asset', aid=aid))
    body = f"""<form method="post" class="panel"><div class="pad" style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="fld full" style="color:var(--muted)">Currently: <b>{h(a.department or '—')}</b> · {h(a.location or '—')}</div>
      <label>To Department<input name="to_dept" value="{h(a.department or '')}"></label>
      <label>To Location / Room<input name="to_location" value="{h(a.location or '')}"></label>
      <label>Date<input type="date" name="date" value="{today()}"></label>
      <label>Reason<input name="reason"></label>
      <div class="fld full"><button class="btn primary">Transfer Asset</button>
        <a class="btn" href="{url_for('fa.fa_asset', aid=aid)}">Cancel</a></div></div></form>"""
    return page(f'Transfer {a.code}', body, 'fa_register',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), (a.code, url_for('fa.fa_asset', aid=aid)), ('Transfer', None)])


# =============================== MAINTENANCE ===============================
@bp.route('/fa/asset/<int:aid>/maintenance', methods=['GET', 'POST'])
@login_required
def fa_maintenance(aid):
    _guard_manage()
    a = Asset.query.get_or_404(aid)
    if request.method == 'POST':
        f = request.form
        cost = float(f.get('cost') or 0)
        m = MaintenanceJob(asset_id=aid, type=f.get('type') or 'Corrective',
                           date=f.get('date') or today(), engineer=f.get('vendor'),
                           description=f.get('description'), labor_cost=cost,
                           status='Done', completed=f.get('date') or today())
        db.session.add(m); db.session.commit()
        # accounting: Dr Repairs & Maintenance, Cr Accounts Payable
        if cost > 0:
            post_journal(m.date, f'MNT-{a.code}-{m.id}', f'Maintenance {a.code} · {a.name}',
                         [('6450', cost, 0), ('2100', 0, cost)])
        log(f'Asset maintenance logged: {a.code} ({money(cost)})', action_type='Create',
            entity=f'Asset {a.code}', reason=f.get('description'))
        flash('Maintenance recorded' + (' and posted to accounting.' if cost > 0 else '.'))
        return redirect(url_for('fa.fa_asset', aid=aid))
    hist = MaintenanceJob.query.filter_by(asset_id=aid).order_by(MaintenanceJob.id.desc()).all()
    hrows = ''.join(f"<tr><td>{h(m.date)}</td><td>{h(m.type or '')}</td><td>{h(m.engineer or '—')}</td>"
                    f"<td>{h(m.description or '')}</td><td class='num'>{money((m.parts_cost or 0)+(m.labor_cost or 0))}</td></tr>" for m in hist)
    hist_panel = (f"<div class='panel'><div class='ph'><h2>Maintenance History</h2></div>"
                  f"<div class='tw'><table><thead><tr><th>Date</th><th>Type</th><th>Vendor</th><th>Description</th><th class='num'>Cost</th></tr></thead>"
                  f"<tbody>{hrows or '<tr><td colspan=5 style=color:var(--muted);padding:12px>No maintenance yet.</td></tr>'}</tbody></table></div></div>") if hist or True else ''
    form = f"""<form method="post" class="panel"><div class="pad" style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <label>Date<input type="date" name="date" value="{today()}"></label>
      <label>Type<select name="type"><option>Corrective</option><option>Preventive</option><option>Calibration</option></select></label>
      <label>Vendor<input name="vendor"></label>
      <label>Cost<input type="number" step="0.01" name="cost" value="0"></label>
      <label class="fld full">Description<textarea name="description"></textarea></label>
      <div class="fld full"><button class="btn primary">Record Maintenance</button>
        <a class="btn" href="{url_for('fa.fa_asset', aid=aid)}">Cancel</a></div></div></form>"""
    return page(f'Maintenance {a.code}', form + hist_panel, 'fa_register',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), (a.code, url_for('fa.fa_asset', aid=aid)), ('Maintenance', None)])


# =============================== REVALUATION ===============================
@bp.route('/fa/asset/<int:aid>/revalue', methods=['GET', 'POST'])
@login_required
def fa_revalue(aid):
    _guard_manage()
    a = Asset.query.get_or_404(aid)
    if request.method == 'POST':
        new_val = float(request.form.get('new_value') or 0)
        old_val = a.nbv
        delta = round(new_val - old_val, 2)
        if abs(delta) >= 0.005:
            a.reval_adjust = round((a.reval_adjust or 0) + delta, 2)
            asset_acc, _, _ = _cat_accounts(a)
            ref = f'REVAL-{a.code}-{AssetRevaluation.query.count()+1}'
            if delta > 0:   # increase: Dr Asset, Cr Revaluation Surplus (equity)
                post_journal(today(), ref, f'Revaluation increase {a.code}',
                             [(asset_acc, delta, 0), ('3300', 0, delta)])
            else:           # decrease: Dr Loss (expense), Cr Asset
                post_journal(today(), ref, f'Revaluation decrease {a.code}',
                             [('6600', -delta, 0), (asset_acc, 0, -delta)])
            rv = AssetRevaluation(asset_id=aid, date=today(), old_value=old_val, new_value=new_val,
                                  delta=delta, reason=request.form.get('reason'), journal_ref=ref,
                                  by=cur_user().username)
            db.session.add(rv); db.session.commit()
            log(f'Asset revalued: {a.code} {money(old_val)}→{money(new_val)}', action_type='Edit',
                entity=f'Asset {a.code}', old=money(old_val), new=money(new_val), reason=request.form.get('reason'))
            flash(f'Asset revalued ({"+" if delta>=0 else ""}{money(delta)}) and posted to accounting.')
        return redirect(url_for('fa.fa_asset', aid=aid))
    body = f"""<form method="post" class="panel"><div class="pad" style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="fld full" style="color:var(--muted)">Current book value: <b>{money(a.nbv)}</b></div>
      <label>New Value *<input type="number" step="0.01" name="new_value" required></label>
      <label>Reason<input name="reason"></label>
      <div class="fld full"><button class="btn primary">Revalue &amp; Post</button>
        <a class="btn" href="{url_for('fa.fa_asset', aid=aid)}">Cancel</a></div>
      <div class="fld full" style="color:var(--muted);font-size:12px">Increase → Dr Asset / Cr Revaluation Surplus · Decrease → Dr Loss / Cr Asset</div>
    </div></form>"""
    return page(f'Revalue {a.code}', body, 'fa_register',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), (a.code, url_for('fa.fa_asset', aid=aid)), ('Revalue', None)])


# =============================== DISPOSAL ===============================
@bp.route('/fa/asset/<int:aid>/dispose', methods=['GET', 'POST'])
@login_required
def fa_dispose(aid):
    _guard_manage()
    a = Asset.query.get_or_404(aid)
    if a.status in ('Disposed', 'Sold', 'Retired'):
        flash('Asset already disposed.'); return redirect(url_for('fa.fa_asset', aid=aid))
    if request.method == 'POST':
        method = request.form.get('method') or 'Retirement'
        proceeds = float(request.form.get('proceeds') or 0)
        nbv = a.nbv
        gain_loss = round(proceeds - nbv, 2)
        asset_acc, accum_acc, _ = _cat_accounts(a)
        ref = f'DISP-{a.code}'
        # Dr Accumulated Depreciation (remove), Dr Cash (proceeds), Dr Loss / Cr Gain, Cr Asset (at cost)
        cost_gross = (a.cost or 0) + (a.reval_adjust or 0)
        lines = [(accum_acc, a.accumulated_dep or 0, 0)]
        if proceeds > 0:
            lines.append(('1102', proceeds, 0))       # cash in hand
        if gain_loss > 0:
            lines.append(('4900', 0, gain_loss))        # gain (income)
        elif gain_loss < 0:
            lines.append(('6600', -gain_loss, 0))       # loss (expense)
        lines.append((asset_acc, 0, cost_gross))        # remove asset at gross
        post_journal(today(), ref, f'Disposal {a.code} · {method}', lines)
        a.status = 'Sold' if method == 'Sale' else ('Retired' if method == 'Retirement' else 'Disposed')
        a.activated = False
        d = AssetDisposal(asset_id=aid, date=today(), method=method, proceeds=proceeds,
                          book_value=nbv, gain_loss=gain_loss, reason=request.form.get('reason'),
                          journal_ref=ref, by=cur_user().username)
        db.session.add(d); db.session.commit()
        log(f'Asset disposed: {a.code} · {method} · {"gain" if gain_loss>=0 else "loss"} {money(abs(gain_loss))}',
            action_type='Cancel', entity=f'Asset {a.code}', old=f'NBV {money(nbv)}',
            new=f'{method}, proceeds {money(proceeds)}', reason=request.form.get('reason'))
        flash(f'Asset disposed ({method}). {"Gain" if gain_loss>=0 else "Loss"} on disposal: {money(abs(gain_loss))}.')
        return redirect(url_for('fa.fa_asset', aid=aid))
    metopts = ''.join(f"<option>{m}</option>" for m in DISPOSAL_METHODS)
    body = f"""<form method="post" class="panel"><div class="pad" style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="fld full" style="color:var(--muted)">Net book value: <b>{money(a.nbv)}</b> · Accumulated dep: {money(a.accumulated_dep or 0)}</div>
      <label>Disposal Method<select name="method">{metopts}</select></label>
      <label>Proceeds / Sale Amount<input type="number" step="0.01" name="proceeds" value="0"></label>
      <label class="fld full">Reason / Notes<input name="reason"></label>
      <div class="fld full"><button class="btn primary" style="color:var(--red)">Dispose Asset</button>
        <a class="btn" href="{url_for('fa.fa_asset', aid=aid)}">Cancel</a></div>
      <div class="fld full" style="color:var(--muted);font-size:12px">Gain/Loss = Proceeds − Net Book Value, posted automatically.</div>
    </div></form>"""
    return page(f'Dispose {a.code}', body, 'fa_register',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), (a.code, url_for('fa.fa_asset', aid=aid)), ('Dispose', None)])


# =============================== CATEGORIES ===============================
@bp.route('/fa/categories', methods=['GET', 'POST'])
@login_required
def fa_categories():
    _guard_view()
    ensure_fa_setup()
    if request.method == 'POST':
        _guard_manage()
        f = request.form
        cid = f.get('id')
        c = AssetCategory.query.get(int(cid)) if cid else AssetCategory()
        c.name = f.get('name'); c.useful_life = int(float(f.get('useful_life') or 5))
        c.method = f.get('method') or 'Straight Line'
        c.residual_pct = float(f.get('residual_pct') or 0)
        c.asset_account = f.get('asset_account') or '1510'
        c.accum_account = f.get('accum_account') or '1520'
        c.expense_account = f.get('expense_account') or '6400'
        if not cid:
            db.session.add(c)
        db.session.commit()
        log(f'Asset category saved: {c.name}', action_type='Edit', entity=f'AssetCategory {c.name}')
        flash('Category saved'); return redirect(url_for('fa.fa_categories'))
    cats = AssetCategory.query.order_by(AssetCategory.name).all()
    rows = ''.join(f"<tr><td><b>{h(c.name)}</b></td><td>{c.useful_life} yr</td><td>{h(c.method)}</td>"
                   f"<td>{c.residual_pct:g}%</td><td>{h(c.asset_account)}</td><td>{h(c.accum_account)}</td>"
                   f"<td>{h(c.expense_account)}</td></tr>" for c in cats)
    table = (f"<div class='panel'><div class='ph'><h2>Asset Categories</h2><span class='so'>{len(cats)}</span></div>"
             f"<div class='tw'><table><thead><tr><th>Category</th><th>Life</th><th>Method</th><th>Residual</th>"
             f"<th>Asset Acct</th><th>Accum Acct</th><th>Expense Acct</th></tr></thead><tbody>{rows}</tbody></table></div></div>")
    metopts = ''.join(f"<option>{m}</option>" for m in METHODS)
    form = (f"<form method='post' class='panel'><div class='ph'><h2>Add / Update Category</h2></div>"
            f"<div class='pad' style='display:grid;grid-template-columns:repeat(3,1fr);gap:10px'>"
            f"<label>Name<input name='name' required></label>"
            f"<label>Useful Life (yrs)<input type='number' name='useful_life' value='5'></label>"
            f"<label>Method<select name='method'>{metopts}</select></label>"
            f"<label>Residual %<input type='number' step='0.1' name='residual_pct' value='0'></label>"
            f"<label>Asset Account<input name='asset_account' value='1510'></label>"
            f"<label>Accum. Dep Account<input name='accum_account' value='1520'></label>"
            f"<label>Expense Account<input name='expense_account' value='6400'></label>"
            f"<div class='fld full'><button class='btn primary'>Save Category</button></div></div></form>") if _can_manage() else ''
    return page('Asset Categories', table + form, 'fa_categories',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), ('Categories', None)])


# =============================== REPORTS ===============================
@bp.route('/fa/reports')
@login_required
def fa_reports():
    _guard_view()
    kinds = [('register', 'Fixed Asset Register'), ('depreciation', 'Depreciation Schedule'),
             ('accumulated', 'Accumulated Depreciation Report'), ('nbv', 'Net Book Value Report'),
             ('purchase', 'Asset Purchase Report'), ('disposal', 'Asset Disposal Report'),
             ('maintenance', 'Maintenance Report'), ('revaluation', 'Revaluation Report'),
             ('department', 'Department Asset Report'), ('branch', 'Branch Asset Report')]
    tiles = ''.join(
        f"<div class='panel' style='padding:0'><div class='pad' style='display:flex;justify-content:space-between;align-items:center'>"
        f"<div><b>{h(lbl)}</b></div><div style='display:flex;gap:6px'>"
        f"<a class='btn sm' href='{url_for('fa.fa_report', kind=k)}'>View</a>"
        f"<a class='btn sm' href='{url_for('fa.fa_report_csv', kind=k)}'>CSV</a></div></div></div>"
        for k, lbl in kinds)
    grid = f"<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px'>{tiles}</div>"
    return page('Fixed Asset Reports', grid, 'fa_reports',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), ('Reports', None)])


def _report_data(kind):
    """Return (title, headers, rows) for a report kind."""
    if kind == 'disposal':
        ds = AssetDisposal.query.order_by(AssetDisposal.id.desc()).all()
        return ('Asset Disposal Report', ['Date', 'Asset', 'Method', 'Proceeds', 'NBV', 'Gain/Loss'],
                [[d.date, (d.asset.code if d.asset else d.asset_id), d.method, money(d.proceeds),
                  money(d.book_value), ('+' if d.gain_loss >= 0 else '') + money(d.gain_loss)] for d in ds])
    if kind == 'maintenance':
        ms = MaintenanceJob.query.order_by(MaintenanceJob.id.desc()).all()
        return ('Maintenance Report', ['Date', 'Asset', 'Type', 'Vendor', 'Cost'],
                [[m.date, (m.asset.code if m.asset else '—'), m.type, m.engineer or '—',
                  money((m.parts_cost or 0) + (m.labor_cost or 0))] for m in ms])
    if kind == 'revaluation':
        rs = AssetRevaluation.query.order_by(AssetRevaluation.id.desc()).all()
        return ('Revaluation Report', ['Date', 'Asset', 'Old', 'New', 'Delta'],
                [[r.date, (r.asset.code if r.asset else '—'), money(r.old_value), money(r.new_value),
                  ('+' if r.delta >= 0 else '') + money(r.delta)] for r in rs])
    if kind == 'purchase':
        aa = Asset.query.order_by(Asset.purchase_date.desc()).all()
        return ('Asset Purchase Report', ['Code', 'Asset', 'Supplier', 'Invoice', 'Date', 'Cost'],
                [[a.code, a.name, a.supplier or '—', a.purchase_invoice or '—', a.purchase_date or '—', money(a.cost)] for a in aa])
    # register / accumulated / nbv / department / branch all derive from assets
    aa = Asset.query.order_by(Asset.code).all()
    if kind == 'department':
        agg = {}
        for a in aa:
            if a.status in ('Disposed', 'Sold'):
                continue
            agg.setdefault(a.department or '—', [0, 0])
            agg[a.department or '—'][0] += (a.cost or 0); agg[a.department or '—'][1] += a.nbv
        return ('Department Asset Report', ['Department', 'Cost', 'Book Value'],
                [[k, money(v[0]), money(v[1])] for k, v in sorted(agg.items())])
    if kind == 'branch':
        agg = {}
        for a in aa:
            if a.status in ('Disposed', 'Sold'):
                continue
            bn = a.branch.name if a.branch else '—'
            agg.setdefault(bn, [0, 0]); agg[bn][0] += (a.cost or 0); agg[bn][1] += a.nbv
        return ('Branch Asset Report', ['Branch', 'Cost', 'Book Value'],
                [[k, money(v[0]), money(v[1])] for k, v in sorted(agg.items())])
    # register / accumulated / nbv
    title = {'register': 'Fixed Asset Register', 'accumulated': 'Accumulated Depreciation Report',
             'nbv': 'Net Book Value Report', 'depreciation': 'Depreciation Schedule'}.get(kind, 'Fixed Asset Register')
    return (title, ['Code', 'Asset', 'Category', 'Cost', 'Accum. Dep', 'Book Value', 'Status'],
            [[a.code, a.name, (a.cat.name if a.cat else a.category or '—'), money(a.cost),
              money(a.accumulated_dep or 0), money(a.nbv), a.status] for a in aa])


@bp.route('/fa/report/<kind>')
@login_required
def fa_report(kind):
    _guard_view()
    title, headers, rows = _report_data(kind)
    hd = ''.join(f'<th>{h(c)}</th>' for c in headers)
    tr = ''.join('<tr>' + ''.join(f'<td>{h(str(c))}</td>' for c in row) + '</tr>' for row in rows)
    body = (f"<div class='panel'><div class='ph'><h2>{h(title)}</h2><span class='so'>{len(rows)} rows · "
            f"<a href='{url_for('fa.fa_report_csv', kind=kind)}'>CSV</a></span></div>"
            f"<div class='tw'><table><thead><tr>{hd}</tr></thead><tbody>{tr or f'<tr><td colspan={len(headers)} style=color:var(--muted);padding:12px>No data.</td></tr>'}</tbody></table></div></div>")
    return page(title, body, 'fa_reports',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')),
                        ('Reports', url_for('fa.fa_reports')), (title, None)])


@bp.route('/fa/report/<kind>.csv')
@login_required
def fa_report_csv(kind):
    _guard_view()
    import io, csv
    from flask import Response
    title, headers, rows = _report_data(kind)
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(headers)
    for row in rows:
        w.writerow([str(c).replace(',', ' ') for c in row])
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=fa_{kind}.csv'})


@bp.route('/fa/asset/<int:aid>/print')
@login_required
def fa_print(aid):
    _guard_view()
    from ..core.printing import printable
    a = Asset.query.get_or_404(aid)
    body = f"""
      <table style="width:100%;border-collapse:collapse;font-size:13.5px">
        <tr><td style="border:1px solid #ccc;padding:6px 9px"><b>Asset Code:</b> {h(a.code)}</td>
            <td style="border:1px solid #ccc;padding:6px 9px"><b>Category:</b> {h(a.cat.name if a.cat else a.category or '—')}</td></tr>
        <tr><td style="border:1px solid #ccc;padding:6px 9px"><b>Name:</b> {h(a.name)}</td>
            <td style="border:1px solid #ccc;padding:6px 9px"><b>Status:</b> {h(a.status)}</td></tr>
        <tr><td style="border:1px solid #ccc;padding:6px 9px"><b>Purchase Date:</b> {h(a.purchase_date or '—')}</td>
            <td style="border:1px solid #ccc;padding:6px 9px"><b>In-Service Date:</b> {h(a.in_service_date or a.purchase_date or '—')}</td></tr>
        <tr><td style="border:1px solid #ccc;padding:6px 9px"><b>Cost:</b> {money(a.cost)}</td>
            <td style="border:1px solid #ccc;padding:6px 9px"><b>Residual:</b> {money(a.residual_value or 0)}</td></tr>
        <tr><td style="border:1px solid #ccc;padding:6px 9px"><b>Accumulated Dep.:</b> {money(a.accumulated_dep or 0)}</td>
            <td style="border:1px solid #ccc;padding:6px 9px"><b>Book Value:</b> {money(a.nbv)}</td></tr>
        <tr><td style="border:1px solid #ccc;padding:6px 9px"><b>Department:</b> {h(a.department or '—')}</td>
            <td style="border:1px solid #ccc;padding:6px 9px"><b>Location:</b> {h(a.location or '—')}</td></tr>
        <tr><td style="border:1px solid #ccc;padding:6px 9px"><b>Custodian:</b> {h(a.custodian or '—')}</td>
            <td style="border:1px solid #ccc;padding:6px 9px"><b>Serial:</b> {h(a.serial or '—')}</td></tr>
      </table>"""
    return printable(f'Asset {a.code}', body, doc_ref=a.code, barcode_text=a.code)


# =============================== SETTINGS ===============================
@bp.route('/fa/settings')
@login_required
def fa_settings():
    _guard_view()
    ensure_fa_setup()
    body = f"""
    <div class="panel"><div class="ph"><h2>Fixed Assets — Settings</h2></div><div class="pad">
      <p><b>Chart of Accounts mapping</b> (defaults; override per category):</p>
      <ul style="line-height:1.9">
        <li>Asset Account — <b>1510 Equipment</b></li>
        <li>Accumulated Depreciation — <b>1520</b></li>
        <li>Depreciation Expense — <b>6400</b></li>
        <li>Repairs &amp; Maintenance — <b>6450</b></li>
        <li>Gain on Disposal — <b>4900</b> · Loss on Disposal — <b>6600</b></li>
        <li>Revaluation Surplus — <b>3300</b></li>
      </ul>
      <p style="color:var(--muted)">Depreciation posts monthly: <b>Dr Depreciation Expense · Cr Accumulated Depreciation</b>.
      Configure useful life, method and per-category accounts under <a href="{url_for('fa.fa_categories')}">Asset Categories</a>.</p>
      <div style="display:flex;gap:8px;margin-top:10px">
        <a class="btn primary" href="{url_for('fa.fa_categories')}">Manage Categories</a>
        <a class="btn" href="{url_for('fa.fa_depreciation')}">Run Depreciation</a>
      </div>
    </div></div>"""
    return page('Fixed Assets Settings', body, 'fa_settings',
                crumbs=[('Fixed Assets', url_for('fa.fa_dashboard')), ('Settings', None)])
