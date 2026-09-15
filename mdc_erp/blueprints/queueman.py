"""Smart Queue — token generation, priority/emergency, displays, voice, analytics.
(Phase 5, v8.0)

Built on the existing QueueTicket model (walk-in tokens), separate from and
non-conflicting with the appointment-based reception queue. Public lobby &
room displays need no login; the staff console is permission-gated ('tokenq').
"""
import datetime as dt
from flask import (Blueprint, request, redirect, url_for, flash, abort, jsonify)
from markupsafe import escape as h
from ..extensions import db
from ..models import QueueTicket, Patient
from ..core.security import (cur_user, can, login_required, log, branch_scope)
from ..core.helpers import today
from ..core.ui import page, public_shell
from ..core.notify import notify

bp = Blueprint('queueman', __name__)

DEPARTMENTS = ['Consultation', 'Laboratory', 'Radiology', 'Pharmacy', 'Cashier']
PRIO_RANK = {'Emergency': 0, 'Priority': 1, 'Normal': 2}
PRIO_PILL = {'Emergency': 'red', 'Priority': 'amber'}
ST_PILL = {'Waiting': 'amber', 'Called': 'blue', 'Done': 'green',
           'Cancelled': 'grey', 'NoShow': 'grey'}


def _now():
    return dt.datetime.now().strftime('%Y-%m-%d %H:%M')


def _hm(ts):
    return (ts or '')[11:16]


def _todays(dept=None):
    q = branch_scope(QueueTicket.query, QueueTicket).filter(QueueTicket.date == today())
    if dept:
        q = q.filter(QueueTicket.department == dept)
    return q.all()


def _wait_sort(tickets):
    return sorted(tickets, key=lambda t: (PRIO_RANK.get(t.priority, 2), t.number or 0))


# ==================================================================== console
def queue_console():
    """Staff token console — App Launcher (mod='tokenq')."""
    tickets = _todays()
    waiting = _wait_sort([t for t in tickets if t.status == 'Waiting'])
    called = [t for t in tickets if t.status == 'Called']
    done = [t for t in tickets if t.status == 'Done']

    # per-department call-next buttons
    dept_bar = ''
    for d in DEPARTMENTS:
        w = [t for t in waiting if t.department == d]
        emerg = any(t.priority == 'Emergency' for t in w)
        dept_bar += (f"<a class='btn {'primary' if w else 'gh'}' "
                     f"href='{url_for('queueman.call_next', dept=d)}'>"
                     f"📢 {h(d)} <span class='pill {'red' if emerg else 'grey'}'>{len(w)}</span></a> ")

    def code_pill(t):
        pc = PRIO_PILL.get(t.priority)
        badge = f" <span class='pill {pc}'>{t.priority[0]}</span>" if pc else ''
        return f"<b style='font-size:15px'>{h(t.code)}</b>{badge}"

    def row(t, acts):
        return (f"<tr><td>{code_pill(t)}</td>"
                f"<td>{h(t.name or (t.patient.name if t.patient else '—'))}</td>"
                f"<td>{h(t.department or '—')}</td>"
                f"<td>{h(t.room or '—')}</td>"
                f"<td>{_hm(t.called_at) or _hm(str(t.created)) or '—'}</td>"
                f"<td><span class='pill {ST_PILL.get(t.status,'grey')}'>{h(t.status)}</span></td>"
                f"<td class='num'>{acts}</td></tr>")

    rows = ''
    for t in called:
        rows += row(t, (f"<a class='btn sm ok' href='{url_for('queueman.act', tid=t.id, a='done')}'>Done</a> "
                        f"<a class='btn sm gh' href='{url_for('queueman.act', tid=t.id, a='recall')}'>🔁 Recall</a>"))
    for t in waiting:
        rows += row(t, (f"<a class='btn sm primary' href='{url_for('queueman.call_next', dept=t.department, tid=t.id)}'>Call</a> "
                        f"<a class='btn sm gh' href='{url_for('queueman.act', tid=t.id, a='cancel')}'>✕</a>"))
    if not rows:
        rows = "<tr><td colspan='7'><div class='empty'><b>No tokens yet today</b>Issue one to start the queue.</div></td></tr>"

    kpis = (f"<div class='kpis'>"
            f"<div class='kpi' style='--ac:var(--amber-dk)'><div class='l'>Waiting</div><div class='v'>{len(waiting)}</div><div class='s'>in queue</div></div>"
            f"<div class='kpi' style='--ac:var(--blue)'><div class='l'>Being served</div><div class='v'>{len(called)}</div><div class='s'>at counters</div></div>"
            f"<div class='kpi' style='--ac:var(--green)'><div class='l'>Served today</div><div class='v'>{len(done)}</div><div class='s'>completed</div></div>"
            f"<div class='kpi' style='--ac:var(--red)'><div class='l'>Emergency</div><div class='v'>{sum(1 for t in waiting if t.priority=='Emergency')}</div><div class='s'>waiting</div></div>"
            f"</div>")
    toolbar = (f"<a class='btn' href='{url_for('queueman.display')}' target='_blank'>🖥 Lobby Display</a> "
               f"<a class='btn' href='{url_for('queueman.analytics')}'>📈 Analytics</a> "
               f"<a class='btn primary' href='{url_for('queueman.issue')}'>+ Issue Token</a>")
    body = (kpis
            + f"<div class='panel'><div class='pad'><b>Call next:</b><br>{dept_bar}</div></div>"
            + f"""<div class="panel"><div class="ph"><h2>Token Queue · {h(today())}</h2>
              <span class="so">Emergency &amp; priority patients are served first</span><div class="sp"></div>
              <a class="btn" href="{url_for('modules.module', mod='tokenq')}">↻ Refresh</a>{toolbar}</div>
              <div class="tw"><table><thead><tr><th>Token</th><th>Name</th><th>Department</th><th>Room</th>
              <th>Time</th><th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>""")
    return page('Token Queue', body, 'tokenq')


