"""Insurance — payers, cards, coverage, pre-authorization, claims  (Phase 3, v8.0).

Ties into existing billing: an invoice paid via the 'Insurance' method already
posts an Insurance Receivable (account 1250). A Claim tracks the amount owed by
the payer; reconciling a claim posts the insurer's payment (Dr Cash/Bank,
Cr 1250), clearing that receivable.
"""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort,
                   render_template)
from markupsafe import escape as h
from ..extensions import db
from ..models import (Insurer, InsuranceCard, CoverageRule, PreAuth, Claim,
                      Invoice)
from ..core.security import (cur_user, can, login_required, log, branch_scope, can_see)
from ..core.helpers import money, today
from ..core.ui import page
from ..core.crud import register, pill, opt_patients
from ..core.posting import post_journal, acc_ensure

bp = Blueprint('insurance', __name__)

CLAIM_COLORS = {'Draft': 'grey', 'Submitted': 'blue', 'Approved': 'teal',
                'Partial': 'amber', 'Rejected': 'red', 'Paid': 'green'}
PAY_ACCOUNTS = {'Cash': '1101', 'Bank': '1102', 'Mobile Money': '1103'}


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


def _opt_insurers():
    return [('', '— select insurer —')] + [
        (i.id, i.name) for i in Insurer.query.filter_by(active=True).order_by(Insurer.name).all()]


def _cards_for(patient_id):
    return InsuranceCard.query.filter_by(patient_id=patient_id, active=True).all()


def _claim_no(cid):
    return f'CLM{dt.date.today().year}{cid:04d}'


# ================================================================= dashboard
def ins_dashboard():
    """Claims worklist — App Launcher (mod='insurance')."""
    fstatus = (request.args.get('status') or '').strip()
    finsurer = request.args.get('insurer', type=int)

    q = branch_scope(Claim.query, Claim).order_by(Claim.id.desc())
    if fstatus:
        q = q.filter(Claim.status == fstatus)
    if finsurer:
        q = q.filter(Claim.insurer_id == finsurer)
    claims = q.limit(500).all()

    # summary across ALL claims (not just filtered)
    allc = branch_scope(Claim.query, Claim).all()
    outstanding = sum((c.approved or c.claimed or 0) - (c.paid or 0)
                      for c in allc if c.status in ('Submitted', 'Approved', 'Partial'))
    by_status = {}
    for c in allc:
        by_status[c.status] = by_status.get(c.status, 0) + 1

    cards = (
        f"<div class='panel' style='display:inline-block;min-width:150px;margin:4px'><div class='pad'>"
        f"<div style='font-size:20px;font-weight:700'>{money(outstanding)}</div>"
        f"<div style='font-size:12px;color:var(--muted)'>Outstanding from payers</div></div></div>")
    for st in ('Draft', 'Submitted', 'Approved', 'Partial', 'Rejected', 'Paid'):
        cards += (
            f"<a href='?status={st}' style='text-decoration:none'>"
            f"<div class='panel' style='display:inline-block;min-width:96px;margin:4px'><div class='pad'>"
            f"<div style='font-size:20px;font-weight:700'>{by_status.get(st,0)}</div>"
            f"<div style='font-size:12px;color:var(--muted)'>{st}</div></div></div></a>")

    rows = []
    for c in claims:
        acts = f"<a class='btn sm' href='{url_for('insurance.claim_view', cid=c.id)}'>Open</a>"
        rows.append([
            h(c.claim_no or f'#{c.id}'),
            h(c.patient.name if c.patient else '—'),
            h(c.insurer.name if c.insurer else '—'),
            money(c.claimed or 0),
            money(c.approved or 0),
            money(c.paid or 0),
            f"<span class='pill {CLAIM_COLORS.get(c.status,'grey')}'>{h(c.status)}</span>",
            acts,
        ])
    clear = (f" <a href='{url_for('modules.module', mod='insurance')}' style='color:var(--petrol)'>clear</a>"
             if (fstatus or finsurer) else '')
    prefix = f"<div style='margin-bottom:8px'>{cards}</div>{('<div style=\"font-size:13px;margin-bottom:6px\">Filter: '+h(fstatus or '')+clear+'</div>') if (fstatus or finsurer) else ''}"
    toolbar = (f"<a class='btn' href='{url_for('modules.module', mod='insurers')}'>🏢 Insurers</a> "
               f"<a class='btn' href='{url_for('modules.module', mod='inscards')}'>🪪 Cards</a> "
               f"<a class='btn' href='{url_for('insurance.preauth_list')}'>🔐 Pre-Auth</a> "
               f"<a class='btn' href='{url_for('modules.module', mod='coverage')}'>📋 Coverage</a> "
               f"<a class='btn primary' href='{url_for('insurance.claim_new')}'>+ New Claim</a>")
    body = render_template(
        'list_page.html', title='Insurance · Claims', prefix=prefix, toolbar=toolbar,
        headers=['Claim #', 'Patient', 'Insurer', 'Claimed', 'Approved', 'Paid', 'Status', ''],
        aligns=['', '', '', 'num', 'num', 'num', '', 'num'], rows=rows,
        empty="<div class='empty'><b>No claims</b>Create a claim from an insurance invoice.</div>")
    return page('Insurance', body, 'insurance')


