"""Accounting Dashboard (Odoo Community 18-style)  (v8.0).

A modern accounting overview: cash/bank/AR/AP cards, monthly revenue/expenses/
net profit, a P&L summary, outstanding & overdue invoices, recent payments and
journal entries — with a branch selector, date-range filter, PDF + Excel export,
optional live refresh, dark/light and a responsive card grid.

Reuses the existing balance and posting helpers so every figure ties to the rest
of the system (cash 1101 / bank 1102, live-invoice receivable, purchase payable,
Income/Expense journal totals).
"""
import datetime as dt
from flask import Blueprint, request, url_for
from markupsafe import escape as h
from ..extensions import db
from ..models import Account, JournalEntry, JournalLine, Invoice, Purchase, PayReceipt, Branch
from ..core.security import can, log, login_required, branch_scope
from ..core.helpers import money, today
from ..core.ui import page
from ..core.posting import live_invoices, acc

bp = Blueprint('acctdash', __name__)


# --------------------------------------------------------------- helpers
def _month_bounds():
    t = dt.date.today()
    s = t.replace(day=1)
    return s.isoformat(), t.isoformat()


def _args():
    a = request.args
    mf, mt = _month_bounds()
    return dict(dfrom=a.get('from') or mf, dto=a.get('to') or mt,
                branch=a.get('branch', ''))


def _bal(code):
    from .accounting import acct_balance
    a = acc(code)
    return acct_balance(a) if a else 0


def _cash_bank():
    cash = _bal('1101')
    bank = _bal('1102')
    # fall back to name-matching if the standard codes aren't set up
    if not acc('1101') or not acc('1102'):
        from .accounting import acct_balance
        for a in Account.query.filter(Account.type == 'Asset').all():
            nm = (a.name or '').lower()
            if not acc('1101') and 'cash' in nm:
                cash += acct_balance(a)
            if not acc('1102') and 'bank' in nm:
                bank += acct_balance(a)
    return cash, bank


def _invoice_scope(q):
    """Apply branch selection to an Invoice query (Invoice has branch_id)."""
    f = _args()
    if f['branch']:
        q = q.filter(Invoice.branch_id == int(f['branch']))
    return branch_scope(q, Invoice)


def _receivable():
    invs = _invoice_scope(Invoice.query).all()
    live = set(i.id for i in live_invoices())
    return sum((i.total - (i.paid or 0)) for i in invs if i.id in live and (i.total - (i.paid or 0)) > 0.005)


def _payable():
    return sum((p.total or 0) - (p.paid or 0) for p in Purchase.query.all())


def _rev_exp(dfrom, dto):
    """Revenue and expenses from the journals over a date range."""
    def by_type(t):
        rows = (db.session.query(
            db.func.coalesce(db.func.sum(JournalLine.debit), 0),
            db.func.coalesce(db.func.sum(JournalLine.credit), 0))
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .join(Account, JournalLine.account_id == Account.id)
            .filter(Account.type == t, JournalEntry.date >= dfrom, JournalEntry.date <= dto).one())
        return (rows[0] or 0, rows[1] or 0)
    dinc, cinc = by_type('Income')
    dexp, cexp = by_type('Expense')
    revenue = cinc - dinc          # income is credit-normal
    expenses = dexp - cexp         # expense is debit-normal
    return revenue, expenses


def _overdue_days():
    return 30


