"""In-app notification helpers.

notify()       — emit an event (optionally targeted at one role)
unseen_count() — badge number for the top bar bell
mark_seen()    — called when the user opens /notifications
"""
from ..extensions import db
from ..models import Notification


def notify(text, link='', role=None):
    """Emit an in-app notification. `role` may be None (everyone), a single role
    string, or an iterable of roles (comma-joined and matched per-user)."""
    if role and not isinstance(role, str):
        role = ','.join(str(r) for r in role)
    db.session.add(Notification(text=text[:255], link=link[:200], role=role))
    db.session.commit()


# --- Notification Center: which roles hear about which business events --------
_FINANCE = ['accountant', 'branch_manager']
_ADMIN = ['super_admin', 'it_admin']
EVENT_ROLES = {
    'patient_registered': ['reception'],
    'payment_received':   ['cashier'] + _FINANCE,
    'report_completed':   ['reception', 'lab_tech', 'radiologist'],
    'invoice_cancelled':  ['cashier'] + _FINANCE + _ADMIN,
    'low_inventory':      ['lab_tech', 'storekeeper'] + _ADMIN,
    'backup_failed':      _ADMIN,
}


def notify_event(event, text, link=''):
    """Emit a notification routed to the roles that care about `event`.
    Never raises — notifications must never break the action that triggered them."""
    try:
        notify(text, link, role=EVENT_ROLES.get(event))
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _visible(u):
    q = Notification.query.order_by(Notification.id.desc()).limit(120).all()
    out = []
    for n in q:
        roles = set(filter(None, (n.role or '').split(',')))
        if (not roles) or (u.role in roles) or u.role == 'super_admin':
            out.append(n)
    return out


def unseen_count(u):
    return sum(1 for n in _visible(u) if str(u.id) not in (n.seen_by or '').split(','))


def visible_for(u):
    return _visible(u)


def mark_seen(u):
    for n in _visible(u):
        seen = set(filter(None, (n.seen_by or '').split(',')))
        if str(u.id) not in seen:
            seen.add(str(u.id))
            n.seen_by = ','.join(sorted(seen))
    db.session.commit()