# ===================================================================== claims
@bp.route('/insurance/claim/new', methods=['GET', 'POST'])
@login_required
def claim_new():
    if not can('insurance'):
        abort(403)
    inv_id = request.args.get('invoice', type=int)
    if request.method == 'POST':
        pid = request.form.get('patient_id') or None
        iid = request.form.get('insurer_id') or None
        if not (pid and iid):
            flash('Patient and insurer are required', 'error')
            return redirect(url_for('insurance.claim_new'))
        card = InsuranceCard.query.filter_by(patient_id=pid, insurer_id=iid, active=True).first()
        u = cur_user()
        c = Claim(patient_id=pid, insurer_id=iid, card_id=(card.id if card else None),
                  invoice_id=request.form.get('invoice_id') or None,
                  claimed=float(request.form.get('claimed') or 0),
                  notes=request.form.get('notes'), status='Draft',
                  created_by=(u.username if u else None),
                  branch_id=(u.branch_id if u else None))
        db.session.add(c)
        db.session.flush()
        c.claim_no = _claim_no(c.id)
        db.session.commit()
        log(f'Insurance claim {c.claim_no} created', entity=f'Claim#{c.id}')
        flash(f'Claim {c.claim_no} created', 'ok')
        return redirect(url_for('insurance.claim_view', cid=c.id))

    # prefill from an invoice if provided
    inv = Invoice.query.get(inv_id) if inv_id else None
    pid = inv.patient_id if inv else ''
    claimed = 0
    insurer_id = ''
    if inv:
        claimed = inv.balance
        card = _cards_for(inv.patient_id)
        if card:
            insurer_id = card[0].insurer_id
            cov = card[0].coverage_pct or (card[0].insurer.coverage_pct if card[0].insurer else 80)
            claimed = round((inv.total or 0) * (cov or 80) / 100.0, 2)

    popts = ''.join(f"<option value='{v}' {'selected' if str(v)==str(pid) else ''}>{h(lb)}</option>"
                    for v, lb in opt_patients())
    iopts = ''.join(f"<option value='{v}' {'selected' if str(v)==str(insurer_id) else ''}>{h(lb)}</option>"
                    for v, lb in _opt_insurers())
    inner = f"""
    <form method='post' class='formwrap'>
      <input type='hidden' name='invoice_id' value='{inv.id if inv else ''}'>
      <div class='fld'><label>Patient</label><select name='patient_id'>{popts}</select></div>
      <div class='fld'><label>Insurer</label><select name='insurer_id'>{iopts}</select></div>
      <div class='fld'><label>Claimed amount</label><input name='claimed' type='number' step='any' value='{claimed}'></div>
      <div class='fld full'><label>Notes</label><textarea name='notes'></textarea></div>
      <div class='fld full'><button class='btn primary'>Create claim</button>
        <a class='btn gh' href="{url_for('modules.module', mod='insurance')}">Cancel</a></div>
    </form>"""
    hint = (f"<div class='panel' style='border-left:3px solid var(--blue)'><div class='pad' style='font-size:13px'>"
            f"Claim seeded from invoice #{inv.id} — coverage applied from the patient's card.</div></div>" if inv else '')
    return page('New Claim', hint + f"<div class='panel'><div class='pad'>{inner}</div></div>", 'insurance')


