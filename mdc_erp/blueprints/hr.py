"""HR: attendance, leave and payroll posting."""
from flask import (Blueprint, request, redirect, url_for, flash, abort)
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from ..core.security import (can, login_required, log)
from ..core.helpers import money, today
from ..core.ui import page
from ..core.crud import (render_form, opt_employees)
from ..core.posting import (post_journal)

bp = Blueprint('hr', __name__)

def attendance_view():
    d=request.args.get('date',today())
    emps=Employee.query.filter_by(active=True).order_by(Employee.name).all()
    existing={a.employee_id:a.status for a in Attendance.query.filter_by(date=d).all()}
    rows=''
    for e in emps:
        st=existing.get(e.id,'')
        btns=''.join(f"<a class='btn sm {'primary' if st==s else ''}' href='{url_for('hr.attendance_mark',eid=e.id,date=d,status=s)}'>{s}</a> " for s in ['Present','Absent','Leave'])
        rows+=f"<tr><td><b>{h(e.code)}</b></td><td>{h(e.name)}</td><td>{h(e.position or '—')}</td><td>{btns}</td></tr>"
    if not emps: rows="<tr><td colspan='4'><div class='empty'><b>No employees</b></div></td></tr>"
    return page('Attendance', f"""<div class="panel"><div class="ph"><h2>Attendance</h2><div class="sp"></div>
      <form method="get" style="display:flex;gap:8px;align-items:center"><input type="date" name="date" value="{h(d)}" style="border:1px solid var(--line);border-radius:8px;padding:7px 10px"><button class="btn sm">Go</button></form></div>
      <div class="tw"><table><thead><tr><th>Code</th><th>Name</th><th>Position</th><th>Mark</th></tr></thead><tbody>{rows}</tbody></table></div></div>""",'attendance')

@bp.route('/attendance/<int:eid>/mark')
@login_required
def attendance_mark(eid):
    d=request.args.get('date',today()); st=request.args.get('status','Present')
    a=Attendance.query.filter_by(employee_id=eid,date=d).first()
    if not a: a=Attendance(employee_id=eid,date=d); db.session.add(a)
    a.status=st; db.session.commit(); return redirect(url_for('modules.module',mod='attendance')+f'?date={d}')

def leave_view():
    leaves=Leave.query.order_by(Leave.id.desc()).all(); rows=''
    for l in leaves:
        st={'Pending':'amber','Approved':'green','Rejected':'red'}
        acts=''
        if l.status=='Pending': acts=f"<a class='btn sm ok' href='{url_for('hr.leave_act',lid=l.id,act='Approved')}'>Approve</a> <a class='btn sm' href='{url_for('hr.leave_act',lid=l.id,act='Rejected')}'>Reject</a>"
        rows+=f"<tr><td>{h(l.employee.name if l.employee else '—')}</td><td>{h(l.type)}</td><td>{h(l.start)} → {h(l.end)}</td><td><span class='pill {st.get(l.status,'grey')}'>{h(l.status)}</span></td><td class='num'>{acts}</td></tr>"
    if not leaves: rows="<tr><td colspan='5'><div class='empty'><b>No leave requests</b></div></td></tr>"
    return page('Leave', f"""<div class="panel"><div class="ph"><h2>Leave Requests</h2><div class="sp"></div><a class="btn primary" href="{url_for('hr.leave_new')}">+ New Request</a></div>
      <div class="tw"><table><thead><tr><th>Employee</th><th>Type</th><th>Period</th><th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>""",'leave')

@bp.route('/leave/new', methods=['GET','POST'])
@login_required
def leave_new():
    if not can('leave'): abort(403)
    if request.method=='POST':
        lv=Leave(employee_id=request.form['employee_id'],type=request.form['type'],start=request.form['start'],end=request.form['end'])
        db.session.add(lv); db.session.commit()
        from ..core.notify import notify
        emp = lv.employee
        notify(f"Leave request: {emp.name if emp else '—'} · {lv.type} {lv.start} → {lv.end}",
               link='/m/leave', role='hr')
        log('Leave requested'); flash('Leave requested'); return redirect(url_for('modules.module',mod='leave'))
    fields=[dict(name='employee_id',label='Employee',type='select',options=opt_employees(),required=True),
            dict(name='type',label='Leave Type',type='select',options=[(t,t) for t in ['Annual','Sick','Unpaid','Maternity','Other']]),
            dict(name='start',label='Start Date',type='date',required=True),dict(name='end',label='End Date',type='date',required=True)]
    return page('New Leave', render_form('New Leave Request',url_for('hr.leave_new'),fields,back=url_for('modules.module',mod='leave')),'leave')

