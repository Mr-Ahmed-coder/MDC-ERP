"""Universal record lifecycle actions for authorized administrative users."""
from flask import Blueprint, request, redirect, url_for, flash, abort
from ..extensions import db
from ..models import RecordArchive
from ..core.security import login_required, can
from ..core.ui import page
from ..core.record_lifecycle import archive_record, restore_archive, delete_record, _model_for_type

bp = Blueprint('record_options', __name__)


def _guard():
    if not can('record_options'):
        abort(403)


def _record(entity, rid):
    model = _model_for_type(entity)
    if model is None or entity == 'RecordArchive':
        abort(404)
    return db.session.get(model, rid) or abort(404)


@bp.route('/record-options')
@login_required
def index():
    _guard()
    rows = RecordArchive.query.order_by(RecordArchive.id.desc()).limit(500).all()
    body = ''.join(
        f"<tr><td>{a.id}</td><td>{a.entity_type} #{a.entity_id}</td>"
        f"<td>{a.label or ''}</td><td>{a.reason}</td><td>{a.archived_by}</td>"
        f"<td>{a.archived_at.strftime('%Y-%m-%d %H:%M') if a.archived_at else ''}</td>"
        f"<td>{'Archived' if a.active else 'Restored'}</td>"
        f"<td>{('<form method=post action=' + url_for('record_options.restore', aid=a.id) + '><button class=\"btn gh sm\">Restore</button></form>') if a.active else ''}</td></tr>"
        for a in rows
    ) or '<tr><td colspan="8">No archive records.</td></tr>'
    return page('Record Options', f'''<div class="panel"><div class="ph"><h2>Record Options</h2><span class="so">Archive history and restore</span></div>
      <div class="tw"><table><thead><tr><th>ID</th><th>Record</th><th>Label</th><th>Reason</th><th>By</th><th>When</th><th>Status</th><th></th></tr></thead><tbody>{body}</tbody></table></div></div>''', 'record_options')


@bp.route('/record-options/archive/<entity>/<int:rid>', methods=['POST'])
@login_required
def archive(entity, rid):
    _guard()
    record = _record(entity, rid)
    reason = request.form.get('reason') or request.form.get('archive_reason')
    try:
        archive_record(record, reason, label=request.form.get('label'))
        db.session.commit()
        flash(f'{entity} archived.')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc))
    return redirect(request.referrer or url_for('record_options.index'))


@bp.route('/record-options/restore/<int:aid>', methods=['POST'])
@login_required
def restore(aid):
    _guard()
    archive_row = RecordArchive.query.get_or_404(aid)
    try:
        restore_archive(archive_row)
        db.session.commit()
        flash('Record restored.')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc))
    return redirect(request.referrer or url_for('record_options.index'))


@bp.route('/record-options/delete/<entity>/<int:rid>', methods=['POST'])
@login_required
def delete(entity, rid):
    _guard()
    record = _record(entity, rid)
    reason = request.form.get('reason') or request.form.get('delete_reason')
    try:
        delete_record(record, reason)
        db.session.commit()
        flash(f'{entity} deleted.')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc))
    return redirect(request.referrer or url_for('record_options.index'))