@bp.route('/insurance/claim/<int:cid>')
@login_required
def claim_view(cid):
    if not can('insurance'):
        abort(403)
    c = Claim.query.get_or_404(cid)
    if not can_see(c):
        abort(403)
    outstanding = (c.approved or c.claimed or 0) - (c.paid or 0)
    info = (f"<div class='panel'><div class='pad'>"
            f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:6px 24px;font-size:13px'>"
            f"<div><b>Claim:</b> {h(c.claim_no)}</div>"
            f"<div><b>Status:</b> <span class='pill {CLAIM_COLORS.get(c.status,'grey')}'>{h(c.status)}</span></div>"
            f"<div><b>Patient:</b> {h(c.patient.name if c.patient else '—')}</div>"
            f"<div><b>Insurer:</b> {h(c.insurer.name if c.insurer else '—')}</div>"
            f"<div><b>Invoice:</b> {('#'+str(c.invoice_id)) if c.invoice_id else '—'}</div>"
            f"<div><b>Submitted:</b> {h(c.submitted_at or '—')}</div>"
            f"<div><b>Claimed:</b> {money(c.claimed or 0)}</div>"
            f"<div><b>Approved:</b> {money(c.approved or 0)}</div>"
            f"<div><b>Paid:</b> {money(c.paid or 0)}</div>"
            f"<div><b>Outstanding:</b> {money(outstanding)}</div>"
            + (f"<div style='grid-column:1/3;color:var(--red)'><b>Rejection:</b> {h(c.reject_reason)}</div>" if c.reject_reason else '')
            + f"</div></div></div>")

    actions = []
    if c.status == 'Draft':
        actions.append(f"<a class='btn primary' href='{url_for('insurance.claim_submit', cid=c.id)}'>📤 Submit</a>")
    if c.status in ('Submitted',):
        actions.append(f"<a class='btn' href='{url_for('insurance.claim_respond', cid=c.id)}'>📥 Record Response</a>")
    if c.status in ('Approved', 'Partial'):
        actions.append(f"<a class='btn primary' href='{url_for('insurance.claim_reconcile', cid=c.id)}'>💵 Reconcile Payment</a>")
    if c.status not in ('Paid', 'Rejected'):
        actions.append(f"<a class='btn gh sm' style='color:var(--red)' href='{url_for('insurance.claim_reject', cid=c.id)}'>Reject</a>")
    bar = f"<div style='margin-bottom:10px'>{' '.join(actions)}</div>"
    return page(f'Claim {c.claim_no}', bar + info, 'insurance',
                crumbs=[('Insurance', url_for('modules.module', mod='insurance')), (c.claim_no, None)])


@bp.route('/insurance/claim/<int:cid>/submit')
@login_required
def claim_submit(cid):
    if not can('insurance'):
        abort(403)
    c = Claim.query.get_or_404(cid)
    if not can_see(c):
        abort(403)
    if c.status == 'Draft':
        c.status = 'Submitted'
        c.submitted_at = _now()
        db.session.commit()
        log(f'Claim {c.claim_no} submitted', entity=f'Claim#{c.id}')
        flash('Claim submitted', 'ok')
    return redirect(url_for('insurance.claim_view', cid=c.id))


@bp.route('/insurance/claim/<int:cid>/respond', methods=['GET', 'POST'])
@login_required
def claim_respond(cid):
    if not can('insurance'):
        abort(403)
    c = Claim.query.get_or_404(cid)
    if not can_see(c):
        abort(403)
    if request.method == 'POST':
        approved = float(request.form.get('approved') or 0)
        c.approved = approved
        c.responded_at = _now()
        if approved <= 0:
            c.status = 'Rejected'
            c.reject_reason = request.form.get('reject_reason') or 'Rejected by payer'
        elif approved < (c.claimed or 0):
            c.status = 'Partial'
            c.reject_reason = request.form.get('reject_reason') or None
        else:
            c.status = 'Approved'
        db.session.commit()
        log(f'Claim {c.claim_no} response: {c.status} ({money(approved)})',
            action_type='Report Approval', entity=f'Claim#{c.id}')
        flash('Response recorded', 'ok')
        return redirect(url_for('insurance.claim_view', cid=c.id))
    inner = f"""
    <form method='post' class='formwrap'>
      <div class='fld'><label>Approved amount</label><input name='approved' type='number' step='any' value='{c.claimed or 0}'></div>
      <div class='fld full'><label>Reason (if partial / rejected)</label><input name='reject_reason' value=""></div>
      <div class='fld full'><button class='btn primary'>Save response</button>
        <a class='btn gh' href="{url_for('insurance.claim_view', cid=c.id)}">Cancel</a></div>
    </form>
    <div style='font-size:12px;color:var(--muted);margin-top:6px'>Claimed: {money(c.claimed or 0)}. Approved below claimed → Partial; zero → Rejected.</div>"""
    return page('Record Response', f"<div class='panel'><div class='pad'>{inner}</div></div>", 'insurance')