@bp.route('/leave/<int:lid>/<act>')
@login_required
def leave_act(lid, act):
    l=Leave.query.get_or_404(lid); l.status=act; db.session.commit(); log(f'Leave #{lid} {act}'); return redirect(url_for('modules.module',mod='leave'))

def payroll_view():
    emps=Employee.query.filter_by(active=True).order_by(Employee.name).all()
    rows=''; tg=tn=0
    for e in emps:
        tg+=e.gross; tn+=e.net
        rows+=f"<tr><td><b>{h(e.code)}</b></td><td>{h(e.name)}</td><td class='num'>{money(e.base)}</td><td class='num'>{money(e.allowance)}</td><td class='num'>{money(e.deduction)}</td><td class='num'>{money(e.gross)}</td><td class='num' style='font-weight:600'>{money(e.net)}</td></tr>"
    if not emps: rows="<tr><td colspan='7'><div class='empty'><b>No employees</b></div></td></tr>"
    return page('Payroll', f"""<div class="panel"><div class="ph"><h2>Monthly Payroll</h2><span class="so">{len(emps)} employees</span><div class="sp"></div><a class="btn sm primary" href="{url_for('hr.payroll_post')}" onclick="return confirm('Post this payroll to Accounting (General Ledger)?')">Post to Accounting</a> <button class="btn sm" onclick="MDCDoc.openSelf('Monthly Payroll','{url_for('hr.payroll_pdf')}')">Print</button></div>
      <div class="tw"><table><thead><tr><th>Code</th><th>Name</th><th class="num">Base</th><th class="num">Allowance</th><th class="num">Deduction</th><th class="num">Gross</th><th class="num">Net</th></tr></thead><tbody>{rows}</tbody>
      <tfoot><tr style="font-weight:700;background:rgba(0,0,0,.02)"><td colspan="5" style="padding:12px 14px">TOTAL</td><td class="num">{money(tg)}</td><td class="num">{money(tn)}</td></tr></tfoot></table></div></div>""",'payroll')

@bp.route('/payroll/pdf')
@login_required
def payroll_pdf():
    if not can('payroll'):
        abort(403)
    from flask import Response
    from ..core.pdfgen import ledger_pdf, available
    from ..core.security import setting
    emps = Employee.query.filter_by(active=True).order_by(Employee.name).all()
    rows = [[e.code or '', e.name, money(e.base), money(e.allowance), money(e.deduction),
             money(e.gross), money(e.net)] for e in emps]
    cols = [('Code', 'l', 16), ('Name', 'l', 50), ('Base', 'r', 22), ('Allowance', 'r', 24),
            ('Deduction', 'r', 24), ('Gross', 'r', 24), ('Net', 'r', 24)]
    totals = ['TOTAL', '', '', '', '', money(sum(e.gross for e in emps)), money(sum(e.net for e in emps))]
    if not available():
        return redirect(url_for('modules.module', mod='payroll'))
    pdf = ledger_pdf('Monthly Payroll', f'{len(emps)} employees', cols, rows, totals,
                     company=setting('company', 'Modern Diagnostic Center'), currency=setting('currency', '$'))
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + ';filename=Monthly-Payroll.pdf'
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


@bp.route('/payroll/post')
@login_required
def payroll_post():
    if not can('payroll'): abort(403)
    emps=Employee.query.filter_by(active=True).all()
    tg=sum(e.gross for e in emps); tn=sum(e.net for e in emps); ym=today()[:7]
    post_journal(today(), f"PAYROLL-{ym}", f"Payroll {ym}", [('6100', tg, 0), ('1102', 0, tn), ('2100', 0, tg-tn)])
    log('Posted payroll to accounting'); flash('Payroll posted to Accounting'); return redirect(url_for('modules.module', mod='payroll'))



