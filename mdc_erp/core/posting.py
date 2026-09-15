"""Accounting engine: price lists, journal posting and re-posting hooks."""
from ..extensions import db
from ..models import *
from .helpers import today, money_round

PRICE_LISTS=['Cash','Insurance','Corporate','VIP','Contract']
PAY_METHODS=['Cash','Sahal','EVC','E. Dahab','MyCash','Premier Wallet','Bank','Card','Insurance','Credit']
# Somali mobile-money wallets all settle into the same GL cash-equivalent (1103).
# Old names (EVC Plus / eDahab / Mobile Money) kept as aliases so historical
# receipts still classify and post to the right account after the rename.
MOBILE_METHODS={'Sahal','EVC','E. Dahab','MyCash','Premier Wallet',
                'Mobile Money','Mobile','EVC Plus','eDahab'}
# Corrected in v2.5 — v1 mapped Cash/Bank inverted (Cash→1102 Bank, Bank→1101 Cash).
# Historical entries are untouched; any re-post uses the corrected accounts.
PM_ACCOUNT={'Cash':'1101','Bank':'1102','Card':'1102','Cheque':'1102','Insurance':'1250',
            'Sahal':'1104','EVC':'1105','E. Dahab':'1106','MyCash':'1107','Premier Wallet':'1108',
            # legacy aliases keep pointing at the old combined Mobile Money account
            'Mobile Money':'1103','EVC Plus':'1105','eDahab':'1106'}

# Human-readable name for each per-provider wallet account, used to auto-create it
# on an existing database the first time a payment uses that method.
PM_ACCOUNT_NAME={'1101':'Main Account (USD)','1102':'Cash in Hand','1103':'Mobile Money',
                 '1104':'Sahal','1105':'EVC','1106':'E. Dahab','1107':'MyCash','1108':'Premier Wallet'}

def pm_account(method):
    """Return the GL account code for a payment method, creating the account if it
    doesn't exist yet (so splitting Mobile Money into Sahal/EVC/E.Dahab/… works on
    databases seeded before the split). Never returns a missing account."""
    code = PM_ACCOUNT.get(method or 'Cash', '1101')
    if not Account.query.filter_by(code=code).first():
        acc_ensure(code, PM_ACCOUNT_NAME.get(code, method or code), 'Asset', '1100')
    return code

def live_invoices():
    """All non-cancelled invoices, with line items eagerly loaded.

    Invoice.total reads self.items, so a plain .all() here made every caller
    fire one extra query per invoice (12k invoices -> ~8s dashboards). The
    selectinload turns that into a couple of queries."""
    from sqlalchemy.orm import selectinload
    return [i for i in Invoice.query.options(selectinload(Invoice.items)).all()
            if i.status != 'Cancelled']

def service_price(s, plist):
    v={'Insurance':s.price_insurance,'Corporate':s.price_corporate,'VIP':s.price_vip,'Contract':s.price_contract}.get(plist or 'Cash', None)
    return (v if (v or 0)>0 else (s.price or 0))

def acc(code): return Account.query.filter_by(code=code).first()

class PeriodClosedError(Exception):
    """Raised when a posting targets a Closed fiscal period."""
    def __init__(self, date):
        super().__init__(f'Fiscal period for {date} is closed')
        self.date = date


class UnbalancedJournalError(Exception):
    """Raised when a journal's debits do not equal its credits. The posting is
    rejected and rolled back so nothing is ever partially written to the ledger."""
    def __init__(self, ref, debit, credit):
        self.ref = ref
        self.debit = debit
        self.credit = credit
        self.diff = round(debit - credit, 2)
        super().__init__(
            f'Journal {ref} is unbalanced: debit {debit:.2f} \u2260 credit {credit:.2f} '
            f'(difference {self.diff:+.2f}). Posting rejected.')


