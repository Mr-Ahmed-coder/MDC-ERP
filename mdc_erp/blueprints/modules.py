"""Generic list / create / edit / delete routes for all registered modules."""
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.security import (cur_user, can, login_required, log,
                             setting, branch_scope, can_see)
from ..core.helpers import money, today
from ..core.ui import page
from ..core.crud import (REG, render_form, resolve_options)
from ..core.posting import (POST_HOOKS,
                            _period_open)

bp = Blueprint('modules', __name__)

@bp.route('/m/<mod>')
@login_required
def module(mod):
    if mod == 'inventory':
        # Odoo-style stock overview replaces the generic list; new/edit still use CRUD.
        from .inventory import inventory_overview
        return inventory_overview()
    if mod == 'purchases':
        # Odoo-style procurement overview replaces the generic list; new/edit still use CRUD.
        from .inventory import purchases_overview
        return purchases_overview()
    if mod == 'costcenters':
        # Odoo-style cost-centers (departments) overview; new/edit still use CRUD.
        from .accounting import costcenters_overview
        return costcenters_overview()
    if mod not in REG:
        # custom modules — imported lazily to avoid circular imports
        from .lab import lab_list, lab_tests_catalog
        from .radiology import rad_list
        from .billing import commission_view, invoice_list, dailytx_view, payables_view, paycenter_view
        from .referrals import referrals_list_view, reqboard_view
        from .accounting import integrity_view, revreport_view, findash_view, journal_list, ledger_view, finance_view, acc_dashboard, coa_view, partnerledger_view, acct_guide
        from .reports import radfees_view, summary_view, revenue_view, reports_view
        from .pharmacy import pharmacy_view
        from .hr import attendance_view, leave_view, payroll_view, hr_dashboard
        from .admin import svcmgmt_view, users_view, audit_view, settings_view, loginhist_view, backup_view, messages_view, errorlog_view, svcconfig_view, system_health
        from .reception import queue_view
        from .pacs import pacs_list
        from .ris import ris_worklist
        from .insurance import ins_dashboard
        from .lis import lis_dashboard
        from .queueman import queue_console
        from .ed import ed_board
        from .ipd import ipd_board
        from .ot import ot_board
        from .dialysis import dia_board
        from .ambulance import amb_board
        from .bloodbank import bb_dashboard
        from .analytics import analytics_board
        from .security_center import sec_board
        from .branchhub import branch_hub
        from .genledger import (gl_dashboard, general_ledger, journal_items,
                                journal_entries, trial_balance, account_balances)
        from .acctdash import acct_dashboard
        from .bankrec import bankrec_list
        from .record_options import index as record_options_view
        from .dash import apps as apps_view
        from .assets import maintdash_view
        from .inventory import stockadj_view, consumption_view, transfers_view, consume_view
        from .lab import critical_alerts_view
        from .chat import chat_view
        from .billing import cashclose_view
        from .accounting import (cashflow_view, araging_view, apaging_view, bankrecon_view,
                                 budgetreport_view, ccreport_view, ratios_view, fiscal_view, taxreport_view)
        from .billing import payalloc_view
        from .reports import branchcmp_view, productivity_view, stockvalue_view
        from .fixedassets import (fa_dashboard, fa_register, fa_purchase, fa_categories,
                                  fa_depreciation, fa_reports, fa_settings)
        custom = {'svcmgmt':svcmgmt_view,'lab':lab_list,'labtests':lab_tests_catalog,'radiology':rad_list,'commission':commission_view,'payables':payables_view,'paycenter':paycenter_view,'referrals':referrals_list_view,'reqboard':reqboard_view,'invoices':invoice_list,'dailytx':dailytx_view,'journal':journal_list,'ledger':ledger_view,'partnerledger':partnerledger_view,'revreport':revreport_view,'findash':findash_view,
                  'fa_dash':fa_dashboard,'fa_register':fa_register,'fa_purchase':fa_purchase,'fa_categories':fa_categories,'fa_depreciation':fa_depreciation,'fa_transfer':fa_register,'fa_maintenance':fa_register,'fa_disposal':fa_register,'fa_revaluation':fa_register,'fa_depjournal':fa_depreciation,'fa_reports':fa_reports,'fa_settings':fa_settings,
                  'finance':finance_view,'acct':acc_dashboard,'accounts':coa_view,'acctguide':acct_guide,'radfees':radfees_view,'summary':summary_view,'revenue':revenue_view,'pharmacy':pharmacy_view,'attendance':attendance_view,'leave':leave_view,'payroll':payroll_view,'hr':hr_dashboard,
                  'reports':reports_view,'users':users_view,'audit':audit_view,'record_options':record_options_view,'errorlog':errorlog_view,'syshealth':system_health,'svcconfig':svcconfig_view,'loginhistory':loginhist_view,'backup':backup_view,'messages':messages_view,'settings':settings_view,'queue':queue_view,'pacs':pacs_list,'ris':ris_worklist,'insurance':ins_dashboard,'lis':lis_dashboard,'tokenq':queue_console,'ed':ed_board,'ipd':ipd_board,'ot':ot_board,'dialysis':dia_board,'ambulance':amb_board,'bloodbank':bb_dashboard,'analytics':analytics_board,'security':sec_board,'branchhub':branch_hub,'gldash':gl_dashboard,'genledger':general_ledger,'jitems':journal_items,'jentries':journal_entries,'trialbal':trial_balance,'acctbal':account_balances,'acctdash':acct_dashboard,'bankrec':bankrec_list,'apps':apps_view,'maintdash':maintdash_view,'branchcmp':branchcmp_view,'productivity':productivity_view,'stockvalue':stockvalue_view,
                  'cashclose':cashclose_view,'cashflow':cashflow_view,'araging':araging_view,'apaging':apaging_view,
                  'stockadj':stockadj_view,'consumption':consumption_view,'transfers':transfers_view,'consume':consume_view,'critical':critical_alerts_view,'chat':chat_view,
                  'bankrecon':bankrecon_view,'budgetreport':budgetreport_view,'ccreport':ccreport_view,
                  'ratios':ratios_view,'integrity':integrity_view,'fiscal':fiscal_view,'taxreport':taxreport_view,'payalloc':payalloc_view}
        if mod in custom:
            if not can(mod): return page('Denied','<div class="panel"><div class="pad"><b>No access.</b></div></div>')
            if not request.args:
                _df = SavedSearch.query.filter_by(username=cur_user().username, module=mod, is_default=True).first()
                if _df and _df.args:
                    return redirect(url_for('modules.module', mod=mod) + '?' + _df.args)
            return custom[mod]()
        abort(404)
    if not can(mod): return page('Denied','<div class="panel"><div class="pad"><b>No access to this section.</b></div></div>')
    # Odoo default saved search: apply the user's default view when the list is
    # opened with no arguments. The redirect adds args, so it never loops.
    if not request.args:
        _u = cur_user()
        _df = SavedSearch.query.filter_by(username=_u.username, module=mod, is_default=True).first()
        if _df and _df.args:
            return redirect(url_for('modules.module', mod=mod) + '?' + _df.args)
    r = REG[mod]
    q = (request.args.get('q') or '').strip()
    period = request.args.get('period') or ''
    dfrom = (request.args.get('from') or '').strip()
    dto = (request.args.get('to') or '').strip()
    query = r['order']()
    model = r['model']
    query = branch_scope(query, model)      # row-level: own branch only
    # ---- text search across configured columns ----
    if q and r.get('search'):
        from sqlalchemy import or_ as _or
        conds = []
        for attr in r['search']:
            col = getattr(model, attr, None)
            if col is not None:
                conds.append(col.ilike(f'%{q}%'))
        if conds:
            query = query.filter(_or(*conds))
    # record per-module search history (recent searches)
    if q:
        try:
            db.session.add(SearchLog(username=cur_user().username, q=q[:120], module=mod))
            db.session.commit()
            log(f'Search {mod}: "{q[:80]}"', action_type='search', entity=mod)
        except Exception:
            db.session.rollback()
    # ---- date period / range filter ----
    df = r.get('date_field')
    if df and hasattr(model, df):
        import datetime as _dt
        col = getattr(model, df)
        tdy = _dt.date.today()
        rng = None
        if period == 'today': rng = (tdy.isoformat(), tdy.isoformat())
        elif period == 'yesterday':
            y = (tdy - _dt.timedelta(days=1)).isoformat(); rng = (y, y)
        elif period == 'week':
            start = (tdy - _dt.timedelta(days=tdy.weekday())).isoformat(); rng = (start, tdy.isoformat())
        elif period == 'month': rng = (tdy.replace(day=1).isoformat(), tdy.isoformat())
        elif period == 'year': rng = (tdy.replace(month=1, day=1).isoformat(), tdy.isoformat())
        elif dfrom or dto: rng = (dfrom or '0000-01-01', dto or '9999-12-31')
        if rng:
            query = query.filter(col >= rng[0], col <= rng[1])
    # ---- dropdown filters (attr == value) ----
    active_filters = {}
    for f in r.get('filters', []):
        fv = (request.args.get(f['name']) or '').strip()
        if fv and hasattr(model, f['attr']):
            query = query.filter(getattr(model, f['attr']) == fv)
            active_filters[f['name']] = fv
    # ---- quick-filter chips + advanced (shared with custom views) ----
    query = _apply_quickfilters(query, model)
    query = _apply_advanced_args(query, model)
    # ---- group-by drill-down: ?group=<col>&gv=<value> narrows to one group ----
    from ..core.crud import groupable_fields, list_fields, money_fields, is_month_col
    from sqlalchemy import func as _fn
    group_col = (request.args.get('group') or '').strip()
    gvals = {n for n, _l, _k in groupable_fields(model)}
    if group_col not in gvals:
        group_col = ''
    gv = request.args.get('gv')
    if group_col and gv is not None:
        col = getattr(model, group_col)
        if is_month_col(group_col):
            query = query.filter(_fn.substr(col, 1, 7) == gv)
        elif gv == '—':
            query = query.filter((col.is_(None)) | (col == ''))
        else:
            query = query.filter(col == gv)

    # ---- sort: any scalar column, either direction ----
    sort_col = (request.args.get('sort') or '').strip()
    sort_dir = 'asc' if request.args.get('dir') == 'asc' else 'desc'
    sortable = {n for n, _l, _k in list_fields(model)}
    if sort_col in sortable:
        c = getattr(model, sort_col)
        query = query.order_by(None).order_by(c.asc() if sort_dir == 'asc' else c.desc())

    # ---- group summary view (no drill-down yet) ----
    if group_col and gv is None:
        col = getattr(model, group_col)
        key = _fn.substr(col, 1, 7) if is_month_col(group_col) else col
        sums = [_fn.sum(getattr(model, m)).label(m) for m in money_fields(model)]
        grp = (query.session.query(key.label('k'), _fn.count(model.id).label('n'), *sums)
               .select_from(model))
        # re-apply the same filters to the aggregate query
        if query.whereclause is not None:
            grp = grp.filter(query.whereclause)
        grp = grp.group_by(key).order_by(_fn.count(model.id).desc())
        rows_g = grp.all()
        mf = money_fields(model)
        head = "<th>" + h(dict((n, l) for n, l, _k in groupable_fields(model)).get(group_col, group_col)) + "</th><th class='num'>Count</th>"
        head += ''.join(f"<th class='num'>{h(m.replace('_',' ').title())}</th>" for m in mf)
        body_g = ''
        tot_n = 0; tot_m = [0.0] * len(mf)
        for r_ in rows_g:
            k = r_.k if (r_.k is not None and str(r_.k) != '') else '—'
            tot_n += r_.n
            cells = ''
            for i, m in enumerate(mf):
                v = getattr(r_, m) or 0
                tot_m[i] += v
                cells += f"<td class='num'>{money(v)}</td>"
            link = url_for('modules.module', mod=mod, **{**{kk: vv for kk, vv in request.args.items()}, 'gv': k})
            body_g += (f"<tr><td><a href='{link}' style='color:var(--petrol);font-weight:600'>{h(str(k))}</a></td>"
                       f"<td class='num'>{r_.n:,}</td>{cells}</tr>")
        body_g += (f"<tr style='font-weight:700;background:var(--canvas)'><td>Total</td><td class='num'>{tot_n:,}</td>"
                   + ''.join(f"<td class='num'>{money(v)}</td>" for v in tot_m) + "</tr>")
        toolbar_g = _list_toolbar(mod, r, q, period, dfrom, dto, active_filters, tot_n,
                                  group_col=group_col, sort_col=sort_col, sort_dir=sort_dir, model=model)
        return page(r['label'], f"""<div class="panel"><div class="ph"><h2>{h(r['label'])} — grouped</h2>
          <span class="so">{len(rows_g)} group(s)</span><div class="sp"></div>
          <a class="btn primary" href="{url_for('modules.module_new',mod=mod)}">+ New {h(r['singular'])}</a></div>{toolbar_g}
          <div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{body_g}</tbody></table></div></div>""", mod)

    # ---- pagination: never render an unbounded table ----
    try:
        per_page = max(10, min(500, int(setting('list_page_size', '50') or 50)))
    except (TypeError, ValueError):
        per_page = 50
    total = query.count()
    pages = max(1, -(-total // per_page))          # ceil
    page_no = request.args.get('page', type=int) or 1
    page_no = max(1, min(page_no, pages))
    rows = query.limit(per_page).offset((page_no - 1) * per_page).all()
    from flask import render_template
    # role-based column hiding: hide_columns maps 'Header' -> [roles that must NOT see it]
    _role = (cur_user().role if cur_user() else '')
    _hide = r.get('hide_columns') or {}
    cols = [c for c in r['columns'] if _role not in _hide.get(c[0], [])]
    headers = [h(c[0]) for c in cols] + ['']
    aligns = [(c[2] if len(c) > 2 else '') for c in cols] + ['num']
    body_rows = []
    for o in rows:
        acts = (f"<a class='btn gh sm' href='{url_for('modules.module_edit',mod=mod,oid=o.id)}'>Edit</a>"
                f"<a class='btn gh sm' href='{url_for('modules.module_del',mod=mod,oid=o.id)}' onclick=\"return confirm('Delete?')\">Delete</a>")
        cells = [c[1](o) for c in cols]
        if q:
            cells = [_hl_cell(cc, q) for cc in cells]
        body_rows.append(cells + [acts])
    empty_msg = 'No records match your filter.' if (q or period or dfrom or dto or active_filters) else f"Add your first {h(r['singular'].lower())}."
    toolbar = _list_toolbar(mod, r, q, period, dfrom, dto, active_filters, total,
                            group_col=group_col, sort_col=sort_col, sort_dir=sort_dir, model=model)
    pager = _pager(mod, page_no, pages, total, per_page)
    body = render_template('list_page.html', title=h(r['label']),
                           toolbar=f"<a class=\"btn primary\" href=\"{url_for('modules.module_new',mod=mod)}\">+ New {h(r['singular'])}</a>",
                           filterbar=toolbar, footer=pager,
                           headers=headers, aligns=aligns, rows=body_rows,
                           empty=f"<div class='empty'><b>No records</b>{empty_msg}</div>")
    return page(r['label'], body, mod)


def _pager(mod, page_no, pages, total, per_page):
    """Page controls that keep the current search/filter arguments."""
    if total <= per_page:
        return ''
    keep = {k: v for k, v in request.args.items() if k != 'page'}
    def link(n, label, disabled=False, current=False):
        if disabled:
            return f"<span class='pg-x'>{label}</span>"
        args = dict(keep); args['page'] = n
        cls = 'pg-a on' if current else 'pg-a'
        return f"<a class='{cls}' href='{url_for('modules.module', mod=mod, **args)}'>{label}</a>"
    # window of page numbers around the current one
    lo = max(1, page_no - 2); hi = min(pages, page_no + 2)
    nums = ''
    if lo > 1:
        nums += link(1, '1') + ("<span class='pg-x'>…</span>" if lo > 2 else '')
    for n in range(lo, hi + 1):
        nums += link(n, str(n), current=(n == page_no))
    if hi < pages:
        nums += ("<span class='pg-x'>…</span>" if hi < pages - 1 else '') + link(pages, str(pages))
    first = (page_no - 1) * per_page + 1
    last = min(total, page_no * per_page)
    return (f"<div class='pager'>"
            f"<span class='pg-info'>{first:,}–{last:,} of {total:,}</span>"
            f"<div class='sp' style='flex:1'></div>"
            f"{link(page_no-1, '‹ Prev', disabled=(page_no<=1))}{nums}"
            f"{link(page_no+1, 'Next ›', disabled=(page_no>=pages))}</div>")


def _apply_quickfilters(query, model):
    """Apply ?status= / ?active=1|0 / ?mine=1 chips to any query."""
    qf_status = (request.args.get('status') or '').strip()
    if qf_status and hasattr(model, 'status'):
        query = query.filter(getattr(model, 'status') == qf_status)
    qf_active = request.args.get('active')
    if qf_active in ('1', '0') and hasattr(model, 'active'):
        query = query.filter(getattr(model, 'active') == (qf_active == '1'))
    if request.args.get('mine') == '1':
        u = cur_user()
        for _own in ('created_by', 'by', 'nurse', 'attending', 'radiologist', 'tech'):
            if u and hasattr(model, _own):
                query = query.filter(getattr(model, _own) == u.username)
                break
    return query


def _apply_advanced_args(query, model):
    """Apply the advanced builder (?adv=<json>&join=and|or) to any query."""
    adv_raw = request.args.get('adv') or ''
    if adv_raw:
        import json as _json
        from ..core.crud import apply_advanced
        try:
            query = apply_advanced(query, model, _json.loads(adv_raw), request.args.get('join', 'and'))
        except Exception:
            pass
    return query


def _apply_period_simple(query, model, date_field):
    """Apply ?period=today|yesterday|week|month|year and ?from/?to on a date column."""
    if not (date_field and hasattr(model, date_field)):
        return query
    import datetime as _dt
    col = getattr(model, date_field)
    period = (request.args.get('period') or '').strip()
    dfrom = (request.args.get('from') or '').strip()
    dto = (request.args.get('to') or '').strip()
    today = _dt.date.today()
    if period == 'today':
        query = query.filter(col == today.isoformat())
    elif period == 'yesterday':
        query = query.filter(col == (today - _dt.timedelta(days=1)).isoformat())
    elif period == 'week':
        start = today - _dt.timedelta(days=today.weekday())
        query = query.filter(col >= start.isoformat())
    elif period == 'month':
        query = query.filter(col >= today.replace(day=1).isoformat())
    elif period == 'year':
        query = query.filter(col >= today.replace(month=1, day=1).isoformat())
    if dfrom:
        query = query.filter(col >= dfrom)
    if dto:
        query = query.filter(col <= dto)
    return query


def search_view(mod, model, query, search_cols=None, date_field=None, has_search=True, basic=False, extra_or=None, placeholder='Search…'):
    """Reusable Odoo-style search view for CUSTOM (non-registry) list pages.

    Applies the current request's search/quick-filters/advanced to `query` and
    returns (filtered_query, q, filterbar_html). The page keeps its own columns,
    actions and pagination; it just filters the query and drops filterbar_html
    into list_page.html's `filterbar` slot. Highlight cells with `hl(html, q)`.

    basic=True renders only the search box (no chips/favorites/advanced panel) —
    used where exposing every field name (e.g. price) would be inappropriate for
    the viewer's role.
    """
    q = (request.args.get('q') or '').strip()
    if q and (search_cols or extra_or):
        from sqlalchemy import or_ as _or
        conds = [db.cast(getattr(model, c), db.String).ilike(f'%{q}%')
                 for c in (search_cols or []) if hasattr(model, c)]
        if extra_or:
            try:
                conds += list(extra_or(q))
            except Exception:
                pass
        if conds:
            query = query.filter(_or(*conds))
        try:
            db.session.add(SearchLog(username=cur_user().username, q=q[:120], module=mod))
            db.session.commit()
            log(f'Search {mod}: "{q[:80]}"', action_type='search', entity=mod)
        except Exception:
            db.session.rollback()
    query = _apply_period_simple(query, model, date_field)
    query = _apply_quickfilters(query, model)
    query = _apply_advanced_args(query, model)
    # toolbar: a compact search box + the shared chips/favorites/advanced/recent
    box = ''
    if has_search:
        box = (f"<form method='get' class='listbar' style='margin-bottom:6px'>"
               f"<input name='q' value='{h(q)}' placeholder='{h(placeholder)}' class='lb-input' autocomplete='off' "
               f"oninput=\"clearTimeout(window._lbT);window._lbT=setTimeout(()=>this.form.submit(),450)\">"
               f"<button class='btn sm'>Search</button>"
               + (f"<a class='btn gh sm' href='?'>Reset</a>" if q else '')
               + f"<span class='lb-count'>{query.count():,} result(s)</span></form>")
    r = {'date_field': date_field, 'search': search_cols or []}
    filterbar = ("<div class='pad' style='border-bottom:1px solid var(--line)'>" + box + "</div>"
                 + ('' if basic else _searchview_extras(mod, r, model, q)))
    return query, q, filterbar


def hl(html_str, q):
    """Public alias for highlighting matches in a rendered cell."""
    return _hl_cell(html_str, q)


def _jsq(s):
    """Safe single-quoted JS string literal."""
    import json as _json
    return "'" + (_json.dumps(str(s or ''))[1:-1].replace("'", "\\'")) + "'"


def _hl_cell(html_str, q):
    """Wrap case-insensitive matches of q in <mark>, only in text (never inside tags)."""
    if not q:
        return html_str
    import re
    parts = re.split(r'(<[^>]+>)', str(html_str))
    pat = re.compile('(' + re.escape(q) + ')', re.I)
    for i in range(0, len(parts), 2):
        if parts[i]:
            parts[i] = pat.sub(r'<mark>\1</mark>', parts[i])
    return ''.join(parts)


@bp.route('/m/<mod>/fav/save', methods=['POST'])
@login_required
def savedsearch_save(mod):
    if not can(mod):
        abort(403)
    u = cur_user()
    name = (request.form.get('name') or '').strip()[:80]
    args = (request.form.get('args') or '').strip()[:600]
    if name:
        db.session.add(SavedSearch(username=u.username, module=mod, name=name, args=args,
                                   shared=(request.form.get('shared') == '1')))
        db.session.commit()
        log(f'Saved search "{name}" for {mod}', action_type='favorite', entity=mod)
        flash('Saved search created', 'ok')
    return redirect(url_for('modules.module', mod=mod) + (('?' + args) if args else ''))


@bp.route('/m/<mod>/fav/<int:sid>/<act>')
@login_required
def savedsearch_action(mod, sid, act):
    if not can(mod):
        abort(403)
    u = cur_user()
    f = SavedSearch.query.get_or_404(sid)
    if f.module != mod or f.username != u.username:   # only the owner manages it
        abort(403)
    if act == 'pin':
        f.pinned = not f.pinned
    elif act == 'default':
        SavedSearch.query.filter_by(username=u.username, module=mod, is_default=True).update({'is_default': False})
        f.is_default = True
    elif act == 'share':
        f.shared = not f.shared
    elif act == 'rename':
        nm = (request.args.get('name') or '').strip()[:80]
        if nm:
            f.name = nm
    elif act == 'del':
        db.session.delete(f)
    db.session.commit()
    return redirect(url_for('modules.module', mod=mod))


def _list_toolbar(mod, r, q, period, dfrom, dto, active_filters, n,
                  group_col='', sort_col='', sort_dir='desc', model=None):
    """Search + date-period + dropdown filters for a generic list page."""
    has_search = bool(r.get('search'))
    has_date = bool(r.get('date_field') and hasattr(r['model'], r.get('date_field') or ''))
    has_filters = bool(r.get('filters'))
    # sort / group / export are available on every list, so the toolbar always renders
    parts = ["<form method='get' class='listbar'>"]
    if has_search:
        # Tell the user exactly what the box searches on (e.g. Patients → ID, name, phone).
        _labels = {'mrn': 'ID', 'name': 'name', 'phone': 'phone', 'gov_id': 'National ID',
                   'code': 'code', 'serial': 'serial', 'email': 'email'}
        _fields = [_labels.get(a, a.replace('_', ' ')) for a in (r.get('search') or [])]
        # de-dupe while keeping order
        _seen = []
        for _f in _fields:
            if _f not in _seen:
                _seen.append(_f)
        _ph = ('Search by ' + ', '.join(_seen[:4]) + '…') if _seen else 'Search…'
        parts.append(f"<input name='q' value='{h(q)}' placeholder='{h(_ph)}' class='lb-input' "
                     f"autocomplete='off' oninput=\"clearTimeout(window._lbT);window._lbT=setTimeout(()=>this.form.submit(),450)\">")
    if has_date:
        opts = [('', 'All dates'), ('today', 'Today'), ('yesterday', 'Yesterday'),
                ('week', 'This Week'), ('month', 'This Month'), ('year', 'This Year')]
        sel = ''.join(f"<option value='{v}' {'selected' if period==v else ''}>{lb}</option>" for v, lb in opts)
        parts.append(f"<select name='period' class='lb-input'>{sel}</select>")
        parts.append(f"<input type='date' name='from' value='{h(dfrom)}' class='lb-input' title='From'>")
        parts.append(f"<input type='date' name='to' value='{h(dto)}' class='lb-input' title='To'>")
    for f in r.get('filters', []):
        cur = active_filters.get(f['name'], '')
        opts = "<option value=''>" + h(f.get('label', f['name'])) + "</option>"
        opts += ''.join(f"<option value='{h(str(v))}' {'selected' if cur==str(v) else ''}>{h(str(lb))}</option>"
                        for v, lb in f['options'])
        parts.append(f"<select name='{f['name']}' class='lb-input'>{opts}</select>")
    # ---- sort / group: derived from the model, so every list behaves alike ----
    if model is not None:
        from ..core.crud import list_fields, groupable_fields
        sopts = "<option value=''>Sort: default</option>" + ''.join(
            f"<option value='{n}' {'selected' if sort_col==n else ''}>Sort: {h(lb)}</option>"
            for n, lb, _k in list_fields(model))
        parts.append(f"<select name='sort' class='lb-input'>{sopts}</select>")
        parts.append(f"<select name='dir' class='lb-input'>"
                     f"<option value='desc' {'selected' if sort_dir=='desc' else ''}>↓ Desc</option>"
                     f"<option value='asc' {'selected' if sort_dir=='asc' else ''}>↑ Asc</option></select>")
        gopts = "<option value=''>No grouping</option>" + ''.join(
            f"<option value='{n}' {'selected' if group_col==n else ''}>Group by {h(lb)}</option>"
            for n, lb, _k in groupable_fields(model))
        parts.append(f"<select name='group' class='lb-input' onchange=\"this.form.gv.value='';this.form.submit()\">{gopts}</select>")
        parts.append("<input type='hidden' name='gv' value=''>")
    parts.append("<button class='btn sm'>Apply</button>")
    if q or period or dfrom or dto or active_filters or group_col or sort_col:
        parts.append(f"<a class='btn gh sm' href='{url_for('modules.module', mod=mod)}'>Reset</a>")
    # export keeps exactly what is on screen
    exp_args = {k: v for k, v in request.args.items() if k != 'page'}
    parts.append(f"<a class='btn gh sm' href='{url_for('modules.module_export', mod=mod, **exp_args)}'>⭳ CSV</a>")
    parts.append(f"<span class='lb-count'>{n:,} result(s)</span>")
    parts.append("</form>")
    base = "<div class='pad' style='border-bottom:1px solid var(--line)'>" + ''.join(parts) + "</div>"
    extra = _searchview_extras(mod, r, model, q)
    return base + extra


def _cur_args(extra=None, drop=None):
    a = {k: v for k, v in request.args.items() if k not in (drop or ())}
    if extra:
        a.update(extra)
    return a


def _searchview_extras(mod, r, model, q):
    """Odoo-style quick-filter chips, Favorites, Advanced builder and Recent."""
    if model is None:
        return ''
    u = cur_user()
    chips = []

    def chip(label, args, on):
        href = url_for('modules.module', mod=mod, **_cur_args(extra=args))
        cls = 'primary' if on else 'gh'
        return f"<a class='btn sm {cls}' href='{h(href)}'>{h(label)}</a>"

    # date quick chips (if the list has a date field)
    if r.get('date_field') and hasattr(model, r['date_field']):
        cur = request.args.get('period') or ''
        for val, lbl in [('today', 'Today'), ('week', 'This Week'), ('month', 'This Month'), ('year', 'This Year')]:
            chips.append(chip(lbl, {'period': ('' if cur == val else val)}, cur == val))
    # active / inactive
    if hasattr(model, 'active'):
        av = request.args.get('active')
        chips.append(chip('Active', {'active': ('' if av == '1' else '1')}, av == '1'))
        chips.append(chip('Inactive', {'active': ('' if av == '0' else '0')}, av == '0'))
    # status values actually present
    if hasattr(model, 'status'):
        try:
            vals = [v[0] for v in db.session.query(getattr(model, 'status')).distinct().limit(12).all() if v[0]]
        except Exception:
            vals = []
        cur = request.args.get('status') or ''
        for v in vals[:8]:
            chips.append(chip(v, {'status': ('' if cur == v else v)}, cur == v))
    # assigned to me
    if any(hasattr(model, o) for o in ('created_by', 'by', 'nurse', 'attending')):
        mine = request.args.get('mine') == '1'
        chips.append(chip('Assigned to me', {'mine': ('' if mine else '1')}, mine))

    chips_html = ("<div class='pad' style='border-bottom:1px solid var(--line);display:flex;gap:6px;flex-wrap:wrap;align-items:center'>"
                  "<span style='font-size:12px;color:var(--muted)'>Filters:</span>" + ''.join(chips)
                  + _favorites_html(mod, u) + _advanced_button(mod, model)
                  + "</div>") if (chips or True) else ''

    # recent searches for this module
    rec = []
    seen = set()
    for s in (SearchLog.query.filter_by(username=u.username, module=mod)
              .order_by(SearchLog.id.desc()).limit(30).all()):
        k = (s.q or '').lower()
        if k and k not in seen:
            seen.add(k)
            rec.append(s.q)
        if len(rec) >= 6:
            break
    rec_html = ''
    if rec:
        links = ' '.join(f"<a class='btn gh sm' href='{h(url_for('modules.module', mod=mod, q=t))}'>🕘 {h(t)}</a>" for t in rec)
        rec_html = ("<div class='pad' style='border-bottom:1px solid var(--line);display:flex;gap:6px;flex-wrap:wrap;align-items:center'>"
                    "<span style='font-size:12px;color:var(--muted)'>Recent:</span>" + links + "</div>")

    return chips_html + rec_html + _advanced_panel(mod, model)


def _favorites_html(mod, u):
    favs = (SavedSearch.query
            .filter(SavedSearch.module == mod,
                    db.or_(SavedSearch.username == u.username, SavedSearch.shared == True))  # noqa: E712
            .order_by(SavedSearch.pinned.desc(), SavedSearch.id.desc()).all())
    items = ''
    for f in favs:
        star = '★' if f.pinned else '☆'
        dflt = " <span class='pill green'>default</span>" if f.is_default else ''
        shic = ' 👥' if f.shared else ''
        own = (f.username == u.username)
        applyl = url_for('modules.module', mod=mod) + ('?' + f.args if f.args else '')
        acts = (f"<a href='{url_for('modules.savedsearch_action', mod=mod, sid=f.id, act='pin')}' title='Pin'>{star}</a> "
                f"<a href='{url_for('modules.savedsearch_action', mod=mod, sid=f.id, act='default')}' title='Set default'>⚑</a> "
                + (f"<a href='#' title='Rename' onclick=\"var n=prompt('Rename',{_jsq(f.name)});if(n)location='{url_for('modules.savedsearch_action', mod=mod, sid=f.id, act='rename')}?name='+encodeURIComponent(n);return false\">✎</a> " if own else '')
                + (f"<a href='{url_for('modules.savedsearch_action', mod=mod, sid=f.id, act='share')}' title='Share with team'>{'👥' if not f.shared else '🔒'}</a> " if own else '')
                + (f"<a href='{url_for('modules.savedsearch_action', mod=mod, sid=f.id, act='del')}' title='Delete' onclick=\"return confirm('Delete favorite?')\">✕</a>" if own else ''))
        items += (f"<div style='display:flex;justify-content:space-between;gap:10px;padding:4px 8px'>"
                  f"<a href='{h(applyl)}' style='font-weight:600'>{h(f.name)}{dflt}{shic}</a>"
                  f"<span style='white-space:nowrap'>{acts}</span></div>")
    if not items:
        items = "<div style='padding:6px 8px;color:var(--muted);font-size:12px'>No saved searches yet.</div>"
    # save-current form (captures the current querystring)
    cur_qs = '&'.join(f"{k}={h(v)}" for k, v in request.args.items() if k != 'page')
    from ..core.security import csrf_token
    save = (f"<form method='post' action='{url_for('modules.savedsearch_save', mod=mod)}' style='display:flex;gap:4px;padding:6px 8px;border-top:1px solid var(--line)'>"
            f"<input type='hidden' name='_csrf' value='{h(csrf_token())}'>"
            f"<input type='hidden' name='args' value='{h(cur_qs)}'>"
            f"<input name='name' placeholder='Save current as…' class='lb-input' style='flex:1' required>"
            f"<label style='font-size:11px;color:var(--muted)'><input type='checkbox' name='shared' value='1'> share</label>"
            f"<button class='btn sm primary'>Save</button></form>")
    return (f"<details style='position:relative;display:inline-block'><summary class='btn sm gh' style='list-style:none'>⭐ Favorites</summary>"
            f"<div style='position:absolute;z-index:50;top:110%;left:0;min-width:280px;background:var(--surface);"
            f"border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow)'>{items}{save}</div></details>")


def _advanced_button(mod, model):
    return "<button type='button' class='btn sm gh' onclick=\"var a=document.getElementById('advpanel');a.style.display=a.style.display=='none'?'block':'none'\">⚙ Advanced</button>"


def _advanced_panel(mod, model):
    from ..core.crud import filter_fields, ADV_OPS
    fopts = ''.join(f"<option value='{n}'>{h(lb)}</option>" for n, lb, _k in filter_fields(model))
    oopts = ''.join(f"<option value='{o}'>{h(l)}</option>" for o, l in ADV_OPS)
    cur_adv = h(request.args.get('adv') or '')
    cur_join = request.args.get('join', 'and')
    # preserve non-adv args as hidden inputs so advanced search stacks on filters
    hid = ''.join(f"<input type='hidden' name='{h(k)}' value='{h(v)}'>"
                  for k, v in request.args.items() if k not in ('adv', 'join', 'page'))
    return f"""
    <div id='advpanel' style='display:none' class='pad'>
      <div style='border:1px solid var(--line);border-radius:10px;padding:10px'>
        <div style='display:flex;gap:8px;align-items:center;margin-bottom:6px'>
          <b style='font-size:13px'>Advanced search</b>
          <select id='advjoin' class='lb-input'><option value='and' {'selected' if cur_join=='and' else ''}>Match ALL (AND)</option><option value='or' {'selected' if cur_join=='or' else ''}>Match ANY (OR)</option></select>
          <button type='button' class='btn sm' onclick='advAdd()'>+ Condition</button>
          <div class='sp' style='flex:1'></div>
          <span style='font-size:11px;color:var(--muted)'>field · operator · value</span>
        </div>
        <div id='advrows'></div>
        <form method='get' id='advform' style='margin-top:8px'>
          {hid}
          <input type='hidden' name='adv' id='advout'>
          <input type='hidden' name='join' id='advjoinout' value='{cur_join}'>
          <button class='btn sm primary' onclick='return advApply()'>Apply advanced</button>
          <a class='btn sm gh' href='{url_for('modules.module', mod=mod)}'>Clear</a>
        </form>
      </div>
    </div>
    <script>
    (function(){{
      var FIELDS=`{fopts}`, OPS=`{oopts}`;
      window.advAdd=function(f,op,v,v2){{
        var d=document.createElement('div'); d.className='advrow';
        d.style.cssText='display:flex;gap:6px;margin:4px 0;flex-wrap:wrap';
        d.innerHTML="<select class='lb-input af'>"+FIELDS+"</select>"+
          "<select class='lb-input ao'>"+OPS+"</select>"+
          "<input class='lb-input av' placeholder='value'>"+
          "<input class='lb-input av2' placeholder='and…' style='display:none'>"+
          "<button type='button' class='btn sm gh' onclick='this.parentNode.remove()'>✕</button>";
        document.getElementById('advrows').appendChild(d);
        var ao=d.querySelector('.ao'); ao.addEventListener('change',function(){{
          var b=['empty','nempty','true','false'].indexOf(ao.value)>=0;
          d.querySelector('.av').style.display=b?'none':''; d.querySelector('.av2').style.display=(ao.value=='between')?'':'none';
        }});
        if(f){{d.querySelector('.af').value=f;}} if(op){{ao.value=op;ao.dispatchEvent(new Event('change'));}}
        if(v!=null)d.querySelector('.av').value=v; if(v2!=null)d.querySelector('.av2').value=v2;
      }};
      window.advApply=function(){{
        var rows=[].map.call(document.querySelectorAll('#advrows .advrow'),function(d){{
          return {{f:d.querySelector('.af').value,op:d.querySelector('.ao').value,
                   v:d.querySelector('.av').value,v2:d.querySelector('.av2').value}}; }})
          .filter(function(c){{return c.f&&c.op}});
        document.getElementById('advout').value=rows.length?JSON.stringify(rows):'';
        document.getElementById('advjoinout').value=document.getElementById('advjoin').value;
        return true;
      }};
      var cur='{cur_adv}';
      if(cur){{try{{JSON.parse(cur).forEach(function(c){{advAdd(c.f,c.op,c.v,c.v2)}});document.getElementById('advpanel').style.display='block';}}catch(e){{}}}}
    }})();
    </script>"""

def apply_form(o, fields):
    for f in fields:
        t = f.get('type')
        if t == 'file': continue                     # handled separately (uploads)
        v = request.form.get(f['name'])
        if t == 'number': v = float(v) if v not in (None,'') else 0
        elif t == 'checkbox': v = (v == '1')
        elif f.get('as_bool'): v = (v == '1')
        setattr(o, f['name'], v)


PAT_PHOTO_DIR = None

def _save_patient_photo(mod, o):
    """Store an uploaded patient photo (jpg/png) as uploads/pat/p<id>.<ext>."""
    if mod != 'patients': return
    f = request.files.get('photo')
    if not f or not f.filename: return
    import os
    from ..config import DATA_DIR
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        flash('Photo must be an image (jpg/png/webp)'); return
    d = os.path.join(DATA_DIR, 'uploads', 'pat'); os.makedirs(d, exist_ok=True)
    name = f'p{o.id}{ext}'
    f.save(os.path.join(d, name))
    o.photo = name; db.session.commit()


def _doctor_portal_pw(mod, o):
    """Hash the portal password on doctors / remote-radiologists forms."""
    if mod not in ('doctors', 'radiologists'): return
    pw = request.form.get('portal_pw_set')
    if not pw: return
    from ..core.security import pw_policy_error
    err = pw_policy_error(pw)
    if err:
        flash(err + ' — portal password NOT changed'); return
    from werkzeug.security import generate_password_hash
    o.portal_pw = generate_password_hash(pw)
    db.session.commit()
    flash('Portal password set')


def _consult_followup(mod, o):
    """Completing a consultation with a follow-up date books the appointment."""
    if mod != 'consult' or not getattr(o, 'followup_date', None): return
    from ..models import Appointment
    if Appointment.query.filter_by(patient_id=o.patient_id, date=o.followup_date).first(): return
    db.session.add(Appointment(patient_id=o.patient_id, date=o.followup_date,
                               department='Consultation', doctor=o.doctor,
                               visit_type='Follow-up', status='Scheduled',
                               notes=f'Auto: follow-up of consultation #{o.id}'))
    db.session.commit()
    from ..core.notify import notify
    notify(f'Follow-up booked {o.followup_date} · {o.patient.name if o.patient else ""}',
           '/m/appointments', role='reception')

@bp.route('/m/<mod>/new', methods=['GET','POST'])
@login_required
def module_new(mod):
    if mod not in REG or not can(mod): abort(403)
    # Purchases use the dedicated Odoo-style RFQ / Purchase Order form
    if mod == 'purchases':
        return redirect(url_for('inventory.po_form'))
    if mod == 'expenses':
        return redirect(url_for('expenses.expense_form'))
    r = REG[mod]; fields = [{**f, 'options': resolve_options(f)} if f.get('type') in ('select','datalist') else f for f in r['fields']]
    # one-place workflow: any field can be prefilled via URL args, e.g. /m/consult/new?patient_id=5
    fields = [{**f, 'default': request.args.get(f['name'], f.get('default',''))} for f in fields]
    if request.method == 'POST':
        _d = request.form.get('date')
        if mod in POST_HOOKS and _d and not _period_open(_d):
            flash(f'Period closed: cannot post to {_d[:7]}. Reopen it in Accounting → Fiscal Periods.')
            return redirect(url_for('modules.module_new', mod=mod))
        if mod == 'patients' and not request.form.get('dup_ok'):
            _ph=(request.form.get('phone') or '').strip()
            _nm=(request.form.get('name') or '').strip()
            _dup=None
            if _ph: _dup=Patient.query.filter(Patient.phone==_ph).first()
            if not _dup and _nm: _dup=Patient.query.filter(db.func.lower(Patient.name)==_nm.lower()).first()
            if _dup:
                from urllib.parse import urlencode
                import datetime as _dt
                _args={k:v for k,v in request.form.items() if k not in ('_csrf','photo')}
                _args['dup_ok']='1'
                _reg_today = bool(getattr(_dup, 'created', None)) and str(_dup.created)[:10] == _dt.date.today().isoformat()
                if _reg_today:
                    flash(f"Patient already registered today: {_dup.name} ({_dup.mrn}). Open their record to continue, or press Save again if this is a different person.")
                else:
                    flash(f"Possible duplicate: {_dup.name} ({_dup.mrn}{', ' + _dup.phone if _dup.phone else ''}) is already registered. Open their record to check, or press Save again to register anyway.")
                return redirect(url_for('modules.module_new', mod='patients')+'?'+urlencode(_args))
        o = r['model']()
        apply_form(o, r['fields'])
        if mod == 'patients' and not o.mrn:
            o.mrn = 'MRN' + str((Patient.query.count() or 0)+1001)
        if mod == 'patients':
            o.reg_by = (cur_user().name or cur_user().username) if cur_user() else None
        if hasattr(o,'branch_id') and getattr(o,'branch_id',None) is None and cur_user():
            o.branch_id = cur_user().branch_id
        db.session.add(o); db.session.commit()
        _save_patient_photo(mod, o)
        _consult_followup(mod, o)
        _doctor_portal_pw(mod, o)
        _h=POST_HOOKS.get(mod)
        if _h:
            try: _h(o)
            except Exception:
                db.session.rollback()
                from ..core.helpers import log_error; log_error(f'POST_HOOK {mod} create #{getattr(o,"id","?")}')
        log(f'Added {r["singular"]}: ' + (getattr(o,"name",None) or str(o.id)))
        if mod == 'patients':
            from ..core.notify import notify_event
            notify_event('patient_registered',
                         f'New patient registered: {getattr(o,"name","")} (MRN {getattr(o,"mrn","")})',
                         link=url_for('patients.patient_detail', pid=o.id))
            flash(f'Patient registered — MRN {getattr(o,"mrn","")}. Continue the workflow below.')
            return redirect(url_for('patients.patient_detail', pid=o.id))
        flash(f'{r["singular"]} added'); return redirect(url_for('modules.module', mod=mod))
    return page('New '+r['singular'], render_form('New '+r['singular'], url_for('modules.module_new',mod=mod), fields, back=url_for('modules.module',mod=mod), enctype=r.get('enctype')), mod)

@bp.route('/m/<mod>/<int:oid>/edit', methods=['GET','POST'])
@login_required
def module_edit(mod, oid):
    if mod not in REG or not can(mod): abort(403)
    if mod == 'purchases':
        return redirect(url_for('inventory.po_form', pid=oid))
    if mod == 'expenses':
        return redirect(url_for('expenses.expense_view', eid=oid))
    r = REG[mod]; o = r['model'].query.get_or_404(oid)
    if not can_see(o): abort(403)          # row-level: no cross-branch access by URL
    fields = [{**f, 'options': resolve_options(f)} if f.get('type') in ('select','datalist') else f for f in r['fields']]
    if request.method == 'POST':
        _d = request.form.get('date')
        if mod in POST_HOOKS and _d and not _period_open(_d):
            flash(f'Period closed: cannot post to {_d[:7]}. Reopen it in Accounting → Fiscal Periods.')
            return redirect(url_for('modules.module_edit', mod=mod, oid=oid))
        _oldprices={k:getattr(o,k,None) for k in ('price','price_insurance','price_corporate','price_vip','price_contract')} if mod=='services' else None
        _SENSITIVE={'pw','password','pin','totp_secret','api_key','secret'}
        _editable=[f['name'] for f in r['fields'] if f['name'] not in _SENSITIVE]
        _before={k:getattr(o,k,None) for k in _editable}
        apply_form(o, r['fields']); db.session.commit()
        _save_patient_photo(mod, o)
        _consult_followup(mod, o)
        _doctor_portal_pw(mod, o)
        if _oldprices:
            for k,ov in _oldprices.items():
                nv=getattr(o,k,None)
                if (ov or 0)!=(nv or 0): log(f"PRICE CHANGE {o.name} {k}: {money(ov or 0)} -> {money(nv or 0)}")
        _h=POST_HOOKS.get(mod)
        if _h:
            try: _h(o)
            except Exception:
                db.session.rollback()
                from ..core.helpers import log_error; log_error(f'POST_HOOK {mod} edit #{oid}')
        _changes=[(k,_before.get(k),getattr(o,k,None)) for k in _editable
                  if (_before.get(k) if _before.get(k) is not None else '') != (getattr(o,k,None) if getattr(o,k,None) is not None else '')]
        if _changes:
            _o='; '.join(f"{k}={ov}" for k,ov,nv in _changes)
            _n='; '.join(f"{k}={nv}" for k,ov,nv in _changes)
            log(f'Edited {r["singular"]} #{oid}', action_type='Edit',
                entity=f'{r["singular"]} #{oid}', old=_o, new=_n)
        else:
            log(f'Edited {r["singular"]} #{oid}', action_type='Edit', entity=f'{r["singular"]} #{oid}')
        flash(f'{r["singular"]} updated'); return redirect(url_for('modules.module', mod=mod))
    return page('Edit '+r['singular'], render_form('Edit '+r['singular'], url_for('modules.module_edit',mod=mod,oid=oid), fields, o, url_for('modules.module',mod=mod), enctype=r.get('enctype')), mod)

@bp.route('/m/<mod>/<int:oid>/delete')
@login_required
def module_del(mod, oid):
    if mod not in REG or not can(mod): abort(403)
    r = REG[mod]; o = r['model'].query.get_or_404(oid)
    if not can_see(o): abort(403)          # row-level: no cross-branch access by URL
    # Soft-delete when the model supports it: keep the row for audit/history,
    # just mark it inactive so it disappears from lists and dropdowns.
    if hasattr(o, 'active'):
        o.active = False
        db.session.commit()
        log(f'Archived {r["singular"]} #{oid} (soft-delete)')
        flash(f'{r["singular"]} archived (kept for records; set Active to restore).')
    else:
        db.session.delete(o); db.session.commit()
        log(f'Deleted {r["singular"]} #{oid}')
        flash('Deleted')
    return redirect(url_for('modules.module', mod=mod))



@bp.route('/m/<mod>/export.csv')
@login_required
def module_export(mod):
    """Export exactly what the current filters/search/sort select — the whole
    result set, not just the page on screen."""
    import csv, io as _io
    if mod not in REG or not can(mod):
        abort(403)
    r = REG[mod]
    model = r['model']
    query = branch_scope(r['order'](), model)

    q = (request.args.get('q') or '').strip()
    if q and r.get('search'):
        from sqlalchemy import or_ as _or
        conds = [getattr(model, a).ilike(f'%{q}%') for a in r['search'] if getattr(model, a, None) is not None]
        if conds:
            query = query.filter(_or(*conds))
    df = r.get('date_field')
    dfrom = (request.args.get('from') or '').strip()
    dto = (request.args.get('to') or '').strip()
    if df and hasattr(model, df) and (dfrom or dto):
        col = getattr(model, df)
        query = query.filter(col >= (dfrom or '0000-01-01'), col <= (dto or '9999-12-31'))
    for f in r.get('filters', []):
        fv = (request.args.get(f['name']) or '').strip()
        if fv and hasattr(model, f['attr']):
            query = query.filter(getattr(model, f['attr']) == fv)
    from ..core.crud import groupable_fields, list_fields, is_month_col
    from sqlalchemy import func as _fn
    gc_ = (request.args.get('group') or '').strip()
    gv = request.args.get('gv')
    if gc_ in {n for n, _l, _k in groupable_fields(model)} and gv:
        col = getattr(model, gc_)
        query = query.filter(_fn.substr(col, 1, 7) == gv) if is_month_col(gc_) else query.filter(col == gv)
    sc = (request.args.get('sort') or '').strip()
    if sc in {n for n, _l, _k in list_fields(model)}:
        c = getattr(model, sc)
        query = query.order_by(None).order_by(c.asc() if request.args.get('dir') == 'asc' else c.desc())

    cols = [c.name for c in model.__table__.columns
            if c.name not in ('pw', 'portal_pw', 'password')]
    out = _io.StringIO()
    w = csv.writer(out)
    w.writerow([c.replace('_', ' ').title() for c in cols])
    n = 0
    for o in query.limit(50000).all():
        w.writerow([getattr(o, c, '') for c in cols])
        n += 1
    log(f'Exported {n} {mod} row(s) to CSV')
    from flask import Response as _R
    return _R(out.getvalue(), mimetype='text/csv',
              headers={'Content-Disposition': f'attachment;filename={mod}-{today()}.csv'})
