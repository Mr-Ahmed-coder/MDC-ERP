"""Odoo-style Expenses: create → Submit to Manager → Approve → Post Journal
Entries → Register Payment, with a statusbar and a PAID ribbon."""
import datetime as dt
from flask import Blueprint, request, redirect, url_for, flash, abort
from markupsafe import escape as h
from ..extensions import db
from ..models import Expense, Account
from ..core.security import cur_user, can, login_required, log, csrf_token
from ..core.ui import page
from ..core.helpers import money, today

bp = Blueprint('expenses', __name__)

_ACCOUNTS = ['600010 Expenses', '600050 Repairs & Maintenance', '6100 Salaries & Wages',
             '6200 Rent', '6300 Utilities', '6500 Other Operating Expenses']
_CATS = ['Maintenance', 'Rent', 'Utilities', 'Salaries', 'Marketing', 'Other']
_METHODS = ['Cash', 'Sahal', 'EVC', 'E. Dahab', 'MyCash', 'Premier Wallet', 'Bank', 'Card', 'Cheque']


def _can_mng():
    return can('expenses')


@bp.route('/expense/new', methods=['GET'])
@bp.route('/expense/<int:eid>/form', methods=['GET'])
@login_required
def expense_form(eid=None):
    """Odoo expense form: Description, Product, Unit Price, Quantity, Account,
    Employee, Paid By, with a statusbar."""
    if not can('expenses'):
        abort(403)
    e = Expense.query.get_or_404(eid) if eid else None
    st = (e.status if e else 'Draft')

    def _seg(label, active, done):
        cls = 'on' if active else ('done' if done else '')
        return f"<div class='po-step {cls}'>{label}</div>"
    order = ['Draft', 'Submitted', 'Approved', 'Posted', 'Paid']
    idx = order.index(st) if st in order else 0
    bar = ''.join(_seg(lbl, i == idx, i < idx) for i, lbl in
                  enumerate(['To Submit', 'Submitted', 'Approved', 'Posted', 'Paid']))

    cat_opts = ''.join(f"<option {'selected' if (e and e.category == c) else ''}>{c}</option>" for c in _CATS)
    acc_opts = ''.join(f"<option {'selected' if (e and e.account == a) else ''}>{a}</option>" for a in _ACCOUNTS)
    v = lambda x: h(x) if x else ''
    qty = (e.qty if e else 1) or 1
    unit = (e.unit_price if e else 0) or 0
    total = qty * unit
    paidby = (e.paid_by if e else 'Company')
    action = url_for('expenses.expense_save', eid=e.id) if e else url_for('expenses.expense_save')

    tb = []
    if not e or st == 'Draft':
        tb.append("<button form='expForm' class='btn primary'>💾 Save</button>")
    tb.append(f"<a class='btn gh' href='{url_for('modules.module', mod='expenses')}'>Discard</a>")

    css = """<style>
      .po-bar{display:flex;margin:12px 0 18px}
      .po-step{flex:1;text-align:center;padding:9px 6px;font-size:12px;font-weight:700;color:#8894a3;background:#EEF3F8;border-right:2px solid #fff}
      .po-step.on{background:var(--petrol);color:#fff}.po-step.done{background:#D7E5D7;color:#1F6B32}
      .ex-title{font-size:24px;font-weight:800;color:var(--ink);margin:2px 0 14px}
      .ex-cols{display:grid;grid-template-columns:1fr 1fr;gap:6px 40px}
      .po-f{display:flex;flex-direction:column;gap:3px;margin-bottom:10px}
      .po-f label{font-size:12.5px;color:var(--muted);font-weight:600}
      .po-f input,.po-f select,.po-f textarea{padding:8px 10px;border:1px solid var(--line);border-radius:7px;font-size:14px;width:100%}
      .ex-tot{margin-top:8px;font-size:15px}.ex-tot b{color:var(--petrol);font-size:18px}
    </style>
    <script>
    function exCalc(){
      var q=parseFloat(document.getElementById('exQty').value)||0;
      var u=parseFloat(document.getElementById('exUnit').value)||0;
      var t=q*u;
      var el=document.getElementById('exTotal'); if(el) el.textContent='$'+t.toFixed(2);
      var am=document.getElementById('exAmount'); if(am) am.value=t;
    }
    </script>"""

    body = f"""{css}
    <div class="panel"><div class="pad" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      {''.join(tb)}<div style="flex:1"></div>
      <span class="pill {'green' if st == 'Paid' else ('amber' if st in ('Submitted','Approved','Posted') else 'grey')}">{st}</span>
    </div>
    <div class="pad">
      <div class="po-bar">{bar}</div>
      <form id="expForm" method="post" action="{action}">
        <input type="hidden" name="_csrf" value="{csrf_token()}">
        <input type="hidden" id="exAmount" name="amount" value="{total:g}">
        <div class="po-f"><label>Description</label><input name="description" value="{v(e.description if e else '')}" placeholder="e.g. Samaynta Epsonkan Xafiiska" style="font-size:16px"></div>
        <div class="ex-cols">
          <div>
            <div class="po-f"><label>Product / Category</label><select name="category">{cat_opts}</select></div>
            <div class="po-f"><label>Unit Price</label><input id="exUnit" name="unit_price" type="number" step="any" value="{unit:g}" oninput="exCalc()"></div>
            <div class="po-f"><label>Quantity</label><input id="exQty" name="qty" type="number" step="any" value="{qty:g}" oninput="exCalc()"></div>
            <div class="ex-tot" style="margin:6px 0">Total: <b id="exTotal">${total:.2f}</b></div>
          </div>
          <div>
            <div class="po-f"><label>Expense Date</label><input type="date" name="date" value="{v(e.date if e else today())}"></div>
            <div class="po-f"><label>Account</label><select name="account">{acc_opts}</select></div>
            <div class="po-f"><label>Employee</label><input name="employee" value="{v(e.employee if e else (cur_user().name or cur_user().username if cur_user() else ''))}"></div>
            <div class="po-f"><label>Paid By</label>
              <select name="paid_by"><option {'selected' if paidby == 'Company' else ''}>Company</option><option {'selected' if paidby == 'Employee' else ''}>Employee</option></select></div>
          </div>
        </div>
        <div class="po-f"><label>Notes</label><textarea name="note" rows="2" placeholder="Notes…">{v(e.note if e else '')}</textarea></div>
      </form>
    </div></div>"""
    return page('Expense', body, 'expenses',
                crumbs=[('Expenses', url_for('modules.module', mod='expenses')),
                        (('EXP-%04d' % e.id) if e else 'New', None)])