# ============================ HR · Odoo-style dashboard ============================
def hr_dashboard():
    """Odoo-style HR hub: headcount + attendance + leave + payroll at a glance."""
    _tdy = today()
    emps = Employee.query.filter_by(active=True).all()
    headcount = len(emps)
    att = {a.employee_id: a.status for a in Attendance.query.filter_by(date=_tdy).all()}
    present = sum(1 for e in emps if att.get(e.id) == 'Present')
    absent = sum(1 for e in emps if att.get(e.id) == 'Absent')
    on_leave = sum(1 for e in emps if att.get(e.id) == 'Leave')
    unmarked = headcount - present - absent - on_leave
    pending_leave = Leave.query.filter_by(status='Pending').all()
    payroll_net = sum(e.net for e in emps)
    payroll_gross = sum(e.gross for e in emps)

    CSS = """<style>
    .hr-stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
    .hr-stat{flex:1;min-width:150px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
    .hr-stat .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);font-weight:700}
    .hr-stat .v{font-size:22px;font-weight:800;font-family:var(--fd);line-height:1.15;margin-top:2px}
    .hr-stat.a{border-left:3px solid var(--petrol)} .hr-stat.b{border-left:3px solid var(--green)}
    .hr-stat.c{border-left:3px solid var(--amber)} .hr-stat.d{border-left:3px solid var(--red)}
    .hr-tiles{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
    .hr-tile{flex:1;min-width:150px;border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:14px;text-decoration:none;color:var(--ink);box-shadow:var(--shadow);transition:.12s}
    .hr-tile:hover{border-color:var(--petrol);transform:translateY(-1px)}
    .hr-tile .t{font-weight:700;font-size:14px;color:var(--petrol)} .hr-tile .s{font-size:12px;color:var(--muted);margin-top:2px}
    </style>"""

    def _c(cls, l, v):
        return f"<div class='hr-stat {cls}'><div class='l'>{l}</div><div class='v'>{v}</div></div>"
    stats = ("<div class='hr-stats'>"
             + _c('a', 'Employees', str(headcount))
             + _c('b', 'Present Today', str(present))
             + _c('d', 'Absent Today', str(absent))
             + _c('c', 'On Leave Today', str(on_leave))
             + _c('c', 'Pending Leave', str(len(pending_leave)))
             + _c('a', 'Monthly Payroll (Net)', money(payroll_net))
             + "</div>")

    def tile(mod, t, s):
        return f"<a class='hr-tile' href='{url_for('modules.module', mod=mod)}'><div class='t'>{t}</div><div class='s'>{s}</div></a>"
    tiles = ("<div class='hr-tiles'>"
             + tile('attendance', '🗓 Attendance', f'{present}/{headcount} present · {unmarked} unmarked')
             + tile('leave', '🌴 Leave', f'{len(pending_leave)} pending')
             + tile('payroll', '💵 Payroll', f'Net {money(payroll_net)} · Gross {money(payroll_gross)}')
             + tile('employees', '👥 Employees', f'{headcount} active')
             + "</div>")

    # pending leave requests (actionable)
    lrows = ''
    for l in pending_leave[:8]:
        lrows += (f"<tr><td><b>{h(l.employee.name if l.employee else '—')}</b></td><td>{h(l.type)}</td>"
                  f"<td>{h(l.start)} → {h(l.end)}</td>"
                  f"<td style='text-align:right;white-space:nowrap'><a class='btn sm ok' href='{url_for('hr.leave_act', lid=l.id, act='Approved')}'>Approve</a> "
                  f"<a class='btn sm' href='{url_for('hr.leave_act', lid=l.id, act='Rejected')}'>Reject</a></td></tr>")
    if not lrows:
        lrows = "<tr><td colspan='4' style='color:var(--muted);padding:16px'>No pending leave requests.</td></tr>"
    leave_panel = (f"<div class='panel'><div class='ph'><h2>Pending Leave Requests</h2>"
                   f"<span class='so'>{len(pending_leave)} waiting</span><div class='sp'></div>"
                   f"<a class='btn sm' href='{url_for('hr.leave_new')}'>+ New Request</a></div>"
                   f"<div class='tw'><table><thead><tr><th>Employee</th><th>Type</th><th>Period</th><th></th></tr></thead>"
                   f"<tbody>{lrows}</tbody></table></div></div>")

    return page('Human Resources', CSS + stats + tiles + leave_panel, 'hr',
                crumbs=[('Human Resources', None)])
