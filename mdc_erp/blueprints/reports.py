"""Reports: overview, summary, revenue analysis, radiologist fees, CSV export."""
import io
import datetime as dt
from flask import (Blueprint, request, url_for, Response,
                   abort)
from markupsafe import escape as h
from ..models import *
from ..core.security import (login_required, setting)
from ..core.helpers import money, today, cur_year
from ..core.ui import page
from ..core.posting import (live_invoices)

bp = Blueprint('reports', __name__)

def radfees_view():
    fee = float(setting('rad_fee', '10') or 10)
    reported = list(RadOrder.query.filter_by(status='Reported').all())
    from collections import defaultdict
    byr = defaultdict(lambda: [0, 0.0])
    for o in reported:
        name = o.radiologist or o.reported_by or '—'
        byr[name][0] += 1; byr[name][1] += (o.fee or fee)
    rows = ''.join(f"<tr><td><b>{h(n)}</b></td><td class='num'>{c}</td><td class='num'>{money(t)}</td></tr>"
                   for n, (c, t) in sorted(byr.items(), key=lambda x: -x[1][1])) \
           or "<tr><td colspan='3' style='color:var(--muted);padding:16px'>No reports written yet.</td></tr>"
    total = sum(t for _, t in byr.values()); tcount = sum(c for c, _ in byr.values())
    detail = ''.join(f"<tr><td>{h(o.date)}</td><td>{h(o.patient.name if o.patient else '—')}</td>"
                     f"<td>{h(o.modality)} · {h(o.service.name if o.service else '')}</td>"
                     f"<td>{h(o.radiologist or o.reported_by or '—')}</td><td class='num'>{money(o.fee or fee)}</td></tr>"
                     for o in sorted(reported, key=lambda x: (x.date or ''), reverse=True))
    body = (f"<div class='panel'><div class='ph'><h2>Radiologist / Report Reader Fees</h2>"
            f"<span class='so'>Fee per report: {money(fee)} · set in Settings</span><div class='sp'></div>"
            f"<button class='btn sm' onclick=\"MDCDoc.openSelf('Radiologist Fees','"+"/radfees/pdf"+"')\">Print</button></div>"
            f"<div class='tw'><table><thead><tr><th>Radiologist</th><th class='num'>Reports</th><th class='num'>Total Fee</th></tr></thead>"
            f"<tbody>{rows}</tbody><tfoot><tr style='font-weight:700;background:#F0F4F5'><td>TOTAL</td>"
            f"<td class='num'>{tcount}</td><td class='num'>{money(total)}</td></tr></tfoot></table></div></div>"
            f"<div class='panel'><div class='ph'><h2>Reported Studies</h2></div><div class='tw'><table>"
            f"<thead><tr><th>Date</th><th>Patient</th><th>Study</th><th>Radiologist</th><th class='num'>Fee</th></tr></thead>"
            f"<tbody>{detail}</tbody></table></div></div>")
    return page('Radiologist Fees', body, 'radfees')

