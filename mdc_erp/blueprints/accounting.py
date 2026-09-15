"""Accounting: journal, ledger, chart of accounts, financial statements."""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.security import (can, login_required, log, cur_user,
                             setting, csrf_token)
from ..core.helpers import money, today, cur_year, money_round
from ..core.ui import page, plink, pnamelink
from ..core.crud import (pill)
from ..core.posting import (live_invoices,
                            acc, _period_open)

bp = Blueprint('acct', __name__)

def _ref_to_invoice(ref):
    """If a journal ref points at an invoice/payment/credit note, return its invoice id."""
    if not ref:
        return None
    import re as _re
    m = _re.match(r'(?:INV|PAY|CN)-(\d+)', ref)
    return int(m.group(1)) if m else None


def journal_list():
    from flask import render_template
    entries=JournalEntry.query.order_by(JournalEntry.date.desc(),JournalEntry.id.desc()).all()
    rows=[]
    for e in entries:
        ok=abs(e.total_debit-e.total_credit)<0.005
        if e.is_reversal: badge="<span class='pill grey'>Reversal</span>"
        elif e.reversed_by: badge="<span class='pill amber'>Reversed</span>"
        else: badge=f"<span class='pill {'green' if ok else 'red'}'>{'Balanced' if ok else 'Off'}</span>"
        act=''
        if not e.is_reversal and not e.reversed_by and _period_open(e.date):
            act=f"<a class='btn gh sm' href='{url_for('acct.journal_reverse',eid=e.id)}' onclick=\"var r=prompt('Reason for reversing this entry?'); if(!r)return false; this.href=this.href.split('?')[0]+'?reason='+encodeURIComponent(r); return true;\">↺ Reverse</a>"
        iid=_ref_to_invoice(e.ref)
        src=f" <a class='btn gh sm' href='{url_for('billing.invoice_view',iid=iid)}' title='Open source invoice'>🧾 Invoice</a>" if iid else ''
        rows.append([
            h(e.date),
            f"<a href='{url_for('acct.journal_entry',eid=e.id)}' style='color:var(--petrol);font-weight:700'>{h(e.ref or ('JV-%04d'%e.id))}</a>",
            h(e.memo or '—'),
            money(e.total_debit),
            money(e.total_credit),
            badge,
            f"{act}{src}",
        ])
    toolbar=(f"<a class='btn' href='{url_for('modules.module',mod='recurjournals')}'>Recurring</a> "
             f"<a class='btn' href='{url_for('acct.journal_transfer')}'>⇄ Transfer</a> "
             f"<a class='btn primary' href='{url_for('acct.journal_new')}'>+ New Entry</a>")
    body=render_template('list_page.html', title='Journal Entries', toolbar=toolbar,
                         headers=['Date','Ref','Memo','Debit','Credit','Status',''],
                         aligns=['','','','num','num','','num'], rows=rows,
                         empty="<div class='empty'><b>No journal entries</b>Record your first double-entry transaction.</div>")
    return page('Journal Entries', body, 'journal')

@bp.route('/journal/new', methods=['GET','POST'])
@login_required
def journal_new():
    if not can('journal'): abort(403)
    accts=Account.query.order_by(Account.code).all()
    if request.method=='POST':
        _jd=request.form.get('date') or today()
        if not _period_open(_jd):
            flash(f'Period closed: cannot post to {_jd[:7]}. Reopen it in Fiscal Periods.')
            return redirect(url_for('acct.journal_new'))
        e=JournalEntry(date=_jd, ref=request.form.get('ref'), memo=request.form.get('memo'))
        db.session.add(e); db.session.commit(); td=tc=0
        for i in range(1,9):
            aid=request.form.get(f'acct{i}')
            if not aid: continue
            d=float(request.form.get(f'debit{i}') or 0); c=float(request.form.get(f'credit{i}') or 0)
            if d==0 and c==0: continue
            db.session.add(JournalLine(entry_id=e.id,account_id=int(aid),debit=d,credit=c)); td+=d; tc+=c
        db.session.commit(); log(f'Journal entry #{e.id}')
        flash('Journal entry saved (balanced)' if abs(td-tc)<0.005 else f'Saved but NOT balanced: Dr {money(td)} vs Cr {money(tc)}')
        return redirect(url_for('modules.module',mod='journal'))
    if not accts: return page('New Journal Entry',"<div class='panel'><div class='pad'><b>No accounts yet.</b> Add accounts in Chart of Accounts first.</div></div>",'journal')
    aopts="<option value=''>— account —</option>"+"".join(f"<option value='{a.id}'>{h(a.code or '')} · {h(a.name)}</option>" for a in accts)
    rows=""
    for i in range(1,9):
        rows+=f"<tr><td><select name='acct{i}' style='width:100%;border:1px solid var(--line);border-radius:6px;padding:6px'>{aopts}</select></td><td><input name='debit{i}' class='jdeb' oninput='jbal()' type='number' step='any' style='width:120px;text-align:right;border:1px solid var(--line);border-radius:6px;padding:6px'></td><td><input name='credit{i}' class='jcr' oninput='jbal()' type='number' step='any' style='width:120px;text-align:right;border:1px solid var(--line);border-radius:6px;padding:6px'></td></tr>"
    body=f"""<div class='panel'><div class='ph'><h2>New Journal Entry</h2><div class='sp'></div>
      <a class='btn' href='{url_for('modules.module',mod='acctguide')}'>📖 Guide</a>
      <a class='btn' href='{url_for('modules.module',mod='journal')}'>Cancel</a></div><div class='pad'>
      <form method='post'><input type='hidden' name='_csrf' value='{csrf_token()}'><div class='fg'>
        <div class='fld'><label>Date</label><input name='date' type='date' value='{today()}'></div>
        <div class='fld'><label>Reference</label><input name='ref' placeholder='JV-001'></div>
        <div class='fld full'><label>Memo / Description</label><input name='memo'></div></div>
        <div class='tw' style='margin-top:10px'><table><thead><tr><th>Account</th><th class='num'>Debit</th><th class='num'>Credit</th></tr></thead><tbody>{rows}</tbody>
        <tfoot><tr style='background:var(--canvas)'><td style='text-align:right'><b>Totals</b></td>
          <td class='num'><b id='jtd'>0</b></td><td class='num'><b id='jtc'>0</b></td></tr>
          <tr><td colspan='3' style='text-align:right'><span id='jmsg' style='font-weight:700'></span></td></tr></tfoot></table></div>
        <div class='fa'><button class='btn primary' id='jsave'>Save Entry</button></div></form>
        <p style='color:var(--muted);font-size:12.5px;margin-top:6px'>Wadarta Debit waa inay la mid noqoto wadarta Credit (double-entry).
        Ma hubtaa sida? Eeg <a href='{url_for('modules.module',mod='acctguide')}' style='color:var(--petrol)'>Accounting Guide</a>.</p></div>
      <script>
      function jbal(){{
        var td=0,tc=0;
        document.querySelectorAll('.jdeb').forEach(function(e){{td+=parseFloat(e.value||0)||0}});
        document.querySelectorAll('.jcr').forEach(function(e){{tc+=parseFloat(e.value||0)||0}});
        document.getElementById('jtd').textContent=td.toLocaleString(undefined,{{minimumFractionDigits:2}});
        document.getElementById('jtc').textContent=tc.toLocaleString(undefined,{{minimumFractionDigits:2}});
        var m=document.getElementById('jmsg'), diff=Math.round((td-tc)*100)/100;
        if(td===0&&tc===0){{m.textContent='';}}
        else if(diff===0){{m.textContent='✓ Balanced';m.style.color='var(--green)';}}
        else {{m.textContent='⚠ Not balanced · difference '+Math.abs(diff).toLocaleString(undefined,{{minimumFractionDigits:2}});m.style.color='var(--red)';}}
      }}
      </script></div>"""
    return page('New Journal Entry', body, 'journal')


@bp.route('/accounting/split-wallets', methods=['GET', 'POST'])
@login_required
def split_wallets():
    """One-time migration for data created before the wallet split: re-posts paid
    invoices, expenses and purchases so their payments move from the old combined
    'Mobile Money' (1103) account to the correct per-provider account (Sahal 1104,
    EVC 1105, E. Dahab 1106, MyCash 1107, Premier Wallet 1108) — using the payment
    method already recorded on each document. Safe to run more than once."""
    from ..core.security import cur_user
    u = cur_user()
    if not (u and u.role == 'super_admin'):
        return page('Denied', "<div class='panel'><div class='pad'><b>Only the administrator can run this migration.</b></div></div>")
    from ..core.posting import repost_invoice, repost_payment, post_expense, post_purchase, PM_ACCOUNT
    from ..models import Invoice, Expense, Purchase
    _wallets = {'Sahal', 'EVC', 'E. Dahab', 'MyCash', 'Premier Wallet', 'EVC Plus', 'eDahab', 'Mobile Money'}
    if request.method == 'POST':
        moved = 0
        # invoices paid by a wallet method → repost the payment to the split account
        for inv in Invoice.query.filter(Invoice.pay_method.in_(list(_wallets))).all():
            try:
                if not _period_open(inv.date):
                    continue
                repost_invoice(inv); repost_payment(inv); moved += 1
            except Exception:
                db.session.rollback()
        for e in Expense.query.filter(Expense.pay_method.in_(list(_wallets))).all():
            try:
                if not _period_open(e.date):
                    continue
                post_expense(e); moved += 1
            except Exception:
                db.session.rollback()
        for p in Purchase.query.filter(Purchase.pay_method.in_(list(_wallets))).all():
            try:
                if not _period_open(p.date):
                    continue
                post_purchase(p); moved += 1
            except Exception:
                db.session.rollback()
        db.session.commit()
        log(f'Wallet split migration: re-posted {moved} document(s)', action_type='Migration', entity='wallets')
        flash(f'✓ Re-posted {moved} document(s). Mobile-money payments now show under Sahal / EVC / E. Dahab / MyCash / Premier Wallet in the ledger.')
        return redirect(url_for('modules.module', mod='genledger'))
    # GET — count what would move
    n = (Invoice.query.filter(Invoice.pay_method.in_(list(_wallets))).count()
         + Expense.query.filter(Expense.pay_method.in_(list(_wallets))).count()
         + Purchase.query.filter(Purchase.pay_method.in_(list(_wallets))).count())
    body = f"""<div class="panel"><div class="ph"><h2>Split Mobile Money into providers</h2>
      <span class="so">one-time migration for data from before the wallet split</span></div>
      <div class="pad">
        <p style="font-size:14px;line-height:1.6">Older payments were all posted to one combined <b>Mobile Money</b> account (1103).
        This tool re-posts them to the correct per-provider account using the payment method already saved on each document:
        <b>Sahal → 1104</b>, <b>EVC → 1105</b>, <b>E. Dahab → 1106</b>, <b>MyCash → 1107</b>, <b>Premier Wallet → 1108</b>.</p>
        <p style="font-size:13px;color:var(--muted)">Documents to re-post: <b>{n}</b>. Closed fiscal periods are skipped. Safe to run more than once.</p>
        <div style="background:#FBEBEA;border-left:3px solid var(--red);border-radius:8px;padding:10px 12px;font-size:12.5px;margin:10px 0">
          <b>Before you run this:</b> take a backup. It changes historical ledger entries (moving them between accounts). Totals stay the same; only the account each mobile-money payment sits under changes.</div>
        <form method="post"><input type="hidden" name="_csrf" value="{csrf_token()}">
          <button class="btn primary" onclick="return confirm('Re-post {n} document(s) to split Mobile Money by provider? Take a backup first.')">Run migration</button>
          <a class="btn gh" href="{url_for('modules.module', mod='genledger')}">Cancel</a>
        </form>
      </div></div>"""
    return page('Split Mobile Money', body, 'genledger')


@bp.route('/journal/transfer', methods=['GET', 'POST'])
@login_required
def journal_transfer():
    if not can('journal'):
        abort(403)
    accts = Account.query.filter_by(is_group=False).order_by(Account.code).all()
    if request.method == 'POST':
        _d = request.form.get('date') or today()
        if not _period_open(_d):
            flash(f'Period closed: cannot post to {_d[:7]}. Reopen it in Fiscal Periods.')
            return redirect(url_for('acct.journal_transfer'))
        try:
            fr = int(request.form.get('from_acct') or 0)
            to = int(request.form.get('to_acct') or 0)
            amt = float(request.form.get('amount') or 0)
        except (ValueError, TypeError):
            flash('Please enter a valid amount and pick both accounts.')
            return redirect(url_for('acct.journal_transfer'))
        if not fr or not to or fr == to:
            flash('Choose two DIFFERENT accounts — From (money leaves) and To (money arrives).')
            return redirect(url_for('acct.journal_transfer'))
        if amt <= 0:
            flash('Enter an amount greater than zero.')
            return redirect(url_for('acct.journal_transfer'))
        fa = Account.query.get(fr); ta = Account.query.get(to)
        n = JournalEntry.query.filter(JournalEntry.ref.like('TRF-%')).count() + 1
        ref = f'TRF-{n:04d}'
        while JournalEntry.query.filter_by(ref=ref).first():
            n += 1; ref = f'TRF-{n:04d}'
        memo = (request.form.get('memo') or '').strip() or f'Transfer: {fa.name} → {ta.name}'
        try:
            e = JournalEntry(date=_d, ref=ref, memo=memo); db.session.add(e); db.session.commit()
            db.session.add(JournalLine(entry_id=e.id, account_id=ta.id, debit=amt, credit=0))   # money arrives
            db.session.add(JournalLine(entry_id=e.id, account_id=fa.id, debit=0, credit=amt))    # money leaves
            db.session.commit()
        except Exception:
            db.session.rollback()
            from ..core.helpers import log_error
            log_error('journal_transfer')
            flash('Could not post the transfer — please try again.')
            return redirect(url_for('acct.journal_transfer'))
        log(f'Account transfer {ref}: {money(amt)} · {fa.name} → {ta.name}',
            action_type='Transfer', entity=ref)
        flash(f'✓ Transferred {money(amt)} from {fa.name} to {ta.name} ({ref}).')
        return redirect(url_for('modules.module', mod='journal'))

    if not accts:
        return page('Account Transfer', "<div class='panel'><div class='pad'><b>No accounts yet.</b> Add accounts in Chart of Accounts first.</div></div>", 'journal')
    opts = "<option value=''>— select account —</option>" + "".join(
        f"<option value='{a.id}'>{h(a.code or '')} · {h(a.name)}</option>" for a in accts)
    n = JournalEntry.query.filter(JournalEntry.ref.like('TRF-%')).count() + 1
    body = f"""<div class='panel' style='max-width:640px'><div class='ph'><h2>Account Transfer</h2>
      <span class='so'>Move money from one account to another (e.g. Cash → Bank)</span><div class='sp'></div>
      <a class='btn' href='{url_for('modules.module',mod='journal')}'>Cancel</a></div><div class='pad'>
      <form method='post'><input type='hidden' name='_csrf' value='{csrf_token()}'><div class='fg'>
        <div class='fld'><label>From Account <small style='color:var(--muted)'>(money leaves)</small></label>
          <select name='from_acct' data-search required style='width:100%'>{opts}</select></div>
        <div class='fld'><label>To Account <small style='color:var(--muted)'>(money arrives)</small></label>
          <select name='to_acct' data-search required style='width:100%'>{opts}</select></div>
        <div class='fld'><label>Amount</label><input name='amount' type='number' step='any' min='0' required placeholder='0.00'></div>
        <div class='fld'><label>Date</label><input name='date' type='date' value='{today()}'></div>
        <div class='fld full'><label>Memo / Reason <small style='color:var(--muted)'>(optional)</small></label>
          <input name='memo' placeholder='e.g. Deposit cash to bank'></div></div>
        <div class='fa' style='margin-top:12px'><button class='btn primary'>⇄ Post Transfer</button></div></form>
        <div style='color:var(--muted);font-size:12.5px;margin-top:10px'>Reference <b>TRF-{n:04d}</b> will be assigned.
        This posts a balanced entry: <b>Debit</b> the To account and <b>Credit</b> the From account — it appears in the Journal, General Ledger and account balances, and can be reversed from the Journal if needed.</div>
      </div></div>"""
    return page('Account Transfer', body, 'journal')