@bp.route('/tokenq/issue', methods=['GET', 'POST'])
@login_required
def issue():
    if not can('tokenq'):
        abort(403)
    if request.method == 'POST':
        dept = request.form.get('department') or 'Consultation'
        prio = request.form.get('priority') or 'Normal'
        name = (request.form.get('name') or '').strip()
        pid = request.form.get('patient_id') or None
        top = (db.session.query(db.func.max(QueueTicket.number))
               .filter_by(date=today(), department=dept).scalar() or 0)
        u = cur_user()
        t = QueueTicket(number=top + 1, department=dept, priority=prio,
                        name=name or None, patient_id=pid, status='Waiting',
                        created_by=(u.username if u else None),
                        branch_id=(u.branch_id if u else None))
        db.session.add(t)
        db.session.commit()
        log(f'Queue token {t.code} issued ({prio})', entity=f'QueueTicket#{t.id}')
        flash(f'Token {t.code} issued', 'ok')
        return redirect(url_for('modules.module', mod='tokenq'))
    dopts = ''.join(f"<option>{d}</option>" for d in DEPARTMENTS)
    popts = "<option value=''>— walk-in (no record) —</option>" + ''.join(
        f"<option value='{p.id}'>{h(p.name)}</option>"
        for p in Patient.query.order_by(Patient.id.desc()).limit(200).all())
    inner = f"""
    <div class='panel'><div class='pad'>
      <form method='post' class='formwrap'>
        <div class='fld'><label>Department</label><select name='department'>{dopts}</select></div>
        <div class='fld'><label>Priority</label><select name='priority'>
          <option>Normal</option><option>Priority</option><option>Emergency</option></select></div>
        <div class='fld'><label>Patient (optional)</label><select name='patient_id'>{popts}</select></div>
        <div class='fld'><label>or Name (walk-in)</label><input name='name' placeholder='Full name'></div>
        <div class='fld full'><button class='btn primary'>Issue token</button>
          <a class='btn gh' href="{url_for('modules.module', mod='tokenq')}">Cancel</a></div>
      </form>
      <div style='font-size:12px;color:var(--muted);margin-top:6px'>
        Priority (elderly/disabled) and Emergency tokens are automatically served before Normal tokens.</div>
    </div></div>"""
    return page('Issue Token', inner, 'tokenq')


