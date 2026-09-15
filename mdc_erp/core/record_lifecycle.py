"""Reusable record lifecycle operations for the ERP.

Archive is the default destructive-looking action. Hard deletion is available
only for explicitly non-protected entities and always requires a reason.
"""
import datetime as dt
import json
from sqlalchemy import inspect
from ..extensions import db
from ..models import RecordArchive, Audit
from .security import cur_user

PROTECTED_TYPES = {
    'Invoice', 'InvoiceItem', 'PayReceipt', 'LabOrder', 'RadOrder',
    'Consultation', 'JournalEntry', 'JournalLine', 'Audit', 'RecordArchive',
}


def _user_name():
    u = cur_user()
    return (u.username if u else 'system')[:80]


def _audit_pending(action, action_type, entity, reason=None):
    """Queue an audit row in the caller's transaction; do not commit here."""
    db.session.add(Audit(user=_user_name(), action=action,
                         action_type=action_type, entity=entity,
                         reason=(reason[:255] if reason else None)))


def snapshot_record(record):
    """Serialize simple column values without exposing relationships."""
    data = {}
    for column in inspect(record).mapper.column_attrs:
        value = getattr(record, column.key, None)
        if isinstance(value, (dt.date, dt.datetime)):
            value = value.isoformat()
        data[column.key] = value
    return data


def archive_record(record, reason, label=None):
    reason = (reason or '').strip()[:255]
    if not reason:
        raise ValueError('An archive reason is required.')
    entity_type = type(record).__name__
    archive = RecordArchive(entity_type=entity_type, entity_id=record.id,
                            label=(label or f'{entity_type} #{record.id}')[:200],
                            snapshot=json.dumps(snapshot_record(record), default=str),
                            reason=reason, archived_by=_user_name())
    db.session.add(archive)
    # Generic active flags are used where present; financial rows remain intact.
    if hasattr(record, 'active'):
        record.active = False
    db.session.flush()
    _audit_pending(f'Archived {entity_type} #{record.id}', 'Archive',
                   f'{entity_type}-{record.id}', reason)
    return archive


def restore_archive(archive):
    if not archive or not archive.active:
        raise ValueError('Archive entry is already restored or unavailable.')
    model = _model_for_type(archive.entity_type)
    if model is None:
        raise ValueError('This record type cannot be restored automatically.')
    record = db.session.get(model, archive.entity_id)
    if record is None:
        raise ValueError('The original record no longer exists.')
    if hasattr(record, 'active'):
        record.active = True
    archive.active = False
    archive.restored_by = _user_name()
    archive.restored_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    db.session.flush()
    _audit_pending(f'Restored {archive.entity_type} #{archive.entity_id}', 'Restore',
                   f'{archive.entity_type}-{archive.entity_id}')
    return record


def delete_record(record, reason):
    entity_type = type(record).__name__
    if entity_type in PROTECTED_TYPES:
        raise ValueError(f'{entity_type} is protected; archive or cancel it instead of deleting it.')
    reason = (reason or '').strip()[:255]
    if not reason:
        raise ValueError('A deletion reason is required.')
    db.session.delete(record)
    db.session.flush()
    _audit_pending(f'Deleted {entity_type} #{record.id}', 'Delete',
                   f'{entity_type}-{record.id}', reason)


def _model_for_type(entity_type):
    from .. import models
    model = getattr(models, entity_type, None)
    return model if model is not None else None
