"""General Ledger module (Odoo Community 18-style)  (v8.0).

Built on the existing double-entry data — JournalEntry (the move: date/ref/memo)
and JournalLine (the item: account/debit/credit) — plus the Account chart. Adds
an Odoo-style General Ledger workspace: dashboard, general ledger with running
balance, journal items, journal entries, and trial balance, with date/period
filters, search, group-by, sorting, drill-down, totals and CSV/print export.

Read-only by nature (it reports on posted data); role-gated via 'genledger'.
"""
import io
import csv
import datetime as dt
from flask import Blueprint, request, url_for, Response
from markupsafe import escape as h
from ..extensions import db
from ..models import Account, JournalEntry, JournalLine
from ..core.security import can, log, login_required, cur_user
from ..core.helpers import money, today
from ..core.ui import page

bp = Blueprint('genledger', __name__)

TYPE_COLORS = {'Asset': 'blue', 'Liability': 'amber', 'Equity': 'teal', 'Income': 'green', 'Expense': 'red'}

# --------------------------------------------------------------- sub-menu
_TABS = [('gldash', 'Dashboard'), ('genledger', 'General Ledger'),
         ('jitems', 'Journal Items'), ('jentries', 'Journal Entries'),
         ('acctbal', 'Account Balances'), ('trialbal', 'Trial Balance'),
         ('accounts', 'Chart of Accounts')]


def _subnav(active):
    tabs = ''.join(
        f"<a class='{'on' if k == active else ''}' href='{url_for('modules.module', mod=k)}'>{h(lbl)}</a>"
        for k, lbl in _TABS)
    return f"<div class='subnav' style='margin-bottom:14px'><span class='subnav-t'>General Ledger</span>{tabs}</div>"


# --------------------------------------------------------------- date helpers
def _iso(d):
    return d.isoformat()


