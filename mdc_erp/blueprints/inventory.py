"""Inventory extras: stock adjustments (with audit trail) and consumption report."""
import datetime as dt
from flask import Blueprint, request, redirect, url_for, flash, abort, jsonify
from markupsafe import escape as h
from ..extensions import db
from ..models import (Medicine, StockAdj, PharmacySale, Prescription, Purchase,
                      Warehouse, StockLevel, StockTransfer, Supplier)
from ..core.stock import (default_warehouse, ensure_levels, adjust_stock,
                          transfer_stock)
from ..core.posting import post_purchase
from ..core.printing import printable
from ..core.security import cur_user, can, login_required, log, csrf_token
from ..core.helpers import money, today, cur_year
from ..core.ui import page
from ..core.crud import stock_pill

bp = Blueprint('inventory', __name__)

ADJ_REASONS = ['Physical count correction', 'Damaged / broken', 'Expired write-off',
               'Received (no PO)', 'Returned to supplier', 'Internal use', 'Other']


def stockadj_view():
    """Adjustment form + history. Applying the change and recording it are atomic."""
    adjs = StockAdj.query.order_by(StockAdj.id.desc()).limit(150).all()
    meds = Medicine.query.order_by(Medicine.name).all()
    med_opts = ''.join(f"<option value='{m.id}'>{h(m.name)} (stock {m.qty or 0})</option>" for m in meds)
    reason_opts = ''.join(f"<option>{r}</option>" for r in ADJ_REASONS)
    wh_opts = ''.join(f"<option value='{w.id}'>{h(w.name)}</option>"
                      for w in Warehouse.query.filter_by(active=True).order_by(Warehouse.id).all())
    rows = ''
    for a in adjs:
        sign = 'var(--green)' if (a.qty_change or 0) >= 0 else 'var(--red)'
        rows += (f"<tr><td>{h(a.date)}</td><td>{h(a.medicine.name if a.medicine else '—')}</td>"
                 f"<td class='num' style='font-weight:700;color:{sign}'>{'+' if (a.qty_change or 0) >= 0 else ''}{a.qty_change:g}</td>"
                 f"<td>{h(a.reason or '—')}</td><td>{h(a.user or '—')}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='5'><div class='empty'><b>No adjustments yet</b>Corrections, damages and write-offs appear here.</div></td></tr>"
    body = f"""<div class="grid2">
      <div class="panel"><div class="ph"><h2>New Adjustment</h2></div><div class="pad">
        <form method="post" action="{url_for('inventory.stockadj_apply')}"><div class="fg">
          <div class="fld full"><label>Supply Item *</label><select name="medicine_id">{med_opts}</select></div>
          <div class="fld"><label>Quantity Change * (+ in / − out)</label><input name="qty_change" type="number" step="any" required></div>
          <div class="fld"><label>Date</label><input name="date" type="date" value="{today()}"></div>
          <div class="fld"><label>Warehouse</label><select name="warehouse_id">{wh_opts}</select></div>
          <div class="fld full"><label>Reason *</label><select name="reason">{reason_opts}</select></div>
          <div class="fld full"><label>Note (optional)</label><input name="note"></div>
        </div><div class="fa"><button class="btn primary">Apply Adjustment</button></div></form></div></div>
      <div class="panel"><div class="ph"><h2>Adjustment History</h2><span class="so">last 150 · full audit trail</span></div>
        <div class="tw"><table><thead><tr><th>Date</th><th>Item</th><th class="num">Change</th><th>Reason</th><th>By</th></tr></thead>
        <tbody>{rows}</tbody></table></div></div></div>"""
    return page('Stock Adjustments', body, 'stockadj')


@bp.route('/stock/adjust', methods=['POST'])
@login_required
def stockadj_apply():
    if not can('stockadj'):
        abort(403)
    m = Medicine.query.get_or_404(int(request.form['medicine_id']))
    try:
        change = float(request.form.get('qty_change') or 0)
    except ValueError:
        change = 0
    if not change:
        flash('Quantity change cannot be zero')
        return redirect(url_for('modules.module', mod='stockadj'))
    reason = (request.form.get('reason') or 'Other')
    note = (request.form.get('note') or '').strip()
    if note:
        reason = f'{reason} — {note}'[:120]
    wh = Warehouse.query.get(int(request.form['warehouse_id'])) if request.form.get('warehouse_id') else None
    adjust_stock(m, change, wh)
    db.session.add(StockAdj(date=request.form.get('date') or today(), medicine_id=m.id,
                            qty_change=change, reason=reason,
                            user=cur_user().username))
    db.session.commit()
    log(f'Stock adjust {m.name}: {change:+g} ({reason})')
    if m.qty <= (m.reorder or 0):
        from ..core.notify import notify
        notify(f'Low stock after adjustment: {m.name} — {m.qty:g} left',
               link='/m/inventory', role='storekeeper')
    flash(f'{m.name}: stock now {m.qty:g}')
    return redirect(url_for('modules.module', mod='stockadj'))


@bp.route('/stock/consume', methods=['POST'])
@login_required
def stock_consume():
    """Manually record that a quantity of a supply was USED UP (e.g. a box finished).
    Deducts stock and logs it as a 'Consumed (manual)' adjustment so it shows in the
    Consumption report as real consumption, not just a correction."""
    if not can('stockadj') and not can('inventory'):
        abort(403)
    m = Medicine.query.get_or_404(int(request.form['medicine_id']))
    try:
        used = abs(float(request.form.get('qty') or 0))
    except ValueError:
        used = 0
    if not used:
        flash('Enter how many were used')
        return redirect(url_for('modules.module', mod='consume'))
    note = (request.form.get('note') or '').strip()
    reason = 'Consumed (manual)' + (f' — {note}' if note else '')
    reason = reason[:120]
    wh = Warehouse.query.get(int(request.form['warehouse_id'])) if request.form.get('warehouse_id') else None
    adjust_stock(m, -used, wh)
    _sa = StockAdj(date=request.form.get('date') or today(), medicine_id=m.id,
                   qty_change=-used, reason=reason, user=cur_user().username)
    db.session.add(_sa)
    db.session.flush()
    # Accounting: consuming stock moves value from the inventory asset to expense.
    #   Dr 5120 Medical Supplies & Contrast (expense)  /  Cr 1300 Inventory (asset)
    # Valued at quantity used × unit cost. Skipped when cost is zero.
    _cost = used * (m.cost or 0)
    if _cost > 0.005:
        try:
            from ..core.posting import post_journal, acc_ensure
            acc_ensure('1300', 'Medical Supplies Inventory', 'Asset', '1000')
            acc_ensure('5120', 'Medical Supplies & Contrast', 'Expense', '5100')
            post_journal(_sa.date, f"CONS-{_sa.id:05d}",
                         f"Consumed {used:g} × {m.name}",
                         [('5120', _cost, 0), ('1300', 0, _cost)])
        except Exception:
            from ..core.helpers import log_error; log_error(f'consume posting {m.name}')
    db.session.commit()
    log(f'Consumed (manual) {m.name}: -{used:g} ({reason}) · expensed {money(_cost)}')
    if m.qty <= (m.reorder or 0):
        from ..core.notify import notify
        notify(f'Low stock after use: {m.name} — {m.qty:g} left', link='/m/inventory', role='storekeeper')
    flash(f'{m.name}: used {used:g} — stock now {m.qty:g}')
    return redirect(url_for('modules.module', mod='consume'))


def consume_view():
    """Quick 'mark as used / box finished' form + recent manual consumption list."""
    if not (can('stockadj') or can('inventory')):
        return page('Denied', "<div class='panel'><div class='pad'><b>No access.</b></div></div>")
    meds = Medicine.query.order_by(Medicine.name).all()
    med_opts = ''.join(f"<option value='{m.id}'>{h(m.name)} (in stock {m.qty or 0:g})</option>" for m in meds)
    wh_opts = ''.join(f"<option value='{w.id}'>{h(w.name)}</option>"
                      for w in Warehouse.query.filter_by(active=True).order_by(Warehouse.id).all())
    # recent manual consumption (reason starts with 'Consumed (manual)')
    recent = [a for a in StockAdj.query.order_by(StockAdj.id.desc()).limit(300).all()
              if (a.reason or '').startswith('Consumed (manual)')][:60]
    rows = ''
    for a in recent:
        rows += (f"<tr><td>{h(a.date)}</td><td>{h(a.medicine.name if a.medicine else '—')}</td>"
                 f"<td class='num' style='font-weight:700;color:var(--red)'>{a.qty_change:g}</td>"
                 f"<td>{h((a.reason or '').replace('Consumed (manual)','').lstrip(' —') or '—')}</td>"
                 f"<td>{h(a.user or '—')}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='5'><div class='empty'><b>Nothing used yet</b>Record a finished box or used supplies here.</div></td></tr>"
    body = f"""<div class="grid2">
      <div class="panel"><div class="ph"><h2>🧴 Consume / Mark as Used</h2><span class="so">record supplies used up (box finished)</span></div><div class="pad">
        <form method="post" action="{url_for('inventory.stock_consume')}"><div class="fg">
          <div class="fld full"><label>Supply Item *</label><select name="medicine_id">{med_opts}</select></div>
          <div class="fld"><label>Quantity Used *</label><input name="qty" type="number" step="any" min="0" placeholder="e.g. 1" required></div>
          <div class="fld"><label>Date</label><input name="date" type="date" value="{today()}"></div>
          <div class="fld full"><label>Warehouse</label><select name="warehouse_id">{wh_opts}</select></div>
          <div class="fld full"><label>Note (optional)</label><input name="note" placeholder="e.g. box finished in radiology"></div>
        </div><div class="fa"><button class="btn primary">Confirm Used</button></div></form>
        <div style="font-size:11.5px;color:var(--muted);margin-top:8px">This lowers stock, counts as consumption in the report, and books the cost as an <b>expense</b> (Dr Medical Supplies Expense / Cr Inventory). For corrections or damage use <b>Stock Adjust</b> instead.</div>
        </div></div>
      <div class="panel"><div class="ph"><h2>Recently Used</h2><span class="so">manual consumption · newest first</span></div>
        <div class="tw"><table><thead><tr><th>Date</th><th>Item</th><th class="num">Used</th><th>Note</th><th>By</th></tr></thead>
        <tbody>{rows}</tbody></table></div></div></div>"""
    return page('Consume Supplies', body, 'consume')


@bp.route('/consumption/pdf')
@login_required
def consumption_pdf():
    from flask import Response
    from ..core.pdfgen import ledger_pdf, available
    from ..core.security import setting
    y = request.args.get('year', type=int) or cur_year()
    yr = str(y)
    meds = Medicine.query.order_by(Medicine.name).all()
    sales = [s for s in PharmacySale.query.all() if (s.date or '').startswith(yr)]
    rx = [r for r in Prescription.query.filter_by(status='Dispensed').all() if (r.date or '').startswith(yr)]
    adjs = [a for a in StockAdj.query.all() if (a.date or '').startswith(yr)]
    rows = []; tot_val = 0.0
    for m in meds:
        sold = sum(s.qty or 0 for s in sales if s.medicine_id == m.id)
        disp = sum(r.qty or 0 for r in rx if r.medicine_id == m.id)
        m_adjs = [a for a in adjs if a.medicine_id == m.id]
        used = sum(-(a.qty_change or 0) for a in m_adjs if (a.reason or '').startswith('Consumed'))
        adj = sum(a.qty_change or 0 for a in m_adjs if not (a.reason or '').startswith('Consumed'))
        val = (m.qty or 0) * (m.cost or 0); tot_val += val
        rows.append([m.name, (m.batch or '-'), f'{sold:g}', f'{disp:g}', f'{used:g}', f'{adj:+g}',
                     f'{(m.qty or 0):g}', money(m.cost), money(val)])
    cols = [('Item', 'l', 36), ('Batch', 'l', 18), ('Sold', 'r', 14), ('Dispensed', 'r', 18),
            ('Used', 'r', 14), ('Adjusted', 'r', 16), ('On Hand', 'r', 16), ('Unit Cost', 'r', 18), ('Stock Value', 'r', 22)]
    totals = ['TOTAL STOCK VALUE', '', '', '', '', '', '', '', money(tot_val)]
    if not available():
        return redirect(url_for('modules.module', mod='consumption') + f'?year={y}')
    pdf = ledger_pdf(f'Consumption & Stock Valuation - FY {y}', 'pharmacy sales + dispensed + supplies used',
                     cols, rows, totals, company=setting('company', 'Modern Diagnostic Center'),
                     currency=setting('currency', '$'))
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + ';filename=Stock-Valuation.pdf'
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


def consumption_view():
    """Per-item consumption & valuation for a year: sold, dispensed, adjusted, on hand."""
    y = cur_year()
    yr = str(y)
    meds = Medicine.query.order_by(Medicine.name).all()
    sales = [s for s in PharmacySale.query.all() if (s.date or '').startswith(yr)]
    rx = [r for r in Prescription.query.filter_by(status='Dispensed').all() if (r.date or '').startswith(yr)]
    adjs = [a for a in StockAdj.query.all() if (a.date or '').startswith(yr)]
    rows = ''
    tot_out = tot_val = 0.0
    for m in meds:
        sold = sum(s.qty or 0 for s in sales if s.medicine_id == m.id)
        disp = sum(r.qty or 0 for r in rx if r.medicine_id == m.id)
        m_adjs = [a for a in adjs if a.medicine_id == m.id]
        # consumption-type adjustments (manual 'Consumed' + auto BOM 'Consumed:') count as USE
        used = sum(-(a.qty_change or 0) for a in m_adjs if (a.reason or '').startswith('Consumed'))
        # everything else is a correction/adjustment
        adj = sum(a.qty_change or 0 for a in m_adjs if not (a.reason or '').startswith('Consumed'))
        out = sold + disp + used
        val = (m.qty or 0) * (m.cost or 0)
        tot_out += out * (m.cost or 0)
        tot_val += val
        rows += (f"<tr><td><b>{h(m.name)}</b></td><td>{h(m.batch or '—')}</td>"
                 f"<td class='num'>{sold:g}</td><td class='num'>{disp:g}</td>"
                 f"<td class='num' style='color:var(--red)'>{used:g}</td>"
                 f"<td class='num' style='color:{'var(--green)' if adj >= 0 else 'var(--red)'}'>{adj:+g}</td>"
                 f"<td class='num'>{stock_pill(m)}</td>"
                 f"<td class='num'>{money(m.cost)}</td><td class='num'>{money(val)}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='9'><div class='empty'><b>No supplies</b>Add items in Inventory → Supplies.</div></td></tr>"
    yrs = ''.join(f"<a class='btn sm{' primary' if yy == y else ''}' href='?year={yy}'>{yy}</a> "
                  for yy in range(dt.date.today().year - 2, dt.date.today().year + 1))
    body = f"""<div class="panel"><div class="ph"><h2>Consumption & Stock Valuation · FY {y}</h2>
      <span class="so">pharmacy sales + dispensed prescriptions + supplies used</span><div class="sp"></div>{yrs}
      <button class="btn sm" onclick="MDCDoc.openSelf('Consumption Report','{url_for('inventory.consumption_pdf')}?year={y}')">Print</button></div>
      <div class="tw"><table><thead><tr><th>Item</th><th>Batch</th><th class="num">Sold</th>
      <th class="num">Dispensed (Rx)</th><th class="num">Used</th><th class="num">Adjusted</th><th class="num">On Hand</th>
      <th class="num">Unit Cost</th><th class="num">Stock Value</th></tr></thead><tbody>{rows}</tbody></table></div>
      <div class="pad"><div class="stmt">
        <div class="r"><span>Consumption cost this year (sold + dispensed + used × unit cost)</span><span class="amt">{money(tot_out)}</span></div>
        <div class="r grand"><span>Total Stock Value on hand</span><span class="amt">{money(tot_val)}</span></div>
      </div></div></div>"""
    return page('Consumption Report', body, 'consumption')


# ------------------------------------------------ PO workflow: order / receive
@bp.route('/purchase/<int:pid>/bill')
@login_required
def purchase_bill(pid):
    """Branded Vendor Bill document for a purchase — mirrors the customer invoice
    layout (Name / Payment Status / items / totals box) on the company letterhead."""
    if not can('purchases'):
        abort(403)
    from ..core.printing import printable
    p = Purchase.query.get_or_404(pid)
    total = p.total or 0; paid = p.paid or 0; bal = total - paid
    if bal <= 0.005 and total > 0:
        status, stcol = 'Paid', '#1FA66D'
    elif paid > 0:
        status, stcol = 'Partial', '#E7A100'
    else:
        status, stcol = 'Unpaid', '#C0392B'
    no = f"BILL-{p.id:04d}"
    supplier = h(p.supplier.name if p.supplier else '—')
    sup_phone = h(p.supplier.phone if (p.supplier and getattr(p.supplier, 'phone', None)) else '—')
    item_name = h(p.item or (p.medicine.name if p.medicine else '—'))
    ruser = h(p.pay_method or 'Logistics')

    rows = (f"<tr><td style='padding:7px 10px;border:1px solid #C9D2DC'>{item_name}</td>"
            f"<td style='padding:7px 10px;border:1px solid #C9D2DC;text-align:right'>{(p.qty or 1):g}</td>"
            f"<td style='padding:7px 10px;border:1px solid #C9D2DC;text-align:right'>{money(p.unit_cost)}</td>"
            f"<td style='padding:7px 10px;border:1px solid #C9D2DC;text-align:right'>{money(total)}</td></tr>")

    def _trow(label, val, bg='', fg='', bold=False, big=False):
        st = (f"background:{bg};" if bg else '') + (f"color:{fg};" if fg else 'color:#1F2933;')
        fw = '700' if bold else '500'; fs = '15px' if big else '13px'
        return (f"<tr><td style='padding:6px 12px;{st}font-weight:{fw};font-size:{fs}'>{label}</td>"
                f"<td style='padding:6px 12px;{st}font-weight:{fw};font-size:{fs};text-align:right'>{val}</td></tr>")

    totals = (
        "<table style='width:320px;border-collapse:collapse;margin-left:auto;margin-top:0'>"
        + _trow('Subtotal', money(total))
        + _trow('Total', money(total), bg='#4A5B8C', fg='#fff', bold=True)
        + _trow(f'Paid on {h(p.received_date or p.date)}', money(paid))
        + _trow('Amount Due', money(bal))
        + _trow('Discount', money(0))
        + _trow('Net Total', money(total), bg='#5A6B7B', fg='#FFE08A', bold=True, big=True)
        + "</table>")

    body = f"""
      <table style="width:100%;border-collapse:collapse;margin:2px 0 6px;font-size:14px">
        <tr>
          <td style="width:58%;vertical-align:top;line-height:2">
            <div><b style="color:#1F2933">Name:</b> &nbsp;<b>{supplier}</b></div>
            <div><b style="color:#1F2933">Supplier Phone:</b> &nbsp;<b>{sup_phone}</b></div>
          </td>
          <td style="width:42%;vertical-align:top;line-height:2.2">
            <div><b style="color:#1F2933">Payment Status:</b> &nbsp;<span style="background:{stcol};color:#fff;padding:2px 12px;border-radius:5px;font-weight:700;font-size:13px">{status}</span></div>
          </td>
        </tr>
      </table>
      <div style="font-size:19px;color:#4A5B8C;font-weight:600;margin:6px 0 10px">Vendor Bill {no}</div>
      <table style="width:100%;border-collapse:collapse;margin:0 0 14px;font-size:13.5px">
        <tr style="line-height:1.9">
          <td style="width:25%;vertical-align:top"><div style="color:#1F2933;font-weight:700">Invoice Date:</div><div><b>{h(p.date or '—')}</b></div></td>
          <td style="width:25%;vertical-align:top"><div style="color:#1F2933;font-weight:700">Reference:</div><div><b>{h(sup_phone)}</b></div></td>
          <td style="width:25%;vertical-align:top"><div style="color:#1F2933;font-weight:700">Category:</div><div><b>{h(p.category or '—')}</b></div></td>
          <td style="width:25%;vertical-align:top"><div style="color:#1F2933;font-weight:700">R. User:</div><div><b>{ruser}</b></div></td>
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
      <div style="clear:both;margin-top:26px;font-size:12.5px;color:#555">Vendor bill reference : <b>{no}</b> · Supplier: {supplier}</div>"""
    return printable(f"Vendor Bill {no}", body, doc_ref=no, barcode_text=no)


@bp.route('/purchase/<int:pid>')
@login_required
def purchase_view(pid):
    """Purchase detail with a sales-style workflow: Purchase Order → Receive
    Product → Bill (posted on receipt) → Register Payment."""
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid)
    _canmng = can('purchases')
    total = p.total or 0; paid = p.paid or 0; bal = total - paid
    _paid_full = total > 0 and bal <= 0.005
    item_name = h(p.item or (p.medicine.name if p.medicine else '—'))
    supplier = h(p.supplier.name if p.supplier else '—')

    # --- workflow status bar: PO → Received → Vendor Bill → Confirmed → Paid
    def _stage(label, active, done):
        cls = 'on' if active else ('done' if done else '')
        return f"<div class='po-step {cls}'>{label}</div>"
    st = p.status or 'Requested'
    received = st == 'Received' or bool(p.received_date)
    bs = p.bill_status or 'none'
    bill_created = bs in ('draft', 'posted')
    bill_posted = bs == 'posted'
    stages = (_stage('Purchase Order', st in ('Requested', 'Ordered'), received)
              + _stage('Received', received and not bill_created, bill_created)
              + _stage('Vendor Bill', bs == 'draft', bill_posted)
              + _stage('Confirmed', bill_posted and not _paid_full, _paid_full)
              + _stage('Paid', _paid_full, False))

    # --- action buttons, one clear next step at a time (like the invoice flow)
    btns = []
    if _canmng:
        if st == 'Requested':
            btns.append(f"<a class='btn primary' href='{url_for('inventory.po_order', pid=p.id)}'>✔ Confirm Order</a>")
        if st in ('Requested', 'Ordered'):
            btns.append(f"<a class='btn primary' href='{url_for('inventory.po_receive', pid=p.id)}'>📦 Receive Item</a>")
        if received and bs in ('none', None):
            btns.append(f"<a class='btn primary' href='{url_for('inventory.po_bill', pid=p.id)}'>🧾 Create Vendor Bill</a>")
        if bs == 'draft':
            btns.append(f"<a class='btn primary' href='{url_for('inventory.po_confirm_bill', pid=p.id)}'>✔ Confirm Bill</a>")
        if bill_posted and bal > 0.005:
            btns.append("<button class='btn ok' onclick=\"document.getElementById('poPayModal').style.display='flex'\">💵 Register Payment</button>")
        if bill_created:
            btns.append(f"<a class='btn gh' href='{url_for('inventory.purchase_bill', pid=p.id)}' data-file='{url_for('inventory.purchase_bill', pid=p.id)}' target='_blank'>🖨 Print Bill</a>")
        if received:
            btns.append(f"<a class='btn gh' href='{url_for('inventory.po_grn', pid=p.id)}' target='_blank'>🖨 GRN</a>")
        if st in ('Requested', 'Ordered'):
            btns.append(f"<a class='btn gh' href='{url_for('inventory.po_form', pid=p.id)}'>✎ Edit</a>")
    btns.append(f"<a class='btn gh' href='{url_for('modules.module', mod='purchases')}'>← Back</a>")

    # --- payment modal (method + amount), mirrors the invoice Register Payment
    _methods = ['Cash', 'Sahal', 'EVC', 'E. Dahab', 'MyCash', 'Premier Wallet', 'Bank', 'Card', 'Cheque']
    _mopts = ''.join(f"<option>{m}</option>" for m in _methods)
    pay_modal = f"""
    <div id="poPayModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:60;align-items:center;justify-content:center">
      <div style="background:#fff;border-radius:12px;max-width:420px;width:92%;padding:20px">
        <div style="font-weight:700;font-size:16px;color:var(--petrol);margin-bottom:4px">Register Payment · PUR-{p.id:04d}</div>
        <div style="color:var(--muted);font-size:12.5px;margin-bottom:14px">Supplier: {supplier} · Balance {money(bal)}</div>
        <form method="post" action="{url_for('inventory.po_pay', pid=p.id)}">
          <input type="hidden" name="_csrf" value="{csrf_token()}">
          <label style="font-size:12px;font-weight:700;color:var(--muted)">Amount</label>
          <input name="amount" type="number" step="any" min="0" value="{bal:g}" style="width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:8px;margin:4px 0 12px">
          <label style="font-size:12px;font-weight:700;color:var(--muted)">Payment Method</label>
          <select name="method" style="width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:8px;margin:4px 0 16px">{_mopts}</select>
          <div style="display:flex;gap:8px;justify-content:flex-end">
            <button type="button" class="btn gh" onclick="document.getElementById('poPayModal').style.display='none'">Cancel</button>
            <button class="btn ok">Confirm Payment</button>
          </div>
        </form>
      </div>
    </div>"""

    css = """<style>
      .po-bar{display:flex;gap:0;margin:14px 0}
      .po-step{flex:1;text-align:center;padding:9px 6px;font-size:12.5px;font-weight:700;color:#8894a3;background:#EEF3F8;border-right:2px solid #fff;position:relative}
      .po-step.on{background:var(--petrol);color:#fff}.po-step.done{background:#D7E5D7;color:#1F6B32}
      .po-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 24px;margin-top:8px}
      .po-grid .k{color:var(--muted);font-size:12.5px}.po-grid .v{font-weight:600}
      .po-tot{margin-top:14px;border-top:1px solid var(--line);padding-top:10px}
      .po-tot .r{display:flex;justify-content:space-between;padding:3px 0}
      .po-tot .r.big{font-size:18px;font-weight:800;color:var(--petrol)}
    </style>"""

    body = f"""{css}
    <div class="panel"><div class="pad" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <div style="font-weight:800;font-size:18px;color:var(--petrol)">PUR-{p.id:04d}</div>
      <span class="pill {'green' if _paid_full else ('amber' if received else 'grey')}">{'Paid' if _paid_full else (p.status or 'Requested')}</span>
      <div style="flex:1"></div>{''.join(btns)}
    </div>
    <div class="pad"><div class="po-bar">{stages}</div>
      <div class="po-grid">
        <div><div class="k">Supplier</div><div class="v">{supplier}</div></div>
        <div><div class="k">Date</div><div class="v">{h(p.date or '—')}</div></div>
        <div><div class="k">Item</div><div class="v">{item_name}</div></div>
        <div><div class="k">Category</div><div class="v">{h(p.category or '—')}</div></div>
        <div><div class="k">Quantity</div><div class="v">{(p.qty or 0):g}</div></div>
        <div><div class="k">Unit Cost</div><div class="v">{money(p.unit_cost)}</div></div>
        <div><div class="k">Received</div><div class="v">{h(p.received_date or '— not yet —')}</div></div>
        <div><div class="k">Payment Method</div><div class="v">{h(p.pay_method or 'Cash')}</div></div>
      </div>
      <div class="po-tot">
        <div class="r big"><span>Total</span><span>{money(total)}</span></div>
        <div class="r"><span>Paid</span><span>{money(paid)}</span></div>
        <div class="r"><span><b>Balance Due</b></span><span><b>{money(bal)}</b></span></div>
      </div>
    </div></div>{pay_modal}"""
    return page(f'Purchase PUR-{p.id:04d}', body, 'purchases',
                crumbs=[('Purchases', url_for('modules.module', mod='purchases')), (f'PUR-{p.id:04d}', None)])


@bp.route('/purchase/<int:pid>/pay', methods=['POST'])
@login_required
def po_pay(pid):
    """Register a payment against a purchase bill — like the sales-side Register
    Payment. Settles part or all of the outstanding balance and books it to the
    account matching the chosen method (Cash/Sahal/E.Dahab/Bank/…)."""
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid)
    if p.bill_status != 'posted':
        flash('Confirm the vendor bill before registering a payment.')
        return redirect(url_for('inventory.purchase_view', pid=pid))
    try:
        amt = float(request.form.get('amount') or 0)
    except ValueError:
        amt = 0
    method = request.form.get('method') or 'Cash'
    bal = (p.total or 0) - (p.paid or 0)
    if amt <= 0:
        flash('Enter a payment amount'); return redirect(url_for('inventory.purchase_view', pid=pid))
    if amt > bal + 0.005:
        amt = bal   # never overpay
    p.paid = (p.paid or 0) + amt
    p.pay_method = method
    db.session.commit()
    try:
        from ..core.posting import repost_purchase_payment
        repost_purchase_payment(p)   # Dr Accounts Payable / Cr cash-or-wallet
    except Exception:
        db.session.rollback()
        from ..core.helpers import log_error; log_error(f'po_pay repost PUR-{pid:04d}')
    log(f'PUR-{pid:04d} payment {money(amt)} via {method}',
        action_type='Purchase Payment', entity=f'PUR-{pid:04d}', new=f'paid {money(p.paid)}')
    _newbal = (p.total or 0) - (p.paid or 0)
    flash(f'✓ Paid {money(amt)} via {method}. ' +
          ('Fully paid.' if _newbal <= 0.005 else f'Balance {money(_newbal)} remaining.'))
    return redirect(url_for('inventory.purchase_view', pid=pid))


@bp.route('/purchase/<int:pid>/order')
@login_required
def po_order(pid):
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid)
    if p.status == 'Requested':
        p.status = 'Ordered'
        db.session.commit()
        log(f'PO PUR-{pid:04d} approved & ordered')
        flash(f'PUR-{pid:04d} marked as Ordered')
    return redirect(url_for('modules.module', mod='purchases'))