def _period_open(date):
    try:
        y, m = int(str(date)[0:4]), int(str(date)[5:7])
    except (TypeError, ValueError):
        return True
    fp = FiscalPeriod.query.filter_by(year=y, month=m).first()
    return not (fp and fp.status == 'Closed')


def acc_ensure(code, name, atype, parent_code=None):
    """Get a COA account, creating it (idempotently) if missing — old DBs included."""
    a = Account.query.filter_by(code=code).first()
    if not a:
        parent = Account.query.filter_by(code=parent_code).first() if parent_code else None
        a = Account(code=code, name=name, type=atype,
                    parent_id=parent.id if parent else None)
        db.session.add(a); db.session.commit()
    return a


def post_journal(date, ref, memo, lines):
    if not _period_open(date):
        raise PeriodClosedError(date)
    real=[(acc(c), d, cr) for (c, d, cr) in lines if acc(c) and (d or cr)]
    if not real:
        # nothing to post — clear any prior entry under this ref and return
        for e in JournalEntry.query.filter_by(ref=ref).all(): db.session.delete(e)
        db.session.commit(); return None
    # ---- INTEGRITY GATE: books MUST balance before anything is written ----
    # Sum debits and credits at cent precision (Decimal) so float drift never
    # trips the check, then require exact balance to the cent. If they differ
    # we reject the WHOLE posting, roll back, record an error, and never write
    # a single line — no partial posting is ever possible.
    from decimal import Decimal, ROUND_HALF_UP
    def _c(x): return Decimal(str(x or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    _dr = sum((_c(d) for _, d, _ in real), Decimal('0'))
    _cr = sum((_c(c) for _, _, c in real), Decimal('0'))
    if _dr != _cr:
        db.session.rollback()
        try:
            from .helpers import log_error
            log_error(f'REJECTED unbalanced journal {ref}: debit {_dr} != credit {_cr} '
                      f'(diff {_dr - _cr}) — posting rolled back')
        except Exception:
            pass
        raise UnbalancedJournalError(ref, float(_dr), float(_cr))
    # balanced — safe to (re)write the entry
    for e in JournalEntry.query.filter_by(ref=ref).all(): db.session.delete(e)
    db.session.flush()
    je=JournalEntry(date=date or today(), ref=ref, memo=memo); db.session.add(je); db.session.flush()
    for a, d, cr in real:
        db.session.add(JournalLine(entry_id=je.id, account_id=a.id, debit=d or 0, credit=cr or 0))
    db.session.commit(); return je

def _drop_reversals(ref):
    """Remove any reset-to-draft reversal paired to postings under `ref`.
    Called when `ref` is re-posted so a stale reversal never lingers to double-count."""
    for e in JournalEntry.query.filter_by(ref=f"REV-{ref}").all():
        db.session.delete(e)

def reverse_invoice_entries(inv, reason='', by=''):
    """Reverse the live accounting for an invoice when it is Reset to Draft.
    Posts balanced reversing entries (is_reversal) for the invoice's sales (INV-)
    and payment (PAY-) postings, swapping debit/credit, and links each original to
    its reversal — preserving a complete audit trail. Books net to zero while the
    invoice is re-worked; the next repost refreshes them cleanly. Returns the count."""
    n = 0
    for ref in (f"INV-{inv.id:04d}", f"PAY-{inv.id:04d}"):
        orig = JournalEntry.query.filter_by(ref=ref).first()
        if not orig or orig.reversed_by or orig.is_reversal or not orig.lines:
            continue
        if not _period_open(today()):
            continue
        rev = JournalEntry(date=today(), ref=f"REV-{ref}", is_reversal=True,
                           memo=(f"Reversal (reset to draft) of {ref}"
                                 + (f" · {reason}" if reason else ''))[:200])
        db.session.add(rev); db.session.flush()
        for l in orig.lines:                      # swap debit/credit
            db.session.add(JournalLine(entry_id=rev.id, account_id=l.account_id,
                                       debit=l.credit or 0, credit=l.debit or 0))
        orig.reversed_by = rev.id
        n += 1
    db.session.commit()
    return n

def invoice_contrast_income(inv):
    """Contrast income embedded in an invoice = the center's own service income
    (kept in full, not commissionable). Booked to a separate Contrast Income account.
    If a manual per-invoice contrast amount is set it wins; otherwise it is auto-detected
    as contrast_cost × qty for each 'with contrast' line."""
    manual = getattr(inv, 'contrast_amount', None)
    if manual is not None:
        try:
            return max(0.0, float(manual))
        except (TypeError, ValueError):
            return 0.0
    try:
        from .security import setting
        cc = float(setting('contrast_cost', '40') or 40)
    except Exception:
        cc = 40.0
    tot = 0.0
    for it in inv.items:
        svc = it.service
        if svc and 'with contrast' in (svc.name or '').lower():
            tot += cc * (it.qty or 1)
    return tot


def repost_invoice(inv):
    ref=f"INV-{inv.id:04d}"; _drop_reversals(ref); sub=inv.subtotal; disc=(inv.discount or 0)+sub*(inv.discount_pct or 0)/100.0; vat=inv.vat or 0; total=inv.total
    if total<=0 or inv.status=='Cancelled':
        for e in JournalEntry.query.filter_by(ref=ref).all(): db.session.delete(e)
        db.session.commit(); return
    who=inv.patient.name if inv.patient else 'Walk-in'
    net_rev = sub - disc
    # split the contrast portion into its own income account (rest → 4400 service revenue)
    contrast_inc = max(0.0, min(invoice_contrast_income(inv), net_rev))
    study_rev = net_rev - contrast_inc
    lines = [('1200', total, 0), ('4400', 0, study_rev), ('2400', 0, vat)]
    if contrast_inc > 0.005:
        acc_ensure('4450', 'Contrast Income', 'Income', '4000')
        lines.append(('4450', 0, contrast_inc))
    post_journal(inv.date, ref, f"Invoice INV-{inv.id:04d} · {who}", lines)

def repost_payment(inv):
    ref=f"PAY-{inv.id:04d}"; _drop_reversals(ref); paid=inv.paid or 0
    _acct=PM_ACCOUNT.get(inv.pay_method or 'Cash')
    if _acct=='1250': acc_ensure('1250','Insurance Receivable','Asset','1000')
    elif _acct: pm_account(inv.pay_method or 'Cash')   # ensure the per-provider wallet account exists
    if inv.status=='Cancelled' or not _acct: paid=0
    post_journal(inv.date, ref, f"Payment INV-{inv.id:04d} ({inv.pay_method or 'Cash'})",
                 [(_acct or '1102', paid, 0), ('1200', 0, paid)] if paid>0 else [])
    # auto-accrue referring-doctor commission + radiologist fee once the invoice is fully paid
    try:
        accrue_commissions(inv)
    except Exception:
        db.session.rollback()
        from .helpers import log_error; log_error(f'accrue_commissions INV-{inv.id:04d}')

def post_expense(e):
    ref = f"EXP-{e.id:04d}"
    # Odoo-style flow: the expense posts to the ledger only when it reaches the
    # POSTED stage (manager approved → journal posted). Draft/Submitted/Approved
    # expenses are not yet accounting events.
    if getattr(e, 'status', None) not in ('Posted', 'Paid'):
        for je in JournalEntry.query.filter_by(ref=ref).all():
            db.session.delete(je)
        db.session.commit(); return
    # Expense category → expense (debit) account
    m={'Rent':'6200','Utilities':'6300','Salaries':'6100','Salaries & Wages':'6100','Maintenance':'6500','Marketing':'6500'}
    accode=m.get(e.category,'6500'); amt=e.amount or 0
    # Post: Dr Expense / Cr Accounts Payable (the payment is a separate step that
    # clears the payable — like a vendor bill).
    post_journal(e.date, ref, f"Expense · {e.description or e.category or ''}",
                 [(accode, amt, 0), ('2100', 0, amt)])


def repost_expense_payment(e):
    """Post the payment side of a posted expense: Dr Accounts Payable / Cr the
    account matching the method (Cash/Sahal/E.Dahab/Bank…)."""
    ref = f"PAYE-{e.id:04d}"
    for je in JournalEntry.query.filter_by(ref=ref).all():
        db.session.delete(je)
    db.session.commit()
    paid = e.paid or 0
    if paid <= 0.005 or getattr(e, 'status', None) not in ('Posted', 'Paid'):
        return
    pay_acc = pm_account(e.pay_method or 'Cash')
    post_journal(e.date, ref, f"Expense Payment · {e.description or e.category or ''} ({e.pay_method or 'Cash'})",
                 [('2100', paid, 0), (pay_acc, 0, paid)])

def post_purchase(p):
    ref = f"PUR-{p.id:04d}"
    # The vendor bill posts to the ledger only once it is CONFIRMED (bill_status
    # == 'posted'), mirroring the customer invoice (Confirm → post). Before that
    # — RFQ, ordered, received or a draft bill — there is no accounting entry.
    if getattr(p, 'bill_status', None) != 'posted' or getattr(p, 'status', None) == 'Cancelled':
        for e in JournalEntry.query.filter_by(ref=ref).all():
            db.session.delete(e)
        db.session.commit(); return
    total = p.total or 0
    who = (p.supplier.name if getattr(p, 'supplier', None) else (p.item or ''))
    # Confirming the bill books the goods to the inventory asset and the amount to
    # Accounts Payable. Registering a payment later credits cash/wallet and clears
    # the payable (handled by po_pay via repost_payment).
    post_journal(p.date, ref, f"Vendor Bill · {who}",
                 [('1300', total, 0), ('2100', 0, total)])


def repost_purchase_payment(p):
    """Post/refresh the payment side of a confirmed vendor bill: Dr Accounts
    Payable / Cr the account matching the method (Cash/Sahal/E.Dahab/Bank…)."""
    ref = f"PAYP-{p.id:04d}"
    _drop_reversals(ref) if '_drop_reversals' in globals() else [db.session.delete(e) for e in JournalEntry.query.filter_by(ref=ref).all()]
    db.session.commit()
    paid = p.paid or 0
    if paid <= 0.005 or getattr(p, 'bill_status', None) != 'posted':
        return
    _pm = getattr(p, 'pay_method', None) or 'Cash'
    pay_acc = pm_account(_pm)
    who = (p.supplier.name if getattr(p, 'supplier', None) else (p.item or ''))
    post_journal(p.date, ref, f"Bill Payment · {who} ({_pm})",
                 [('2100', paid, 0), (pay_acc, 0, paid)])


POST_HOOKS = {'expenses': post_expense, 'purchases': post_purchase}


def commission_preview(inv):
    """Compute the payable amounts for an invoice — used by both the invoice screen
    and accrue_commissions so the numbers always match.
    Percent-based amounts are scaled by the discount factor (commission AFTER discount);
    fixed per-study fees are not scaled."""
    from ..models import RadOrder, Radiologist
    fees = inv.service_fees  # gross, from per-service config
    sub = inv.subtotal or 0
    net = sub - (inv.discount or 0) - sub * (getattr(inv, 'discount_pct', 0) or 0) / 100.0
    factor = (net / sub) if sub > 0 else 1.0
    factor = max(0.0, min(1.0, factor))

    doctor_name = (inv.doctor_ref.name if inv.doctor_ref else None) or getattr(inv, 'doctor_name', None)
    # contrast is the center's own income → excluded from the doctor/writer commission base.
    # Commission base = commissionable subtotal − discount − contrast (absolute $, NOT compounded
    # proportions), then apply the effective rate. e.g. 180 − 30 − 25 = 125 → 125 × 20% = $25.
    contrast = invoice_contrast_income(inv)
    gross_doc = (fees.get('doctor', 0) + fees.get('writer', 0))
    dbase = sum((it.qty or 1) * (it.price or 0) for it in inv.items
                if it.service and ((getattr(it.service, 'comm_doctor_val', 0) or 0)
                                   or (getattr(it.service, 'comm_report_val', 0) or 0)))
    if gross_doc > 0.005 and dbase > 0:
        disc_on_comm = (sub - net) * (dbase / sub) if sub > 0 else 0.0   # discount share on commissionable lines
        base = max(0.0, dbase - disc_on_comm - contrast)
        doc_amt = money_round(gross_doc * (base / dbase))
    else:
        doc_amt = money_round(gross_doc * factor)
    # fallback: per-doctor rule (legacy Doctor.commission_type) when services carry no config
    if doc_amt <= 0.005 and inv.doctor_ref:
        d = inv.doctor_ref
        if d.commission_type == 'Fixed':
            doc_amt = money_round(d.fixed_rate or 0)
        else:
            rate = d.percent_rate or 0
            rate = rate / 100.0 if rate > 1 else rate   # accept 20 or 0.20 for 20%
            base = max(0.0, net - contrast)              # (subtotal − discount) − contrast
            doc_amt = money_round(base * rate)

    rad_name = None
    rads = RadOrder.query.filter_by(invoice_id=inv.id).all() if hasattr(RadOrder, 'invoice_id') else []
    if not rads and inv.referral_id:
        rads = RadOrder.query.filter_by(ref_id=inv.referral_id).all()
    for ro in rads:
        rad_name = ro.radiologist or (ro.assigned_rad.name if getattr(ro, 'assigned_rad', None) else None)
        if rad_name:
            break

    # ── Radiologist reporting fee ─────────────────────────────────────────────
    # A flat fee (default $10, Settings 'rad_fee') is charged for EVERY scan report
    # and deducted — together with the doctor commission — after the discount. A
    # per-service comm_radiologist_* or an assigned Radiologist's own rule overrides
    # the default when configured (Percent applies to the discounted line amount).
    def _is_rad(it):
        s = it.service
        return bool(s and (getattr(s, 'modality', None)
                    or (s.department or '') in ('Radiology', 'CT Scan', 'MRI', 'X-Ray', 'Ultrasound')
                    or getattr(it, 'rad_order_id', None)))
    rad_lines = [it for it in inv.items if _is_rad(it)]

    try:
        from .security import setting as _setting
        global_fee = float(_setting('rad_fee', '10') or 10)
    except Exception:
        global_fee = 10.0

    _r = Radiologist.query.filter_by(name=rad_name).first() if rad_name else None
    rule_type = _r.fee_type if (_r and _r.fee_type in ('Fixed', 'Percent') and (_r.fee_value or 0) > 0) else None
    rule_val = (_r.fee_value or 0) if rule_type else 0

    rad_amt = 0.0
    n_studies = 0
    for it in rad_lines:
        qty = int(it.qty or 1)
        n_studies += qty
        line_net = (qty * (it.price or 0)) * factor   # after discount
        # rate priority: assigned radiologist's rule > per-service config > flat default
        if rule_type:
            rtype, rval = rule_type, rule_val
        else:
            rtype = getattr(it.service, 'comm_radiologist_type', None)
            rval = getattr(it.service, 'comm_radiologist_val', 0) or 0
        if rval:
            rad_amt += (line_net * rval / 100.0) if rtype == 'Percent' else (rval * qty)
        else:
            rad_amt += global_fee * qty               # default: flat fee per scan report
    rad_amt += (fees.get('technician', 0) or 0)       # any technician fee (flat), unchanged
    rad_amt = money_round(rad_amt)
    return doctor_name, doc_amt, rad_name, rad_amt


def accrue_commissions(inv):
    """When an invoice becomes fully paid, accrue the referring-doctor commission and
    radiologist reporting fee as outstanding payables, and post the accounting entries.
    Idempotent: existing accruals/journals for this invoice are cleared and rebuilt."""
    from ..models import CommissionAccrual
    # clear prior accruals + journals for this invoice (unless already partly paid out)
    prior = CommissionAccrual.query.filter_by(invoice_id=inv.id).all()
    if any((a.paid or 0) > 0 for a in prior):
        return  # already settled against these — never disturb paid history
    for a in prior:
        db.session.delete(a)
    for je in JournalEntry.query.filter_by(ref=f"COMM-{inv.id:04d}").all():
        db.session.delete(je)
    db.session.flush()

    fully_paid = (inv.total or 0) > 0 and (inv.paid or 0) >= (inv.total or 0) - 0.005
    if inv.status == 'Cancelled' or not fully_paid:
        return

    doctor_name, doc_amt, rad_name, rad_amt = commission_preview(inv)

    lines = []
    acc_ensure('2300', 'Doctor Commission Payable', 'Liability', '2000')
    acc_ensure('5130', 'Doctor Commission', 'Expense', '5100')
    acc_ensure('2310', 'Radiologist Fee Payable', 'Liability', '2000')
    acc_ensure('5140', 'Radiologist Fees', 'Expense', '5100')

    if doc_amt > 0:
        db.session.add(CommissionAccrual(invoice_id=inv.id, date=inv.date, role='doctor',
                                         payee_kind='doctor', payee_name=doctor_name or 'Unassigned',
                                         amount=doc_amt, paid=0, status='Unpaid'))
        lines += [('5130', doc_amt, 0), ('2300', 0, doc_amt)]
    if rad_amt > 0:
        db.session.add(CommissionAccrual(invoice_id=inv.id, date=inv.date, role='radiologist',
                                         payee_kind='radiologist', payee_name=rad_name or 'Unassigned',
                                         amount=rad_amt, paid=0, status='Unpaid'))
        lines += [('5140', rad_amt, 0), ('2310', 0, rad_amt)]

    if lines:
        post_journal(inv.date, f"COMM-{inv.id:04d}",
                     f"Commission accrual · INV-{inv.id:04d}", lines)


# ------------------------------------------------------- credit / debit notes
def post_credit_note(cn):
    if not cn.user:
        from .security import cur_user
        u = cur_user(); cn.user = u.username if u else ''
    inv = cn.invoice
    who = inv.patient.name if (inv and inv.patient) else 'Walk-in'
    post_journal(cn.date, f"CN-{cn.id:04d}",
                 f"Credit Note · INV-{inv.id:04d} · {who} · {cn.reason or ''}",
                 [('4400', cn.amount or 0, 0), ('1200', 0, cn.amount or 0)])


def post_debit_note(dn):
    if not dn.user:
        from .security import cur_user
        u = cur_user(); dn.user = u.username if u else ''
    p = dn.purchase
    who = p.supplier.name if (p and p.supplier) else (p.item if p else '')
    pref = f"PUR-{p.id:04d}" if p else "—"
    post_journal(dn.date, f"DN-{dn.id:04d}",
                 f"Debit Note · {pref} · {who} · {dn.reason or ''}",
                 [('2100', dn.amount or 0, 0), ('1300', 0, dn.amount or 0)])


POST_HOOKS['creditnotes'] = post_credit_note
POST_HOOKS['debitnotes'] = post_debit_note


# ----------------------------------------------------------- depreciation run
def annual_depreciation(asset, year):
    """Straight-line charge for one asset in one calendar year (first year prorated)."""
    cost = asset.cost or 0
    life = asset.useful_life or 5
    if cost <= 0 or asset.status == 'Retired':
        return 0.0
    try:
        start = __import__('datetime').date.fromisoformat(asset.purchase_date)
    except (TypeError, ValueError):
        return 0.0
    if start.year > year or start.year + life <= year:
        return 0.0
    annual = cost / life
    if start.year == year:
        annual = annual * (13 - start.month) / 12.0
    return round(annual, 2)


def run_depreciation(year):
    """(Re)post the aggregate straight-line depreciation entry DEP-<year>."""
    acc_ensure('1590', 'Accumulated Depreciation', 'Asset', '1000')
    acc_ensure('5900', 'Depreciation Expense', 'Expense', '5000')
    total = round(sum(annual_depreciation(a, year) for a in Asset.query.all()), 2)
    post_journal(f'{year}-12-31', f'DEP-{year}', f'Depreciation FY {year} (straight-line)',
                 [('5900', total, 0), ('1590', 0, total)] if total > 0 else [])
    return total


# ------------------------------------------------------------ year-end close
def close_fiscal_year(year):
    """Move net P&L into Retained Earnings and lock all 12 periods."""
    acc_ensure('3200', 'Retained Earnings', 'Equity', '3000')
    yr = str(year)
    bal = {}
    for l in JournalLine.query.join(JournalEntry).filter(JournalEntry.date.like(yr + '%')).all():
        a = l.account
        if not a or a.type not in ('Income', 'Expense'):
            continue
        bal[a.code] = bal.get(a.code, 0.0) + (l.credit or 0) - (l.debit or 0)
    lines, net = [], 0.0
    for code, b in sorted(bal.items()):
        if abs(b) < 0.005:
            continue
        # zero the account: income (credit balance) is debited, expense credited
        lines.append((code, b, 0) if b > 0 else (code, 0, -b))
        net += b
    if lines:
        lines.append(('3200', 0, net) if net > 0 else ('3200', -net, 0))
        post_journal(f'{year}-12-31', f'CLS-{year}', f'Year-end closing FY {year}', lines)
    for m in range(1, 13):
        fp = FiscalPeriod.query.filter_by(year=year, month=m).first()
        if not fp:
            fp = FiscalPeriod(year=year, month=m)
            db.session.add(fp)
        fp.status = 'Closed'
    db.session.commit()
    return net


# ------------------------------------------------- opening balances (COA)
def opening_dr(a):
    """Account opening balance expressed debit-positive.

    Users enter openings in the account's natural direction:
    Asset/Expense -> debit balance, Liability/Equity/Income -> credit balance.
    """
    op = a.opening or 0
    return op if a.type in ('Asset', 'Expense') else -op


def opening_totals():
    """(op_asset, op_liab, op_equity, net_debit_of_all_openings)."""
    from ..models import Account
    oa = ol = oe = net = 0.0
    for a in Account.query.all():
        if not (a.opening or 0):
            continue
        if a.type == 'Asset': oa += a.opening or 0
        elif a.type == 'Liability': ol += a.opening or 0
        elif a.type == 'Equity': oe += a.opening or 0
        net += opening_dr(a)
    return oa, ol, oe, net


# ---------------------------------------------------------------------------
# GL-LINKED FINANCIAL STATEMENTS
# One engine that reads the general ledger and builds the P&L, Balance Sheet and
# Cash Flow from account balances by TYPE. Because every money movement posts to
# the ledger through post_journal(), everything flows into the statements
# automatically and they always tie to the Trial Balance.
# ---------------------------------------------------------------------------
CASH_CODE_PREFIXES = ('1101', '1102', '1103', '1104', '1105', '1106', '1107', '1108')


def gl_account_movement(account_id, d1=None, d2=None):
    """Sum (debit - credit) posted to an account, optionally within [d1, d2]."""
    from ..models import JournalLine, JournalEntry
    q = db.session.query(
        db.func.coalesce(db.func.sum(JournalLine.debit), 0) -
        db.func.coalesce(db.func.sum(JournalLine.credit), 0)
    ).filter(JournalLine.account_id == account_id)
    if d1 or d2:
        q = q.join(JournalEntry)
        if d1:
            q = q.filter(JournalEntry.date >= d1)
        if d2:
            q = q.filter(JournalEntry.date <= d2)
    return money_round(q.scalar() or 0)


def gl_statements(d1, d2):
    """Return P&L / Balance Sheet / Cash-Flow figures computed ENTIRELY from the
    general ledger (posted journal lines) + opening balances. `d1..d2` bounds the
    P&L and cash-flow period; the balance sheet is 'as at d2' (cumulative)."""
    from ..models import Account
    accounts = Account.query.filter_by(is_group=False).all()

    income = expense = 0.0            # period P&L (from Income/Expense accounts)
    income_rows = []; expense_rows = []
    assets = liabilities = equity = 0.0
    asset_rows = []; liab_rows = []; equity_rows = []
    cash_asat = 0.0                   # cash & bank & wallets, as at d2
    cash_movement = 0.0               # net cash movement within the period

    for a in accounts:
        period = gl_account_movement(a.id, d1, d2)          # debit-positive, in period
        cumulative = (a.opening or 0) + gl_account_movement(a.id, None, d2)  # dr-positive incl opening, as at d2 (Asset/Expense natural)
        # convert opening to debit-positive natural direction for cumulative
        cum_dr = opening_dr(a) + gl_account_movement(a.id, None, d2)
        if a.type == 'Income':
            amt = -period                                   # income is credit-natural
            if abs(amt) > 0.005:
                income += amt; income_rows.append((a.code, a.name, amt))
        elif a.type == 'Expense':
            amt = period                                    # expense is debit-natural
            if abs(amt) > 0.005:
                expense += amt; expense_rows.append((a.code, a.name, amt))
        elif a.type == 'Asset':
            if abs(cum_dr) > 0.005:
                assets += cum_dr; asset_rows.append((a.code, a.name, cum_dr))
            if any((a.code or '').startswith(p) for p in CASH_CODE_PREFIXES):
                cash_asat += cum_dr
                cash_movement += period
        elif a.type == 'Liability':
            amt = -cum_dr                                    # liability credit-natural
            if abs(amt) > 0.005:
                liabilities += amt; liab_rows.append((a.code, a.name, amt))
        elif a.type == 'Equity':
            amt = -cum_dr
            if abs(amt) > 0.005:
                equity += amt; equity_rows.append((a.code, a.name, amt))

    net_income = money_round(income - expense)
    # Opening balances entered on accounts (via the chart of accounts) rarely
    # self-balance on their own, so — exactly like the Trial Balance — add a
    # single "Opening Balance Equity" plug to Equity so Assets = Liabilities +
    # Equity always holds. obe = net debit of all openings; a net-debit opening
    # means extra assets financed by equity (credit), hence subtract into equity.
    _oa, _ol, _oe, obe = opening_totals()
    # obe = net DEBIT of all openings. A net debit (extra assets) is balanced by a
    # CREDIT to equity of the same amount, so add +obe into equity.
    equity_obe = obe if abs(obe) > 0.005 else 0.0
    if abs(equity_obe) > 0.005:
        equity += equity_obe
        equity_rows.append(('3199', 'Opening Balance Equity', equity_obe))
    # Balance-sheet equity must include the current-period net income (retained
    # earnings) so that Assets = Liabilities + Equity holds.
    equity_with_ni = money_round(equity + net_income)
    return {
        'd1': d1, 'd2': d2,
        'income': money_round(income), 'expense': money_round(expense), 'net_income': net_income,
        'income_rows': income_rows, 'expense_rows': expense_rows,
        'assets': money_round(assets), 'liabilities': money_round(liabilities),
        'equity': money_round(equity), 'equity_with_ni': equity_with_ni,
        'asset_rows': asset_rows, 'liab_rows': liab_rows, 'equity_rows': equity_rows,
        'cash_asat': money_round(cash_asat), 'cash_movement': money_round(cash_movement),
        'balances': money_round(assets - (liabilities + equity_with_ni)),  # should be ~0
    }