# --------------------------------------------------------------- dashboard
def acct_dashboard():
    f = _args()
    cash, bank = _cash_bank()
    ar = _receivable()
    ap = _payable()
    revenue, expenses = _rev_exp(f['dfrom'], f['dto'])
    net = revenue - expenses

    branches = Branch.query.order_by(Branch.name).all()
    bsel = "<select name='branch' class='lb-input' onchange='this.form.submit()'>"
    bsel += f"<option value=''>All branches</option>"
    for b in branches:
        bsel += f"<option value='{b.id}' {'selected' if str(b.id) == f['branch'] else ''}>{h(b.name)}</option>"
    bsel += "</select>"

    controls = (f"<form method='get' class='listbar' style='gap:8px'>"
                f"{bsel}"
                f"<input type='date' name='from' value='{h(f['dfrom'])}' class='lb-input' title='From'>"
                f"<input type='date' name='to' value='{h(f['dto'])}' class='lb-input' title='To'>"
                f"<button class='btn sm'>Apply</button>"
                f"<a class='btn gh sm' href='{url_for('acctdash.dash_xlsx')}?{_qs()}'>⭳ Excel</a>"
                f"<a class='btn gh sm' href='{url_for('acctdash.dash_print')}?{_qs()}' target='_blank'>🖨 PDF</a>"
                f"<label class='btn gh sm' style='cursor:pointer'><input type='checkbox' id='livechk' style='margin-right:4px'>Live</label>"
                f"</form>")

    # --- cards ---
    def card(label, val, icon, ac, sub='', link=''):
        inner = (f"<div class='ad-card' style='--ac:{ac}'>"
                 f"<div class='ad-ic'>{icon}</div>"
                 f"<div class='ad-l'>{h(label)}</div>"
                 f"<div class='ad-v'>{val}</div>"
                 f"<div class='ad-s'>{h(sub)}</div></div>")
        return f"<a href='{link}' style='text-decoration:none;color:inherit'>{inner}</a>" if link else inner

    cards = ("<div class='ad-grid'>"
             + card('Cash Balance', money(cash), '💵', 'var(--green)', 'Account 1101', url_for('modules.module', mod='genledger') + '?q=1101')
             + card('Bank Balance', money(bank), '🏦', 'var(--teal)', 'Account 1102', url_for('modules.module', mod='genledger') + '?q=1102')
             + card('Accounts Receivable', money(ar), '📥', 'var(--amber)', 'Unpaid invoices', url_for('modules.module', mod='araging'))
             + card('Accounts Payable', money(ap), '📤', 'var(--red)', 'Supplier bills', url_for('modules.module', mod='apaging'))
             + "</div>")

    pnl_cards = ("<div class='ad-grid'>"
                 + card('Monthly Revenue', money(revenue), '📈', 'var(--green)', f"{f['dfrom']} → {f['dto']}")
                 + card('Monthly Expenses', money(expenses), '📉', 'var(--red)', 'Period expenses')
                 + card('Net Profit', money(net), '🧮', 'var(--petrol)' if net >= 0 else 'var(--red)', 'Revenue − Expenses')
                 + "</div>")

    # --- P&L summary panel ---
    pnl = (f"<div class='panel'><div class='ph'><h2>Profit &amp; Loss Summary</h2>"
           f"<span class='so'>{h(f['dfrom'])} → {h(f['dto'])}</span></div>"
           f"<div class='pad'>"
           f"<div style='display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line)'><span>Revenue</span><b style='color:var(--green)'>{money(revenue)}</b></div>"
           f"<div style='display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line)'><span>Expenses</span><b style='color:var(--red)'>({money(expenses)})</b></div>"
           f"<div style='display:flex;justify-content:space-between;padding:8px 0;font-size:16px'><span><b>Net Profit</b></span><b style='color:{'var(--green)' if net>=0 else 'var(--red)'}'>{money(net)}</b></div>"
           f"</div></div>")

    # --- outstanding & overdue invoices ---
    live_ids = set(i.id for i in live_invoices())
    outstanding = [i for i in _invoice_scope(Invoice.query).order_by(Invoice.id.desc()).all()
                   if i.id in live_ids and (i.total - (i.paid or 0)) > 0.005]
    cutoff = (dt.date.today() - dt.timedelta(days=_overdue_days())).isoformat()

    def inv_rows(items, overdue=False):
        out = ''
        for i in items[:12]:
            bal = i.total - (i.paid or 0)
            who = h(i.patient.name if i.patient else (i.guarantor or 'Walk-in'))
            age = ''
            if overdue:
                age = f"<td>{h(i.date)}</td>"
            out += (f"<tr><td><a href='{url_for('billing.invoice_view', iid=i.id)}' style='color:var(--petrol);font-weight:600'>INV-{i.id:04d}</a></td>"
                    f"<td>{who}</td>{age}<td class='num'>{money(i.total)}</td><td class='num'>{money(i.paid or 0)}</td>"
                    f"<td class='num'><b>{money(bal)}</b></td></tr>")
        return out or f"<tr><td colspan='{6 if overdue else 5}' style='color:var(--muted)'>None</td></tr>"

    overdue = [i for i in outstanding if (i.date or '9999') < cutoff]
    out_panel = (f"<div class='panel'><div class='ph'><h2>Outstanding Invoices</h2><span class='so'>{len(outstanding)} unpaid</span></div>"
                 f"<div class='tw'><table><thead><tr><th>Invoice</th><th>Partner</th><th class='num'>Total</th><th class='num'>Paid</th><th class='num'>Balance</th></tr></thead>"
                 f"<tbody>{inv_rows(outstanding)}</tbody></table></div></div>")
    over_panel = (f"<div class='panel'><div class='ph'><h2>Overdue Invoices</h2><span class='so'>&gt; {_overdue_days()} days · {len(overdue)}</span></div>"
                  f"<div class='tw'><table><thead><tr><th>Invoice</th><th>Partner</th><th>Date</th><th class='num'>Total</th><th class='num'>Paid</th><th class='num'>Balance</th></tr></thead>"
                  f"<tbody>{inv_rows(overdue, overdue=True)}</tbody></table></div></div>")

    # --- recent payments ---
    pq = PayReceipt.query
    if f['branch']:
        pq = pq.join(Invoice, PayReceipt.invoice_id == Invoice.id).filter(Invoice.branch_id == int(f['branch']))
    pays = pq.order_by(PayReceipt.id.desc()).limit(10).all()
    prows = ''.join(
        f"<tr><td>{h(p.date)}</td><td><a href='/receipt/{p.id}' style='color:var(--petrol)'>RCT-{p.id:05d}</a></td>"
        f"<td>INV-{p.invoice_id:04d}</td><td>{h(p.method or '')}</td><td class='num'><b>{money(p.amount)}</b></td></tr>"
        for p in pays) or "<tr><td colspan='5' style='color:var(--muted)'>No payments</td></tr>"
    pay_panel = (f"<div class='panel'><div class='ph'><h2>Recent Payments</h2></div>"
                 f"<div class='tw'><table><thead><tr><th>Date</th><th>Receipt</th><th>Invoice</th><th>Method</th><th class='num'>Amount</th></tr></thead>"
                 f"<tbody>{prows}</tbody></table></div></div>")

    # --- recent journal entries ---
    jes = JournalEntry.query.order_by(JournalEntry.id.desc()).limit(10).all()
    jrows = ''
    for e in jes:
        amt = sum((l.debit or 0) for l in e.lines)
        ref = e.ref or f'JV-{e.id:04d}'
        jrows += (f"<tr><td>{h(e.date)}</td><td><a href='{url_for('genledger.gl_entry', eid=e.id)}' style='color:var(--petrol)'>{h(ref)}</a></td>"
                  f"<td>{h((e.memo or '')[:48])}</td><td class='num'>{money(amt)}</td></tr>")
    jrows = jrows or "<tr><td colspan='4' style='color:var(--muted)'>No entries</td></tr>"
    je_panel = (f"<div class='panel'><div class='ph'><h2>Recent Journal Entries</h2><div class='sp'></div>"
                f"<a class='btn sm' href='{url_for('modules.module', mod='jentries')}'>All →</a></div>"
                f"<div class='tw'><table><thead><tr><th>Date</th><th>Move</th><th>Description</th><th class='num'>Amount</th></tr></thead>"
                f"<tbody>{jrows}</tbody></table></div></div>")

    css = """<style>
    .ad-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin-bottom:16px}
    .ad-card{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--ac);border-radius:12px;
      padding:16px 18px;box-shadow:var(--shadow)}
    .ad-ic{font-size:22px}.ad-l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-top:6px}
    .ad-v{font-size:26px;font-weight:700;margin:2px 0}.ad-s{font-size:12px;color:var(--muted)}
    .ad-two{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:860px){.ad-two{grid-template-columns:1fr}}
    </style>"""

    header = (f"<div class='panel' style='margin-bottom:16px'><div class='ph'><h2>Accounting Dashboard</h2>"
              f"<span class='so'>Modern Diagnostic Center</span><div class='sp'></div>{controls}</div></div>")

    body = (css + header + cards + pnl_cards
            + "<div class='ad-two'>" + pnl + je_panel + "</div>"
            + "<div style='height:16px'></div>"
            + "<div class='ad-two'>" + out_panel + over_panel + "</div>"
            + "<div style='height:16px'></div>"
            + pay_panel
            + """<script>
            (function(){var t;var c=document.getElementById('livechk');
              if(c){c.addEventListener('change',function(){
                if(c.checked){t=setInterval(function(){var u=new URL(location.href);u.searchParams.set('_r',Date.now());location.replace(u.toString());},30000);}
                else{clearInterval(t);}});}})();
            </script>""")
    log('Viewed accounting dashboard', action_type='view', entity='Accounting')
    return page('Accounting Dashboard', body, 'acctdash')