@bp.route('/purchase/<int:pid>/receive')
@login_required
def po_receive(pid):
    """Receive Item: stock in only (like receiving goods). No accounting yet —
    the vendor bill is created and confirmed as separate steps."""
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid)
    if p.status not in ('Requested', 'Ordered'):
        flash('Already received')
        return redirect(url_for('inventory.purchase_view', pid=pid))
    p.status = 'Received'
    p.received_date = today()
    if p.medicine_id:
        m = Medicine.query.get(p.medicine_id)
        if m:
            wh = p.warehouse or default_warehouse()
            adjust_stock(m, p.qty or 0, wh)
            log(f'GRN PUR-{pid:04d}: +{p.qty:g} {m.name} into {wh.name if wh else "Main"}')
    db.session.commit()
    from ..core.notify import notify
    notify(f'Goods received: PUR-{pid:04d} · {p.item or (p.medicine.name if p.medicine else "")} '
           f'({p.qty:g} pcs, {money(p.total)})', link='/m/purchases', role='accountant')
    log(f'PO PUR-{pid:04d} received')
    flash(f'📦 PUR-{pid:04d} received — stock updated. Create the vendor bill next.')
    return redirect(url_for('inventory.purchase_view', pid=pid))


@bp.route('/purchase/<int:pid>/create-bill')
@login_required
def po_bill(pid):
    """Create Vendor Bill (draft) — like a draft invoice, not yet posted."""
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid)
    if p.bill_status not in (None, 'none'):
        flash('Vendor bill already created.')
        return redirect(url_for('inventory.purchase_view', pid=pid))
    p.bill_status = 'draft'
    db.session.commit()
    log(f'Vendor bill created (draft) PUR-{pid:04d}')
    flash(f'🧾 Vendor bill created for PUR-{pid:04d}. Confirm it to post to the ledger.')
    return redirect(url_for('inventory.purchase_view', pid=pid))