def acct_guide():
    """Step-by-step guide: manual bookkeeping (journal entries) and billing."""
    if not can('journal'):
        abort(403)

    def step(n, title, body):
        return (f"<div style='display:flex;gap:12px;margin-bottom:14px'>"
                f"<div style='flex:none;width:30px;height:30px;border-radius:50%;background:var(--petrol);color:#fff;"
                f"display:flex;align-items:center;justify-content:center;font-weight:700'>{n}</div>"
                f"<div style='flex:1'><b>{h(title)}</b><div style='color:var(--muted);font-size:13.5px;margin-top:3px'>{body}</div></div></div>")

    # debit/credit rules
    rules = (
        "<table><thead><tr><th>Account type</th><th>Increases with</th><th>Decreases with</th><th>Examples</th></tr></thead><tbody>"
        "<tr><td><span class='pill blue'>Asset</span></td><td><b style='color:var(--green)'>Debit</b></td><td>Credit</td><td>Cash 1101, Bank 1102, Receivable 1200</td></tr>"
        "<tr><td><span class='pill red'>Expense</span></td><td><b style='color:var(--green)'>Debit</b></td><td>Credit</td><td>Salaries, Rent, Bank charges</td></tr>"
        "<tr><td><span class='pill amber'>Liability</span></td><td><b style='color:var(--red)'>Credit</b></td><td>Debit</td><td>Payable 2100, VAT 2300</td></tr>"
        "<tr><td><span class='pill teal'>Equity</span></td><td><b style='color:var(--red)'>Credit</b></td><td>Debit</td><td>Owner's Capital 3000</td></tr>"
        "<tr><td><span class='pill green'>Income</span></td><td><b style='color:var(--red)'>Credit</b></td><td>Debit</td><td>Lab 4000, X-ray, Consultation</td></tr>"
        "</tbody></table>")

    # common entries cheat-sheet
    cheat = (
        "<table><thead><tr><th>Transaction</th><th>Debit (Dr)</th><th>Credit (Cr)</th></tr></thead><tbody>"
        "<tr><td>Patient invoice (service given)</td><td>Accounts Receivable 1200</td><td>Income 40xx (Lab/X-ray/Consultation)</td></tr>"
        "<tr><td>Patient pays cash</td><td>Cash 1101</td><td>Accounts Receivable 1200</td></tr>"
        "<tr><td>Patient pays by EVC/Sahal/e-Dahab/Bank</td><td>Bank 1102</td><td>Accounts Receivable 1200</td></tr>"
        "<tr><td>Buy supplies on credit</td><td>Inventory / Expense</td><td>Accounts Payable 2100</td></tr>"
        "<tr><td>Pay a supplier</td><td>Accounts Payable 2100</td><td>Bank 1102</td></tr>"
        "<tr><td>Pay staff salary</td><td>Salary Expense</td><td>Cash 1101 / Bank 1102</td></tr>"
        "<tr><td>Bank charge / fee</td><td>Bank Charges (Expense)</td><td>Bank 1102</td></tr>"
        "<tr><td>Owner adds capital</td><td>Cash 1101 / Bank 1102</td><td>Owner's Capital 3000</td></tr>"
        "</tbody></table>")

    body = f"""
    <div class='panel' style='margin-bottom:16px'>
      <div class='ph'><h2>Accounting Guide · Step by step</h2><span class='so'>Manual bookkeeping &amp; billing</span>
      <div class='sp'></div>
      <a class='btn primary' href='{url_for('acct.journal_new')}'>+ New Journal Entry</a>
      <a class='btn' href='{url_for('billing.invoice_new')}'>+ New Invoice</a></div>
      <div class='pad' style='color:var(--muted);font-size:14px'>
        Every transaction uses <b>double-entry</b>: total <b>Debit</b> must equal total <b>Credit</b>.
        Waxaa jira laba nooc oo qorista ah: (1) <b>gacanta</b> — Journal Entry; (2) <b>si toos ah</b> — billing-ka
        (invoice + lacag-bixin) oo si otomaatig ah ugu qora General Ledger-ka.
      </div>
    </div>

    <div class='panel' style='margin-bottom:16px'>
      <div class='ph'><h2>The rule: Debit &amp; Credit</h2></div>
      <div class='tw'>{rules}</div>
      <div class='pad' style='color:var(--muted);font-size:13px'>Tip: Assets &amp; Expenses grow on the <b>Debit</b> side; Income, Liabilities &amp; Equity grow on the <b>Credit</b> side.</div>
    </div>

    <div class='ad-two' style='display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px'>
      <div class='panel'>
        <div class='ph'><h2>A · Manual journal entry (book by hand)</h2></div>
        <div class='pad'>
          {step(1, "Open the form", f"Accounting → <a href='{url_for('acct.journal_new')}' style='color:var(--petrol)'>New Journal Entry</a>.")}
          {step(2, "Header", "Enter the <b>Date</b>, a <b>Reference</b> (e.g. JV-001) and a <b>Memo</b> describing the transaction.")}
          {step(3, "Add the lines", "On each row pick an <b>Account</b>, then type the amount in <b>Debit</b> OR <b>Credit</b> (never both on one line).")}
          {step(4, "Balance it", "The live total at the bottom must show <b>Balanced ✓</b> — total Debit = total Credit.")}
          {step(5, "Save", "Click <b>Save Entry</b>. It posts to the General Ledger and appears in Journal Entries.")}
          <div class='pad' style='background:var(--canvas);border-radius:10px;margin-top:6px'>
            <b>Example — Owner adds $1,000 to the bank:</b>
            <table style='margin-top:6px'><thead><tr><th>Account</th><th class='num'>Debit</th><th class='num'>Credit</th></tr></thead><tbody>
            <tr><td>1102 · Bank</td><td class='num'>1,000</td><td class='num'>—</td></tr>
            <tr><td>3000 · Owner's Capital</td><td class='num'>—</td><td class='num'>1,000</td></tr>
            <tr style='background:var(--surface)'><td><b>Total</b></td><td class='num'><b>1,000</b></td><td class='num'><b>1,000</b></td></tr>
            </tbody></table>
          </div>
        </div>
      </div>

      <div class='panel'>
        <div class='ph'><h2>B · Billing transaction (automatic posting)</h2></div>
        <div class='pad'>
          {step(1, "New invoice", f"Billing → <a href='{url_for('billing.invoice_new')}' style='color:var(--petrol)'>New Invoice</a>. Choose the patient (or Walk-in).")}
          {step(2, "Add services", "Add each service/test line with its price. Apply discount or VAT if needed.")}
          {step(3, "Save invoice", "Saving creates the invoice (status <b>Unpaid</b>) and auto-posts: <b>Dr</b> Accounts Receivable / <b>Cr</b> Income.")}
          {step(4, "Register payment", "Click <b>Register Payment</b>, enter the amount and method (Cash / EVC Plus / Sahal / e-Dahab / Bank).")}
          {step(5, "Payment posts", "This posts <b>Dr</b> Cash/Bank / <b>Cr</b> Accounts Receivable and creates a receipt (RCT).")}
          {step(6, "Print", "Use <b>Print</b> → the Print / Download / Open dialog for the receipt or invoice.")}
          {step(7, "Trace it", f"Open the <a href='{url_for('modules.module', mod='genledger')}' style='color:var(--petrol)'>General Ledger</a> — every line is clickable to the invoice, patient and account.")}
        </div>
      </div>
    </div>

    <div class='panel'>
      <div class='ph'><h2>Common transactions · cheat-sheet</h2></div>
      <div class='tw'>{cheat}</div>
      <div class='pad' style='color:var(--muted);font-size:12.5px'>Account codes are examples — match them to your Chart of Accounts.</div>
    </div>
    """
    return page('Accounting Guide', body, 'acctguide')


def ledger_view():
    # The old ledger has been merged into the new General Ledger module
    # (genledger). Redirect so every existing "General Ledger" link opens the
    # new screen (with Partner/Label, clickable rows, Account Balances, etc.).
    acct = request.args.get('account')
    if acct:
        return redirect(url_for('modules.module', mod='genledger', account=acct, group='none'))
    return redirect(url_for('modules.module', mod='genledger'))

TYPE_COLORS = {'Asset':'blue','Liability':'amber','Equity':'teal','Income':'green','Expense':'red'}

def acct_balance(a):
    # SQLAlchemy applies the Money type's result processor to aggregates too,
    # so this sum already comes back in dollars (verified by test).
    net = db.session.query(
        db.func.coalesce(db.func.sum(JournalLine.debit), 0) -
        db.func.coalesce(db.func.sum(JournalLine.credit), 0)
    ).filter(JournalLine.account_id == a.id).scalar() or 0
    return money_round((a.opening or 0) + net)

def coa_view():
    roots = Account.query.filter_by(parent_id=None).order_by(Account.code).all()
    def render(a, depth):
        pad = 14 + depth * 24
        typ = pill(a.type, TYPE_COLORS)
        if a.is_group:
            row = (f"<tr style='background:#F7FAFB'><td style='padding-left:{pad}px'><b>{h(a.code or '')} &nbsp; {h(a.name)}</b></td>"
                   f"<td>{typ}</td><td class='num' style='color:var(--muted)'>group</td>"
                   f"<td class='num'><a class='btn gh sm' href='{url_for('acct.coa_form')}?parent={a.id}'>+ Sub</a>"
                   f"<a class='btn gh sm' href='{url_for('acct.coa_form')}?id={a.id}'>Edit</a></td></tr>")
        else:
            row = (f"<tr><td style='padding-left:{pad}px'>{h(a.code or '')} &nbsp; {h(a.name)}</td>"
                   f"<td>{typ}</td><td class='num'>{money(acct_balance(a))}</td>"
                   f"<td class='num'><a class='btn gh sm' href='{url_for('acct.coa_form')}?id={a.id}'>Edit</a>"
                   f"<a class='btn gh sm' href='{url_for('acct.coa_delete', aid=a.id)}' onclick=\"return confirm('Delete this account?')\">Del</a></td></tr>")
        out = row
        for c in sorted(a.children, key=lambda x: (x.code or '')):
            out += render(c, depth + 1)
        return out
    body = ''.join(render(a, 0) for a in roots) or "<tr><td colspan='4'><div class='empty'><b>No accounts yet</b></div></td></tr>"
    # ---- Odoo stat band: totals by account type ----
    _leaf = Account.query.filter_by(is_group=False).all()
    _tot = {'Asset': 0.0, 'Liability': 0.0, 'Equity': 0.0, 'Income': 0.0, 'Expense': 0.0}
    for a in _leaf:
        if a.type in _tot:
            _tot[a.type] += acct_balance(a)
    _COL = {'Asset': ('a', '#2b7de9'), 'Liability': ('c', 'var(--amber)'), 'Equity': ('t', '#0E7C86'),
            'Income': ('b', 'var(--green)'), 'Expense': ('d', 'var(--red)')}
    _CSS = """<style>
    .coa-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .coa-stat{flex:1;min-width:150px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
    .coa-stat .l{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
    .coa-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
    </style>"""
    _LBL = {'Asset': 'Assets', 'Liability': 'Liabilities', 'Equity': 'Equity',
            'Income': 'Income', 'Expense': 'Expenses'}
    _cards = ''.join(
        f"<div class='coa-stat' style='border-left:3px solid {_COL[t][1]}'><div class='l'>{_LBL[t]}</div>"
        f"<div class='v'>{money(_tot[t])}</div></div>" for t in ('Asset', 'Liability', 'Equity', 'Income', 'Expense'))
    stats = _CSS + f"<div class='coa-stats'>{_cards}</div>"
    inner = (stats + f"<div class='panel'><div class='ph'><h2>Chart of Accounts</h2><span class='so'>Xisaabaadka & sub-accounts</span>"
             f"<div class='sp'></div><a class='btn primary' href='{url_for('acct.coa_form')}'>+ New Account</a></div>"
             f"<div class='tw'><table><thead><tr><th>Code &amp; Account Name</th><th>Type</th><th class='num'>Balance</th><th></th></tr></thead>"
             f"<tbody>{body}</tbody></table></div>"
             f"<div class='pad' style='color:var(--muted);font-size:12.5px'>Tusaale: hoosta <b>Cash and Bank</b> waxaad ku dari kartaa sub-accounts sida Main Account, Cash in Hand, Mobile Money — guji <b>+ Sub</b>.</div></div>")
    return page('Chart of Accounts', inner, 'accounts')

@bp.route('/coa/form')
@login_required
def coa_form():
    if not can('accounts'): abort(403)
    aid = request.args.get('id'); parent = request.args.get('parent')
    a = Account.query.get(int(aid)) if aid else None
    groups = Account.query.filter_by(is_group=True).order_by(Account.code).all()
    popts = "<option value=''>— none (top level) —</option>" + "".join(
        f"<option value='{g.id}' {'selected' if (a and a.parent_id==g.id) or (not a and parent and str(g.id)==str(parent)) else ''}>{h(g.code or '')} · {h(g.name)}</option>"
        for g in groups)
    topts = "".join(f"<option {'selected' if a and a.type==t else ''}>{t}</option>" for t in ['Asset','Liability','Equity','Income','Expense'])
    body = (f"<div class='panel' style='max-width:560px'><div class='ph'><h2>{'Edit' if a else 'New'} Account</h2></div><div class='pad'>"
            f"<form method='post' action='{url_for('acct.coa_save')}'>"
            f"<input type='hidden' name='id' value='{a.id if a else ''}'>"
            f"<div class='fld'><label>Account Code</label><input name='code' value='{h(a.code if a else '')}' required></div>"
            f"<div class='fld'><label>Account Name</label><input name='name' value='{h(a.name if a else '')}' required></div>"
            f"<div class='fld'><label>Type</label><select name='type'>{topts}</select></div>"
            f"<div class='fld'><label>Parent Account (to make it a sub-account)</label><select name='parent_id'>{popts}</select></div>"
            f"<div class='fld'><label style='font-weight:400'><input type='checkbox' name='is_group' value='1' {'checked' if a and a.is_group else ''}> This is a Group / Header (holds sub-accounts, no balance)</label></div>"
            f"<div class='fld'><label>Opening Balance</label><input name='opening' type='number' step='any' value='{a.opening if a else 0}'></div>"
            f"<div style='display:flex;gap:10px;justify-content:flex-end;margin-top:14px'><a class='btn' href='{url_for('modules.module', mod='accounts')}'>Cancel</a><button class='btn primary'>Save Account</button></div>"
            f"</form></div></div>")
    return page('Account', body, 'accounts')

@bp.route('/coa/save', methods=['POST'])
@login_required
def coa_save():
    if not can('accounts'): abort(403)
    aid = request.form.get('id')
    a = Account.query.get(int(aid)) if aid else Account()
    a.code = request.form.get('code'); a.name = request.form.get('name'); a.type = request.form.get('type')
    p = request.form.get('parent_id'); a.parent_id = int(p) if p else None
    a.is_group = bool(request.form.get('is_group'))
    a.opening = float(request.form.get('opening') or 0); a.active = True
    if not aid: db.session.add(a)
    db.session.commit(); log(f"Saved account {a.code} {a.name}")
    flash('Account saved'); return redirect(url_for('modules.module', mod='accounts'))

@bp.route('/coa/<int:aid>/delete')
@login_required
def coa_delete(aid):
    if not can('accounts'): abort(403)
    a = Account.query.get_or_404(aid)
    if a.children:
        flash('Cannot delete: this account has sub-accounts. Delete them first.')
    else:
        db.session.delete(a); db.session.commit(); log(f"Deleted account {a.code}")
        flash('Account deleted')
    return redirect(url_for('modules.module', mod='accounts'))

