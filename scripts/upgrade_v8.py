"""Idempotent schema upgrade for MDC ERP v8.0 (PACS + RIS + Insurance + LIS).

Safe to run repeatedly. On an existing, populated database it:
  * creates all new tables (PACS: img_study/img_series/img_instance/img_modality;
    Insurance: insurer/insurance_card/coverage_rule/pre_auth/claim;
    LIS: lab_instrument/lab_result_value)
  * adds new nullable columns to existing tables (rad_order RIS columns,
    lab_order.panic_ack)

Works for both SQLite (dev/Windows) and PostgreSQL (production). No data is
modified or backfilled — every added column is nullable.

Usage:
    python scripts/upgrade_v8.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect, text
from mdc_erp import create_app
from mdc_erp.extensions import db

# table -> {column: SQL type} for columns added to EXISTING tables
NEW_COLUMNS = {
    'rad_order': {
        'priority': 'VARCHAR(10)',
        'modality_id': 'INTEGER',
        'scheduled_for': 'VARCHAR(20)',
        'technician': 'VARCHAR(60)',
        'requested_at': 'VARCHAR(20)',
        'scheduled_at': 'VARCHAR(20)',
        'acquired_at': 'VARCHAR(20)',
        'reported_at': 'VARCHAR(20)',
        'approved_at': 'VARCHAR(20)',
        'approved_by': 'VARCHAR(60)',
        'signature': 'VARCHAR(40)',
    },
    'lab_order': {
        'panic_ack': 'BOOLEAN',
    },
    'queue_ticket': {
        'priority': "VARCHAR(10)",
        'room': 'VARCHAR(30)',
        'called_at': 'VARCHAR(20)',
        'done_at': 'VARCHAR(20)',
        'created_by': 'VARCHAR(60)',
        'branch_id': 'INTEGER',
    },
}


def upgrade(app=None):
    app = app or create_app()
    added = []
    with app.app_context():
        # 1) new tables
        db.create_all()

        # 2) new columns on existing tables
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())
        for table, cols in NEW_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c['name'] for c in insp.get_columns(table)}
            for col, sqltype in cols.items():
                if col not in existing:
                    db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {sqltype}'))
                    added.append(f'{table}.{col}')
        db.session.commit()
    return added


if __name__ == '__main__':
    added = upgrade()
    if added:
        print('Added columns:', ', '.join(added))
    else:
        print('Schema already up to date — no columns to add.')
    print('New tables ensured. Upgrade complete.')