def summary_view():
    f = request.args.get('from', ''); t = request.args.get('to', '')
    br = request.args.get('branch','')
    def inrange(d):
        d = d or ''
        if f and d < f: return False
        if t and d > t: return False
        return True
    invs = [i for i in live_invoices() if inrange(i.date) and (not br or str(i.branch_id or '')==br)]
    purs = [p for p in Purchase.query.all() if inrange(p.date)]
    exps = [e for e in Expense.query.all() if inrange(e.date) and (not br or str(e.branch_id or '')==br)]
    billed = sum(i.total for i in invs); paid = sum(i.paid or 0 for i in invs); bal = billed - paid
    purtot = sum(p.total for p in purs); exptot = sum(e.amount for e in exps)
    from collections import defaultdict
    pp = defaultdict(lambda: [0, 0.0, 0.0])
    for i in invs:
        nm = i.patient.name if i.patient else 'Walk-in'
        pp[nm][0] += 1; pp[nm][1] += i.total; pp[nm][2] += (i.paid or 0)
    prow = ''.join(f"<tr><td>{h(n)}</td><td class='num'>{c}</td><td class='num'>{money(b)}</td>"
                   f"<td class='num'>{money(pd)}</td><td class='num'>{money(b-pd)}</td></tr>"
                   for n, (c, b, pd) in sorted(pp.items(), key=lambda x: -x[1][1])[:100]) \
           or "<tr><td colspan='5' style='color:var(--muted);padding:14px'>No invoices in range.</td></tr>"
    pv = defaultdict(lambda: [0, 0.0, 0.0])
    for p in purs:
        nm = (p.supplier.name if getattr(p, 'supplier', None) else (p.item or 'Vendor'))
        pv[nm][0] += 1; pv[nm][1] += p.total; pv[nm][2] += (getattr(p, 'paid', 0) or 0)
    vrow = ''.join(f"<tr><td>{h(n)}</td><td class='num'>{c}</td><td class='num'>{money(b)}</td>"
                   f"<td class='num'>{money(pd)}</td><td class='num'>{money(b-pd)}</td></tr>"
                   for n, (c, b, pd) in sorted(pv.items(), key=lambda x: -x[1][1])[:100]) \
           or "<tr><td colspan='5' style='color:var(--muted);padding:14px'>No vendor bills in range.</td></tr>"
    kpis = ("<div class='kpis'>"
            f"<div class='kpi' style='--ac:var(--teal)'><div class='l'>Patient Billed</div><div class='v'>{money(billed)}</div><div class='s'>{len(invs)} invoices</div></div>"
            f"<div class='kpi' style='--ac:var(--green)'><div class='l'>Collected</div><div class='v'>{money(paid)}</div><div class='s'>Balance {money(bal)}</div></div>"
            f"<div class='kpi' style='--ac:#E4572E'><div class='l'>Vendor Bills</div><div class='v'>{money(purtot)}</div><div class='s'>{len(purs)} bills</div></div>"
            f"<div class='kpi' style='--ac:var(--amber)'><div class='l'>Expenses</div><div class='v'>{money(exptot)}</div><div class='s'>{len(exps)} entries</div></div></div>")
    filt = (f"<div class='panel'><div class='pad'><form method='get' style='display:flex;gap:10px;align-items:end;flex-wrap:wrap'>"
            f"<div class='fld' style='margin:0'><label>From date</label><input type='date' name='from' value='{h(f)}'></div>"
            f"<div class='fld' style='margin:0'><label>To date</label><input type='date' name='to' value='{h(t)}'></div>"
            f"<div class='fld' style='margin:0'><label>Branch</label><select name='branch'><option value=''>— All branches —</option>{''.join(chr(60)+chr(111)+'ption value='+chr(39)+str(b.id)+chr(39)+(' selected' if br==str(b.id) else '')+chr(62)+h(b.name)+chr(60)+'/option'+chr(62) for b in Branch.query.filter_by(active=True).all())}</select></div>"
            f"<button class='btn primary'>Apply</button><button class='btn' type='button' onclick=\"MDCDoc.openSelf('Revenue Analysis','{url_for('reports.summary_pdf')}?from={h(f)}&to={h(t)}')\">Print</button><a class='btn' href='/export/invoices?from={h(f)}&to={h(t)}'>⬇ Excel/CSV</a></form></div></div>")
    body = (filt + kpis
            + f"<div class='panel'><div class='ph'><h2>Patient Invoice Summary</h2><span class='so'>{h(f) or '…'} → {h(t) or '…'}</span></div>"
            + f"<div class='tw'><table><thead><tr><th>Patient</th><th class='num'>Invoices</th><th class='num'>Billed</th><th class='num'>Paid</th><th class='num'>Balance</th></tr></thead><tbody>{prow}</tbody></table></div></div>"
            + f"<div class='panel'><div class='ph'><h2>Vendor Bill Summary</h2></div>"
            + f"<div class='tw'><table><thead><tr><th>Vendor / Item</th><th class='num'>Bills</th><th class='num'>Total</th><th class='num'>Paid</th><th class='num'>Balance</th></tr></thead><tbody>{vrow}</tbody></table></div></div>")
    return page('Summary Report', body, 'summary')