@bp.route('/tokenq/call/<dept>')
@bp.route('/tokenq/call/<dept>/<int:tid>')
@login_required
def call_next(dept, tid=None):
    if not can('tokenq'):
        abort(403)
    u = cur_user()
    room = request.args.get('room') or (u.username if u else '') or dept
    if tid:
        t = QueueTicket.query.get_or_404(tid)
    else:
        waiting = _wait_sort([x for x in _todays(dept) if x.status == 'Waiting'])
        if not waiting:
            flash(f'No one waiting in {dept}', 'error')
            return redirect(url_for('modules.module', mod='tokenq'))
        t = waiting[0]
    t.status = 'Called'
    t.called_at = _now()
    t.room = room[:30]
    db.session.commit()
    log(f'Queue token {t.code} called to {t.room}', entity=f'QueueTicket#{t.id}')
    notify(f'Now serving {t.code} → {t.room}', url_for('queueman.display'),
           role=['reception', 'doctor'])
    return redirect(url_for('modules.module', mod='tokenq'))


@bp.route('/tokenq/<int:tid>/<a>')
@login_required
def act(tid, a):
    if not can('tokenq'):
        abort(403)
    t = QueueTicket.query.get_or_404(tid)
    if a == 'done':
        t.status = 'Done'
        t.done_at = _now()
    elif a == 'recall':
        t.called_at = _now()
        notify(f'Re-calling {t.code} → {t.room or ""}', url_for('queueman.display'), role=['reception'])
    elif a == 'cancel':
        t.status = 'Cancelled'
    elif a == 'noshow':
        t.status = 'NoShow'
    db.session.commit()
    log(f'Queue token {t.code} → {t.status}', entity=f'QueueTicket#{t.id}')
    return redirect(url_for('modules.module', mod='tokenq'))


# ============================================================= public displays
@bp.route('/display')
@bp.route('/display/<room>')
def display(room=None):
    """Public lobby / room display board (no login). Voice announces new calls."""
    title = f'Queue Display · {room}' if room else 'Queue Display'
    feed = url_for('queueman.display_feed', room=room) if room else url_for('queueman.display_feed')
    scope = h(room) if room else 'All Departments'
    inner = f"""
    <div style='min-height:100vh;background:#0b1220;color:#fff;font-family:system-ui,sans-serif;padding:2vw'>
      <div style='display:flex;align-items:center;justify-content:space-between'>
        <h1 style='margin:0;font-size:3vw'>Modern Diagnostic Center</h1>
        <button id='sound' onclick='enableSound()' style='padding:8px 16px;border-radius:8px;border:0;background:#2563eb;color:#fff;cursor:pointer'>🔊 Enable sound</button>
      </div>
      <div style='color:#93c5fd;font-size:1.4vw;margin-bottom:1vw'>{scope} · <span id='clock'></span></div>
      <div id='now' style='display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1.2vw'></div>
      <h2 style='color:#93c5fd;margin-top:2vw;font-size:1.6vw'>Waiting</h2>
      <div id='waiting' style='font-size:2vw;letter-spacing:2px;color:#cbd5e1'></div>
    </div>
    <script>
    let soundOn=false, spoken={{}};
    function enableSound(){{ soundOn=true; document.getElementById('sound').style.display='none';
      try{{var u=new SpeechSynthesisUtterance('Sound enabled');speechSynthesis.speak(u);}}catch(e){{}} }}
    function speak(txt){{ if(!soundOn)return; try{{var u=new SpeechSynthesisUtterance(txt);u.rate=.9;speechSynthesis.speak(u);}}catch(e){{}} }}
    function tick(){{ document.getElementById('clock').textContent=new Date().toLocaleTimeString(); }}
    setInterval(tick,1000); tick();
    async function refresh(){{
      try{{
        const r=await fetch('{feed}'); const d=await r.json();
        const now=document.getElementById('now');
        now.innerHTML = d.called.length ? '' : "<div style='color:#64748b;font-size:1.4vw'>No one being served right now</div>";
        d.called.forEach(function(c){{
          const card=document.createElement('div');
          card.style.cssText='background:#111c33;border:2px solid #2563eb;border-radius:16px;padding:1.4vw;text-align:center';
          card.innerHTML="<div style='font-size:1.2vw;color:#93c5fd'>"+c.department+"</div>"+
            "<div style='font-size:5vw;font-weight:800;line-height:1'>"+c.code+"</div>"+
            "<div style='font-size:1.6vw;color:#fbbf24'>➜ "+c.room+"</div>";
          now.appendChild(card);
          if(spoken[c.id]!==c.called_at){{ spoken[c.id]=c.called_at;
            speak('Token '+c.code.split('-').join(' ')+', please proceed to '+c.room); }}
        }});
        document.getElementById('waiting').textContent =
          d.waiting.length ? d.waiting.join('   ') : '—';
      }}catch(e){{}}
    }}
    refresh(); setInterval(refresh,4000);
    </script>"""
    return public_shell(title, inner)