@bp.route('/purchase/<int:pid>/confirm-bill')
@login_required
def po_confirm_bill(pid):
    """Confirm the vendor bill → posts Dr Inventory / Cr Accounts Payable
    (mirrors confirming a customer invoice)."""
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid)
    if p.bill_status != 'draft':
        flash('Only a draft vendor bill can be confirmed.')
        return redirect(url_for('inventory.purchase_view', pid=pid))
    p.bill_status = 'posted'
    db.session.commit()
    try:
        post_purchase(p)   # Dr 1300 Inventory / Cr 2100 Accounts Payable
    except Exception:
        db.session.rollback()
        from ..core.helpers import log_error; log_error(f'confirm bill PUR-{pid:04d}')
    log(f'Vendor bill CONFIRMED & posted PUR-{pid:04d}', action_type='Edit', entity=f'PUR-{pid:04d}')
    flash(f'✓ Vendor bill PUR-{pid:04d} confirmed and posted to the ledger. Register the payment below.')
    return redirect(url_for('inventory.purchase_view', pid=pid))


@bp.route('/purchase/<int:pid>/grn')
@login_required
def po_grn(pid):
    """Printable Goods Received Note."""
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid)
    wh = p.warehouse or default_warehouse()
    return printable(f'Goods Received Note · PUR-{p.id:04d}', f"""
      <p><b>Supplier:</b> {h(p.supplier.name if p.supplier else '—')}<br>
      <b>PO Date:</b> {h(p.date)} · <b>Received:</b> {h(p.received_date or '—')}<br>
      <b>Warehouse:</b> {h(wh.name if wh else 'Main Store')}</p>
      <table style="width:100%;border-collapse:collapse;margin:12px 0">
        <thead><tr style="border-bottom:2px solid #333">
          <th style="text-align:left;padding:6px">Item</th><th style="text-align:left;padding:6px">Category</th>
          <th style="text-align:right;padding:6px">Qty</th><th style="text-align:right;padding:6px">Unit Cost</th>
          <th style="text-align:right;padding:6px">Total</th></tr></thead>
        <tbody><tr><td style="padding:6px">{h(p.item or (p.medicine.name if p.medicine else '—'))}</td>
          <td style="padding:6px">{h(p.category or '—')}</td>
          <td style="text-align:right;padding:6px">{p.qty:g}</td>
          <td style="text-align:right;padding:6px">{money(p.unit_cost)}</td>
          <td style="text-align:right;padding:6px">{money(p.total)}</td></tr></tbody></table>
      <div style="max-width:280px;margin-left:auto">
        <div style="display:flex;justify-content:space-between;padding:3px 0;font-weight:700;border-top:2px solid #333"><span>Total</span><span>{money(p.total)}</span></div>
        <div style="display:flex;justify-content:space-between;padding:3px 0"><span>Paid</span><span>{money(p.paid)}</span></div>
        <div style="display:flex;justify-content:space-between;padding:3px 0"><span>Balance Payable</span><span>{money((p.total or 0)-(p.paid or 0))}</span></div></div>
      <p style="margin-top:40px">Received by: ____________________ &nbsp;&nbsp;&nbsp; Storekeeper: ____________________</p>""",
      doc_ref=f'PUR-{p.id:04d}', barcode_text=f'PUR-{p.id:04d}')