def revenue_view():
    f = request.args.get('from', dt.date.today().replace(day=1).isoformat())
    t = request.args.get('to', dt.date.today().isoformat())
    def inr(d):
        d = d or ''
        return (not f or d >= f) and (not t or d <= t)
    invs = [i for i in live_invoices() if inr(i.date)]
    from collections import defaultdict
    daily = defaultdict(lambda: [0, 0.0, 0.0])
    by_dep = defaultdict(float); by_svc = defaultdict(lambda: [0, 0.0]); by_doc = defaultdict(lambda: [0, 0.0, 0.0])
    for i in invs:
        daily[i.date or '—'][0] += 1; daily[i.date or '—'][1] += i.total; daily[i.date or '—'][2] += (i.paid or 0)
        for it in i.items:
            dep = (it.service.department if it.service else 'Other') or 'Other'
            by_dep[dep] += it.qty * it.price
            by_svc[it.desc][0] += int(it.qty); by_svc[it.desc][1] += it.qty * it.price
        if i.referring_doctor_id and i.doctor_ref:
            by_doc[i.doctor_ref.name][0] += 1; by_doc[i.doctor_ref.name][1] += i.total; by_doc[i.doctor_ref.name][2] += i.commission
    tot = sum(i.total for i in invs); col = sum(i.paid or 0 for i in invs)
    drows = ''.join(f"<tr><td>{h(d)}</td><td class='num'>{c}</td><td class='num'>{money(b)}</td><td class='num'>{money(p)}</td><td class='num'>{money(b-p)}</td></tr>"
                    for d, (c, b, p) in sorted(daily.items(), reverse=True)) or "<tr><td colspan='5' style='color:var(--muted);padding:14px'>No invoices in range.</td></tr>"
    total_dep = sum(by_dep.values()) or 1
    deprows = ''.join(f"<tr><td>{h(d)}</td><td class='num'>{money(v)}</td><td class='num'>{v/total_dep*100:.1f}%</td>"
                      f"<td><div style='background:var(--line);border-radius:4px;height:8px'><div style='background:var(--amber);width:{v/total_dep*100:.0f}%;height:8px;border-radius:4px'></div></div></td></tr>"
                      for d, v in sorted(by_dep.items(), key=lambda x: -x[1])) or "<tr><td colspan='4' style='color:var(--muted);padding:14px'>No data.</td></tr>"
    srows = ''.join(f"<tr><td>{h(s)}</td><td class='num'>{c}</td><td class='num'>{money(v)}</td></tr>"
                    for s, (c, v) in sorted(by_svc.items(), key=lambda x: -x[1][1])[:40]) or "<tr><td colspan='3' style='color:var(--muted);padding:14px'>No data.</td></tr>"
    docrows = ''.join(f"<tr><td>{h(n)}</td><td class='num'>{c}</td><td class='num'>{money(v)}</td><td class='num'>{money(cm)}</td></tr>"
                      for n, (c, v, cm) in sorted(by_doc.items(), key=lambda x: -x[1][1])) or "<tr><td colspan='4' style='color:var(--muted);padding:14px'>No referred invoices.</td></tr>"
    kpis = ("<div class='kpis'>"
            f"<div class='kpi' style='--ac:var(--teal)'><div class='l'>Revenue (billed)</div><div class='v'>{money(tot)}</div><div class='s'>{len(invs)} invoices</div></div>"
            f"<div class='kpi' style='--ac:var(--green)'><div class='l'>Collected</div><div class='v'>{money(col)}</div><div class='s'>{(col/tot*100 if tot else 0):.0f}% of billed</div></div>"
            f"<div class='kpi' style='--ac:#E4572E'><div class='l'>Outstanding</div><div class='v'>{money(tot-col)}</div><div class='s'>Balance due</div></div></div>")
    filt = (f"<div class='panel'><div class='pad'><form method='get' style='display:flex;gap:10px;align-items:end;flex-wrap:wrap'>"
            f"<div class='fld' style='margin:0'><label>From</label><input type='date' name='from' value='{h(f)}'></div>"
            f"<div class='fld' style='margin:0'><label>To</label><input type='date' name='to' value='{h(t)}'></div>"
            f"<button class='btn primary'>Apply</button><button class='btn' type='button' onclick=\"MDCDoc.openSelf('Revenue Analysis','{url_for('reports.summary_pdf')}?from={h(f)}&to={h(t)}')\">Print</button>"
            f"<a class='btn' href='/export/invoices?from={h(f)}&to={h(t)}'>⬇ Excel/CSV</a></form></div></div>")
    body = (filt + kpis + "<div class='grid2'>"
            + f"<div class='panel' style='grid-column:1/-1'><div class='ph'><h2>Daily Revenue</h2><span class='so'>{h(f)} → {h(t)}</span></div><div class='tw'><table><thead><tr><th>Date</th><th class='num'>Invoices</th><th class='num'>Billed</th><th class='num'>Collected</th><th class='num'>Balance</th></tr></thead><tbody>{drows}</tbody></table></div></div>"
            + f"<div class='panel'><div class='ph'><h2>Revenue by Department</h2></div><div class='tw'><table><thead><tr><th>Department</th><th class='num'>Revenue</th><th class='num'>%</th><th style='width:130px'></th></tr></thead><tbody>{deprows}</tbody></table></div></div>"
            + f"<div class='panel'><div class='ph'><h2>Revenue by Doctor (referrals)</h2></div><div class='tw'><table><thead><tr><th>Doctor</th><th class='num'>Invoices</th><th class='num'>Revenue</th><th class='num'>Commission</th></tr></thead><tbody>{docrows}</tbody></table></div></div>"
            + f"<div class='panel' style='grid-column:1/-1'><div class='ph'><h2>Revenue by Service</h2><span class='so'>Top 40</span></div><div class='tw'><table><thead><tr><th>Service</th><th class='num'>Qty</th><th class='num'>Revenue</th></tr></thead><tbody>{srows}</tbody></table></div></div>"
            + "</div>")
    return page('Revenue Analysis', body, 'revenue')


