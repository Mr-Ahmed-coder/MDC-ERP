"""Read-only financial integrity checks for operational reconciliation.

The checks intentionally do not mutate financial records. They produce compact
records that can be reviewed, exported, or used by a scheduled monitoring job.
"""
from collections import defaultdict
from ..extensions import db
from ..models import Invoice, InvoiceItem


def find_financial_mismatches(limit=500):
    """Return invoice/payment and source-link anomalies."""
    findings = []
    for inv in Invoice.query.order_by(Invoice.id).limit(limit).all():
        receipts_total = sum((r.amount or 0) for r in getattr(inv, 'receipts', []))
        paid = inv.paid or 0
        if abs(float(receipts_total) - float(paid)) > 0.005:
            findings.append({
                'kind': 'invoice_receipt_mismatch',
                'invoice_id': inv.id,
                'invoice_paid': paid,
                'receipt_total': receipts_total,
                'difference': paid - receipts_total,
            })
        if paid < 0 or paid > inv.total + (inv.credits or 0) + 0.005:
            findings.append({
                'kind': 'invoice_balance_invalid',
                'invoice_id': inv.id,
                'paid': paid,
                'total': inv.total,
                'credits': inv.credits,
            })

    for source_attr, label in (('lab_order_id', 'lab'),
                               ('rad_order_id', 'rad'),
                               ('consult_id', 'consult')):
        rows = (db.session.query(getattr(InvoiceItem, source_attr), db.func.count(InvoiceItem.id))
                .filter(getattr(InvoiceItem, source_attr).isnot(None))
                .group_by(getattr(InvoiceItem, source_attr))
                .having(db.func.count(InvoiceItem.id) > 1).all())
        for source_id, count in rows:
            findings.append({'kind': 'duplicate_billable_source',
                             'source_type': label, 'source_id': source_id, 'count': count})

    return findings


def summary():
    findings = find_financial_mismatches()
    by_kind = defaultdict(int)
    for row in findings:
        by_kind[row['kind']] += 1
    return {'ok': not findings, 'count': len(findings), 'by_kind': dict(by_kind),
            'findings': findings}
