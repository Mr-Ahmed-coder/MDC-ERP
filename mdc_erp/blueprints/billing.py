"""Billing: invoices, items, payments, doctor commission ledger."""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, Response,
                   flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.security import (cur_user, can, login_required, log,
                             csrf_token)
from ..core.helpers import money, today, cur_year, money_round
from ..core.ui import page, smartbar, track_view, next_step, plink, pnamelink
from ..core.posting import (PRICE_LISTS, PAY_METHODS, service_price, repost_invoice,
                            repost_payment, reverse_invoice_entries)
from ..core.printing import printable

bp = Blueprint('billing', __name__)


def _step_bar(step):
    """Guided progress indicator: ① PATIENT → ② SERVICES → ③ REVIEW → ④ PAYMENT.
    `step` is the 1-based index of the current step (1-4)."""
    labels = ['① Patient', '② Services', '③ Review', '④ Payment']
    parts = []
    for i, lab in enumerate(labels, start=1):
        if i < step:
            parts.append(f"<span style='color:var(--green);font-weight:600'>✓ {lab}</span>")
        elif i == step:
            parts.append(f"<span style='color:#fff;background:var(--petrol);padding:3px 10px;border-radius:20px;font-weight:700'>{lab}</span>")
        else:
            parts.append(f"<span style='color:var(--muted)'>{lab}</span>")
        if i < len(labels):
            parts.append("<span style='color:var(--line)'>→</span>")
    return ("<div class='panel'><div class='pad' style='display:flex;gap:10px;align-items:center;"
            "flex-wrap:wrap;font-size:13px'>" + ' '.join(parts) + "</div></div>")


def _display_status(inv):
    """Cashier-facing status badge: DRAFT → CONFIRMED → PARTIALLY PAID → PAID,
    or CANCELLED. Purely a display label — the underlying inv.status field
    ('Unpaid'/'Partial'/'Paid'/'Cancelled') and its many downstream readers
    (accounting, referrals, portal…) are untouched."""
    if inv.status == 'Cancelled':
        return 'CANCELLED', 'grey'
    if inv.total > 0 and inv.balance <= 0.005:
        return 'PAID', 'green'
    if (inv.paid or 0) > 0 or (inv.credits or 0) > 0:
        return 'PARTIALLY PAID', 'amber'
    if getattr(inv, 'confirmed', False):
        return 'CONFIRMED', 'blue'
    return 'DRAFT', 'grey'


# ── Odoo account.move form chrome ────────────────────────────────────────────
INV_ODOO_CSS = """<style>
.oform{max-width:940px;margin:0 auto}
.osb{display:inline-flex;align-items:stretch;border:1px solid var(--line);border-radius:8px;overflow:hidden;font-family:var(--fd,inherit)}
.osb .s{padding:6px 15px 6px 20px;font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);background:var(--surface);display:flex;align-items:center;position:relative;white-space:nowrap}
.osb .s:first-child{padding-left:15px}
.osb .s:not(:first-child)::before{content:"";position:absolute;left:0;top:50%;width:9px;height:9px;transform:translate(-55%,-50%) rotate(45deg);background:var(--surface);border-right:1px solid var(--line);border-top:1px solid var(--line);z-index:1}
.osb .s.done{color:var(--petrol)}
.osb .s.cur{background:var(--petrol);color:#fff}.osb .s.cur::before{background:var(--petrol);border-color:var(--petrol)}
.osb .s.cur.paid{background:var(--green)}.osb .s.cur.paid::before{background:var(--green);border-color:var(--green)}
.osb .s.cur.cancel{background:#8494a1}.osb .s.cur.cancel::before{background:#8494a1;border-color:#8494a1}
.o-stats{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}
.o-stat{display:flex;align-items:center;gap:10px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:8px 14px;color:var(--ink);min-width:120px}
.o-stat .n{font-family:var(--fd,inherit);font-size:19px;font-weight:700;color:var(--petrol);line-height:1}
.o-stat .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.o-stat.link:hover{border-color:var(--petrol);box-shadow:0 4px 12px rgba(4,76,140,.12)}
.o-sheet{position:relative;overflow:hidden;background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:0 6px 24px rgba(2,48,90,.07);padding:26px 30px 30px}
.o-title{font-family:var(--fd,inherit);font-size:30px;font-weight:800;letter-spacing:-.5px;color:var(--ink);line-height:1.05}
.o-title small{display:block;font-size:12.5px;font-weight:600;color:var(--muted);letter-spacing:.02em;margin-top:3px}
.o-head{display:grid;grid-template-columns:1fr 1fr;gap:8px 46px;margin:22px 0 6px}
@media(max-width:680px){.o-head{grid-template-columns:1fr}}
.o-row{display:flex;gap:10px;font-size:13.5px;padding:3px 0;align-items:baseline}
.o-row .k{color:var(--muted);min-width:130px;flex:none}
.o-row .v{color:var(--ink);font-weight:600}
.o-row .v select,.o-row .v input{border:1px solid var(--line);border-radius:6px;padding:4px 8px;background:var(--surface);color:var(--ink);font-size:13px}
.o-tabs{margin-top:20px;border-bottom:2px solid var(--line);display:flex;gap:2px}
.o-tab-h{padding:9px 16px;font-size:13.5px;font-weight:700;color:var(--muted);cursor:pointer;border:0;background:none;border-bottom:2px solid transparent;margin-bottom:-2px}
.o-tab-h.on{color:var(--petrol);border-bottom-color:var(--petrol)}
.o-tab{display:none;padding-top:14px}.o-tab.on{display:block}
.o-lines{width:100%;border-collapse:collapse;font-size:13.5px}
.o-lines thead th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--petrol);font-weight:700;padding:8px 10px;border-bottom:1px solid var(--line)}
.o-lines thead th.num,.o-lines td.num{text-align:right}
.o-lines tbody td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top}
.o-lines tbody tr:hover{background:var(--hover)}
.o-lines .src{font-size:11px;color:var(--muted)}
.o-addline{margin-top:8px}
.o-addline .lnk{color:var(--petrol);font-weight:700;font-size:13px;cursor:pointer;display:inline-flex;align-items:center;gap:5px}
.o-addline .lnk:hover{text-decoration:underline}
.o-add-form{display:none;margin-top:12px;background:var(--canvas);border:1px solid var(--line);border-radius:10px;padding:12px}
.o-add-form.on{display:block}
.o-totals{margin:16px 0 0 auto;max-width:320px}
.o-totals .r{display:flex;justify-content:space-between;padding:4px 0;font-size:13.5px;color:var(--ink)}
.o-totals .r .k{color:var(--muted)}
.o-totals .grand{border-top:2px solid var(--line);margin-top:6px;padding-top:8px;font-family:var(--fd,inherit);font-size:19px;font-weight:800;color:var(--petrol)}
.o-totals .due{border-top:1px solid var(--line);margin-top:4px;padding-top:6px;font-weight:700}
.inv-ribbon{position:absolute;top:20px;right:-52px;transform:rotate(45deg);width:190px;text-align:center;padding:6px 0;font-weight:800;font-size:12px;letter-spacing:.1em;color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.22);z-index:6;pointer-events:none}
.inv-ribbon.paid{background:var(--green)}.inv-ribbon.partial{background:var(--amber)}.inv-ribbon.cancel{background:#8494a1}
.mdcpay{position:fixed;inset:0;z-index:9500;display:flex;align-items:flex-start;justify-content:center}
.mdcpay[hidden]{display:none}
.mdcpay-back{position:absolute;inset:0;background:rgba(15,23,42,.45)}
.mdcpay-box{position:relative;margin-top:11vh;width:min(460px,94vw);background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:12px;box-shadow:0 24px 64px rgba(0,0,0,.30);overflow:hidden}
.mdcpay-hd{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--line);font-size:16px;font-weight:700;color:var(--petrol)}
.mdcpay-x{border:0;background:transparent;color:var(--muted);font-size:22px;line-height:1;cursor:pointer}
.mdcpay-bd{padding:16px 18px}
.mdcpay-bd label{display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);margin:10px 0 4px}
.mdcpay-bd input,.mdcpay-bd select{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:8px;font-size:14px;background:var(--surface);color:var(--ink)}
.mdcpay-due{background:var(--canvas);border:1px solid var(--line);border-radius:8px;padding:10px 12px;display:flex;justify-content:space-between;align-items:center;font-size:13px}
.mdcpay-due b{font-size:18px;color:var(--petrol);font-family:var(--fd,inherit)}
.mdcpay-ft{padding:12px 18px;border-top:1px solid var(--line);display:flex;gap:8px;justify-content:flex-end}
@media(max-width:480px){.mdcpay-box{margin-top:0;width:100vw;min-height:100vh;border-radius:0}}
</style>"""


def _odoo_statusbar(inv):
    if inv.status == 'Cancelled':
        return ("<span class='osb'><span class='s'>Draft</span>"
                "<span class='s cur cancel'>Cancelled</span></span>")
    paid = inv.total > 0 and inv.balance <= 0.005
    partial = (not paid) and ((inv.paid or 0) > 0 or (inv.credits or 0) > 0)
    confirmed = bool(getattr(inv, 'confirmed', False) or paid or partial or inv.locked)
    idx = 2 if paid else (1 if confirmed else 0)
    labels = ['Draft', 'Posted', 'Paid']
    out = []
    for i, lab in enumerate(labels):
        if i == idx:
            if i == 1 and partial:
                lab = 'Partial'
            out.append(f"<span class='s cur{' paid' if i==2 else ''}'>{lab}</span>")
        elif i < idx:
            out.append(f"<span class='s done'>{lab}</span>")
        else:
            out.append(f"<span class='s'>{lab}</span>")
    return "<span class='osb'>" + ''.join(out) + "</span>"


def _pay_ribbon(inv):
    if inv.status == 'Cancelled':
        return "<div class='inv-ribbon cancel'>CANCELLED</div>"
    if inv.total > 0 and inv.balance <= 0.005:
        return "<div class='inv-ribbon paid'>PAID</div>"
    if (inv.paid or 0) > 0 or (inv.credits or 0) > 0:
        return "<div class='inv-ribbon partial'>PARTIAL</div>"
    return ''


@bp.route('/api/patients/quicksearch')
@login_required
def patients_quicksearch():
    """Lightweight JSON lookup for the invoice 'Select Patient' search box —
    search by name, MRN or phone. Powers live results, no page reload."""
    from flask import jsonify
    from ..core.security import branch_scope
    if not can('invoices'):
        return jsonify({'results': []}), 403
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify({'results': []})
    like = f'%{q}%'
    rows = (branch_scope(Patient.query, Patient)
            .filter(db.or_(Patient.name.ilike(like), Patient.mrn.ilike(like),
                            Patient.phone.ilike(like), Patient.phone2.ilike(like)))
            .order_by(Patient.name).limit(8).all())
    out = [dict(id=p.id, mrn=p.mrn or '—', name=p.name, gender=p.gender or '—',
                age=p.age if p.age is not None else '—', phone=p.phone or '—')
           for p in rows]
    return jsonify({'results': out})


