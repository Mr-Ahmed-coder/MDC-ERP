"""
Reset the MDC ERP to ZERO — a clean slate to start real work.

Clears ALL transactional / operational data (patients, invoices, receipts,
journal entries, lab/radiology orders, referrals, prescriptions, pharmacy sales,
stock movements, assets + depreciation, expenses, purchases, notifications, audit
log, admissions, surgeries, dialysis, ED/IPD, blood bank, claims, ...).

KEEPS your setup so the system is ready to use immediately:
  users, settings/branding, chart of accounts (zeroed), service catalog,
  doctors, radiologists, branches, warehouses, suppliers, insurers,
  asset categories, fiscal periods, lab/imaging config, wards/beds/theatres.

A timestamped BACKUP of the database is made first.

Usage (from the project folder):
    python reset_to_zero.py                # keep catalog + config, clear transactions
    python reset_to_zero.py --wipe-catalog # also clear services / doctors / suppliers
    python reset_to_zero.py --yes          # skip the confirmation prompt
"""
import os
import sys
import shutil
import datetime

os.environ.setdefault('FLASK_CONFIG', 'development')

from mdc_erp import create_app          # noqa: E402
from mdc_erp.extensions import db       # noqa: E402
from sqlalchemy import text             # noqa: E402

# Master / configuration tables that make the app usable — kept by default.
KEEP = {
    'user', 'setting', 'currency', 'account', 'cost_center', 'fiscal_period',
    'service', 'doctor', 'radiologist', 'branch', 'warehouse', 'supplier',
    'asset_category', 'insurer', 'coverage_rule', 'svc_contract',
    'lab_param', 'lab_instrument', 'img_modality',
    'ambulance', 'ambulance_driver', 'dialysis_machine', 'dialysis_lab',
    'theatre', 'ward', 'bed',
}
WIPE_CATALOG = '--wipe-catalog' in sys.argv
if WIPE_CATALOG:
    KEEP -= {'service', 'doctor', 'radiologist', 'supplier'}

ASSUME_YES = ('--yes' in sys.argv) or ('-y' in sys.argv)


def main():
    app = create_app()
    with app.app_context():
        uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        all_tables = [t.name for t in db.metadata.sorted_tables]
        to_clear = [t for t in all_tables if t not in KEEP]

        print('=' * 60)
        print('  RESET MDC ERP TO ZERO')
        print('=' * 60)
        print(f'  Keep (config/catalog): {len(KEEP & set(all_tables))} tables')
        print(f'  Clear (transactions):  {len(to_clear)} tables')
        if WIPE_CATALOG:
            print('  --wipe-catalog: services / doctors / suppliers WILL be cleared')
        print('=' * 60)

        if not ASSUME_YES:
            ans = input('Type  YES  to reset (a backup is made first): ').strip()
            if ans != 'YES':
                print('Aborted. Nothing changed.')
                return

        # 1) backup the sqlite database file
        if uri.startswith('sqlite:///'):
            path = uri[len('sqlite:///'):]
            if os.path.exists(path):
                stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
                bak = f'{path}.bak-{stamp}'
                shutil.copy2(path, bak)
                print(f'✔ Backup saved: {bak}')
        else:
            print('! Non-SQLite database — make sure you have your own backup.')

        # 2) delete every non-kept (transactional) table
        try:
            db.session.execute(text('PRAGMA foreign_keys=OFF'))
        except Exception:
            pass
        rows = 0
        for name in reversed(all_tables):     # children before parents
            if name in KEEP:
                continue
            try:
                r = db.session.execute(text(f'DELETE FROM "{name}"'))
                rows += (r.rowcount or 0)
            except Exception as e:
                print(f'  skip {name}: {e}')

        # 3) zero balances / stock on the kept tables
        for stmt in (
            'UPDATE account SET opening=0',
            "UPDATE bed SET status='Available'",
        ):
            try:
                db.session.execute(text(stmt))
            except Exception:
                pass

        db.session.commit()
        print(f'✔ Cleared {len(to_clear)} tables ({rows} rows).')
        print('✔ System reset to ZERO — ready to start working.')
        print('  Log in and begin: everything now reads 0 / empty.')


if __name__ == '__main__':
    main()