def acc_dashboard():
    ym = dt.date.today().isoformat()[:7]
    td = dt.date.today().isoformat()
    inv = live_invoices()
    rev_month = sum(i.total for i in inv if (i.date or '').startswith(ym))
    exp_month = sum(e.amount for e in Expense.query.all() if (e.date or '').startswith(ym))
    rev_today = sum(i.total for i in inv if (i.date or '') == td)
    exp_today = sum(e.amount for e in Expense.query.all() if (e.date or '') == td)
    net_month = rev_month - exp_month
    outstanding = sum(i.total - (i.paid or 0) for i in inv if i.status != 'Paid')
    n_out = sum(1 for i in inv if i.status != 'Paid' and (i.total - (i.paid or 0)) > 0)
    banks = [a for a in Account.query.filter_by(is_group=False).all() if a.parent and a.parent.name == 'Cash and Bank']
    bank_balance = sum(acct_balance(a) for a in banks)
    cash_acc = Account.query.filter_by(code='1000').first()
    cash_balance = acct_balance(cash_acc) if cash_acc else 0
    # pending commission / radiologist payables + insurance receivables
    from ..models import CommissionAccrual
    pend_doc = sum(a.balance for a in CommissionAccrual.query.filter_by(payee_kind='doctor').all())
    pend_rad = sum(a.balance for a in CommissionAccrual.query.filter_by(payee_kind='radiologist').all())
    ins_recv = sum(i.total - (i.paid or 0) for i in inv if (i.pay_method or '') == 'Insurance' and i.status != 'Paid')

    def kpi(l, v, s, ac, neg=False, link=None):
        core = f"<div class='kpi' style='--ac:{ac}'><div class='l'>{l}</div><div class='v {'neg' if neg else ''}'>{v}</div><div class='s'>{s}</div></div>"
        return f"<a href='{link}' style='text-decoration:none'>{core}</a>" if link else core
    kpis = ("<div class='kpis' style='grid-template-columns:repeat(5,1fr)'>"
            + kpi("Cash Balance", money(cash_balance), "Account 1000", "var(--green)")
            + kpi("Bank Balance", money(bank_balance), f"{len(banks)} accounts", "var(--amber)")
            + kpi("Today's Income", money(rev_today), td, "var(--teal)")
            + kpi("Today's Expenses", money(exp_today), td, "#E4572E")
            + kpi("Net Profit", money(net_month), "This month", "var(--green)", neg=net_month < 0)
            + "</div><div class='kpis' style='grid-template-columns:repeat(5,1fr)'>"
            + kpi("Monthly Revenue", money(rev_month), ym, "var(--teal)")
            + kpi("Outstanding Invoices", money(outstanding), f"{n_out} unpaid", "#9B5DE5")
            + kpi("Pending Dr Commission", money(pend_doc), "Payable", "var(--red)" if pend_doc else "var(--green)", link=url_for('modules.module', mod='payables') + '?kind=doctor')
            + kpi("Pending Radiologist Fees", money(pend_rad), "Payable", "var(--red)" if pend_rad else "var(--green)", link=url_for('modules.module', mod='payables') + '?kind=radiologist')
            + kpi("Insurance Receivables", money(ins_recv), "Unpaid insurance", "var(--blue)")
            + "</div>")

    cards = [
        ('#4C7DF0','A','Chart of Accounts',['Account List','Account Groups','Sub-accounts','Account Types'], url_for('modules.module', mod='accounts')),
        ('#22A06B','J','Journal Entries',['Journal Vouchers','General Journal','Posted Entries','Double-entry'], url_for('modules.module', mod='journal')),
        ('#F5852B','I','Sales Invoices',['Customer Invoices','Payments','VAT & Discount','Invoice Reports'], url_for('modules.module', mod='invoices')),
        ('#9B5DE5','L','General Ledger',['All Transactions','By Account','Running Balance','Ledger Report'], url_for('modules.module', mod='genledger')),
        ('#1FB6C1','B','Bank & Cash',['Bank Accounts','Cash in Hand','Mobile Money','Balances'], url_for('modules.module', mod='accounts')),
        ('#E4572E','E','Expenses',['Expense Entry','Categories','Approval','Expense Reports'], url_for('modules.module', mod='expenses')),
        ('#EC4899','F','Assets',['Fixed Assets','Equipment','Depreciation','Asset Reports'], url_for('modules.module', mod='accounts')),
        ('#2ECC71','R','Financial Reports',['Profit & Loss','Balance Sheet','Cash Flow','Trial Balance'], url_for('modules.module', mod='finance')),
        ('#0F9D8C','C','Doctor Commission',['Referring Doctors','Per-invoice','By Doctor','Commission Report'], url_for('modules.module', mod='commission')),
    ]
    card_html = ''
    for color, letter, title, subs, link in cards:
        bullets = ''.join(f"<li>{h(s)}</li>" for s in subs)
        card_html += (f"<a class='acc-card' href='{link}'><div class='acc-ic' style='background:{color}'>{letter}</div>"
                      f"<div class='acc-body'><div class='acc-title'>{h(title)}</div><ul>{bullets}</ul></div></a>")

    # recent transactions
    tx = []
    for i in sorted(inv, key=lambda x: (x.date or ''), reverse=True)[:6]:
        tx.append((i.date or '', f"INV-{i.id:04d}", (i.patient.name if i.patient else 'Invoice'), i.total, 'in'))
    for e in sorted(Expense.query.all(), key=lambda x: (x.date or ''), reverse=True)[:6]:
        tx.append((e.date or '', "EXP", (e.category or 'Expense'), -(e.amount or 0), 'out'))
    tx.sort(key=lambda x: x[0], reverse=True); tx = tx[:6]
    tx_rows = ''.join(
        f"<div class='txr'><div><b>{h(ref)}</b><br><small>{h(who)}</small></div>"
        f"<div style='text-align:right'><span style='color:{'var(--green)' if amt>=0 else 'var(--red)'};font-weight:600'>{money(amt)}</span><br><small>{h(d)}</small></div></div>"
        for d, ref, who, amt, direction in tx) or "<div class='pad' style='color:var(--muted)'>No transactions yet.</div>"

    bank_rows = ''.join(
        f"<div class='txr'><div><b>{h(a.name)}</b><br><small>{h(a.code or '')}</small></div>"
        f"<div style='font-weight:600'>{money(acct_balance(a))}</div></div>"
        for a in banks) or "<div class='pad' style='color:var(--muted)'>Add bank sub-accounts under Cash and Bank.</div>"

    quick = (f"<a class='qa' href='{url_for('billing.invoice_new')}'>+ Create Invoice</a>"
             f"<a class='qa' href='{url_for('modules.module', mod='expenses')}'>+ Record Expense</a>"
             f"<a class='qa' href='{url_for('acct.coa_form')}'>+ New Account</a>"
             f"<a class='qa' href='{url_for('acct.journal_new')}'>+ Journal Entry</a>")

    style = """<style>
    .acc-wrap{display:grid;grid-template-columns:1fr 320px;gap:18px;align-items:start}
    .acc-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
    .acc-card{display:flex;gap:12px;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:15px;text-decoration:none;color:inherit;transition:.15s;box-shadow:var(--shadow)}
    .acc-card:hover{border-color:var(--petrol-300);transform:translateY(-2px)}
    .acc-ic{width:42px;height:42px;flex:none;border-radius:11px;color:#fff;display:grid;place-items:center;font-weight:700;font-family:'Space Grotesk';font-size:18px}
    .acc-title{font-weight:700;font-size:14.5px;color:var(--petrol);font-family:'Space Grotesk';margin-bottom:5px}
    .acc-card ul{list-style:none;padding:0;margin:0}
    .acc-card ul li{font-size:12px;color:var(--muted);padding:1.5px 0 1.5px 13px;position:relative}
    .acc-card ul li:before{content:'•';position:absolute;left:2px;color:var(--amber-dk)}
    .acc-side .panel{margin-bottom:16px}
    .txr{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line);font-size:13px}
    .txr:last-child{border-bottom:none}.txr small{color:var(--muted);font-size:11px}
    .qa{display:block;background:#F0F4F5;border:1px solid var(--line);border-radius:9px;padding:10px 13px;margin:0 14px 8px;text-decoration:none;color:var(--petrol);font-weight:600;font-size:13px}
    .qa:hover{background:var(--amber-soft);border-color:var(--amber)}
    @media(max-width:900px){.acc-wrap{grid-template-columns:1fr}.acc-cards{grid-template-columns:1fr 1fr}}
    @media(max-width:560px){.acc-cards{grid-template-columns:1fr}}
    </style>"""

    body = (style + kpis
            + "<div class='acc-wrap'><div><div class='panel'><div class='ph'><h2>Accounting Categories &amp; Features</h2>"
            + "<span class='so'>Guji mid si aad u gasho</span></div><div class='pad'><div class='acc-cards'>" + card_html + "</div></div></div></div>"
            + "<div class='acc-side'>"
            + "<div class='panel'><div class='ph'><h2>Recent Transactions</h2></div>" + tx_rows + "</div>"
            + "<div class='panel'><div class='ph'><h2>Bank Accounts</h2></div>" + bank_rows + "</div>"
            + "<div class='panel'><div class='ph'><h2>Quick Actions</h2></div><div style='padding-top:12px'>" + quick + "</div></div>"
            + "</div></div>")
    return page('Accounting', body, 'acct')


def finance_view():
    tab=request.args.get('tab','pnl'); y=cur_year()
    d1, d2, plabel, pd1, pd2 = report_period()
    from ..core.posting import gl_statements as _gl_stmt
    def _in(dstr, a, b): return a <= (dstr or '') <= b
    inv=[i for i in live_invoices() if _in(i.date, d1, d2)]
    exp=[e for e in Expense.query.all() if _in(e.date, d1, d2)]
    pur=[p for p in Purchase.query.all() if _in(p.date, d1, d2)]
    # previous period (for comparison)
    pinv=[i for i in live_invoices() if _in(i.date, pd1, pd2)]
    pexp=[e for e in Expense.query.all() if _in(e.date, pd1, pd2)]
    prev_rev=sum(i.total for i in pinv); prev_exp=sum(e.amount for e in pexp)
    import datetime as _dt
    _days=( _dt.date.fromisoformat(d2)-_dt.date.fromisoformat(d1)).days+1
    rev_services=sum(i.total for i in inv)
    revenue=rev_services
    from ..core.posting import commission_preview
    # Use the SAME source as the ledger accrual (accrue_commissions → commission_preview)
    # so the statement reconciles with what actually posts to 5130 / 5140. The legacy
    # Invoice.commission property double-counted percent rates (20 → ×20, not ×0.20).
    _cp=[commission_preview(i) for i in inv]
    commission=sum((c[1] or 0) for c in _cp)
    rad_fee=sum((c[3] or 0) for c in _cp)
    payroll=sum(e.gross for e in Employee.query.filter_by(active=True).all())*12*( _days/365.0)
    cogs=sum(p.total for p in pur if p.category in ('Medical Supplies','Contrast Media','Reagents','Films'))
    exp_total=sum(e.amount for e in exp)
    opex=exp_total+payroll
    net=revenue-cogs-commission-rad_fee-opex
    prev_net=prev_rev-prev_exp
    def _delta(cur, prev):
        if not prev: return ''
        ch=(cur-prev)/abs(prev)*100
        cl='var(--green)' if ch>=0 else 'var(--red)'
        return f" <small style='color:{cl};font-weight:700'>{'▲' if ch>=0 else '▼'} {abs(ch):.0f}% vs prev</small>"
    cmp_bar=(f"<div class='panel'><div class='pad' style='display:flex;gap:26px;flex-wrap:wrap;font-size:13.5px'>"
             f"<span><b>Period:</b> {h(plabel)} ({h(d1)} → {h(d2)})</span>"
             f"<span><b>Revenue:</b> {money(revenue)}{_delta(revenue, prev_rev)}</span>"
             f"<span><b>Expenses:</b> {money(exp_total)}{_delta(exp_total, prev_exp)}</span>"
             f"<span><b>Net:</b> {money(net)}{_delta(net, prev_net)}</span>"
             f"<span style='color:var(--muted)'>Prev period: {h(pd1)} → {h(pd2)} · Rev {money(prev_rev)}</span>"
             f"</div></div>")
    _period_ui = period_toolbar() + cmp_bar
    cash_in=sum(i.paid or 0 for i in inv)
    cash_out=sum(e.paid or 0 for e in exp)+sum(p.paid or 0 for p in pur)+payroll+commission+rad_fee
    receivable=sum(i.total-(i.paid or 0) for i in live_invoices())
    payable=sum(p.total-(p.paid or 0) for p in Purchase.query.all())
    capital=float(setting('capital','0') or 0)
    cash=capital+cash_in-cash_out

    _pq = f"period={h(request.args.get('period','year'))}&from={h(request.args.get('from',''))}&to={h(request.args.get('to',''))}"
    tabs=f"""<div class="tabs">
      <a class="{'active' if tab=='pnl' else ''}" href="?tab=pnl&{_pq}">Profit & Loss</a>
      <a class="{'active' if tab=='cash' else ''}" href="?tab=cash&{_pq}">Cash Book</a>
      <a class="{'active' if tab=='bs' else ''}" href="?tab=bs&{_pq}">Balance Sheet</a>
      <a class="{'active' if tab=='tb' else ''}" href="?tab=tb&{_pq}">Trial Balance</a></div>"""
    def _glt(t):
        return url_for('modules.module', mod='genledger') + f"?type={t}&group=account"

    def _M(m):
        return url_for('modules.module', mod=m)

    def _drill(label, href):
        return (f"<a href='{href}' style='color:var(--petrol);text-decoration:none' title='See where this comes from'>{label} <span style='font-size:10px;opacity:.7'>&#8599;</span></a>"
                if href else label)

    def R(l, v, c='', href=''):
        return f"<div class='r {c}'><span>{_drill(l, href)}</span><span class='amt {'neg' if v<0 else ''}' style='color:{'var(--red)' if v<0 else 'inherit'}'>{money(v)}</span></div>"
    _hint = "<div style='color:var(--muted);font-size:12px;margin-bottom:8px'>Tip: click a line (e.g. Revenue) to see where it comes from.</div>"
    _FIN_CSS = ("<style>.fin-band{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}"
                ".fin-stat{flex:1;min-width:150px;border:1px solid var(--line);background:var(--surface);"
                "border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}"
                ".fin-stat .l{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}"
                ".fin-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}</style>")
    def _band(*cards):
        cells = ''.join(
            f"<div class='fin-stat' style='border-left:3px solid {ac}'><div class='l'>{lbl}</div>"
            f"<div class='v' style='color:{vc}'>{money(val)}</div></div>" for lbl, val, ac, vc in cards)
        return _FIN_CSS + f"<div class='fin-band'>{cells}</div>"
    def _rows_to_html(rep):
        """Render finance_report_rows() output (GL-linked) into the on-screen stmt."""
        out = []
        for kind, label, val, disp in rep['rows']:
            if kind == 'sec':
                out.append(f"<div class='sec'>{h(label)}</div>")
            elif kind == 'line':
                out.append(R(label, val or 0))
            elif kind == 'tot':
                out.append(R(label, val or 0, 'tot'))
            elif kind == 'grand':
                out.append(R(label, val or 0, 'grand'))
        return "<div class='stmt' style='max-width:620px'>" + ''.join(out) + "</div>"

    if tab == 'pnl':
        G = _gl_stmt(d1, d2)
        _grn = 'var(--green)' if G['net_income'] >= 0 else 'var(--red)'
        inner = _band(('Total Income', G['income'], 'var(--petrol)', 'var(--ink)'),
                      ('Total Expenses', G['expense'], 'var(--amber)', 'var(--ink)'),
                      ('Net Profit', G['net_income'], _grn, _grn)) + _hint + _rows_to_html(finance_report_rows('pnl'))
    elif tab == 'cash':
        G = _gl_stmt(d1, d2)
        _opening_cash = G['cash_asat'] - G['cash_movement']
        inner = _band(('Opening Cash', _opening_cash, 'var(--muted)', 'var(--ink)'),
                      ('Net Movement', G['cash_movement'], 'var(--amber)', 'var(--ink)'),
                      ('Closing Cash & Bank', G['cash_asat'], 'var(--petrol)', 'var(--ink)')) + _hint + _rows_to_html(finance_report_rows('cash'))
    elif tab=='tb':
        from sqlalchemy import func
        from ..core.posting import opening_dr, opening_totals
        rows=''; td=tc=0
        for a in Account.query.order_by(Account.code).all():
            dd=db.session.query(func.coalesce(func.sum(JournalLine.debit),0)).filter(JournalLine.account_id==a.id).scalar() or 0
            cc=db.session.query(func.coalesce(func.sum(JournalLine.credit),0)).filter(JournalLine.account_id==a.id).scalar() or 0
            net=opening_dr(a)+dd-cc
            if abs(net)<0.005: continue
            dr=net if net>0 else 0; cr=-net if net<0 else 0; td+=dr; tc+=cr
            op_tag=" <span class='pill blue' style='font-size:10px'>incl. opening</span>" if abs(opening_dr(a))>0.005 else ''
            rows+=f"<tr><td><a href='{url_for('modules.module', mod='genledger')}?account={a.id}&group=none' style='color:var(--petrol);text-decoration:none'>{h(a.code or '')} &middot; {h(a.name)}</a>{op_tag}</td><td class='num'>{money(dr) if dr else '—'}</td><td class='num'>{money(cr) if cr else '—'}</td></tr>"
        _,_,_,obe=opening_totals()
        if abs(obe)>0.005:
            # standard Opening Balance Equity offset so openings self-balance
            if obe>0: tc+=obe; rows+=f"<tr><td>3199 &middot; Opening Balance Equity <span class='pill teal' style='font-size:10px'>auto</span></td><td class='num'>—</td><td class='num'>{money(obe)}</td></tr>"
            else: td+=-obe; rows+=f"<tr><td>3199 &middot; Opening Balance Equity <span class='pill teal' style='font-size:10px'>auto</span></td><td class='num'>{money(-obe)}</td><td class='num'>—</td></tr>"
        if not rows: rows="<tr><td colspan='3' style='color:var(--muted);padding:14px'>No journal entries yet. Post entries in Journal Entries.</td></tr>"
        chk=td-tc
        _cc = 'var(--green)' if abs(chk)<=0.5 else 'var(--red)'
        inner=_band(('Total Debit',td,'var(--petrol)','var(--ink)'),
                    ('Total Credit',tc,'#0E7C86','var(--ink)'),
                    ('Difference',chk,_cc,_cc))+f"<div class='tw'><table><thead><tr><th>Account</th><th class='num'>Debit</th><th class='num'>Credit</th></tr></thead><tbody>{rows}</tbody><tfoot><tr style='font-weight:700;background:#F0F4F5'><td>TOTAL</td><td class='num'>{money(td)}</td><td class='num'>{money(tc)}</td></tr></tfoot></table></div><div class='stmt' style='max-width:560px;margin-top:10px'><div class='check' style=\"{'background:var(--red-soft);color:var(--red)' if abs(chk)>0.5 else ''}\"><span>{'⚠ Out of balance' if abs(chk)>0.5 else '✓ Debits = Credits'}</span><span>{money(chk)}</span></div></div>"
    else:
        G = _gl_stmt(d1, d2)
        chk = G['balances']
        inner = _band(('Total Assets', G['assets'], 'var(--petrol)', 'var(--ink)'),
                      ('Liabilities', G['liabilities'], 'var(--amber)', 'var(--ink)'),
                      ('Equity', G['equity_with_ni'], 'var(--green)', 'var(--ink)')) + _hint + _rows_to_html(finance_report_rows('bs')) + \
                f"<div class='stmt' style='max-width:620px'><div class=\"check\" style=\"{'background:var(--red-soft);color:var(--red)' if abs(chk)>0.5 else ''}\"><span>{'⚠ Out of balance' if abs(chk)>0.5 else '✓ Balanced (ties to Trial Balance)'}</span><span>{money(chk)}</span></div></div>"
    _rep_url = url_for('acct.finance_report_pdf') + f'?tab={tab}&{_pq}'
    _rep_title = 'Profit & Loss' if tab == 'pnl' else 'Cash Book' if tab == 'cash' else 'Trial Balance' if tab == 'tb' else 'Balance Sheet'
    return page('Accounting', _period_ui+tabs+f"<div class='panel'><div class='ph'><h2>{'Profit & Loss' if tab=='pnl' else 'Cash Book' if tab=='cash' else 'Trial Balance' if tab=='tb' else 'Balance Sheet'}</h2><span class='so'>{h(plabel)}</span><div class='sp'></div><button class='btn sm' onclick=\"MDCDoc.openSelf('{_rep_title}','{_rep_url}')\">Print</button></div><div class='pad'>{inner}</div></div>", 'finance')