def invoice_list():
    from ..models import Referral
    from flask import render_template
    # --- Waiting for Billing: registered referrals with no invoice yet ---
    pend_rows = ''
    _billed = {rid for (rid,) in db.session.query(Invoice.referral_id)
               .filter(Invoice.referral_id.isnot(None)).distinct().all()}
    pending = [r for r in Referral.query.filter(Referral.status.in_(['New', 'Accepted']))
               .order_by(Referral.id.desc()).limit(50).all() if r.id not in _billed]
    for r in pending:
        who = (r.doctor_ref.name if r.doctor_ref else r.doctor_name) or '—'
        mrn = (r.patient.mrn if r.patient_id and r.patient else '—')
        stc = {'New': 'blue', 'Accepted': 'amber'}.get(r.status, 'grey')
        if r.patient_id:
            act = (f"<a class='btn primary sm' href='/referral/{r.id}/invoice'>Create Invoice</a> "
                   f"<a class='btn gh sm' href='/patient/{r.patient_id}'>Patient</a>")
        else:
            act = f"<a class='btn sm' href='{url_for('ref.referral_accept', rid=r.id)}'>Register First</a>"
        act += f" <a class='btn gh sm' href='{url_for('ref.referral_detail', rid=r.id)}'>Preview</a>"
        pend_rows += (f"<tr><td><b>REF-{r.id:04d}</b></td><td>{pnamelink(r.patient_name)}</td><td>{h(mrn)}</td>"
                      f"<td>{h(who)}</td><td style='max-width:220px;white-space:normal'><small>{h((r.tests or '—')[:90])}</small></td>"
                      f"<td>{h(r.date)}</td><td><span class='pill {stc}'>{'Waiting' if r.status=='Accepted' else r.status}</span></td>"
                      f"<td class='num'>{act}</td></tr>")
    pend_panel = ''
    if pend_rows:
        pend_panel = (f"<div class='panel' style='border-left:3px solid var(--amber)'>"
                      f"<div class='ph'><h2>⏳ Waiting for Billing</h2>"
                      f"<span class='so'>{len(pending)} referral(s) — hal-guji Create Invoice (adeegyadu si toos ah ayay u soo galaan)</span></div>"
                      f"<div class='tw'><table><thead><tr><th>Referral</th><th>Patient</th><th>MRN</th><th>Doctor</th>"
                      f"<th>Services</th><th>Date</th><th>Status</th><th></th></tr></thead>"
                      f"<tbody>{pend_rows}</tbody></table></div></div>")
    from ..core.security import branch_scope
    from sqlalchemy.orm import selectinload
    from ..models import Patient
    from .modules import search_view, hl

    def _inv_extra(q):
        # also match the linked patient's name / MRN, and the invoice number
        conds = [Invoice.patient.has(Patient.name.ilike(f'%{q}%')),
                 Invoice.patient.has(Patient.mrn.ilike(f'%{q}%')),
                 Invoice.guarantor.ilike(f'%{q}%')]
        digits = ''.join(ch for ch in q if ch.isdigit())
        if digits:
            try:
                conds.append(Invoice.id == int(digits))
            except ValueError:
                pass
        return conds

    _q = branch_scope(Invoice.query, Invoice)
    _cust = request.args.get('cust', type=int)
    if _cust:
        _q = _q.filter(Invoice.patient_id == _cust)
    _q, _sq, _fbar = search_view('invoices', Invoice, _q,
                                 search_cols=['status'], date_field='date',
                                 extra_or=_inv_extra,
                                 placeholder='Search patient, MRN, invoice no…')
    _total = _q.count()
    _per = 50
    _pages = max(1, -(-_total // _per))
    _pg = request.args.get('page', type=int) or 1
    _pg = max(1, min(_pg, _pages))
    inv = (_q.options(selectinload(Invoice.items), selectinload(Invoice.patient))
             .order_by(Invoice.id.desc()).limit(_per).offset((_pg - 1) * _per).all())
    # Invoice.credits queries CreditNote per invoice; fetch them for this page in one go
    from ..models import CreditNote
    _ids = [i.id for i in inv]
    _cred = dict(db.session.query(CreditNote.invoice_id, db.func.sum(CreditNote.amount))
                 .filter(CreditNote.invoice_id.in_(_ids)).group_by(CreditNote.invoice_id).all()) if _ids else {}
    body_rows=[]
    for i in inv:
        _t = i.total
        _cr = _cred.get(i.id, 0) or 0
        _bal = _t - (i.paid or 0) - _cr
        settled = _bal <= 0.005 and _t > 0
        if i.status == 'Cancelled':
            stt, paidst = 'Cancelled', 'grey'
        elif not getattr(i, 'confirmed', True):
            stt, paidst = 'Draft', 'grey'
        elif settled:
            stt, paidst = 'Paid', 'green'
        elif (i.paid or 0) > 0 or _cr > 0:
            stt, paidst = 'Partial', 'amber'
        else:
            stt, paidst = 'Unpaid', 'red'
        refcell = f"REF-{i.referral_id:04d}" if i.referral_id else '—'
        gcell = (f"<b>{h(i.guarantor)}</b>" if i.guarantor
                 else ("<span style='color:var(--muted)'>—</span>" if settled
                       else "<span style='color:var(--red)'>not set</span>"))
        body_rows.append([
            f"<b>INV-{i.id:04d}</b>",
            h(i.date),
            h(i.patient.name if i.patient else '—'),
            refcell,
            gcell,
            money(_t),
            money(i.paid),
            f"<span class='pill {paidst}'>{stt}</span>",
            (f"<a class='btn gh sm' href='{url_for('billing.invoice_view',iid=i.id)}'>Open</a>"
             f"<a class='btn gh sm' href='{url_for('billing.invoice_print',iid=i.id)}' target='_blank'>Print</a>"),
        ])
    if _sq:
        body_rows = [[hl(c, _sq) for c in row] for row in body_rows]
    # ---- Odoo stat band (full branch-scoped snapshot, not the filtered page) ----
    _sb_objs = branch_scope(Invoice.query, Invoice).options(selectinload(Invoice.items)).all()
    _sbids = [o.id for o in _sb_objs]
    _sbcred = dict(db.session.query(CreditNote.invoice_id, db.func.sum(CreditNote.amount))
                   .filter(CreditNote.invoice_id.in_(_sbids)).group_by(CreditNote.invoice_id).all()) if _sbids else {}
    def _sbal(o): return (o.total or 0) - (o.paid or 0) - (_sbcred.get(o.id, 0) or 0)
    _cancelled = [o for o in _sb_objs if o.status == 'Cancelled']
    _liveq = [o for o in _sb_objs if o.status != 'Cancelled']
    _paid = [o for o in _liveq if (o.total or 0) > 0 and _sbal(o) <= 0.005]
    _outst = [o for o in _liveq if _sbal(o) > 0.005]
    _mon = today()[:7]
    _mon_inv = sum((o.total or 0) for o in _liveq if (o.date or '').startswith(_mon))
    _outst_amt = sum(_sbal(o) for o in _outst)
    _ICSS = """<style>
    .iv-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .iv-stat{flex:1;min-width:145px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
    .iv-stat .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
    .iv-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
    .iv-stat.a{border-left:3px solid var(--petrol)} .iv-stat.b{border-left:3px solid var(--green)}
    .iv-stat.c{border-left:3px solid var(--amber)} .iv-stat.d{border-left:3px solid var(--red)} .iv-stat.g{border-left:3px solid #98a2b3}
    </style>"""
    def _ivc(cls, l, v):
        return f"<div class='iv-stat {cls}'><div class='l'>{l}</div><div class='v'>{v}</div></div>"
    _stats = (_ICSS + "<div class='iv-stats'>"
              + _ivc('a', 'Invoices', str(len(_liveq)))
              + _ivc('b', 'Paid', str(len(_paid)))
              + _ivc('c', 'Outstanding', str(len(_outst)))
              + _ivc('d', 'Outstanding Amount', money(_outst_amt))
              + _ivc('g', 'Cancelled', str(len(_cancelled)))
              + _ivc('a', 'This Month Invoiced', money(_mon_inv))
              + "</div>")
    # customer (patient) quick filter dropdown
    _pids = [pid for (pid,) in db.session.query(Invoice.patient_id)
             .filter(Invoice.patient_id.isnot(None)).distinct().all()]
    _pats = Patient.query.filter(Patient.id.in_(_pids)).order_by(Patient.name).all() if _pids else []
    _copts = "<option value=''>All customers</option>" + ''.join(
        f"<option value='{p.id}' {'selected' if _cust == p.id else ''}>{h(p.name)}{(' · ' + h(p.mrn)) if p.mrn else ''}</option>"
        for p in _pats)
    _custform = (f"<form method='get' style='display:inline-flex;gap:6px;align-items:center;margin-right:8px'>"
                 f"<span style='font-size:12.5px;color:var(--muted)'>Customer:</span>"
                 f"<select name='cust' onchange='this.form.submit()' style='padding:6px 10px;border:1px solid var(--line);border-radius:8px;max-width:230px'>{_copts}</select></form>")
    shortcuts = """<script>document.addEventListener('keydown',function(e){
      if(e.ctrlKey && e.key==='n'){e.preventDefault();location.href='/invoice/new';}
    });</script>"""
    body = render_template('list_page.html', title='Invoices', prefix=_stats + pend_panel,
                           subtitle='Ctrl+N = New', filterbar=_fbar,
                           toolbar=_custform + f"<a class=\"btn primary\" href=\"{url_for('billing.invoice_new')}\">+ New Invoice</a>",
                           headers=['No.','Date','Patient','Referral','Guarantor','Total','Paid','Status',''],
                           aligns=['','','','','','num','num','','num'], rows=body_rows,
                           footer=_inv_pager(_pg, _pages, _total, _per),
                           empty="<div class='empty'><b>No invoices</b>Create the first invoice.</div>")
    return page('Invoices', body + shortcuts, 'invoices')


def _inv_pager(page_no, pages, total, per):
    if total <= per:
        return ''
    def lk(n, label, disabled=False, cur=False):
        if disabled:
            return f"<span class='pg-x'>{label}</span>"
        return f"<a class='pg-a {'on' if cur else ''}' href='?page={n}'>{label}</a>"
    lo = max(1, page_no - 2); hi = min(pages, page_no + 2)
    nums = ''.join(lk(n, str(n), cur=(n == page_no)) for n in range(lo, hi + 1))
    first = (page_no - 1) * per + 1; last = min(total, page_no * per)
    return (f"<div class='pager'><span class='pg-info'>{first:,}–{last:,} of {total:,}</span>"
            f"<div class='sp' style='flex:1'></div>"
            f"{lk(page_no-1,'‹ Prev',disabled=page_no<=1)}{nums}"
            f"{lk(page_no+1,'Next ›',disabled=page_no>=pages)}</div>")

def _wf_completed(inv):
    """A workflow is complete when the invoice is fully settled AND every linked
    lab/radiology order has reached its terminal (approved/reported) state."""
    if not (inv.total > 0 and inv.balance <= 0.005):
        return False
    labs = LabOrder.query.filter_by(invoice_id=inv.id).all()
    rads = RadOrder.query.filter_by(invoice_id=inv.id).all()
    if not labs and not rads:
        return True   # pure billing workflow — settled is enough
    return all(o.status == 'Approved' for o in labs) and all(o.status == 'Reported' for o in rads)


def _maybe_complete(inv):
    """Lock the invoice once its whole workflow is done. Idempotent and audited."""
    if not inv or inv.locked or inv.status == 'Cancelled':
        return
    if _wf_completed(inv):
        inv.locked = True
        if inv.referral_id:
            from ..models import Referral
            r = Referral.query.get(inv.referral_id)
            if r and r.status != 'Completed':
                r.status = 'Completed'
        db.session.commit()
        log(f'Workflow completed — INV-{inv.id:04d} locked', action_type='Report Approval',
            entity=f'INV-{inv.id:04d}', old='Open', new='Completed & locked')


def _reset_to_draft(inv, reason='', by=''):
    try:
        from .inventory import unconsume_for_invoice; unconsume_for_invoice(inv)
    except Exception:
        pass
    """Return a posted/paid invoice to an editable Draft, reversing ALL of its live
    accounting: sale (INV-) + payment (PAY-) via reversing entries (audit trail kept),
    plus the commission (COMM- journal + un-settled CommissionAccrual rows), and
    re-locking any linked lab/radiology orders. Returns the count of sale/payment
    entries reversed. The next Confirm + payment reposts the books cleanly."""
    from ..core.posting import reverse_invoice_entries
    n = reverse_invoice_entries(inv, reason=reason, by=by)
    for _e in JournalEntry.query.filter_by(ref=f'COMM-{inv.id:04d}').all():
        db.session.delete(_e)
    try:
        for _a in CommissionAccrual.query.filter_by(invoice_id=inv.id).all():
            if (getattr(_a, 'paid', 0) or 0) <= 0:      # keep any commission already paid out
                db.session.delete(_a)
    except Exception:
        pass
    try:
        for _o in LabOrder.query.filter_by(invoice_id=inv.id).all():
            _o.paid_gate = False
        for _o in RadOrder.query.filter_by(invoice_id=inv.id).all():
            _o.paid_gate = False
    except Exception:
        pass
    inv.paid = 0
    inv.confirmed = False
    inv.locked = False
    inv.status = 'Draft'
    return n


def _pending_orders_count(inv):
    """Read-only: count uninvoiced lab/radiology orders for this invoice's patient.
    Performs no writes — safe to call while rendering a GET page."""
    from ..models import LabOrder, RadOrder
    if not inv.patient_id or inv.status == 'Cancelled':
        return 0
    n = 0
    for Model in (LabOrder, RadOrder):
        for o in Model.query.filter_by(patient_id=inv.patient_id).all():
            if (o.invoice_id or 0) or (o.status or '') == 'Cancelled' or not o.service_id:
                continue
            n += 1
    return n


def _autofill_from_orders(inv):
    """Automatically pull every currently-eligible billable item onto this
    invoice — lab, radiology, and billable consultations today; more
    sources can be added later purely inside get_billable_services().
    Thin wrapper kept for backward compatibility with existing call sites."""
    from ..core.billing_engine import apply_billable_services
    n = apply_billable_services(inv)
    if n:
        log(f'Invoice #{inv.id}: {n} pending billable item(s) auto-added')
    return n


@bp.route('/invoice/new', methods=['GET','POST'])
@login_required
def invoice_new():
    if not can('invoices'): abort(403)
    if request.method=='POST':
        inv=Invoice(patient_id=request.form.get('patient_id') or None, date=request.form.get('date') or today(), branch_id=(cur_user().branch_id if cur_user() else None))
        db.session.add(inv); db.session.commit(); log(f'Created invoice #{inv.id}')
        n=_autofill_from_orders(inv)
        if n:
            flash(f'⚡ {n} service{"s" if n!=1 else ""} automatically added — review below and confirm.')
        elif inv.patient_id:
            flash('No pending billable services were found for this patient. You can add a line manually if needed.')
        return redirect(url_for('billing.invoice_view', iid=inv.id))
    # --- Skip the search step when the patient is already known, e.g. the ----
    # patient hub's "Create Invoice" link (?patient=<id>) or any other caller
    # that already knows who the invoice is for. Odoo-style: go straight to
    # an invoice with services auto-filled, instead of asking to search again.
    _pid = request.args.get('patient', type=int)
    if _pid:
        patient = Patient.query.get(_pid)
        if not patient:
            flash('Patient not found.')
            return redirect(url_for('billing.invoice_new'))
        # Reuse an existing draft (unconfirmed, not cancelled) invoice for this
        # patient instead of spawning a new blank one on every click.
        existing = Invoice.query.filter_by(patient_id=_pid, confirmed=False)\
            .filter(Invoice.status != 'Cancelled').order_by(Invoice.id.desc()).first()
        if existing:
            return redirect(url_for('billing.invoice_view', iid=existing.id))
        inv = Invoice(patient_id=_pid, date=today(), branch_id=(cur_user().branch_id if cur_user() else None))
        db.session.add(inv); db.session.commit(); log(f'Created invoice #{inv.id} for {patient.name}')
        n = _autofill_from_orders(inv)
        if n:
            flash(f'⚡ {n} service{"s" if n!=1 else ""} automatically added — review below and confirm.')
        else:
            flash('No pending billable services were found for this patient. You can add a line manually if needed.')
        return redirect(url_for('billing.invoice_view', iid=inv.id))
    # --- Step 1: Select Patient — live search by name / MRN / phone -----------
    # Replaces the old "pick from a giant dropdown of every patient" field with
    # a fast, typeahead search so the cashier never has to scroll a long list.
    body = _step_bar(1) + f"""
    <div class="panel"><div class="ph"><h2>New Invoice</h2><span class="so">Step 1 of 4 — Select Patient</span></div>
      <div class="pad">
        <div style="position:relative;max-width:520px">
          <input id="pq" autocomplete="off" placeholder="Search by name, MRN or phone…"
                 style="width:100%;padding:12px 14px;font-size:15px;border:1px solid var(--line);border-radius:10px">
          <div id="pq-results" style="position:relative;margin-top:6px"></div>
        </div>
        <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--line);display:flex;align-items:center;gap:10px">
          <span style="color:var(--muted);font-size:13px">No patient for this sale?</span>
          <form method="post"><input type="hidden" name="patient_id" value="">
            <button class="btn sm">Walk-in Invoice (no patient)</button></form>
        </div>
      </div>
    </div>
    <script>
    (function(){{
      var box=document.getElementById('pq'), out=document.getElementById('pq-results'), t=null;
      function card(p){{
        var d=document.createElement('form'); d.method='post';
        d.style.cssText='display:flex;align-items:center;gap:12px;padding:11px 14px;border:1px solid var(--line);'
          +'border-radius:10px;margin-bottom:6px;background:var(--surface);cursor:pointer';
        d.innerHTML='<input type="hidden" name="patient_id" value="'+p.id+'">'
          +'<input type="hidden" name="_csrf" value="{csrf_token()}">'
          +'<div style="width:36px;height:36px;border-radius:50%;background:var(--petrol);color:#fff;'
          +'display:grid;place-items:center;font-weight:600;font-size:13px;flex:none">'+(p.name||'?').charAt(0).toUpperCase()+'</div>'
          +'<div style="flex:1;min-width:0"><b>'+p.name+'</b>'
          +'<div style="color:var(--muted);font-size:12px">MRN '+p.mrn+' · '+p.gender+' · Age '+p.age+' · '+p.phone+'</div></div>'
          +'<button type="submit" class="btn primary sm">Select →</button>';
        d.onclick=function(e){{ if(e.target.tagName!=='BUTTON') d.requestSubmit(); }};
        d.addEventListener('submit', function(){{
          var ov=document.createElement('div');
          ov.style.cssText='position:fixed;inset:0;background:rgba(255,255,255,.85);z-index:999;display:flex;align-items:center;justify-content:center;font-size:15px;color:var(--petrol);font-weight:600';
          ov.textContent='⏳ Finding billable services…';
          document.body.appendChild(ov);
        }});
        return d;
      }}
      box.addEventListener('input', function(){{
        clearTimeout(t); var q=box.value.trim();
        if(q.length<2){{ out.innerHTML=''; return; }}
        t=setTimeout(function(){{
          fetch('{url_for('billing.patients_quicksearch')}?q='+encodeURIComponent(q))
            .then(function(r){{return r.json();}})
            .then(function(d){{
              out.innerHTML='';
              if(!d.results || !d.results.length){{
                out.innerHTML='<div style="color:var(--muted);font-size:13px;padding:8px 2px">No matching patients.</div>';
                return;
              }}
              d.results.forEach(function(p){{ out.appendChild(card(p)); }});
            }});
        }}, 250);
      }});
      box.focus();
    }})();
    </script>"""
    return page('New Invoice', body, 'invoices', crumbs=[('Invoices', url_for('modules.module', mod='invoices')), ('New', None)])

@bp.route('/invoice/<int:iid>', methods=['GET','POST'])
@login_required
def invoice_view(iid):
    inv=Invoice.query.get_or_404(iid)
    from ..core.security import can_see
    if not can_see(inv): abort(403)        # row-level: invoices stay inside their branch
    _refnote=''
    if getattr(inv,'referral_id',None):
        from ..models import Referral as _R
        _rr=_R.query.get(inv.referral_id)
        if _rr:
            _refnote=(f"<div class='panel' style='border-left:3px solid var(--petrol)'><div class='pad' style='font-size:13px'>"
                      f"📋 <b>Doctor Request REF-{_rr.id:04d}</b> · Dr {h(_rr.doctor_name or '—')} · Priority {h(_rr.priority or 'Routine')}"
                      f"{' · '+(_rr.tests or '') if _rr.tests else ''}</div></div>")
    # NOTE: no ledger writes on GET — posting happens on POST actions (pay/update)
    # or explicitly via the 'sync' action below. This keeps page views side-effect
    # free and prevents double-posting from refreshes, prefetch or concurrent loads.
    if request.method=='POST':
        act=request.form.get('act')
        if inv.locked:
            flash('🔒 This invoice is completed and locked. Only an administrator can reset it to draft.')
            log(f'BLOCKED "{act}" on locked INV-{iid:04d}')
            return redirect(url_for('billing.invoice_view', iid=iid))
        if act=='confirm':
            if not inv.items:
                flash('Add at least one service before confirming the invoice.')
                return redirect(url_for('billing.invoice_view', iid=iid))
            if any((it.price or 0) <= 0 for it in inv.items):
                flash('One or more lines have no price set — fix the price before confirming.')
                return redirect(url_for('billing.invoice_view', iid=iid))
            inv.confirmed = True
            db.session.commit()
            # Auto-post to the general ledger on confirm (Dr AR / Cr Revenue),
            # pulling in any pending lab/radiology orders first. No separate
            # "Sync & Post to ledger" step is needed.
            try:
                _autofill_from_orders(inv)   # commits + posts via repost_invoice
                repost_invoice(inv)
            except Exception:
                db.session.rollback()
                from ..core.helpers import log_error; log_error(f'auto-post on confirm INV-{iid:04d}')
            log(f'Invoice INV-{iid:04d} confirmed', action_type='Edit', entity=f'INV-{iid:04d}', new='Confirmed & posted')
            flash('✓ Invoice confirmed and posted to the ledger — register the payment below.')
            return redirect(url_for('billing.invoice_view', iid=iid) + '#pay')
        elif act=='draft':
            flash('Draft saved. You can come back and finish this invoice anytime from the Invoices list.')
            return redirect(url_for('modules.module', mod='invoices'))
        elif act=='unconfirm':
            _paid = (inv.paid or 0) > 0 or inv.credits
            if _paid and not (can('discounts') or can('creditnotes')):
                flash('This invoice has a payment — only a supervisor/admin can reset it to draft.')
                return redirect(url_for('billing.invoice_view', iid=iid))
            _rev = _reset_to_draft(inv, reason=(request.form.get('reason') or 'reset to draft'),
                                   by=(cur_user().username if cur_user() else ''))
            db.session.commit()
            log(f'Invoice INV-{iid:04d} reset to draft', action_type='Reset Draft',
                entity=f'INV-{iid:04d}', old='Posted/Paid' if _paid else 'Posted',
                new=f'Draft (editable) · {_rev} accounting entr{"y" if _rev==1 else "ies"} reversed',
                reason=(request.form.get('reason') or None))
            flash('↺ Reset to draft — edit the lines, then Confirm & register payment again.'
                  + (f' Payment & commission reversed ({_rev} entr{"y" if _rev==1 else "ies"}).' if _paid else ''))
            return redirect(url_for('billing.invoice_view', iid=iid))
        elif act=='additem':
            def _qty(raw):
                """Return (value, ok). Blank -> (1, True). Present but <=0 or bad -> (0, False)."""
                if raw is None or str(raw).strip()=='':
                    return 1.0, True
                try: x=float(raw)
                except (TypeError, ValueError): return 0.0, False
                return (x, True) if x>0 else (0.0, False)
            # Reason is prompted in the UI (required there); on the server we
            # default it so an add is never silently blocked. Who/when are always
            # recorded for the audit trail.
            _reason=(request.form.get('reason') or '').strip() or 'Manual entry'
            _u=cur_user(); _who=(_u.name or _u.username) if _u else None; _when=dt.datetime.now().strftime('%Y-%m-%d %H:%M')
            sid=request.form.get('service_id')
            if sid:
                s=Service.query.get(int(sid)); _q,_ok=_qty(request.form.get('qty'))
                if not s or getattr(s, 'active', True) is False:
                    flash('Service unavailable — it may have been discontinued. Please choose another service.')
                    log(f'BLOCKED unavailable service {sid} on INV-{iid:04d}')
                    return redirect(url_for('billing.invoice_view', iid=iid))
                if not _ok:
                    flash('Quantity must be a number greater than zero.'); return redirect(url_for('billing.invoice_view', iid=iid))
                _pr=service_price(s, inv.price_list)
                if _pr<=0:
                    flash(f'Service "{s.name}" has no price — set a price in Service Catalog first.'); return redirect(url_for('billing.invoice_view', iid=iid))
                # repeat add of the same service increases its quantity (Odoo-style)
                _existing=InvoiceItem.query.filter_by(invoice_id=iid, service_id=s.id).first()
                if _existing:
                    _existing.qty=(_existing.qty or 0)+_q
                    log(f'Qty +{_q:g} on INV-{iid:04d}: {s.name} (now {_existing.qty:g}) · by={_who}')
                else:
                    db.session.add(InvoiceItem(invoice_id=iid,service_id=s.id,desc=s.name,qty=_q,price=_pr,
                                                manual_reason=_reason,manual_by=_who,manual_at=_when))
                    log(f'Manual service added to INV-{iid:04d}: {s.name} · reason={_reason} · by={_who}')
                if s.supply_id and (s.supply_qty or 0)>0:
                    _m=Medicine.query.get(s.supply_id)
                    if _m:
                        from ..core.stock import deduct_stock
                        deduct_stock(_m, (s.supply_qty or 0)*_q)
                        _m.qty=int(_m.qty or 0)
                        log(f"Stock auto-deduct: {_m.name} -{(s.supply_qty or 0)*_q:g} (invoice {iid})")
                        if _m.qty <= (_m.reorder or 0):
                            from ..core.notify import notify
                            notify(f"Low stock: {_m.name} — {_m.qty} left (reorder level {_m.reorder or 0})",
                                   link='/m/inventory', role='storekeeper')
            else:
                _q,_ok=_qty(request.form.get('qty'))
                if not _ok:
                    flash('Quantity must be a number greater than zero.'); return redirect(url_for('billing.invoice_view', iid=iid))
                try: _pr=float(request.form.get('price') or 0)
                except (TypeError, ValueError): _pr=0.0
                if _pr<0: _pr=0.0
                _desc=request.form.get('desc') or 'Item'
                db.session.add(InvoiceItem(invoice_id=iid,desc=_desc,qty=_q,price=_pr,
                                            manual_reason=_reason,manual_by=_who,manual_at=_when))
                log(f'Manual custom line added to INV-{iid:04d}: {_desc} · reason={_reason} · by={_who}')
            db.session.commit()
        elif act=='delitem':
            it=InvoiceItem.query.get(int(request.form['item_id']))
            if it:
                log(f'Line removed from INV-{iid:04d}: {it.desc} ({money(it.price)} × {it.qty:g})')
                for src_model, src_attr in ((LabOrder,'lab_order_id'),(RadOrder,'rad_order_id'),(Consultation,'consult_id')):
                    src_id = getattr(it, src_attr, None)
                    if src_id:
                        o = src_model.query.get(src_id)
                        if o and o.invoice_id == iid: o.invoice_id = None   # release back to "pending" so it can be re-billed
                db.session.delete(it); db.session.commit()
        elif act=='adjust':
            # Financial figures (discount / contrast / VAT / price-list) are only
            # editable while the invoice is a DRAFT. Once Confirmed they are locked —
            # reject the change server-side even if a stale form is posted.
            _draft_now = (not inv.confirmed and not inv.locked and inv.status != 'Cancelled')
            if not _draft_now:
                flash('🔒 This invoice is Posted — discount & contrast are locked. Use "Reset to Draft" to change them.')
                log(f'BLOCKED adjust on non-draft INV-{iid:04d}')
                return redirect(url_for('billing.invoice_view', iid=iid))
            _nd=float(request.form.get('discount') or 0); _np=float(request.form.get('discount_pct') or 0)
            if (abs(_nd-(inv.discount or 0))>0.005 or abs(_np-(inv.discount_pct or 0))>0.005):
                if not can('discounts'):
                    flash('Discounts require authorization (Admin / Accountant / Branch Manager)')
                    return redirect(url_for('billing.invoice_view', iid=iid))
                _orig=inv.subtotal; _u=cur_user()
                inv.disc_reason=request.form.get('disc_reason') or 'Management Approval'
                inv.disc_by=(_u.name or _u.username) if _u else None
                inv.disc_date=today()
                log(f"DISCOUNT INV-{iid:04d}: {money(_nd)} + {_np}% of {money(_orig)} · reason={inv.disc_reason} · by={inv.disc_by}")
            inv.discount=_nd; inv.vat=float(request.form.get('vat') or 0)
            inv.discount_pct=_np
            _cv=request.form.get('contrast_amount')
            inv.contrast_amount=(float(_cv) if (_cv is not None and _cv.strip()!='') else None)
            _pl=request.form.get('price_list')
            if _pl in PRICE_LISTS: inv.price_list=_pl
            # invoice date — cashier may set/correct it (incl. a previous date) while draft
            _idate=(request.form.get('inv_date') or '').strip()
            if _idate:
                import datetime as _dtmod
                try:
                    _pd=_dtmod.date.fromisoformat(_idate)
                    if _pd > _dtmod.date.today():
                        flash('Invoice date cannot be in the future — using the date entered is only allowed up to today.')
                    else:
                        if str(inv.date) != _idate:
                            log(f"INVOICE DATE INV-{iid:04d}: {inv.date} → {_idate}")
                        inv.date=_idate
                except ValueError:
                    flash('Invoice date is not a valid date — left unchanged.')
            rd=request.form.get('referring_doctor_id'); inv.referring_doctor_id=int(rd) if rd else None; db.session.commit()
            flash('Other Info updated')
            return redirect(url_for('billing.invoice_view', iid=iid) + '#otherinfo')
        elif act=='pay':
            if inv.total>0 and inv.balance<=0.005:
                flash('Invoice is already fully paid — additional payment blocked.')
                log(f'BLOCKED duplicate payment on INV-{iid:04d}')
                return redirect(url_for('billing.invoice_view', iid=iid))
            _old=inv.paid or 0
            _outstanding=inv.balance   # current amount owed, before this payment
            try:
                _newpaid=float(request.form.get('paid') or 0)
            except (TypeError, ValueError):
                _newpaid=_old
            if _newpaid<0:
                flash('Payment amount cannot be negative.'); return redirect(url_for('billing.invoice_view', iid=iid))
            if (_newpaid - _old) > _outstanding + 0.005:
                flash(f'Payment exceeds balance. The outstanding balance is {money(max(_outstanding,0))} — please enter that amount or less.')
                log(f'BLOCKED overpayment on INV-{iid:04d} (tried {money(_newpaid-_old)}, balance {money(_outstanding)})')
                return redirect(url_for('billing.invoice_view', iid=iid))
            inv.paid=_newpaid
            _pm=request.form.get('pay_method')
            if _pm in PAY_METHODS: inv.pay_method=_pm
            inv.status='Paid' if inv.balance<=0.005 and inv.total>0 else ('Partial' if inv.paid>0 or inv.credits>0 else 'Unpaid')
            _delta=(inv.paid or 0)-_old
            _rct=None
            if _delta>0.005:
                _u=cur_user()
                _rct=PayReceipt(invoice_id=iid, amount=_delta, method=inv.pay_method or 'Cash',
                                ref=request.form.get('pay_ref') or '',
                                cashier=(_u.name or _u.username) if _u else '')
                db.session.add(_rct)
            db.session.commit()
            log(f'Payment recorded on INV-{iid:04d}', action_type='Payment', entity=f'INV-{iid:04d}',
                old=f'paid {money(_old)}', new=f'paid {money(inv.paid)} via {inv.pay_method or "Cash"}',
                reason=(request.form.get('pay_ref') or None))
            if _delta>0.005:
                from ..core.notify import notify_event
                notify_event('payment_received',
                             f'Payment received: {money(_delta)} on INV-{iid:04d} via {inv.pay_method or "Cash"}'
                             + (f' — {inv.patient.name}' if inv.patient else ''),
                             link=url_for('billing.invoice_view', iid=iid))
            _maybe_complete(inv)
            # NOTE: automatic consumable deduction on payment is DISABLED by request —
            # supplies are now deducted only via the manual Consume screen. The
            # consume_for_invoice() helper is kept but no longer called here.
            try:
                from .referrals import _release_gate; _release_gate(inv)
            except Exception: pass
            if _rct:
                try: repost_invoice(inv); repost_payment(inv)
                except Exception:
                    db.session.rollback()
                    from ..core.helpers import log_error; log_error(f'repost on payment INV-{iid:04d}')
                flash(f'✓ Payment recorded — Receipt RCT-{_rct.id:05d} is ready. Click "🖨 Print Receipt" when you want to print it.')
                return redirect(url_for('billing.invoice_view', iid=iid))
        elif act=='refund':
            amt=float(request.form.get('refund_amount') or 0)
            if amt<=0 or amt>(inv.paid or 0):
                flash('Refund must be between 0 and the amount paid')
                return redirect(url_for('billing.invoice_view', iid=iid))
            inv.paid=(inv.paid or 0)-amt
            inv.status='Paid' if inv.balance<=0.005 and inv.total>0 else ('Partial' if inv.paid>0 or inv.credits>0 else 'Unpaid')
            db.session.commit()
            log(f'REFUND {money(amt)} on INV-{iid:04d} ({request.form.get("refund_reason") or "no reason"}) — paid now {money(inv.paid)}')
            from ..core.notify import notify
            notify(f'Refund {money(amt)} issued on INV-{iid:04d}', link=f'/invoice/{iid}', role='accountant')
            flash(f'Refunded {money(amt)}')
        elif act=='guarantor':
            _was = inv.guarantor
            inv.guarantor = (request.form.get('guarantor') or '').strip()[:160] or None
            inv.due_date = (request.form.get('due_date') or '').strip() or None
            _u = cur_user()
            inv.guarantor_by = ((_u.name or _u.username) if _u else '') if inv.guarantor else None
            inv.guarantor_at = today() if inv.guarantor else None
            db.session.commit()
            log(f"GUARANTOR INV-{iid:04d}: {_was or '—'} → {inv.guarantor or 'cleared'}"
                + (f" · due {inv.due_date}" if inv.due_date else ''))
            flash('Credit details saved' if inv.guarantor else 'Guarantor cleared')
            return redirect(url_for('billing.invoice_view', iid=iid) + '#otherinfo')
        elif act=='sync':
            _n=_autofill_from_orders(inv)
            flash(f'⚡ Synced — {_n} pending order(s) added and posted to the ledger.' if _n else 'Posted to the ledger.')
        elif act=='cancel':
            if not (can('creditnotes') or can('discounts')):
                flash('You do not have permission to cancel an invoice.')
                return redirect(url_for('billing.invoice_view', iid=iid))
            _wasp=inv.paid or 0
            inv.status='Cancelled'; db.session.commit()
            log(f'Invoice INV-{iid:04d} cancelled', action_type='Cancel', entity=f'INV-{iid:04d}',
                old=f'Active (paid {money(_wasp)}, total {money(inv.total)})', new='Cancelled',
                reason=(request.form.get('reason') or request.form.get('cancel_reason') or None))
            from ..core.notify import notify_event
            notify_event('invoice_cancelled',
                         f'Invoice INV-{iid:04d} cancelled ({money(inv.total)})'
                         + (f' — {inv.patient.name}' if inv.patient else ''),
                         link=url_for('billing.invoice_view', iid=iid))
            # reverse ALL accounting for this invoice: sale, payment AND commission accrual
            for _ref in (f'INV-{iid:04d}', f'PAY-{iid:04d}', f'COMM-{iid:04d}'):
                for _e in JournalEntry.query.filter_by(ref=_ref).all():
                    db.session.delete(_e)
            # drop any commission/radiologist payables raised for this invoice
            try:
                for _a in CommissionAccrual.query.filter_by(invoice_id=iid).all():
                    db.session.delete(_a)
            except Exception:
                pass
            # free the linked lab/radiology orders so the visit can be re-invoiced
            try:
                for _o in LabOrder.query.filter_by(invoice_id=iid).all():
                    _o.invoice_id = None; _o.paid_gate = False
                for _o in RadOrder.query.filter_by(invoice_id=iid).all():
                    _o.invoice_id = None; _o.paid_gate = False
            except Exception:
                pass
            db.session.commit()
            flash('Invoice cancelled — sale, payment and commission all reversed from Accounting.')
            return redirect(url_for('billing.invoice_view', iid=iid))
        elif act=='delete':
            _u = cur_user()
            if not (_u and _u.role == 'super_admin'):
                flash('Only the administrator can delete an invoice.')
                log(f'DENIED delete INV-{iid:04d} by {_u.username if _u else "?"}')
                return redirect(url_for('billing.invoice_view', iid=iid))
            _is_draft_del = not (inv.confirmed or inv.locked or (inv.paid or 0) > 0 or inv.credits or inv.status == 'Cancelled')
            if not _is_draft_del:
                # posted/paid → reverse ALL accounting first so the books stay balanced:
                # sale, payment AND doctor/radiologist commission (journals + accruals)
                for _ref in (f'INV-{iid:04d}', f'PAY-{iid:04d}', f'COMM-{iid:04d}'):
                    for _e in JournalEntry.query.filter_by(ref=_ref).all():
                        db.session.delete(_e)
                try:
                    for _a in CommissionAccrual.query.filter_by(invoice_id=iid).all():
                        db.session.delete(_a)
                except Exception:
                    pass
                try:
                    for _cn in CreditNote.query.filter_by(invoice_id=iid).all():
                        db.session.delete(_cn)
                except Exception:
                    pass
            # free the linked lab/radiology orders so the visit can be re-invoiced
            try:
                for _o in LabOrder.query.filter_by(invoice_id=iid).all():
                    _o.invoice_id = None; _o.paid_gate = False
                for _o in RadOrder.query.filter_by(invoice_id=iid).all():
                    _o.invoice_id = None; _o.paid_gate = False
            except Exception:
                pass
            for _it in list(inv.items):
                db.session.delete(_it)
            log(f"INV-{iid:04d} deleted ({'draft' if _is_draft_del else 'posted — sale/payment/commission reversed'})",
                action_type='Delete', entity=f'INV-{iid:04d}',
                old=f'total {money(inv.total)}, paid {money(inv.paid or 0)}', new='Deleted',
                reason=(request.form.get('reason') or None))
            db.session.delete(inv); db.session.commit()
            flash('🗑 Draft invoice deleted.' if _is_draft_del
                  else '🗑 Invoice deleted — sale, payment and commission all reversed automatically.')
            return redirect(url_for('modules.module', mod='invoices'))
        try: repost_invoice(inv); repost_payment(inv)
        except Exception as _e:
            db.session.rollback()
            from ..core.helpers import log_error; log_error(f'repost after action INV-{iid:04d}')
        return redirect(url_for('billing.invoice_view', iid=iid))
    # ── Odoo account.move form ───────────────────────────────────────────────
    dispst, dispclr = _display_status(inv)
    from ..core.posting import commission_preview
    _prev_docname, _prev_doc, _prev_radname, _prev_rad = commission_preview(inv)
    _can_adv = can('discounts')
    _ready_for_payment = bool(inv.confirmed or (inv.paid or 0) > 0 or inv.locked)
    _is_draft = (not inv.confirmed and not inv.locked and inv.status != 'Cancelled')
    _paid_full = (inv.total > 0 and inv.balance <= 0.005 and inv.status != 'Cancelled')
    _can_pay = (_ready_for_payment and inv.balance > 0.005 and inv.status != 'Cancelled')
    _edit = _is_draft   # Odoo: only a draft invoice's lines are editable
    svc_opts = "".join(f"<option value='{s.id}'>{h(s.name)} — {money(s.price)}</option>"
                       for s in Service.query.filter_by(active=True).order_by(Service.name).all())
    doc_opts = "".join(f"<option value='{d.id}' {'selected' if inv.referring_doctor_id==d.id else ''}>{h((d.code + ' · ') if d.code else '')}{h(d.name)}</option>"
                       for d in Doctor.query.filter_by(active=True).order_by(Doctor.name).all())

    # ---- Invoice lines (Odoo grid) ----
    def _line_row(it):
        _del = ""
        if _edit:
            _del = (f"<form method='post' style='display:inline'><input type='hidden' name='act' value='delitem'>"
                    f"<input type='hidden' name='item_id' value='{it.id}'>"
                    f"<button class='btn gh sm' title='Remove line'>🗑</button></form>")
        _src = f"<div class='src'>{h(it.source_label)}</div>" if it.source_label else ''
        return (f"<tr><td><b>{h(it.desc)}</b>{_src}</td>"
                f"<td class='num'>{it.qty:g}</td>"
                f"<td class='num'>{money(it.price)}</td>"
                f"<td class='num'>{money(it.qty*it.price)}</td>"
                f"<td class='num'>{_del}</td></tr>")
    items = ''.join(_line_row(it) for it in inv.items)
    if not inv.items:
        items = ("<tr><td colspan='5' style='color:var(--muted);padding:26px;text-align:center'>"
                 "No lines yet.<br><small>Lab, Radiology &amp; Consultation orders flow in automatically when requested — "
                 "or use “Add a line”.</small></td></tr>")

    # ---- Add a line (draft only) ----
    if not _edit and inv.status != 'Cancelled':
        add_line = ("<div class='o-addline' style='color:var(--muted);font-size:12.5px'>"
                    "🔒 Posted — lines are locked. Use <b>Reset to Draft</b> to change them.</div>")
    elif inv.referral_id:
        add_line = ("<div class='o-addline' style='color:var(--muted);font-size:12.5px'>"
                    f"⚡ Automatic invoice — lines came from Doctor Request <b>REF-{inv.referral_id:04d}</b> and update automatically.</div>")
    elif _can_adv:
        add_line = f"""<div class="o-addline">
          <span class="lnk" onclick="var f=document.getElementById('addf');f.classList.toggle('on');if(f.classList.contains('on'))f.querySelector('select,input').focus();">➕ Add a line</span>
          <div class="o-add-form" id="addf"><form method="post" class="fg"><input type="hidden" name="act" value="additem">
            <div class="fld full"><label>Product / Service</label><select name="service_id"><option value="">— custom line below —</option>{svc_opts}</select></div>
            <div class="fld"><label>Or custom label</label><input name="desc"></div>
            <div class="fld"><label>Quantity</label><input name="qty" type="number" step="any" value="1"></div>
            <div class="fld"><label>Unit Price</label><input name="price" type="number" step="any" value="0"></div>
            <div class="fld full"><label>Reason <small style="color:var(--muted)">(optional)</small></label><input name="reason" placeholder="e.g. walk-in item (optional)"></div>
            <div class="fld" style="justify-content:flex-end"><button class="btn primary">Add</button></div>
          </form></div></div>"""
    else:
        add_line = ''

    # ---- Totals (Odoo bottom-right stack) ----
    _disc_total = (inv.discount or 0) + inv.subtotal*(inv.discount_pct or 0)/100.0
    _paid_line = (f"<div class='r'><span class='k'>Paid</span><span>-{money(inv.paid)}</span></div>"
                  if (inv.paid or 0) else '')
    _receipt_lnk = (f"<div style='text-align:right;margin-top:6px'><a class='btn sm' target='_blank' "
                    f"href='/receipt/{inv.receipts[-1].id}' data-pdf='/receipt/{inv.receipts[-1].id}/pdf'>🖨 Print Receipt</a></div>"
                    if (_paid_full and inv.receipts) else '')
    totals = f"""<div class="o-totals">
        <div class="r"><span class="k">Untaxed Amount</span><span>{money(inv.subtotal)}</span></div>
        {f'<div class="r"><span class="k">Discount</span><span>-{money(_disc_total)}</span></div>' if _disc_total else ''}
        <div class="r"><span class="k">Tax / VAT</span><span>{money(inv.vat or 0)}</span></div>
        <div class="r grand"><span>Total</span><span>{money(inv.total)}</span></div>
        {_paid_line}
        <div class="r due"><span>Amount Due</span><span>{money(inv.balance)}</span></div>
      </div>{_receipt_lnk}"""

    # ---- Header groups (Customer / Invoice info) ----
    _p = inv.patient
    if _p:
        _cust = (f"<a href='{url_for('patients.patient_detail', pid=_p.id)}' style='color:var(--petrol);font-weight:700'>{h(_p.name)}</a>"
                 f"<div style='font-size:12px;color:var(--muted)'>MRN {h(_p.mrn or '—')} · {h(_p.gender or '—')}"
                 f"{' · Age '+str(_p.age) if _p.age is not None else ''} · {h(_p.phone or '—')}</div>")
    else:
        _cust = "<span style='color:var(--muted)'>Walk-in (no patient)</span>"
    _refdoc = _dlabel(inv.doctor_ref) if inv.doctor_ref else '—'
    _branch = inv.branch.name if inv.branch else '—'
    # Guarantor is intentionally NOT shown here on the invoice. It lives under the
    # Other Info tab (to set/edit) and on the dedicated Loan Invoice document (to see
    # who stands behind the debt). Keeping it off the main invoice keeps it clean.
    head = f"""<div class="o-head">
      <div>
        <div class="o-row"><span class="k">Customer</span><span class="v">{_cust}</span></div>
        <div class="o-row"><span class="k">Referring Doctor</span><span class="v">{h(_refdoc)}</span></div>
        {f'<div class="o-row"><span class="k">Source</span><span class="v">Doctor Request REF-{inv.referral_id:04d}</span></div>' if inv.referral_id else ''}
      </div>
      <div>
        <div class="o-row"><span class="k">Invoice Date</span><span class="v">{h(inv.date)}</span></div>
        <div class="o-row"><span class="k">Branch</span><span class="v">{h(_branch)}</span></div>
        <div class="o-row"><span class="k">Price List</span><span class="v">{h(inv.price_list or 'Cash')}</span></div>
        {f'<div class="o-row"><span class="k">Created by</span><span class="v">{h(inv.created_by)}{(" · " + h(inv.created_at)) if inv.created_at else ""}</span></div>' if inv.created_by else ''}
      </div>
    </div>"""

    # ---- Other Info tab (pricing, commission, guarantor, receipts, refund/cancel) ----
    # Discount / contrast / price-list / VAT are only editable while the invoice is a
    # DRAFT and the user has the discounts permission. Once Confirmed (Posted) these
    # financial figures lock, exactly like the invoice lines do.
    _can_adjust = _can_adv and _is_draft
    _dis = '' if _can_adjust else 'disabled'
    # contrast income excluded from the doctor commission (manual amount wins, else auto-detected)
    from ..core.posting import invoice_contrast_income as _ici
    _contrast_ded = _ici(inv)
    _manual_c = inv.contrast_amount is not None
    _comm_lbl = 'Doctor Commission'
    _extra = []
    if inv.discount or inv.discount_pct:
        _extra.append('discount')
    if _contrast_ded > 0.005:
        _extra.append('contrast')
    if _extra:
        _comm_lbl += ' (after ' + ' &amp; '.join(_extra) + ')'
    _contrast_note = (f"<div style='font-size:11px;color:var(--muted);margin:2px 0 6px'>Contrast income "
                      f"({'manual' if _manual_c else 'auto'} · booked as service income, kept by the center): "
                      f"<b>{money(_contrast_ded)}</b> — doctor commission is calculated on the net study price"
                      f"</div>"
                      if _contrast_ded > 0.005 else '')
    _comm_rows = f"""<div class="o-row"><span class="k">{_comm_lbl}</span>
        <span class="v">{money(_prev_doc)}{f' · {h(_prev_docname)}' if _prev_docname else ''}</span></div>
      {_contrast_note}
      <div class="o-row"><span class="k">Radiologist Fee <small style="color:var(--muted)">($/scan report)</small></span><span class="v">{money(_prev_rad)}{f' · {h(_prev_radname)}' if _prev_radname else ''}</span></div>"""
    _disc_by = (f"<div style='font-size:11px;color:var(--muted);margin:4px 0'>Discount approved by <b>{h(inv.disc_by)}</b> · {h(inv.disc_date or '')} · {h(inv.disc_reason or '')}</div>"
                if inv.disc_by else '')
    # ---- Credit / Guarantor: locks once saved; an Edit button unlocks it ----
    _guar_edit = request.args.get('edit_guar') == '1'
    _guar_saved = bool((inv.guarantor or '').strip())
    _guar_granted = (f"<div style='font-size:11.5px;color:var(--muted);margin-top:4px'>Credit granted by <b>{h(inv.guarantor_by)}</b> on {h(inv.guarantor_at or '')}</div>"
                     if inv.guarantor_by else '')
    if _guar_saved and not _guar_edit:
        # LOCKED view — read-only, with an Edit button to change it
        _guarantor_block = (
            "<div style='margin-top:12px;border-top:1px solid var(--line);padding-top:12px'>"
            "<div class='o-row'><span class='k'>Credit / Guarantor</span>"
            f"<span class='v' style='flex:1'><b>🔒 {h(inv.guarantor)}</b></span></div>"
            + (f"<div class='o-row'><span class='k'>Payment Due Date</span><span class='v'>{h(inv.due_date)}</span></div>" if inv.due_date else "")
            + f"<div style='text-align:right;margin-top:6px'><a class='btn gh sm' href='{url_for('billing.invoice_view', iid=iid)}?edit_guar=1#otherinfo'>✎ Edit credit details</a></div>"
            + "</div>" + _guar_granted)
    else:
        # EDITABLE form (new credit, or after clicking Edit)
        _guarantor_block = (
            '<form method="post" style="margin-top:12px;border-top:1px solid var(--line);padding-top:12px"><input type="hidden" name="act" value="guarantor">'
            f'<div class="o-row"><span class="k">Credit / Guarantor</span><span class="v" style="flex:1"><input name="guarantor" value="{h(inv.guarantor or "")}" placeholder="e.g. Modern Hospital / Cabdi Nuur Warsame" maxlength="160" style="width:100%;max-width:360px"></span></div>'
            f'<div class="o-row"><span class="k">Payment Due Date</span><span class="v"><input type="date" name="due_date" value="{h(inv.due_date or "")}"> <small style="color:var(--muted)">for credit / loan sales</small></span></div>'
            '<div style="text-align:right;margin-top:4px"><button class="btn sm primary">Save credit details</button></div>'
            '</form>' + _guar_granted)
    _receipts = ''
    if inv.receipts:
        _receipts = ("<div style='margin-top:12px'><div style='font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px'>Receipts</div>"
                     + ''.join(f"<div style='display:flex;justify-content:space-between;font-size:13px;padding:2px 0'>"
                               f"<span>RCT-{r_.id:05d} · {h(r_.date)} · {h(r_.method)}</span>"
                               f"<span>{money(r_.amount)} <a class='btn gh sm' href='/receipt/{r_.id}' data-pdf='/receipt/{r_.id}/pdf' target='_blank'>🖨</a></span></div>"
                               for r_ in inv.receipts) + "</div>")
    _refund_cancel = ''
    if _can_adv and not inv.locked and inv.status != 'Cancelled':
        _refund_cancel = f"""<details style="margin-top:14px;border-top:1px solid var(--line);padding-top:10px"><summary style="cursor:pointer;color:var(--red);font-weight:700;font-size:13px">Refund &amp; Cancel</summary>
        <form method="post" class="fg" style="margin-top:8px"><input type="hidden" name="act" value="refund">
          <div class="fld"><label>Refund Amount</label><input name="refund_amount" type="number" step="any" value="0"></div>
          <div class="fld"><label>Reason</label><input name="refund_reason"></div>
          <div class="fld full"><button class="btn sm" style="color:var(--red)">↩ Issue Refund</button></div></form>
        <form method="post" onsubmit="var r=prompt('Reason for cancelling this invoice?'); if(r===null)return false; this.reason.value=r; return true" style="margin-top:6px"><input type="hidden" name="act" value="cancel"><input type="hidden" name="reason" value="">
          <button class="btn sm" style="width:100%;color:var(--red)">✕ Cancel Invoice</button></form></details>"""
    other = f"""<form method="post"><input type="hidden" name="act" value="adjust">
        <div class="o-head" style="margin:4px 0">
          <div>
            <div class="o-row"><span class="k">Referring Doctor</span><span class="v"><select name="referring_doctor_id"><option value="">— none —</option>{doc_opts}</select></span></div>
            <div class="o-row"><span class="k">Invoice Date</span><span class="v"><input name="inv_date" type="date" value="{h(inv.date or '')}" max="{today()}" {_dis} style="width:150px"> <small style="color:var(--muted)">can be a previous date</small></span></div>
            <div class="o-row"><span class="k">Price List</span><span class="v"><select name="price_list" {_dis}>{''.join(f"<option {'selected' if (inv.price_list or 'Cash')==pl else ''}>{pl}</option>" for pl in PRICE_LISTS)}</select></span></div>
            <div class="o-row"><span class="k">Discount ($)</span><span class="v"><input name="discount" type="number" step="any" value="{inv.discount or 0}" {_dis} style="width:110px;text-align:right"></span></div>
      <div class="o-row"><span class="k">Contrast ($) <small style="color:var(--muted)">income · blank = auto</small></span><span class="v"><input name="contrast_amount" type="number" step="any" value="{'' if inv.contrast_amount is None else inv.contrast_amount}" placeholder="auto" {_dis} style="width:110px;text-align:right"></span></div>
            <div class="o-row"><span class="k">Discount (%)</span><span class="v"><input name="discount_pct" type="number" step="any" value="{inv.discount_pct or 0}" {_dis} style="width:110px;text-align:right"></span></div>
          </div>
          <div>
            <div class="o-row"><span class="k">Discount Reason</span><span class="v"><select name="disc_reason" {_dis}>{''.join(f"<option {'selected' if (inv.disc_reason or 'Management Approval')==x else ''}>{x}</option>" for x in ('Staff','Charity','Promotion','Management Approval','Insurance Agreement'))}</select></span></div>
            <div class="o-row"><span class="k">Tax / VAT</span><span class="v"><input name="vat" type="number" step="any" value="{inv.vat or 0}" {_dis} style="width:110px;text-align:right"></span></div>
            {_comm_rows}
          </div>
        </div>
        {'' if _can_adv else "<div style='font-size:11.5px;color:var(--muted)'>Discounts &amp; price-list overrides require Manager / Accountant / Admin.</div>"}
        {('<div style="text-align:right"><button class="btn sm">Update</button></div>') if _can_adjust else ("<div style='font-size:11.5px;color:var(--muted)'>🔒 Posted — discount &amp; contrast are locked. Use <b>Reset to Draft</b> to change them.</div>" if not _is_draft else '')}
      </form>
      {_disc_by}
      {_guarantor_block}
      {_receipts}{_refund_cancel}"""

    # ---- Header action buttons (Odoo order) ----
    _hdr = []
    if _is_draft:
        _hdr.append("<form method='post' style='display:inline'><input type='hidden' name='act' value='confirm'>"
                    "<button class='btn primary sm'>Confirm Invoice</button></form>")
    if _can_pay:
        _hdr.append("<button class='btn primary sm' onclick=\"MDCPay.open()\">💵 Register Payment</button>")
    if inv.confirmed and not inv.locked and inv.status != 'Cancelled':
        _paid_inv = (inv.paid or 0) > 0 or inv.credits
        if not _paid_inv:
            _hdr.append("<form method='post' style='display:inline'><input type='hidden' name='act' value='unconfirm'>"
                        "<button class='btn sm'>↺ Reset to Draft</button></form>")
        elif can('discounts') or can('creditnotes'):
            _hdr.append("<form method='post' style='display:inline' "
                        "onsubmit=\"var r=prompt('Reset this PAID invoice to draft so you can edit it? The payment and commission are reversed automatically. Type a reason:'); if(r===null||r==='')return false; this.reason.value=r; return true\">"
                        "<input type='hidden' name='act' value='unconfirm'><input type='hidden' name='reason' value=''>"
                        "<button class='btn sm'>↺ Reset to Draft</button></form>")
    _hdr.append(f"<button class='btn sm' onclick=\"MDCDoc.open({{print:'{url_for('billing.invoice_print',iid=iid)}?auto=1',download:'{url_for('billing.invoice_pdf_dl',iid=iid)}',open:'{url_for('billing.invoice_print',iid=iid)}',title:'Invoice INV-{iid:04d}'}})\">🖨 Print</button>")
    if (inv.balance > 0.005) or (inv.pay_method in ('Credit', 'Insurance')):
        _loan_url = url_for('billing.invoice_print', iid=iid) + '?loan=1'
        if (inv.guarantor or '').strip():
            _loan_onclick = (f"MDCDoc.open({{print:'{_loan_url}&auto=1',open:'{_loan_url}',"
                             f"html:'{_loan_url}',title:'Loan Invoice INV-{iid:04d}'}})")
        else:
            # no guarantor yet → don't open the print dialog; point them to Other Info
            _loan_onclick = ("alert('🤝 Fadlan gali macluumaadka damiinka (Guarantor) tab-ka Other Info "
                             "ka hor inta aan la daabicin Loan Invoice.\\n\\nPlease fill in the guarantor "
                             "details under Other Info before printing the Loan Invoice.');"
                             "var t=document.querySelector('.o-tab-h[data-t=\\'other\\']');"
                             "if(t){t.click();}")
        _hdr.append(f"<button class='btn sm' onclick=\"{_loan_onclick}\" title='Prints the invoice with the customer contact, guarantor and due date, plus signature lines — requires a guarantor on file'>📝 Loan Invoice</button>")
    _hdr.append(f"<a class='btn sm' href='{url_for('billing.invoice_new')}'>+ New</a>")
    # error-correction: DELETE is admin-only; Cancel (reverse, keep record) stays for supervisors
    _u_del = cur_user()
    _is_admin = bool(_u_del and _u_del.role == 'super_admin')
    if _is_draft and _edit:
        if _is_admin:
            _hdr.append("<form method='post' style='display:inline' "
                        "onsubmit=\"return confirm('Delete this draft invoice? This cannot be undone.')\">"
                        "<input type='hidden' name='act' value='delete'>"
                        "<button class='btn sm' style='color:var(--red)'>🗑 Delete</button></form>")
    elif inv.status != 'Cancelled' and not inv.locked:
        if can('creditnotes') or can('discounts'):
            _hdr.append("<form method='post' style='display:inline' "
                        "onsubmit=\"var r=prompt('Reason for cancelling this invoice? (reverses the sale, payment &amp; commission)'); if(r===null)return false; this.reason.value=r; return true\">"
                        "<input type='hidden' name='act' value='cancel'><input type='hidden' name='reason' value=''>"
                        "<button class='btn sm' style='color:var(--red)'>✕ Cancel</button></form>")
        if _is_admin:
            _hdr.append("<form method='post' style='display:inline' "
                        "onsubmit=\"var r=prompt('DELETE this invoice permanently? The sale, payment and doctor commission are reversed automatically. Type a reason to confirm:'); if(r===null||r==='')return false; this.reason.value=r; return true\">"
                        "<input type='hidden' name='act' value='delete'><input type='hidden' name='reason' value=''>"
                        "<button class='btn sm' style='color:var(--red)'>🗑 Delete</button></form>")
    _hdr.append(f"<a class='btn sm' href='{url_for('modules.module', mod='invoices')}'>← Back</a>")
    actionbar = INV_ODOO_CSS + f"""<div class='panel' style='position:sticky;top:8px;z-index:40'>
      <div class='pad' style='display:flex;align-items:center;gap:9px;flex-wrap:wrap'>
        <b style='font-family:var(--fd,inherit);font-size:15px;color:var(--petrol)'>INV-{inv.id:04d}</b>
        {_odoo_statusbar(inv)}
        <div class='sp' style='flex:1'></div>
        {''.join(_hdr)}
      </div></div>
      <script>document.addEventListener('keydown',function(e){{
        if(e.ctrlKey && e.key==='p'){{e.preventDefault();window.open('{url_for('billing.invoice_print',iid=iid)}','_blank');}}
        if(e.ctrlKey && e.key==='n'){{e.preventDefault();location.href='/invoice/new';}}
        if(e.ctrlKey && e.key==='Enter'){{e.preventDefault();if(window.MDCPay)MDCPay.open();}}
      }});</script>"""

    # ---- Register Payment modal (Odoo wizard) ----
    if _can_pay:
        paymodal = f"""<div class="mdcpay" id="paymodal" hidden>
        <div class="mdcpay-back" onclick="MDCPay.close()"></div>
        <div class="mdcpay-box" role="dialog" aria-label="Register Payment">
          <div class="mdcpay-hd">Register Payment<button class="mdcpay-x" onclick="MDCPay.close()" aria-label="Close">&times;</button></div>
          <form method="post" class="mdcpay-bd"><input type="hidden" name="act" value="pay">
            <input type="hidden" name="paid" id="paidHidden" value="{(inv.total if inv.balance>0.005 else inv.paid) or 0}">
            <div class="mdcpay-due"><span>Amount Due — <b style="font-size:13px;font-weight:600">INV-{inv.id:04d}</b></span><b>{money(inv.balance)}</b></div>
            <label>Pay</label>
            <div style="display:flex;gap:8px;margin-bottom:2px">
              <button type="button" class="btn primary" id="btnFull" style="flex:1" onclick="MDCPay.full()">● Full</button>
              <button type="button" class="btn" id="btnPart" style="flex:1" onclick="MDCPay.partial()">◐ Partial</button>
            </div>
            <label>Amount to pay now</label>
            <input id="paynow" type="number" step="any" min="0" max="{inv.balance}" value="{inv.balance}" oninput="MDCPay.sync()" autofocus>
            <div id="remHint" style="font-size:12px;color:var(--muted);margin-top:4px"></div>
            <label>Journal (Payment Method)</label>
            <select name="pay_method">{''.join(f"<option {'selected' if (inv.pay_method or 'Cash')==pm else ''}>{pm}</option>" for pm in PAY_METHODS)}</select>
            <label>Payment Date</label>
            <input name="pay_date" type="date" value="{today()}">
            <label>Memo / Reference</label>
            <input name="pay_ref" placeholder="e.g. EVC txn id, cheque no.">
            <div class="mdcpay-ft"><button type="button" class="btn" onclick="MDCPay.close()">Discard</button>
              <button class="btn primary" id="payGo">✓ Create Payment</button></div>
          </form>
        </div></div>
        <script>window.MDCPay=(function(){{
          var OLD={inv.paid or 0}, BAL={inv.balance};
          function sync(){{
            var el=document.getElementById('paynow'); var v=parseFloat(el.value)||0;
            if(v<0){{v=0;el.value=0;}} if(v>BAL+0.005){{v=BAL;el.value=BAL;}}
            document.getElementById('paidHidden').value=(OLD+v).toFixed(2);
            var rem=BAL-v; if(rem<0)rem=0;
            var full=Math.abs(v-BAL)<0.005;
            document.getElementById('remHint').innerHTML = full
              ? '<span style=\\'color:var(--green)\\'>Pays the invoice in full — nothing left owing.</span>'
              : 'Partial — remaining after this payment: <b>$'+rem.toFixed(2)+'</b>';
            document.getElementById('btnFull').classList.toggle('primary',full);
            document.getElementById('btnPart').classList.toggle('primary',!full && v>0);
            document.getElementById('payGo').textContent = full ? '✓ Pay in full' : '✓ Pay $'+v.toFixed(2);
          }}
          return {{
            open:function(){{var m=document.getElementById('paymodal');if(m){{m.hidden=false;var a=document.getElementById('paynow');if(a)setTimeout(function(){{a.focus();a.select();}},30);sync();}}}},
            close:function(){{var m=document.getElementById('paymodal');if(m)m.hidden=true;}},
            full:function(){{document.getElementById('paynow').value=BAL;sync();}},
            partial:function(){{var f=document.getElementById('paynow');f.value='';f.focus();sync();}},
            sync:sync
          }};
        }})();
        document.addEventListener('keydown',function(e){{if(e.key==='Escape')MDCPay.close();}});</script>"""
    else:
        paymodal = "<script>window.MDCPay={open:function(){},close:function(){}};</script>"

    # ---- The sheet ----
    _title_main = 'Draft Invoice' if _is_draft else (f'INV-{inv.id:04d}' if inv.status != 'Cancelled' else 'Cancelled Invoice')
    _title_sub = f"INV-{inv.id:04d} · {h(_p.name) if _p else 'Walk-in'}"
    sheet = f"""<div class="o-sheet inv-sheet">{_pay_ribbon(inv)}
      <div class="o-title">{_title_main}<small>{_title_sub}</small></div>
      {head}
      <div class="o-tabs">
        <button class="o-tab-h on" data-t="lines" onclick="oTab(this)">Invoice Lines</button>
        <button class="o-tab-h" data-t="other" onclick="oTab(this)">Other Info</button>
      </div>
      <div class="o-tab on" id="t-lines">
        <table class="o-lines"><thead><tr><th>Product / Service</th><th class="num">Qty</th><th class="num">Unit Price</th><th class="num">Amount</th><th></th></tr></thead>
          <tbody>{items}</tbody></table>
        {add_line}
        {totals}
      </div>
      <div class="o-tab" id="t-other">{other}</div>
    </div>
    {paymodal}
    <script>function oTab(b){{var t=b.getAttribute('data-t');
      document.querySelectorAll('.o-tab-h').forEach(function(x){{x.classList.toggle('on',x===b);}});
      document.getElementById('t-lines').classList.toggle('on',t==='lines');
      document.getElementById('t-other').classList.toggle('on',t==='other');}}
    // Open the Other Info tab automatically when the page is opened with the
    // #otherinfo anchor (used after saving discount/contrast or credit details)
    // or with ?edit_guar=1, so the user stays on Other Info instead of Lines.
    (function(){{
      if(location.hash==='#otherinfo' || /[?&]edit_guar=1/.test(location.search)){{
        var t=document.querySelector('.o-tab-h[data-t="other"]'); if(t){{oTab(t);}}
      }}
    }})();</script>"""

    body = actionbar + sheet
    track_view('invoice', inv.id, f"INV-{inv.id:04d} · {inv.patient.name if inv.patient else 'Walk-in'}", url_for('billing.invoice_view', iid=inv.id))
    # read-only: prompt to sync/post rather than doing it silently on GET
    _posted = JournalEntry.query.filter(JournalEntry.ref.in_([f"INV-{inv.id:04d}", f"PAY-{inv.id:04d}"])).first() is not None
    _lockbar = ''
    if inv.locked:
        _u = cur_user()
        _reset = (f"<form method='post' action='{url_for('billing.invoice_reset',iid=inv.id)}' "
                  f"onsubmit=\"var r=prompt('Reason for resetting to draft?'); if(r===null)return false; this.reason.value=r; return true\" style='margin-left:auto'>"
                  f"<input type='hidden' name='reason' value=''>"
                  f"<button class='btn sm'>↺ Reset to Draft</button></form>") if (_u and _u.role == 'super_admin') else ''
        _lockbar = ("<div class='panel' style='border-left:3px solid var(--green)'>"
                    "<div class='pad' style='display:flex;gap:12px;align-items:center;flex-wrap:wrap'>"
                    "<span style='font-size:13px'>🔒 <b>Completed &amp; locked.</b> No further invoice, service or payment changes are allowed. "
                    + ('An administrator can reset it to draft.' if _reset else 'Contact an administrator to reset it.')
                    + f"</span>{_reset}</div></div>")
    _pending = _pending_orders_count(inv)
    _syncbar = ''
    if inv.status != 'Cancelled' and (_pending or (inv.total > 0 and not _posted)):
        _msgs = []
        if _pending: _msgs.append(f"{_pending} pending lab/radiology order(s) not yet on this invoice")
        if inv.total > 0 and not _posted: _msgs.append("not yet posted to the ledger")
        _syncbar = ("<div class='panel' style='border-left:3px solid var(--amber)'>"
                    "<div class='pad' style='display:flex;gap:12px;align-items:center;flex-wrap:wrap'>"
                    f"<span style='font-size:13px'>⚡ {' · '.join(_msgs)}.</span>"
                    "<form method='post' style='margin-left:auto'><input type='hidden' name='act' value='sync'>"
                    "<button class='btn primary sm'>Sync orders &amp; Post to ledger</button></form></div></div>")
    _crumbs = [('Invoices', url_for('modules.module', mod='invoices'))]
    if inv.patient:
        _crumbs.append((inv.patient.name, url_for('patients.patient_detail', pid=inv.patient_id)))
    _crumbs.append((f"INV-{inv.id:04d}", None))
    _ns_inv = ''
    if not getattr(inv, 'locked', False) and inv.balance <= 0.005 and (inv.total or 0) > 0:
        _pl = LabOrder.query.filter(LabOrder.invoice_id == inv.id, LabOrder.status.in_(['Requested', 'Collected', 'Received'])).first()
        _pr = RadOrder.query.filter(RadOrder.invoice_id == inv.id, RadOrder.status.in_(['Requested', 'Imaged'])).first()
        if _pl:
            _u = url_for('lab.lab_result', oid=_pl.id) if _pl.status == 'Received' else url_for('modules.module', mod='lab')
            _ns_inv = next_step(_u, 'Proceed to Laboratory', f'{_pl.service.name if _pl.service else "Test"} · {_pl.status}')
        elif _pr:
            _u = url_for('rad.rad_report', oid=_pr.id) if _pr.status == 'Imaged' else url_for('modules.module', mod='radiology')
            _ns_inv = next_step(_u, 'Proceed to Radiology', f'{_pr.modality or ""} · {_pr.status}')
    return page(f'Invoice INV-{inv.id:04d}',
                f"<div class='oform'>{actionbar}{_lockbar}{_syncbar}{_ns_inv}{_refnote}{sheet}{_acct_link_panel(inv)}</div>",
                'invoices', crumbs=_crumbs)


def _acct_link_panel(inv):
    """Show the journal entries this invoice/payment posted to (billing↔accounting link)."""
    from ..models import JournalEntry, Account
    # Accounting detail is for accountants/managers — cashiers get a clean screen.
    if not (can('journal') or can('discounts')):
        return ''
    refs = [f"INV-{inv.id:04d}", f"PAY-{inv.id:04d}", f"CN-{inv.id:04d}"]
    entries = JournalEntry.query.filter(JournalEntry.ref.in_(refs)).order_by(JournalEntry.id).all()
    if not entries:
        return ("<div class='panel'><div class='ph'><h2>Accounting</h2></div><div class='pad' style='font-size:13px;color:var(--muted)'>"
                "This invoice has not posted to the ledger yet."
                "<form method='post' style='margin-top:8px'><input type='hidden' name='act' value='sync'>"
                "<button class='btn primary sm'>⚡ Post to ledger now</button></form></div></div>")
    rows = ''
    for e in entries:
        lines = ''
        for l in e.lines:
            a = Account.query.get(l.account_id)
            lines += (f"<tr><td style='padding-left:20px;color:var(--muted)'>{h(a.code if a else '')} · {h(a.name if a else '—')}</td>"
                      f"<td class='num'>{money(l.debit) if l.debit else ''}</td>"
                      f"<td class='num'>{money(l.credit) if l.credit else ''}</td></tr>")
        rows += (f"<tr><td><a href='{url_for('acct.journal_entry', eid=e.id)}' style='color:var(--petrol);font-weight:600'>{h(e.ref or ('JV-%04d'%e.id))}</a>"
                 f"<div style='font-size:11px;color:var(--muted)'>{h(e.date)} · {h(e.memo or '')}</div></td>"
                 f"<td class='num'>{money(e.total_debit)}</td><td class='num'>{money(e.total_credit)}</td></tr>{lines}")
    return (f"<div class='panel'><div class='ph'><h2>Accounting</h2>"
            f"<span class='so'>auto-posted double-entry</span></div>"
            f"<div class='tw'><table><thead><tr><th>Journal Entry</th><th class='num'>Debit</th><th class='num'>Credit</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            f"<div class='pad' style='font-size:12px;color:var(--muted)'>💡 Every invoice and payment posts automatically to the General Ledger. "
            f"Click a reference to open the journal entry.</div></div>")

@bp.route('/invoice/<int:iid>/pdf')
@login_required
def invoice_pdf_dl(iid):
    inv=Invoice.query.get_or_404(iid)
    from ..core.helpers import setting as _setting
    from ..core.security import can_see
    if not can_see(inv):
        abort(403)
    _dl = request.args.get('dl')
    _disp = 'attachment' if _dl else 'inline'
    _fname = f'INV-{iid:04d}.pdf'

    # BEST: render with headless Chromium exactly as the browser's Print → Save PDF
    # (fills the page, footer glued to the bottom, watermark centred).
    from ..core.htmlpdf import (chrome_available, chrome_pdf_from_url,
                                available as _wk_ok, html_to_pdf)
    if chrome_available():
        print_url = url_for('billing.invoice_print', iid=iid, _external=True)
        cookies = _session_cookies_for(print_url)
        pdf = chrome_pdf_from_url(print_url, cookies=cookies)
        if pdf:
            log(f'{"Downloaded" if _dl else "Opened"} PDF INV-{iid:04d}')
            return Response(pdf, mimetype='application/pdf',
                            headers={'Content-Disposition': f'{_disp};filename={_fname}'})
    # NEXT: wkhtmltopdf render of the same print-view HTML
    if _wk_ok():
        html = invoice_print(iid, _return_html=True)
        pdf = html_to_pdf(html)
        if pdf:
            log(f'{"Downloaded" if _dl else "Opened"} PDF INV-{iid:04d}')
            return Response(pdf, mimetype='application/pdf',
                            headers={'Content-Disposition': f'{_disp};filename={_fname}'})
    # FALLBACK: built-in reportlab generator
    from ..core.pdfgen import invoice_pdf, available
    if not available():
        flash('Server PDF is unavailable on this deployment — use Print / Save PDF from the print view.')
        return redirect(url_for('billing.invoice_print', iid=iid))
    data=invoice_pdf(inv, company=_setting('company','Modern Diagnostic Center'),
                     currency=_setting('currency','$'))
    log(f'{"Downloaded" if _dl else "Opened"} PDF INV-{iid:04d}')
    return Response(data, mimetype='application/pdf',
                    headers={'Content-Disposition': f'{_disp};filename={_fname}'})


def _session_cookies_for(url):
    """Build the Playwright cookie list so headless Chromium loads the page as the
    currently logged-in user (the print route requires login)."""
    from urllib.parse import urlparse
    _p = urlparse(url)
    out = []
    try:
        for k, v in request.cookies.items():
            out.append({'name': k, 'value': v, 'domain': _p.hostname, 'path': '/'})
    except Exception:
        pass
    return out


@bp.route('/invoice/<int:iid>/reset', methods=['POST'])
@login_required
def invoice_reset(iid):
    """Unlock a completed invoice back to draft. Administrator only; fully audited."""
    inv = Invoice.query.get_or_404(iid)
    u = cur_user()
    if not (u and u.role == 'super_admin'):
        flash('Only an administrator can reset a completed invoice to draft.')
        log(f'DENIED reset-to-draft on INV-{iid:04d} by {u.username if u else "?"}')
        return redirect(url_for('billing.invoice_view', iid=iid))
    _reason = (request.form.get('reason') or f'unlocked by admin {u.username}')
    # full reversal (sale + payment + commission) and return to an editable Draft
    _rev = _reset_to_draft(inv, reason=_reason, by=u.username)
    if inv.referral_id:
        from ..models import Referral
        r = Referral.query.get(inv.referral_id)
        if r and r.status == 'Completed':
            r.status = 'Accepted'
    db.session.commit()
    log(f'Invoice INV-{iid:04d} reset to draft', action_type='Reset Draft', entity=f'INV-{iid:04d}',
        old='Completed / Locked', new=f'Draft (editable) · {_rev} accounting entr{"y" if _rev==1 else "ies"} reversed',
        reason=_reason)
    _msg = f'INV-{iid:04d} reset to draft — editing re-enabled.'
    if _rev:
        _msg += f' {_rev} accounting entr{"y" if _rev==1 else "ies"} automatically reversed.'
    flash(_msg)
    return redirect(url_for('billing.invoice_view', iid=iid))


@bp.route('/invoice/<int:iid>/print')
@login_required
def invoice_print(iid, _return_html=False):
    inv=Invoice.query.get_or_404(iid)
    from ..core.security import can_see
    if not can_see(inv): abort(403)
    log(f'PRINT invoice INV-{iid:04d}')
    # The guarantor / loan block is only for the dedicated "Loan Invoice" document,
    # requested explicitly via ?loan=1. The normal invoice print never shows it —
    # even for an unpaid balance — so cash receipts stay clean.
    _loan_doc = request.args.get('loan') == '1'
    # A loan document can only be printed once the guarantor is on file. Without a
    # named guarantor there is nobody standing behind the debt, so we refuse the
    # print and send the cashier back to fill in the credit details first.
    if _loan_doc and not (inv.guarantor or '').strip():
        flash('🤝 Fadlan gali macluumaadka damiinka (Guarantor) ka hor inta aan la daabicin Loan Invoice — please fill in the guarantor details first.')
        log(f'BLOCKED loan-invoice print on INV-{iid:04d}: no guarantor')
        return redirect(url_for('billing.invoice_view', iid=iid) + '#otherinfo')
    _on_credit = _loan_doc and (
        (inv.balance > 0.005) or (inv.pay_method in ('Credit', 'Insurance')))
    credit_block = ''
    if _on_credit:
        _who = h(inv.guarantor) if inv.guarantor else '__________________________'
        _contact = h(inv.patient.phone) if (inv.patient and inv.patient.phone) else '__________________'
        _due = h(inv.due_date) if inv.due_date else '__________________'
        credit_block = (
            "<div style='margin:16px 0 4px;padding:12px 14px;border:1px solid #333;"
            "border-left:4px solid #333'>"
            "<div style='font-size:12px;letter-spacing:.08em;text-transform:uppercase;"
            "color:#555;margin-bottom:8px;font-weight:700'>Credit account / loan</div>"
            "<table style='width:100%;font-size:13px;border-collapse:collapse'>"
            f"<tr><td style='padding:3px 0;color:#555;width:42%'>Customer</td><td><b>{h(inv.patient.name if inv.patient else 'Walk-in')}</b></td></tr>"
            f"<tr><td style='padding:3px 0;color:#555'>Contact (phone)</td><td><b>{_contact}</b></td></tr>"
            f"<tr><td style='padding:3px 0;color:#555'>Guarantor</td><td><b>{_who}</b></td></tr>"
            f"<tr><td style='padding:3px 0;color:#555'>Outstanding balance</td><td><b>{money(inv.balance)}</b></td></tr>"
            f"<tr><td style='padding:3px 0;color:#555'>Payment due date</td><td><b>{_due}</b></td></tr>"
            "</table>"
            "<div style='margin-top:10px;font-size:12px;color:#333'>I, the customer named above, "
            f"promise to pay the outstanding balance of <b>{money(inv.balance)}</b> on or before "
            f"<b>{_due}</b>. The guarantor named above guarantees this payment.</div>"
            "<div style='margin-top:28px;font-size:12px;color:#555;display:flex;justify-content:space-between;gap:24px'>"
            "<span>Customer signature: ____________________<br><span style='font-size:11px'>Date: __________</span></span>"
            "<span>Guarantor signature: ____________________<br><span style='font-size:11px'>Date: __________</span></span>"
            "</div></div>")
    _p = inv.patient
    _gender = h(_p.gender) if (_p and _p.gender) else '—'
    _age = (f"{_p.age} Year" if (_p and getattr(_p, 'age', None) is not None) else '—')
    _drname = h(inv.doctor_ref.name) if inv.doctor_ref else '—'
    if inv.status == 'Cancelled':
        _status = 'Cancelled'
    elif inv.total > 0 and inv.balance <= 0.005:
        _status = 'Paid'
    elif (inv.paid or 0) > 0 or inv.credits:
        _status = 'Partial'
    else:
        _status = 'Unpaid'
    _stcol = {'Paid': '#1FA66D', 'Partial': '#E7A100', 'Unpaid': '#C0392B', 'Cancelled': '#8A96A3'}.get(_status, '#8A96A3')
    _mobile = h(_p.phone) if (_p and _p.phone) else '—'
    _rcpt = PayReceipt.query.filter_by(invoice_id=inv.id).order_by(PayReceipt.id.desc()).first()
    _ref = (f"REF-{inv.referral_id:04d}" if inv.referral_id else (h(_rcpt.ref) if (_rcpt and _rcpt.ref) else '—'))
    _ruser = h(_rcpt.cashier) if (_rcpt and _rcpt.cashier) else (h(inv.disc_by) if inv.disc_by else (h(inv.created_by) if inv.created_by else '—'))
    _paid_date = h(_rcpt.date) if (_rcpt and _rcpt.date) else h(inv.date)
    _no = f"INV-{inv.id:04d}"
    _gross = inv.subtotal + (inv.vat or 0)
    rows = ''.join(
        f"<tr><td style='padding:7px 10px;border:1px solid #C9D2DC'>{h(it.desc)}</td>"
        f"<td style='padding:7px 10px;border:1px solid #C9D2DC;text-align:right'>{(it.qty or 1):g}</td>"
        f"<td style='padding:7px 10px;border:1px solid #C9D2DC;text-align:right'>{money(it.price)}</td>"
        f"<td style='padding:7px 10px;border:1px solid #C9D2DC;text-align:right'>{money((it.qty or 1)*it.price)}</td></tr>"
        for it in inv.items)

    def _trow(label, val, bg='', fg='', bold=False, big=False):
        st = f"background:{bg};" if bg else ''
        st += f"color:{fg};" if fg else 'color:#1F2933;'
        fw = '700' if bold else '500'
        fs = '15px' if big else '13px'
        return (f"<tr><td style='padding:6px 12px;{st}font-weight:{fw};font-size:{fs}'>{label}</td>"
                f"<td style='padding:6px 12px;{st}font-weight:{fw};font-size:{fs};text-align:right'>{val}</td></tr>")

    totals = (
        "<table style='width:320px;border-collapse:collapse;margin-left:auto;margin-top:0'>"
        + _trow('Subtotal', money(inv.subtotal))
        + _trow('Total', money(_gross), bg='#4A5B8C', fg='#fff', bold=True)
        + _trow(f'Paid on {_paid_date}', money(inv.paid))
        + _trow('Amount Due', money(inv.balance))
        + _trow('Discount', money(inv.discount))
        + _trow('Net Total', money(inv.total), bg='#5A6B7B', fg='#FFE08A', bold=True, big=True)
        + "</table>")

    body = f"""
      <table style="width:100%;border-collapse:collapse;margin:2px 0 6px;font-size:14px">
        <tr>
          <td style="width:58%;vertical-align:top;line-height:2">
            <div><b style="color:#1F2933">Name:</b> &nbsp;<b>{h(_p.name) if _p else 'Walk-in'}</b></div>
            <div><b style="color:#1F2933">Patient ID:</b> &nbsp;<b>{h(_p.mrn) if (_p and _p.mrn) else '—'}</b></div>
            <div><b style="color:#1F2933">Dr. Name:</b> &nbsp;<b>{_drname}</b></div>
          </td>
          <td style="width:42%;vertical-align:top;line-height:2.2">
            <div><b style="color:#1F2933">Gender/Age:</b> &nbsp;<b>{_gender} / {_age}</b></div>
            <div><b style="color:#1F2933">Payment Status:</b> &nbsp;<span style="background:{_stcol};color:#fff;padding:2px 12px;border-radius:5px;font-weight:700;font-size:13px">{h(_status)}</span></div>
          </td>
        </tr>
      </table>
      <div style="font-size:19px;color:#4A5B8C;font-weight:600;margin:6px 0 10px">Invoice {_no}</div>
      <table style="width:100%;border-collapse:collapse;margin:0 0 14px;font-size:13.5px">
        <tr style="line-height:1.9">
          <td style="width:25%;vertical-align:top"><div style="color:#1F2933;font-weight:700">Invoice Date:</div><div><b>{h(inv.date)}</b></div></td>
          <td style="width:25%;vertical-align:top"><div style="color:#1F2933;font-weight:700">Reference:</div><div><b>{_ref}</b></div></td>
          <td style="width:25%;vertical-align:top"><div style="color:#1F2933;font-weight:700">Mobile No:</div><div><b>{_mobile}</b></div></td>
          <td style="width:25%;vertical-align:top"><div style="color:#1F2933;font-weight:700">R. User:</div><div><b>{_ruser}</b></div></td>
        </tr>
      </table>
      <table style="width:100%;border-collapse:collapse;margin:0 0 8px;font-size:13.5px">
        <thead><tr style="color:#4A5B8C">
          <th style="padding:8px 10px;border:1px solid #C9D2DC;text-align:left;font-weight:700;letter-spacing:.03em">DESCRIPTION</th>
          <th style="padding:8px 10px;border:1px solid #C9D2DC;text-align:right;font-weight:700">QUANTITY</th>
          <th style="padding:8px 10px;border:1px solid #C9D2DC;text-align:right;font-weight:700">UNIT PRICE</th>
          <th style="padding:8px 10px;border:1px solid #C9D2DC;text-align:right;font-weight:700">AMOUNT</th>
        </tr></thead><tbody>{rows}</tbody>
      </table>
      {totals}
      <div style="clear:both;margin-top:26px;font-size:12.5px;color:#555">Please use the following communication for your payment : <b>{_no}</b></div>
      {credit_block}"""
    _html = printable(f"Invoice {_no}", body, doc_ref=_no, barcode_text=_no)
    if _return_html:
        return _html
    return _html

@bp.route('/preview/invoice/<int:iid>')
@login_required
def invoice_preview(iid):
    """Small JSON payload for the modal record-preview popup."""
    from flask import jsonify
    from ..core.security import can_see
    inv = Invoice.query.get_or_404(iid)
    if not can_see(inv): abort(403)
    return jsonify({
        'title': f'INV-{inv.id:04d}',
        'rows': [
            ['Patient', str(inv.patient.name if inv.patient else 'Walk-in')],
            ['Date', str(inv.date or '—')],
            ['Total', money(inv.total)],
            ['Paid', money(inv.paid)],
            ['Balance', money(inv.balance)],
            ['Status', str(inv.status or '—')],
        ],
        'actions': [
            ['Open', url_for('billing.invoice_view', iid=inv.id), 'primary', False],
            ['Print', url_for('billing.invoice_print', iid=inv.id), '', True],
        ],
    })

def _dlabel(d):
    """Referring-doctor label with its manual code, e.g. 'DR-001 · Dr Xasan'."""
    if not d:
        return '—'
    return (d.code + ' · ' if getattr(d, 'code', None) else '') + (d.name or '')


def commission_view():
    from ..core.posting import commission_preview
    from collections import defaultdict
    y=cur_year()
    inv=[i for i in Invoice.query.order_by(Invoice.date.desc(),Invoice.id.desc()).all() if (i.date or '').startswith(str(y)) and i.referring_doctor_id and i.status!='Cancelled']
    body=''
    tot=defaultdict(float); grand=0.0
    for i in inv:
        d=i.doctor_ref
        _dc=commission_preview(i)[1]          # authoritative payable (after discount, contrast, manual override)
        tot[_dlabel(d)]+=_dc; grand+=_dc
        _typ=(d.commission_type if d else '')
        body+=f"<tr><td>{h(i.date)}</td><td>INV-{i.id:04d}</td><td>{h(_dlabel(d))}</td><td>{plink(i.patient)}</td><td class='num'>{money(i.subtotal)}</td><td><span class='pill teal'>{h(_typ)}</span></td><td class='num' style='font-weight:600;color:var(--petrol)'>{money(_dc)}</td></tr>"
    if not inv: body="<tr><td colspan='7'><div class='empty'><b>No commission yet</b>Ku xir dhakhtar gudbiye (referring doctor) invoice-ka.</div></td></tr>"
    srows=''.join(f"<div class='r'><span>{h(n)}</span><span class='amt'>{money(v)}</span></div>" for n,v in sorted(tot.items(),key=lambda x:-x[1])) or "<div class='r'><span style='color:var(--muted)'>No data</span><span>—</span></div>"
    return page('Doctor Commission', f'''<div class="grid2"><div class="panel" style="grid-column:1/-1"><div class="ph"><h2>Doctor Commission Ledger</h2><span class="so">Auto from invoices &middot; after discount &amp; contrast &middot; {y}</span></div>
      <div class="tw"><table><thead><tr><th>Date</th><th>Invoice</th><th>Doctor</th><th>Patient</th><th class="num">Revenue</th><th>Type</th><th class="num">Commission</th></tr></thead><tbody>{body}</tbody></table></div></div>
      <div class="panel"><div class="ph"><h2>By Doctor</h2></div><div class="pad"><div class="stmt">{srows}<div class="r grand"><span>Total</span><span class="amt">{money(grand)}</span></div></div></div></div></div>''', 'commission')


# ------------------------------------------------------- daily cash closing
def _day_figures(d):
    invs = [i for i in Invoice.query.filter_by(date=d).all() if i.status != 'Cancelled']
    by_method = {}
    for i in invs:
        paid = min(i.paid or 0, i.total or 0) if (i.total or 0) > 0 else (i.paid or 0)
        if paid > 0:
            by_method[i.pay_method or 'Cash'] = by_method.get(i.pay_method or 'Cash', 0) + paid
    pharm = sum(s.total or 0 for s in PharmacySale.query.filter_by(date=d).all())
    if pharm:
        by_method['Cash'] = by_method.get('Cash', 0) + 0  # pharmacy sales are invoiced separately when dispensed
    exp_paid = sum(e.paid or 0 for e in Expense.query.filter_by(date=d).all())
    collected = sum(by_method.values())
    billed = sum(i.total or 0 for i in invs)
    outstanding = sum(max((i.total or 0) - (i.paid or 0), 0) for i in invs)
    return invs, by_method, collected, billed, outstanding, exp_paid


def cashclose_view():
    from ..models import CashClosing
    d = request.args.get('date', today())
    invs, by_method, collected, billed, outstanding, exp_paid = _day_figures(d)
    closing = CashClosing.query.filter_by(date=d).first()
    cash_in = by_method.get('Cash', 0)
    mrows = ''.join(f"<div class='r'><span>{h(m)}</span><span class='amt'>{money(v)}</span></div>"
                    for m, v in sorted(by_method.items())) or "<div class='r'><span style='color:var(--muted)'>No collections</span><span>—</span></div>"
    irows = ''
    for i in invs:
        st = 'Paid' if (i.paid or 0) >= (i.total or 0) and (i.total or 0) > 0 else ('Partial' if (i.paid or 0) > 0 else 'Unpaid')
        irows += (f"<tr><td><b>INV-{i.id:04d}</b></td><td>{plink(i.patient, i.patient.name if i.patient else 'Walk-in')}</td>"
                  f"<td>{h(i.pay_method or '—')}</td><td class='num'>{money(i.total)}</td>"
                  f"<td class='num'>{money(i.paid)}</td>"
                  f"<td><span class='pill {'green' if st == 'Paid' else ('amber' if st == 'Partial' else 'red')}'>{st}</span></td></tr>")
    if not irows:
        irows = "<tr><td colspan='6'><div class='empty'><b>No invoices this day</b></div></td></tr>"
    net = collected - exp_paid

    # ---- cash reconciliation panel ----
    if closing:
        opening = closing.opening_cash or 0
        withdr = closing.withdrawals or 0
        expected = closing.expected_cash or 0
        actual = closing.actual_cash or 0
        diff = closing.difference or 0
        dcolor = 'green' if abs(diff) < 0.005 else ('amber' if diff > 0 else 'red')
        dlabel = 'Balanced' if abs(diff) < 0.005 else (f'Over {money(diff)}' if diff > 0 else f'Short {money(-diff)}')
        recon = (f"<div class='stmt'><div class='sec'>Cash Reconciliation "
                 f"<span class='pill {'green' if closing.status=='Closed' else 'amber'}'>{h(closing.status)}</span></div>"
                 f"<div class='r'><span>Opening Cash (float)</span><span class='amt'>{money(opening)}</span></div>"
                 f"<div class='r'><span>Cash Received</span><span class='amt'>{money(cash_in)}</span></div>"
                 f"<div class='r'><span>Withdrawals</span><span class='amt'>({money(withdr)})</span></div>"
                 f"<div class='r tot'><span>Expected Cash</span><span class='amt'>{money(expected)}</span></div>"
                 f"<div class='r'><span>Actual Counted</span><span class='amt'>{money(actual)}</span></div>"
                 f"<div class='r grand'><span>Difference</span><span class='amt'><span class='pill {dcolor}'>{dlabel}</span></span></div>"
                 f"<div style='font-size:12px;color:var(--muted);margin-top:8px'>Closed by {h(closing.closed_by or '—')} · {closing.closed_at.strftime('%Y-%m-%d %H:%M') if closing.closed_at else ''}"
                 f"{(' · reopened by '+h(closing.reopened_by)) if closing.reopened_by else ''}</div></div>")
        reopen = (f"<a class='btn sm' href='/cashclose/reopen?date={h(d)}' onclick=\"return confirm('Reopen day {h(d)}? Admin action, logged.')\">Reopen (Admin)</a>"
                  if can('reopenday') else '')
        action_bar = f"<a class='btn sm' href='/cashclose/print?date={h(d)}' target='_blank'>Print</a>{reopen}"
    else:
        recon = (f"<div class='stmt'><div class='sec'>Close the Day</div>"
                 f"<form method='post' action='/cashclose/close?date={h(d)}'>"
                 f"<input type='hidden' name='_csrf' value='{csrf_token()}'>"
                 f"<div class='r'><span>Opening Cash (float)</span><input name='opening' type='number' step='any' value='0' style='width:120px;text-align:right;border:1px solid var(--line);border-radius:7px;padding:5px 8px'></div>"
                 f"<div class='r'><span>Cash Received (system)</span><span class='amt'>{money(cash_in)}</span></div>"
                 f"<div class='r'><span>Withdrawals</span><input name='withdrawals' type='number' step='any' value='0' style='width:120px;text-align:right;border:1px solid var(--line);border-radius:7px;padding:5px 8px'></div>"
                 f"<div class='r'><span>Actual Cash Counted</span><input name='actual' type='number' step='any' value='0' style='width:120px;text-align:right;border:1px solid var(--line);border-radius:7px;padding:5px 8px'></div>"
                 f"<div class='r'><span>Note</span><input name='note' placeholder='optional' style='width:160px;border:1px solid var(--line);border-radius:7px;padding:5px 8px'></div>"
                 f"<button class='btn primary' style='width:100%;margin-top:8px' onclick=\"return confirm('Close the day {h(d)}? This locks it and records the audit log.')\">🔒 Close Day</button></form></div>")
        action_bar = f"<a class='btn sm' href='/cashclose/print?date={h(d)}' target='_blank'>Print</a>"

    body = f"""<div class="panel"><div class="ph"><h2>Daily Cash Closing</h2>
      <span class="so">payments recorded on invoice date</span><div class="sp"></div>
      <form method="get" style="display:flex;gap:8px"><input type="date" name="date" value="{h(d)}"
        style="border:1px solid var(--line);border-radius:8px;padding:7px 10px"><button class="btn sm">Go</button></form>
      <a class="btn sm" href="{url_for('modules.module', mod='dailytx')}?date={h(d)}">Daily Transactions</a>{action_bar}</div>
      <div class="pad"><div class="grid2"><div class="stmt">
        <div class="sec">Collections by Payment Method</div>{mrows}
        <div class="r tot"><span>Total Collected</span><span class="amt">{money(collected)}</span></div>
        <div class="r"><span>Expenses Paid Today</span><span class="amt">({money(exp_paid)})</span></div>
        <div class="r grand"><span>NET CASH · {h(d)}</span><span class="amt">{money(net)}</span></div>
      </div>{recon}</div></div>
      <div class="tw"><table><thead><tr><th>No.</th><th>Patient</th><th>Method</th>
      <th class="num">Total</th><th class="num">Paid</th><th>Status</th></tr></thead><tbody>{irows}</tbody></table></div></div>"""
    return page('Daily Cash Closing', body, 'cashclose')


@bp.route('/cashclose/close', methods=['GET', 'POST'])
@login_required
def cashclose_close():
    if not can('cashclose'): abort(403)
    from ..models import CashClosing
    d = request.args.get('date', today())
    _, by_method, collected, billed, outstanding, exp_paid = _day_figures(d)
    if CashClosing.query.filter_by(date=d).first():
        flash(f'Day {d} is already closed'); return redirect(url_for('modules.module', mod='cashclose') + f'?date={d}')
    cash_in = by_method.get('Cash', 0)
    opening = float(request.form.get('opening') or 0)
    withdr = float(request.form.get('withdrawals') or 0)
    actual = float(request.form.get('actual') or 0)
    expected = opening + cash_in - withdr
    diff = actual - expected
    cc = CashClosing(date=d, opening_cash=opening, expected_cash=expected, actual_cash=actual,
                     withdrawals=withdr, difference=diff, collected=collected,
                     note=request.form.get('note'), closed_by=(cur_user().name or cur_user().username),
                     status='Closed')
    db.session.add(cc); db.session.commit()
    log(f'DAY CLOSED {d}: collected {money(collected)} · expected cash {money(expected)} · '
        f'actual {money(actual)} · diff {money(diff)} · net {money(collected - exp_paid)}')
    from ..core.notify import notify
    over = 'balanced' if abs(diff) < 0.005 else (f'OVER {money(diff)}' if diff > 0 else f'SHORT {money(-diff)}')
    notify(f'Cash closing {d}: {over} · collected {money(collected)}',
           link=f'/m/cashclose?date={d}', role='accountant')
    flash(f'Day {d} closed ({over}) — recorded in Audit Log')
    return redirect(url_for('modules.module', mod='cashclose') + f'?date={d}')


@bp.route('/cashclose/reopen')
@login_required
def cashclose_reopen():
    if not can('reopenday'): abort(403)
    from ..models import CashClosing
    d = request.args.get('date', today())
    cc = CashClosing.query.filter_by(date=d).first()
    if not cc:
        flash('That day is not closed'); return redirect(url_for('modules.module', mod='cashclose') + f'?date={d}')
    cc.status = 'Reopened'; cc.reopened_by = (cur_user().name or cur_user().username)
    cc.reopened_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).replace(tzinfo=None)
    db.session.commit()
    log(f'DAY REOPENED {d} by {cc.reopened_by}')
    flash(f'Day {d} reopened — logged'); return redirect(url_for('modules.module', mod='cashclose') + f'?date={d}')


@bp.route('/cashclose/print')
@login_required
def cashclose_print():
    if not can('cashclose'): abort(403)
    d = request.args.get('date', today())
    invs, by_method, collected, billed, outstanding, exp_paid = _day_figures(d)
    mrows = ''.join(f"<tr><td style='padding:5px'>{h(m)}</td><td style='text-align:right;padding:5px'>{money(v)}</td></tr>"
                    for m, v in sorted(by_method.items()))
    return printable(f'Daily Cash Closing · {d}', f"""
      <table style="width:100%;border-collapse:collapse;margin:10px 0">
        <thead><tr style="border-bottom:2px solid #333"><th style="text-align:left;padding:5px">Payment Method</th>
        <th style="text-align:right;padding:5px">Collected</th></tr></thead><tbody>{mrows}</tbody></table>
      <div style="max-width:320px;margin-left:auto">
        <div style="display:flex;justify-content:space-between;padding:4px 0;border-top:2px solid #333;font-weight:700"><span>Total Collected</span><span>{money(collected)}</span></div>
        <div style="display:flex;justify-content:space-between;padding:4px 0"><span>Expenses Paid</span><span>({money(exp_paid)})</span></div>
        <div style="display:flex;justify-content:space-between;padding:6px 0;font-weight:700;font-size:16px;border-top:1px solid #999"><span>NET CASH</span><span>{money(collected - exp_paid)}</span></div>
        <div style="display:flex;justify-content:space-between;padding:4px 0;color:#666"><span>Invoices / Billed</span><span>{len(invs)} · {money(billed)}</span></div>
        <div style="display:flex;justify-content:space-between;padding:4px 0;color:#666"><span>Outstanding</span><span>{money(outstanding)}</span></div>
      </div>
      <p style="margin-top:40px">Cashier signature: ____________________ &nbsp;&nbsp;&nbsp; Manager signature: ____________________</p>""",
      doc_ref=f'CLOSE-{d}')


# ---------------------------------------------------------- payment allocation
def payalloc_view():
    pts = Patient.query.order_by(Patient.name).all()
    presel = request.args.get('patient','')
    opts = ''
    for p_ in pts:
        bal = sum(max(i.balance, 0) for i in Invoice.query.filter_by(patient_id=p_.id).all()
                  if i.status != 'Cancelled')
        if bal > 0.005 or str(p_.id) == presel:
            sel = ' selected' if str(p_.id) == presel else ''
            opts += f"<option value='{p_.id}'{sel}>{h(p_.name)} · {h(p_.mrn or '')} · owes {money(bal)}</option>"
    pm_opts = ''.join(f"<option>{m}</option>" for m in PAY_METHODS)
    recent = ''
    for a in Audit.query.filter(Audit.action.like('RECEIPT %')).order_by(Audit.id.desc()).limit(12).all():
        recent += f"<tr><td>{a.ts.strftime('%d-%b %H:%M') if a.ts else '—'}</td><td>{h(a.action)}</td><td>{h(a.user or '—')}</td></tr>"
    if not recent:
        recent = "<tr><td colspan='3'><div class='empty'><b>No receipts yet</b></div></td></tr>"
    form_html = ('<div class="empty"><b>No outstanding patient balances</b></div>' if not opts else
        f"""<form method="post" action="{url_for('billing.payalloc_apply')}"><div class="fg">
          <div class="fld full"><label>Patient *</label><select name="patient_id">{opts}</select></div>
          <div class="fld"><label>Amount Received *</label><input name="amount" type="number" step="any" required></div>
          <div class="fld"><label>Method</label><select name="method">{pm_opts}</select></div>
        </div><div class="fa"><button class="btn primary">Allocate Payment</button></div></form>""")
    body = f"""<div class="grid2">
      <div class="panel"><div class="ph"><h2>Receive Payment</h2>
        <span class="so">auto-allocated to the patient's oldest unpaid invoices</span></div>
        <div class="pad">{form_html}</div></div>
      <div class="panel"><div class="ph"><h2>Recent Receipts</h2></div>
        <div class="tw"><table><thead><tr><th>When</th><th>Receipt</th><th>By</th></tr></thead>
        <tbody>{recent}</tbody></table></div></div></div>"""
    return page('Receive Payment', body, 'payalloc')


@bp.route('/payments/receive', methods=['POST'])
@login_required
def payalloc_apply():
    if not can('payalloc'): abort(403)
    p_ = Patient.query.get_or_404(int(request.form['patient_id']))
    try:
        amount = float(request.form.get('amount') or 0)
    except ValueError:
        amount = 0
    method = request.form.get('method') or 'Cash'
    if amount <= 0:
        flash('Amount must be positive')
        return redirect(url_for('modules.module', mod='payalloc'))
    remaining = amount
    hits = []
    open_invs = sorted([i for i in Invoice.query.filter_by(patient_id=p_.id).all()
                        if i.status != 'Cancelled' and i.balance > 0.005],
                       key=lambda i: (i.date or '', i.id))
    for inv in open_invs:
        if remaining <= 0.005:
            break
        take = min(remaining, inv.balance)
        inv.paid = (inv.paid or 0) + take
        inv.pay_method = method
        inv.status = 'Paid' if inv.balance <= 0.005 else 'Partial'
        remaining -= take
        hits.append((inv, take))
        repost_payment(inv)
    _u = cur_user()
    for inv, take in hits:
        db.session.add(PayReceipt(invoice_id=inv.id, amount=take, method=method,
                                  ref=request.form.get('ref') or '',
                                  cashier=(_u.name or _u.username) if _u else ''))
    db.session.commit()
    alloc = ', '.join(f'INV-{i.id:04d} {money(t)}' for i, t in hits) or 'nothing (no open invoices)'
    log(f'RECEIPT {money(amount)} from {p_.name} ({method}) → {alloc}'
        + (f' · unallocated {money(remaining)}' if remaining > 0.005 else ''))
    flash(f'Allocated {money(amount - remaining)} to {len(hits)} invoice(s)'
          + (f' — {money(remaining)} exceeds open balances (not allocated)' if remaining > 0.005 else ''))
    return redirect(url_for('modules.module', mod='payalloc'))


@bp.route('/receipt/<int:rid>/pdf')
@login_required
def receipt_pdf_dl(rid):
    if not can('invoices'):
        abort(403)
    r = PayReceipt.query.get_or_404(rid)
    from ..core.pdfgen import receipt_pdf, available
    from ..core.helpers import setting as _setting
    if not available():
        flash('Server PDF is unavailable on this deployment — use Print / Save PDF from the print view.')
        return redirect(url_for('billing.receipt_view', rid=rid))
    data = receipt_pdf(r, company=_setting('company', 'Modern Diagnostic Center'),
                       currency=_setting('currency', '$'))
    _dl = request.args.get('dl')
    _disp = 'attachment' if _dl else 'inline'
    log(f'{"Downloaded" if _dl else "Opened"} PDF RCT-{rid:05d}')
    return Response(data, mimetype='application/pdf',
                    headers={'Content-Disposition': f'{_disp};filename=RCT-{rid:05d}.pdf'})


@bp.route('/creditnote/<int:cid>/print')
@login_required
def credit_note_print(cid):
    if not (can('creditnotes') or can('invoices')):
        abort(403)
    cn = CreditNote.query.get_or_404(cid)
    inv = cn.invoice
    p = inv.patient if inv else None
    ref = f'CN-{cn.id:04d}'
    inv_ref = f'INV-{inv.id:04d}' if inv else '—'
    body = f"""
      <table style="width:100%;border-collapse:collapse;margin:6px 0 14px;font-size:13.5px">
        <tr><td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Credit Note:</b> {ref}</td>
            <td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Date:</b> {h(cn.date or '')}</td></tr>
        <tr><td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Against Invoice:</b> {inv_ref}</td>
            <td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Patient:</b> {h(p.name if p else 'Walk-in')}</td></tr>
        <tr><td style="padding:6px 8px;border:1px solid #dfe4e8"><b>MRN:</b> {h(p.mrn if p else '—')}</td>
            <td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Issued by:</b> {h(cn.user or '—')}</td></tr>
      </table>
      <h2 style="text-align:center;color:#103D46;font-family:'Space Grotesk';letter-spacing:.5px;margin:6px 0 10px">CREDIT NOTE</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead><tr style="background:#044C8C;color:#fff">
          <th style="text-align:left;padding:9px 10px">Description</th>
          <th style="text-align:right;padding:9px 10px">Amount</th></tr></thead>
        <tbody>
          <tr><td style="padding:9px 10px;border:1px solid #dfe4e8">{h(cn.reason or 'Credit against invoice ' + inv_ref)}</td>
              <td style="padding:9px 10px;border:1px solid #dfe4e8;text-align:right">{money(cn.amount)}</td></tr>
        </tbody>
        <tfoot><tr style="font-weight:700;background:#EAF0F7">
          <td style="padding:10px;border:1px solid #dfe4e8;text-align:right">TOTAL CREDIT</td>
          <td style="padding:10px;border:1px solid #dfe4e8;text-align:right">{money(cn.amount)}</td></tr></tfoot>
      </table>
      <p style="margin-top:14px;color:#44515a;font-size:13px">
        This credit note reduces the outstanding balance of Invoice <b>{inv_ref}</b> by <b>{money(cn.amount)}</b>.
      </p>"""
    return printable(f'Credit Note {ref}', body, doc_ref=ref, barcode_text=ref,
                     signature={'name': cn.user or 'Authorized', 'title': 'Issued & Approved'})


@bp.route('/debitnote/<int:did>/print')
@login_required
def debit_note_print(did):
    if not (can('debitnotes') or can('purchases')):
        abort(403)
    dn = DebitNote.query.get_or_404(did)
    pur = dn.purchase
    sup = pur.supplier if pur else None
    ref = f'DN-{dn.id:04d}'
    pur_ref = f'PUR-{pur.id:04d}' if pur else '—'
    body = f"""
      <table style="width:100%;border-collapse:collapse;margin:6px 0 14px;font-size:13.5px">
        <tr><td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Debit Note:</b> {ref}</td>
            <td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Date:</b> {h(dn.date or '')}</td></tr>
        <tr><td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Against Purchase:</b> {pur_ref}</td>
            <td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Supplier:</b> {h(sup.name if sup else '—')}</td></tr>
        <tr><td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Supplier Phone:</b> {h(getattr(sup,'phone','') or '—')}</td>
            <td style="padding:6px 8px;border:1px solid #dfe4e8"><b>Issued by:</b> {h(dn.user or '—')}</td></tr>
      </table>
      <h2 style="text-align:center;color:#103D46;font-family:'Space Grotesk';letter-spacing:.5px;margin:6px 0 10px">DEBIT NOTE</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead><tr style="background:#044C8C;color:#fff">
          <th style="text-align:left;padding:9px 10px">Description</th>
          <th style="text-align:right;padding:9px 10px">Amount</th></tr></thead>
        <tbody>
          <tr><td style="padding:9px 10px;border:1px solid #dfe4e8">{h(dn.reason or 'Debit against purchase ' + pur_ref)}</td>
              <td style="padding:9px 10px;border:1px solid #dfe4e8;text-align:right">{money(dn.amount)}</td></tr>
        </tbody>
        <tfoot><tr style="font-weight:700;background:#EAF0F7">
          <td style="padding:10px;border:1px solid #dfe4e8;text-align:right">TOTAL DEBIT</td>
          <td style="padding:10px;border:1px solid #dfe4e8;text-align:right">{money(dn.amount)}</td></tr></tfoot>
      </table>
      <p style="margin-top:14px;color:#44515a;font-size:13px">
        This debit note reduces the amount payable on Purchase <b>{pur_ref}</b> by <b>{money(dn.amount)}</b>.
      </p>"""
    return printable(f'Debit Note {ref}', body, doc_ref=ref, barcode_text=ref,
                     signature={'name': dn.user or 'Authorized', 'title': 'Issued & Approved'})


@bp.route('/receipt/<int:rid>')
@login_required
def receipt_view(rid):
    if not can('invoices'): abort(403)
    from ..core.printing import printable
    r = PayReceipt.query.get_or_404(rid)
    inv = r.invoice
    p = inv.patient if inv else None
    items = ''.join(f"<tr><td style='padding:3px 8px 3px 0'>{h(i.desc)}</td>"
                    f"<td style='text-align:right'>{i.qty:g} × {money(i.price)}</td>"
                    f"<td style='text-align:right;font-weight:600'>{money(i.qty*i.price)}</td></tr>"
                    for i in (inv.items if inv else []))
    disc = (inv.discount or 0) + inv.subtotal*(inv.discount_pct or 0)/100.0 if inv else 0
    def row(l, v, b=False):
        st = 'font-weight:700' if b else ''
        return f"<tr><td colspan='2' style='padding:3px 8px 3px 0;color:#444'>{l}</td><td style='text-align:right;{st}'>{v}</td></tr>"
    body = f"""
    <div style='max-width:420px'>
      <div style='display:flex;justify-content:space-between;margin-bottom:8px'>
        <div><b>{h(p.name) if p else 'Walk-in'}</b><div style='color:#666;font-size:12px'>{h(p.mrn) if p else ''}</div></div>
        <div style='text-align:right'><b>INV-{inv.id:04d}</b><div style='color:#666;font-size:12px'>{h(r.date)}</div></div>
      </div>
      <table style='width:100%;border-collapse:collapse;font-size:13px;border-top:1px solid #ddd;border-bottom:1px solid #ddd'>
        {items}
        {row('Discount', '-'+money(disc)) if disc else ''}
        {row('VAT', money(inv.vat or 0)) if (inv.vat or 0) else ''}
        {row('TOTAL', money(inv.total), True)}
        {row(f'PAID NOW ({h(r.method)})' + (f' · ref {h(r.ref)}' if r.ref else ''), money(r.amount), True)}
        {row('Total Paid to Date', money(inv.paid or 0))}
        {row('Balance', money(inv.balance), True)}
      </table>
      <div style='color:#666;font-size:12px;margin-top:8px'>Cashier: <b>{h(r.cashier or '—')}</b></div>
    </div>"""
    return printable(f'Receipt RCT-{r.id:05d}', body, doc_ref=f'RCT-{r.id:05d}', barcode_text=f'RCT-{r.id:05d}',
                     signature=({'name': r.cashier, 'title': 'Received by · Cashier'} if getattr(r, 'cashier', None) else None))


def dailytx_view():
    """Daily Transactions — line-by-line payment events for a day with method totals."""
    from ..models import PayReceipt, CashClosing
    d = request.args.get('date', today())
    receipts = PayReceipt.query.filter_by(date=d).order_by(PayReceipt.id).all()
    invs = [i for i in Invoice.query.filter_by(date=d).all() if i.status != 'Cancelled']
    inv_by_id = {i.id: i for i in Invoice.query.all()}
    by_method = {}
    rows = ''
    for rc in receipts:
        inv = inv_by_id.get(rc.invoice_id)
        pat = inv.patient if inv else None
        by_method[rc.method or 'Cash'] = by_method.get(rc.method or 'Cash', 0) + (rc.amount or 0)
        rows += (f"<tr><td><b>RCT-{rc.id:05d}</b><div style='font-size:11px;color:var(--muted)'>{rc.date}</div></td>"
                 f"<td>{h(pat.mrn if pat else '—')}</td>"
                 f"<td>{h(pat.name if pat else 'Walk-in')}</td>"
                 f"<td><a href='/invoice/{rc.invoice_id}' style='color:var(--petrol);font-weight:600'>INV-{rc.invoice_id:04d}</a></td>"
                 f"<td><span class='pill blue'>{h(rc.method or 'Cash')}</span></td>"
                 f"<td>{h(rc.ref or '—')}</td>"
                 f"<td>{h(rc.cashier or '—')}</td>"
                 f"<td class='num'><b>{money(rc.amount)}</b></td></tr>")
    if not rows:
        rows = "<tr><td colspan='8'><div class='empty'><b>No transactions</b>No payments recorded on this day.</div></td></tr>"
    # discounts & refunds for the day
    discounts = sum((i.discount or 0) for i in invs)
    refunds = sum((i.refund or 0) for i in invs if hasattr(i, 'refund'))
    total_collected = sum(by_method.values())
    npat = len({i.patient_id for i in invs if i.patient_id})
    mrows = ''.join(f"<div class='r'><span>{h(m)}</span><span class='amt'>{money(v)}</span></div>"
                    for m, v in sorted(by_method.items())) or "<div class='r'><span style='color:var(--muted)'>No collections</span><span>—</span></div>"
    net = total_collected - refunds
    def _wsum(*names):
        return sum(v for k, v in by_method.items() if k in names)
    summary = (f"<div class='grid2'><div class='stmt'>"
               f"<div class='sec'>Income by Payment Method</div>{mrows}"
               f"<div class='r tot'><span>Total Collected</span><span class='amt'>{money(total_collected)}</span></div>"
               f"<div class='r'><span>Refunds</span><span class='amt'>({money(refunds)})</span></div>"
               f"<div class='r'><span>Discounts Given</span><span class='amt'>{money(discounts)}</span></div>"
               f"<div class='r grand'><span>NET REVENUE</span><span class='amt'>{money(net)}</span></div></div>"
               f"<div class='stmt'><div class='sec'>Day Summary</div>"
               f"<div class='r'><span>Patients</span><span class='amt'>{npat}</span></div>"
               f"<div class='r'><span>Invoices</span><span class='amt'>{len(invs)}</span></div>"
               f"<div class='r'><span>Transactions</span><span class='amt'>{len(receipts)}</span></div>"
               f"<div class='r'><span>Cash Income</span><span class='amt'>{money(by_method.get('Cash',0))}</span></div>"
               f"<div class='r'><span>Sahal</span><span class='amt'>{money(_wsum('Sahal'))}</span></div>"
               f"<div class='r'><span>EVC</span><span class='amt'>{money(_wsum('EVC','EVC Plus'))}</span></div>"
               f"<div class='r'><span>E. Dahab</span><span class='amt'>{money(_wsum('E. Dahab','eDahab','E.Dahab'))}</span></div>"
               f"<div class='r'><span>MyCash</span><span class='amt'>{money(_wsum('MyCash','My Cash'))}</span></div>"
               f"<div class='r'><span>Premier Wallet</span><span class='amt'>{money(_wsum('Premier Wallet','Premier'))}</span></div>"
               f"<div class='r'><span>Bank</span><span class='amt'>{money(by_method.get('Bank',0)+by_method.get('Card',0))}</span></div>"
               f"<div class='r'><span>Insurance</span><span class='amt'>{money(by_method.get('Insurance',0))}</span></div></div></div>")
    closing = CashClosing.query.filter_by(date=d).first()
    lock_badge = (f"<span class='pill green'>Day Closed by {h(closing.closed_by or '')}</span>" if closing and closing.status == 'Closed'
                  else f"<span class='pill amber'>Reopened</span>" if closing else '')
    body = (f"<div class='panel'><div class='ph'><h2>Daily Transactions</h2>{lock_badge}<div class='sp'></div>"
            f"<form method='get' style='display:flex;gap:8px'><input type='date' name='date' value='{h(d)}' style='border:1px solid var(--line);border-radius:8px;padding:7px 10px'><button class='btn sm'>Go</button></form>"
            f"<a class='btn sm' href='/dailytx/print?date={h(d)}' target='_blank'>Print</a>"
            f"<a class='btn sm primary' href='{url_for('modules.module', mod='cashclose')}?date={h(d)}'>Cash Closing →</a></div>"
            f"<div class='pad'>{summary}</div>"
            f"<div class='tw'><table><thead><tr><th>Receipt</th><th>Patient ID</th><th>Patient</th><th>Invoice</th><th>Method</th><th>Reference</th><th>Cashier</th><th class='num'>Amount</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></div>")
    return page('Daily Transactions', body, 'dailytx')


@bp.route('/dailytx/print')
@login_required
def dailytx_print():
    if not can('invoices') and not can('cashclose'):
        abort(403)
    from ..models import PayReceipt
    d = request.args.get('date', today())
    receipts = PayReceipt.query.filter_by(date=d).order_by(PayReceipt.id).all()
    inv_by_id = {i.id: i for i in Invoice.query.all()}
    by_method = {}
    trs = ''
    for rc in receipts:
        inv = inv_by_id.get(rc.invoice_id)
        pat = inv.patient if inv else None
        by_method[rc.method or 'Cash'] = by_method.get(rc.method or 'Cash', 0) + (rc.amount or 0)
        trs += (f"<tr><td>RCT-{rc.id:05d}</td><td>{h(pat.name if pat else 'Walk-in')}</td>"
                f"<td>INV-{rc.invoice_id:04d}</td><td>{h(rc.method or 'Cash')}</td>"
                f"<td>{h(rc.cashier or '—')}</td><td style='text-align:right'>{money(rc.amount)}</td></tr>")
    total = sum(by_method.values())
    mtr = ''.join(f"<tr><td>{h(m)}</td><td style='text-align:right'>{money(v)}</td></tr>" for m, v in sorted(by_method.items()))
    from ..core.printing import printable
    body = (f"<p><b>Date:</b> {h(d)}</p>"
            f"<h3>Transactions</h3><table style='width:100%;border-collapse:collapse' border='1' cellpadding='5'>"
            f"<tr><th>Receipt</th><th>Patient</th><th>Invoice</th><th>Method</th><th>Cashier</th><th>Amount</th></tr>{trs}</table>"
            f"<h3>Totals by Method</h3><table style='width:60%;border-collapse:collapse' border='1' cellpadding='5'>{mtr}"
            f"<tr><td><b>Total</b></td><td style='text-align:right'><b>{money(total)}</b></td></tr></table>")
    return printable('Daily Transactions Report', body, doc_ref=f'DTX-{d}')



@bp.route('/dailytx/csv')
@login_required
def dailytx_csv():
    """Export the day's transactions as CSV (Excel-compatible)."""
    if not can('dailytx') and not can('invoices') and not can('cashclose'):
        abort(403)
    from ..models import PayReceipt
    from flask import Response
    d = request.args.get('date', today())
    inv_by_id = {i.id: i for i in Invoice.query.all()}
    lines = ['No,Date,MRN,Patient,Invoice,Receipt,Amount,Method,Cashier,Reference']

    def esc(x):
        return '"' + str(x if x is not None else '').replace('"', '""') + '"'
    for i, rc in enumerate(PayReceipt.query.filter_by(date=d).order_by(PayReceipt.id).all(), 1):
        inv = inv_by_id.get(rc.invoice_id)
        pat = inv.patient if inv else None
        lines.append(','.join([
            str(i), esc(d), esc(pat.mrn if pat else ''), esc(pat.name if pat else 'Walk-in'),
            f'INV-{rc.invoice_id:04d}', f'RCT-{rc.id:05d}', str(rc.amount or 0),
            esc(rc.method or 'Cash'), esc(rc.cashier or ''), esc(rc.ref or '')]))
    log(f'Daily transactions CSV exported for {d}')
    return Response('\n'.join(lines), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=daily-transactions-{d}.csv'})


# ==================== Commission & Radiologist Fee Payables (auto-accrued on payment) ====================

def _accrual_kpis():
    """Outstanding / paid / today / month totals split by doctor vs radiologist."""
    from ..models import CommissionAccrual
    from ..core.helpers import today
    td = today(); ym = td[:7]
    k = {kind: dict(outstanding=0.0, paid=0.0, today=0.0, month=0.0)
         for kind in ('doctor', 'radiologist')}
    for a in CommissionAccrual.query.all():
        kind = a.payee_kind if a.payee_kind in k else 'doctor'
        k[kind]['outstanding'] += a.balance
        k[kind]['paid'] += (a.paid or 0)
        if (a.date or '') == td:
            k[kind]['today'] += (a.amount or 0)
        if (a.date or '').startswith(ym):
            k[kind]['month'] += (a.amount or 0)
    return k


def payables_view():
    """Doctor Commission & Radiologist Fee payables — accrued automatically on payment."""
    from ..models import CommissionAccrual, CommissionPayment
    kind = request.args.get('kind', 'doctor')
    if kind not in ('doctor', 'radiologist'):
        kind = 'doctor'
    show = request.args.get('show', 'open')
    k = _accrual_kpis()

    # --- KPI cards ---
    def card(label, val, ac):
        return (f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div>"
                f"<div class='v'>{money(val)}</div><div class='s'>{kind.title()}</div></div>")
    kpis = ("<div class='kpis'>"
            + card('Outstanding', k[kind]['outstanding'], 'var(--red)')
            + card('Paid to date', k[kind]['paid'], 'var(--green)')
            + card("Today accrued", k[kind]['today'], 'var(--blue)')
            + card('This month', k[kind]['month'], 'var(--petrol)') + "</div>")

    # --- tabs ---
    def tab(kk, lb):
        return f"<a class='btn sm {'primary' if kind==kk else ''}' href='?kind={kk}'>{lb}</a>"
    tabs = tab('doctor', 'Doctor Commission') + ' ' + tab('radiologist', 'Radiologist Fees')
    stab = (f"<a class='btn sm {'primary' if show=='open' else ''}' href='?kind={kind}&show=open'>Open</a> "
            f"<a class='btn sm {'primary' if show=='all' else ''}' href='?kind={kind}&show=all'>All</a> "
            f"<a class='btn sm {'primary' if show=='history' else ''}' href='?kind={kind}&show=history'>Payment History</a>")

    # --- Payment History + monthly summary ---
    if show == 'history':
        pays = CommissionPayment.query.filter_by(payee_kind=kind).order_by(
            CommissionPayment.date.desc(), CommissionPayment.id.desc()).all()
        hrows = ''
        months = {}
        for p_ in pays:
            months[(p_.date or '')[:7]] = months.get((p_.date or '')[:7], 0) + (p_.amount or 0)
            hrows += (f"<tr><td>{h(p_.date)}</td><td><b>{h(p_.payee_name)}</b></td>"
                      f"<td class='num'>{money(p_.amount)}</td><td>{h(p_.method or 'Cash')}</td>"
                      f"<td>{h(p_.user or '—')}</td>"
                      f"<td class='num'><a class='btn gh sm' href='/payables/voucher/{p_.id}' target='_blank'>🖨 Voucher</a></td></tr>")
        if not hrows:
            hrows = "<tr><td colspan='6'><div class='empty'><b>No payments yet</b></div></td></tr>"
        mrows = ''.join(f"<tr><td><b>{h(m)}</b></td><td class='num'>{money(v)}</td></tr>"
                        for m, v in sorted(months.items(), reverse=True))
        body = (f"<div class='panel'><div class='pad'>"
                f"<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center'>{tabs}"
                f"<div class='sp' style='flex:1'></div>{stab}</div></div></div>"
                + kpis +
                f"<div class='grid2'><div class='panel'><div class='ph'><h2>Payment History · {'Doctor' if kind=='doctor' else 'Radiologist'}</h2></div>"
                f"<div class='tw'><table><thead><tr><th>Date</th><th>Payee</th><th class='num'>Amount</th>"
                f"<th>Method</th><th>Paid by</th><th></th></tr></thead><tbody>{hrows}</tbody></table></div></div>"
                f"<div class='panel'><div class='ph'><h2>Monthly Payment Summary</h2></div>"
                f"<div class='tw'><table><thead><tr><th>Month</th><th class='num'>Total Paid</th></tr></thead>"
                f"<tbody>{mrows or '<tr><td colspan=2>—</td></tr>'}</tbody></table></div></div></div>")
        return page('Commission Payables', body, 'payables')

    # --- accrual rows (with checkboxes for Pay Selected) ---
    q = CommissionAccrual.query.filter_by(payee_kind=kind).order_by(CommissionAccrual.date.desc(), CommissionAccrual.id.desc())
    accruals = q.all()
    if show == 'open':
        accruals = [a for a in accruals if a.balance > 0.005]
    rows = ''
    for a in accruals:
        stc = {'Paid': 'green', 'Partial': 'amber', 'Unpaid': 'red'}.get(a.status, 'grey')
        cb = (f"<input type='checkbox' name='ids' value='{a.id}' form='payform'>" if a.balance > 0.005 else '')
        if a.balance > 0.005:
            pay_cell = (f"<a class='btn gh sm' href='/payables/pay?ids={a.id}&kind={kind}' "
                        f"onclick=\"return confirm('Pay this payable?')\">Pay</a>")
        else:
            pay_cell = ''
        rows += (f"<tr><td>{cb}</td><td>{h(a.date)}</td>"
                 f"<td><a href='/invoice/{a.invoice_id}' style='color:var(--petrol);font-weight:600'>INV-{a.invoice_id:04d}</a></td>"
                 f"<td><b>{h(a.payee_name or 'Unassigned')}</b></td>"
                 f"<td class='num'>{money(a.amount)}</td><td class='num'>{money(a.paid)}</td>"
                 f"<td class='num' style='font-weight:600'>{money(a.balance)}</td>"
                 f"<td><span class='pill {stc}'>{h(a.status)}</span></td>"
                 f"<td class='num'>{pay_cell}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='9'><div class='empty'><b>No payables</b>Amounts accrue automatically when patients pay.</div></td></tr>"

    outstanding = k[kind]['outstanding']
    payall = (f"<a class='btn primary sm' href='/payables/pay?kind={kind}&all=1' "
              f"onclick=\"return confirm('Pay ALL outstanding {kind} payables ({money(outstanding)})?')\">Pay All ({money(outstanding)})</a>"
              if outstanding > 0.005 else '')
    paysel = ("<button class='btn sm' form='payform' type='submit'>Pay Selected</button>"
              if any(a.balance > 0.005 for a in accruals) else '')
    ym_now = today()[:7]
    schedule_bar = ''
    if outstanding > 0.005:
        schedule_bar = (
            f"<div class='panel'><div class='pad' style='display:flex;gap:16px;flex-wrap:wrap;align-items:center'>"
            f"<form method='get' action='/payables/pay-monthly' style='display:flex;gap:8px;align-items:center'>"
            f"<input type='hidden' name='kind' value='{kind}'>"
            f"<input type='hidden' name='method' class='pm-hidden' value='Cash'>"
            f"<b style='font-size:13px'>Pay Monthly:</b>"
            f"<input type='month' name='month' value='{ym_now}' class='lb-input'>"
            f"<button class='btn sm'>Pay Month</button></form>"
            f"<span style='color:var(--line)'>|</span>"
            f"<form method='post' action='/payables/pay-partial' style='display:flex;gap:8px;align-items:center'>"
            f"<input type='hidden' name='_csrf' value='{csrf_token()}'>"
            f"<input type='hidden' name='method' class='pm-hidden' value='Cash'>"
            f"<input type='hidden' name='kind' value='{kind}'>"
            f"<b style='font-size:13px'>Partial Payment:</b>"
            f"<input name='amount' type='number' step='0.01' placeholder='Amount $' class='lb-input' style='width:120px' required>"
            f"<button class='btn sm'>Pay Amount</button>"
            f"<small style='color:var(--muted)'>oldest first — statuses become Partial/Paid</small></form>"
            f"</div></div>")

    # by-payee summary (Radiologist/Doctor · reports · due · paid · outstanding)
    by = {}
    for a in CommissionAccrual.query.filter_by(payee_kind=kind).all():
        d_ = by.setdefault(a.payee_name or 'Unassigned', dict(n=0, due=0.0, paid=0.0, out=0.0))
        d_['n'] += 1; d_['due'] += (a.amount or 0); d_['paid'] += (a.paid or 0); d_['out'] += a.balance
    from urllib.parse import quote as _q
    who = 'Radiologist' if kind == 'radiologist' else 'Doctor'
    srows = ''
    for nm, v in sorted(by.items(), key=lambda x: -x[1]['out']):
        stp = "<span class='pill green'>Paid</span>" if v['out'] <= 0.005 else ("<span class='pill amber'>Partial</span>" if v['paid'] > 0.005 else "<span class='pill red'>Pending</span>")
        pay_btn = (f"<a class='btn primary sm' href='/payables/pay-payee?kind={kind}&name={_q(nm)}' "
                   f"onclick=\"return confirm('Pay ALL outstanding for this {who.lower()}?')\">Pay {money(v['out'])} →</a>"
                   if v['out'] > 0.005 else '')
        srows += (f"<tr><td><b>{h(nm)}</b></td><td class='num'>{v['n']}</td>"
                  f"<td class='num'>{money(v['due'])}</td><td class='num'>{money(v['paid'])}</td>"
                  f"<td class='num' style='font-weight:600'>{money(v['out'])}</td><td>{stp}</td>"
                  f"<td class='num'>{pay_btn}</td></tr>")
    summary_panel = ''
    if srows:
        summary_panel = (f"<div class='panel'><div class='ph'><h2>By {who}</h2>"
                         f"<span class='so'>pay one {who.lower()}'s whole balance in one click</span></div>"
                         f"<div class='tw'><table><thead><tr><th>{who}</th>"
                         f"<th class='num'>{'Reports' if kind=='radiologist' else 'Invoices'}</th><th class='num'>Amount Due</th>"
                         f"<th class='num'>Paid</th><th class='num'>Outstanding</th><th>Status</th><th></th></tr></thead>"
                         f"<tbody>{srows}</tbody></table></div></div>")

    from ..core.posting import PAY_METHODS as _ALLPM
    _payout_methods = [m for m in _ALLPM if m not in ('Credit', 'Insurance')]  # money going out
    _method_opts = ''.join(f"<option {'selected' if m=='Cash' else ''}>{m}</option>" for m in _payout_methods)
    method_bar = (
        f"<div class='panel'><div class='pad' style='display:flex;gap:10px;align-items:center;flex-wrap:wrap'>"
        f"<b style='font-size:13px'>💳 Pay via:</b>"
        f"<select id='payMethod' class='lb-input' onchange=\"payMethodSync()\" style='min-width:150px'>{_method_opts}</select>"
        f"<small style='color:var(--muted)'>choose how the commission / fee is paid out — Cash, Sahal, E. Dahab, ...</small>"
        f"</div></div>"
        "<script>function payMethodSync(){"
        "var m=document.getElementById('payMethod'); if(!m)return; var v=encodeURIComponent(m.value);"
        "document.querySelectorAll('input.pm-hidden').forEach(function(i){i.value=m.value;});"
        "document.querySelectorAll('a[href*=\\'/payables/pay\\']').forEach(function(a){"
        "  var u=a.getAttribute('href'); if(!u)return; u=u.replace(/([&?])method=[^&]*/,'$1').replace(/[&?]$/,'');"
        "  a.setAttribute('href', u + (u.indexOf('?')>=0?'&':'?') + 'method=' + v);"
        "});"
        "}document.addEventListener('DOMContentLoaded',payMethodSync);</script>")

    body = (f"<div class='panel'><div class='pad'>"
            f"<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center'>{tabs}"
            f"<div class='sp' style='flex:1'></div>{stab}</div></div></div>"
            + kpis + method_bar + summary_panel + schedule_bar +
            f"<form id='payform' method='post' action='/payables/pay-selected'>"
            f"<input type='hidden' name='_csrf' value='{csrf_token()}'>"
            f"<input type='hidden' name='method' class='pm-hidden' value='Cash'>"
            f"<input type='hidden' name='kind' value='{kind}'></form>"
            f"<div class='panel'><div class='ph'><h2>{'Doctor Commission' if kind=='doctor' else 'Radiologist Fee'} Payables</h2>"
            f"<div class='sp'></div>{paysel} {payall}</div>"
            f"<div class='tw'><table><thead><tr><th></th><th>Date</th><th>Invoice</th>"
            f"<th>{'Doctor' if kind=='doctor' else 'Radiologist'}</th>"
            f"<th class='num'>Accrued</th><th class='num'>Paid</th><th class='num'>Balance</th>"
            f"<th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>")
    return page('Commission Payables', body, 'payables')


def _settle_accruals(accruals, kind, cap=None, method='Cash'):
    """Settle accruals (oldest first). If cap is given, pay up to that total (partial allowed);
    otherwise pay each in full. Posts Debit Payable / Credit <wallet/cash>; records the
    CommissionPayment with the chosen payment method (Cash, Sahal, E. Dahab, ...)."""
    from ..models import CommissionPayment
    from ..core.posting import post_journal, acc_ensure, pm_account, PAY_METHODS
    # money is going OUT, so only real cash/wallet accounts make sense here
    if method not in PAY_METHODS or method in ('Credit', 'Insurance'):
        method = 'Cash'
    pay_acc = pm_account(method)   # Cash→1101, Sahal→1104, E.Dahab→1106, Bank→1102, …
    payable_acc = '2300' if kind == 'doctor' else '2310'
    total = 0.0
    by_payee = {}
    remaining = cap if cap is not None else None
    ordered = sorted([a for a in accruals if a.balance > 0.005],
                     key=lambda a: (a.date or '', a.id))
    for a in ordered:
        if remaining is not None and remaining <= 0.005:
            break
        bal = a.balance
        pay = money_round(bal if remaining is None else min(bal, remaining))
        a.paid = money_round((a.paid or 0) + pay)
        a.status = 'Paid' if a.balance <= 0.005 else 'Partial'
        total = money_round(total + pay)
        if remaining is not None:
            remaining = money_round(remaining - pay)
        by_payee[a.payee_name or 'Unassigned'] = money_round(by_payee.get(a.payee_name or 'Unassigned', 0) + pay)
    if total <= 0.005:
        return 0.0
    u = cur_user()
    for payee, amt in by_payee.items():
        db.session.add(CommissionPayment(date=today(), payee_kind=kind, payee_name=payee,
                                         amount=amt, method=method, user=u.username if u else ''))
    acc_ensure(payable_acc, 'Doctor Commission Payable' if kind == 'doctor' else 'Radiologist Fee Payable', 'Liability', '2000')
    post_journal(today(), f"CMPAY-{kind[:3].upper()}-{int(__import__('time').time())%100000}",
                 f"{'Doctor commission' if kind=='doctor' else 'Radiologist fee'} settlement ({method})",
                 [(payable_acc, total, 0), (pay_acc, 0, total)])
    db.session.commit()
    log(f'{kind.title()} payables settled: {money(total)} across {len(by_payee)} payee(s) via {method}')
    return total


@bp.route('/payables/pay')
@login_required
def payables_pay():
    if not can('payables'): abort(403)
    from ..models import CommissionAccrual
    kind = request.args.get('kind', 'doctor')
    if request.args.get('all') == '1':
        accruals = [a for a in CommissionAccrual.query.filter_by(payee_kind=kind).all() if a.balance > 0.005]
    else:
        ids = [int(x) for x in (request.args.get('ids', '')).split(',') if x.strip().isdigit()]
        accruals = CommissionAccrual.query.filter(CommissionAccrual.id.in_(ids)).all()
    total = _settle_accruals(accruals, kind, method=request.args.get('method', 'Cash'))
    flash(f'Paid {money(total)} in {kind} payables' if total else 'Nothing to pay')
    return redirect(url_for('modules.module', mod='payables') + f'?kind={kind}')


@bp.route('/payables/pay-selected', methods=['POST'])
@login_required
def payables_pay_selected():
    if not can('payables'): abort(403)
    from ..models import CommissionAccrual
    kind = request.form.get('kind', 'doctor')
    ids = [int(x) for x in request.form.getlist('ids') if str(x).isdigit()]
    accruals = CommissionAccrual.query.filter(CommissionAccrual.id.in_(ids)).all()
    total = _settle_accruals(accruals, kind, method=request.form.get('method', 'Cash'))
    flash(f'Paid {money(total)} in {kind} payables' if total else 'No rows selected')
    return redirect(url_for('modules.module', mod='payables') + f'?kind={kind}')


@bp.route('/payables/pay-payee')
@login_required
def payables_pay_payee():
    """Settle ALL open accruals for one payee (one doctor or one radiologist) at once."""
    if not can('payables'): abort(403)
    from ..models import CommissionAccrual
    kind = request.args.get('kind', 'doctor')
    name = request.args.get('name', '')
    accruals = [a for a in CommissionAccrual.query.filter_by(payee_kind=kind, payee_name=name).all()
                if a.balance > 0.005]
    total = _settle_accruals(accruals, kind, method=request.args.get('method', 'Cash'))
    flash(f'Paid {money(total)} to {name}' if total else f'Nothing outstanding for {name}')
    return redirect(url_for('modules.module', mod='payables') + f'?kind={kind}')


@bp.route('/payables/pay-monthly')
@login_required
def payables_pay_monthly():
    """Settle every open accrual dated in the chosen month (default schedule for radiologists)."""
    if not can('payables'): abort(403)
    from ..models import CommissionAccrual
    kind = request.args.get('kind', 'radiologist')
    month = (request.args.get('month') or today()[:7])[:7]
    accruals = [a for a in CommissionAccrual.query.filter_by(payee_kind=kind).all()
                if (a.date or '').startswith(month) and a.balance > 0.005]
    total = _settle_accruals(accruals, kind, method=request.args.get('method', 'Cash'))
    flash(f'Paid {money(total)} in {kind} payables for {month}' if total else f'Nothing due for {month}')
    return redirect(url_for('modules.module', mod='payables') + f'?kind={kind}')


@bp.route('/payables/pay-partial', methods=['POST'])
@login_required
def payables_pay_partial():
    """Pay up to a given amount across open accruals (oldest first) — Partially Paid supported."""
    if not can('payables'): abort(403)
    from ..models import CommissionAccrual
    kind = request.form.get('kind', 'doctor')
    try:
        amount = float(request.form.get('amount') or 0)
    except ValueError:
        amount = 0
    if amount <= 0:
        flash('Enter a valid amount'); return redirect(url_for('modules.module', mod='payables') + f'?kind={kind}')
    accruals = [a for a in CommissionAccrual.query.filter_by(payee_kind=kind).all() if a.balance > 0.005]
    total = _settle_accruals(accruals, kind, cap=amount, method=request.form.get('method', 'Cash'))
    flash(f'Partial payment of {money(total)} applied (oldest first)' if total else 'Nothing to pay')
    return redirect(url_for('modules.module', mod='payables') + f'?kind={kind}')


@bp.route('/payables/voucher/<int:pid>')
@login_required
def payables_voucher(pid):
    """Printable payment voucher for one commission/fee payment."""
    if not can('payables'): abort(403)
    from ..models import CommissionPayment
    from ..core.printing import printable
    p = CommissionPayment.query.get_or_404(pid)
    kind_lb = 'Doctor Commission' if p.payee_kind == 'doctor' else 'Radiologist Fee'
    body = f"""
    <h3 style='margin:14px 0 8px'>Payment Voucher</h3>
    <table style='width:100%;border-collapse:collapse;font-size:14px'>
      <tr><td style='padding:8px;border:1px solid #ddd;width:35%'><b>Voucher No.</b></td><td style='padding:8px;border:1px solid #ddd'>CMV-{p.id:05d}</td></tr>
      <tr><td style='padding:8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:8px;border:1px solid #ddd'>{h(p.date)}</td></tr>
      <tr><td style='padding:8px;border:1px solid #ddd'><b>Paid To</b></td><td style='padding:8px;border:1px solid #ddd'><b>{h(p.payee_name)}</b></td></tr>
      <tr><td style='padding:8px;border:1px solid #ddd'><b>Type</b></td><td style='padding:8px;border:1px solid #ddd'>{kind_lb}</td></tr>
      <tr><td style='padding:8px;border:1px solid #ddd'><b>Amount</b></td><td style='padding:8px;border:1px solid #ddd;font-size:17px'><b>{money(p.amount)}</b></td></tr>
      <tr><td style='padding:8px;border:1px solid #ddd'><b>Method</b></td><td style='padding:8px;border:1px solid #ddd'>{h(p.method or 'Cash')}</td></tr>
      <tr><td style='padding:8px;border:1px solid #ddd'><b>Prepared By</b></td><td style='padding:8px;border:1px solid #ddd'>{h(p.user or '—')}</td></tr>
    </table>
    <div style='display:flex;justify-content:space-between;margin-top:44px;font-size:13px'>
      <span>Received by: ____________________</span>
      <span>Approved by: ____________________</span>
    </div>"""
    return printable(f'{kind_lb} Voucher', body, doc_ref=f'CMV-{p.id:05d}', barcode_text=f'CMV-{p.id:05d}',
                     signature=({'name': p.user, 'title': 'Prepared & Authorized'} if getattr(p, 'user', None) else None))


# ==================== Pay Center — one place to pay every debt ====================

def paycenter_view():
    """Hal meel: dhammaan deynaha (doctor commission, radiologist fees, vendor expenses,
    purchases) + Pay buttons."""
    from ..models import CommissionAccrual, Expense, Purchase
    doc_out = sum(a.balance for a in CommissionAccrual.query.filter_by(payee_kind='doctor').all())
    rad_out = sum(a.balance for a in CommissionAccrual.query.filter_by(payee_kind='radiologist').all())
    exps = [e for e in Expense.query.order_by(Expense.date.desc()).all() if (e.amount or 0) - (e.paid or 0) > 0.005]
    purs = [p_ for p_ in Purchase.query.order_by(Purchase.date.desc()).all() if (p_.total or 0) - (p_.paid or 0) > 0.005]
    exp_out = sum((e.amount or 0) - (e.paid or 0) for e in exps)
    pur_out = sum((p_.total or 0) - (p_.paid or 0) for p_ in purs)
    grand = doc_out + rad_out + exp_out + pur_out

    def kpi(l, v, ac, link):
        return (f"<a href='{link}' style='text-decoration:none'><div class='kpi' style='--ac:{ac}'>"
                f"<div class='l'>{l}</div><div class='v'>{money(v)}</div><div class='s'>Outstanding</div></div></a>")
    kpis = ("<div class='kpis'>"
            + kpi('Doctor Commission', doc_out, 'var(--red)' if doc_out else 'var(--green)', url_for('modules.module', mod='payables') + '?kind=doctor')
            + kpi('Radiologist Fees', rad_out, 'var(--red)' if rad_out else 'var(--green)', url_for('modules.module', mod='payables') + '?kind=radiologist')
            + kpi('Vendor Expenses (Utilities...)', exp_out, 'var(--red)' if exp_out else 'var(--green)', '#exps')
            + kpi('Purchases / Suppliers', pur_out, 'var(--red)' if pur_out else 'var(--green)', '#purs')
            + f"<div class='kpi' style='--ac:var(--petrol)'><div class='l'>TOTAL DEBTS · Wadarta Deynaha</div><div class='v'>{money(grand)}</div><div class='s'>Dhammaan waxa lagugu leeyahay</div></div>"
            + "</div>")

    tok = csrf_token()
    erows = ''
    for e in exps:
        bal = (e.amount or 0) - (e.paid or 0)
        who = e.supplier.name if getattr(e, 'supplier', None) else '—'
        erows += (f"<tr><td>{h(e.date)}</td><td><b>{h(who)}</b></td><td>{h(e.category or '—')}</td>"
                  f"<td>{h((e.note or '')[:40])}</td><td class='num'>{money(e.amount)}</td>"
                  f"<td class='num'>{money(e.paid)}</td><td class='num' style='font-weight:700'>{money(bal)}</td>"
                  f"<td class='num'><a class='btn primary sm' href='/paycenter/pay-expense/{e.id}' "
                  f"onclick=\"return confirm('Pay this expense in full?')\">Pay</a></td></tr>")
    if not erows:
        erows = "<tr><td colspan='8' style='color:var(--muted);padding:14px'>No unpaid expenses ✓</td></tr>"
    prows = ''
    for p_ in purs:
        bal = (p_.total or 0) - (p_.paid or 0)
        who = p_.supplier.name if getattr(p_, 'supplier', None) else (p_.item or '—')
        prows += (f"<tr><td>{h(p_.date)}</td><td><b>{h(who)}</b></td>"
                  f"<td class='num'>{money(p_.total)}</td><td class='num'>{money(p_.paid)}</td>"
                  f"<td class='num' style='font-weight:700'>{money(bal)}</td>"
                  f"<td class='num'><a class='btn primary sm' href='/paycenter/pay-purchase/{p_.id}' "
                  f"onclick=\"return confirm('Pay this purchase in full?')\">Pay</a></td></tr>")
    if not prows:
        prows = "<tr><td colspan='6' style='color:var(--muted);padding:14px'>No unpaid purchases ✓</td></tr>"

    combtns = (f"<div class='panel'><div class='pad' style='display:flex;gap:10px;flex-wrap:wrap'>"
               f"<a class='btn primary' href='/payables/pay?kind=doctor&all=1' onclick=\"return confirm('Pay ALL doctor commission ({money(doc_out)})?')\" {'style=display:none' if doc_out<=0.005 else ''}>Pay All Doctor Commission ({money(doc_out)})</a>"
               f"<a class='btn primary' href='/payables/pay?kind=radiologist&all=1' onclick=\"return confirm('Pay ALL radiologist fees ({money(rad_out)})?')\" {'style=display:none' if rad_out<=0.005 else ''}>Pay All Radiologist Fees ({money(rad_out)})</a>"
               f"<a class='btn' href='{url_for('modules.module', mod='payables')}?kind=doctor'>Open Commission Payables →</a>"
               f"</div></div>")

    body = (kpis + combtns
            + f"<div class='panel' id='exps'><div class='ph'><h2>💡 Unpaid Vendor Expenses (Utilities, Electricity, Water...)</h2>"
              f"<span class='so'>{len(exps)} bill(s) · {money(exp_out)}</span></div>"
              f"<div class='tw'><table><thead><tr><th>Date</th><th>Vendor</th><th>Category</th><th>Note</th>"
              f"<th class='num'>Amount</th><th class='num'>Paid</th><th class='num'>Balance</th><th></th></tr></thead>"
              f"<tbody>{erows}</tbody></table></div></div>"
            + f"<div class='panel' id='purs'><div class='ph'><h2>📦 Unpaid Purchases</h2>"
              f"<span class='so'>{len(purs)} order(s) · {money(pur_out)}</span></div>"
              f"<div class='tw'><table><thead><tr><th>Date</th><th>Supplier</th>"
              f"<th class='num'>Total</th><th class='num'>Paid</th><th class='num'>Balance</th><th></th></tr></thead>"
              f"<tbody>{prows}</tbody></table></div></div>")
    return page('Pay Center', body, 'paycenter')


@bp.route('/paycenter/pay-expense/<int:eid>')
@login_required
def paycenter_pay_expense(eid):
    if not can('paycenter'): abort(403)
    from ..models import Expense
    from ..core.posting import post_expense
    e = Expense.query.get_or_404(eid)
    bal = (e.amount or 0) - (e.paid or 0)
    if bal <= 0.005:
        flash('Already paid'); return redirect(url_for('modules.module', mod='paycenter'))
    e.paid = e.amount
    db.session.commit()
    try:
        post_expense(e)   # repost: Debit expense acct / Credit Cash (AP cleared)
    except Exception:
        db.session.rollback()
    log(f'Pay Center: expense EXP-{e.id:04d} paid {money(bal)} ({e.category or ""})')
    flash(f'Paid {money(bal)} — {e.category or "expense"}')
    return redirect(url_for('modules.module', mod='paycenter'))


@bp.route('/paycenter/pay-purchase/<int:pid>')
@login_required
def paycenter_pay_purchase(pid):
    if not can('paycenter'): abort(403)
    from ..models import Purchase
    from ..core.posting import post_purchase
    p_ = Purchase.query.get_or_404(pid)
    bal = (p_.total or 0) - (p_.paid or 0)
    if bal <= 0.005:
        flash('Already paid'); return redirect(url_for('modules.module', mod='paycenter'))
    p_.paid = p_.total
    db.session.commit()
    try:
        post_purchase(p_)
    except Exception:
        db.session.rollback()
    log(f'Pay Center: purchase PUR-{p_.id:04d} paid {money(bal)}')
    flash(f'Paid {money(bal)} — purchase')
    return redirect(url_for('modules.module', mod='paycenter'))