@bp.route('/expense/save', methods=['POST'])
@bp.route('/expense/<int:eid>/save', methods=['POST'])
@login_required
def expense_save(eid=None):
    if not can('expenses'):
        abort(403)
    e = Expense.query.get_or_404(eid) if eid else Expense(status='Draft')
    f = request.form
    e.description = (f.get('description') or '').strip() or None
    e.category = f.get('category') or None
    e.account = f.get('account') or None
    e.employee = (f.get('employee') or '').strip() or None
    e.paid_by = f.get('paid_by') or 'Company'
    # Payment method is chosen at the Register Payment step (last stage), not here.
    if not eid:
        e.pay_method = 'Cash'
    e.date = f.get('date') or today()
    try: e.qty = float(f.get('qty') or 1)
    except ValueError: e.qty = 1
    try: e.unit_price = float(f.get('unit_price') or 0)
    except ValueError: e.unit_price = 0
    e.amount = e.qty * e.unit_price
    e.note = (f.get('note') or '').strip() or None
    if not eid:
        db.session.add(e)
    db.session.commit()
    log(f'Expense saved EXP-{e.id:04d}', entity=f'EXP-{e.id:04d}')
    flash(f'✔ Expense EXP-{e.id:04d} saved.')
    return redirect(url_for('expenses.expense_view', eid=e.id))


