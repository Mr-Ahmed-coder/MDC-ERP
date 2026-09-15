"""Pharmacy: direct sales and prescription dispensing (stock + accounting)."""
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.security import (cur_user, can, login_required, log)
from ..core.helpers import money, today
from ..core.ui import page
from ..core.crud import (render_form, opt_patients)
from ..core.posting import (repost_invoice)

bp = Blueprint('pharmacy', __name__)

def pharmacy_list():
    from .modules import search_view, hl
    from ..models import Patient, Medicine
    _base = PharmacySale.query.order_by(PharmacySale.id.desc())

    def _ph_extra(q):
        conds = [PharmacySale.patient.has(Patient.name.ilike(f'%{q}%')),
                 PharmacySale.patient.has(Patient.mrn.ilike(f'%{q}%')),
                 PharmacySale.medicine.has(Medicine.name.ilike(f'%{q}%'))]
        digits = ''.join(ch for ch in q if ch.isdigit())
        if digits:
            try:
                conds.append(PharmacySale.id == int(digits))
            except ValueError:
                pass
        return conds

    _base, _sq, _fbar = search_view('pharmacy', PharmacySale, _base,
                                    search_cols=['date'], date_field='date',
                                    extra_or=_ph_extra,
                                    placeholder='Search patient, MRN, medicine…')
    sales = _base.limit(200).all()
    body=''
    for s in sales:
        body+=f"<tr><td>{h(s.date)}</td><td>{hl(h(s.medicine.name if s.medicine else '—'),_sq)}</td><td>{hl(h(s.patient.name if s.patient else 'Walk-in'),_sq)}</td><td class='num'>{s.qty}</td><td class='num'>{money(s.total)}</td></tr>"
    if not sales: body="<tr><td colspan='5'><div class='empty'><b>No sales found</b>Dispense a medicine or adjust the search.</div></td></tr>"
    total=sum(s.total for s in sales)
    return page('Pharmacy', f"""<div class="panel"><div class="ph"><h2>Pharmacy Dispensing</h2><div class="sp"></div>
      <a class="btn" href="{url_for('modules.module',mod='inventory')}">Manage Stock</a><a class="btn primary" href="{url_for('pharmacy.pharm_sell')}">+ Dispense / Sell</a></div>
      {_fbar}
      <div class="tw"><table><thead><tr><th>Date</th><th>Medicine</th><th>Patient</th><th class="num">Qty</th><th class="num">Total</th></tr></thead><tbody>{body}</tbody>
      <tfoot><tr style="font-weight:700;background:rgba(0,0,0,.02)"><td colspan="4" style="padding:12px 14px">Total (shown)</td><td class="num">{money(total)}</td></tr></tfoot></table></div></div>""",'pharmacy')

@bp.route('/pharmacy/sell', methods=['GET','POST'])
@login_required
def pharm_sell():
    if not can('pharmacy'): abort(403)
    if request.method=='POST':
        med=Medicine.query.get(int(request.form['medicine_id'])); qty=int(request.form.get('qty') or 1)
        if not med: flash('Select a medicine'); return redirect(url_for('pharmacy.pharm_sell'))
        if med.qty < qty: flash(f'Not enough stock ({med.qty} left)'); return redirect(url_for('pharmacy.pharm_sell'))
        from ..core.stock import deduct_stock
        deduct_stock(med, qty)
        s=PharmacySale(medicine_id=med.id, patient_id=request.form.get('patient_id') or None, qty=qty, total=qty*(med.price or 0))
        db.session.add(s); db.session.commit(); log(f'Dispensed {qty} × {med.name}'); flash('Dispensed'); return redirect(url_for('modules.module',mod='pharmacy'))
    meds=[(m.id,f"{m.name} — {money(m.price)} ({m.qty} in stock)") for m in Medicine.query.filter(Medicine.qty>0).order_by(Medicine.name).all()]
    if not meds: return page('Dispense',"<div class='panel'><div class='pad'><b>No medicines in stock.</b> Add stock in Medicines.</div></div>",'pharmacy')
    fields=[dict(name='medicine_id',label='Medicine',type='select',options=meds,required=True),
            dict(name='qty',label='Quantity',type='number',default=1,required=True),
            dict(name='patient_id',label='Patient (optional)',type='select',options=opt_patients())]
    return page('Dispense', render_form('Dispense / Sell Medicine',url_for('pharmacy.pharm_sell'),fields,back=url_for('modules.module',mod='pharmacy')),'pharmacy')