@bp.route('/insurance/claim/<int:cid>/reject', methods=['GET', 'POST'])
@login_required
def claim_reject(cid):
    if not can('insurance'):
        abort(403)
    c = Claim.query.get_or_404(cid)
    if not can_see(c):
        abort(403)
    if request.method == 'POST':
        c.status = 'Rejected'
        c.reject_reason = request.form.get('reject_reason') or 'Rejected'
        c.responded_at = _now()
        db.session.commit()
        log(f'Claim {c.claim_no} rejected', entity=f'Claim#{c.id}')
        flash('Claim marked rejected', 'ok')
        return redirect(url_for('insurance.claim_view', cid=c.id))
    inner = f"""
    <form method='post' class='formwrap'>
      <div class='fld full'><label>Rejection reason</label><input name='reject_reason' value=""></div>
      <div class='fld full'><button class='btn primary' style='background:var(--red)'>Confirm rejection</button>
        <a class='btn gh' href="{url_for('insurance.claim_view', cid=c.id)}">Cancel</a></div>
    </form>"""
    return page('Reject Claim', f"<div class='panel'><div class='pad'>{inner}</div></div>", 'insurance')


@bp.route('/insurance/claim/<int:cid>/reconcile', methods=['GET', 'POST'])
@login_required
def claim_reconcile(cid):
    if not can('insurance'):
        abort(403)
    c = Claim.query.get_or_404(cid)
    if not can_see(c):
        abort(403)
    ar = (c.insurer.ar_account if c.insurer and c.insurer.ar_account else '1250')
    if request.method == 'POST':
        amt = float(request.form.get('amount') or 0)
        method = request.form.get('method') or 'Bank'
        pdate = request.form.get('date') or today()
        if amt <= 0:
            flash('Enter a payment amount', 'error')
            return redirect(url_for('insurance.claim_reconcile', cid=c.id))
        # accounting: Dr cash/bank, Cr insurance receivable (clears 1250)
        acc_ensure(ar, 'Insurance Receivable', 'Asset', '1000')
        cash = PAY_ACCOUNTS.get(method, '1102')
        acc_ensure(cash, method, 'Asset', '1000')
        try:
            post_journal(pdate, f'CLAIM-PAY-{c.id}',
                         f'Insurance payment {c.claim_no} ({c.insurer.name if c.insurer else ""})',
                         [(cash, amt, 0), (ar, 0, amt)])
        except Exception as e:
            flash(f'Could not post to accounting: {h(str(e))}', 'error')
            return redirect(url_for('insurance.claim_reconcile', cid=c.id))
        c.paid = (c.paid or 0) + amt
        target = c.approved or c.claimed or 0
        c.status = 'Paid' if c.paid >= target - 0.001 else 'Partial'
        db.session.commit()
        log(f'Claim {c.claim_no} reconciled {money(amt)} via {method}',
            action_type='Payment', entity=f'Claim#{c.id}')
        flash(f'Payment of {money(amt)} recorded and receivable cleared', 'ok')
        return redirect(url_for('insurance.claim_view', cid=c.id))
    outstanding = (c.approved or c.claimed or 0) - (c.paid or 0)
    inner = f"""
    <form method='post' class='formwrap'>
      <div class='fld'><label>Amount received</label><input name='amount' type='number' step='any' value='{outstanding}'></div>
      <div class='fld'><label>Method</label><select name='method'>
        <option>Bank</option><option>Cash</option><option>Mobile Money</option></select></div>
      <div class='fld'><label>Date</label><input name='date' type='date' value='{today()}'></div>
      <div class='fld full'><button class='btn primary'>Record payment</button>
        <a class='btn gh' href="{url_for('insurance.claim_view', cid=c.id)}">Cancel</a></div>
    </form>
    <div style='font-size:12px;color:var(--muted);margin-top:6px'>Posts Dr {money(outstanding)} to cash/bank, Cr account {ar} (Insurance Receivable).</div>"""
    return page('Reconcile Payment', f"<div class='panel'><div class='pad'>{inner}</div></div>", 'insurance')