def finance_report_rows(tab):
    """Statement rows for the on-screen tabs and the PDF. The P&L, Balance Sheet
    and Cash Flow are now built ENTIRELY from the general ledger (via
    gl_statements), so every posted money movement flows in automatically and the
    statements tie to the Trial Balance."""
    from ..core.posting import (commission_preview, opening_dr, opening_totals,
                                 gl_statements)
    from sqlalchemy import func
    d1, d2, plabel, pd1, pd2 = report_period()
    G = gl_statements(d1, d2)
    M = money

    if tab == 'cash':
        # Cash Flow straight from the ledger: net movement on cash/bank/wallet
        # accounts in the period, tied to the closing cash balance as at d2.
        opening_cash = G['cash_asat'] - G['cash_movement']
        rows = [('sec', 'Cash Flow (from the General Ledger)', None, None),
                ('line', 'Opening Cash & Bank', opening_cash, M(opening_cash)),
                ('line', 'Net Cash Movement (period)', G['cash_movement'], M(G['cash_movement'])),
                ('grand', 'Closing Cash & Bank', G['cash_asat'], M(G['cash_asat']))]
        return {'title': 'Cash Flow', 'plabel': plabel, 'kind': 'stmt', 'rows': rows}

    if tab == 'tb':
        td = tc = 0; body = []
        for a in Account.query.order_by(Account.code).all():
            dd = db.session.query(func.coalesce(func.sum(JournalLine.debit), 0)).filter(JournalLine.account_id == a.id).scalar() or 0
            cc = db.session.query(func.coalesce(func.sum(JournalLine.credit), 0)).filter(JournalLine.account_id == a.id).scalar() or 0
            n = opening_dr(a) + dd - cc
            if abs(n) < 0.005: continue
            dr = n if n > 0 else 0; cr = -n if n < 0 else 0; td += dr; tc += cr
            body.append((f"{a.code or ''} · {a.name}", M(dr) if dr else '', M(cr) if cr else ''))
        _, _, _, obe = opening_totals()
        if abs(obe) > 0.005:
            if obe > 0: tc += obe; body.append(('3199 · Opening Balance Equity', '', M(obe)))
            else: td += -obe; body.append(('3199 · Opening Balance Equity', M(-obe), ''))
        return {'title': 'Trial Balance', 'plabel': plabel, 'kind': 'tb', 'tb': body,
                'td_disp': M(td), 'tc_disp': M(tc), 'chk': td - tc, 'chk_disp': M(td - tc)}

    if tab == 'bs':
        rows = [('sec', 'Assets', None, None)]
        for code, name, amt in sorted(G['asset_rows']):
            rows.append(('line', f'{code} · {name}', amt, M(amt)))
        rows.append(('tot', 'Total Assets', G['assets'], M(G['assets'])))
        rows.append(('sec', 'Liabilities', None, None))
        for code, name, amt in sorted(G['liab_rows']):
            rows.append(('line', f'{code} · {name}', amt, M(amt)))
        rows.append(('tot', 'Total Liabilities', G['liabilities'], M(G['liabilities'])))
        rows.append(('sec', 'Equity', None, None))
        for code, name, amt in sorted(G['equity_rows']):
            rows.append(('line', f'{code} · {name}', amt, M(amt)))
        rows.append(('line', 'Retained Earnings (period net income)', G['net_income'], M(G['net_income'])))
        rows.append(('tot', 'Total Equity', G['equity_with_ni'], M(G['equity_with_ni'])))
        rows.append(('grand', 'Liabilities + Equity', G['liabilities'] + G['equity_with_ni'],
                     M(G['liabilities'] + G['equity_with_ni'])))
        if abs(G['balances']) > 0.005:
            rows.append(('line', '⚠ Out of balance (A − (L+E))', G['balances'], M(G['balances'])))
        return {'title': 'Balance Sheet', 'plabel': plabel, 'kind': 'stmt', 'rows': rows}

    # default: P&L — Income and Expense account balances from the ledger
    rows = [('sec', 'Income', None, None)]
    for code, name, amt in sorted(G['income_rows']):
        rows.append(('line', f'{code} · {name}', amt, M(amt)))
    rows.append(('tot', 'Total Income', G['income'], M(G['income'])))
    rows.append(('sec', 'Expenses', None, None))
    for code, name, amt in sorted(G['expense_rows']):
        rows.append(('line', f'{code} · {name}', amt, M(amt)))
    rows.append(('tot', 'Total Expenses', G['expense'], M(G['expense'])))
    rows.append(('grand', 'NET PROFIT', G['net_income'], M(G['net_income'])))
    return {'title': 'Profit & Loss', 'plabel': plabel, 'kind': 'stmt', 'rows': rows}


@bp.route('/finance/report.pdf')
@login_required
def finance_report_pdf():
    if not can('finance'):
        abort(403)
    from flask import Response
    from ..core.pdfgen import financial_statement_pdf, available
    tab = request.args.get('tab', 'pnl')
    data = finance_report_rows(tab)
    if not available():
        flash('PDF engine is unavailable on this server — use Print instead.')
        return redirect(url_for('modules.module', mod='finance'))
    pdf = financial_statement_pdf(data, company=setting('company', 'Modern Diagnostic Center'),
                                  currency=setting('currency', '$'))
    fn = data['title'].replace(' ', '-').replace('&', 'and')
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + f';filename={fn}.pdf'
    log(f'Financial statement PDF: {data["title"]}')
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


# --------------------------------------------------------------- cash flow
CASH_CODES = ('1101', '1102', '1103')


