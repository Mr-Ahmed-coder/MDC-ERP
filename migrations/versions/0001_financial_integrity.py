"""Financial integrity baseline for MDC ERP v8.2.

Revision ID: 0001_financial_integrity
Revises: 0000_initial_schema
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_financial_integrity"
down_revision = "0000_initial_schema"
branch_labels = None
depends_on = None


def _duplicates(table, column):
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        f"SELECT {column}, COUNT(*) AS n FROM {table} "
        f"WHERE {column} IS NOT NULL GROUP BY {column} HAVING COUNT(*) > 1"
    )).fetchall()
    return rows


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    receipt_cols = {c["name"] for c in inspector.get_columns("pay_receipt")}
    if "idempotency_key" not in receipt_cols:
        op.add_column("pay_receipt", sa.Column("idempotency_key", sa.String(length=128), nullable=True))

    # Existing duplicate links must be reconciled by an operator rather than
    # silently hidden by a new constraint.
    for table, column in (("invoice_item", "lab_order_id"),
                          ("invoice_item", "rad_order_id"),
                          ("invoice_item", "consult_id"),
                          ("pay_receipt", "idempotency_key")):
        if table in inspector.get_table_names() and column in {c["name"] for c in inspector.get_columns(table)}:
            dup = _duplicates(table, column)
            if dup:
                raise RuntimeError(f"Cannot apply financial-integrity migration: duplicate {table}.{column} values exist: {dup[:10]}")

    existing = {idx['name'] for table in ('pay_receipt', 'invoice_item')
                for idx in sa.inspect(bind).get_indexes(table)}
    indexes = (
        ('ix_pay_receipt_idempotency_key', 'pay_receipt', ['idempotency_key'], None),
        ('ix_invoice_item_lab_order_id', 'invoice_item', ['lab_order_id'], sa.text('lab_order_id IS NOT NULL')),
        ('ix_invoice_item_rad_order_id', 'invoice_item', ['rad_order_id'], sa.text('rad_order_id IS NOT NULL')),
        ('ix_invoice_item_consult_id', 'invoice_item', ['consult_id'], sa.text('consult_id IS NOT NULL')),
    )
    for name, table, columns, predicate in indexes:
        if name not in existing:
            kwargs = {'unique': True}
            if predicate is not None and bind.dialect.name == 'postgresql':
                kwargs['postgresql_where'] = predicate
            op.create_index(name, table, columns, **kwargs)


def downgrade():
    op.drop_index("ix_invoice_item_consult_id", table_name="invoice_item")
    op.drop_index("ix_invoice_item_rad_order_id", table_name="invoice_item")
    op.drop_index("ix_invoice_item_lab_order_id", table_name="invoice_item")
    op.drop_index("ix_pay_receipt_idempotency_key", table_name="pay_receipt")
    inspector = sa.inspect(op.get_bind())
    if "idempotency_key" in {c["name"] for c in inspector.get_columns("pay_receipt")}:
        op.drop_column("pay_receipt", "idempotency_key")