# ================================================================== pre-auth
@bp.route('/insurance/preauth')
@login_required
def preauth_list():
    if not can('insurance'):
        abort(403)
    pas = branch_scope(PreAuth.query, PreAuth).order_by(PreAuth.id.desc()).limit(300).all()
    colors = {'Pending': 'amber', 'Approved': 'green', 'Rejected': 'red'}
    rows = []
    for p in pas:
        acts = ''
        if p.status == 'Pending':
            acts = (f"<a class='btn sm primary' href='{url_for('insurance.preauth_decide', pid=p.id, d='approve')}'>Approve</a> "
                    f"<a class='btn sm gh' style='color:var(--red)' href='{url_for('insurance.preauth_decide', pid=p.id, d='reject')}'>Reject</a>")
        rows.append([
            h(p.requested_at or '—'),
            h(p.patient.name if p.patient else '—'),
            h(p.insurer.name if p.insurer else '—'),
            h(p.description or '—'),
            money(p.est_amount or 0),
            f"<span class='pill {colors.get(p.status,'grey')}'>{h(p.status)}</span>"
            + (f" <span class='pill teal'>{h(p.auth_code)}</span>" if p.auth_code else ''),
            acts,
        ])
    toolbar = f"<a class='btn primary' href='{url_for('insurance.preauth_new')}'>+ New Pre-Auth</a>"
    body = render_template(
        'list_page.html', title='Pre-Authorizations', toolbar=toolbar,
        headers=['Requested', 'Patient', 'Insurer', 'Description', 'Est.', 'Status', ''],
        aligns=['', '', '', '', 'num', '', 'num'], rows=rows,
        empty="<div class='empty'><b>No pre-auth requests</b></div>")
    return page('Pre-Auth', body, 'insurance',
                crumbs=[('Insurance', url_for('modules.module', mod='insurance')), ('Pre-Auth', None)])


@bp.route('/insurance/preauth/new', methods=['GET', 'POST'])
@login_required
def preauth_new():
    if not can('insurance'):
        abort(403)
    if request.method == 'POST':
        u = cur_user()
        p = PreAuth(patient_id=request.form.get('patient_id') or None,
                    insurer_id=request.form.get('insurer_id') or None,
                    description=request.form.get('description'),
                    est_amount=float(request.form.get('est_amount') or 0),
                    valid_to=request.form.get('valid_to') or None,
                    status='Pending', requested_by=(u.username if u else None),
                    branch_id=(u.branch_id if u else None))
        db.session.add(p)
        db.session.commit()
        log('Pre-auth requested', entity=f'PreAuth#{p.id}')
        flash('Pre-authorization requested', 'ok')
        return redirect(url_for('insurance.preauth_list'))
    popts = ''.join(f"<option value='{v}'>{h(lb)}</option>" for v, lb in opt_patients())
    iopts = ''.join(f"<option value='{v}'>{h(lb)}</option>" for v, lb in _opt_insurers())
    inner = f"""
    <form method='post' class='formwrap'>
      <div class='fld'><label>Patient</label><select name='patient_id'>{popts}</select></div>
      <div class='fld'><label>Insurer</label><select name='insurer_id'>{iopts}</select></div>
      <div class='fld full'><label>Description / service</label><input name='description'></div>
      <div class='fld'><label>Estimated amount</label><input name='est_amount' type='number' step='any' value='0'></div>
      <div class='fld'><label>Valid until</label><input name='valid_to' type='date'></div>
      <div class='fld full'><button class='btn primary'>Request pre-auth</button>
        <a class='btn gh' href="{url_for('insurance.preauth_list')}">Cancel</a></div>
    </form>"""
    return page('New Pre-Auth', f"<div class='panel'><div class='pad'>{inner}</div></div>", 'insurance')


@bp.route('/insurance/preauth/<int:pid>/<d>', methods=['GET', 'POST'])
@login_required
def preauth_decide(pid, d):
    if not can('insurance'):
        abort(403)
    p = PreAuth.query.get_or_404(pid)
    if not can_see(p):
        abort(403)
    if d == 'approve':
        import secrets
        p.status = 'Approved'
        p.auth_code = 'PA-' + secrets.token_hex(3).upper()
        p.decided_at = _now()
        flash(f'Approved — auth code {p.auth_code}', 'ok')
    else:
        p.status = 'Rejected'
        p.reject_reason = request.values.get('reason') or 'Rejected'
        p.decided_at = _now()
        flash('Pre-auth rejected', 'ok')
    db.session.commit()
    log(f'Pre-auth #{p.id} {p.status}', entity=f'PreAuth#{p.id}')
    return redirect(url_for('insurance.preauth_list'))