def cashflow_view():
    """Monthly cash inflow/outflow from journal lines on cash & bank accounts."""
    y = cur_year()
    cash_ids = [a.id for a in Account.query.filter(Account.code.in_(CASH_CODES)).all()]
    lines = (JournalLine.query.join(JournalEntry)
             .filter(JournalLine.account_id.in_(cash_ids)).all()) if cash_ids else []
    months = {m: [0.0, 0.0] for m in range(1, 13)}   # in, out
    for l in lines:
        d = (l.entry.date or '') if l.entry else ''
        if not d.startswith(str(y)):
            continue
        try:
            m = int(d[5:7])
        except ValueError:
            continue
        months[m][0] += l.debit or 0
        months[m][1] += l.credit or 0
    opening = sum(a.opening or 0 for a in Account.query.filter(Account.code.in_(CASH_CODES)).all())
    rows = ''
    run = opening
    names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    tin = tout = 0.0
    for m in range(1, 13):
        i, o = months[m]
        net = i - o
        run += net
        tin += i; tout += o
        if i == 0 and o == 0:
            continue
        rows += (f"<tr><td>{names[m-1]} {y}</td><td class='num'>{money(i)}</td>"
                 f"<td class='num'>({money(o)})</td>"
                 f"<td class='num' style='font-weight:600;color:{'var(--green)' if net >= 0 else 'var(--red)'}'>{money(net)}</td>"
                 f"<td class='num'>{money(run)}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='5'><div class='empty'><b>No cash movement</b>Journal entries on cash/bank accounts appear here.</div></td></tr>"
    yrs = ''.join(f"<a class='btn sm{' primary' if yy == y else ''}' href='?year={yy}'>{yy}</a> "
                  for yy in range(dt.date.today().year - 2, dt.date.today().year + 1))
    body = f"""<div class="panel"><div class="ph"><h2>Cash Flow Statement · FY {y}</h2>
      <span class="so">accounts 1101 / 1102 / 1103 · opening {money(opening)}</span><div class="sp"></div>{yrs}
      <button class="btn sm" onclick="MDCDoc.openSelf('Cash Flow','{url_for('acct.cashflow_pdf')}?year={y}')">Print</button></div>
      <div class="tw"><table><thead><tr><th>Month</th><th class="num">Cash In</th><th class="num">Cash Out</th>
      <th class="num">Net</th><th class="num">Running Balance</th></tr></thead><tbody>{rows}</tbody></table></div>
      <div class="pad"><div class="stmt">
        <div class="r"><span>Total Inflow</span><span class="amt">{money(tin)}</span></div>
        <div class="r"><span>Total Outflow</span><span class="amt">({money(tout)})</span></div>
        <div class="r grand"><span>Closing Cash Position</span><span class="amt">{money(run)}</span></div>
      </div></div></div>"""
    return page('Cash Flow', body, 'cashflow')


# ------------------------------------------------------------ AR / AP aging
AGE_BUCKETS = [(0, 30, '0–30 days'), (31, 60, '31–60'), (61, 90, '61–90'), (91, 99999, '90+')]


def _age_days(iso):
    try:
        return (dt.date.today() - dt.date.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return 0


def _aging_table(items, who_label):
    """items: list of (who, date, ref, balance)."""
    buckets = [0.0] * len(AGE_BUCKETS)
    rows = ''
    for who, d, ref, bal in sorted(items, key=lambda x: x[1] or ''):
        age = _age_days(d)
        bidx = next(i for i, (lo, hi, _) in enumerate(AGE_BUCKETS) if lo <= age <= hi)
        buckets[bidx] += bal
        cls = 'green' if age <= 30 else ('amber' if age <= 60 else 'red')
        rows += (f"<tr><td>{h(who)}</td><td>{h(d)}</td><td>{ref}</td>"
                 f"<td class='num'>{age}</td><td><span class='pill {cls}'>{AGE_BUCKETS[bidx][2]}</span></td>"
                 f"<td class='num' style='font-weight:600'>{money(bal)}</td></tr>")
    if not rows:
        rows = f"<tr><td colspan='6'><div class='empty'><b>Nothing outstanding</b>All {who_label.lower()} balances are settled.</div></td></tr>"
    brow = ''.join(f"<div class='r'><span>{lbl}</span><span class='amt'>{money(buckets[i])}</span></div>"
                   for i, (_, _, lbl) in enumerate(AGE_BUCKETS))
    total = sum(buckets)
    return rows, brow, total


def araging_view():
    open_inv = [i for i in Invoice.query.all()
                if i.status != 'Cancelled' and i.balance > 0.005]
    items = [((plink(i.patient, i.patient.name if i.patient else 'Walk-in')), i.date, f'INV-{i.id:04d}', i.balance)
             for i in open_inv]
    rows, brow, total = _aging_table(items, 'Receivable')
    # who guarantees each open debt — the column you actually chase payment on
    gmap = {f'INV-{i.id:04d}': (i.guarantor or '') for i in open_inv}
    import re as _re
    def _add_guarantor(html):
        def sub(m):
            ref = m.group(1)
            g = gmap.get(ref, '')
            cell = (f"<td><b>{h(g)}</b></td>" if g
                    else "<td style='color:var(--muted)'>— patient —</td>")
            return m.group(0) + cell
        return _re.sub(r'<td>(INV-\d{4})</td>', sub, html)
    rows = _add_guarantor(rows)
    n_gua = sum(1 for v in gmap.values() if v)
    gua_total = sum(i.balance for i in open_inv if i.guarantor)
    body = f"""<div class="grid2"><div class="panel" style="grid-column:1/-1"><div class="ph">
      <h2>Accounts Receivable Aging</h2><span class="so">unpaid patient invoices by age</span>
      <div class="sp"></div><button class="btn sm" onclick="MDCDoc.openSelf('AR Aging','{url_for('acct.araging_pdf')}')">Print</button></div>
      <div class="tw"><table><thead><tr><th>Patient</th><th>Date</th><th>Invoice</th><th>Guarantor</th>
      <th class="num">Days</th><th>Bucket</th><th class="num">Balance</th></tr></thead><tbody>{rows}</tbody></table></div>
      <div class="pad" style="color:var(--muted);font-size:12.5px;border-top:1px solid var(--line)">
        {n_gua} of {len(open_inv)} open invoice(s) are guaranteed by a hospital, company or named person
        — {money(gua_total)} of {money(total)} outstanding.</div></div>
      <div class="panel"><div class="ph"><h2>By Bucket</h2></div><div class="pad"><div class="stmt">{brow}
      <div class="r grand"><span>Total Receivable</span><span class="amt">{money(total)}</span></div></div></div></div></div>"""
    return page('AR Aging', body, 'araging')


def apaging_view():
    items = []
    for p_ in Purchase.query.all():
        bal = (p_.total or 0) - (p_.paid or 0)
        if bal > 0.005:
            items.append(((p_.supplier.name if p_.supplier else (p_.item or '—')), p_.date,
                          f'PUR-{p_.id:04d}', bal))
    for e in Expense.query.all():
        bal = (e.amount or 0) - (e.paid or 0)
        if bal > 0.005:
            items.append((f'{e.category or "Expense"} · {(e.note or "")[:30]}', e.date,
                          f'EXP-{e.id:04d}', bal))
    rows, brow, total = _aging_table(items, 'Payable')
    body = f"""<div class="grid2"><div class="panel" style="grid-column:1/-1"><div class="ph">
      <h2>Accounts Payable Aging</h2><span class="so">unpaid purchases & expenses by age</span>
      <div class="sp"></div><button class="btn sm" onclick="MDCDoc.openSelf('AP Aging','{url_for('acct.apaging_pdf')}')">Print</button></div>
      <div class="tw"><table><thead><tr><th>Supplier / Item</th><th>Date</th><th>Ref</th>
      <th class="num">Days</th><th>Bucket</th><th class="num">Balance</th></tr></thead><tbody>{rows}</tbody></table></div></div>
      <div class="panel"><div class="ph"><h2>By Bucket</h2></div><div class="pad"><div class="stmt">{brow}
      <div class="r grand"><span>Total Payable</span><span class="amt">{money(total)}</span></div></div></div></div></div>"""
    return page('AP Aging', body, 'apaging')


# --------------------------------------------------------- bank reconciliation
def bankrecon_view():
    from ..models import BankAccount
    banks = BankAccount.query.filter_by(active=True).all()
    if not banks:
        body = f"""<div class="panel"><div class="pad"><div class="empty"><b>No bank accounts yet</b>
          Create one in <a href="{url_for('modules.module', mod='banks')}" style="color:var(--amber-dk);font-weight:600">Accounting → Bank Accounts</a>
          and link it to a COA cash account (1101/1102/1103).</div></div></div>"""
        return page('Bank Reconciliation', body, 'bankrecon')
    bid = request.args.get('bank', type=int) or banks[0].id
    bank = next((b for b in banks if b.id == bid), banks[0])
    stmt = request.args.get('stmt', type=float)
    lines = (JournalLine.query.join(JournalEntry)
             .filter(JournalLine.account_id == bank.account_id)
             .order_by(JournalEntry.date, JournalLine.id).all()) if bank.account_id else []
    ledger_bal = (bank.account.opening or 0) + sum((l.debit or 0) - (l.credit or 0) for l in lines) if bank.account else 0
    cleared_bal = (bank.account.opening or 0) + sum((l.debit or 0) - (l.credit or 0) for l in lines if l.cleared) if bank.account else 0
    tabs = ''.join(f"<a class='btn sm{' primary' if b.id == bank.id else ''}' href='?bank={b.id}'>{h(b.name)}</a> " for b in banks)
    rows = ''
    for l in lines:
        e = l.entry
        rows += (f"<tr{' style=opacity:.55' if l.cleared else ''}><td>{h(e.date if e else '—')}</td>"
                 f"<td>{h(e.ref if e else '—')}</td><td>{h((e.memo or '')[:48] if e else '')}</td>"
                 f"<td class='num'>{money(l.debit) if l.debit else ''}</td>"
                 f"<td class='num'>{money(l.credit) if l.credit else ''}</td>"
                 f"<td class='num'><input type='checkbox' name='clr_{l.id}' value='1'{' checked' if l.cleared else ''}></td></tr>")
    if not rows:
        rows = "<tr><td colspan='6'><div class='empty'><b>No transactions on this account</b></div></td></tr>"
    diff_html = ''
    if stmt is not None:
        diff = stmt - cleared_bal
        ok = abs(diff) < 0.005
        diff_html = (f"<div class='r'><span>Bank Statement Balance</span><span class='amt'>{money(stmt)}</span></div>"
                     f"<div class='r grand'><span>{'RECONCILED ✓' if ok else 'Difference'}</span>"
                     f"<span class='amt' style='color:{'var(--green)' if ok else 'var(--red)'}'>{money(diff)}</span></div>")
    body = f"""<div class="panel"><div class="ph"><h2>Bank Reconciliation · {h(bank.name)}</h2>
      <span class="so">{h(bank.bank_name or '')} {h(bank.number or '')}</span><div class="sp"></div>{tabs}</div>
      <div class="pad"><div class="grid2"><div class="stmt">
        <div class="r"><span>Ledger Balance ({h(bank.account.code if bank.account else '—')})</span><span class="amt">{money(ledger_bal)}</span></div>
        <div class="r tot"><span>Cleared Balance</span><span class="amt">{money(cleared_bal)}</span></div>{diff_html}
      </div>
      <form method="get" class="stmt"><input type="hidden" name="bank" value="{bank.id}">
        <div class="sec">Compare with Bank Statement</div>
        <div class="r"><span>Statement closing balance</span>
        <span><input name="stmt" type="number" step="any" value="{stmt if stmt is not None else ''}"
          style="border:1px solid var(--line);border-radius:8px;padding:6px 8px;width:130px"></span></div>
        <div class="fa"><button class="btn sm primary">Compare</button></div></form></div></div>
      <form method="post" action="{url_for('acct.bankrecon_save')}"><input type="hidden" name="bank" value="{bank.id}">
      <div class="tw"><table><thead><tr><th>Date</th><th>Ref</th><th>Memo</th>
      <th class="num">In</th><th class="num">Out</th><th class="num">Cleared</th></tr></thead><tbody>{rows}</tbody></table></div>
      <div class="pad"><div class="fa"><button class="btn primary">Save Cleared Marks</button></div></div></form></div>"""
    return page('Bank Reconciliation', body, 'bankrecon')


@bp.route('/bankrecon/save', methods=['POST'])
@login_required
def bankrecon_save():
    from ..models import BankAccount
    if not can('bankrecon'): abort(403)
    bank = BankAccount.query.get_or_404(int(request.form['bank']))
    lines = (JournalLine.query.filter_by(account_id=bank.account_id).all()) if bank.account_id else []
    n = 0
    for l in lines:
        new = bool(request.form.get(f'clr_{l.id}'))
        if bool(l.cleared) != new:
            l.cleared = new; n += 1
    db.session.commit()
    log(f'Bank reconciliation {bank.name}: {n} line(s) updated')
    flash(f'{n} line(s) updated')
    return redirect(url_for('modules.module', mod='bankrecon') + f'?bank={bank.id}')


# --------------------------------------------------------- budget vs actual
def budgetreport_view():
    from ..models import Budget
    y = cur_year()
    budgets = Budget.query.filter_by(year=y).all()
    actual = {}
    for l in JournalLine.query.join(JournalEntry).filter(JournalEntry.date.like(f'{y}%')).all():
        a = l.account
        if not a: continue
        v = (l.credit or 0) - (l.debit or 0) if a.type == 'Income' else (l.debit or 0) - (l.credit or 0)
        actual[a.id] = actual.get(a.id, 0.0) + v
    rows = ''; tb = ta = 0.0
    for b in sorted(budgets, key=lambda x: x.account.code if x.account else ''):
        act = actual.get(b.account_id, 0.0)
        pct = (act / b.amount * 100) if b.amount else 0
        tb += b.amount or 0; ta += act
        cls = 'green' if pct <= 90 else ('amber' if pct <= 105 else 'red')
        if b.account and b.account.type == 'Income':
            cls = 'green' if pct >= 90 else ('amber' if pct >= 60 else 'red')
        barw = min(int(pct), 100)
        rows += (f"<tr><td>{h(f'{b.account.code} · {b.account.name}' if b.account else '—')}</td>"
                 f"<td>{pill(b.account.type if b.account else '—','blue')}</td>"
                 f"<td class='num'>{money(b.amount)}</td><td class='num'>{money(act)}</td>"
                 f"<td class='num'>{money((b.amount or 0) - act)}</td>"
                 f"<td style='min-width:130px'><div style='background:var(--line);border-radius:6px;height:9px'>"
                 f"<div style='width:{barw}%;height:9px;border-radius:6px;background:var(--{ 'green' if cls=='green' else ('amber' if cls=='amber' else 'red')})'></div></div></td>"
                 f"<td><span class='pill {cls}'>{pct:.0f}%</span></td></tr>")
    if not rows:
        rows = (f"<tr><td colspan='7'><div class='empty'><b>No budgets for {y}</b>"
                f"Create them in <a href='{url_for('modules.module', mod='budgets')}' style='color:var(--amber-dk);font-weight:600'>Budgets</a>.</div></td></tr>")
    yrs = ''.join(f"<a class='btn sm{' primary' if yy == y else ''}' href='?year={yy}'>{yy}</a> "
                  for yy in range(dt.date.today().year - 2, dt.date.today().year + 2))
    body = f"""<div class="panel"><div class="ph"><h2>Budget vs Actual · FY {y}</h2>
      <span class="so">actuals from the General Ledger</span><div class="sp"></div>{yrs}
      <a class="btn sm" href="/export/xlsx/budget?year={y}">Excel</a></div>
      <div class="tw"><table><thead><tr><th>Account</th><th>Type</th><th class="num">Budget</th>
      <th class="num">Actual</th><th class="num">Remaining</th><th>Utilisation</th><th></th></tr></thead>
      <tbody>{rows}</tbody></table></div>
      <div class="pad"><div class="stmt"><div class="r grand"><span>Total Budget / Actual</span>
      <span class="amt">{money(tb)} / {money(ta)}</span></div></div></div></div>"""
    return page('Budget vs Actual', body, 'budgetreport')


# ----------------------------------------------------------- cost center report
def ccreport_view():
    from ..models import CostCenter
    y = cur_year()
    ccs = CostCenter.query.order_by(CostCenter.code).all()
    exps = [e for e in Expense.query.all() if (e.date or '').startswith(str(y))]
    rows = ''; tot = 0.0
    untagged = sum(e.amount or 0 for e in exps if not e.cost_center_id)
    for c in ccs:
        amt = sum(e.amount or 0 for e in exps if e.cost_center_id == c.id)
        n = sum(1 for e in exps if e.cost_center_id == c.id)
        tot += amt
        rows += (f"<tr><td><b>{h(c.code or '')}</b></td><td>{h(c.name)}</td>"
                 f"<td class='num'>{n}</td><td class='num' style='font-weight:600'>{money(amt)}</td></tr>")
    if untagged:
        rows += (f"<tr style='color:var(--muted)'><td>—</td><td>Untagged expenses</td>"
                 f"<td class='num'>{sum(1 for e in exps if not e.cost_center_id)}</td>"
                 f"<td class='num'>{money(untagged)}</td></tr>")
        tot += untagged
    if not rows:
        rows = (f"<tr><td colspan='4'><div class='empty'><b>No cost centers</b>"
                f"Create them in <a href='{url_for('modules.module', mod='costcenters')}' style='color:var(--amber-dk);font-weight:600'>Cost Centers</a> "
                "then tag each expense.</div></td></tr>")
    yrs = ''.join(f"<a class='btn sm{' primary' if yy == y else ''}' href='?year={yy}'>{yy}</a> "
                  for yy in range(dt.date.today().year - 2, dt.date.today().year + 1))
    body = f"""<div class="panel"><div class="ph"><h2>Cost Center Report · FY {y}</h2>
      <span class="so">expense allocation by department/center</span><div class="sp"></div>{yrs}</div>
      <div class="tw"><table><thead><tr><th>Code</th><th>Cost Center</th><th class="num">Expenses</th>
      <th class="num">Total</th></tr></thead><tbody>{rows}</tbody></table></div>
      <div class="pad"><div class="stmt"><div class="r grand"><span>Total Expenses FY {y}</span>
      <span class="amt">{money(tot)}</span></div></div></div></div>"""
    return page('Cost Center Report', body, 'ccreport')


# ------------------------------------------------------------ financial ratios
def _fx_line(amount):
    """Optional multi-currency display: '≈ 26,500,000 SOS @ 26500' per active currency."""
    from ..models import Currency
    cur = setting('currency', 'USD')
    parts = []
    for c in Currency.query.filter_by(active=True).all():
        if c.code == cur or not c.rate:
            continue
        parts.append(f"≈ {amount * c.rate:,.0f} {h(c.code)}")
    return f"<div style='color:var(--muted);font-size:12px;margin-top:2px'>{' · '.join(parts)}</div>" if parts else ''


def ratios_view():
    y = cur_year(); yr = str(y)
    invs = [i for i in live_invoices() if (i.date or '').startswith(yr)]
    revenue = sum(i.total for i in invs)
    collected = sum(min(i.paid or 0, i.total) for i in invs)
    ar = sum(max(i.balance, 0) for i in Invoice.query.all() if i.status != 'Cancelled')
    exps = sum(e.amount or 0 for e in Expense.query.all() if (e.date or '').startswith(yr))
    cash_ids = [a.id for a in Account.query.filter(Account.code.in_(CASH_CODES)).all()]
    cash = sum(a.opening or 0 for a in Account.query.filter(Account.code.in_(CASH_CODES)).all())
    for l in JournalLine.query.filter(JournalLine.account_id.in_(cash_ids)).all() if cash_ids else []:
        cash += (l.debit or 0) - (l.credit or 0)
    inv_val = sum((m.qty or 0) * (m.cost or 0) for m in Medicine.query.all())
    ap = sum(max((p.total or 0) - (p.paid or 0), 0) for p in Purchase.query.all()) +          sum(max((e.amount or 0) - (e.paid or 0), 0) for e in Expense.query.all())
    net = revenue - exps
    cl = ap or 1e-9
    ratios = [
        ('Current Ratio', (cash + ar + inv_val) / cl if ap else None, 'x',
         'Current assets ÷ current liabilities · healthy ≥ 1.5'),
        ('Quick Ratio', (cash + ar) / cl if ap else None, 'x',
         'Excluding inventory · healthy ≥ 1.0'),
        ('Net Margin', (net / revenue * 100) if revenue else None, '%',
         'Net income ÷ revenue'),
        ('Collection Rate', (collected / revenue * 100) if revenue else None, '%',
         'Collected ÷ billed this year · target ≥ 90%'),
        ('AR Days (DSO)', (ar / (revenue / 365)) if revenue else None, 'd',
         'Average days to collect receivables'),
        ('Expense Ratio', (exps / revenue * 100) if revenue else None, '%',
         'Operating expenses ÷ revenue'),
    ]
    cards = ''
    for name, val, unit, expl in ratios:
        disp = '—' if val is None else (f'{val:,.2f}×' if unit == 'x' else (f'{val:,.1f}%' if unit == '%' else f'{val:,.0f} days'))
        cards += (f"<div class='kpi' style='--ac:var(--teal)'><div class='l'>{name}</div>"
                  f"<div class='v'>{disp}</div><div class='s'>{expl}</div></div>")
    body = f"""<div class="kpis">{cards}</div>
      <div class="grid2">
      <div class="panel"><div class="ph"><h2>Position · FY {y}</h2></div><div class="pad"><div class="stmt">
        <div class="r"><span>Cash & Bank</span><span class="amt">{money(cash)}</span></div>
        <div class="r"><span>Accounts Receivable</span><span class="amt">{money(ar)}</span></div>
        <div class="r"><span>Inventory Value</span><span class="amt">{money(inv_val)}</span></div>
        <div class="r"><span>Accounts Payable</span><span class="amt">({money(ap)})</span></div>
        <div class="r grand"><span>Working Capital</span><span class="amt">{money(cash + ar + inv_val - ap)}</span></div>
        {_fx_line(cash + ar + inv_val - ap)}
      </div></div></div>
      <div class="panel"><div class="ph"><h2>Performance · FY {y}</h2></div><div class="pad"><div class="stmt">
        <div class="r"><span>Revenue (accrual — recognised at invoicing)</span><span class="amt">{money(revenue)}</span></div>
        <div class="r"><span>Collected</span><span class="amt">{money(collected)}</span></div>
        <div class="r"><span>Operating Expenses</span><span class="amt">({money(exps)})</span></div>
        <div class="r grand"><span>Net Income</span><span class="amt" style="color:{'var(--green)' if net >= 0 else 'var(--red)'}">{money(net)}</span></div>
        {_fx_line(net)}
      </div></div></div></div>
      <div class="panel"><div class="ph"><h2>Downloads</h2></div><div class="pad" style="display:flex;gap:8px;flex-wrap:wrap">
        <a class="btn sm" href="/finance/pdf?year={y}" target="_blank">📄 Financial Statements PDF</a>
        <a class="btn sm" href="/export/xlsx/trialbalance?year={y}">Trial Balance (Excel)</a>
        <a class="btn sm" href="/export/xlsx/ledger?year={y}">General Ledger (Excel)</a>
        <a class="btn sm" href="/export/xlsx/araging">AR Aging (Excel)</a>
        <a class="btn sm" href="/export/xlsx/apaging">AP Aging (Excel)</a>
        <div style="width:100%;height:6px"></div>
        <a class="btn sm" href="/export/csv/trialbalance?year={y}">Trial Balance (CSV)</a>
        <a class="btn sm" href="/export/csv/ledger?year={y}">General Ledger (CSV)</a>
        <a class="btn sm" href="/export/csv/araging">AR Aging (CSV)</a>
        <a class="btn sm" href="/export/csv/invoices">All Invoices (CSV)</a>
      </div></div>"""
    return page('Financial Ratios', body, 'ratios')


# ---------------------------------------------------- fiscal periods & closing
def fiscal_view():
    from ..models import FiscalPeriod
    y = cur_year()
    names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    cells = ''
    closed_n = 0
    _audit_rows = ''
    for m in range(1, 13):
        fp = FiscalPeriod.query.filter_by(year=y, month=m).first()
        closed = fp and fp.status == 'Closed'
        closed_n += 1 if closed else 0
        if closed:
            # reopening is the sensitive action → prompt for a reason
            _oc = ("var r=prompt('Reason to REOPEN this closed period?'); if(!r)return false; "
                   "this.href=this.href.split('?')[0]+'?reason='+encodeURIComponent(r); return true;")
            _tip = f"Closed by {h(fp.closed_by or '—')} {h(fp.closed_at or '')}" if fp else ''
        else:
            _oc = f"return confirm('Close {names[m-1]} {y}? Postings into this month will be blocked.')"
            _tip = 'Open'
        cells += (f"<a href='/fiscal/toggle/{y}/{m}' class='btn sm{'' if closed else ' primary'}' "
                  f"onclick=\"{_oc}\" title=\"{_tip}\" style='min-width:86px;text-align:center'>"
                  f"{names[m-1]} · {'🔒 Closed' if closed else 'Open'}</a>")
        if fp and (fp.closed_by or fp.reopened_by):
            _a = f"Closed by {h(fp.closed_by or '—')} on {h(fp.closed_at or '—')}"
            if fp.reopened_by:
                _a += f" · Reopened by {h(fp.reopened_by)} on {h(fp.reopened_at or '—')} — reason: {h(fp.reopen_reason or '—')}"
            _audit_rows += f"<tr><td><b>{names[m-1]} {y}</b></td><td>{_a}</td></tr>"
    yrs = ''.join(f"<a class='btn sm{' primary' if yy == y else ''}' href='?year={yy}'>{yy}</a> "
                  for yy in range(dt.date.today().year - 2, dt.date.today().year + 1))
    cls_done = bool(JournalEntry.query.filter_by(ref=f'CLS-{y}').first())
    body = f"""<div class="panel"><div class="ph"><h2>Fiscal Periods · FY {y}</h2>
      <span class="so">postings into a Closed month are blocked system-wide</span><div class="sp"></div>{yrs}</div>
      <div class="pad" style="display:flex;gap:8px;flex-wrap:wrap">{cells}</div></div>
      {f'<div class="panel"><div class="ph"><h2>Period Close / Reopen Log</h2><span class="so">who closed or reopened each month, and why</span></div><div class="tw"><table><thead><tr><th>Period</th><th>Audit</th></tr></thead><tbody>{_audit_rows}</tbody></table></div></div>' if _audit_rows else ''}
      <div class="panel"><div class="ph"><h2>Year-End Closing</h2></div><div class="pad">
      <p style="color:var(--muted);font-size:13.5px;max-width:640px">Closing FY {y} posts entry <b>CLS-{y}</b>
      (net income → 3200 Retained Earnings) and locks all 12 months. Depreciation should be run first.
      {('<b style=color:var(--green)>Already closed.</b>' if cls_done else '')}</p>
      <div class="fa"><a class="btn sm" href="/depreciation/run?year={y}"
        onclick="return confirm('Post straight-line depreciation for {y}?')">1 · Run Depreciation {y}</a>
      <a class="btn sm primary" href="/fiscal/closeyear/{y}"
        onclick="return confirm('Close fiscal year {y}? All 12 months will be locked.')">2 · Close Fiscal Year {y}</a></div></div></div>"""
    return page('Fiscal Periods', body, 'fiscal')


@bp.route('/fiscal/toggle/<int:y>/<int:m>', methods=['GET', 'POST'])
@login_required
def fiscal_toggle(y, m):
    from ..models import FiscalPeriod
    if not can('fiscal'): abort(403)
    fp = FiscalPeriod.query.filter_by(year=y, month=m).first()
    if not fp:
        fp = FiscalPeriod(year=y, month=m, status='Open')
        db.session.add(fp)
    _u = cur_user()
    _who = (_u.name or _u.username) if _u else 'system'
    _now = f'{today()} {dt.datetime.now().strftime("%H:%M")}'
    if fp.status == 'Closed':
        # REOPEN — this is the sensitive action: require a reason and audit it.
        reason = (request.values.get('reason') or '').strip()
        if not reason:
            flash('A reason is required to reopen a closed fiscal period.')
            return redirect(url_for('modules.module', mod='fiscal') + f'?year={y}')
        fp.status = 'Open'
        fp.reopened_by = _who; fp.reopened_at = _now; fp.reopen_reason = reason[:200]
        db.session.commit()
        log(f'Fiscal period {y}-{m:02d} REOPENED by {_who} · reason: {reason}',
            action_type='Fiscal Reopen', entity=f'FP-{y}-{m:02d}', old='Closed', new='Open', reason=reason)
        flash(f'{y}-{m:02d} reopened — recorded for audit.')
    else:
        # CLOSE
        fp.status = 'Closed'
        fp.closed_by = _who; fp.closed_at = _now
        db.session.commit()
        log(f'Fiscal period {y}-{m:02d} CLOSED by {_who}',
            action_type='Fiscal Close', entity=f'FP-{y}-{m:02d}', old='Open', new='Closed')
        flash(f'{y}-{m:02d} closed — postings into this month are now blocked.')
    return redirect(url_for('modules.module', mod='fiscal') + f'?year={y}')


@bp.route('/fiscal/closeyear/<int:y>')
@login_required
def fiscal_closeyear(y):
    from ..core.posting import close_fiscal_year
    if not can('fiscal'): abort(403)
    net = close_fiscal_year(y)
    log(f'Fiscal year {y} closed · net {money(net)} to Retained Earnings')
    flash(f'FY {y} closed — net {money(net)} moved to Retained Earnings')
    return redirect(url_for('modules.module', mod='fiscal') + f'?year={y}')


@bp.route('/depreciation/run')
@login_required
def depreciation_run():
    from ..core.posting import run_depreciation
    if not can('fiscal') and not can('acct'): abort(403)
    y = request.args.get('year', type=int) or dt.date.today().year
    total = run_depreciation(y)
    log(f'Depreciation posted for {y}: {money(total)} (DEP-{y})')
    flash(f'Depreciation {y}: {money(total)} posted (DEP-{y})')
    return redirect(request.referrer or url_for('modules.module', mod='genledger'))


# ------------------------------------------------------------------ tax report
def taxreport_view():
    y = cur_year()
    names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    months = {m: 0.0 for m in range(1, 13)}
    for i in Invoice.query.all():
        if i.status == 'Cancelled' or not (i.date or '').startswith(str(y)):
            continue
        try:
            months[int(i.date[5:7])] += i.vat or 0
        except (ValueError, IndexError):
            pass
    rows = ''; tot = 0.0
    for m in range(1, 13):
        if not months[m]:
            continue
        tot += months[m]
        rows += f"<tr><td>{names[m-1]} {y}</td><td class='num'>{money(months[m])}</td></tr>"
    if not rows:
        rows = ("<tr><td colspan='2'><div class='empty'><b>No VAT collected</b>"
                "Add VAT amounts on invoices; they post to 2400 VAT Payable.</div></td></tr>")
    yrs = ''.join(f"<a class='btn sm{' primary' if yy == y else ''}' href='?year={yy}'>{yy}</a> "
                  for yy in range(dt.date.today().year - 2, dt.date.today().year + 1))
    body = f"""<div class="panel"><div class="ph"><h2>Tax Report (VAT) · FY {y}</h2>
      <span class="so">VAT charged on invoices → account 2400 VAT Payable</span><div class="sp"></div>{yrs}</div>
      <div class="tw"><table><thead><tr><th>Month</th><th class="num">VAT Collected</th></tr></thead>
      <tbody>{rows}</tbody></table></div>
      <div class="pad"><div class="stmt"><div class="r grand"><span>Total VAT Payable FY {y}</span>
      <span class="amt">{money(tot)}</span></div></div></div></div>"""
    return page('Tax Report', body, 'taxreport')


@bp.route('/journal/<int:eid>/reverse', methods=['GET', 'POST'])
@login_required
def journal_reverse(eid):
    if not can('journal'): abort(403)
    e = JournalEntry.query.get_or_404(eid)
    if e.reversed_by or e.is_reversal:
        flash('Already reversed or is itself a reversal'); return redirect(url_for('modules.module', mod='journal'))
    if not _period_open(e.date):
        flash('Period closed — reopen it in Fiscal Periods first'); return redirect(url_for('modules.module', mod='journal'))
    # A correction must state WHY. Reason comes from the confirm prompt (GET ?reason=)
    # or a POST field; without it we refuse, so every reversal is accountable.
    reason = (request.values.get('reason') or '').strip()
    if not reason:
        flash('A reason is required to reverse a posted journal entry.')
        return redirect(url_for('modules.module', mod='journal'))
    _u = cur_user()
    _who = (_u.name or _u.username) if _u else 'system'
    _now = f'{today()} {dt.datetime.now().strftime("%H:%M")}'
    rev = JournalEntry(date=today(), ref=f'REV-{e.ref or e.id}',
                       memo=(f'Reversal of {e.ref or ("JV-%04d" % e.id)}: {reason}')[:200],
                       is_reversal=True, reverses_id=e.id, posted_by=_who)
    db.session.add(rev); db.session.commit()
    for l in e.lines:                       # swap debit/credit
        db.session.add(JournalLine(entry_id=rev.id, account_id=l.account_id,
                                   debit=l.credit or 0, credit=l.debit or 0))
    # record the audit trail on the original
    e.reversed_by = rev.id
    e.reversed_at = _now
    e.reversed_by_user = _who
    e.reversal_reason = reason[:200]
    db.session.commit()
    log(f'Journal {eid} ({e.ref}) reversed by entry {rev.id} · by {_who} · reason: {reason}',
        action_type='Journal Reversal', entity=f'JE-{eid}',
        old=f'{e.ref} (posted)', new=f'REV-{e.ref or e.id}', reason=reason)
    flash(f'Reversing entry REV-{e.ref or e.id} posted — original preserved for audit.')
    return redirect(url_for('modules.module', mod='journal'))


@bp.route('/recurring/run')
@login_required
def recurring_run():
    if not can('journal'): abort(403)
    from ..models import RecurringJournal
    ym = today()[:7]
    n = 0
    for r in RecurringJournal.query.filter_by(active=True).all():
        if (r.last_run or '')[:7] == ym:      # already posted this month
            continue
        if not r.amount or not r.dr_account or not r.cr_account:
            continue
        d = f'{ym}-{min(r.day or 1, 28):02d}'
        if not _period_open(d):
            continue
        da = Account.query.filter_by(code=r.dr_account).first()
        ca = Account.query.filter_by(code=r.cr_account).first()
        if not (da and ca):
            continue
        e = JournalEntry(date=d, ref=f'REC-{r.id}-{ym}', memo=r.memo or 'Recurring journal')
        db.session.add(e); db.session.commit()
        db.session.add(JournalLine(entry_id=e.id, account_id=da.id, debit=r.amount, credit=0))
        db.session.add(JournalLine(entry_id=e.id, account_id=ca.id, debit=0, credit=r.amount))
        r.last_run = d
        db.session.commit(); n += 1
    log(f'Recurring journals run: {n} posted')
    flash(f'{n} recurring journal(s) posted for {ym}')
    return redirect(url_for('modules.module', mod='recurjournals'))


@bp.route('/cash/transfer', methods=['GET', 'POST'])
@login_required
def cash_transfer():
    """Petty cash top-up / bank transfer — a guided cash↔bank journal."""
    if not can('journal'): abort(403)
    from ..core.posting import post_journal, acc_ensure
    accts = [a for a in Account.query.order_by(Account.code).all()
             if a.code and (a.code.startswith('11') or a.code == '1104')]
    if request.method == 'POST':
        d = request.form.get('date') or today()
        if not _period_open(d):
            flash('Period closed'); return redirect(url_for('acct.cash_transfer'))
        frm = request.form.get('from_code'); to = request.form.get('to_code')
        amt = float(request.form.get('amount') or 0)
        if not (frm and to and amt > 0 and frm != to):
            flash('Choose two different accounts and a positive amount')
            return redirect(url_for('acct.cash_transfer'))
        fa = acc(frm); ta = acc(to)
        post_journal(d, f'XFER-{dt.datetime.now().strftime("%H%M%S")}',
                     f'Cash/bank transfer: {fa.name} → {ta.name}',
                     [(to, amt, 0), (frm, 0, amt)])
        log(f'Cash transfer {money(amt)} {frm}->{to}')
        flash(f'Transferred {money(amt)}'); return redirect(url_for('modules.module', mod='journal'))
    # ensure a petty cash account exists to offer
    if not acc('1104'):
        acc_ensure('1104', 'Petty Cash', 'Asset', '1000'); db.session.commit()
        accts = [a for a in Account.query.order_by(Account.code).all()
                 if a.code and (a.code.startswith('11') or a.code == '1104')]
    opts = ''.join(f"<option value='{a.code}'>{h(a.code)} · {h(a.name)}</option>" for a in accts)
    body = f"""<div class='panel'><div class='ph'><h2>Cash / Bank Transfer · Petty Cash</h2>
      <div class='sp'></div><a class='btn sm' href='{url_for('modules.module', mod='journal')}'>← Journal</a></div>
      <div class='pad'><form method='post'><div class='fg'>
        <div class='fld'><label>Date</label><input name='date' type='date' value='{today()}'></div>
        <div class='fld'><label>Amount</label><input name='amount' type='number' step='any' required></div>
        <div class='fld'><label>From</label><select name='from_code'>{opts}</select></div>
        <div class='fld'><label>To</label><select name='to_code'>{opts}</select></div>
        <div class='fld full'><button class='btn primary'>Post Transfer</button></div>
      </div></form>
      <p style='color:var(--muted);font-size:12.5px'>Tusaale: Bank → Petty Cash (buuxi sanduuqa), ama Cash → Bank (dhig bangiga). Double-entry ayaa si toos ah loo qoraa.</p>
      </div></div>"""
    return page('Cash Transfer', body, 'journal')


def revreport_view():
    """Revenue by department/service + expense analysis (this month)."""
    month = request.args.get('m') or today()[:7]
    invs = [i for i in Invoice.query.filter(Invoice.date.like(month + '%')).all()
            if i.status != 'Cancelled']
    rev_dep = {}
    rev_svc = {}
    for i in invs:
        for it in i.items:
            svc = Service.query.get(it.service_id) if it.service_id else None
            dep = (svc.department if svc else None) or 'Other'
            amt = (it.qty or 0) * (it.price or 0)
            rev_dep[dep] = rev_dep.get(dep, 0) + amt
            key = svc.name if svc else (it.desc or 'Other')
            rev_svc[key] = rev_svc.get(key, 0) + amt
    exps = Expense.query.filter(Expense.date.like(month + '%')).all()
    exp_cat = {}
    for e in exps:
        exp_cat[e.category or 'Other'] = exp_cat.get(e.category or 'Other', 0) + (e.amount or 0)
    tot_rev = sum(rev_dep.values()); tot_exp = sum(exp_cat.values())

    def tbl(title, d, tot):
        rows = ''.join(f"<tr><td>{h(k)}</td><td class='num'>{money(v)}</td>"
                       f"<td class='num' style='color:var(--muted)'>{(v/tot*100 if tot else 0):.0f}%</td></tr>"
                       for k, v in sorted(d.items(), key=lambda x: -x[1])) or \
               "<tr><td colspan='3' style='color:var(--muted);padding:12px'>None.</td></tr>"
        return (f"<div class='panel'><div class='ph'><h2>{title}</h2></div><div class='tw'><table>"
                f"<thead><tr><th>Item</th><th class='num'>Amount</th><th class='num'>%</th></tr></thead>"
                f"<tbody>{rows}<tr style='font-weight:700;background:var(--canvas)'><td>Total</td>"
                f"<td class='num'>{money(tot)}</td><td></td></tr></tbody></table></div></div>")
    k = lambda n, v, c: (f"<div class='panel' style='flex:1;min-width:150px'><div class='pad'>"
        f"<div style='font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase'>{n}</div>"
        f"<div style='font-family:Space Grotesk;font-weight:700;font-size:24px;color:{c}'>{money(v)}</div></div></div>")
    picker = (f"<div class='panel'><div class='pad'><form method='get' style='display:flex;gap:8px;align-items:center'>"
              f"<label style='font-size:13px;color:var(--muted)'>Month</label>"
              f"<input type='month' name='m' value='{h(month)}' style='border:1px solid var(--line);border-radius:8px;padding:6px 10px'>"
              f"<button class='btn sm'>View</button> <button class='btn sm' type='button' onclick=\"MDCDoc.openSelf('Revenue &amp; Expense Analysis','{url_for('acct.revreport_pdf')}?m={h(month)}')\">Print</button></form></div></div>")
    kpis = (f"<div style='display:flex;gap:12px;flex-wrap:wrap'>{k('Revenue', tot_rev, 'var(--green)')}"
            f"{k('Expenses', tot_exp, 'var(--red)')}{k('Net', tot_rev - tot_exp, 'var(--petrol)')}</div>")
    return page('Revenue & Expense Analysis',
                kpis + picker + tbl('Revenue by Department', rev_dep, tot_rev)
                + tbl('Revenue by Service', rev_svc, tot_rev)
                + tbl('Expense by Category', exp_cat, tot_exp), 'revreport')


@bp.route('/revreport/pdf')
@login_required
def revreport_pdf():
    from flask import Response
    from ..core.pdfgen import financial_statement_pdf, available
    month = request.args.get('m') or today()[:7]
    invs = [i for i in Invoice.query.filter(Invoice.date.like(month + '%')).all() if i.status != 'Cancelled']
    rev_dep = {}; rev_svc = {}
    for i in invs:
        for it in i.items:
            svc = Service.query.get(it.service_id) if it.service_id else None
            dep = (svc.department if svc else None) or 'Other'
            amt = (it.qty or 0) * (it.price or 0)
            rev_dep[dep] = rev_dep.get(dep, 0) + amt
            key = svc.name if svc else (it.desc or 'Other'); rev_svc[key] = rev_svc.get(key, 0) + amt
    exp_cat = {}
    for e in Expense.query.filter(Expense.date.like(month + '%')).all():
        exp_cat[e.category or 'Other'] = exp_cat.get(e.category or 'Other', 0) + (e.amount or 0)
    tot_rev = sum(rev_dep.values()); tot_exp = sum(exp_cat.values())
    rows = [('sec', 'Revenue by Department', None, None)]
    for k, v in sorted(rev_dep.items(), key=lambda x: -x[1]):
        rows.append(('line', k, v, money(v)))
    rows.append(('tot', 'Total Revenue', tot_rev, money(tot_rev)))
    rows.append(('sec', 'Revenue by Service', None, None))
    for k, v in sorted(rev_svc.items(), key=lambda x: -x[1]):
        rows.append(('line', k, v, money(v)))
    rows.append(('sec', 'Expenses by Category', None, None))
    for k, v in sorted(exp_cat.items(), key=lambda x: -x[1]):
        rows.append(('line', k, v, money(v)))
    rows.append(('tot', 'Total Expenses', tot_exp, money(tot_exp)))
    rows.append(('grand', 'NET', tot_rev - tot_exp, money(tot_rev - tot_exp)))
    if not available():
        return redirect(url_for('modules.module', mod='revreport') + f'?m={month}')
    data = {'title': 'Revenue & Expense Analysis', 'plabel': f'Month {month}', 'kind': 'stmt', 'rows': rows}
    pdf = financial_statement_pdf(data, company=setting('company', 'Modern Diagnostic Center'), currency=setting('currency', '$'))
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + ';filename=Revenue-Expense-Analysis.pdf'
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


@bp.route('/cashflow/pdf')
@login_required
def cashflow_pdf():
    from flask import Response
    from ..core.pdfgen import ledger_pdf, available
    y = request.args.get('year', type=int) or cur_year()
    cash_ids = [a.id for a in Account.query.filter(Account.code.in_(CASH_CODES)).all()]
    lines = JournalLine.query.filter(JournalLine.account_id.in_(cash_ids)).all() if cash_ids else []
    months = {m: [0.0, 0.0] for m in range(1, 13)}
    for l in lines:
        d = l.entry.date if l.entry else ''
        if not (d or '').startswith(str(y)):
            continue
        try:
            mo = int(d[5:7])
        except Exception:
            continue
        months[mo][0] += l.debit or 0; months[mo][1] += l.credit or 0
    opening = sum(a.opening or 0 for a in Account.query.filter(Account.code.in_(CASH_CODES)).all())
    names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    rows = []; run = opening; ti = to = 0.0
    for m in range(1, 13):
        i, o = months[m]; net = i - o; run += net; ti += i; to += o
        rows.append([f'{names[m-1]} {y}', money(i), f'({money(o)})', money(net), money(run)])
    cols = [('Month', 'l', 30), ('Cash In', 'r', 28), ('Cash Out', 'r', 28), ('Net', 'r', 28), ('Running Balance', 'r', 32)]
    totals = ['TOTAL', money(ti), f'({money(to)})', money(ti - to), money(run)]
    if not available():
        return redirect(url_for('modules.module', mod='cashflow') + f'?year={y}')
    pdf = ledger_pdf(f'Cash Flow - {y}', f'Opening cash {money(opening)}', cols, rows, totals,
                     company=setting('company', 'Modern Diagnostic Center'), currency=setting('currency', '$'))
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + ';filename=Cash-Flow.pdf'
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


def _aging_pdf(items, title, fn):
    from flask import Response
    from ..core.pdfgen import ledger_pdf, available
    rows = []; total = 0.0
    for who, d, ref, bal in sorted(items, key=lambda x: x[1] or ''):
        age = _age_days(d)
        bidx = next(i for i, (lo, hi, _) in enumerate(AGE_BUCKETS) if lo <= age <= hi)
        total += bal
        rows.append([str(who), d or '', str(ref), str(age), AGE_BUCKETS[bidx][2], money(bal)])
    cols = [('Name', 'l', 46), ('Date', 'l', 22), ('Ref', 'l', 22), ('Days', 'r', 14), ('Bucket', 'l', 20), ('Balance', 'r', 26)]
    totals = ['TOTAL', '', '', '', '', money(total)]
    if not available():
        return None
    return ledger_pdf(title, f'{len(rows)} open item(s)', cols, rows, totals,
                      company=setting('company', 'Modern Diagnostic Center'), currency=setting('currency', '$')), fn


@bp.route('/araging/pdf')
@login_required
def araging_pdf():
    from flask import Response
    open_inv = [i for i in Invoice.query.all() if i.status != 'Cancelled' and i.balance > 0.005]
    items = [((i.patient.name if i.patient else 'Walk-in'), i.date, f'INV-{i.id:04d}', i.balance) for i in open_inv]
    res = _aging_pdf(items, 'AR Aging - Receivables', 'AR-Aging.pdf')
    if not res:
        return redirect(url_for('modules.module', mod='araging'))
    pdf, fn = res
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + f';filename={fn}'
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


@bp.route('/apaging/pdf')
@login_required
def apaging_pdf():
    from flask import Response
    items = []
    for p_ in Purchase.query.all():
        bal = (p_.total or 0) - (p_.paid or 0)
        if bal > 0.005:
            items.append(((p_.supplier.name if p_.supplier else (p_.item or '-')), p_.date, f'PO-{p_.id:04d}', bal))
    for e in Expense.query.all():
        bal = (e.amount or 0) - (getattr(e, 'paid', 0) or 0)
        if bal > 0.005:
            items.append((f'{e.category or "Expense"} - {(e.note or "")[:30]}', e.date, f'EXP-{e.id:04d}', bal))
    res = _aging_pdf(items, 'AP Aging - Payables', 'AP-Aging.pdf')
    if not res:
        return redirect(url_for('modules.module', mod='apaging'))
    pdf, fn = res
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + f';filename={fn}'
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


def findash_view():

    """Executive Financial Dashboard."""
    from ..core.posting import acc as _acc
    tdy = today(); ym = tdy[:7]
    inv_all = [i for i in Invoice.query.all() if i.status != 'Cancelled']
    rev_today = sum(i.total or 0 for i in inv_all if i.date == tdy)
    rev_month = sum(i.total or 0 for i in inv_all if (i.date or '').startswith(ym))
    exp_today = sum(e.amount or 0 for e in Expense.query.filter_by(date=tdy).all())
    exp_month = sum(e.amount or 0 for e in Expense.query.filter(Expense.date.like(ym + '%')).all())
    ar = sum(max(i.balance, 0) for i in inv_all)
    ap = sum(max((p.total or 0) - (p.paid or 0), 0) for p in Purchase.query.all()
             if (p.status or 'Received') == 'Received')

    def bal(code):
        a = _acc(code)
        if not a: return 0
        from ..core.posting import opening_dr
        net = opening_dr(a) + sum((l.debit or 0) - (l.credit or 0) for l in
                                  JournalLine.query.filter_by(account_id=a.id).all())
        return net
    cash = bal('1101') + bal('1104'); bank = bal('1102') + bal('1103')
    net_month = rev_month - exp_month
    # budget utilization (this year)
    from ..models import Budget
    byr = today()[:4]
    buds = Budget.query.filter(Budget.year == int(byr)).all() if hasattr(Budget, 'year') else []
    bud_tot = sum(b.amount or 0 for b in buds)
    bud_used = exp_month  # rough: month expense vs annual budget
    k = lambda n, v, c='var(--petrol)', money_=True: (
        f"<div class='panel' style='flex:1;min-width:160px'><div class='pad'>"
        f"<div style='font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase'>{n}</div>"
        f"<div style='font-family:Space Grotesk;font-weight:700;font-size:23px;color:{c}'>{money(v) if money_ else v}</div></div></div>")
    row1 = (f"<div style='display:flex;gap:12px;flex-wrap:wrap'>"
            f"{k('Revenue Today', rev_today, 'var(--green)')}{k('Revenue Month', rev_month, 'var(--green)')}"
            f"{k('Expenses Today', exp_today, 'var(--red)')}{k('Expenses Month', exp_month, 'var(--red)')}</div>")
    row2 = (f"<div style='display:flex;gap:12px;flex-wrap:wrap'>"
            f"{k('Net Profit (Month)', net_month, 'var(--green)' if net_month >= 0 else 'var(--red)')}"
            f"{k('Cash Balance', cash)}{k('Bank Balance', bank)}</div>")
    row3 = (f"<div style='display:flex;gap:12px;flex-wrap:wrap'>"
            f"{k('Receivables (AR)', ar, 'var(--amber)')}{k('Payables (AP)', ap, 'var(--amber)')}"
            f"{k('Annual Budget', bud_tot)}</div>")
    links = (f"<div class='panel'><div class='pad' style='display:flex;gap:10px;flex-wrap:wrap'>"
             f"<a class='btn' href='{url_for('modules.module', mod='finance')}'>Financial Statements</a>"
             f"<a class='btn' href='{url_for('modules.module', mod='revreport')}'>Revenue Analysis</a>"
             f"<a class='btn' href='{url_for('modules.module', mod='araging')}'>AR Aging</a>"
             f"<a class='btn' href='{url_for('modules.module', mod='ratios')}'>Ratios</a>"
             f"<a class='btn' href='{url_for('modules.module', mod='ccreport')}'>Cost Centers</a></div></div>")
    return page('Financial Dashboard',
                f"<div class='panel'><div class='pad'><h2 style='margin:0;color:var(--petrol);font-family:Space Grotesk'>Financial Dashboard</h2>"
                f"<div style='color:var(--muted);font-size:13px'>{h(tdy)}</div></div></div>"
                + row1 + row2 + row3 + links, 'findash')


@bp.route('/journal/<int:eid>')
@login_required
def journal_entry(eid):
    """Journal entry detail — shows lines and links back to the source invoice (accounting↔billing)."""
    if not can('journal'): abort(403)
    from ..models import Account
    e = JournalEntry.query.get_or_404(eid)
    iid = _ref_to_invoice(e.ref)
    lines = ''
    for l in e.lines:
        a = Account.query.get(l.account_id)
        lines += (f"<tr><td><b>{h(a.code if a else '')}</b> · {h(a.name if a else '—')}</td>"
                  f"<td class='num'>{money(l.debit) if l.debit else ''}</td>"
                  f"<td class='num'>{money(l.credit) if l.credit else ''}</td></tr>")
    ok = abs(e.total_debit - e.total_credit) < 0.005
    # cross-links: source invoice, reversal relationships
    links = ''
    if iid:
        from ..models import Invoice
        _inv = Invoice.query.get(iid)
        if _inv:
            links += (f"<a class='sbtn' href='{url_for('billing.invoice_view', iid=iid)}'>"
                      f"<span class='sbtn-v'>INV-{iid:04d}</span><span class='sbtn-l'>Source Invoice · {h(_inv.status)}</span></a>")
    if e.reversed_by:
        links += (f"<a class='sbtn' href='{url_for('acct.journal_entry', eid=e.reversed_by)}'>"
                  f"<span class='sbtn-v'>↺</span><span class='sbtn-l'>Reversing Entry</span></a>")
    if e.is_reversal:
        orig = JournalEntry.query.get(e.reverses_id) if e.reverses_id else JournalEntry.query.filter_by(reversed_by=e.id).first()
        if orig:
            links += (f"<a class='sbtn' href='{url_for('acct.journal_entry', eid=orig.id)}'>"
                      f"<span class='sbtn-v'>{h(orig.ref or orig.id)}</span><span class='sbtn-l'>Original Entry</span></a>")
    smart = f"<div class='sbtns'>{links}</div>" if links else ''
    # Reversal audit trail (immutability: a posted entry is corrected only by reversal)
    _rev_audit = ''
    if e.reversed_by and (e.reversal_reason or e.reversed_by_user):
        _rev_audit = (f"<div class='panel' style='border-left:3px solid var(--amber)'><div class='pad' style='font-size:13px'>"
                      f"<b style='color:var(--amber)'>↺ Reversed</b> &nbsp; "
                      f"by <b>{h(e.reversed_by_user or '—')}</b> on {h(e.reversed_at or '—')} · "
                      f"reason: <i>{h(e.reversal_reason or '—')}</i></div></div>")
    rev_btn = ''
    if not e.is_reversal and not e.reversed_by and _period_open(e.date):
        rev_btn = (f"<a class='btn gh' href='{url_for('acct.journal_reverse', eid=e.id)}' "
                   f"onclick=\"var r=prompt('Reason for reversing this entry?'); if(!r)return false; this.href=this.href.split('?')[0]+'?reason='+encodeURIComponent(r); return true;\">↺ Reverse Entry</a>")
    body = (f"<div class='panel'><div class='pad'>"
            f"<div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px'>"
            f"<div><div style='font-family:var(--fd);font-size:20px;font-weight:700;color:var(--petrol)'>{h(e.ref or ('JV-%04d'%e.id))}</div>"
            f"<div style='color:var(--muted);font-size:13px'>{h(e.date)} · {h(e.memo or '')}</div></div>"
            f"<div><span class='pill {'green' if ok else 'red'}'>{'Balanced' if ok else 'Off'}</span></div></div></div></div>"
            + smart + _rev_audit +
            f"<div class='panel'><div class='ph'><h2>Entry Lines</h2><div class='sp'></div>{rev_btn} "
            f"<a class='btn sm' href='{url_for('modules.module', mod='journal')}'>← Journal</a></div>"
            f"<div class='tw'><table><thead><tr><th>Account</th><th class='num'>Debit</th><th class='num'>Credit</th></tr></thead>"
            f"<tbody>{lines}<tr style='font-weight:700;background:var(--canvas)'><td>Total</td>"
            f"<td class='num'>{money(e.total_debit)}</td><td class='num'>{money(e.total_credit)}</td></tr></tbody></table></div></div>")
    return page(f'Journal {e.ref or e.id}', body, 'journal')


@bp.route('/partnerledger/pdf')
@login_required
def partnerledger_pdf():
    from flask import Response
    from ..models import Patient, Supplier, Invoice, PayReceipt, Purchase
    from ..core.pdfgen import ledger_pdf, available
    side = request.args.get('side', 'customer')
    pid = request.args.get('partner', type=int)
    if not pid or not available():
        return redirect(url_for('modules.module', mod='partnerledger') + f'?side={side}')
    events = []; pname = ''
    if side == 'vendor':
        sp = Supplier.query.get(pid); pname = sp.name if sp else ''
        for pu in Purchase.query.filter_by(supplier_id=pid).all():
            events.append((pu.date or '', f'PO-{pu.id:04d}', 'Purchase', pu.total or 0, 0))
            if getattr(pu, 'paid', 0):
                events.append((pu.date or '', f'PO-{pu.id:04d}', 'Payment', 0, pu.paid or 0))
    else:
        pt = Patient.query.get(pid); pname = pt.name if pt else ''
        for i in Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id).all():
            if i.status == 'Cancelled':
                continue
            events.append((i.date or '', f'INV-{i.id:04d}', 'Invoice', i.total, 0))
            for rc in PayReceipt.query.filter_by(invoice_id=i.id).all():
                events.append((rc.date or '', f'RCT-{rc.id:05d}', f'Payment ({rc.method or "Cash"})', 0, rc.amount or 0))
    events.sort(key=lambda e: (e[0], e[1]))
    rows = []; bal = tot_d = tot_c = 0.0
    for date, ref, kind, deb, cred in events:
        bal += deb - cred; tot_d += deb; tot_c += cred
        rows.append([date, ref, kind, money(deb) if deb else '', money(cred) if cred else '', money(bal)])
    cols = [('Date', 'l', 22), ('Ref', 'l', 24), ('Type', 'l', 40),
            ('Debit', 'r', 24), ('Credit', 'r', 24), ('Balance', 'r', 26)]
    totals = ['TOTAL', '', '', money(tot_d), money(tot_c), money(bal)]
    pdf = ledger_pdf(f'Partner Ledger - {pname}', ('Vendor' if side == 'vendor' else 'Patient') + ' account',
                     cols, rows, totals, company=setting('company', 'Modern Diagnostic Center'),
                     currency=setting('currency', '$'))
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + ';filename=Partner-Ledger.pdf'
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


def partnerledger_view():
    """Partner Ledger — per-patient (customer) or per-supplier statement of invoices & payments."""
    from ..models import Patient, Supplier, Invoice, PayReceipt, Purchase
    side = request.args.get('side', 'customer')
    pid = request.args.get('partner', type=int)

    if side == 'vendor':
        partners = Supplier.query.order_by(Supplier.name).all()
    else:
        # only patients with at least one invoice (keeps the list useful)
        ids = {i.patient_id for i in Invoice.query.all() if i.patient_id}
        partners = Patient.query.filter(Patient.id.in_(ids)).order_by(Patient.name).all() if ids else []

    popts = "<option value=''>— Select {} —</option>".format('vendor' if side == 'vendor' else 'patient')
    for p in partners:
        sel = 'selected' if pid == p.id else ''
        label = f"{getattr(p, 'mrn', '') or ''} {p.name}".strip()
        popts += f"<option value='{p.id}' {sel}>{h(label)}</option>"

    tabs = (f"<a class='btn sm {'primary' if side=='customer' else ''}' href='?side=customer'>Customers (Patients)</a> "
            f"<a class='btn sm {'primary' if side=='vendor' else ''}' href='?side=vendor'>Vendors (Suppliers)</a>")

    rows = ''; bal = 0.0; tot_d = tot_c = 0.0
    if pid:
        events = []
        if side == 'vendor':
            for pu in Purchase.query.filter_by(supplier_id=pid).all():
                events.append((pu.date or '', f'PO-{pu.id:04d}', 'Purchase', pu.total or 0, 0))
                if getattr(pu, 'paid', 0):
                    events.append((pu.date or '', f'PO-{pu.id:04d}', 'Payment', 0, pu.paid or 0))
        else:
            for i in Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id).all():
                if i.status == 'Cancelled':
                    continue
                events.append((i.date or '', f'INV-{i.id:04d}', 'Invoice', i.total, 0))
                for rc in PayReceipt.query.filter_by(invoice_id=i.id).all():
                    events.append((rc.date or '', f'RCT-{rc.id:05d}', f'Payment ({rc.method or "Cash"})', 0, rc.amount or 0))
        events.sort(key=lambda e: (e[0], e[1]))
        for date, ref, kind, deb, cred in events:
            bal += deb - cred; tot_d += deb; tot_c += cred
            link = f"/invoice/{int(ref[4:]):d}" if ref.startswith('INV-') else ''
            ref_html = f"<a href='{link}' style='color:var(--petrol);font-weight:600'>{ref}</a>" if link else f"<b>{ref}</b>"
            rows += (f"<tr><td>{h(date)}</td><td>{ref_html}</td><td>{h(kind)}</td>"
                     f"<td class='num'>{money(deb) if deb else ''}</td>"
                     f"<td class='num'>{money(cred) if cred else ''}</td>"
                     f"<td class='num' style='font-weight:600'>{money(bal)}</td></tr>")
        rows += (f"<tr style='font-weight:700;background:var(--canvas)'><td colspan='3'>Total</td>"
                 f"<td class='num'>{money(tot_d)}</td><td class='num'>{money(tot_c)}</td>"
                 f"<td class='num'>{money(bal)}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='6' style='color:var(--muted);padding:16px'>Select a partner to view their statement.</td></tr>"

    _plp = ''
    if pid:
        _plurl = url_for('acct.partnerledger_pdf') + '?side=' + side + '&partner=' + str(pid)
        _plp = "<button class='btn sm' onclick=\"MDCDoc.openSelf('Partner Ledger','" + _plurl + "')\">Print</button>"
    picker = (f"<div class='panel'><div class='pad' style='display:flex;gap:10px;align-items:center;flex-wrap:wrap'>{tabs}"
              f"<form method='get' style='display:flex;gap:8px;align-items:center;flex:1'>"
              f"<input type='hidden' name='side' value='{h(side)}'>"
              f"<select name='partner' class='lb-input' style='min-width:260px' onchange='this.form.submit()'>{popts}</select>"
              f"<button class='btn sm'>View</button></form>"
              f"{_plp}</div></div>")
    stmt = (f"<div class='panel'><div class='ph'><h2>Partner Ledger · Statement</h2>"
            f"<span class='so'>{'Vendor' if side=='vendor' else 'Patient'} account</span></div>"
            f"<div class='tw'><table><thead><tr><th>Date</th><th>Ref</th><th>Type</th>"
            f"<th class='num'>Debit</th><th class='num'>Credit</th><th class='num'>Balance</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></div>")
    return page('Partner Ledger', picker + stmt, 'partnerledger')


# ==================== report period helper (Odoo-style date presets) ====================

PERIODS = [('today','Today'),('yesterday','Yesterday'),('week','This Week'),('lastweek','Last Week'),
           ('month','This Month'),('lastmonth','Last Month'),('quarter','This Quarter'),
           ('lastquarter','Last Quarter'),('year','This Year'),('lastyear','Last Year')]


def report_period():
    """Read ?period= / ?from= / ?to= and return (d1, d2, label, prev_d1, prev_d2)."""
    import datetime as _dt
    p = request.args.get('period', 'year')
    f = (request.args.get('from') or '').strip()
    t = (request.args.get('to') or '').strip()
    td = _dt.date.today()

    def q_start(d): return _dt.date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
    def m_end(d):
        n = _dt.date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
        return n - _dt.timedelta(days=1)

    if f or t:
        d1 = _dt.date.fromisoformat(f) if f else _dt.date(2000, 1, 1)
        d2 = _dt.date.fromisoformat(t) if t else td
        label = f'{d1} → {d2}'
    elif p == 'today': d1 = d2 = td; label = 'Today'
    elif p == 'yesterday': d1 = d2 = td - _dt.timedelta(days=1); label = 'Yesterday'
    elif p == 'week':
        d1 = td - _dt.timedelta(days=td.weekday()); d2 = td; label = 'This Week'
    elif p == 'lastweek':
        d2 = td - _dt.timedelta(days=td.weekday() + 1); d1 = d2 - _dt.timedelta(days=6); label = 'Last Week'
    elif p == 'month': d1 = td.replace(day=1); d2 = td; label = 'This Month'
    elif p == 'lastmonth':
        d2 = td.replace(day=1) - _dt.timedelta(days=1); d1 = d2.replace(day=1); label = 'Last Month'
    elif p == 'quarter': d1 = q_start(td); d2 = td; label = 'This Quarter'
    elif p == 'lastquarter':
        d2 = q_start(td) - _dt.timedelta(days=1); d1 = q_start(d2); label = 'Last Quarter'
    elif p == 'lastyear':
        d1 = _dt.date(td.year - 1, 1, 1); d2 = _dt.date(td.year - 1, 12, 31); label = f'Year {td.year-1}'
    else:  # year
        d1 = _dt.date(td.year, 1, 1); d2 = td; label = f'Year {td.year}'
    span = (d2 - d1).days + 1
    prev_d2 = d1 - _dt.timedelta(days=1)
    prev_d1 = prev_d2 - _dt.timedelta(days=span - 1)
    return d1.isoformat(), d2.isoformat(), label, prev_d1.isoformat(), prev_d2.isoformat()


def period_toolbar(extra=''):
    """Render the period preset + custom range toolbar (keeps other args)."""
    cur = request.args.get('period', 'year')
    f = h(request.args.get('from', '')); t = h(request.args.get('to', ''))
    keep = ''.join(f"<input type='hidden' name='{h(k)}' value='{h(v)}'>"
                   for k, v in request.args.items() if k not in ('period', 'from', 'to'))
    opts = ''.join(f"<option value='{v}' {'selected' if cur==v and not (f or t) else ''}>{lb}</option>"
                   for v, lb in PERIODS)
    return (f"<div class='panel'><div class='pad'><form method='get' class='listbar'>{keep}"
            f"<select name='period' class='lb-input' onchange='this.form.submit()'>{opts}</select>"
            f"<span style='color:var(--muted);font-size:12px'>or custom:</span>"
            f"<input type='date' name='from' value='{f}' class='lb-input'>"
            f"<input type='date' name='to' value='{t}' class='lb-input'>"
            f"<button class='btn sm'>Apply</button>{extra}</form></div></div>")


# ==================== Integrity / Reconciliation Health Check ====================

def _integrity_checks():
    """Return a list of (severity, title, detail, count) financial-integrity findings."""
    from ..models import JournalEntry, Invoice, CommissionAccrual
    out = []

    # 1. Journal entries where debit != credit (double-entry must balance)
    unbal = [e for e in JournalEntry.query.all()
             if abs((e.total_debit or 0) - (e.total_credit or 0)) > 0.005]
    out.append(('error' if unbal else 'ok', 'Journal entries balanced',
                (f"{len(unbal)} entry(ies) out of balance: "
                 + ', '.join((e.ref or f'JV-{e.id:04d}') for e in unbal[:8])) if unbal
                else 'All journal entries balance (debit = credit).', len(unbal)))

    # 2. Invoice total vs its line items
    badtot = []
    for i in Invoice.query.all():
        if i.status == 'Cancelled':
            continue
        line_sum = sum((it.qty or 1) * (it.price or 0) for it in i.items)
        expect = line_sum - (i.discount or 0) - line_sum * (getattr(i, 'discount_pct', 0) or 0) / 100.0 + (i.vat or 0)
        if abs((i.total or 0) - expect) > 0.01:
            badtot.append(i)
    out.append(('error' if badtot else 'ok', 'Invoice totals match line items',
                (f"{len(badtot)} invoice(s) mismatched: "
                 + ', '.join(f'INV-{i.id:04d}' for i in badtot[:8])) if badtot
                else 'Every invoice total equals its lines − discount + VAT.', len(badtot)))

    # 3. Payments never exceed invoice total (overpayment guard)
    overpaid = [i for i in Invoice.query.all()
                if i.status != 'Cancelled' and (i.paid or 0) - (i.total or 0) > 0.01]
    out.append(('warn' if overpaid else 'ok', 'No overpaid invoices',
                (f"{len(overpaid)} invoice(s) paid above total: "
                 + ', '.join(f'INV-{i.id:04d}' for i in overpaid[:8])) if overpaid
                else 'No invoice is paid beyond its total.', len(overpaid)))

    # 4. Commission accruals never paid beyond accrued amount
    badacc = [a for a in CommissionAccrual.query.all() if (a.paid or 0) - (a.amount or 0) > 0.01]
    out.append(('error' if badacc else 'ok', 'Commission payments within accrued',
                f"{len(badacc)} accrual(s) overpaid." if badacc
                else 'No commission/fee paid beyond what was accrued.', len(badacc)))

    # 5. Paid invoices should have a revenue journal entry
    missing_je = []
    for i in Invoice.query.all():
        if i.status == 'Cancelled' or (i.paid or 0) <= 0.005:
            continue
        if not JournalEntry.query.filter_by(ref=f'INV-{i.id:04d}').first():
            missing_je.append(i)
    out.append(('warn' if missing_je else 'ok', 'Paid invoices posted to ledger',
                (f"{len(missing_je)} paid invoice(s) with no journal: "
                 + ', '.join(f'INV-{i.id:04d}' for i in missing_je[:8])) if missing_je
                else 'Every paid invoice has a ledger entry.', len(missing_je)))

    return out


# ==================== Integrity / Reconciliation Health Check ====================

def _integrity_checks():
    """Run a series of financial-integrity checks. Returns list of
    (severity, title, detail, count) where severity is 'ok'|'warn'|'error'."""
    from ..models import JournalEntry, Invoice, CommissionAccrual
    checks = []

    # 1. Every journal entry must balance (debit == credit)
    unbal = [e for e in JournalEntry.query.all()
             if abs((e.total_debit or 0) - (e.total_credit or 0)) > 0.005]
    checks.append(('error' if unbal else 'ok', 'Journal entries balanced',
                   (f"{len(unbal)} entry(ies) out of balance: "
                    + ', '.join((e.ref or f'JV-{e.id:04d}') for e in unbal[:8]))
                   if unbal else 'All journal entries have equal debit and credit.',
                   len(unbal)))

    # 2. Invoice.total must equal the sum of its line items (minus discount + vat)
    bad_tot = []
    for inv in Invoice.query.all():
        line_sum = sum((it.qty or 0) * (it.price or 0) for it in inv.items)
        expect = line_sum - (inv.discount or 0) - line_sum * (getattr(inv, 'discount_pct', 0) or 0) / 100.0 + (inv.vat or 0)
        if abs(expect - (inv.total or 0)) > 0.01:
            bad_tot.append(inv)
    checks.append(('error' if bad_tot else 'ok', 'Invoice totals match line items',
                   (f"{len(bad_tot)} invoice(s) mismatched: "
                    + ', '.join(f'INV-{i.id:04d}' for i in bad_tot[:8]))
                   if bad_tot else 'Every invoice total equals its lines − discount + VAT.',
                   len(bad_tot)))

    # 3. No invoice paid more than its total (overpayment)
    overpaid = [i for i in Invoice.query.all() if (i.paid or 0) - (i.total or 0) > 0.01 and i.status != 'Cancelled']
    checks.append(('warn' if overpaid else 'ok', 'No overpaid invoices',
                   (f"{len(overpaid)} invoice(s) paid above total: "
                    + ', '.join(f'INV-{i.id:04d}' for i in overpaid[:8]))
                   if overpaid else 'No invoice has payments exceeding its total.',
                   len(overpaid)))

    # 4. Commission accruals never paid beyond their amount
    over_acc = [a for a in CommissionAccrual.query.all() if (a.paid or 0) - (a.amount or 0) > 0.01]
    checks.append(('error' if over_acc else 'ok', 'Commission/fee payments within accrued amount',
                   f"{len(over_acc)} accrual(s) overpaid." if over_acc
                   else 'No commission or radiologist fee is overpaid.', len(over_acc)))

    # 5. Paid invoices should have a revenue journal entry
    missing_je = []
    for inv in Invoice.query.all():
        if (inv.paid or 0) > 0.005 and inv.status != 'Cancelled':
            if not JournalEntry.query.filter_by(ref=f'INV-{inv.id:04d}').first():
                missing_je.append(inv)
    checks.append(('warn' if missing_je else 'ok', 'Paid invoices posted to the ledger',
                   (f"{len(missing_je)} paid invoice(s) without a journal entry: "
                    + ', '.join(f'INV-{i.id:04d}' for i in missing_je[:8]))
                   if missing_je else 'Every paid invoice has a ledger entry.', len(missing_je)))

    return checks


def integrity_view():
    checks = _integrity_checks()
    errors = sum(1 for c in checks if c[0] == 'error')
    warns = sum(1 for c in checks if c[0] == 'warn')
    if errors:
        hero_c, hero_t = 'var(--red)', f'{errors} issue(s) need attention'
    elif warns:
        hero_c, hero_t = 'var(--amber)', f'{warns} warning(s) to review'
    else:
        hero_c, hero_t = 'var(--green)', 'All checks passed — books are consistent'
    icon = {'ok': '✓', 'warn': '⚠', 'error': '✗'}
    colr = {'ok': 'var(--green)', 'warn': 'var(--amber)', 'error': 'var(--red)'}
    rows = ''
    for sev, title, detail, count in checks:
        rows += (f"<tr><td style='font-size:18px;color:{colr[sev]};text-align:center'>{icon[sev]}</td>"
                 f"<td><b>{h(title)}</b></td><td style='color:var(--muted)'>{h(detail)}</td></tr>")
    hero = (f"<div class='panel' style='border-left:4px solid {hero_c}'><div class='pad' "
            f"style='display:flex;align-items:center;gap:14px'>"
            f"<div style='font-size:30px;color:{hero_c}'>{'✓' if not errors and not warns else ('⚠' if not errors else '✗')}</div>"
            f"<div><div style='font-weight:700;font-size:16px;font-family:Space Grotesk'>Financial Health Check</div>"
            f"<div style='color:var(--muted)'>{h(hero_t)}</div></div>"
            f"<div class='sp' style='flex:1'></div>"
            f"<a class='btn sm' href='{url_for('modules.module', mod='integrity')}'>↻ Re-run</a></div></div>")
    panel = (f"<div class='panel'><div class='ph'><h2>Reconciliation Checks</h2>"
             f"<span class='so'>{len(checks)} checks · {errors} error(s) · {warns} warning(s)</span></div>"
             f"<div class='tw'><table><thead><tr><th style='width:44px'></th><th>Check</th><th>Result</th></tr></thead>"
             f"<tbody>{rows}</tbody></table></div></div>")
    return page('Integrity', hero + panel, 'integrity')


def costcenters_overview():
    """Odoo-style Cost Centers (Departments) overview: activity + entries per center."""
    from flask import request
    q = (request.args.get('q') or '').strip()
    centers = CostCenter.query.order_by(CostCenter.code).all()
    # activity (expense spend) + entry count per cost center
    rows_dbg = (db.session.query(Expense.cost_center_id,
                                 db.func.coalesce(db.func.sum(Expense.amount), 0),
                                 db.func.count(Expense.id))
                .filter(Expense.cost_center_id.isnot(None))
                .group_by(Expense.cost_center_id).all())
    act = {cid: (float(tot or 0), int(n or 0)) for cid, tot, n in rows_dbg}
    if q:
        ql = q.lower()
        centers = [c for c in centers if ql in (c.name or '').lower() or ql in (c.code or '').lower()]

    total_activity = sum(act.get(c.id, (0, 0))[0] for c in centers)
    active_n = sum(1 for c in centers if c.active)

    CSS = """<style>
    .cc-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .cc-stat{flex:1;min-width:160px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
    .cc-stat .l{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
    .cc-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
    .cc-stat.a{border-left:3px solid var(--petrol)} .cc-stat.b{border-left:3px solid var(--green)} .cc-stat.c{border-left:3px solid var(--amber)}
    </style>"""
    stats = (CSS + "<div class='cc-stats'>"
             f"<div class='cc-stat a'><div class='l'>Cost Centers</div><div class='v'>{len(centers)}</div></div>"
             f"<div class='cc-stat b'><div class='l'>Active</div><div class='v'>{active_n}</div></div>"
             f"<div class='cc-stat c'><div class='l'>Total Activity</div><div class='v'>{money(total_activity)}</div></div>"
             "</div>")

    search = (f"<form method='get' style='margin-bottom:10px'>"
              f"<input name='q' value='{h(q)}' placeholder='🔍  Search cost center…' "
              f"style='width:min(360px,100%);padding:7px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px'></form>")
    toolbar = (f"<div class='panel' style='padding:10px 12px;margin-bottom:12px'>"
               f"<a class='btn primary sm' href='{url_for('modules.module_new', mod='costcenters')}'>+ New Cost Center</a></div>")

    rows = ''
    for c in sorted(centers, key=lambda x: act.get(x.id, (0, 0))[0], reverse=True):
        amt, n = act.get(c.id, (0, 0))
        rows += (f"<tr><td><b>{h(c.code or '—')}</b></td><td>{h(c.name)}</td>"
                 f"<td class='num'>{n}</td><td class='num'>{money(amt)}</td>"
                 f"<td>{pill('Active','green') if c.active else pill('Off','grey')}</td>"
                 f"<td class='num'><a class='btn gh sm' href='{url_for('modules.module_edit', mod='costcenters', oid=c.id)}'>Edit</a></td></tr>")
    if not rows:
        rows = "<tr><td colspan='6'><div class='empty'><b>No cost centers</b><br>Add departments to tag journal entries.</div></td></tr>"
    table = (f"<div class='panel'><div class='ph'><h2>Cost Centers · Departments</h2>"
             f"<span class='so'>Activity = total expenses tagged to each department</span></div>"
             f"<div class='tw'><table><thead><tr><th>Code</th><th>Cost Center</th>"
             f"<th class='num'>Entries</th><th class='num'>Activity</th><th>Status</th><th></th></tr></thead>"
             f"<tbody>{rows}</tbody></table></div></div>")

    return page('Cost Centers', stats + toolbar + search + table, 'costcenters',
                crumbs=[('Cost Centers', None)])
