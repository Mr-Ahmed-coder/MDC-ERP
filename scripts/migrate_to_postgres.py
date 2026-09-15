#!/usr/bin/env python3
"""Copy all data from the SQLite database into a PostgreSQL database.

Use this once when moving an existing single-site installation onto PostgreSQL
for multi-user concurrency. It does NOT change business logic — it only moves
rows. The schema on the target is created from the application's own models, so
it always matches the running code.

USAGE
-----
    # 1. Point DATABASE_URL at the (empty) target PostgreSQL database
    export DATABASE_URL=postgresql://user:pass@host:5432/mdc_erp

    # 2. Run, giving the path to the source SQLite file
    python scripts/migrate_to_postgres.py --sqlite data/erp.db

SAFETY
------
- The target should be an EMPTY database (fresh). The script aborts if it already
  contains invoices, so you cannot accidentally overwrite a live system.
- The source SQLite file is only read, never modified.
- Always take a backup of both databases first.
- Run against a staging target and verify before switching production over.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def main():
    ap = argparse.ArgumentParser(description="Migrate MDC ERP data SQLite -> PostgreSQL")
    ap.add_argument('--sqlite', default='data/erp.db', help='path to the source SQLite file')
    ap.add_argument('--yes', action='store_true', help='skip the confirmation prompt')
    args = ap.parse_args()

    target_url = (os.environ.get('DATABASE_URL') or '').replace('postgres://', 'postgresql://')
    if not target_url.startswith('postgresql://'):
        sys.exit('ERROR: set DATABASE_URL to your PostgreSQL target, e.g.\n'
                 '  export DATABASE_URL=postgresql://user:pass@host:5432/mdc_erp')

    src_path = os.path.abspath(args.sqlite)
    if not os.path.exists(src_path):
        sys.exit(f'ERROR: source SQLite file not found: {src_path}')

    from sqlalchemy import create_engine, inspect, text

    # --- build the target schema from the application's models (guarantees match) ---
    os.environ['DATABASE_URL'] = target_url
    from mdc_erp import create_app
    from mdc_erp.bootstrap import init_db
    from mdc_erp.extensions import db

    app = create_app()
    with app.app_context():
        # guard: refuse to run against a non-empty target
        try:
            existing = db.session.execute(text('SELECT COUNT(*) FROM invoice')).scalar()
            if existing and existing > 0:
                sys.exit('ERROR: target PostgreSQL already has data (invoices found). '
                         'Use a fresh, empty database.')
        except Exception:
            pass  # tables not created yet — expected on a brand-new database

        init_db(app, demo=False)   # create_all + migrations on the target
        target_engine = db.engine
        table_order = db.metadata.sorted_tables   # respects foreign-key dependencies

    src_engine = create_engine('sqlite:///' + src_path)
    src_insp = inspect(src_engine)
    src_tables = set(src_insp.get_table_names())

    if not args.yes:
        print(f'Source : {src_path}')
        print(f'Target : {target_url}')
        print(f'Tables : {len(table_order)} (schema from models)')
        if input('Proceed with copy? [y/N] ').strip().lower() not in ('y', 'yes'):
            sys.exit('Aborted.')

    copied_rows = 0
    copied_tables = 0
    with src_engine.connect() as src, target_engine.begin() as dst:
        for table in table_order:
            name = table.name
            if name not in src_tables:
                continue
            # only copy columns that exist in BOTH schemas
            src_cols = {c['name'] for c in src_insp.get_columns(name)}
            cols = [c.name for c in table.columns if c.name in src_cols]
            if not cols:
                continue
            rows = src.execute(text(f'SELECT {", ".join(cols)} FROM "{name}"')).fetchall()
            if not rows:
                continue
            dst.execute(table.insert(), [dict(zip(cols, r)) for r in rows])
            copied_rows += len(rows)
            copied_tables += 1
            print(f'  {name:<24} {len(rows):>7} rows')

    # --- reset PostgreSQL sequences so new inserts don't collide with copied ids ---
    with target_engine.begin() as dst:
        for table in table_order:
            if 'id' in [c.name for c in table.columns]:
                dst.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1))"))

    print(f'\nDone. Copied {copied_rows} rows across {copied_tables} tables.')
    print('Verify the application against the PostgreSQL target before switching production.')


if __name__ == '__main__':
    main()