# --------------------------------------------------------- warehouse transfers
def transfers_view():
    transfers = StockTransfer.query.order_by(StockTransfer.id.desc()).limit(150).all()
    whs = Warehouse.query.filter_by(active=True).order_by(Warehouse.id).all()
    meds = Medicine.query.order_by(Medicine.name).all()
    med_opts = ''.join(f"<option value='{m.id}'>{h(m.name)} (total {m.qty or 0:g})</option>" for m in meds)
    wh_opts = ''.join(f"<option value='{w.id}'>{h(w.name)}</option>" for w in whs)
    # per-warehouse stock matrix
    head = '<th>Item</th>' + ''.join(f'<th class="num">{h(w.name)}</th>' for w in whs) + '<th class="num">Total</th>'
    mrows = ''
    for m in meds:
        ensure_levels(m)
        cells = ''
        for w in whs:
            lv = StockLevel.query.filter_by(medicine_id=m.id, warehouse_id=w.id).first()
            q = lv.qty if lv else 0
            cells += f"<td class='num'>{q:g}</td>"
        mrows += f"<tr><td><b>{h(m.name)}</b></td>{cells}<td class='num' style='font-weight:700'>{m.qty or 0:g}</td></tr>"
    from ..extensions import db as _db
    _db.session.commit()
    if not mrows:
        mrows = f"<tr><td colspan='{len(whs)+2}'><div class='empty'><b>No supplies</b></div></td></tr>"
    trows = ''
    for t in transfers:
        trows += (f"<tr><td>{h(t.date)}</td><td>{h(t.medicine.name if t.medicine else '—')}</td>"
                  f"<td>{h(t.from_wh.name if t.from_wh else '—')} → {h(t.to_wh.name if t.to_wh else '—')}</td>"
                  f"<td class='num'>{t.qty:g}</td><td>{h(t.note or '—')}</td><td>{h(t.user or '—')}</td></tr>")
    if not trows:
        trows = "<tr><td colspan='6'><div class='empty'><b>No transfers yet</b></div></td></tr>"
    body = f"""<div class="grid2">
      <div class="panel"><div class="ph"><h2>New Transfer</h2></div><div class="pad">
        <form method="post" action="{url_for('inventory.transfer_apply')}"><div class="fg">
          <div class="fld full"><label>Supply Item *</label><select name="medicine_id">{med_opts}</select></div>
          <div class="fld"><label>From Warehouse *</label><select name="from_id">{wh_opts}</select></div>
          <div class="fld"><label>To Warehouse *</label><select name="to_id">{wh_opts}</select></div>
          <div class="fld"><label>Quantity *</label><input name="qty" type="number" step="any" required></div>
          <div class="fld"><label>Date</label><input name="date" type="date" value="{today()}"></div>
          <div class="fld full"><label>Note</label><input name="note"></div>
        </div><div class="fa"><button class="btn primary">Transfer</button></div></form></div></div>
      <div class="panel"><div class="ph"><h2>Stock by Warehouse</h2></div>
        <div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{mrows}</tbody></table></div></div>
      </div>
      <div class="panel"><div class="ph"><h2>Transfer History</h2><span class="so">last 150</span></div>
        <div class="tw"><table><thead><tr><th>Date</th><th>Item</th><th>Route</th><th class="num">Qty</th><th>Note</th><th>By</th></tr></thead>
        <tbody>{trows}</tbody></table></div></div>"""
    return page('Stock Transfers', body, 'transfers')


@bp.route('/stock/transfer', methods=['POST'])
@login_required
def transfer_apply():
    if not can('transfers'):
        abort(403)
    m = Medicine.query.get_or_404(int(request.form['medicine_id']))
    f_wh = Warehouse.query.get_or_404(int(request.form['from_id']))
    t_wh = Warehouse.query.get_or_404(int(request.form['to_id']))
    try:
        qty = float(request.form.get('qty') or 0)
    except ValueError:
        qty = 0
    err = transfer_stock(m, f_wh, t_wh, qty)
    if err:
        flash(err)
        return redirect(url_for('modules.module', mod='transfers'))
    db.session.add(StockTransfer(date=request.form.get('date') or today(), medicine_id=m.id,
                                 from_id=f_wh.id, to_id=t_wh.id, qty=qty,
                                 note=(request.form.get('note') or '')[:120],
                                 user=cur_user().username))
    db.session.commit()
    log(f'Stock transfer {m.name}: {qty:g} {f_wh.name} → {t_wh.name}')
    flash(f'Transferred {qty:g} × {m.name} to {t_wh.name}')
    return redirect(url_for('modules.module', mod='transfers'))


