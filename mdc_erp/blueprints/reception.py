"""Reception queue: daily token numbers, check-in, call-next and status board."""
import datetime as dt
from flask import Blueprint, redirect, url_for, flash, abort
from markupsafe import escape as h
from ..extensions import db
from ..models import Appointment
from ..core.security import can, login_required, log
from ..core.helpers import today
from ..core.ui import page

bp = Blueprint('reception', __name__)

QUEUE_FLOW = {'Scheduled': 'Waiting', 'Waiting': 'In Progress', 'In Progress': 'Done'}
PILL = {'Scheduled': 'grey', 'Waiting': 'amber', 'In Progress': 'blue',
        'Done': 'green', 'Cancelled': 'red'}


def _todays():
    return (Appointment.query.filter_by(date=today())
            .order_by(Appointment.queue_no.is_(None), Appointment.queue_no,
                      Appointment.time, Appointment.id).all())


def queue_view():
    appts = _todays()
    waiting = [a for a in appts if a.status == 'Waiting']
    serving = [a for a in appts if a.status == 'In Progress']
    done = [a for a in appts if a.status == 'Done']

    def board_card(label, value, sub, ac):
        return (f"<div class='kpi' style='--ac:{ac}'><div class='l'>{label}</div>"
                f"<div class='v'>{value}</div><div class='s'>{sub}</div></div>")

    now_no = serving[0].queue_no if serving and serving[0].queue_no else '—'
    next_no = waiting[0].queue_no if waiting and waiting[0].queue_no else '—'
    kpis = ("<div class='kpis'>"
            + board_card('Now Serving · Hadda', f"<span style='font-size:34px'>{now_no}</span>",
                         (h(serving[0].patient.name) if serving and serving[0].patient else '—'), 'var(--blue)')
            + board_card('Next · Xiga', f"<span style='font-size:34px'>{next_no}</span>",
                         (h(waiting[0].patient.name) if waiting and waiting[0].patient else '—'), 'var(--amber)')
            + board_card('Waiting · Sugaya', len(waiting), 'checked-in', 'var(--amber-dk)')
            + board_card('Done · Dhammeystiran', len(done), 'served today', 'var(--green)')
            + "</div>")

    rows = ''
    for a in appts:
        if a.status == 'Cancelled':
            continue
        acts = ''
        if a.status == 'Scheduled':
            acts = (f"<a class='btn sm' href='{url_for('reception.queue_action', aid=a.id, act='confirm')}'>Confirm</a> "
                    f"<a class='btn sm primary' href='{url_for('reception.queue_action', aid=a.id, act='checkin')}'>Check in</a> "
                    f"<a class='btn sm gh' href='{url_for('reception.queue_action', aid=a.id, act='noshow')}'>No show</a>")
        elif a.status == 'Confirmed':
            acts = (f"<a class='btn sm primary' href='{url_for('reception.queue_action', aid=a.id, act='checkin')}'>Check in</a> "
                    f"<a class='btn sm gh' href='{url_for('reception.queue_action', aid=a.id, act='noshow')}'>No show</a>")
        elif a.status == 'Waiting':
            acts = f"<a class='btn sm' href='{url_for('reception.queue_action', aid=a.id, act='start')}'>Call / Start</a>"
        elif a.status == 'In Progress':
            acts = f"<a class='btn sm ok' href='{url_for('reception.queue_action', aid=a.id, act='done')}'>Done</a>"
        no = f"<b style='font-size:16px'>{a.queue_no}</b>" if a.queue_no else '—'
        rows += (f"<tr><td class='num'>{no}</td><td>{h(a.time or '—')}</td>"
                 f"<td>{h(a.patient.name if a.patient else '—')}</td>"
                 f"<td>{h(a.department or '—')}</td><td>{h(a.doctor or '—')}</td>"
                 f"<td>{h(a.checkin_time or '—')}</td>"
                 f"<td><span class='pill {PILL.get(a.status, 'grey')}'>{h(a.status)}</span></td>"
                 f"<td class='num'>{acts}</td></tr>")
    if not rows:
        rows = ("<tr><td colspan='8'><div class='empty'><b>No appointments today</b>"
                f"Book one in <a href='{url_for('modules.module', mod='appointments')}' "
                "style='color:var(--amber-dk);font-weight:600'>Appointments</a>.</div></td></tr>")

    body = kpis + f"""<div class="panel"><div class="ph"><h2>Today's Queue · {h(today())}</h2>
      <span class="so">Check in → Call → Done · token numbers reset daily</span><div class="sp"></div>
      <a class="btn" href="{url_for('modules.module', mod='queue')}">↻ Refresh</a>
      <a class="btn primary" href="{url_for('modules.module', mod='appointments')}">+ Appointment</a></div>
      <div class="tw"><table><thead><tr><th class="num">No.</th><th>Time</th><th>Patient</th><th>Department</th>
      <th>Doctor</th><th>Checked in</th><th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>"""
    return page('Reception Queue', body, 'queue')


@bp.route('/queue/<int:aid>/<act>')
@login_required
def queue_action(aid, act):
    if not can('queue'):
        abort(403)
    a = Appointment.query.get_or_404(aid)
    if act == 'confirm' and a.status == 'Scheduled':
        a.status = 'Confirmed'
        log(f'Queue: confirmed appt #{aid}')
    elif act == 'noshow' and a.status in ('Scheduled', 'Confirmed'):
        a.status = 'No Show'
        log(f'Queue: no-show appt #{aid}')
    elif act == 'checkin' and a.status in ('Scheduled', 'Confirmed'):
        top = (db.session.query(db.func.max(Appointment.queue_no))
               .filter_by(date=today()).scalar() or 0)
        a.queue_no = top + 1
        a.checkin_time = dt.datetime.now().strftime('%H:%M')
        a.status = 'Waiting'
        log(f'Queue: checked in appt #{aid} as token {a.queue_no}')
        from ..core.notify import notify
        notify(f'Token {a.queue_no} checked in · {a.patient.name if a.patient else ""}'
               + (f' → Dr {a.doctor}' if a.doctor else ''),
               '/m/queue', role='doctor')
    elif act == 'start' and a.status == 'Waiting':
        a.status = 'In Progress'
        log(f'Queue: serving token {a.queue_no or aid}')
    elif act == 'done' and a.status in ('Waiting', 'In Progress'):
        a.status = 'Done'
        log(f'Queue: completed token {a.queue_no or aid}')
    db.session.commit()
    return redirect(url_for('modules.module', mod='queue'))


@bp.route('/appt/<int:aid>/remind')
@login_required
def appt_remind(aid):
    if not can('queue') and not can('appointments'): abort(403)
    a = Appointment.query.get_or_404(aid)
    if not (a.patient and a.patient.phone):
        flash('Patient has no phone number'); return redirect(url_for('modules.module', mod='appointments'))
    from ..core.messaging import queue_msg
    m = queue_msg(a.patient.phone,
                  f"{a.patient.name}, xusuusin: ballan MDC {a.date} {a.time or ''} ({a.department or 'Consultation'}"
                  + (f", Dr {a.doctor}" if a.doctor else '') + "). Fadlan waqtiga kaalay.",
                  ref=f'APPT-{a.id}')
    log(f'Reminder queued for appt #{aid}')
    flash(f'Reminder {m.status if m else "skipped"} → {a.patient.phone}')
    return redirect(url_for('modules.module', mod='appointments'))