@bp.route('/expense/<int:eid>')
@login_required
def expense_view(eid):
    """Expense detail with the Odoo statusbar and stage actions."""
    if not can('expenses'):
        abort(403)
    e = Expense.query.get_or_404(eid)
    st = e.status or 'Draft'
    total = e.amount or 0
    paid = e.paid or 0
    bal = total - paid
    _paid_full = st == 'Paid' or (total > 0 and bal <= 0.005 and st == 'Posted')

    def _seg(label, active, done):
        cls = 'on' if active else ('done' if done else '')
        return f"<div class='po-step {cls}'>{label}</div>"
    order = ['Draft', 'Submitted', 'Approved', 'Posted', 'Paid']
    idx = order.index(st) if st in order else 0
    bar = ''.join(_seg(lbl, i == idx, i < idx) for i, lbl in
                  enumerate(['To Submit', 'Submitted', 'Approved', 'Posted', 'Paid']))

    btns = []
    if _can_mng():
        if st == 'Draft':
            btns.append(f"<a class='btn primary' href='{url_for('expenses.exp_submit', eid=e.id)}'>📤 Submit to Manager</a>")
            btns.append(f"<a class='btn gh' href='{url_for('expenses.expense_form', eid=e.id)}'>✎ Edit</a>")
        if st == 'Submitted':
            btns.append(f"<a class='btn primary' href='{url_for('expenses.exp_approve', eid=e.id)}'>✔ Approve</a>")
            btns.append(f"<a class='btn gh' href='{url_for('expenses.exp_refuse', eid=e.id)}'>✖ Refuse</a>")
        if st == 'Approved':
            btns.append(f"<a class='btn primary' href='{url_for('expenses.exp_post', eid=e.id)}'>📊 Post Journal Entries</a>")
        if st == 'Posted' and bal > 0.005:
            btns.append("<button class='btn ok' onclick=\"document.getElementById('expPayModal').style.display='flex'\">💵 Register Payment</button>")
    btns.append(f"<a class='btn gh' href='{url_for('modules.module', mod='expenses')}'>← Back</a>")

    ribbon = ("<div style='position:absolute;top:22px;right:-42px;transform:rotate(45deg);background:var(--green);"
              "color:#fff;padding:5px 52px;font-weight:800;font-size:13px;letter-spacing:1px'>PAID</div>") if _paid_full else ''

    pm_opts = ''.join(f"<option>{m}</option>" for m in _METHODS)
    pay_modal = f"""
    <div id="expPayModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:60;align-items:center;justify-content:center">
      <div style="background:#fff;border-radius:12px;max-width:420px;width:92%;padding:20px">
        <div style="font-weight:700;font-size:16px;color:var(--petrol);margin-bottom:4px">Register Payment · EXP-{e.id:04d}</div>
        <div style="color:var(--muted);font-size:12.5px;margin-bottom:14px">Balance {money(bal)}</div>
        <form method="post" action="{url_for('expenses.exp_pay', eid=e.id)}">
          <input type="hidden" name="_csrf" value="{csrf_token()}">
          <label style="font-size:12px;font-weight:700;color:var(--muted)">Amount</label>
          <input name="amount" type="number" step="any" min="0" value="{bal:g}" style="width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:8px;margin:4px 0 12px">
          <label style="font-size:12px;font-weight:700;color:var(--muted)">Payment Method</label>
          <select name="method" style="width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:8px;margin:4px 0 16px">{pm_opts}</select>
          <div style="display:flex;gap:8px;justify-content:flex-end">
            <button type="button" class="btn gh" onclick="document.getElementById('expPayModal').style.display='none'">Cancel</button>
            <button class="btn ok">Confirm Payment</button>
          </div>
        </form>
      </div>
    </div>"""

    css = """<style>
      .po-bar{display:flex;margin:12px 0 18px}
      .po-step{flex:1;text-align:center;padding:9px 6px;font-size:12px;font-weight:700;color:#8894a3;background:#EEF3F8;border-right:2px solid #fff}
      .po-step.on{background:var(--petrol);color:#fff}.po-step.done{background:#D7E5D7;color:#1F6B32}
      .ex-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 24px;margin-top:8px}
      .ex-grid .k{color:var(--muted);font-size:12.5px}.ex-grid .v{font-weight:600}
      .ex-tot .r{display:flex;justify-content:space-between;padding:4px 0}
      .ex-tot .r.big{font-size:18px;font-weight:800;color:var(--petrol);border-top:1px solid var(--line);padding-top:8px;margin-top:4px}
    </style>"""
    body = f"""{css}
    <div class="panel" style="position:relative;overflow:hidden">{ribbon}
      <div class="pad" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <div style="font-weight:800;font-size:18px;color:var(--petrol)">EXP-{e.id:04d}</div>
        <span class="pill {'green' if _paid_full else ('amber' if st in ('Submitted','Approved','Posted') else 'grey')}">{st}</span>
        <div style="flex:1"></div>{''.join(btns)}
      </div>
      <div class="pad">
        <div class="po-bar">{bar}</div>
        <div style="font-weight:800;font-size:20px;color:var(--ink);margin-bottom:6px">{h(e.description or e.category or '—')}</div>
        <div class="ex-grid">
          <div><div class="k">Product / Category</div><div class="v">{h(e.category or '—')}</div></div>
          <div><div class="k">Expense Date</div><div class="v">{h(e.date or '—')}</div></div>
          <div><div class="k">Account</div><div class="v">{h(e.account or '—')}</div></div>
          <div><div class="k">Employee</div><div class="v">{h(e.employee or '—')}</div></div>
          <div><div class="k">Paid By</div><div class="v">{h(e.paid_by or 'Company')}</div></div>
          <div><div class="k">Payment Method</div><div class="v">{h(e.pay_method) if (e.paid or 0) > 0 else '— (set at payment)'}</div></div>
          <div><div class="k">Quantity</div><div class="v">{(e.qty or 1):g}</div></div>
          <div><div class="k">Unit Price</div><div class="v">{money(e.unit_price or 0)}</div></div>
        </div>
        <div class="ex-tot" style="max-width:300px;margin-left:auto;margin-top:14px">
          <div class="r big"><span>Total</span><span>{money(total)}</span></div>
          <div class="r"><span>Paid</span><span>{money(paid)}</span></div>
          <div class="r"><span><b>Amount Due</b></span><span><b>{money(bal)}</b></span></div>
        </div>
      </div>
    </div>{pay_modal}"""
    return page(f'Expense EXP-{e.id:04d}', body, 'expenses',
                crumbs=[('Expenses', url_for('modules.module', mod='expenses')), (f'EXP-{e.id:04d}', None)])