# ============================ ODOO-STYLE STOCK OVERVIEW ========================
INV_ODOO_CSS = """<style>
.iv-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.iv-stat{flex:1;min-width:150px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
.iv-stat .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
.iv-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
.iv-stat.a{border-left:3px solid var(--petrol)} .iv-stat.b{border-left:3px solid var(--green)}
.iv-stat.c{border-left:3px solid var(--amber)} .iv-stat.d{border-left:3px solid var(--red)}
.iv-chip{display:inline-block;padding:5px 12px;border:1px solid var(--line);border-radius:20px;font-size:12.5px;font-weight:600;color:var(--muted);margin-right:6px;text-decoration:none}
.iv-chip.on{background:var(--petrol);color:#fff;border-color:var(--petrol)}
.iv-onhand{font-family:var(--fd);font-weight:700}
</style>"""


def _stock_status(m):
    if (m.qty or 0) <= 0:
        return ('Out of Stock', 'red')
    if (m.qty or 0) <= (m.reorder or 0):
        return ('Low Stock', 'amber')
    return ('In Stock', 'green')


@bp.route('/stock/quick-add', methods=['POST'])
@login_required
def stock_quick_add():
    """Create a new supply item (Medicine) inline from the Purchase Order form —
    Odoo's 'Create & Edit'. Returns JSON {id, name, cost} so the form can select it
    without a page reload."""
    if not can('purchases') and not can('inventory'):
        return jsonify({'error': 'forbidden'}), 403
    name = (request.form.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Product name is required'}), 400
    try:
        cost = float(request.form.get('cost') or 0)
    except ValueError:
        cost = 0
    try:
        reorder = float(request.form.get('reorder') or 0)
    except ValueError:
        reorder = 0
    m = Medicine(name=name[:120], batch=(request.form.get('batch') or '').strip() or None,
                 expiry=(request.form.get('expiry') or '').strip() or None,
                 qty=0, reorder=reorder, cost=cost, price=0)
    db.session.add(m); db.session.commit()
    log(f'Product created (inline): {m.name}', action_type='Create', entity=f'MED-{m.id}')
    return jsonify({'id': m.id, 'name': m.name, 'cost': cost, 'stock': 0})


@bp.route('/purchase/new', methods=['GET'])
@bp.route('/purchase/<int:pid>/form', methods=['GET'])
@login_required
def po_form(pid=None):
    """Odoo-style Purchase Order / RFQ form: statusbar, vendor + deadline + receipt,
    a product line, discount, terms and a totals box."""
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid) if pid else None
    st = (p.status if p else 'Requested')
    # ---- statusbar: RFQ → Confirmed → Received → Billed → Paid
    def _seg(label, active, done):
        cls = 'on' if active else ('done' if done else '')
        return f"<div class='po-step {cls}'>{label}</div>"
    _received = bool(p and (p.status == 'Received' or p.received_date))
    _paid_full = bool(p and (p.total or 0) > 0 and (p.total or 0) - (p.paid or 0) <= 0.005)
    bar = (_seg('Request for Quotation', st in ('Requested',), st not in ('Requested',))
           + _seg('Purchase Order', st == 'Ordered', _received or _paid_full)
           + _seg('Received', st == 'Received' and not _paid_full, _paid_full)
           + _seg('Paid', _paid_full, False))

    sup_opts = "<option value=''>— select vendor —</option>" + ''.join(
        f"<option value='{s.id}' {'selected' if (p and p.supplier_id == s.id) else ''}>{h(s.name)}</option>"
        for s in Supplier.query.order_by(Supplier.name).all())
    med_opts = "<option value=''>— non-stock / free text —</option>" + ''.join(
        f"<option value='{m.id}' {'selected' if (p and p.medicine_id == m.id) else ''}>{h(m.name)} (stock {m.qty or 0})</option>"
        for m in Medicine.query.order_by(Medicine.name).all())
    cat_opts = ''.join(f"<option {'selected' if (p and p.category == c) else ''}>{c}</option>"
                       for c in ['Medical Supplies', 'Contrast Media', 'Reagents', 'Films', 'Equipment', 'Other'])
    _methods = ['Cash', 'Sahal', 'EVC', 'E. Dahab', 'MyCash', 'Premier Wallet', 'Bank', 'Card', 'Cheque',
                'Credit / Payable — pay the supplier later']
    pm_opts = ''.join(f"<option value='{m.split(' — ')[0]}' {'selected' if (p and p.pay_method == m.split(' — ')[0]) else ''}>{m}</option>" for m in _methods)

    v = lambda x: h(x) if x else ''
    qty = (p.qty if p else 1) or 1
    unit = (p.unit_cost if p else 0) or 0
    disc = (p.discount if p else 0) or 0
    subtotal = qty * unit
    net = max(subtotal - disc, 0)
    action = url_for('inventory.po_save', pid=p.id) if p else url_for('inventory.po_save')

    # top action buttons by state
    tb = []
    if not p or st == 'Requested':
        tb.append("<button form='poForm' class='btn primary'>💾 Save</button>")
    if p and st == 'Requested':
        tb.append(f"<a class='btn' href='{url_for('inventory.po_order', pid=p.id)}'>✔ Confirm Order</a>")
    if p and st in ('Requested', 'Ordered'):
        tb.append(f"<a class='btn' href='{url_for('inventory.po_receive', pid=p.id)}'>📦 Receive Products</a>")
    if p:
        tb.append(f"<a class='btn gh' href='{url_for('inventory.po_grn', pid=p.id)}' target='_blank'>🖨 Print RFQ</a>")
        if st in ('Requested', 'Ordered'):
            tb.append(f"<a class='btn gh' href='{url_for('inventory.po_cancel', pid=p.id)}'>✖ Cancel</a>")
    tb.append(f"<a class='btn gh' href='{url_for('modules.module', mod='purchases')}'>Discard</a>")

    css = """<style>
      .po-bar{display:flex;margin:12px 0 18px}
      .po-step{flex:1;text-align:center;padding:9px 6px;font-size:12px;font-weight:700;color:#8894a3;background:#EEF3F8;border-right:2px solid #fff}
      .po-step.on{background:var(--petrol);color:#fff}.po-step.done{background:#D7E5D7;color:#1F6B32}
      .po-hd{font-size:13px;color:var(--muted);font-weight:600;margin-bottom:2px}
      .po-title{font-size:26px;font-weight:800;color:var(--ink);margin:0 0 14px}
      .po-cols{display:grid;grid-template-columns:1fr 1fr;gap:8px 40px;margin-bottom:8px}
      .po-f{display:flex;flex-direction:column;gap:3px;margin-bottom:8px}
      .po-f label{font-size:12.5px;color:var(--muted);font-weight:600}
      .po-f input,.po-f select,.po-f textarea{padding:8px 10px;border:1px solid var(--line);border-radius:7px;font-size:14px;width:100%}
      .po-tabs{display:flex;gap:18px;border-bottom:2px solid var(--line);margin:10px 0 12px}
      .po-tab{padding:8px 2px;font-weight:700;color:var(--petrol);border-bottom:2px solid var(--petrol);margin-bottom:-2px}
      .po-line th{background:#F7F9FB;text-align:left;padding:8px 10px;font-size:12px;color:var(--muted);border-bottom:1px solid var(--line)}
      .po-line td{padding:6px 10px;border-bottom:1px solid var(--line)}
      .po-line input,.po-line select{padding:7px 9px;border:1px solid var(--line);border-radius:6px;width:100%;font-size:13.5px}
      .po-tot{margin-left:auto;width:300px;margin-top:14px}
      .po-tot .r{display:flex;justify-content:space-between;padding:5px 0;font-size:14px}
      .po-tot .r.net{border-top:2px solid var(--line);font-weight:800;font-size:17px;color:var(--petrol);padding-top:8px}
      .po-foot{display:flex;gap:24px;border-top:2px solid #37506A;padding-top:14px;margin-top:6px;flex-wrap:wrap}
    </style>
    <script>
    (function(){
      function num(id){ var e=document.getElementById(id); return e?(parseFloat(e.value)||0):0; }
      function set(id,val){ var e=document.getElementById(id); if(e) e.textContent='$'+val.toFixed(2); }
      function poCalc(){
        var q=num('poQty'), u=num('poUnit'), d=num('poDisc');
        var sub=q*u, net=sub-d; if(net<0) net=0;
        set('poSub',sub); set('poLineSub',sub); set('poDiscOut',d); set('poNet',net);
      }
      window.poCalc=poCalc;
      function boot(){
        ['poQty','poUnit','poDisc'].forEach(function(id){
          var e=document.getElementById(id);
          if(e){ e.addEventListener('input',poCalc); e.addEventListener('change',poCalc); }
        });
        var sel=document.getElementById('poMed');
        if(sel){ sel.addEventListener('change',function(){
          var t=sel.options[sel.selectedIndex].text || '';
          var itm=document.getElementById('poItem');
          if(itm && !itm.value){ itm.value=t.split(' (stock')[0]; }
        }); }
        poCalc();
      }
      if(document.readyState!=='loading') boot();
      else document.addEventListener('DOMContentLoaded',boot);
    })();
    </script>"""

    body = f"""{css}
    <div class="panel"><div class="pad" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      {''.join(tb)}
      <div style="flex:1"></div>
      <span class="pill {'green' if _paid_full else ('amber' if _received else 'grey')}">{'Paid' if _paid_full else st}</span>
    </div>
    <div class="pad">
      <div class="po-bar">{bar}</div>
      <form id="poForm" method="post" action="{action}">
        <input type="hidden" name="_csrf" value="{csrf_token()}">
        <div class="po-hd">Request for Quotation</div>
        <div class="po-title">{('PUR-%04d' % p.id) if p else 'New'}</div>
        <div class="po-cols">
          <div>
            <div class="po-f"><label>Vendor</label><select name="supplier_id">{sup_opts}</select></div>
            <div class="po-f"><label>Vendor Reference</label><input name="vendor_ref" value="{v(p.vendor_ref if p else '')}" placeholder="their quote / invoice no"></div>
          </div>
          <div>
            <div class="po-f"><label>Order Deadline</label><input type="date" name="order_deadline" value="{v(p.order_deadline if p else today())}"></div>
            <div class="po-f"><label>Receipt Date (expected)</label><input type="date" name="expected_date" value="{v(p.expected_date if p else '')}"></div>
          </div>
        </div>

        <div class="po-tabs"><div class="po-tab">Products</div></div>
        <table class="po-line" style="width:100%;border-collapse:collapse">
          <thead><tr><th style="width:26%">Product</th><th>Description</th><th style="width:12%">Quantity</th><th style="width:14%">Unit Price</th><th style="width:16%;text-align:right">Subtotal</th></tr></thead>
          <tbody><tr>
            <td><select id="poMed" name="medicine_id">{med_opts}</select>
                <a href="javascript:void(0)" onclick="document.getElementById('newProdModal').style.display='flex'" style="font-size:12px;color:var(--petrol);font-weight:700;display:inline-block;margin-top:4px">+ Create &amp; Edit product…</a></td>
            <td><input id="poItem" name="item" value="{v(p.item if p else '')}" placeholder="item / description"></td>
            <td><input id="poQty" name="qty" type="number" step="any" value="{qty:g}"></td>
            <td><input id="poUnit" name="unit_cost" type="number" step="any" value="{unit:g}"></td>
            <td style="text-align:right;font-weight:700"><span id="poLineSub">${subtotal:.2f}</span></td>
          </tr></tbody>
        </table>
        <div class="po-f" style="max-width:280px;margin-top:10px"><label>Category</label><select name="category">{cat_opts}</select></div>

        <div class="po-foot">
          <div style="flex:1;min-width:240px">
            <div class="po-f"><label>Discount (Fixed Amount)</label><input id="poDisc" name="discount" type="number" step="any" value="{disc:g}" style="max-width:180px"></div>
            <div class="po-f"><label>Terms &amp; Conditions</label><textarea name="terms" rows="2" placeholder="Define your terms and conditions …">{v(p.terms if p else '')}</textarea></div>
          </div>
          <div class="po-tot">
            <div class="r"><span>Untaxed Amount</span><span id="poSub">${subtotal:.2f}</span></div>
            <div class="r"><span>Discount</span><span id="poDiscOut">${disc:.2f}</span></div>
            <div class="r"><span>Taxes</span><span>$0.00</span></div>
            <div class="r net"><span>Net Total</span><span id="poNet">${net:.2f}</span></div>
          </div>
        </div>
      </form>
    </div></div>
    <div id="newProdModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:70;align-items:center;justify-content:center">
      <div style="background:#fff;border-radius:12px;max-width:520px;width:94%;padding:22px;max-height:90vh;overflow:auto">
        <div style="display:flex;align-items:center;margin-bottom:12px">
          <div style="font-weight:800;font-size:17px;color:var(--petrol)">Create Product</div>
          <div style="flex:1"></div>
          <a href="javascript:void(0)" onclick="document.getElementById('newProdModal').style.display='none'" style="font-size:20px;color:var(--muted);text-decoration:none">×</a>
        </div>
        <div class="po-f"><label>Product Name *</label><input id="np_name" placeholder="e.g. Contrast Media (Iohexol)"></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 16px">
          <div class="po-f"><label>Category</label><select id="np_cat">{cat_opts}</select></div>
          <div class="po-f"><label>Unit Cost</label><input id="np_cost" type="number" step="any" value="0"></div>
          <div class="po-f"><label>Reorder Level</label><input id="np_reorder" type="number" step="any" value="0"></div>
          <div class="po-f"><label>Batch / Lot</label><input id="np_batch" placeholder="optional"></div>
          <div class="po-f"><label>Expiry Date</label><input id="np_expiry" type="date"></div>
        </div>
        <div id="np_err" style="color:var(--red);font-size:12.5px;margin:4px 0"></div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn gh" onclick="document.getElementById('newProdModal').style.display='none'">Discard</button>
          <button type="button" class="btn primary" onclick="npSave()">💾 Save &amp; use</button>
        </div>
      </div>
    </div>
    <script>
    function npSave(){{
      var name=document.getElementById('np_name').value.trim();
      var err=document.getElementById('np_err'); err.textContent='';
      if(!name){{ err.textContent='Product name is required'; return; }}
      var fd=new FormData();
      fd.append('name',name);
      fd.append('cost',document.getElementById('np_cost').value||'0');
      fd.append('reorder',document.getElementById('np_reorder').value||'0');
      fd.append('batch',document.getElementById('np_batch').value||'');
      fd.append('expiry',document.getElementById('np_expiry').value||'');
      var _t=document.querySelector('#poForm input[name=_csrf]');
      if(_t) fd.append('_csrf', _t.value);
      fetch('{url_for('inventory.stock_quick_add')}',{{method:'POST',body:fd,headers:{{'X-Requested-With':'fetch'}}}})
      .then(function(r){{return r.json();}}).then(function(d){{
        if(d.error){{ err.textContent=d.error; return; }}
        var sel=document.getElementById('poMed');
        var opt=document.createElement('option');
        opt.value=d.id; opt.textContent=d.name+' (stock '+(d.stock||0)+')'; opt.selected=true;
        sel.appendChild(opt);
        // fill the line: description + unit price from the new product
        var itm=document.getElementById('poItem'); if(itm) itm.value=d.name;
        var unit=document.getElementById('poUnit'); if(unit && d.cost){{ unit.value=d.cost; }}
        var cat=document.querySelector('select[name=category]');
        var npc=document.getElementById('np_cat'); if(cat && npc){{ cat.value=npc.value; }}
        if(window.poCalc) window.poCalc();
        document.getElementById('newProdModal').style.display='none';
        // reset modal
        ['np_name','np_batch'].forEach(function(id){{document.getElementById(id).value='';}});
      }}).catch(function(){{ err.textContent='Could not create the product — try again.'; }});
    }}
    </script>"""
    return page('Purchase Order', body, 'purchases',
                crumbs=[('Purchase Orders', url_for('modules.module', mod='purchases')),
                        (('PUR-%04d' % p.id) if p else 'New', None)])


