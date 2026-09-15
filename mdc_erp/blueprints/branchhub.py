"""Multi-branch hub  (Phase 15, v8.0).

A per-branch overview for cross-branch users, plus a branch **focus switcher**:
an admin can narrow the whole ERP to a single branch (or view all branches).
The focus is stored in the session and honoured by the core branch_scope, so
every module's lists, dashboards and detail pages follow it. No new tables.
"""
from flask import Blueprint, session, redirect, url_for, flash, abort
from markupsafe import escape as h
from ..extensions import db
from ..models import Branch, Patient, Invoice, User, Admission, EDVisit
from ..core.security import (cur_user, log, focus_branch,
                             _is_cross)
from ..core.helpers import money, today
from ..core.ui import page

bp = Blueprint('branchhub', __name__)


def _sum_paid(rows):
    return sum((i.paid or 0) for i in rows)


def branch_hub():
    """Branch overview + focus switcher — App Launcher (mod='branchhub')."""
    u = cur_user()
    cross = _is_cross(u)
    focus = focus_branch()
    branches = Branch.query.order_by(Branch.name).all()

    # preload once, bucket by branch
    pts = Patient.query.all()
    invs = Invoice.query.options(db.joinedload(Invoice.items)).all()
    adms = Admission.query.filter_by(status='Admitted').all()
    eds = EDVisit.query.filter(EDVisit.status.in_(['Waiting', 'InTreatment', 'Observation'])).all()
    users = User.query.filter_by(active=True).all()

    def by(rows, bid):
        return [r for r in rows if getattr(r, 'branch_id', None) == bid]

    # focus banner
    if cross:
        cur = ('All branches' if focus is None
               else next((b.name for b in branches if b.id == focus), f'Branch #{focus}'))
        banner = (f"<div class='panel' style='border-left:4px solid var(--petrol)'><div class='pad' "
                  f"style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>"
                  f"<div>Currently viewing: <b>{h(cur)}</b>"
                  f"<div style='font-size:12px;color:var(--muted)'>Focus narrows every screen in the system to one branch.</div></div>"
                  f"<a class='btn {'primary' if focus else 'gh'}' href='{url_for('branchhub.focus_all')}'>View all branches</a></div></div>")
    else:
        banner = (f"<div class='panel'><div class='pad' style='font-size:13px;color:var(--muted)'>"
                  f"You are scoped to your branch. Only administrators can switch branch focus.</div></div>")

    rows = ''
    for b in branches:
        bp_pts, bp_adm, bp_ed = len(by(pts, b.id)), len(by(adms, b.id)), len(by(eds, b.id))
        bp_rev = _sum_paid(by(invs, b.id))
        bp_staff = len(by(users, b.id))
        is_focus = (focus == b.id)
        act = ''
        if cross:
            act = (f"<a class='btn sm {'primary' if is_focus else ''}' "
                   f"href='{url_for('branchhub.focus_one', bid=b.id)}'>{'● Focused' if is_focus else 'Focus'}</a>")
        rows += (f"<tr{' style=background:var(--petrol-soft,#eef4f5)' if is_focus else ''}>"
                 f"<td><b>{h(b.name)}</b>{' <span class=pill grey>'+h(b.code)+'</span>' if b.code else ''}"
                 f"<br><span style='font-size:12px;color:var(--muted)'>{h(b.address or '')} {h(b.phone or '')}</span></td>"
                 f"<td class='num'>{bp_pts}</td><td class='num'>{bp_staff}</td>"
                 f"<td class='num'>{bp_adm}</td><td class='num'>{bp_ed}</td>"
                 f"<td class='num'>{money(bp_rev)}</td><td class='num'>{act}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='7'><div class='empty'><b>No branches</b>Add one under Administration → Branches.</div></td></tr>"

    table = (f"<div class='panel'><div class='ph'><h2>Branches · {h(today())}</h2><div class='sp'></div>"
             f"<a class='btn' href='{url_for('modules.module', mod='branches')}'>Manage branches</a></div>"
             f"<div class='tw'><table><thead><tr><th>Branch</th><th class='num'>Patients</th>"
             f"<th class='num'>Staff</th><th class='num'>Inpatients</th><th class='num'>ED active</th>"
             f"<th class='num'>Collected</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>")
    return page('Branches', banner + table, 'branchhub')


def _require_cross():
    u = cur_user()
    if not _is_cross(u):
        abort(403)
    return u


@bp.route('/branch/focus/<int:bid>')
def focus_one(bid):
    _require_cross()
    b = Branch.query.get_or_404(bid)
    session['focus_branch'] = b.id
    log(f'Branch focus set to {b.name}', action_type='view', entity=f'Branch#{b.id}')
    flash(f'Now viewing {b.name}', 'ok')
    return redirect(url_for('modules.module', mod='branchhub'))


@bp.route('/branch/focus/all')
def focus_all():
    _require_cross()
    session.pop('focus_branch', None)
    log('Branch focus cleared (all branches)', action_type='view', entity='Branch')
    flash('Now viewing all branches', 'ok')
    return redirect(url_for('modules.module', mod='branchhub'))