def _set_status(eid, new_status, msg):
    e = Expense.query.get_or_404(eid)
    e.status = new_status
    db.session.commit()
    log(f'Expense EXP-{eid:04d} → {new_status}', action_type='Edit', entity=f'EXP-{eid:04d}')
    flash(msg)
    return redirect(url_for('expenses.expense_view', eid=eid))


@bp.route('/expense/<int:eid>/submit')
@login_required
def exp_submit(eid):
    if not can('expenses'): abort(403)
    return _set_status(eid, 'Submitted', '📤 Submitted to manager.')


@bp.route('/expense/<int:eid>/approve')
@login_required
def exp_approve(eid):
    if not can('expenses'): abort(403)
    return _set_status(eid, 'Approved', '✔ Expense approved.')


@bp.route('/expense/<int:eid>/refuse')
@login_required
def exp_refuse(eid):
    if not can('expenses'): abort(403)
    return _set_status(eid, 'Draft', 'Expense refused — back to draft.')


@bp.route('/expense/<int:eid>/post')
@login_required
def exp_post(eid):
    if not can('expenses'): abort(403)
    e = Expense.query.get_or_404(eid)
    if e.status != 'Approved':
        flash('Only an approved expense can be posted.')
        return redirect(url_for('expenses.expense_view', eid=eid))
    from ..core.posting import _period_open
    if e.date and not _period_open(e.date):
        flash(f'Period closed: cannot post to {e.date[:7]}. Reopen it in Accounting → Fiscal Periods.')
        return redirect(url_for('expenses.expense_view', eid=eid))
    e.status = 'Posted'
    db.session.commit()
    try:
        from ..core.posting import post_expense
        post_expense(e)   # Dr Expense / Cr Accounts Payable
    except Exception:
        db.session.rollback()
        from ..core.helpers import log_error; log_error(f'post expense EXP-{eid:04d}')
    log(f'Expense EXP-{eid:04d} journal posted', action_type='Edit', entity=f'EXP-{eid:04d}')
    flash('📊 Journal entries posted. Register the payment to settle it.')
    return redirect(url_for('expenses.expense_view', eid=eid))


@bp.route('/expense/<int:eid>/pay', methods=['POST'])
@login_required
def exp_pay(eid):
    if not can('expenses'): abort(403)
    e = Expense.query.get_or_404(eid)
    if e.status not in ('Posted', 'Paid'):
        flash('Post the journal entries before registering a payment.')
        return redirect(url_for('expenses.expense_view', eid=eid))
    try:
        amt = float(request.form.get('amount') or 0)
    except ValueError:
        amt = 0
    method = request.form.get('method') or 'Cash'
    bal = (e.amount or 0) - (e.paid or 0)
    if amt <= 0:
        flash('Enter a payment amount'); return redirect(url_for('expenses.expense_view', eid=eid))
    if amt > bal + 0.005:
        amt = bal
    e.paid = (e.paid or 0) + amt
    e.pay_method = method
    if (e.amount or 0) - (e.paid or 0) <= 0.005:
        e.status = 'Paid'
    db.session.commit()
    try:
        from ..core.posting import repost_expense_payment
        repost_expense_payment(e)   # Dr AP / Cr cash-or-wallet
    except Exception:
        db.session.rollback()
        from ..core.helpers import log_error; log_error(f'exp_pay EXP-{eid:04d}')
    log(f'Expense EXP-{eid:04d} payment {money(amt)} via {method}',
        action_type='Payment', entity=f'EXP-{eid:04d}')
    _bal = (e.amount or 0) - (e.paid or 0)
    flash(f'✓ Paid {money(amt)} via {method}. ' + ('Fully paid.' if _bal <= 0.005 else f'Balance {money(_bal)}.'))
    return redirect(url_for('expenses.expense_view', eid=eid))