@bp.route('/purchase/save', methods=['POST'])
@bp.route('/purchase/<int:pid>/save', methods=['POST'])
@login_required
def po_save(pid=None):
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid) if pid else Purchase(status='Requested')
    f = request.form
    p.supplier_id = int(f['supplier_id']) if f.get('supplier_id') else None
    p.vendor_ref = (f.get('vendor_ref') or '').strip() or None
    p.order_deadline = f.get('order_deadline') or None
    p.expected_date = f.get('expected_date') or None
    p.date = p.date or (f.get('order_deadline') or today())
    p.medicine_id = int(f['medicine_id']) if f.get('medicine_id') else None
    p.item = (f.get('item') or '').strip() or None
    p.category = f.get('category') or None
    try: p.qty = float(f.get('qty') or 1)
    except ValueError: p.qty = 1
    try: p.unit_cost = float(f.get('unit_cost') or 0)
    except ValueError: p.unit_cost = 0
    try: p.discount = float(f.get('discount') or 0)
    except ValueError: p.discount = 0
    p.total = max(p.qty * p.unit_cost - (p.discount or 0), 0)
    try: p.paid = float(f.get('paid') or 0)
    except ValueError: p.paid = 0
    p.pay_method = f.get('pay_method') or 'Cash'
    p.terms = (f.get('terms') or '').strip() or None
    if not pid:
        db.session.add(p)
    db.session.commit()
    log(f'RFQ saved PUR-{p.id:04d}', entity=f'PUR-{p.id:04d}')
    flash(f'✔ Request for Quotation PUR-{p.id:04d} saved.')
    return redirect(url_for('inventory.po_form', pid=p.id))


@bp.route('/purchase/<int:pid>/cancel')
@login_required
def po_cancel(pid):
    if not can('purchases'):
        abort(403)
    p = Purchase.query.get_or_404(pid)
    p.status = 'Cancelled'; db.session.commit()
    log(f'PO PUR-{pid:04d} cancelled')
    flash(f'Purchase PUR-{pid:04d} cancelled.')
    return redirect(url_for('inventory.po_form', pid=pid))


