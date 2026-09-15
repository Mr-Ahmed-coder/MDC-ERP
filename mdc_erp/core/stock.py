"""Warehouse-aware stock helpers.

Medicine.qty stays the grand total (all existing screens/logic keep working).
StockLevel rows split that total across warehouses. All mutations go through
these helpers so the invariant total == sum(levels) always holds.
"""
from ..extensions import db
from ..models import Warehouse, StockLevel


def default_warehouse():
    """First active warehouse = Main Store (created at bootstrap)."""
    return Warehouse.query.filter_by(active=True).order_by(Warehouse.id).first()


def level(medicine, warehouse):
    """StockLevel row for (item, warehouse), created lazily at qty 0."""
    lv = StockLevel.query.filter_by(medicine_id=medicine.id,
                                    warehouse_id=warehouse.id).first()
    if not lv:
        lv = StockLevel(medicine_id=medicine.id, warehouse_id=warehouse.id, qty=0)
        db.session.add(lv)
        db.session.flush()
    return lv


def ensure_levels(medicine):
    """Backfill: if an item has no levels yet, place its full qty in Main."""
    if not StockLevel.query.filter_by(medicine_id=medicine.id).first():
        wh = default_warehouse()
        if wh:
            db.session.add(StockLevel(medicine_id=medicine.id,
                                      warehouse_id=wh.id, qty=medicine.qty or 0))
            db.session.flush()


def adjust_stock(medicine, change, warehouse=None):
    """Apply +/- change to one warehouse level AND the grand total."""
    wh = warehouse or default_warehouse()
    if wh:
        ensure_levels(medicine)
        lv = level(medicine, wh)
        lv.qty = (lv.qty or 0) + change
    medicine.qty = (medicine.qty or 0) + change
    if change < 0:
        _auto_reorder(medicine)


def deduct_stock(medicine, qty, warehouse=None):
    adjust_stock(medicine, -abs(qty), warehouse)


def _auto_reorder(m):
    """Below reorder level -> auto-create a Requested purchase (once) + notify."""
    try:
        if (m.qty or 0) > (m.reorder or 0):
            return
        from ..models import Purchase
        open_po = Purchase.query.filter(Purchase.medicine_id == m.id,
                                        Purchase.status.in_(('Requested', 'Ordered'))).first()
        if open_po:
            return
        import datetime as _dt
        need = max((m.reorder or 10) * 2 - (m.qty or 0), 1)
        po = Purchase(date=_dt.date.today().isoformat(), item=m.name, category='Auto-reorder',
                      medicine_id=m.id, qty=need, unit_cost=m.cost or 0,
                      total=need * (m.cost or 0), paid=0, status='Requested')
        db.session.add(po); db.session.commit()
        from ..core.notify import notify_event
        notify_event('low_inventory',
                     f'Low inventory: {m.name} (stock {m.qty or 0:g} ≤ reorder {m.reorder or 0}) — PO requested for {need:g} pcs',
                     link='/m/purchases')
    except Exception:
        db.session.rollback()
        from ..core.helpers import log_error; log_error(f'auto-reorder {getattr(m, "name", "?")}')


def transfer_stock(medicine, from_wh, to_wh, qty):
    """Move qty between warehouses. Returns error string or None."""
    if from_wh.id == to_wh.id:
        return 'Source and destination warehouse are the same'
    ensure_levels(medicine)
    src = level(medicine, from_wh)
    if qty <= 0:
        return 'Quantity must be positive'
    if (src.qty or 0) < qty:
        return f'Only {src.qty or 0:g} in {from_wh.name}'
    src.qty -= qty
    level(medicine, to_wh).qty = (level(medicine, to_wh).qty or 0) + qty
    return None