def pharmacy_view():
    from .modules import search_view, hl
    from ..models import Patient, Medicine
    from sqlalchemy import or_ as _or

    def _rx_extra(q):
        return [Prescription.patient.has(Patient.name.ilike(f'%{q}%')),
                Prescription.patient.has(Patient.mrn.ilike(f'%{q}%')),
                Prescription.medicine.has(Medicine.name.ilike(f'%{q}%')),
                Prescription.doctor.ilike(f'%{q}%')]

    _pend = Prescription.query.filter_by(status='Pending').order_by(Prescription.id.desc())
    _pend, _sq, _fbar = search_view('pharmacy', Prescription, _pend,
                                    search_cols=['status'], date_field='date',
                                    extra_or=_rx_extra,
                                    placeholder='Search patient, MRN, medicine, doctor…')
    pend = _pend.all()
    _done = Prescription.query.filter_by(status='Dispensed')
    if _sq:
        _done = _done.filter(_or(*_rx_extra(_sq)))
    done = _done.order_by(Prescription.id.desc()).limit(15).all()

    def prow(r, pending=True):
        m = r.medicine
        stock = (m.qty or 0) if m else 0
        okstock = m and stock >= (r.qty or 0)
        act = (f"<a class='btn primary sm' href='{url_for('pharmacy.rx_dispense', rid=r.id)}'>Dispense</a>" if okstock
               else "<span class='pill red'>No stock</span>") if pending else \
              (f"<a class='btn gh sm' href='/invoice/{r.invoice_id}'>Invoice</a>" if r.invoice_id else '—')
        return (f"<tr><td>{h(r.date)}</td><td><b>{hl(h(r.patient.name if r.patient else '—'),_sq)}</b><br><small>{hl(h(r.patient.mrn if r.patient else ''),_sq)}</small></td>"
                f"<td>{hl(h(m.name if m else '—'),_sq)}<br><small>{h(r.dosage or '')}</small></td>"
                f"<td class='num'>{r.qty:g}</td><td class='num'>{money((m.price or 0)*(r.qty or 0)) if m else '—'}</td>"
                f"<td>{hl(h(r.doctor or '—'),_sq)}</td><td class='num'>{act}</td></tr>")
    pbody = ''.join(prow(r) for r in pend) or "<tr><td colspan='7'><div class='empty'><b>No pending prescriptions</b>Dhakhtarku wuxuu ka qoraa Prescriptions.</div></td></tr>"
    dbody = ''.join(prow(r, False) for r in done) or "<tr><td colspan='7' style='color:var(--muted);padding:14px'>Nothing dispensed yet.</td></tr>"
    head = "<tr><th>Date</th><th>Patient</th><th>Medicine</th><th class='num'>Qty</th><th class='num'>Amount</th><th>Doctor</th><th></th></tr>"

    # ---- Odoo-style stat band -------------------------------------------------
    _today = today(); _month = _today[:7]
    pend_all = Prescription.query.filter_by(status='Pending').count()
    disp_today = Prescription.query.filter_by(status='Dispensed').filter(Prescription.date == _today).count()
    disp_month = Prescription.query.filter_by(status='Dispensed').filter(Prescription.date.like(_month + '%')).count()
    _meds = Medicine.query.all()
    out_stock = sum(1 for m in _meds if (m.qty or 0) <= 0)
    low_stock = sum(1 for m in _meds if 0 < (m.qty or 0) <= (m.reorder or 0))
    sales_today = (sum(s.total or 0 for s in PharmacySale.query.filter_by(date=_today).all())
                   + sum((r.medicine.price or 0) * (r.qty or 0)
                         for r in Prescription.query.filter_by(status='Dispensed').filter(Prescription.date == _today).all()
                         if r.medicine))
    CSS = """<style>
    .ph-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .ph-stat{flex:1;min-width:148px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
    .ph-stat .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
    .ph-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
    .ph-stat.a{border-left:3px solid var(--petrol)} .ph-stat.b{border-left:3px solid var(--green)}
    .ph-stat.c{border-left:3px solid var(--amber)} .ph-stat.d{border-left:3px solid var(--red)}
    </style>"""

    def _c(cls, label, val):
        return f"<div class='ph-stat {cls}'><div class='l'>{label}</div><div class='v'>{val}</div></div>"
    stats = ("<div class='ph-stats'>"
             + _c('c', 'Pending Rx', str(pend_all))
             + _c('b', "Dispensed Today", str(disp_today))
             + _c('b', "Today's Sales", money(sales_today))
             + _c('a', 'Dispensed This Month', str(disp_month))
             + _c('c', 'Low Stock', str(low_stock))
             + _c('d', 'Out of Stock', str(out_stock))
             + "</div>")
    toolbar = (f"<div class='panel' style='padding:10px 12px;margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap'>"
               f"<a class='btn primary sm' href='{url_for('modules.module_new', mod='prescriptions')}'>+ New Prescription</a>"
               f"<a class='btn sm' href='{url_for('pharmacy.pharm_sell')}'>💊 Dispense / Sell</a>"
               f"<a class='btn sm' href='{url_for('modules.module', mod='inventory')}'>📦 Manage Stock</a></div>")

    body = (CSS + toolbar + stats
            + f"<div class='panel'><div class='ph'><h2>Pending Prescriptions</h2><span class='so'>{len(pend)} waiting</span></div>"
            f"{_fbar}"
            f"<div class='tw'><table><thead>{head}</thead><tbody>{pbody}</tbody></table></div>"
            f"<div class='pad' style='color:var(--muted);font-size:12.5px'>Dispense = si toos ah: stock-ka ayaa laga jaraa + invoice ayaa la abuuraa + Accounting ayaa la geliyaa.</div></div>"
            f"<div class='panel'><div class='ph'><h2>Recently Dispensed</h2></div>"
            f"<div class='tw'><table><thead>{head}</thead><tbody>{dbody}</tbody></table></div></div>")
    return page('Pharmacy', body, 'pharmacy')