@bp.route('/stock/item/<int:mid>')
@login_required
def inventory_item(mid):
    """Odoo-style product detail: status bar, smart-button stats, details and the
    stock-movement history for one supply item."""
    if not can('inventory'):
        abort(403)
    m = Medicine.query.get_or_404(mid)
    st, sc = _stock_status(m)
    on_hand = m.qty or 0
    value = on_hand * (m.cost or 0)
    reorder = m.reorder or 0
    # expiry state
    exp_txt = '—'
    try:
        if m.expiry:
            _d = dt.date.fromisoformat(m.expiry[:10]); _today = dt.date.today()
            if _d < _today:
                exp_txt = f"<span class='pill red'>Expired · {h(m.expiry)}</span>"
            elif (_d - _today).days < 90:
                exp_txt = f"<span class='pill amber'>{h(m.expiry)}</span>"
            else:
                exp_txt = h(m.expiry)
    except Exception:
        exp_txt = h(m.expiry or '—')

    # movement history: purchases (in), adjustments (±), consumption
    moves = []
    for a in StockAdj.query.filter_by(medicine_id=mid).order_by(StockAdj.id.desc()).limit(60).all():
        _consumed = (a.reason or '').lower().startswith('consumed')
        moves.append((a.date or '', 'Consume' if _consumed else 'Adjustment',
                      a.qty_change or 0, a.reason or '—', a.user or '—'))
    for p in Purchase.query.filter_by(medicine_id=mid).order_by(Purchase.id.desc()).limit(30).all():
        if p.received_date or p.status == 'Received':
            moves.append((p.received_date or p.date or '', 'Purchase (received)',
                          p.qty or 0, f"PUR-{p.id:04d} · {p.supplier.name if p.supplier else ''}", '—'))
    moves.sort(key=lambda r: r[0], reverse=True)
    mrows = ''
    for d, kind, qty, note, who in moves[:80]:
        col = 'var(--green)' if (qty or 0) >= 0 else 'var(--red)'
        mrows += (f"<tr><td>{h(d)}</td><td>{h(kind)}</td>"
                  f"<td class='num' style='font-weight:700;color:{col}'>{'+' if (qty or 0) >= 0 else ''}{qty:g}</td>"
                  f"<td>{h(note)}</td><td>{h(who)}</td></tr>")
    if not mrows:
        mrows = "<tr><td colspan='5' style='text-align:center;color:var(--muted);padding:16px'>No stock movements yet.</td></tr>"

    def smart(label, val, sub=''):
        return (f"<div class='sb'><div class='sb-v'>{val}</div><div class='sb-l'>{label}</div>"
                + (f"<div class='sb-s'>{sub}</div>" if sub else '') + "</div>")
    smart_row = ("<div class='sb-row'>"
                 + smart('On Hand', f"{on_hand:g}", st)
                 + smart('Stock Value', money(value))
                 + smart('Reorder Level', f"{reorder:g}")
                 + smart('Unit Cost', money(m.cost or 0))
                 + "</div>")

    btns = (f"<a class='btn primary' href='{url_for('modules.module', mod='consume')}?item={m.id}'>🧴 Consume</a>"
            f"<a class='btn' href='{url_for('modules.module', mod='stockadj')}'>⚖ Adjust</a>"
            f"<a class='btn' href='{url_for('modules.module_new', mod='purchases')}'>+ Purchase</a>"
            f"<a class='btn gh' href='{url_for('modules.module_edit', mod='inventory', oid=m.id)}'>✎ Edit</a>"
            f"<a class='btn gh' href='{url_for('modules.module', mod='inventory')}'>← Back</a>")

    css = """<style>
      .sb-row{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}
      .sb{flex:1;min-width:150px;background:#F7F9FB;border:1px solid var(--line);border-radius:10px;padding:12px 14px;text-align:center}
      .sb-v{font-size:24px;font-weight:800;color:var(--petrol)}
      .sb-l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-top:2px}
      .sb-s{font-size:11px;color:var(--green);margin-top:2px;font-weight:700}
      .iv-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 24px;margin-top:6px}
      .iv-grid .k{color:var(--muted);font-size:12.5px}.iv-grid .v{font-weight:600}
    </style>"""
    body = f"""{css}
    <div class="panel"><div class="pad" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <div style="font-weight:800;font-size:20px;color:var(--petrol)">{h(m.name)}</div>
      <span class="pill {sc}">{st}</span>
      {(f"<span class='pill grey'>{on_hand:g} in stock</span>")}
      <div style="flex:1"></div>{btns}
    </div>
    <div class="pad">{smart_row}
      <div class="iv-grid">
        <div><div class="k">Batch / Lot</div><div class="v">{h(m.batch or '—')}</div></div>
        <div><div class="k">Expiry</div><div class="v">{exp_txt}</div></div>
        <div><div class="k">Reorder Level</div><div class="v">{reorder:g}</div></div>
        <div><div class="k">Unit Cost</div><div class="v">{money(m.cost or 0)}</div></div>
        <div><div class="k">On Hand</div><div class="v">{on_hand:g}</div></div>
        <div><div class="k">Stock Value</div><div class="v">{money(value)}</div></div>
      </div>
    </div></div>
    <div class="panel"><div class="ph"><h2>Stock Movements</h2><span class="so">purchases in · adjustments · consumption</span></div>
      <div class="tw"><table><thead><tr><th>Date</th><th>Type</th><th class="num">Qty</th><th>Reference / Reason</th><th>By</th></tr></thead>
      <tbody>{mrows}</tbody></table></div></div>"""
    return page(f'{m.name}', body, 'inventory',
                crumbs=[('Inventory', url_for('modules.module', mod='inventory')), (m.name, None)])


def inventory_overview():
    """Odoo-style Inventory: stat cards + a stock list with on-hand, value and status."""
    if not can('inventory'):
        return page('Denied', "<div class='panel'><div class='pad'><b>No access.</b></div></div>")
    q = (request.args.get('q') or '').strip()
    f = (request.args.get('f') or 'all')
    items = Medicine.query.order_by(Medicine.name).all()
    if q:
        ql = q.lower()
        items = [m for m in items if ql in (m.name or '').lower() or ql in (m.batch or '').lower()]

    def _expired(m):
        try:
            return m.expiry and dt.date.fromisoformat(m.expiry[:10]) < dt.date.today()
        except Exception:
            return False
    def _expiring(m):
        try:
            return m.expiry and 0 <= (dt.date.fromisoformat(m.expiry[:10]) - dt.date.today()).days < 90
        except Exception:
            return False

    total_items = len(items)
    total_value = sum((m.qty or 0) * (m.cost or 0) for m in items)
    low = [m for m in items if 0 < (m.qty or 0) <= (m.reorder or 0)]
    out = [m for m in items if (m.qty or 0) <= 0]
    expiring = [m for m in items if _expiring(m) or _expired(m)]

    view = items
    if f == 'low':
        view = low
    elif f == 'out':
        view = out
    elif f == 'instock':
        view = [m for m in items if (m.qty or 0) > (m.reorder or 0)]
    elif f == 'expiring':
        view = expiring

    def card(cls, label, val):
        return f"<div class='iv-stat {cls}'><div class='l'>{label}</div><div class='v'>{val}</div></div>"
    stats = ("<div class='iv-stats'>"
             + card('a', 'Products', str(total_items))
             + card('b', 'Stock Value', money(total_value))
             + card('c', 'Low Stock', str(len(low)))
             + card('d', 'Out of Stock', str(len(out)))
             + card('c', 'Expiring / Expired', str(len(expiring)))
             + "</div>")

    def chip(key, label, n=None):
        on = 'on' if f == key else ''
        cnt = f" ({n})" if n is not None else ''
        url = url_for('modules.module', mod='inventory', f=key) + (f'&q={h(q)}' if q else '')
        return f"<a class='iv-chip {on}' href='{url}'>{label}{cnt}</a>"
    chips = ("<div style='margin-bottom:10px'>"
             + chip('all', 'All', total_items) + chip('instock', 'In Stock')
             + chip('low', 'Low', len(low)) + chip('out', 'Out', len(out))
             + chip('expiring', 'Expiring/Expired', len(expiring)) + "</div>")

    rows = ''
    for m in view:
        st, sc = _stock_status(m)
        val = (m.qty or 0) * (m.cost or 0)
        exp = expiry_cell = ('—' if not m.expiry else
               (f"<span class='pill red'>Expired</span>" if _expired(m) else
                (f"<span class='pill amber'>{h(m.expiry)}</span>" if _expiring(m) else h(m.expiry))))
        rows += (
            f"<tr><td><a class='idlink' href='{url_for('inventory.inventory_item', mid=m.id)}'><b>{h(m.name)}</b></a></td>"
            f"<td>{h(m.batch or '—')}</td>"
            f"<td>{expiry_cell}</td>"
            f"<td class='num iv-onhand'>{m.qty or 0}</td>"
            f"<td class='num'>{m.reorder or 0}</td>"
            f"<td class='num'>{money(m.cost or 0)}</td>"
            f"<td class='num'>{money(val)}</td>"
            f"<td><span class='pill {sc}'>{st}</span></td>"
            f"<td class='num' style='white-space:nowrap'>"
            f"<a class='btn gh sm' href='{url_for('modules.module_edit', mod='inventory', oid=m.id)}'>Edit</a> "
            f"<a class='btn gh sm' href='{url_for('modules.module', mod='consume')}'>Use</a> "
            f"<a class='btn gh sm' href='{url_for('modules.module', mod='stockadj')}'>Adjust</a></td></tr>")
    if not rows:
        rows = "<tr><td colspan='9' style='text-align:center;color:var(--muted);padding:20px'>No supply items.</td></tr>"

    controls = (
        "<div class='ph'><h2>Inventory · Stock</h2><div class='sp'></div>"
        f"<form method='get' style='display:inline'><input type='hidden' name='f' value='{h(f)}'>"
        f"<input name='q' value='{h(q)}' placeholder='Search item / batch…' style='padding:6px 10px'></form> "
        f"<a class='btn primary sm' href='{url_for('modules.module_new', mod='inventory')}'>+ New Supply</a> "
        f"<a class='btn sm' href='{url_for('modules.module', mod='consume')}'>🧴 Consume</a> "
        f"<a class='btn sm' href='{url_for('modules.module', mod='stockadj')}'>Stock Adjust</a> "
        f"<a class='btn sm' href='{url_for('modules.module', mod='transfers')}'>Transfers</a></div>")

    table = (f"<div class='panel'>{controls}<div class='pad'>{chips}</div>"
             "<div class='tw'><table><thead><tr>"
             "<th>Product</th><th>Batch</th><th>Expiry</th><th class='num'>On Hand</th>"
             "<th class='num'>Reorder</th><th class='num'>Unit Cost</th><th class='num'>Stock Value</th>"
             "<th>Status</th><th></th></tr></thead>"
             f"<tbody>{rows}</tbody></table></div></div>")

    return page('Inventory', INV_ODOO_CSS + stats + table, 'inventory',
                crumbs=[('Inventory', None)])


