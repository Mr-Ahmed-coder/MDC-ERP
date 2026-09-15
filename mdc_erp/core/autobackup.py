"""Automatic, scheduled database backups.

Writes a timestamped JSON snapshot to a backups/ folder:
  * once shortly after startup (so a fresh deploy always has a baseline), and
  * every BACKUP_INTERVAL_HOURS thereafter (default 24h),
keeping only the most recent BACKUP_KEEP files (default 14).

This is best-effort and never blocks the app: failures are logged and swallowed.
The manual "Download Backup" feature is unchanged; this adds the *scheduled*
on-disk backups the audit review flagged as missing.
"""
import os
import json
import time
import threading
import datetime as dt

_started = False
_lock = threading.Lock()


def _backup_dir(app):
    d = app.config.get('BACKUP_DIR') or os.path.join(app.instance_path, 'backups')
    os.makedirs(d, exist_ok=True)
    return d


def write_backup(app, reason='scheduled'):
    """Write one snapshot now. Returns the path, or None on failure."""
    from ..blueprints.admin import dump_db
    try:
        with app.app_context():
            payload = {
                'created': dt.datetime.now().isoformat(timespec='seconds'),
                'reason': reason,
                'data': dump_db(),
            }
            body = json.dumps(payload, indent=2, default=str)
        d = _backup_dir(app)
        stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
        path = os.path.join(d, f'auto-backup-{stamp}.json')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(body)
        _prune(app, d)
        _snapshot_sqlite(app, d, stamp)   # also keep a raw .db copy (easy restore)
        return path
    except Exception as e:  # pragma: no cover - best effort
        try:
            app.logger.warning('Auto-backup failed: %s', e)
        except Exception:
            pass
        try:
            with app.app_context():
                from .notify import notify_event
                notify_event('backup_failed', f'Backup failed: {str(e)[:120]}', link='/m/errorlog')
        except Exception:
            pass
        return None


def _prune(app, d):
    keep = int(app.config.get('BACKUP_KEEP', 14))
    files = sorted(
        (f for f in os.listdir(d) if f.startswith('auto-backup-') and f.endswith('.json')),
        reverse=True,
    )
    for stale in files[keep:]:
        try:
            os.remove(os.path.join(d, stale))
        except OSError:
            pass


def _snapshot_sqlite(app, d, stamp):
    """Also keep a raw copy of the SQLite database file. Restoring is then as simple
    as copying db-snapshot-*.db back over erp.db. Uses SQLite's online-backup API so
    the copy is consistent even while the app is running."""
    import shutil
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri.startswith('sqlite:///'):
        return
    src = uri[len('sqlite:///'):]
    if not os.path.exists(src):
        return
    dst = os.path.join(d, f'db-snapshot-{stamp}.db')
    try:
        import sqlite3
        con = sqlite3.connect(src)
        bck = sqlite3.connect(dst)
        with bck:
            con.backup(bck)
        con.close()
        bck.close()
    except Exception:
        try:
            shutil.copy2(src, dst)
        except Exception:
            return
    keep = int(app.config.get('BACKUP_KEEP', 14))
    files = sorted((f for f in os.listdir(d)
                    if f.startswith('db-snapshot-') and f.endswith('.db')), reverse=True)
    for stale in files[keep:]:
        try:
            os.remove(os.path.join(d, stale))
        except OSError:
            pass


def list_backups(app):
    d = _backup_dir(app)
    out = []
    for f in sorted(os.listdir(d), reverse=True):
        if f.startswith('auto-backup-') and f.endswith('.json'):
            p = os.path.join(d, f)
            out.append({'name': f, 'size': os.path.getsize(p),
                        'mtime': dt.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec='minutes')})
    return out


def start(app):
    """Launch the background backup loop once per process."""
    global _started
    with _lock:
        if _started or app.config.get('TESTING') or not app.config.get('AUTO_BACKUP', True):
            return
        _started = True

    interval = float(app.config.get('BACKUP_INTERVAL_HOURS', 24)) * 3600.0

    def _loop():
        time.sleep(float(app.config.get('BACKUP_STARTUP_DELAY', 30)))
        write_backup(app, reason='startup')
        while True:
            time.sleep(interval)
            write_backup(app, reason='scheduled')

    t = threading.Thread(target=_loop, name='mdc-autobackup', daemon=True)
    t.start()