@bp.route('/rx/<int:rid>/dispense')
@login_required
def rx_dispense(rid):
    if not can('pharmacy'): abort(403)
    r = Prescription.query.get_or_404(rid)
    if r.status == 'Dispensed':
        flash('Already dispensed'); return redirect(url_for('modules.module', mod='pharmacy'))
    m = r.medicine
    if not m:
        flash('Medicine not found'); return redirect(url_for('modules.module', mod='pharmacy'))
    if (m.qty or 0) < (r.qty or 0):
        flash(f'Insufficient stock for {m.name} — in stock: {m.qty or 0}'); return redirect(url_for('modules.module', mod='pharmacy'))
    if (m.price or 0) <= 0:
        flash(f'"{m.name}" has no selling price — set it in Supplies first.'); return redirect(url_for('modules.module', mod='pharmacy'))
    from ..core.stock import deduct_stock
    deduct_stock(m, r.qty or 0)
    m.qty = int(m.qty or 0)
    inv = Invoice(patient_id=r.patient_id, date=today(), branch_id=(cur_user().branch_id if cur_user() else None))
    db.session.add(inv); db.session.flush()
    db.session.add(InvoiceItem(invoice_id=inv.id, desc=f"Pharmacy · {m.name}", qty=r.qty or 1, price=m.price or 0))
    r.status = 'Dispensed'; r.invoice_id = inv.id
    db.session.commit()
    try: repost_invoice(inv)
    except Exception: db.session.rollback()
    log(f"Dispensed {m.name} x{r.qty:g} -> INV-{inv.id:04d} (stock now {m.qty})")
    flash(f'Dispensed ✓ — invoice INV-{inv.id:04d} created, stock updated')
    return redirect(url_for('billing.invoice_view', iid=inv.id))