# ============================ PURCHASES · Odoo-style overview ============================
def purchases_overview():
    """Odoo-style Procurement overview: stat band + filter chips + PO list.
    Served via the module dispatcher (mod='purchases'); new/edit still use CRUD."""
    from flask import request
    q = (request.args.get('q') or '').strip()
    f = (request.args.get('f') or 'all')
    vendor = request.args.get('vendor', type=int)
    pos = Purchase.query.order_by(Purchase.id.desc()).all()
    if vendor:
        pos = [p for p in pos if p.supplier_id == vendor]
    if q:
        ql = q.lower()
        pos = [p for p in pos if ql in (p.item or '').lower()
               or ql in ((p.supplier.name if p.supplier else '') or '').lower()
               or ql in (p.category or '').lower()
               or ql in f"pur-{p.id:04d}".lower()]

    def _bal(p): return round((p.total or 0) - (p.paid or 0), 2)
    live = [p for p in pos if p.status != 'Cancelled']
    requested = [p for p in pos if p.status == 'Requested']
    ordered = [p for p in pos if p.status == 'Ordered']
    received = [p for p in pos if p.status == 'Received']
    awaiting = [p for p in pos if p.status in ('Requested', 'Ordered')]
    unpaid = [p for p in live if _bal(p) > 0.005]
    _month = today()[:7]
    month_spend = sum(p.total or 0 for p in live if (p.date or '').startswith(_month))
    total_val = sum(p.total or 0 for p in live)
    outstanding = sum(_bal(p) for p in unpaid)

    view = pos
    if f == 'requested': view = requested
    elif f == 'ordered': view = ordered
    elif f == 'received': view = received
    elif f == 'awaiting': view = awaiting
    elif f == 'unpaid': view = unpaid

    def _po_state(p):
        return {'Requested': ('Requested', 'grey'), 'Ordered': ('Ordered', 'amber'),
                'Received': ('Received', 'green'), 'Cancelled': ('Cancelled', 'red')}.get(p.status, (p.status or '—', 'grey'))

    CSS = """<style>
    .pu-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .pu-stat{flex:1;min-width:148px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
    .pu-stat .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
    .pu-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
    .pu-stat.a{border-left:3px solid var(--petrol)} .pu-stat.b{border-left:3px solid var(--green)}
    .pu-stat.c{border-left:3px solid var(--amber)} .pu-stat.d{border-left:3px solid var(--red)}
    .pu-chip{display:inline-block;padding:5px 12px;border:1px solid var(--line);border-radius:20px;font-size:12.5px;font-weight:600;color:var(--muted);margin-right:6px;margin-bottom:6px;text-decoration:none}
    .pu-chip.on{background:var(--petrol);color:#fff;border-color:var(--petrol)}
    </style>"""

    def _c(cls, label, val):
        return f"<div class='pu-stat {cls}'><div class='l'>{label}</div><div class='v'>{val}</div></div>"
    stats = ("<div class='pu-stats'>"
             + _c('a', 'Purchase Orders', str(len(live)))
             + _c('a', 'Total Value', money(total_val))
             + _c('d', 'Outstanding Payable', money(outstanding))
             + _c('c', 'Awaiting Receipt', str(len(awaiting)))
             + _c('b', 'Received', str(len(received)))
             + _c('a', 'This Month', money(month_spend))
             + "</div>")

    def chip(key, label, n=None):
        on = 'on' if f == key else ''
        cnt = f" ({n})" if n is not None else ''
        url = url_for('modules.module', mod='purchases', f=key) + (f'&q={h(q)}' if q else '') + (f'&vendor={vendor}' if vendor else '')
        return f"<a class='pu-chip {on}' href='{url}'>{label}{cnt}</a>"
    chips = ("<div style='margin-bottom:10px'>"
             + chip('all', 'All', len(pos)) + chip('requested', 'Requested', len(requested))
             + chip('ordered', 'Ordered', len(ordered)) + chip('received', 'Received', len(received))
             + chip('awaiting', 'Awaiting Receipt', len(awaiting)) + chip('unpaid', 'Unpaid', len(unpaid))
             + "</div>")

    _sups = Supplier.query.order_by(Supplier.name).all()
    _vopts = "<option value=''>All vendors</option>" + ''.join(
        f"<option value='{s.id}' {'selected' if vendor == s.id else ''}>{h(s.name)}</option>" for s in _sups)
    _vendform = (f"<span style='font-size:12.5px;color:var(--muted);margin-right:4px'>Vendor:</span>"
                 f"<form method='get' style='display:inline'><input type='hidden' name='f' value='{h(f)}'>"
                 f"<select name='vendor' onchange='this.form.submit()' style='padding:6px 10px;border:1px solid var(--line);border-radius:8px;max-width:220px'>{_vopts}</select></form>")
    _canmng = can('purchases')
    toolbar = (f"<div class='panel' style='padding:10px 12px;margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center'>"
               f"<a class='btn primary sm' href='{url_for('modules.module_new', mod='purchases')}'>+ New Purchase Order</a>"
               f"<a class='btn sm' href='{url_for('modules.module', mod='suppliers')}'>🏢 Suppliers</a>"
               f"<a class='btn sm' href='{url_for('modules.module', mod='inventory')}'>📦 Inventory</a>"
               f"<span style='flex:1'></span>{_vendform}</div>")

    search = (f"<form method='get' style='margin-bottom:10px'><input type='hidden' name='f' value='{h(f)}'>"
              + (f"<input type='hidden' name='vendor' value='{vendor}'>" if vendor else "")
              + f"<input name='q' value='{h(q)}' placeholder='🔍  Search PO#, supplier, item, category…' "
              f"style='width:min(430px,100%);padding:7px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px'></form>")

    hdr = ("<tr><th>PO #</th><th>Date</th><th>Supplier</th><th>Item</th><th>Category</th>"
           "<th class='num'>Qty</th><th class='num'>Unit Cost</th><th class='num'>Total</th>"
           "<th class='num'>Paid</th><th class='num'>Balance</th><th>Status</th><th></th></tr>")
    rows = ''
    for p in view:
        st, sc = _po_state(p)
        acts = f"<a class='btn gh sm' href='{url_for('inventory.purchase_view', pid=p.id)}'>Open</a>"
        if _canmng:
            if p.status == 'Requested':
                acts += f" <a class='btn gh sm' href='{url_for('inventory.po_order', pid=p.id)}'>Approve</a>"
            if p.status in ('Requested', 'Ordered'):
                acts += f" <a class='btn primary sm' href='{url_for('inventory.po_receive', pid=p.id)}'>Receive</a>"
            if (p.status == 'Received' or p.received_date) and ((p.total or 0) - (p.paid or 0)) > 0.005:
                acts += f" <a class='btn ok sm' href='{url_for('inventory.purchase_view', pid=p.id)}#pay'>Pay</a>"
        bal = _bal(p)
        rows += (f"<tr><td><a class='idlink' href='{url_for('inventory.purchase_view', pid=p.id)}'>PUR-{p.id:04d}</a></td>"
                 f"<td>{h(p.date or '—')}</td><td>{h(p.supplier.name if p.supplier else '—')}</td>"
                 f"<td><b>{h(p.item or (p.medicine.name if p.medicine else '—'))}</b></td><td>{h(p.category or '—')}</td>"
                 f"<td class='num'>{(p.qty or 0):g}</td><td class='num'>{money(p.unit_cost)}</td>"
                 f"<td class='num'>{money(p.total)}</td><td class='num'>{money(p.paid or 0)}</td>"
                 f"<td class='num'>{('<b>'+money(bal)+'</b>') if bal>0.005 else '<span style=\"color:var(--green)\">Paid</span>'}</td>"
                 f"<td><span class='pill {sc}'>{h(st)}</span></td>"
                 f"<td style='text-align:right;white-space:nowrap'>{acts}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='12'><div class='empty' style='padding:26px;text-align:center;color:var(--muted)'><b>No purchase orders</b><br>Create a purchase order to begin.</div></td></tr>"
    table = f"<div class='panel'><div class='tw'><table><thead>{hdr}</thead><tbody>{rows}</tbody></table></div></div>"

    return page('Purchases', CSS + toolbar + stats + chips + search + table, 'purchases',
                crumbs=[('Procurement', None)])


def consume_for_invoice(inv):
    """Deduct each service's consumables (ServiceConsumable BOM) from stock ONCE when
    the invoice is fully paid. Idempotent via inv.consumed. One StockAdj -out per item.
    Returns count of items deducted."""
    from ..models import ServiceConsumable, Medicine, StockAdj
    if getattr(inv, 'consumed', False):
        return 0
    n = 0
    for it in inv.items:
        if not it.service_id:
            continue
        for sc in ServiceConsumable.query.filter_by(service_id=it.service_id).all():
            m = Medicine.query.get(sc.medicine_id)
            if not m or not (sc.qty or 0):
                continue
            use = (sc.qty or 0) * (it.qty or 1)
            m.qty = (m.qty or 0) - use
            db.session.add(StockAdj(medicine_id=m.id, qty_change=-use, user='system',
                                    reason=f'Consumed: {(it.desc or "service")[:40]} · INV-{inv.id:04d}'))
            n += 1
    inv.consumed = True
    db.session.commit()
    return n


def unconsume_for_invoice(inv):
    """Restore the consumables of an invoice (on reset-to-draft / cancel) — reverses the
    'Consumed: … INV-xxxx' StockAdj rows and adds the qty back to stock. Clears the flag."""
    from ..models import StockAdj, Medicine
    if not getattr(inv, 'consumed', False):
        return 0
    n = 0
    for adj in StockAdj.query.filter(StockAdj.reason.like(f'Consumed:%INV-{inv.id:04d}')).all():
        m = Medicine.query.get(adj.medicine_id)
        if m:
            m.qty = (m.qty or 0) - (adj.qty_change or 0)   # qty_change is negative → adds back
        db.session.delete(adj); n += 1
    inv.consumed = False
    db.session.commit()
    return n