def reports_view():
    y=cur_year(); d=today()
    inv=Invoice.query.all()
    def rev_range(pred): return sum(i.total for i in inv if pred(i.date or ''))
    rev_today=rev_range(lambda x:x==d)
    rev_month=rev_range(lambda x:x[:7]==d[:7])
    rev_year=rev_range(lambda x:x[:4]==str(y))
    cards="<div class='kpis'>"+\
      f"<div class='kpi' style='--ac:var(--teal)'><div class='l'>Today</div><div class='v'>{money(rev_today)}</div><div class='s'>{d}</div></div>"+\
      f"<div class='kpi' style='--ac:var(--green)'><div class='l'>This Month</div><div class='v'>{money(rev_month)}</div><div class='s'>{d[:7]}</div></div>"+\
      f"<div class='kpi' style='--ac:var(--amber)'><div class='l'>This Year</div><div class='v'>{money(rev_year)}</div><div class='s'>{y}</div></div>"+\
      f"<div class='kpi' style='--ac:var(--blue)'><div class='l'>Patients</div><div class='v'>{Patient.query.count()}</div><div class='s'>Total</div></div></div>"
    # counts
    stats=f"""<div class="panel"><div class="ph"><h2>Activity Summary · {y}</h2></div><div class="pad"><div class="stmt" style="max-width:520px">
      <div class="r"><span>Invoices issued</span><span class="amt">{len([i for i in inv if (i.date or '')[:4]==str(y)])}</span></div>
      <div class="r"><span>Lab tests</span><span class="amt">{LabOrder.query.count()}</span></div>
      <div class="r"><span>Radiology studies</span><span class="amt">{RadOrder.query.count()}</span></div>
      <div class="r"><span>Pharmacy sales</span><span class="amt">{PharmacySale.query.count()}</span></div>
      <div class="r"><span>Appointments</span><span class="amt">{Appointment.query.count()}</span></div>
      <div class="r"><span>Employees</span><span class="amt">{Employee.query.filter_by(active=True).count()}</span></div>
      </div><div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap"><a class="btn" href="{url_for('modules.module',mod='summary')}">📅 Summary (date range) →</a> <a class="btn" href="{url_for('modules.module',mod='radfees')}">🩻 Radiologist Fees →</a> <a class="btn" href="{url_for('modules.module',mod='finance')}">Financial Reports →</a> <button class="btn" onclick="MDCDoc.openSelf()">Print</button></div>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap"><a class="btn sm" href="/export/patients">⬇ Patients (Excel/CSV)</a><a class="btn sm" href="/export/invoices">⬇ Invoices</a><a class="btn sm" href="/export/expenses">⬇ Expenses</a><a class="btn sm" href="/export/ledger">⬇ General Ledger</a></div>
        <p style="margin-top:12px;font-size:12.5px;color:var(--muted)">Patient Portal (bukaanka): la wadaag link-gan → <b>{request.host_url.rstrip('/')}/portal</b> — wuxuu ku galaa MRN + telefoon, wuxuuna arkaa natiijada &amp; invoice-ka.</p></div></div>"""
    return page('Reports', cards+stats, 'reports')