def _qs():
    return '&'.join(f"{k}={h(v)}" for k, v in request.args.items() if k != '_r')


# --------------------------------------------------------------- exports
@bp.route('/acctdash/export.xlsx')
@login_required
def dash_xlsx():
    if not can('acctdash'):
        from flask import abort
        abort(403)
    from .finexport import _wb, _sheet, _send_wb
    f = _args()
    cash, bank = _cash_bank()
    ar, ap = _receivable(), _payable()
    revenue, expenses = _rev_exp(f['dfrom'], f['dto'])
    wb, hf, hfill, _al = _wb()
    ws = wb.active
    _sheet(ws, 'Summary',
           ['Metric', 'Value'],
           [['Period', f"{f['dfrom']} → {f['dto']}"],
            ['Cash Balance', cash], ['Bank Balance', bank],
            ['Accounts Receivable', ar], ['Accounts Payable', ap],
            ['Monthly Revenue', revenue], ['Monthly Expenses', expenses],
            ['Net Profit', revenue - expenses]],
           hf, hfill, money_cols=(2,))
    # outstanding invoices
    live_ids = set(i.id for i in live_invoices())
    outs = [i for i in _invoice_scope(Invoice.query).order_by(Invoice.id.desc()).all()
            if i.id in live_ids and (i.total - (i.paid or 0)) > 0.005]
    _sheet(wb.create_sheet(), 'Outstanding',
           ['Invoice', 'Partner', 'Date', 'Total', 'Paid', 'Balance'],
           [[f'INV-{i.id:04d}', (i.patient.name if i.patient else (i.guarantor or 'Walk-in')),
             i.date, i.total, i.paid or 0, i.total - (i.paid or 0)] for i in outs],
           hf, hfill, money_cols=(4, 5, 6))
    # recent payments
    pays = PayReceipt.query.order_by(PayReceipt.id.desc()).limit(50).all()
    _sheet(wb.create_sheet(), 'Payments',
           ['Date', 'Receipt', 'Invoice', 'Method', 'Amount'],
           [[p.date, f'RCT-{p.id:05d}', f'INV-{p.invoice_id:04d}', p.method or '', p.amount] for p in pays],
           hf, hfill, money_cols=(5,))
    log('Exported accounting dashboard (Excel)', action_type='export', entity='Accounting')
    return _send_wb(wb, f'accounting-dashboard-{today()}.xlsx')


