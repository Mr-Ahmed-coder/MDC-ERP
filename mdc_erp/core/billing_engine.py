"""Universal billable-service discovery and atomic invoice claiming.

The engine exposes a single source of truth for clinical charges. Source rows
are claimed with an atomic ``UPDATE ... WHERE invoice_id IS NULL`` before an
InvoiceItem is created. This makes duplicate prevention a database operation,
not merely a browser or stale-session check. The enclosing transaction must be
committed or rolled back by the caller as one unit.
"""
from ..models import LabOrder, RadOrder, Consultation, Service, db


def _priced(service, price_list):
    from .posting import service_price
    if not service:
        return 0
    pr = service_price(service, price_list)
    return pr if pr and pr > 0 else (service.price or 0)


def get_billable_services(patient_id, price_list='Cash'):
    """Return eligible, not-yet-invoiced billable items for a patient."""
    if not patient_id:
        return []
    out = []

    for o in LabOrder.query.filter_by(patient_id=patient_id).all():
        if (o.invoice_id or 0) or (o.status or '') == 'Cancelled' or not o.service_id:
            continue
        s = Service.query.get(o.service_id)
        if not s or not s.active:
            continue
        out.append(dict(source_type='lab', source_id=o.id, service_id=s.id, name=s.name,
                        department=s.department or 'Laboratory', price=_priced(s, price_list), qty=1,
                        label=f'Laboratory Order #LAB-{o.id:05d}'))

    for o in RadOrder.query.filter_by(patient_id=patient_id).all():
        if (o.invoice_id or 0) or (o.status or '') == 'Cancelled' or not o.service_id:
            continue
        s = Service.query.get(o.service_id)
        if not s or not s.active:
            continue
        dep = s.department or o.modality or 'Radiology'
        out.append(dict(source_type='rad', source_id=o.id, service_id=s.id, name=s.name,
                        department=dep, price=_priced(s, price_list), qty=1,
                        label=f'Radiology Order #RAD-{o.id:05d}'))

    for c in Consultation.query.filter_by(patient_id=patient_id).all():
        if (c.invoice_id or 0) or not c.service_id:
            continue
        s = Service.query.get(c.service_id)
        if not s or not s.active:
            continue
        out.append(dict(source_type='consultation', source_id=c.id, service_id=s.id, name=s.name,
                        department=s.department or 'Consultation', price=_priced(s, price_list), qty=1,
                        label=f'Doctor Consultation #CON-{c.id:05d}'))

    return out


def _claim_source(source_type, source_id, invoice_id):
    """Atomically claim a billable source for an invoice.

    The affected-row count is the concurrency gate. On PostgreSQL this is a
    row-level atomic update; on SQLite the writer lock serializes the update.
    A zero count means another transaction already claimed the source, so the
    caller must not create an InvoiceItem for it.
    """
    models = {'lab': LabOrder, 'rad': RadOrder, 'consultation': Consultation}
    model = models.get(source_type)
    if model is None:
        return False
    changed = (db.session.query(model)
               .filter(model.id == source_id, model.invoice_id.is_(None))
               .update({model.invoice_id: invoice_id}, synchronize_session=False))
    return changed == 1


def apply_billable_services(inv):
    """Attach currently eligible items to ``inv`` without duplicate claims.

    The caller's transaction owns both source claims and invoice-line inserts.
    If any later operation fails, the caller should roll back the transaction so
    source rows become billable again.
    """
    from ..models import InvoiceItem
    if not inv.patient_id or inv.status == 'Cancelled':
        return 0
    if not inv.id:
        db.session.flush()

    items = get_billable_services(inv.patient_id, inv.price_list or 'Cash')
    n = 0
    for it in items:
        if not _claim_source(it['source_type'], it['source_id'], inv.id):
            continue
        line = InvoiceItem(invoice_id=inv.id, service_id=it['service_id'], desc=it['name'],
                           qty=it['qty'], price=it['price'])
        if it['source_type'] == 'lab':
            line.lab_order_id = it['source_id']
        elif it['source_type'] == 'rad':
            line.rad_order_id = it['source_id']
        else:
            line.consult_id = it['source_id']
        db.session.add(line)
        n += 1

    # Flush to surface integrity errors while the caller still owns the
    # transaction. Do not commit here; invoice creation and posting must be
    # committed atomically by the surrounding workflow.
    if n:
        db.session.flush()
    return n