@bp.route('/display/feed')
@bp.route('/display/feed/<room>')
def display_feed(room=None):
    tickets = _todays()
    if room:
        called = [t for t in tickets if t.status == 'Called' and (t.room == room or t.department == room)]
    else:
        called = [t for t in tickets if t.status == 'Called']
    called.sort(key=lambda t: t.called_at or '', reverse=True)
    waiting = _wait_sort([t for t in tickets if t.status == 'Waiting'])
    return jsonify({
        'called': [{'id': t.id, 'code': t.code, 'department': t.department or '',
                    'room': t.room or '', 'called_at': t.called_at or ''} for t in called[:6]],
        'waiting': [t.code for t in waiting[:20]],
    })


# ================================================================== analytics
@bp.route('/tokenq/analytics')
@login_required
def analytics():
    if not can('tokenq'):
        abort(403)
    frm = request.args.get('from') or today()
    to = request.args.get('to') or today()
    tickets = branch_scope(QueueTicket.query, QueueTicket).filter(
        QueueTicket.date >= frm, QueueTicket.date <= to).all()

    def _mins(a, b):
        try:
            da = dt.datetime.strptime(a[:16], '%Y-%m-%d %H:%M')
            db_ = dt.datetime.strptime(b[:16], '%Y-%m-%d %H:%M')
            return max(int((db_ - da).total_seconds() // 60), 0)
        except Exception:
            return None

    by_dept = {}
    for t in tickets:
        d = by_dept.setdefault(t.department or '—', {'issued': 0, 'served': 0, 'wait': [], 'svc': []})
        d['issued'] += 1
        if t.status == 'Done':
            d['served'] += 1
        if t.called_at:
            w = _mins(str(t.created).replace('T', ' '), t.called_at)
            if w is not None:
                d['wait'].append(w)
        if t.called_at and t.done_at:
            s = _mins(t.called_at, t.done_at)
            if s is not None:
                d['svc'].append(s)

    def avg(xs):
        return f"{sum(xs)//len(xs)}m" if xs else '—'
    rows = ''
    tot_i = tot_s = 0
    for d, v in sorted(by_dept.items()):
        tot_i += v['issued']
        tot_s += v['served']
        rows += (f"<tr><td>{h(d)}</td><td class='num'>{v['issued']}</td><td class='num'>{v['served']}</td>"
                 f"<td class='num'>{avg(v['wait'])}</td><td class='num'>{avg(v['svc'])}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='5'><div class='empty'><b>No tokens in this period</b></div></td></tr>"
    body = f"""
    <div class='panel'><div class='ph'><h2>Queue Analytics</h2><div class='sp'></div>
      <form method='get' style='display:flex;gap:6px;align-items:center'>
        <input type='date' name='from' value='{h(frm)}'><span>→</span>
        <input type='date' name='to' value='{h(to)}'><button class='btn sm'>View</button></form></div>
      <div class='pad' style='display:flex;gap:20px;font-size:14px'>
        <div><b style='font-size:22px'>{tot_i}</b><br>tokens issued</div>
        <div><b style='font-size:22px'>{tot_s}</b><br>served</div></div>
      <div class='tw'><table><thead><tr><th>Department</th><th class='num'>Issued</th><th class='num'>Served</th>
      <th class='num'>Avg wait</th><th class='num'>Avg service</th></tr></thead><tbody>{rows}</tbody></table></div></div>"""
    return page('Queue Analytics', body, 'tokenq',
                crumbs=[('Token Queue', url_for('modules.module', mod='tokenq')), ('Analytics', None)])