# ==================================================== simple-entity CRUD (REG)
register('insurers', Insurer, 'Insurers',
         columns=[('Name', lambda o: f"<b>{h(o.name)}</b>"),
                  ('Code', lambda o: h(o.code or '—')),
                  ('Contact', lambda o: h(o.contact_person or '—')),
                  ('Phone', lambda o: h(o.phone or '—')),
                  ('Coverage', lambda o: f"{int(o.coverage_pct or 0)}%"),
                  ('Status', lambda o: pill('Active' if o.active in (True, None) else 'Inactive',
                                            'green' if o.active in (True, None) else 'grey'))],
         fields=[dict(name='name', label='Company Name', required=True),
                 dict(name='code', label='Short Code'),
                 dict(name='contact_person', label='Contact Person'),
                 dict(name='phone', label='Phone'), dict(name='email', label='Email'),
                 dict(name='address', label='Address'),
                 dict(name='coverage_pct', label='Default Coverage %', type='number'),
                 dict(name='ar_account', label='Receivable Account', default='1250'),
                 dict(name='active', label='Status', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: Insurer.query.order_by(Insurer.name),
         search=['name', 'code', 'contact_person'])

register('inscards', InsuranceCard, 'Insurance Cards',
         columns=[('Patient', lambda o: h(o.patient.name if o.patient else '—')),
                  ('Insurer', lambda o: h(o.insurer.name if o.insurer else '—')),
                  ('Policy #', lambda o: h(o.policy_no or '—')),
                  ('Plan', lambda o: h(o.plan or '—')),
                  ('Relation', lambda o: h(o.relation or '—')),
                  ('Valid to', lambda o: h(o.valid_to or '—')),
                  ('Status', lambda o: pill('Active' if o.active in (True, None) else 'Inactive',
                                            'green' if o.active in (True, None) else 'grey'))],
         fields=[dict(name='patient_id', label='Patient', type='select', options_fn=opt_patients, required=True),
                 dict(name='insurer_id', label='Insurer', type='select', options_fn=_opt_insurers, required=True),
                 dict(name='policy_no', label='Policy Number'),
                 dict(name='plan', label='Plan'),
                 dict(name='holder_name', label='Policy Holder'),
                 dict(name='relation', label='Relation', type='select',
                      options=[('Self', 'Self'), ('Spouse', 'Spouse'), ('Child', 'Child'), ('Other', 'Other')]),
                 dict(name='coverage_pct', label='Coverage % (blank = insurer default)', type='number'),
                 dict(name='valid_from', label='Valid From', type='date'),
                 dict(name='valid_to', label='Valid To', type='date'),
                 dict(name='active', label='Status', type='select',
                      options=[('1', 'Active'), ('', 'Inactive')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: InsuranceCard.query.order_by(InsuranceCard.id.desc()),
         search=['policy_no', 'plan', 'holder_name'])

register('coverage', CoverageRule, 'Coverage Rules',
         columns=[('Insurer', lambda o: h(o.insurer.name if o.insurer else '—')),
                  ('Category', lambda o: h(o.category or '—')),
                  ('Coverage', lambda o: f"{int(o.coverage_pct or 0)}%"),
                  ('Copay', lambda o: f"{int(o.copay_pct or 0)}%"),
                  ('Cap', lambda o: (money(o.annual_cap) if o.annual_cap else '—')),
                  ('Excluded', lambda o: pill('Excluded', 'red') if o.excluded else '—')],
         fields=[dict(name='insurer_id', label='Insurer', type='select', options_fn=_opt_insurers, required=True),
                 dict(name='category', label='Service Category', type='select',
                      options=[(c, c) for c in ('Consultation', 'Laboratory', 'Radiology', 'Pharmacy', 'Procedure', 'Other')]),
                 dict(name='coverage_pct', label='Coverage %', type='number'),
                 dict(name='copay_pct', label='Patient Copay %', type='number'),
                 dict(name='annual_cap', label='Annual Cap (0 = none)', type='number'),
                 dict(name='excluded', label='Excluded?', type='select',
                      options=[('', 'Covered'), ('1', 'Excluded')], as_bool=True),
                 dict(name='notes', label='Notes', type='textarea', full=True)],
         order=lambda: CoverageRule.query.order_by(CoverageRule.insurer_id))