@bp.route('/acctdash/print')
@login_required
def dash_print():
    if not can('acctdash'):
        from flask import abort
        abort(403)
    from ..core.printing import printable
    f = _args()
    cash, bank = _cash_bank()
    ar, ap = _receivable(), _payable()
    revenue, expenses = _rev_exp(f['dfrom'], f['dto'])
    net = revenue - expenses

    def row(k, v):
        return f"<tr><td>{h(k)}</td><td style='text-align:right'>{v}</td></tr>"
    inner = (f"<p><b>Period:</b> {h(f['dfrom'])} → {h(f['dto'])}</p>"
             f"<table style='width:100%;border-collapse:collapse'>"
             f"<tr style='border-bottom:2px solid #333'><th style='text-align:left'>Metric</th><th style='text-align:right'>Value</th></tr>"
             + row('Cash Balance', money(cash)) + row('Bank Balance', money(bank))
             + row('Accounts Receivable', money(ar)) + row('Accounts Payable', money(ap))
             + row('Monthly Revenue', money(revenue)) + row('Monthly Expenses', money(expenses))
             + f"<tr style='border-top:2px solid #333;font-weight:700'><td>Net Profit</td><td style='text-align:right'>{money(net)}</td></tr>"
             + "</table>")
    return printable(f"Accounting Dashboard · {f['dfrom']}–{f['dto']}", inner, doc_ref='ACCT-DASHBOARD')
