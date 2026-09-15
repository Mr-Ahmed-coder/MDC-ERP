"""
Restore the MDC ERP database from an automatic .db snapshot.

Lists the raw database snapshots in instance/backups/, lets you pick one,
backs up the CURRENT database first, then copies the snapshot over erp.db.

Stop the server before restoring. Usage:
    python restore_backup.py
"""
import os
import sys
import shutil
import datetime

os.environ.setdefault('FLASK_CONFIG', 'development')

from mdc_erp import create_app          # noqa: E402


def main():
    app = create_app()
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('sqlite:///'):
        print('This helper only supports SQLite databases.')
        return
    db_path = uri[len('sqlite:///'):]
    bdir = app.config.get('BACKUP_DIR') or os.path.join(app.instance_path, 'backups')

    snaps = sorted((f for f in os.listdir(bdir)
                    if f.startswith('db-snapshot-') and f.endswith('.db')), reverse=True) \
        if os.path.isdir(bdir) else []
    if not snaps:
        print('No .db snapshots found in', bdir)
        print('(Automatic snapshots appear after the app has run for a bit, or run BACKUP-NOW.bat.)')
        return

    print('=' * 60)
    print('  RESTORE MDC ERP DATABASE')
    print('=' * 60)
    for i, f in enumerate(snaps[:20], 1):
        p = os.path.join(bdir, f)
        sz = os.path.getsize(p) // 1024
        when = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')
        print(f'  {i:2}. {f}   ({sz} KB, {when})')
    print('=' * 60)

    try:
        choice = input('Enter the number to restore (or blank to cancel): ').strip()
    except EOFError:
        choice = ''
    if not choice:
        print('Cancelled. Nothing changed.')
        return
    try:
        pick = snaps[int(choice) - 1]
    except (ValueError, IndexError):
        print('Invalid choice. Nothing changed.')
        return

    confirm = input(f'Restore "{pick}" over the current database? Type YES: ').strip()
    if confirm != 'YES':
        print('Cancelled. Nothing changed.')
        return

    # back up the current database first
    if os.path.exists(db_path):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        pre = f'{db_path}.pre-restore-{stamp}'
        shutil.copy2(db_path, pre)
        print('✔ Current database saved to:', pre)

    shutil.copy2(os.path.join(bdir, pick), db_path)
    print(f'✔ Restored {pick}.')
    print('  Start the system again with START-MDC-ERP.bat.')


if __name__ == '__main__':
    main()