def _period_range(period):
    """Return (from_iso, to_iso) for a named period, or (None, None)."""
    t = dt.date.today()
    if period == 'today':
        return _iso(t), _iso(t)
    if period == 'week':
        s = t - dt.timedelta(days=t.weekday())
        return _iso(s), _iso(s + dt.timedelta(days=6))
    if period == 'month':
        s = t.replace(day=1)
        nm = (s.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return _iso(s), _iso(nm - dt.timedelta(days=1))
    if period == 'quarter':
        q = (t.month - 1) // 3
        s = dt.date(t.year, q * 3 + 1, 1)
        em = q * 3 + 3
        e = (dt.date(t.year, em, 28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        return _iso(s), _iso(e)
    if period in ('year', 'fiscal'):
        return _iso(dt.date(t.year, 1, 1)), _iso(dt.date(t.year, 12, 31))
    return None, None


def _args():
    a = request.args
    period = a.get('period', '')
    pf, pt = _period_range(period)
    return dict(period=period,
                dfrom=(a.get('from') or pf or ''),
                dto=(a.get('to') or pt or ''),
                account=a.get('account', ''),
                atype=a.get('type', ''),
                creator=(a.get('creator') or '').strip(),
                group=a.get('group', 'account'),
                sort=a.get('sort', 'date'),
                direction=a.get('dir', 'asc'),
                q=(a.get('q') or '').strip(),
                page=a.get('page', type=int) or 1)


def _base_lines(f):
    """Filtered JournalLine query joined to entry + account (no ordering)."""
    qy = (JournalLine.query.join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
          .join(Account, JournalLine.account_id == Account.id))
    if f['dfrom']:
        qy = qy.filter(JournalEntry.date >= f['dfrom'])
    if f['dto']:
        qy = qy.filter(JournalEntry.date <= f['dto'])
    if f['account']:
        qy = qy.filter(JournalLine.account_id == int(f['account']))
    if f['atype']:
        qy = qy.filter(Account.type == f['atype'])
    if f.get('creator'):
        qy = qy.filter(JournalEntry.posted_by == f['creator'])
    if f['q']:
        like = f"%{f['q']}%"
        qy = qy.filter(db.or_(Account.code.ilike(like), Account.name.ilike(like),
                              JournalEntry.ref.ilike(like), JournalEntry.memo.ilike(like)))
    return qy


def _partner_name(entry):
    """Customer/patient name derived from the entry's source document (best-effort)."""
    ref = (entry.ref or '')
    try:
        from ..models import Invoice, PayReceipt
        if ref.startswith(('INV-', 'PAY-', 'REV-INV-', 'REV-PAY-')):
            num = int(ref.replace('REV-', '').split('-')[1])
            inv = Invoice.query.get(num)
            if inv:
                return inv.patient.name if inv.patient else (inv.guarantor or '')
        elif ref.startswith('RCT-'):
            num = int(ref.split('-')[1])
            r = PayReceipt.query.get(num)
            if r and r.invoice:
                return r.invoice.patient.name if r.invoice.patient else (r.invoice.guarantor or '')
    except Exception:
        pass
    return ''


def _ref_link(ref, eid):
    """Drill-down: link a move ref to its source document."""
    ref = ref or (f'JV-{eid:04d}')
    try:
        if ref.startswith(('INV-', 'PAY-', 'REV-INV-', 'REV-PAY-')):
            num = int(ref.replace('REV-', '').split('-')[1])
            return f"<a href='{url_for('billing.invoice_view', iid=num)}' style='color:var(--petrol);font-weight:600'>{h(ref)}</a>"
        if ref.startswith('RCT-'):
            num = int(ref.split('-')[1])
            return f"<a href='/receipt/{num}' style='color:var(--petrol);font-weight:600'>{h(ref)}</a>"
    except Exception:
        pass
    return f"<a href='{url_for('genledger.gl_entry', eid=eid)}' style='color:var(--petrol)'>{h(ref)}</a>"


# --------------------------------------------------------------- 1) Dashboard
def gl_dashboard():
    f = _args()
    tot = db.session.query(
        db.func.coalesce(db.func.sum(JournalLine.debit), 0),
        db.func.coalesce(db.func.sum(JournalLine.credit), 0)).one()
    tdeb, tcred = tot[0] or 0, tot[1] or 0
    n_entries = JournalEntry.query.count()
    n_accts = Account.query.filter_by(active=True).count()

    def kpi(label, val, ac, sub=''):
        return (f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div>"
                f"<div class='v'>{val}</div><div class='s'>{sub}</div></div>")
    kpis = ("<div class='kpis'>"
            + kpi('Total Debit', money(tdeb), 'var(--green)')
            + kpi('Total Credit', money(tcred), 'var(--red)')
            + kpi('Net Balance', money(tdeb - tcred), 'var(--petrol)', 'debit − credit')
            + kpi('Journal Entries', f'{n_entries:,}', 'var(--teal)', f'{n_accts} accounts')
            + "</div>")

    # latest entries
    latest = JournalEntry.query.order_by(JournalEntry.id.desc()).limit(8).all()
    lrows = ''
    for e in latest:
        d = sum((l.debit or 0) for l in e.lines)
        lrows += (f"<tr><td>{h(e.date)}</td><td>{_ref_link(e.ref, e.id)}</td>"
                  f"<td>{h((e.memo or '')[:60])}</td><td class='num'>{money(d)}</td></tr>")
    latest_panel = (f"<div class='panel'><div class='ph'><h2>Latest entries</h2><div class='sp'></div>"
                    f"<a class='btn sm' href='{url_for('modules.module', mod='jentries')}'>All entries →</a></div>"
                    f"<div class='tw'><table><thead><tr><th>Date</th><th>Move</th><th>Description</th>"
                    f"<th class='num'>Amount</th></tr></thead><tbody>{lrows or '<tr><td colspan=4 style=color:var(--muted)>No entries yet</td></tr>'}</tbody></table></div></div>")

    # 6-month debit/credit comparison
    months = []
    t = dt.date.today().replace(day=1)
    for _ in range(6):
        months.append(t)
        t = (t - dt.timedelta(days=1)).replace(day=1)
    months.reverse()
    bars = ''
    mx = 1
    mdata = []
    for m in months:
        s = m.isoformat()
        e = ((m.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)).isoformat()
        row = db.session.query(db.func.coalesce(db.func.sum(JournalLine.debit), 0)).join(JournalEntry).filter(
            JournalEntry.date >= s, JournalEntry.date <= e).scalar() or 0
        mdata.append((m.strftime('%b'), row))
        mx = max(mx, row)
    for lbl, val in mdata:
        hgt = int(90 * val / mx) if mx else 0
        bars += (f"<div style='display:flex;flex-direction:column;align-items:center;gap:4px;flex:1'>"
                 f"<div style='font-size:10px;color:var(--muted)'>{money(val)}</div>"
                 f"<div style='width:70%;height:{hgt}px;background:var(--petrol);border-radius:4px 4px 0 0'></div>"
                 f"<div style='font-size:11px;color:var(--muted)'>{lbl}</div></div>")
    chart = (f"<div class='panel'><div class='ph'><h2>Monthly posting volume · debit</h2></div>"
             f"<div class='pad' style='display:flex;align-items:flex-end;gap:8px;height:150px'>{bars}</div></div>")

    return page('General Ledger', _subnav('gldash') + kpis + latest_panel + chart, 'gldash')


# --------------------------------------------------------------- 2) General Ledger
def _period_chips(f):
    cur = f['period']
    out = "<span style='font-size:12px;color:var(--muted)'>Period:</span>"
    for val, lbl in [('today', 'Today'), ('week', 'This Week'), ('month', 'This Month'),
                     ('quarter', 'This Quarter'), ('year', 'This Year')]:
        args = {k: v for k, v in request.args.items() if k not in ('period', 'from', 'to', 'page')}
        args['period'] = '' if cur == val else val
        href = url_for('modules.module', mod='genledger', **args)
        out += f"<a class='btn sm {'primary' if cur == val else 'gh'}' href='{h(href)}'>{lbl}</a>"
    return out


def _gl_toolbar(f, mod='genledger'):
    accts = Account.query.filter_by(active=True).order_by(Account.code).all()
    aopts = "<option value=''>— All accounts —</option>" + ''.join(
        f"<option value='{a.id}' {'selected' if str(a.id) == f['account'] else ''}>{h(a.code or '')} · {h(a.name)}</option>" for a in accts)
    topts = "<option value=''>— All types —</option>" + ''.join(
        f"<option value='{t}' {'selected' if t == f['atype'] else ''}>{t}</option>" for t in ['Asset', 'Liability', 'Equity', 'Income', 'Expense'])
    gopts = ''.join(f"<option value='{v}' {'selected' if v == f['group'] else ''}>{lbl}</option>"
                    for v, lbl in [('account', 'Account'), ('type', 'Account Type'), ('month', 'Month'), ('none', 'No grouping')])
    # distinct users who have posted journal entries, for the "Created by" filter
    _creators = [r[0] for r in db.session.query(JournalEntry.posted_by)
                 .filter(JournalEntry.posted_by.isnot(None), JournalEntry.posted_by != '')
                 .distinct().order_by(JournalEntry.posted_by).all()]
    copts = "<option value=''>— Created by (all) —</option>" + ''.join(
        f"<option value='{h(c)}' {'selected' if c == f.get('creator') else ''}>{h(c)}</option>" for c in _creators)
    hidden = ''.join(f"<input type='hidden' name='{k}' value='{h(v)}'>" for k, v in request.args.items()
                     if k in ('sort', 'dir'))
    _split_link = (f"<a class='btn gh sm' href='{url_for('acct.split_wallets')}' title='Split old Mobile Money into Sahal / EVC / E. Dahab …'>⇄ Split Mobile Money</a>"
                   if (cur_user() and cur_user().role == 'super_admin') else '')
    form = (f"<form method='get' class='listbar'>{hidden}"
            f"<input name='q' value='{h(f['q'])}' placeholder='Account, code, ref, description…' class='lb-input' "
            f"autocomplete='off' oninput=\"clearTimeout(window._glT);window._glT=setTimeout(()=>this.form.submit(),450)\">"
            f"<input type='date' name='from' value='{h(f['dfrom'])}' class='lb-input' title='From'>"
            f"<input type='date' name='to' value='{h(f['dto'])}' class='lb-input' title='To'>"
            f"<select name='account' class='lb-input'>{aopts}</select>"
            f"<select name='type' class='lb-input'>{topts}</select>"
            f"<select name='creator' class='lb-input' title='Created by'>{copts}</select>"
            f"<select name='group' class='lb-input'>{gopts}</select>"
            f"<button class='btn sm'>Apply</button>"
            f"<a class='btn gh sm' href='{url_for('modules.module', mod=mod)}'>Reset</a>"
            f"<a class='btn gh sm' href='{url_for('genledger.gl_csv')}?{_qs()}'>⭳ CSV</a>"
            f"<a class='btn gh sm' href='{url_for('genledger.gl_print')}?{_qs()}' data-pdf='{url_for('genledger.gl_pdf')}?{_qs()}' target='_blank'>🖨 Print</a>"
            f"{_split_link}"
            f"</form>")
    chips = f"<div class='pad' style='display:flex;gap:6px;flex-wrap:wrap;align-items:center;border-top:1px solid var(--line)'>{_period_chips(f)}</div>"
    return f"<div class='pad' style='border-bottom:1px solid var(--line)'>{form}</div>{chips}"


def _qs():
    return '&'.join(f"{k}={h(v)}" for k, v in request.args.items() if k != 'page')


def _sortkey(l, key):
    if key == 'code':
        return (l.account.code or '') if l.account else ''
    if key == 'debit':
        return l.debit or 0
    if key == 'credit':
        return l.credit or 0
    return (l.entry.date or '', l.id)


def _gl_rows(f, for_export=False):
    """Return (rows_data, totals, opening) honoring filters, grouping, sorting."""
    lines = _base_lines(f).all()
    # sort
    rev = (f['direction'] == 'desc')
    lines.sort(key=lambda l: _sortkey(l, f['sort']), reverse=rev)
    tdeb = sum((l.debit or 0) for l in lines)
    tcred = sum((l.credit or 0) for l in lines)

    # opening balance (only meaningful for a single account)
    opening = 0
    if f['account']:
        a = Account.query.get(int(f['account']))
        if a:
            opening = a.opening or 0
            if f['dfrom']:
                prior = db.session.query(
                    db.func.coalesce(db.func.sum(JournalLine.debit), 0) -
                    db.func.coalesce(db.func.sum(JournalLine.credit), 0)).join(JournalEntry).filter(
                    JournalLine.account_id == a.id, JournalEntry.date < f['dfrom']).scalar() or 0
                opening += prior
    return lines, (tdeb, tcred), opening


def general_ledger():
    f = _args()
    lines, (tdeb, tcred), opening = _gl_rows(f)
    total = len(lines)
    per = 100
    pages = max(1, -(-total // per))
    pg = max(1, min(f['page'], pages))
    view = lines[(pg - 1) * per: pg * per]

    # partner (customer/patient) derived from each entry's source document, memoized
    pcache = {}

    def _partner(entry):
        if entry.id in pcache:
            return pcache[entry.id]
        name = ''
        ref = entry.ref or ''
        try:
            from ..models import Invoice, PayReceipt
            if ref.startswith(('INV-', 'PAY-', 'REV-INV-', 'REV-PAY-')):
                num = int(ref.replace('REV-', '').split('-')[1])
                inv = Invoice.query.get(num)
                if inv:
                    name = (inv.patient.name if inv.patient else (inv.guarantor or ''))
            elif ref.startswith('RCT-'):
                num = int(ref.split('-')[1])
                r = PayReceipt.query.get(num)
                if r and r.invoice:
                    name = (r.invoice.patient.name if r.invoice.patient else (r.invoice.guarantor or ''))
        except Exception:
            pass
        pcache[entry.id] = name
        return name

    # build grouped/running rows
    def line_cells(l, run, gid=None):
        acc = l.account
        hidden = (gid is not None)
        cls = f"glrow gdetail g-{gid}" if hidden else "glrow"
        style = "display:none;cursor:pointer" if hidden else "cursor:pointer"
        entry_url = url_for('genledger.gl_entry', eid=l.entry_id)
        acc_cell = h(acc.name if acc else '—')
        if acc:
            acc_url = url_for('modules.module', mod='genledger') + f"?account={acc.id}&group=none"
            acc_cell = f"<a href='{h(acc_url)}' onclick='event.stopPropagation()' style='color:var(--petrol)'>{h(acc.name)}</a>"
        partner = _partner(l.entry)
        return (f"<tr class=\"{cls}\" style=\"{style}\" onclick=\"location.href='{entry_url}'\" title='Open journal entry'>"
                f"<td>{h(l.entry.date)}</td>"
                f"<td onclick='event.stopPropagation()'>{_ref_link(l.entry.ref, l.entry_id)}</td>"
                f"<td>{h(partner) if partner else '—'}</td>"
                f"<td>{h((l.entry.memo or '')[:60])}</td>"
                f"<td>{h(acc.code if acc else '')}</td><td>{acc_cell}</td>"
                f"<td class='num'>{money(l.debit) if l.debit else '—'}</td>"
                f"<td class='num'>{money(l.credit) if l.credit else '—'}</td>"
                f"<td class='num'>{money(run)}</td>"
                f"<td class='num'><span style='color:var(--muted)'>↗</span></td></tr>")

    def ghead(gid, label, count, gd, gc, cum, pill=''):
        return (f"<tr style='background:var(--canvas);cursor:pointer' onclick=\"glToggle('{gid}',this)\">"
                f"<td colspan='6'><span class='gcaret'>▸</span> <b>{label}</b> "
                f"<span style='color:var(--muted)'>({count})</span> {pill}</td>"
                f"<td class='num'><b>{money(gd)}</b></td><td class='num'><b>{money(gc)}</b></td>"
                f"<td class='num'><b>{money(gd - gc)}</b></td><td class='num'><b>{money(cum)}</b></td></tr>")

    body = ''
    grp = f['group']
    cum = 0
    from itertools import groupby
    if grp == 'account':
        keyed = sorted(view, key=lambda l: (l.account.code or '') if l.account else '')
        for gi, (acode, grp_lines) in enumerate(groupby(keyed, key=lambda l: (l.account.code or '') if l.account else '')):
            gl = list(grp_lines)
            a = gl[0].account
            gd = sum((x.debit or 0) for x in gl)
            gc = sum((x.credit or 0) for x in gl)
            cum += gd - gc
            pill = f"<span class='pill {TYPE_COLORS.get(a.type if a else '','grey')}'>{h(a.type if a else '')}</span>"
            body += ghead(gi, f"{h(a.code if a else '')} · {h(a.name if a else '—')}", len(gl), gd, gc, cum, pill)
            run = (a.opening or 0) if (a and not f['dfrom']) else 0
            for l in sorted(gl, key=lambda x: (x.entry.date or '', x.id)):
                run += (l.debit or 0) - (l.credit or 0)
                body += line_cells(l, run, gid=gi)
    elif grp == 'month':
        keyed = sorted(view, key=lambda l: (l.entry.date or '')[:7])
        for gi, (mon, grp_lines) in enumerate(groupby(keyed, key=lambda l: (l.entry.date or '')[:7])):
            gl = list(grp_lines)
            gd = sum((x.debit or 0) for x in gl)
            gc = sum((x.credit or 0) for x in gl)
            cum += gd - gc
            body += ghead(gi, h(mon or '—'), len(gl), gd, gc, cum)
            run = 0
            for l in gl:
                run += (l.debit or 0) - (l.credit or 0)
                body += line_cells(l, run, gid=gi)
    elif grp == 'type':
        keyed = sorted(view, key=lambda l: (l.account.type or '') if l.account else '')
        for gi, (typ, grp_lines) in enumerate(groupby(keyed, key=lambda l: (l.account.type or '') if l.account else '')):
            gl = list(grp_lines)
            gd = sum((x.debit or 0) for x in gl)
            gc = sum((x.credit or 0) for x in gl)
            cum += gd - gc
            body += ghead(gi, h(typ or '—'), len(gl), gd, gc, cum)
            run = 0
            for l in gl:
                run += (l.debit or 0) - (l.credit or 0)
                body += line_cells(l, run, gid=gi)
    else:
        run = opening
        if opening:
            body += (f"<tr style='background:var(--canvas)'><td>—</td><td><b>OPENING</b></td><td colspan='4'>Opening balance (Chart of Accounts)</td>"
                     f"<td class='num'>—</td><td class='num'>—</td><td class='num'>{money(opening)}</td><td></td></tr>")
        for l in view:
            run += (l.debit or 0) - (l.credit or 0)
            body += line_cells(l, run)

    # grand total footer — proves debits == credits (balance 0.00 when balanced)
    if body:
        body += (f"<tr style='background:var(--petrol);color:#fff'><td colspan='6'><b>TOTAL</b></td>"
                 f"<td class='num'><b>{money(tdeb)}</b></td><td class='num'><b>{money(tcred)}</b></td>"
                 f"<td class='num'><b>{money(tdeb - tcred)}</b></td><td class='num'><b>{money(cum if grp in ('account','type','month') else tdeb - tcred)}</b></td></tr>")

    if not body:
        body = "<tr><td colspan='10'><div class='empty'><b>No transactions</b>Adjust the filters or post journal entries.</div></td></tr>"

    # sortable headers
    def sh(label, key):
        d = 'desc' if (f['sort'] == key and f['direction'] == 'asc') else 'asc'
        args = {k: v for k, v in request.args.items() if k not in ('sort', 'dir', 'page')}
        args['sort'] = key
        args['dir'] = d
        arrow = ' ▲' if (f['sort'] == key and f['direction'] == 'asc') else (' ▼' if f['sort'] == key else '')
        return f"<th{' class=num' if key in ('debit','credit') else ''}><a href='{h(url_for('modules.module', mod='genledger', **args))}' style='color:inherit'>{h(label)}{arrow}</a></th>"

    summary = (f"<div class='pad' style='display:flex;gap:20px;flex-wrap:wrap;border-top:1px solid var(--line);font-size:14px'>"
               f"<div>Opening: <b>{money(opening)}</b></div>"
               f"<div>Total Debit: <b style='color:var(--green)'>{money(tdeb)}</b></div>"
               f"<div>Total Credit: <b style='color:var(--red)'>{money(tcred)}</b></div>"
               f"<div>Difference: <b>{money(tdeb - tcred)}</b></div>"
               + (f"<div style='color:var(--green)'>✓ balanced</div>" if abs(tdeb - tcred) < 0.5 else '')
               + f"<div style='margin-left:auto;color:var(--muted)'>{total:,} items · "
               + (f"<a href='#' onclick=\"glAll(true);return false\">expand all</a> · <a href='#' onclick=\"glAll(false);return false\">collapse all</a>" if grp in ('account', 'type', 'month') else '')
               + "</div></div>")

    js = ("<script>function glToggle(g,row){var rows=document.querySelectorAll('.g-'+g);var open=false;"
          "rows.forEach(function(r){var vis=r.style.display!=='none';r.style.display=vis?'none':'';open=!vis;});"
          "var c=row.querySelector('.gcaret');if(c)c.textContent=open?'▾':'▸';}"
          "function glAll(show){document.querySelectorAll('.gdetail').forEach(function(r){r.style.display=show?'':'none';});"
          "document.querySelectorAll('.gcaret').forEach(function(c){c.textContent=show?'▾':'▸';});}</script>"
          "<style>.glrow:hover{background:var(--green-soft)!important}.glrow td a:hover{text-decoration:underline}</style>")

    tbl = (f"<div class='panel'><div class='ph'><h2>General Ledger</h2>"
           f"<span class='so'>{h(f['dfrom'] or '…')} → {h(f['dto'] or '…')}</span></div>"
           + _gl_toolbar(f) + summary
           + f"<div class='tw'><table><thead><tr>{sh('Date','date')}<th>Journal Entry</th><th>Partner</th><th>Label</th>"
           f"{sh('Code','code')}<th>Account</th>{sh('Debit','debit')}{sh('Credit','credit')}<th class='num'>Balance</th><th class='num'>Cumulated</th></tr></thead>"
           f"<tbody>{body}</tbody></table></div>"
           + _pager(pg, pages, total) + js + "</div>")
    return page('General Ledger', _subnav('genledger') + tbl, 'genledger')


def _pager(pg, pages, total):
    if pages <= 1:
        return ''
    args = {k: v for k, v in request.args.items() if k != 'page'}
    def link(p, lbl):
        args['page'] = p
        return f"<a class='btn sm gh' href='{h(url_for('modules.module', mod='genledger', **args))}'>{lbl}</a>"
    prev = link(pg - 1, '← Prev') if pg > 1 else ''
    nxt = link(pg + 1, 'Next →') if pg < pages else ''
    return f"<div class='pad' style='display:flex;justify-content:space-between;align-items:center'><span style='color:var(--muted);font-size:13px'>Page {pg} / {pages}</span><span>{prev} {nxt}</span></div>"


# --------------------------------------------------------------- 3) Journal Items (flat)
def journal_items():
    # flat view = general ledger with no grouping
    if 'group' not in request.args:
        # force group=none by rebuilding args
        pass
    f = _args()
    f['group'] = 'none'
    lines, (tdeb, tcred), opening = _gl_rows(f)
    total = len(lines)
    per = 100
    pages = max(1, -(-total // per))
    pg = max(1, min(f['page'], pages))
    view = lines[(pg - 1) * per: pg * per]
    body = ''
    for l in view:
        acc = l.account
        entry_url = url_for('genledger.gl_entry', eid=l.entry_id)
        partner = _partner_name(l.entry)
        body += (f"<tr class='glrow' style='cursor:pointer' onclick=\"location.href='{entry_url}'\" title='Open journal entry'>"
                 f"<td>{h(l.entry.date)}</td><td onclick='event.stopPropagation()'>{_ref_link(l.entry.ref, l.entry_id)}</td>"
                 f"<td>{h(partner) if partner else '—'}</td>"
                 f"<td>{h(acc.code if acc else '')} · {h(acc.name if acc else '—')}</td>"
                 f"<td>{h((l.entry.memo or '')[:60])}</td>"
                 f"<td class='num'>{money(l.debit) if l.debit else '—'}</td>"
                 f"<td class='num'>{money(l.credit) if l.credit else '—'}</td></tr>")
    if not body:
        body = "<tr><td colspan='7'><div class='empty'><b>No journal items</b></div></td></tr>"
    summary = (f"<div class='pad' style='display:flex;gap:20px;border-top:1px solid var(--line)'>"
               f"<div>Total Debit: <b style='color:var(--green)'>{money(tdeb)}</b></div>"
               f"<div>Total Credit: <b style='color:var(--red)'>{money(tcred)}</b></div>"
               f"<div style='margin-left:auto;color:var(--muted)'>{total:,} items</div></div>")
    js = "<style>.glrow:hover{background:var(--green-soft)!important}</style>"
    tbl = (f"<div class='panel'><div class='ph'><h2>Journal Items</h2></div>"
           + _gl_toolbar(f, mod='jitems') + summary
           + f"<div class='tw'><table><thead><tr><th>Date</th><th>Journal Entry</th><th>Partner</th><th>Account</th><th>Label</th>"
           f"<th class='num'>Debit</th><th class='num'>Credit</th></tr></thead><tbody>{body}</tbody></table></div>"
           + _pager(pg, pages, total) + js + "</div>")
    return page('Journal Items', _subnav('jitems') + tbl, 'jitems')


# --------------------------------------------------------------- 4) Journal Entries (moves)
def journal_entries():
    f = _args()
    qy = JournalEntry.query
    if f['dfrom']:
        qy = qy.filter(JournalEntry.date >= f['dfrom'])
    if f['dto']:
        qy = qy.filter(JournalEntry.date <= f['dto'])
    if f['q']:
        like = f"%{f['q']}%"
        qy = qy.filter(db.or_(JournalEntry.ref.ilike(like), JournalEntry.memo.ilike(like)))
    entries = qy.order_by(JournalEntry.date.desc(), JournalEntry.id.desc()).limit(300).all()
    # GL integrity scan across ALL entries (not just the shown page)
    _sums = (db.session.query(JournalLine.entry_id,
                              db.func.coalesce(db.func.sum(JournalLine.debit), 0),
                              db.func.coalesce(db.func.sum(JournalLine.credit), 0))
             .group_by(JournalLine.entry_id).all())
    _unbal = {eid for eid, d, c in _sums if abs((d or 0) - (c or 0)) > 0.01}
    _total_entries = JournalEntry.query.count()
    if _unbal:
        _links = ' · '.join(f"<a href='{url_for('genledger.gl_entry', eid=i)}' style='color:#fff;text-decoration:underline'>#{i}</a>"
                            for i in sorted(_unbal)[:12])
        integrity = (f"<div class='panel' style='background:var(--red);color:#fff;margin-bottom:12px'>"
                     f"<div class='pad'><b>⚠ {len(_unbal)} of {_total_entries} journal entries are out of balance</b> "
                     f"(debits ≠ credits). Review &amp; fix: {_links}{' …' if len(_unbal) > 12 else ''}</div></div>")
    else:
        integrity = (f"<div class='panel' style='border-left:3px solid var(--green);margin-bottom:12px'>"
                     f"<div class='pad' style='color:var(--green);font-weight:600'>✓ All {_total_entries} journal entries balanced (debits = credits)</div></div>")
    body = ''
    for e in entries:
        d = sum((l.debit or 0) for l in e.lines)
        c = sum((l.credit or 0) for l in e.lines)
        if e.id in _unbal:
            st = "<span class='pill red'>⚠ Unbalanced</span>"
        elif e.is_reversal:
            st = "<span class='pill amber'>Reversal</span>"
        else:
            st = "<span class='pill green'>Posted</span>"
        body += (f"<tr><td>{h(e.date)}</td><td>{_ref_link(e.ref, e.id)}</td>"
                 f"<td>{h((e.memo or '')[:70])}</td><td class='num'>{money(d)}</td>"
                 f"<td class='num'>{money(c)}</td><td>{st}</td>"
                 f"<td class='num'><a class='btn gh sm' href='{url_for('genledger.gl_entry', eid=e.id)}'>Open</a></td></tr>")
    if not body:
        body = "<tr><td colspan='7'><div class='empty'><b>No journal entries</b></div></td></tr>"
    tbl = (f"<div class='panel'><div class='ph'><h2>Journal Entries</h2><span class='so'>{len(entries)} moves</span></div>"
           f"<div class='pad' style='border-bottom:1px solid var(--line)'>"
           f"<form method='get' class='listbar'>"
           f"<input name='q' value='{h(f['q'])}' placeholder='Move ref or description…' class='lb-input' autocomplete='off'>"
           f"<input type='date' name='from' value='{h(f['dfrom'])}' class='lb-input'>"
           f"<input type='date' name='to' value='{h(f['dto'])}' class='lb-input'>"
           f"<button class='btn sm'>Apply</button><a class='btn gh sm' href='{url_for('modules.module', mod='jentries')}'>Reset</a></form></div>"
           f"<div class='tw'><table><thead><tr><th>Date</th><th>Move</th><th>Description</th>"
           f"<th class='num'>Debit</th><th class='num'>Credit</th><th>Status</th><th></th></tr></thead><tbody>{body}</tbody></table></div></div>")
    return page('Journal Entries', _subnav('jentries') + integrity + tbl, 'jentries')


@bp.route('/gl/entry/<int:eid>')
@login_required
def gl_entry(eid):
    if not can('genledger'):
        from flask import abort
        abort(403)
    e = JournalEntry.query.get_or_404(eid)
    rows = ''
    td = tc = 0
    for l in e.lines:
        td += (l.debit or 0)
        tc += (l.credit or 0)
        acc = l.account
        if acc:
            acc_url = url_for('modules.module', mod='genledger') + f"?account={acc.id}&group=none"
            acc_cell = f"<a href='{h(acc_url)}' style='color:var(--petrol);font-weight:600'>{h(acc.name)}</a>"
            ledger_cell = f"<a class='btn gh sm' href='{h(acc_url)}' title='View account ledger'>Ledger →</a>"
            code = h(acc.code or '')
        else:
            acc_cell, ledger_cell, code = '—', '', ''
        rows += (f"<tr><td>{code}</td><td>{acc_cell}</td>"
                 f"<td class='num'>{money(l.debit) if l.debit else '—'}</td>"
                 f"<td class='num'>{money(l.credit) if l.credit else '—'}</td>"
                 f"<td class='num'>{ledger_cell}</td></tr>")

    # "Everything related" — source document, patient, receipt
    related = []
    ref = e.ref or ''
    inv = None
    try:
        from ..models import Invoice
        if ref.startswith(('INV-', 'PAY-', 'REV-INV-', 'REV-PAY-')):
            num = int(ref.replace('REV-', '').split('-')[1])
            inv = Invoice.query.get(num)
            if inv:
                related.append((f"🧾 Invoice INV-{inv.id:04d}", url_for('billing.invoice_view', iid=inv.id)))
        elif ref.startswith('RCT-'):
            num = int(ref.split('-')[1])
            related.append((f"💵 Receipt RCT-{num:05d}", f'/receipt/{num}'))
    except Exception:
        pass
    if inv is not None and inv.patient:
        try:
            related.append((f"👤 {inv.patient.name}", url_for('patients.patient_detail', pid=inv.patient_id)))
        except Exception:
            pass
    rel_html = ''
    if related:
        chips = ' '.join(f"<a class='btn sm' href='{h(u)}'>{h(lbl)}</a>" for lbl, u in related)
        rel_html = (f"<div class='pad' style='border-top:1px solid var(--line);display:flex;gap:8px;align-items:center;flex-wrap:wrap'>"
                    f"<span style='color:var(--muted);font-size:13px'>Related:</span>{chips}</div>")

    body = (f"<div class='panel'><div class='ph'><h2>{h(e.ref or ('JV-%04d' % e.id))}</h2>"
            f"<span class='so'>{h(e.date)}</span><div class='sp'></div>"
            f"<a class='btn sm' href='{url_for('modules.module', mod='jentries')}'>← Entries</a></div>"
            f"<div class='pad'><b>Description:</b> {h(e.memo or '—')}"
            + ("  <span class='pill amber'>Reversal</span>" if e.is_reversal else "  <span class='pill green'>Posted</span>")
            + f"</div>{rel_html}<div class='tw'><table><thead><tr><th>Code</th><th>Account</th>"
            f"<th class='num'>Debit</th><th class='num'>Credit</th><th></th></tr></thead><tbody>{rows}"
            f"<tr style='background:var(--canvas)'><td colspan='2'><b>Total</b></td>"
            f"<td class='num'><b>{money(td)}</b></td><td class='num'><b>{money(tc)}</b></td><td></td></tr>"
            f"</tbody></table></div></div>")
    log(f'Viewed journal entry {e.ref or e.id}', action_type='view', entity=f'JournalEntry#{e.id}')
    return page(e.ref or f'JV-{e.id}', _subnav('jentries') + body, 'jentries')


# --------------------------------------------------------------- 5) Trial Balance
def trial_balance():
    f = _args()
    accts = Account.query.filter_by(active=True).order_by(Account.code).all()
    rows = ''
    tot_open = tot_d = tot_c = tot_close = 0
    for a in accts:
        qy = db.session.query(
            db.func.coalesce(db.func.sum(JournalLine.debit), 0),
            db.func.coalesce(db.func.sum(JournalLine.credit), 0)).join(JournalEntry).filter(
            JournalLine.account_id == a.id)
        if f['dfrom']:
            qy = qy.filter(JournalEntry.date >= f['dfrom'])
        if f['dto']:
            qy = qy.filter(JournalEntry.date <= f['dto'])
        d, c = qy.one()
        d, c = d or 0, c or 0
        opening = a.opening or 0
        closing = opening + d - c
        if abs(d) < 0.005 and abs(c) < 0.005 and abs(opening) < 0.005:
            continue
        tot_open += opening
        tot_d += d
        tot_c += c
        tot_close += closing
        rows += (f"<tr><td>{h(a.code or '')}</td><td>{h(a.name)}</td>"
                 f"<td><span class='pill {TYPE_COLORS.get(a.type,'grey')}'>{h(a.type or '')}</span></td>"
                 f"<td class='num'>{money(opening)}</td><td class='num'>{money(d)}</td>"
                 f"<td class='num'>{money(c)}</td><td class='num'><b>{money(closing)}</b></td></tr>")
    if not rows:
        rows = "<tr><td colspan='7'><div class='empty'><b>No account activity</b></div></td></tr>"
    foot = (f"<tr style='background:var(--canvas)'><td colspan='3'><b>TOTAL</b></td>"
            f"<td class='num'><b>{money(tot_open)}</b></td><td class='num'><b>{money(tot_d)}</b></td>"
            f"<td class='num'><b>{money(tot_c)}</b></td><td class='num'><b>{money(tot_close)}</b></td></tr>")
    bal = '✓ balanced' if abs(tot_d - tot_c) < 0.5 else f'⚠ off by {money(abs(tot_d - tot_c))}'
    tbl = (f"<div class='panel'><div class='ph'><h2>Trial Balance</h2><span class='so'>{bal}</span><div class='sp'></div>"
           f"<a class='btn gh sm' href='{url_for('genledger.gl_print')}?tb=1&{_qs()}' data-pdf='{url_for('genledger.gl_pdf')}?tb=1&{_qs()}' target='_blank'>🖨 Print</a></div>"
           f"<div class='pad' style='border-bottom:1px solid var(--line)'><form method='get' class='listbar'>"
           f"<input type='date' name='from' value='{h(f['dfrom'])}' class='lb-input' title='From'>"
           f"<input type='date' name='to' value='{h(f['dto'])}' class='lb-input' title='To'>"
           f"<button class='btn sm'>Apply</button><a class='btn gh sm' href='{url_for('modules.module', mod='trialbal')}'>Reset</a></form></div>"
           f"<div class='tw'><table><thead><tr><th>Code</th><th>Account</th><th>Type</th>"
           f"<th class='num'>Opening</th><th class='num'>Debit</th><th class='num'>Credit</th><th class='num'>Closing</th></tr></thead>"
           f"<tbody>{rows}{foot}</tbody></table></div></div>")
    return page('Trial Balance', _subnav('trialbal') + tbl, 'trialbal')


# --------------------------------------------------------------- Account Balances (Odoo account list)
def account_balances():
    """A flat list of EVERY account with its current balance (Odoo-style)."""
    f = _args()
    nonzero = request.args.get('nonzero') == '1'
    grp_type = request.args.get('group', 'type') == 'type'   # group by type by default
    q = f['q']

    # one grouped query for debit/credit per account over the (optional) date range
    sq = (db.session.query(
        JournalLine.account_id,
        db.func.coalesce(db.func.sum(JournalLine.debit), 0),
        db.func.coalesce(db.func.sum(JournalLine.credit), 0))
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id))
    if f['dfrom']:
        sq = sq.filter(JournalEntry.date >= f['dfrom'])
    if f['dto']:
        sq = sq.filter(JournalEntry.date <= f['dto'])
    sums = {aid: (d or 0, c or 0) for aid, d, c in sq.group_by(JournalLine.account_id).all()}

    accts = Account.query.filter_by(active=True)
    if f['atype']:
        accts = accts.filter(Account.type == f['atype'])
    if q:
        like = f"%{q}%"
        accts = accts.filter(db.or_(Account.code.ilike(like), Account.name.ilike(like)))
    accts = accts.order_by(Account.type, Account.code).all()

    def bal_of(a):
        d, c = sums.get(a.id, (0, 0))
        return (a.opening or 0) + d - c, d, c

    # optionally drop zero-balance / no-activity accounts
    def has_activity(a):
        b, d, c = bal_of(a)
        return not (abs(b) < 0.005 and abs(d) < 0.005 and abs(c) < 0.005)

    shown = [a for a in accts if (has_activity(a) if nonzero else True)]

    def acct_row(a):
        b, d, c = bal_of(a)
        drill = url_for('modules.module', mod='genledger') + f'?account={a.id}&group=none'
        bcol = 'var(--green)' if b >= 0 else 'var(--red)'
        return (f"<tr><td><a href='{h(drill)}' style='color:var(--petrol);font-weight:600'>{h(a.code or '')}</a></td>"
                f"<td>{h(a.name)}</td>"
                f"<td><span class='pill {TYPE_COLORS.get(a.type,'grey')}'>{h(a.type or '')}</span></td>"
                f"<td class='num'>{money(d) if d else '—'}</td><td class='num'>{money(c) if c else '—'}</td>"
                f"<td class='num' style='color:{bcol};font-weight:700'>{money(b)}</td></tr>")

    rows = ''
    tot_d = tot_c = tot_b = 0
    if grp_type:
        from itertools import groupby
        for typ, grp in groupby(shown, key=lambda a: a.type or '—'):
            gl = list(grp)
            gd = sum(bal_of(a)[1] for a in gl)
            gc = sum(bal_of(a)[2] for a in gl)
            gb = sum(bal_of(a)[0] for a in gl)
            tot_d += gd
            tot_c += gc
            tot_b += gb
            rows += (f"<tr style='background:var(--canvas)'><td colspan='3'><b>{h(typ)}</b> "
                     f"<span style='color:var(--muted)'>({len(gl)})</span></td>"
                     f"<td class='num'><b>{money(gd)}</b></td><td class='num'><b>{money(gc)}</b></td>"
                     f"<td class='num'><b>{money(gb)}</b></td></tr>")
            for a in gl:
                rows += acct_row(a)
    else:
        for a in shown:
            b, d, c = bal_of(a)
            tot_d += d
            tot_c += c
            tot_b += b
            rows += acct_row(a)
    if not rows:
        rows = "<tr><td colspan='6'><div class='empty'><b>No accounts</b></div></td></tr>"
    foot = (f"<tr style='background:var(--petrol);color:#fff'><td colspan='3'><b>TOTAL</b></td>"
            f"<td class='num'><b>{money(tot_d)}</b></td><td class='num'><b>{money(tot_c)}</b></td>"
            f"<td class='num'><b>{money(tot_b)}</b></td></tr>")

    # toolbar
    topts = "<option value=''>All types</option>" + ''.join(
        f"<option value='{t}' {'selected' if t == f['atype'] else ''}>{t}</option>"
        for t in ['Asset', 'Liability', 'Equity', 'Income', 'Expense'])
    gsel = ("<label class='btn gh sm' style='cursor:pointer'>"
            f"<input type='checkbox' name='nonzero' value='1' {'checked' if nonzero else ''} "
            f"onchange='this.form.submit()' style='margin-right:4px'>Hide empty</label>")
    toolbar = (f"<div class='pad' style='border-bottom:1px solid var(--line)'><form method='get' class='listbar'>"
               f"<input name='q' value='{h(q)}' placeholder='Account code or name…' class='lb-input' "
               f"autocomplete='off' oninput=\"clearTimeout(window._abT);window._abT=setTimeout(()=>this.form.submit(),400)\">"
               f"<select name='type' class='lb-input'>{topts}</select>"
               f"<select name='group' class='lb-input'><option value='type' {'selected' if grp_type else ''}>Group by type</option>"
               f"<option value='none' {'selected' if not grp_type else ''}>No grouping</option></select>"
               f"<input type='date' name='from' value='{h(f['dfrom'])}' class='lb-input' title='From (optional)'>"
               f"<input type='date' name='to' value='{h(f['dto'])}' class='lb-input' title='To (optional)'>"
               f"{gsel}<button class='btn sm'>Apply</button>"
               f"<a class='btn gh sm' href='{url_for('modules.module', mod='acctbal')}'>Reset</a></form></div>")

    period = f"{f['dfrom']} → {f['dto']}" if (f['dfrom'] or f['dto']) else 'All time (current balances)'
    tbl = (f"<div class='panel'><div class='ph'><h2>Account Balances</h2>"
           f"<span class='so'>{h(period)} · {len(shown)} accounts</span></div>"
           + toolbar
           + f"<div class='tw'><table><thead><tr><th>Code</th><th>Account</th><th>Type</th>"
           f"<th class='num'>Debit</th><th class='num'>Credit</th><th class='num'>Balance</th></tr></thead>"
           f"<tbody>{rows}{foot}</tbody></table></div></div>")
    return page('Account Balances', _subnav('acctbal') + tbl, 'acctbal')


# --------------------------------------------------------------- Export / Print
@bp.route('/gl/export.csv')
@login_required
def gl_csv():
    if not can('genledger'):
        from flask import abort
        abort(403)
    f = _args()
    lines, _t, _o = _gl_rows(f)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Date', 'Journal Entry', 'Partner', 'Label', 'Account Code', 'Account Name', 'Debit', 'Credit'])
    for l in lines:
        acc = l.account
        w.writerow([l.entry.date, l.entry.ref or f'JV-{l.entry_id}', _partner_name(l.entry), (l.entry.memo or ''),
                    acc.code if acc else '', acc.name if acc else '', l.debit or 0, l.credit or 0])
    log('Exported General Ledger CSV', action_type='export', entity='GeneralLedger')
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment;filename=general-ledger-{today()}.csv'})


@bp.route('/gl/print.pdf')
@login_required
def gl_pdf():
    if not can('genledger'):
        from flask import abort
        abort(403)
    from ..core.pdfgen import ledger_pdf, available
    from ..core.security import setting
    from flask import redirect
    f = _args()
    if not available():
        return redirect(url_for('genledger.gl_print') + '?' + request.query_string.decode())
    company = setting('company', 'Modern Diagnostic Center'); currency = setting('currency', '$')
    dl = request.args.get('dl') == '1'
    if request.args.get('tb'):
        accts = Account.query.filter_by(active=True).order_by(Account.code).all()
        rows = []; td = tc = 0
        for a in accts:
            qy = db.session.query(
                db.func.coalesce(db.func.sum(JournalLine.debit), 0),
                db.func.coalesce(db.func.sum(JournalLine.credit), 0)).join(JournalEntry).filter(JournalLine.account_id == a.id)
            if f['dfrom']:
                qy = qy.filter(JournalEntry.date >= f['dfrom'])
            if f['dto']:
                qy = qy.filter(JournalEntry.date <= f['dto'])
            d, cc = qy.one(); d, cc = d or 0, cc or 0
            if abs(d) < 0.005 and abs(cc) < 0.005:
                continue
            td += d; tc += cc
            rows.append([a.code or '', a.name, money(d) if d else '', money(cc) if cc else ''])
        cols = [('Code', 'l', 24), ('Account', 'l', 96), ('Debit', 'r', 30), ('Credit', 'r', 30)]
        totals = ['TOTAL', '', money(td), money(tc)]
        title = 'Trial Balance'; fn = 'Trial-Balance'
    else:
        lines, (tdeb, tcred), opening = _gl_rows(f)
        run = opening; rows = []
        for l in lines[:3000]:
            run += (l.debit or 0) - (l.credit or 0)
            acc = l.account
            rows.append([l.entry.date, l.entry.ref or f'JV-{l.entry_id}', acc.code if acc else '',
                         acc.name if acc else '', money(l.debit) if l.debit else '',
                         money(l.credit) if l.credit else '', money(run)])
        cols = [('Date', 'l', 24), ('Move', 'l', 24), ('Code', 'l', 16), ('Account', 'l', 54),
                ('Debit', 'r', 26), ('Credit', 'r', 26), ('Balance', 'r', 28)]
        totals = ['TOTAL', '', '', '', money(tdeb), money(tcred), '']
        title = 'General Ledger'; fn = 'General-Ledger'
    period = f"Period: {f['dfrom'] or '...'} -> {f['dto'] or '...'}"
    pdf = ledger_pdf(title, period, cols, rows, totals, company=company, currency=currency)
    disp = ('attachment' if dl else 'inline') + f';filename={fn}-{today()}.pdf'
    log('General Ledger PDF', action_type='export', entity='GeneralLedger')
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


@bp.route('/gl/print')
@login_required
def gl_print():
    if not can('genledger'):
        from flask import abort
        abort(403)
    from ..core.printing import printable
    f = _args()
    if request.args.get('tb'):
        # trial balance print
        accts = Account.query.filter_by(active=True).order_by(Account.code).all()
        rows = ''
        td = tc = 0
        for a in accts:
            qy = db.session.query(
                db.func.coalesce(db.func.sum(JournalLine.debit), 0),
                db.func.coalesce(db.func.sum(JournalLine.credit), 0)).join(JournalEntry).filter(JournalLine.account_id == a.id)
            if f['dfrom']:
                qy = qy.filter(JournalEntry.date >= f['dfrom'])
            if f['dto']:
                qy = qy.filter(JournalEntry.date <= f['dto'])
            d, c = qy.one()
            d, c = d or 0, c or 0
            if abs(d) < 0.005 and abs(c) < 0.005:
                continue
            td += d
            tc += c
            rows += f"<tr><td>{h(a.code or '')}</td><td>{h(a.name)}</td><td style='text-align:right'>{money(d)}</td><td style='text-align:right'>{money(c)}</td></tr>"
        inner = (f"<table style='width:100%;border-collapse:collapse'><thead><tr style='border-bottom:2px solid #333'>"
                 f"<th style='text-align:left'>Code</th><th style='text-align:left'>Account</th>"
                 f"<th style='text-align:right'>Debit</th><th style='text-align:right'>Credit</th></tr></thead><tbody>{rows}"
                 f"<tr style='border-top:2px solid #333;font-weight:700'><td colspan='2'>TOTAL</td>"
                 f"<td style='text-align:right'>{money(td)}</td><td style='text-align:right'>{money(tc)}</td></tr></tbody></table>")
        return printable(f"Trial Balance · {f['dfrom'] or ''}–{f['dto'] or ''}", inner, doc_ref='TRIAL-BALANCE')
    # general ledger print
    lines, (tdeb, tcred), opening = _gl_rows(f)
    run = opening
    body = ''
    for l in lines[:2000]:
        run += (l.debit or 0) - (l.credit or 0)
        acc = l.account
        body += (f"<tr><td>{h(l.entry.date)}</td><td>{h(l.entry.ref or '')}</td>"
                 f"<td>{h(acc.code if acc else '')}</td><td>{h(acc.name if acc else '')}</td>"
                 f"<td style='text-align:right'>{money(l.debit) if l.debit else ''}</td>"
                 f"<td style='text-align:right'>{money(l.credit) if l.credit else ''}</td>"
                 f"<td style='text-align:right'>{money(run)}</td></tr>")
    inner = (f"<p><b>Period:</b> {h(f['dfrom'] or '…')} → {h(f['dto'] or '…')}</p>"
             f"<table style='width:100%;border-collapse:collapse;font-size:12px'><thead><tr style='border-bottom:2px solid #333'>"
             f"<th style='text-align:left'>Date</th><th style='text-align:left'>Move</th><th style='text-align:left'>Code</th>"
             f"<th style='text-align:left'>Account</th><th style='text-align:right'>Debit</th><th style='text-align:right'>Credit</th>"
             f"<th style='text-align:right'>Balance</th></tr></thead><tbody>{body}"
             f"<tr style='border-top:2px solid #333;font-weight:700'><td colspan='4'>TOTAL</td>"
             f"<td style='text-align:right'>{money(tdeb)}</td><td style='text-align:right'>{money(tcred)}</td>"
             f"<td style='text-align:right'>{money(opening + tdeb - tcred)}</td></tr></tbody></table>")
    return printable(f"General Ledger · {f['dfrom'] or ''}–{f['dto'] or ''}", inner, doc_ref='GENERAL-LEDGER')