def _csv_response(name, header, rows):
    import csv as _csv
    buf=io.StringIO(); w=_csv.writer(buf)
    w.writerow(header)
    for r in rows: w.writerow(r)
    return Response('\ufeff'+buf.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{name}"'})

@bp.route('/radfees/pdf')
@login_required
def radfees_pdf():
    from flask import redirect
    from ..core.pdfgen import ledger_pdf, available
    fee = float(setting('rad_fee', '10') or 10)
    reported = list(RadOrder.query.filter_by(status='Reported').all())
    rows = [[o.date, (o.patient.name if o.patient else '-'),
             f"{o.modality} - {o.service.name if o.service else ''}",
             (o.radiologist or o.reported_by or '-'), money(o.fee or fee)]
            for o in sorted(reported, key=lambda x: (x.date or ''), reverse=True)]
    cols = [('Date', 'l', 22), ('Patient', 'l', 44), ('Study', 'l', 50),
            ('Radiologist', 'l', 34), ('Fee', 'r', 22)]
    totals = ['TOTAL', '', '', '', money(sum((o.fee or fee) for o in reported))]
    if not available():
        return redirect(url_for('modules.module', mod='radfees'))
    pdf = ledger_pdf('Radiologist / Report Reader Fees', f'Fee per report: {money(fee)}',
                     cols, rows, totals, company=setting('company', 'Modern Diagnostic Center'),
                     currency=setting('currency', '$'))
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + ';filename=Radiologist-Fees.pdf'
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


@bp.route('/summary/pdf')
@login_required
def summary_pdf():
    from flask import redirect
    from ..core.pdfgen import ledger_pdf, available
    from collections import defaultdict
    f = request.args.get('from', ''); t = request.args.get('to', '')
    def inr(d):
        d = d or ''
        return (not f or d >= f) and (not t or d <= t)
    invs = [i for i in live_invoices() if inr(i.date)]
    daily = defaultdict(lambda: [0, 0.0, 0.0])
    for i in invs:
        daily[i.date or '-'][0] += 1; daily[i.date or '-'][1] += i.total; daily[i.date or '-'][2] += (i.paid or 0)
    rows = [[d, str(c), money(b), money(p), money(b - p)]
            for d, (c, b, p) in sorted(daily.items(), reverse=True)]
    tot = sum(i.total for i in invs); col = sum(i.paid or 0 for i in invs)
    cols = [('Date', 'l', 26), ('Invoices', 'r', 22), ('Billed', 'r', 28),
            ('Collected', 'r', 28), ('Balance', 'r', 28)]
    totals = ['TOTAL', str(len(invs)), money(tot), money(col), money(tot - col)]
    if not available():
        return redirect(url_for('modules.module', mod='summary'))
    period = (f'{f or "..."} -> {t or "..."}')
    pdf = ledger_pdf('Revenue Analysis - Daily', period, cols, rows, totals,
                     company=setting('company', 'Modern Diagnostic Center'), currency=setting('currency', '$'))
    disp = ('attachment' if request.args.get('dl') == '1' else 'inline') + ';filename=Revenue-Analysis.pdf'
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': disp})


@bp.route('/export/<what>')
@login_required
def export_csv(what):
    f=request.args.get('from',''); t=request.args.get('to','')
    def inr(d):
        d=d or ''
        if f and d<f: return False
        if t and d>t: return False
        return True
    if what=='patients':
        rows=[(p.mrn,p.name,p.phone or '',p.gender or '',p.gov_id or '',p.address or '') for p in Patient.query.order_by(Patient.id).all()]
        return _csv_response('patients.csv',['MRN','Name','Phone','Gender','Gov ID','Address'],rows)
    if what=='invoices':
        rows=[(f"INV-{i.id:04d}",i.date,(i.patient.name if i.patient else 'Walk-in'),i.subtotal,i.discount or 0,i.vat or 0,i.total,i.paid or 0,i.total-(i.paid or 0),i.status) for i in Invoice.query.order_by(Invoice.id).all() if inr(i.date)]
        return _csv_response('invoices.csv',['Invoice','Date','Patient','Subtotal','Discount','VAT','Total','Paid','Balance','Status'],rows)
    if what=='expenses':
        rows=[(e.date,e.category or '',e.amount or 0,e.paid or 0,getattr(e,'note','') or '') for e in Expense.query.order_by(Expense.id).all() if inr(e.date)]
        return _csv_response('expenses.csv',['Date','Category','Amount','Paid','Note'],rows)
    if what=='ledger':
        out=[]
        for je in JournalEntry.query.order_by(JournalEntry.id).all():
            if not inr(je.date): continue
            for l in je.lines:
                a=Account.query.get(l.account_id)
                out.append((je.date,je.ref or '',(a.code+' '+a.name) if a else '',je.memo or '',l.debit or 0,l.credit or 0))
        return _csv_response('general-ledger.csv',['Date','Ref','Account','Memo','Debit','Credit'],out)
    abort(404)


def branchcmp_view():
    """HQ view: revenue, collections, expenses and net per branch for a year."""
    y = cur_year()
    branches = Branch.query.order_by(Branch.id).all()
    invs = [i for i in live_invoices() if (i.date or '').startswith(str(y))]
    exps = [e for e in Expense.query.all() if (e.date or '').startswith(str(y))]

    def by_branch(bid):
        binv = [i for i in invs if (i.branch_id or (branches[0].id if branches else None)) == bid]
        bexp = [e for e in exps if (getattr(e, 'branch_id', None) or (branches[0].id if branches else None)) == bid]
        rev = sum(i.total for i in binv)
        col = sum(i.paid or 0 for i in binv)
        exp = sum(e.amount or 0 for e in bexp)
        return len(binv), rev, col, exp, rev - exp

    rows = ''
    tot = [0, 0.0, 0.0, 0.0, 0.0]
    maxrev = 1.0
    stats = {}
    for b in branches:
        st = by_branch(b.id)
        stats[b.id] = st
        maxrev = max(maxrev, st[1])
    for b in branches:
        n, rev, col, exp, net = stats[b.id]
        for i, v in enumerate((n, rev, col, exp, net)):
            tot[i] += v
        barw = int(100 * rev / maxrev)
        bar = (f"<div style='background:var(--line);border-radius:6px;height:10px;min-width:120px'>"
               f"<div style='width:{barw}%;background:var(--amber);height:10px;border-radius:6px'></div></div>")
        rows += (f"<tr><td><b>{h(b.code or '')}</b> {h(b.name)}</td><td>{bar}</td>"
                 f"<td class='num'>{n}</td><td class='num'>{money(rev)}</td>"
                 f"<td class='num'>{money(col)}</td><td class='num'>{money(exp)}</td>"
                 f"<td class='num' style='font-weight:700;color:{'var(--green)' if net >= 0 else 'var(--red)'}'>{money(net)}</td></tr>")
    rows += (f"<tr style='border-top:2px solid var(--petrol);font-weight:700'>"
             f"<td>TOTAL (HQ Consolidated)</td><td></td><td class='num'>{tot[0]}</td>"
             f"<td class='num'>{money(tot[1])}</td><td class='num'>{money(tot[2])}</td>"
             f"<td class='num'>{money(tot[3])}</td><td class='num'>{money(tot[4])}</td></tr>")
    yrs = ''.join(f"<a class='btn sm{' primary' if yy == y else ''}' href='?year={yy}'>{yy}</a> "
                  for yy in range(dt.date.today().year - 2, dt.date.today().year + 1))
    body = f"""<div class="panel"><div class="ph"><h2>Branch Comparison · FY {y}</h2>
      <span class="so">Consolidated headquarters view</span><div class="sp"></div>{yrs}</div>
      <div class="tw"><table><thead><tr><th>Branch</th><th>Revenue</th><th class="num">Invoices</th>
      <th class="num">Revenue</th><th class="num">Collected</th><th class="num">Expenses</th><th class="num">Net</th></tr></thead>
      <tbody>{rows}</tbody></table></div>
      <div class="pad" style="color:var(--muted);font-size:12.5px">Invoices/expenses without a branch are counted under the first branch (HQ).
      Assign users to branches in Users so new records are tagged automatically.</div></div>"""
    return page('Branch Comparison', body, 'branchcmp')


def productivity_view():
    """Reports → Productivity: doctors, technicians, pending work."""
    import datetime as dt
    month = request.args.get('m') or dt.date.today().isoformat()[:7]
    # doctor productivity: consultations this month
    docs = {}
    for c_ in Consultation.query.filter(Consultation.date.like(month + '%')).all():
        d_ = c_.doctor or '—'
        docs[d_] = docs.get(d_, 0) + 1
    # technician productivity: lab results entered / approved this month
    techs = {}
    for o in LabOrder.query.filter(LabOrder.date.like(month + '%')).all():
        if o.result_by:
            t = techs.setdefault(o.result_by, [0, 0]); t[0] += 1
        if o.approved_by:
            t = techs.setdefault(o.approved_by, [0, 0]); t[1] += 1
    pend_lab = LabOrder.query.filter(LabOrder.status.in_(('Requested', 'Collected', 'Received', 'Resulted'))).count()
    pend_rad = RadOrder.query.filter(RadOrder.status != 'Reported').count()
    k = lambda n, v, c='var(--petrol)': (f"<div class='panel' style='flex:1;min-width:150px'><div class='pad'>"
        f"<div style='font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase'>{n}</div>"
        f"<div style='font-family:Space Grotesk;font-weight:700;font-size:26px;color:{c}'>{v}</div></div></div>")
    kpis = f"<div style='display:flex;gap:12px;flex-wrap:wrap'>{k('Pending Lab Reports', pend_lab, 'var(--amber)' if pend_lab else 'var(--green)')}{k('Pending Radiology', pend_rad, 'var(--amber)' if pend_rad else 'var(--green)')}{k('Consultations · ' + month, sum(docs.values()))}</div>"
    drows = ''.join(f"<tr><td><b>{h(d_)}</b></td><td class='num'>{n}</td></tr>"
                    for d_, n in sorted(docs.items(), key=lambda x: -x[1])) or \
            "<tr><td colspan='2' style='color:var(--muted);padding:12px'>No consultations this month.</td></tr>"
    trows = ''.join(f"<tr><td><b>{h(t_)}</b></td><td class='num'>{v[0]}</td><td class='num'>{v[1]}</td></tr>"
                    for t_, v in sorted(techs.items(), key=lambda x: -(x[1][0] + x[1][1]))) or \
            "<tr><td colspan='3' style='color:var(--muted);padding:12px'>No lab activity this month.</td></tr>"
    picker = f"""<div class='panel'><div class='pad'><form method='get' style='display:flex;gap:8px;align-items:center'>
      <label style='font-size:13px;color:var(--muted)'>Month</label>
      <input type='month' name='m' value='{h(month)}' style='border:1px solid var(--line);border-radius:8px;padding:6px 10px'>
      <button class='btn sm'>View</button></form></div></div>"""
    return page('Productivity', kpis + picker + f"""<div class='grid2'>
      <div class='panel'><div class='ph'><h2>Doctor Productivity · {h(month)}</h2></div>
        <div class='tw'><table><thead><tr><th>Doctor</th><th class='num'>Consultations</th></tr></thead><tbody>{drows}</tbody></table></div></div>
      <div class='panel'><div class='ph'><h2>Lab Staff Productivity · {h(month)}</h2></div>
        <div class='tw'><table><thead><tr><th>Staff</th><th class='num'>Results Entered</th><th class='num'>Approved</th></tr></thead><tbody>{trows}</tbody></table></div></div>
      </div>""", 'productivity')


def stockvalue_view():
    """Inventory → Valuation: qty × cost per item."""
    meds = Medicine.query.order_by(Medicine.name).all()
    rows = ''; total = 0.0
    for m in meds:
        v = (m.qty or 0) * (m.cost or 0)
        total += v
        rows += (f"<tr><td><b>{h(m.name)}</b></td><td class='num'>{m.qty or 0:g}</td>"
                 f"<td class='num'>{money(m.cost or 0)}</td><td class='num'><b>{money(v)}</b></td></tr>")
    rows = rows or "<tr><td colspan='4' style='color:var(--muted);padding:14px'>No stock items.</td></tr>"
    head = (f"<div class='panel'><div class='pad' style='display:flex;justify-content:space-between;align-items:center'>"
            f"<div style='font-size:13px;color:var(--muted)'>Valuation basis: unit cost (weighted by current quantity)</div>"
            f"<div><span style='font-size:11px;color:var(--muted);text-transform:uppercase;font-weight:700'>Total Stock Value </span>"
            f"<span style='font-family:Space Grotesk;font-weight:700;font-size:22px;color:var(--petrol)'>{money(total)}</span></div></div></div>")
    return page('Stock Valuation', head + f"""<div class='panel'><div class='ph'><h2>Inventory Valuation</h2></div>
      <div class='tw'><table><thead><tr><th>Item</th><th class='num'>Qty</th><th class='num'>Unit Cost</th><th class='num'>Value</th></tr></thead>
      <tbody>{rows}</tbody></table></div></div>""", 'stockvalue')
