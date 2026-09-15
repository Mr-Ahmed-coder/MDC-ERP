"""Generic CRUD engine: field rendering, form rendering and the module registry."""
import datetime as dt
from markupsafe import escape as h
from ..extensions import db
from ..models import *
from .helpers import money, today

def field_input(f, val=''):
    t = f.get('type','text'); name = f['name']; val = '' if val is None else val
    lab = f['label'] + (' <span style="color:var(--amber-dk)">*</span>' if f.get('required') else '')
    cls = 'fld full' if f.get('full') else 'fld'
    if t == 'select':
        opts = ''.join(f"<option value='{h(v)}'{' selected' if str(v)==str(val) else ''}>{h(lb)}</option>" for v,lb in f['options'])
        inp = f"<select name='{name}'>{opts}</select>"
    elif t == 'datalist':
        opts = ''.join(f"<option value='{h(v)}'>{h(lb)}</option>" for v,lb in f.get('options', []))
        inp = (f"<input name='{name}' list='dl_{name}' value='{h(val)}' autocomplete='off'>"
               f"<datalist id='dl_{name}'>{opts}</datalist>")
    elif t == 'file':
        inp = f"<input name='{name}' type='file' accept='{f.get('accept','image/*')}'{' multiple' if f.get('multiple') else ''}>"
    elif t == 'textarea':
        inp = f"<textarea name='{name}' rows='2'>{h(val)}</textarea>"
    elif t == 'checkbox':
        inp = f"<select name='{name}'><option value='1'{' selected' if val else ''}>Active</option><option value='0'{' selected' if not val else ''}>Inactive</option></select>"
    else:
        step = "step='any'" if t=='number' else ''
        inp = f"<input name='{name}' type='{t}' {step} value='{h(val)}'>"
    return f"<div class='{cls}'><label>{lab}</label>{inp}</div>"

def render_form(title, action, fields, obj=None, back='', enctype=None):
    from flask import render_template
    fields_html = ''.join(field_input(f, getattr(obj, f['name'], f.get('default', '')) if obj else f.get('default', '')) for f in fields)
    return render_template('form_page.html', title=title, action=action,
                           back=back, enctype=enctype, fields_html=fields_html)

# Registry of simple entities
def opt_patients(): return [('', '— none —')] + [(p.id, f"{p.mrn} · {p.name}") for p in Patient.query.order_by(Patient.name).all()]
def opt_services(dep=None):
    q = Service.query.filter_by(active=True)
    if dep:
        # match either the raw department, or services whose workflow routes to this core area
        # (e.g. CT Scan / MRI / X-Ray / Ultrasound all route to Radiology)
        RAD_DEPTS = ('Radiology', 'CT Scan', 'MRI', 'X-Ray', 'Ultrasound', 'ECG',
                     'Echocardiography', 'Mammography')
        LAB_DEPTS = ('Laboratory', 'Lab')
        if dep == 'Radiology':
            from ..models import Service as _S
            q = q.filter(db.or_(_S.department.in_(RAD_DEPTS), _S.workflow == 'Radiology'))
        elif dep in ('Laboratory', 'Lab'):
            from ..models import Service as _S
            q = q.filter(db.or_(_S.department.in_(LAB_DEPTS), _S.workflow == 'Laboratory'))
        else:
            q = q.filter_by(department=dep)
    return [(s.id, f"{s.name} — {money(s.price)}") for s in q.order_by(Service.name).all()]
def opt_suppliers(): return [('', '—')] + [(s.id, s.name) for s in Supplier.query.order_by(Supplier.name).all()]
def opt_employees(): return [(e.id, f"{e.code} · {e.name}") for e in Employee.query.order_by(Employee.name).all()]

REG = {}
def register(key, model, label, columns, fields, order=None, singular=None, enctype=None,
             search=None, filters=None, date_field=None, hide_columns=None):
    REG[key] = dict(model=model, label=label, columns=columns, fields=fields, order=order,
                    singular=singular or label[:-1], enctype=enctype,
                    search=search or [], filters=filters or [], date_field=date_field,
                    hide_columns=hide_columns or {})

register('patients', Patient, 'Patients',
    columns=[('MRN', lambda o:f"<b>{h(o.mrn)}</b>"),('Name',lambda o:f"<a href='/patient/{o.id}' style='color:var(--petrol);font-weight:600'>{h(o.name)}</a>"),
             ('Age',lambda o:(f"{o.age} yr" if o.age is not None else '—')),('Phone',lambda o:h(o.phone or '—')),
             ('Gender',lambda o:h(o.gender or '—')),('Blood',lambda o:(pill(o.blood_group,'red') if o.blood_group else '—')),
             ('Status',lambda o:pill('Active' if o.active in (True,None) else 'Inactive', 'green' if o.active in (True,None) else 'grey')),
             ('Card',lambda o:f"<a class='btn gh sm' href='/patient/{o.id}/card' target='_blank'>🪪 Card</a>")],
    fields=[dict(name='name',label='Full Name',required=True),dict(name='phone',label='Phone'),
            dict(name='phone2',label='Alternative Phone'),
            dict(name='gender',label='Gender',type='select',options=[('','—'),('Male','Male'),('Female','Female')]),
            dict(name='dob',label='Date of Birth (age auto-calculated)',type='date'),
            dict(name='age_years',label='Age (years) — use if date of birth is unknown',type='number'),
            dict(name='blood_group',label='Blood Group',type='select',options=[('','—')]+[(b,b) for b in ('A+','A-','B+','B-','AB+','AB-','O+','O-')]),
            dict(name='marital',label='Marital Status',type='select',options=[('','—'),('Single','Single'),('Married','Married'),('Widowed','Widowed'),('Divorced','Divorced')]),
            dict(name='occupation',label='Occupation'),
            dict(name='gov_id',label='National ID / Passport'),dict(name='address',label='Address'),
            dict(name='emerg_name',label='Emergency Contact'),dict(name='emerg_phone',label='Emergency Phone'),
            dict(name='ins_company',label='Insurance Company'),dict(name='ins_number',label='Insurance Number'),
            dict(name='allergies',label='Allergies',type='textarea',full=True),
            dict(name='med_history',label='Medical History',type='textarea',full=True),
            dict(name='photo',label='Patient Photo',type='file',accept='image/*'),
            dict(name='active',label='Patient Status',type='select',options=[('1','Active'),('','Inactive')],as_bool=True),
            dict(name='notes',label='Notes',type='textarea',full=True)],
    enctype='multipart/form-data',
    order=lambda: Patient.query.order_by(Patient.id.desc()),
    search=['name', 'phone', 'mrn', 'gov_id'],
    filters=[dict(name='gender', attr='gender', label='All Genders',
                  options=[('Male', 'Male'), ('Female', 'Female')]),
             dict(name='blood', attr='blood_group', label='All Blood Groups',
                  options=[(b, b) for b in ('A+','A-','B+','B-','AB+','AB-','O+','O-')])])

register('appointments', Appointment, 'Appointments',
    columns=[('Date',lambda o:h(o.date)),('Time',lambda o:h(o.time or '—')),('Patient',lambda o:h(o.patient.name if o.patient else '—')),
             ('Department',lambda o:h(o.department or '—')),('Doctor',lambda o:h(o.doctor or '—')),
             ('Type',lambda o:pill(getattr(o,'visit_type',None) or 'New', 'red' if getattr(o,'visit_type','')=='Emergency' else 'grey')),
             ('Priority',lambda o:(pill('Urgent','red') if getattr(o,'priority','')=='Urgent' else '—')),
             ('Status',lambda o:pill(o.status,{'Scheduled':'blue','Confirmed':'teal','Waiting':'amber','In Progress':'amber','Done':'green','Cancelled':'red','No Show':'red'})),
             ('Remind',lambda o:(f"<a class='btn gh sm' href='/appt/{o.id}/remind'>📱 SMS</a>" if o.status in ('Scheduled','Confirmed') and o.patient and o.patient.phone else '—'))],
    fields=[dict(name='patient_id',label='Patient',type='select',options_fn=opt_patients,required=True),
            dict(name='date',label='Date',type='date',required=True,default=today()),dict(name='time',label='Time',type='time'),
            dict(name='department',label='Department',type='select',options=[('Consultation','Consultation'),('Laboratory','Laboratory'),('Radiology','Radiology'),('Pharmacy','Pharmacy')]),
            dict(name='doctor',label='Doctor'),
            dict(name='service_id',label='Service',type='select',options_fn=lambda:[('','—')]+opt_services()),
            dict(name='visit_type',label='Visit Type',type='select',options=[('New','New'),('Follow-up','Follow-up'),('Emergency','Emergency')]),
            dict(name='priority',label='Priority',type='select',options=[('Normal','Normal'),('Urgent','Urgent')]),
            dict(name='status',label='Status',type='select',options=[(x,x) for x in ('Scheduled','Confirmed','Waiting','In Progress','Done','Cancelled','No Show')]),
            dict(name='notes',label='Notes',type='textarea',full=True)],
    order=lambda: Appointment.query.order_by(Appointment.date.desc(), Appointment.id.desc()))

register('services', Service, 'Service Catalog',
    columns=[('Code',lambda o:f"<b>{h(o.code)}</b>"),('Name',lambda o:h(o.name)),('Department',lambda o:pill(o.department or '—','grey')),
             ('Price',lambda o:money(o.price),'num'),('Cost',lambda o:money(o.cost),'num'),
             ('Status',lambda o:pill('Active','green') if o.active else pill('Off','grey'))],
    fields=[dict(name='code',label='Code',required=True),dict(name='name',label='Name',required=True),
            dict(name='department',label='Department',type='select',options=[('Consultation','Consultation'),('Laboratory','Laboratory'),('Radiology','Radiology'),('Other','Other')]),
            dict(name='price',label='Cash Price',type='number'),
            dict(name='price_insurance',label='Insurance Price (0 = use Cash)',type='number'),
            dict(name='price_corporate',label='Corporate Price (0 = use Cash)',type='number'),
            dict(name='price_vip',label='VIP Price (0 = use Cash)',type='number'),
            dict(name='price_contract',label='Contract Price (0 = use Cash)',type='number'),
            dict(name='cost',label='Direct Cost',type='number'),
            dict(name='ref_range',label='Reference Range (lab only, e.g. 4.0 – 11.0)'),
            dict(name='unit',label='Unit (lab only, e.g. x10⁹/L, mg/dL)'),
            dict(name='supply_id',label='Supply item used (auto-deduct from stock)',type='select',options_fn=lambda:[('','— none —')]+[(m.id,m.name) for m in Medicine.query.order_by(Medicine.name).all()]),
            dict(name='supply_qty',label='Qty used per service (e.g. 1 film, 1 kit)',type='number'),
            dict(name='active',label='Status',type='checkbox',default=True)],
    order=lambda: Service.query.order_by(Service.department, Service.code),
    hide_columns={'Price': ['lab_tech', 'lab_supervisor'], 'Cost': ['lab_tech', 'lab_supervisor']})

register('suppliers', Supplier, 'Suppliers',
    columns=[('Name',lambda o:f"<b>{h(o.name)}</b>"),('Phone',lambda o:h(o.phone or '—')),('Address',lambda o:h(o.address or '—')),('Statement',lambda o:f"<a class='btn gh sm' href='/supplier/{o.id}/statement' target='_blank'>Statement</a>")],
    fields=[dict(name='name',label='Vendor Name',required=True),
            dict(name='category',label='Category',type='select',options=[(c,c) for c in
                ['Medical Equipment Supplier','Laboratory Supplier','Pharmacy Supplier','Electricity Company',
                 'Water Company','Internet Provider','Fuel Supplier','Cleaning Company','Security Company',
                 'Maintenance Company','Construction Company','Government','Other']]),
            dict(name='contact_person',label='Contact Person'),dict(name='phone',label='Phone'),
            dict(name='email',label='Email'),dict(name='tax_no',label='Tax Number'),
            dict(name='bank_details',label='Bank Details',full=True),
            dict(name='address',label='Address',full=True)],
    order=lambda: Supplier.query.order_by(Supplier.name),
    search=['name','phone','address','contact_person','email','category'],
    filters=[dict(name='vcat', attr='category', label='All Categories',
                  options=[(c,c) for c in ['Medical Equipment Supplier','Laboratory Supplier','Pharmacy Supplier',
                                           'Electricity Company','Water Company','Internet Provider','Fuel Supplier',
                                           'Cleaning Company','Security Company','Maintenance Company','Other']])])

register('inventory', Medicine, 'Supplies',
    columns=[('Name',lambda o:f"<b>{h(o.name)}</b>"),('Batch',lambda o:h(o.batch or '—')),('Expiry',lambda o:expiry_pill(o.expiry)),
             ('Stock',lambda o:stock_pill(o),'num'),('Unit Cost',lambda o:money(o.cost),'num')],
    fields=[dict(name='name',label='Supply Item (reagent, film, contrast...)',required=True),dict(name='batch',label='Batch Number'),
            dict(name='expiry',label='Expiry Date',type='date'),dict(name='qty',label='Quantity in Stock',type='number'),
            dict(name='reorder',label='Reorder Level',type='number',default=10),dict(name='price',label='Selling Price',type='number'),
            dict(name='cost',label='Unit Cost',type='number')],
    order=lambda: Medicine.query.order_by(Medicine.name), singular='Supply Item')

register('doctors', Doctor, 'Referring Doctors',
    columns=[('Code',lambda o:f"<b>{h(o.code or '—')}</b>"),('Name',lambda o:f"<b>{h(o.name)}</b>"),('Specialty',lambda o:h(o.specialty or '—')),('Phone',lambda o:h(o.phone or '—')),
             ('Commission',lambda o:pill(o.commission_type,'teal')),('Rate',lambda o:(money(o.fixed_rate) if o.commission_type=='Fixed' else f"{(o.percent_rate or 0)*100:g}%"),'num')],
    fields=[dict(name='code',label='Doctor Code / Number (you assign, e.g. DR-001)'),dict(name='name',label='Doctor Name',required=True),dict(name='specialty',label='Specialty'),dict(name='phone',label='Phone'),
            dict(name='commission_type',label='Commission Type',type='select',options=[('Percent','Percent (% of revenue)'),('Fixed','Fixed (per referral)')]),
            dict(name='fixed_rate',label='Fixed Rate (per referral)',type='number'),
            dict(name='percent_rate',label='Percent Rate (0.15 = 15%)',type='number'),
            dict(name='active',label='Status',type='checkbox',default=True),
            dict(name='portal_user',label='Portal Username (doctor referral portal /dr)'),
            dict(name='portal_pw_set',label='Set Portal Password (blank = keep current)')],
    order=lambda: Doctor.query.order_by(Doctor.name), singular='Referring Doctor',
    search=['code','name','specialty','phone'])

register('branches', Branch, 'Branches',
    columns=[('Code',lambda o:f"<b>{h(o.code or '')}</b>"),('Branch Name',lambda o:h(o.name)),('Address',lambda o:h(o.address or '—')),
             ('Phone',lambda o:h(o.phone or '—')),('Status',lambda o:pill('Active','green') if o.active else pill('Off','grey'))],
    fields=[dict(name='code',label='Code',required=True),dict(name='name',label='Branch Name',required=True),
            dict(name='address',label='Address'),dict(name='phone',label='Phone'),
            dict(name='active',label='Status',type='checkbox',default=True)],
    order=lambda: Branch.query.order_by(Branch.id), singular='Branch')

register('consult', Consultation, 'Consultations',
    columns=[('Date',lambda o:h(o.date)),('Patient',lambda o:f"<a href='/patient/{o.patient_id}' style='color:var(--petrol);font-weight:600'>{h(o.patient.name if o.patient else '—')}</a>"),
             ('Doctor',lambda o:h(o.doctor or '—')),('Complaint',lambda o:h((o.complaint or '—')[:40])),
             ('ICD-10',lambda o:(pill(o.icd_code,'blue') if getattr(o,'icd_code',None) else '—')),
             ('Diagnosis',lambda o:h((o.diagnosis or '—')[:40])),
             ('Status',lambda o:pill(getattr(o,'status',None) or 'Open','green' if getattr(o,'status','')=='Completed' else 'amber')),
             ('Actions',lambda o:(f"<span style='display:flex;gap:4px;flex-wrap:wrap'>"
                                  f"<a class='btn gh sm' href='/lab/new?patient={o.patient_id}'>🧪 Lab</a>"
                                  f"<a class='btn gh sm' href='/rad/new?patient={o.patient_id}'>📷 Rad</a>"
                                  f"<a class='btn gh sm' href='/m/prescriptions/new?patient_id={o.patient_id}'>💊 Rx</a>"
                                  f"<a class='btn gh sm' href='/invoice/new?patient={o.patient_id}'>🧾 Bill</a></span>"))],
    fields=[dict(name='patient_id',label='Patient',type='select',options_fn=opt_patients),
            dict(name='date',label='Date',type='date',default=today()),
            dict(name='doctor',label='Doctor'),
            dict(name='complaint',label='Complaint / Symptoms',type='textarea',full=True),
            dict(name='icd_code',label='ICD-10 Diagnosis Code (type or pick)',type='datalist',
                 options_fn=lambda: __import__('mdc_erp.core.icd10',fromlist=['icd10_datalist_options']).icd10_datalist_options()),
            dict(name='bp',label='BP (e.g. 120/80)'),dict(name='temp_c',label='Temp °C',type='number',step='any'),
            dict(name='pulse',label='Pulse /min',type='number'),dict(name='spo2',label='SpO2 %',type='number'),
            dict(name='weight_kg',label='Weight kg',type='number',step='any'),dict(name='height_cm',label='Height cm',type='number',step='any'),
            dict(name='diagnosis',label='Diagnosis (clinical text)',type='textarea',full=True),
            dict(name='notes',label='Clinical Notes',type='textarea',full=True),
            dict(name='followup_date',label='Follow-up Visit Date (auto-books appointment)',type='date'),
            dict(name='status',label='Status',type='select',options=[('Open','Open'),('Completed','Completed')]),
            dict(name='service_id',label='Billable Consultation Fee (optional — auto-added to next invoice)',
                 type='select',options_fn=lambda: [('','— not billable —')]+opt_services('Consultation'))],
    order=lambda: Consultation.query.order_by(Consultation.id.desc()), singular='Consultation')

def _qc_pill(o):
    z=abs(o.z)
    if z<=2: return pill(f'In control · z={o.z:+.1f}','green')
    if z<=3: return pill(f'Warning · z={o.z:+.1f}','amber')
    return pill(f'OUT · z={o.z:+.1f}','red')

register('labqc', QCRecord, 'Lab QC (Internal Quality Control)',
    columns=[('Date',lambda o:h(o.date)),('Test',lambda o:h(o.service.name if o.service else '—')),
             ('Level',lambda o:h(o.level)),('Value',lambda o:f"{o.value:g}"),
             ('Target',lambda o:f"{o.target_mean:g} ± {o.target_sd:g}"),
             ('Status',_qc_pill),('Operator',lambda o:h(o.operator or '—'))],
    fields=[dict(name='date',label='Date',type='date',required=True,default=today()),
            dict(name='service_id',label='Test',type='select',options_fn=lambda:opt_services('Laboratory'),required=True),
            dict(name='level',label='Control Level',type='select',options=[('L1','L1 (normal)'),('L2','L2 (abnormal)')]),
            dict(name='value',label='Measured Value',type='number',step='any',required=True),
            dict(name='target_mean',label='Target Mean',type='number',step='any',required=True),
            dict(name='target_sd',label='Target SD',type='number',step='any',required=True),
            dict(name='operator',label='Operator')],
    order=lambda: QCRecord.query.order_by(QCRecord.id.desc()), singular='QC Run')

def med_opts(): return [(m.id, f"{m.name} — {money(m.price)} (stock {m.qty or 0})") for m in Medicine.query.order_by(Medicine.name).all()]

register('prescriptions', Prescription, 'Prescriptions',
    columns=[('Date',lambda o:h(o.date)),('Patient',lambda o:h(o.patient.name if o.patient else '—')),
             ('Medicine',lambda o:h(o.medicine.name if o.medicine else '—')),('Qty',lambda o:f"{o.qty:g}",'num'),
             ('Dosage',lambda o:h(o.dosage or '—')),('Doctor',lambda o:h(o.doctor or '—')),
             ('Status',lambda o:pill(o.status,{'Pending':'amber','Dispensed':'green'}))],
    fields=[dict(name='patient_id',label='Patient',type='select',options_fn=opt_patients),
            dict(name='medicine_id',label='Medicine',type='select',options_fn=med_opts),
            dict(name='qty',label='Quantity',type='number',default=1),
            dict(name='dosage',label='Dosage / Instructions (e.g. 1x3 for 5 days)'),
            dict(name='doctor',label='Prescribing Doctor'),
            dict(name='date',label='Date',type='date',default=today())],
    order=lambda: Prescription.query.order_by(Prescription.id.desc()), singular='Prescription')

def emp_opts(): return [(e.id, f"{e.code} · {e.name}") for e in Employee.query.filter_by(active=True).order_by(Employee.name).all()]

register('advances', SalaryAdvance, 'Salary Advances',
    columns=[('Date',lambda o:h(o.date)),('Employee',lambda o:h(o.employee.name if o.employee else '—')),
             ('Amount',lambda o:money(o.amount),'num'),('Reason',lambda o:h(o.reason or '—')),
             ('Status',lambda o:pill(o.status,{'Pending':'amber','Approved':'blue','Deducted':'green'}))],
    fields=[dict(name='employee_id',label='Employee',type='select',options_fn=emp_opts),
            dict(name='date',label='Date',type='date',default=today()),
            dict(name='amount',label='Advance Amount',type='number'),
            dict(name='reason',label='Reason'),
            dict(name='status',label='Status',type='select',options=[('Pending','Pending'),('Approved','Approved'),('Deducted','Deducted from salary')])],
    order=lambda: SalaryAdvance.query.order_by(SalaryAdvance.id.desc()), singular='Salary Advance')

register('loans', EmpLoan, 'Employee Loans',
    columns=[('Date',lambda o:h(o.date)),('Employee',lambda o:h(o.employee.name if o.employee else '—')),
             ('Amount',lambda o:money(o.amount),'num'),('Repaid',lambda o:money(o.paid),'num'),
             ('Balance',lambda o:money(o.balance),'num'),('Status',lambda o:pill(o.status,{'Active':'amber','Cleared':'green'}))],
    fields=[dict(name='employee_id',label='Employee',type='select',options_fn=emp_opts),
            dict(name='date',label='Date',type='date',default=today()),
            dict(name='amount',label='Loan Amount',type='number'),
            dict(name='paid',label='Amount Repaid',type='number'),
            dict(name='installment',label='Monthly Installment',type='number'),
            dict(name='status',label='Status',type='select',options=[('Active','Active'),('Cleared','Cleared')]),
            dict(name='notes',label='Notes',type='textarea',full=True)],
    order=lambda: EmpLoan.query.order_by(EmpLoan.id.desc()), singular='Employee Loan')

register('logistics', Logistic, 'Logistics',
    columns=[('Date',lambda o:h(o.date)),('Type',lambda o:pill(o.type or '—','teal')),('Reference',lambda o:h(o.ref or '—')),
             ('Route',lambda o:h((o.origin or '—')+' → '+(o.destination or '—'))),('Driver',lambda o:h(o.driver or '—')),
             ('Status',lambda o:pill(o.status,{'Pending':'amber','In Transit':'blue','Delivered':'green'}))],
    fields=[dict(name='date',label='Date',type='date',default=today()),
            dict(name='type',label='Type',type='select',options=[(t,t) for t in ['Sample Transport','Result Delivery','Supply Pickup','Equipment','Other']]),
            dict(name='ref',label='Reference / Item'),
            dict(name='origin',label='From'),dict(name='destination',label='To'),
            dict(name='driver',label='Driver / Courier'),
            dict(name='status',label='Status',type='select',options=[('Pending','Pending'),('In Transit','In Transit'),('Delivered','Delivered')]),
            dict(name='notes',label='Notes',type='textarea',full=True)],
    order=lambda: Logistic.query.order_by(Logistic.id.desc()), singular='Logistic Entry')

register('expenses', Expense, 'Expenses',
    columns=[('Date',lambda o:h(o.date)),('Vendor',lambda o:h(o.supplier.name if o.supplier else '—')),
             ('Category',lambda o:pill(o.category or '—','grey')),('Method',lambda o:h(o.pay_method or 'Cash')),
             ('Note',lambda o:h(o.note or '—')),('Amount',lambda o:money(o.amount),'num'),('Paid',lambda o:money(o.paid),'num')],
    fields=[dict(name='date',label='Date',type='date',required=True,default=today()),
            dict(name='cost_center_id',label='Cost Center',type='select',options_fn=lambda:[('','— none —')]+[(c.id,f'{c.code} · {c.name}') for c in CostCenter.query.filter_by(active=True).order_by(CostCenter.code).all()]),
            dict(name='supplier_id',label='Vendor',type='select',options_fn=lambda:[('','— none —')]+[(sp.id,sp.name) for sp in Supplier.query.order_by(Supplier.name).all()]),
            dict(name='category',label='Category',type='select',options=[(c,c) for c in
                ['Electricity','Water','Fuel','Diesel','Generator','Internet','Telephone','Rent','Maintenance',
                 'Vehicle','Cleaning','Stationery','Medical Supplies','Office Supplies','Equipment Repair',
                 'Staff Welfare','Security','Marketing','Training','Utilities','Professional Fees','Insurance','Other']]),
            dict(name='pay_method',label='Payment Method',type='select',options=[(m,m) for m in ['Cash','Sahal','EVC','E. Dahab','MyCash','Premier Wallet','Bank','Cheque','Credit']]),
            dict(name='amount',label='Amount',type='number',required=True),dict(name='paid',label='Amount Paid',type='number'),
            dict(name='note',label='Description',full=True)],
    order=lambda: Expense.query.order_by(Expense.date.desc(), Expense.id.desc()),
    search=['category','note'], date_field='date',
    filters=[dict(name='ecat', attr='category', label='All Categories',
                  options=[(c,c) for c in ['Electricity','Water','Fuel','Internet','Rent','Maintenance','Medical Supplies','Security','Marketing','Other']])])

register('employees', Employee, 'Employees',
    columns=[('Code',lambda o:f"<b>{h(o.code)}</b>"),('Name',lambda o:h(o.name)),('Position',lambda o:h(o.position or '—')),
             ('Base',lambda o:money(o.base),'num'),('Gross',lambda o:money(o.gross),'num'),('Net',lambda o:money(o.net),'num')],
    fields=[dict(name='code',label='Employee Code',required=True),dict(name='name',label='Full Name',required=True),
            dict(name='position',label='Position'),dict(name='dept',label='Department'),
            dict(name='base',label='Base Salary',type='number'),dict(name='allowance',label='Allowances',type='number'),
            dict(name='deduction',label='Deductions',type='number'),dict(name='active',label='Status',type='checkbox',default=True)],
    order=lambda: Employee.query.order_by(Employee.name),
    search=['name','code','position'])

def _po_status(o):
    st = getattr(o, 'status', None) or 'Received'   # legacy rows = already received
    return pill(st, {'Requested': 'grey', 'Ordered': 'blue', 'Received': 'green', 'Cancelled': 'red'})

def _po_actions(o):
    st = getattr(o, 'status', None)
    if st == 'Requested':
        return f"<a class='btn sm' href='/purchase/{o.id}/order'>Approve → Order</a>"
    if st == 'Ordered':
        return (f"<a class='btn sm ok' href='/purchase/{o.id}/receive'>Receive (GRN)</a>")
    if st == 'Received' or st in (None, ''):
        return f"<a class='btn gh sm' href='/purchase/{o.id}/grn' target='_blank'>GRN</a>"
    return ''

def _wh_opts():
    return [(w.id, f"{w.code} · {w.name}") for w in Warehouse.query.filter_by(active=True).order_by(Warehouse.id).all()]

register('purchases', Purchase, 'Purchase Orders',
    columns=[('Date',lambda o:h(o.date)),('Supplier',lambda o:h(o.supplier.name if o.supplier else '—')),('Item',lambda o:h(o.item or '—')),
             ('Qty',lambda o:f"{o.qty:g}",'num'),('Total',lambda o:money(o.total),'num'),('Paid',lambda o:money(o.paid),'num'),
             ('Status',_po_status),('Workflow',_po_actions,'num')],
    fields=[dict(name='date',label='Date',type='date',required=True,default=today()),
            dict(name='supplier_id',label='Supplier / Company',type='select',options_fn=opt_suppliers),
            dict(name='item',label='Item / Description'),
            dict(name='category',label='Category',type='select',options=[(c,c) for c in ['Medical Supplies','Contrast Media','Reagents','Films','Equipment','Other']]),
            dict(name='medicine_id',label='Link to Supply Item (stock will increase on receipt)',type='select',
                 options_fn=lambda:[('','— none / non-stock —')]+[(m.id,m.name) for m in Medicine.query.order_by(Medicine.name).all()]),
            dict(name='warehouse_id',label='Receive Into Warehouse',type='select',options_fn=lambda:[('','— Main —')]+_wh_opts()),
            dict(name='qty',label='Quantity',type='number',default=1),dict(name='unit_cost',label='Unit Cost',type='number'),
            dict(name='total',label='Total Amount',type='number'),dict(name='paid',label='Amount Paid',type='number'),
            dict(name='pay_method',label='Payment Method (how the paid amount is settled)',type='select',
                 options=[('Cash','Cash'),('Sahal','Sahal'),('EVC','EVC'),('E. Dahab','E. Dahab'),
                          ('MyCash','MyCash'),('Premier Wallet','Premier Wallet'),('Bank','Bank'),
                          ('Card','Card'),('Cheque','Cheque'),
                          ('Credit','Credit / Payable — pay the supplier later (on account)')]),
            dict(name='status',label='Status',type='select',options=[('Requested','Requested (purchase request)'),('Ordered','Ordered (PO sent)'),('Received','Received'),('Cancelled','Cancelled')])],
    order=lambda: Purchase.query.order_by(Purchase.id.desc()), singular='Purchase Order')

register('warehouses', Warehouse, 'Warehouses',
    columns=[('Code',lambda o:f"<b>{h(o.code or '')}</b>"),('Warehouse',lambda o:h(o.name)),
             ('Branch',lambda o:h(o.branch.name if o.branch else '—')),
             ('Status',lambda o:pill('Active','green') if o.active else pill('Off','grey'))],
    fields=[dict(name='code',label='Code',required=True),dict(name='name',label='Warehouse Name',required=True),
            dict(name='branch_id',label='Branch',type='select',
                 options_fn=lambda:[(b.id,b.name) for b in Branch.query.filter_by(active=True).all()]),
            dict(name='active',label='Status',type='checkbox',default=True)],
    order=lambda: Warehouse.query.order_by(Warehouse.id), singular='Warehouse')

# Chart of Accounts is handled by a custom hierarchical view (coa_view) — see ACCOUNTING section

def pill(text, mapping):
    if isinstance(mapping, dict): cls = mapping.get(text, 'grey')
    else: cls = mapping
    return f"<span class='pill {cls}'>{h(text)}</span>"
def stock_pill(m):
    if m.qty <= 0: return "<span class='pill red'>Out</span>"
    if m.qty <= (m.reorder or 0): return f"<span class='pill amber'>{m.qty} low</span>"
    return f"{m.qty}"
def expiry_pill(exp):
    if not exp: return '—'
    try:
        d = dt.date.fromisoformat(exp); days = (d - dt.date.today()).days
        if days < 0: return f"<span class='pill red'>Expired</span>"
        if days < 90: return f"<span class='pill amber'>{h(exp)}</span>"
        return h(exp)
    except: return h(exp)

def resolve_options(f):
    if 'options_fn' in f: return f['options_fn']()
    return f.get('options', [])



ASSET_CATS = ['Medical Equipment','Computer / IT','Furniture','Vehicle','Building / Fixture','Other']

register('assets', Asset, 'Assets',
    columns=[('Code',lambda o:f"<b>{h(o.code or '')}</b>"),('Asset',lambda o:h(o.name)),
             ('Category',lambda o:pill(o.category or '—','grey')),
             ('Cost',lambda o:money(o.cost),'num'),('Book Value',lambda o:money(o.book_value),'num'),
             ('Calibration Due',lambda o:expiry_pill(o.calibration_due)),
             ('Warranty',lambda o:expiry_pill(o.warranty_expiry)),
             ('Status',lambda o:pill(o.status,{'Active':'green','Under Repair':'amber','Retired':'grey'}))],
    fields=[dict(name='code',label='Asset Code',required=True),
            dict(name='name',label='Asset Name',required=True),
            dict(name='category',label='Category',type='select',options=[(c,c) for c in ASSET_CATS]),
            dict(name='serial',label='Serial Number'),
            dict(name='location',label='Location / Room'),
            dict(name='purchase_date',label='Purchase Date',type='date'),
            dict(name='cost',label='Purchase Cost',type='number'),
            dict(name='useful_life',label='Useful Life (years, straight-line)',type='number',default=5),
            dict(name='warranty_expiry',label='Warranty Expiry',type='date'),
            dict(name='calibration_due',label='Next Calibration Due',type='date'),
            dict(name='status',label='Status',type='select',options=[('Active','Active'),('Under Repair','Under Repair'),('Retired','Retired')]),
            dict(name='notes',label='Notes',type='textarea',full=True)],
    order=lambda: Asset.query.order_by(Asset.code), singular='Asset')

def _asset_opts():
    return [(a.id, f"{a.code} · {a.name}") for a in Asset.query.order_by(Asset.code).all()]

register('maintenance', MaintenanceJob, 'Maintenance Jobs',
    columns=[('Date',lambda o:h(o.date)),('Asset',lambda o:h(f"{o.asset.code} · {o.asset.name}" if o.asset else '—')),
             ('Type',lambda o:pill(o.type,{'Preventive':'blue','Corrective':'amber'})),
             ('Engineer',lambda o:h(o.engineer or '—')),
             ('Cost',lambda o:money((o.parts_cost or 0)+(o.labor_cost or 0)),'num'),
             ('Status',lambda o:pill(o.status,{'Open':'red','In Progress':'amber','Done':'green'})),
             ('Completed',lambda o:h(o.completed or '—'))],
    fields=[dict(name='asset_id',label='Asset',type='select',options_fn=_asset_opts,required=True),
            dict(name='type',label='Type',type='select',options=[('Preventive','Preventive'),('Corrective','Corrective')]),
            dict(name='date',label='Reported / Scheduled Date',type='date',default=today()),
            dict(name='engineer',label='Assigned Engineer'),
            dict(name='description',label='Problem / Work Description',type='textarea',full=True),
            dict(name='parts_cost',label='Spare Parts Cost',type='number'),
            dict(name='labor_cost',label='Labor Cost',type='number'),
            dict(name='status',label='Status',type='select',options=[('Open','Open'),('In Progress','In Progress'),('Done','Done')]),
            dict(name='completed',label='Completion Date',type='date')],
    order=lambda: MaintenanceJob.query.order_by(MaintenanceJob.status.desc(), MaintenanceJob.date.desc(), MaintenanceJob.id.desc()),
    singular='Maintenance Job')


def _acc_opts(types=None):
    q = Account.query.filter_by(is_group=False) if hasattr(Account, 'is_group') else Account.query
    accs = [a for a in q.order_by(Account.code).all() if not types or a.type in types]
    return [(a.id, f"{a.code} · {a.name}") for a in accs]

def _open_invoice_opts():
    out=[]
    for i in Invoice.query.order_by(Invoice.id.desc()).limit(300).all():
        if i.status!='Cancelled' and i.total>0:
            out.append((i.id, f"INV-{i.id:04d} · {(i.patient.name if i.patient else 'Walk-in')} · bal {money(i.balance)}"))
    return out

def _received_po_opts():
    return [(p.id, f"PUR-{p.id:04d} · {(p.supplier.name if p.supplier else p.item or '')} · {money(p.total)}")
            for p in Purchase.query.order_by(Purchase.id.desc()).limit(300).all()]

register('banks', BankAccount, 'Bank Accounts',
    columns=[('Account',lambda o:f"<b>{h(o.name)}</b>"),('Bank',lambda o:h(o.bank_name or '—')),
             ('Number',lambda o:h(o.number or '—')),('COA',lambda o:h(f"{o.account.code} · {o.account.name}" if o.account else '—')),
             ('Currency',lambda o:pill(o.currency or 'USD','blue')),
             ('Status',lambda o:pill('Active','green') if o.active else pill('Off','grey'))],
    fields=[dict(name='name',label='Account Nickname',required=True),
            dict(name='bank_name',label='Bank / Provider'),
            dict(name='number',label='Account Number / Wallet'),
            dict(name='account_id',label='Linked COA Account',type='select',
                 options_fn=lambda:_acc_opts({'Asset'})),
            dict(name='currency',label='Currency',default='USD'),
            dict(name='active',label='Status',type='checkbox',default=True)],
    order=lambda: BankAccount.query.order_by(BankAccount.id), singular='Bank Account')

register('budgets', Budget, 'Budgets',
    columns=[('Year',lambda o:f"<b>{o.year}</b>"),('Account',lambda o:h(f"{o.account.code} · {o.account.name}" if o.account else '—')),
             ('Annual Budget',lambda o:money(o.amount),'num'),('Note',lambda o:h(o.note or '—'))],
    fields=[dict(name='year',label='Fiscal Year',type='number',default=dt.date.today().year,required=True),
            dict(name='account_id',label='Account (revenue or expense)',type='select',
                 options_fn=lambda:_acc_opts({'Income','Expense'}),required=True),
            dict(name='amount',label='Annual Budget Amount',type='number',required=True),
            dict(name='note',label='Note')],
    order=lambda: Budget.query.order_by(Budget.year.desc(), Budget.id), singular='Budget')

register('costcenters', CostCenter, 'Cost Centers',
    columns=[('Code',lambda o:f"<b>{h(o.code or '')}</b>"),('Cost Center',lambda o:h(o.name)),
             ('Status',lambda o:pill('Active','green') if o.active else pill('Off','grey'))],
    fields=[dict(name='code',label='Code',required=True),dict(name='name',label='Name',required=True),
            dict(name='active',label='Status',type='checkbox',default=True)],
    order=lambda: CostCenter.query.order_by(CostCenter.code), singular='Cost Center')

register('currencies', Currency, 'Currencies',
    columns=[('Code',lambda o:f"<b>{h(o.code)}</b>"),('Currency',lambda o:h(o.name or '—')),
             ('Rate per 1 base',lambda o:f"{o.rate:,.4g}",'num'),
             ('Status',lambda o:pill('Active','green') if o.active else pill('Off','grey'))],
    fields=[dict(name='code',label='Code (e.g. SOS, EUR)',required=True),
            dict(name='name',label='Currency Name'),
            dict(name='rate',label='Exchange Rate (units per 1 base currency)',type='number',required=True),
            dict(name='active',label='Status',type='checkbox',default=True)],
    order=lambda: Currency.query.order_by(Currency.code), singular='Currency')

register('creditnotes', CreditNote, 'Credit Notes',
    columns=[('No.',lambda o:f"<b>CN-{o.id:04d}</b>"),('Date',lambda o:h(o.date)),
             ('Invoice',lambda o:h(f"INV-{o.invoice_id:04d}" if o.invoice_id else '—')),
             ('Patient',lambda o:h(o.invoice.patient.name if (o.invoice and o.invoice.patient) else 'Walk-in')),
             ('Amount',lambda o:money(o.amount),'num'),('Reason',lambda o:h(o.reason or '—')),
             ('By',lambda o:h(o.user or '—')),
             ('',lambda o:f"<a class='btn gh sm' href='/creditnote/{o.id}/print' data-file='/creditnote/{o.id}/print' target='_blank'>🖨 Print</a>",'num')],
    fields=[dict(name='date',label='Date',type='date',default=today(),required=True),
            dict(name='invoice_id',label='Against Invoice',type='select',options_fn=_open_invoice_opts,required=True),
            dict(name='amount',label='Credit Amount',type='number',required=True),
            dict(name='reason',label='Reason',required=True)],
    order=lambda: CreditNote.query.order_by(CreditNote.id.desc()), singular='Credit Note')

register('debitnotes', DebitNote, 'Debit Notes',
    columns=[('No.',lambda o:f"<b>DN-{o.id:04d}</b>"),('Date',lambda o:h(o.date)),
             ('Purchase',lambda o:h(f"PUR-{o.purchase_id:04d}" if o.purchase_id else '—')),
             ('Supplier',lambda o:h(o.purchase.supplier.name if (o.purchase and o.purchase.supplier) else '—')),
             ('Amount',lambda o:money(o.amount),'num'),('Reason',lambda o:h(o.reason or '—')),
             ('By',lambda o:h(o.user or '—')),
             ('',lambda o:f"<a class='btn gh sm' href='/debitnote/{o.id}/print' data-file='/debitnote/{o.id}/print' target='_blank'>🖨 Print</a>",'num')],
    fields=[dict(name='date',label='Date',type='date',default=today(),required=True),
            dict(name='purchase_id',label='Against Purchase',type='select',options_fn=_received_po_opts,required=True),
            dict(name='amount',label='Debit Amount',type='number',required=True),
            dict(name='reason',label='Reason',required=True)],
    order=lambda: DebitNote.query.order_by(DebitNote.id.desc()), singular='Debit Note')


def _exp_pill(o):
    import datetime as _dt
    if not o.expiry: return '—'
    try:
        d=(_dt.date.fromisoformat(o.expiry)-_dt.date.today()).days
    except Exception: return h(o.expiry)
    if d<0: return pill(f'{o.expiry} · EXPIRED','red')
    if d<=90: return pill(f'{o.expiry} · {d}d','amber')
    return pill(o.expiry,'green')

register('batches', MedBatch, 'Batches / Lots (FEFO)',
    columns=[('Item',lambda o:h(o.medicine.name if o.medicine else '—')),('Batch',lambda o:f"<b>{h(o.batch_no)}</b>"),
             ('Expiry',_exp_pill),('Qty',lambda o:f"{o.qty:g}"),('Received',lambda o:h(o.received))],
    fields=[dict(name='medicine_id',label='Item',type='select',options_fn=med_opts,required=True),
            dict(name='batch_no',label='Batch / Lot No.',required=True),
            dict(name='expiry',label='Expiry Date',type='date',required=True),
            dict(name='qty',label='Quantity',type='number',step='any',required=True),
            dict(name='received',label='Received Date',type='date',default=today())],
    order=lambda: MedBatch.query.order_by(MedBatch.expiry), singular='Batch')

register('contracts', EmpContract, 'Employment Contracts',
    columns=[('Employee',lambda o:h(o.employee.name if o.employee else '—')),('Type',lambda o:h(o.ctype)),
             ('Start',lambda o:h(o.start or '—')),('End',lambda o:h(o.end or 'Open')),
             ('Salary',lambda o:money(o.salary))],
    fields=[dict(name='employee_id',label='Employee',type='select',options_fn=emp_opts,required=True),
            dict(name='ctype',label='Contract Type',type='select',options=[(x,x) for x in ('Permanent','Fixed-term','Probation','Part-time')]),
            dict(name='start',label='Start Date',type='date',default=today()),dict(name='end',label='End Date',type='date'),
            dict(name='salary',label='Monthly Salary',type='number',step='any'),
            dict(name='notes',label='Notes',full=True)],
    order=lambda: EmpContract.query.order_by(EmpContract.id.desc()), singular='Contract')

register('performance', Performance, 'Performance Reviews',
    columns=[('Employee',lambda o:h(o.employee.name if o.employee else '—')),('Date',lambda o:h(o.date)),
             ('Score',lambda o:pill('★'*(o.score or 0)+'☆'*(5-(o.score or 0)),'green' if (o.score or 0)>=4 else ('amber' if (o.score or 0)>=3 else 'red'))),
             ('Reviewer',lambda o:h(o.reviewer or '—'))],
    fields=[dict(name='employee_id',label='Employee',type='select',options_fn=emp_opts,required=True),
            dict(name='date',label='Review Date',type='date',default=today()),
            dict(name='score',label='Score (1–5)',type='select',options=[(str(i),f'{i} — '+t) for i,t in ((5,'Excellent'),(4,'Good'),(3,'Satisfactory'),(2,'Needs improvement'),(1,'Poor'))]),
            dict(name='reviewer',label='Reviewer'),
            dict(name='notes',label='Notes',type='textarea',full=True)],
    order=lambda: Performance.query.order_by(Performance.id.desc()), singular='Review')

register('training', Training, 'Training Records',
    columns=[('Employee',lambda o:h(o.employee.name if o.employee else '—')),('Course',lambda o:h(o.course or '—')),
             ('Provider',lambda o:h(o.provider or '—')),('Date',lambda o:h(o.date)),('Result',lambda o:pill(o.result or '—','green' if o.result=='Completed' else 'grey'))],
    fields=[dict(name='employee_id',label='Employee',type='select',options_fn=emp_opts,required=True),
            dict(name='course',label='Course / Topic',required=True),dict(name='provider',label='Provider'),
            dict(name='date',label='Date',type='date',default=today()),
            dict(name='result',label='Result',type='select',options=[(x,x) for x in ('Completed','In progress','Failed')])],
    order=lambda: Training.query.order_by(Training.id.desc()), singular='Training')

def _asset_opts():
    return [(a.id, a.name) for a in Asset.query.order_by(Asset.name).all()]

def _sc_pill(o):
    import datetime as _dt
    if not o.end: return '—'
    try: d=(_dt.date.fromisoformat(o.end)-_dt.date.today()).days
    except Exception: return h(o.end)
    if d<0: return pill(f'{o.end} · ENDED','red')
    if d<=60: return pill(f'{o.end} · {d}d left','amber')
    return pill(o.end,'green')

register('svccontracts', SvcContract, 'Service Contracts (Equipment)',
    columns=[('Asset',lambda o:h(o.asset.name if o.asset else '—')),('Vendor',lambda o:h(o.vendor or '—')),
             ('Phone',lambda o:h(o.phone or '—')),('Start',lambda o:h(o.start or '—')),('Ends',_sc_pill),
             ('Annual Cost',lambda o:money(o.cost))],
    fields=[dict(name='asset_id',label='Asset / Equipment',type='select',options_fn=_asset_opts,required=True),
            dict(name='vendor',label='Vendor / Service Company',required=True),dict(name='phone',label='Vendor Phone'),
            dict(name='start',label='Start',type='date',default=today()),dict(name='end',label='End',type='date'),
            dict(name='cost',label='Contract Cost / year',type='number',step='any'),
            dict(name='notes',label='Notes',full=True)],
    order=lambda: SvcContract.query.order_by(SvcContract.end), singular='Service Contract')


BLOOD_GROUPS=('A+','A-','B+','B-','AB+','AB-','O+','O-')

register('donors', Donor, 'Blood Donors',
    columns=[('Name',lambda o:f"<b>{h(o.name)}</b>"),('Phone',lambda o:h(o.phone or '—')),
             ('Group',lambda o:pill(o.blood_group or '—','red')),
             ('Last Donation',lambda o:h(o.last_donation or '—'))],
    fields=[dict(name='name',label='Donor Name',required=True),dict(name='phone',label='Phone'),
            dict(name='blood_group',label='Blood Group',type='select',options=[('','—')]+[(b,b) for b in BLOOD_GROUPS]),
            dict(name='last_donation',label='Last Donation',type='date'),
            dict(name='notes',label='Screening Notes',type='textarea',full=True)],
    order=lambda: Donor.query.order_by(Donor.name), singular='Donor')

def _bu_pill(o):
    import datetime as _dt
    stc={'Available':'green','Reserved':'blue','Used':'grey','Expired':'red','Discarded':'red'}
    x=pill(o.status,stc.get(o.status,'grey'))
    try:
        if o.status=='Available' and o.expiry and (_dt.date.fromisoformat(o.expiry)-_dt.date.today()).days<=7:
            x+= ' '+pill('exp soon','amber')
    except Exception: pass
    return x

register('bloodunits', BloodUnit, 'Blood Units (Stock)',
    columns=[('Unit',lambda o:f"<b>{h(o.unit_no or f'BU-{o.id:04d}')}</b>"),
             ('Group',lambda o:pill(o.blood_group or '—','red')),
             ('Donor',lambda o:h(o.donor.name if o.donor else '—')),
             ('Collected',lambda o:h(o.collected or '—')),('Expiry',lambda o:h(o.expiry or '—')),
             ('Status',_bu_pill),
             ('Issued To',lambda o:h(o.patient.name if o.patient else '—'))],
    fields=[dict(name='unit_no',label='Unit No. (blank = auto)'),
            dict(name='blood_group',label='Blood Group',type='select',options=[(b,b) for b in BLOOD_GROUPS],required=True),
            dict(name='donor_id',label='Donor',type='select',options_fn=lambda:[('','—')]+[(d.id,f'{d.name} ({d.blood_group or "?"})') for d in Donor.query.order_by(Donor.name)]),
            dict(name='collected',label='Collected',type='date',default=today()),
            dict(name='expiry',label='Expiry',type='date'),
            dict(name='status',label='Status',type='select',options=[(x,x) for x in ('Available','Reserved','Used','Expired','Discarded')]),
            dict(name='issued_to',label='Issued to Patient (when Used)',type='select',options_fn=lambda:[('','—')]+opt_patients()),
            dict(name='issued_date',label='Issued Date',type='date'),
            dict(name='notes',label='Notes',full=True)],
    order=lambda: BloodUnit.query.order_by(BloodUnit.status, BloodUnit.expiry), singular='Blood Unit')

register('vaccinations', Vaccination, 'Vaccinations',
    columns=[('Patient',lambda o:h(o.patient.name if o.patient else '—')),
             ('Vaccine',lambda o:f"<b>{h(o.vaccine or '—')}</b>"),('Dose',lambda o:f"#{o.dose_no or 1}"),
             ('Date',lambda o:h(o.date)),('Next Due',lambda o:h(o.next_due or '—')),
             ('Cert',lambda o:f"<a class='btn gh sm' href='/vacc/{o.id}/cert' target='_blank'>🖨 Certificate</a>")],
    fields=[dict(name='patient_id',label='Patient',type='select',options_fn=opt_patients,required=True),
            dict(name='vaccine',label='Vaccine',required=True),
            dict(name='dose_no',label='Dose Number',type='number',default='1'),
            dict(name='date',label='Date Given',type='date',default=today()),
            dict(name='batch',label='Vaccine Batch/Lot'),
            dict(name='next_due',label='Next Dose Due',type='date'),
            dict(name='given_by',label='Given By')],
    order=lambda: Vaccination.query.order_by(Vaccination.id.desc()), singular='Vaccination')

def _rev_pill(o):
    import datetime as _dt
    if not o.review_due: return '—'
    try: d=(_dt.date.fromisoformat(o.review_due)-_dt.date.today()).days
    except Exception: return h(o.review_due)
    if d<0: return pill(f'{o.review_due} · OVERDUE','red')
    if d<=30: return pill(f'{o.review_due} · {d}d','amber')
    return pill(o.review_due,'green')

register('sops', SOPDoc, 'SOPs & Documents (ISO 15189)',
    columns=[('Code',lambda o:f"<b>{h(o.code or '—')}</b>"),('Title',lambda o:h(o.title or '—')),
             ('Dept',lambda o:h(o.department or '—')),('Ver',lambda o:h(o.version or '—')),
             ('Review Due',_rev_pill),
             ('Status',lambda o:pill(o.status,{'Active':'green','Draft':'amber','Obsolete':'grey'}.get(o.status,'grey')))],
    fields=[dict(name='code',label='Document Code (e.g. SOP-LAB-001)',required=True),
            dict(name='title',label='Title',required=True),
            dict(name='department',label='Department',type='select',options=[(x,x) for x in ('Laboratory','Radiology','Reception','Pharmacy','Admin','Quality')]),
            dict(name='version',label='Version',default='1.0'),
            dict(name='effective',label='Effective Date',type='date',default=today()),
            dict(name='review_due',label='Review Due',type='date'),
            dict(name='owner',label='Document Owner'),
            dict(name='status',label='Status',type='select',options=[(x,x) for x in ('Draft','Active','Obsolete')]),
            dict(name='notes',label='Notes / Location',type='textarea',full=True)],
    order=lambda: SOPDoc.query.order_by(SOPDoc.code), singular='Document',
    search=['code','title'])

register('incidents', Incident, 'Incidents & Nonconformities',
    columns=[('Date',lambda o:h(o.date)),('Dept',lambda o:h(o.department or '—')),
             ('Type',lambda o:h(o.itype or '—')),
             ('Severity',lambda o:pill(o.severity,{'Minor':'amber','Major':'red','Critical':'red'}.get(o.severity,'grey'))),
             ('Description',lambda o:h((o.description or '—')[:50])),
             ('Status',lambda o:pill(o.status,{'Open':'red','Investigating':'amber','Closed':'green'}.get(o.status,'grey')))],
    fields=[dict(name='date',label='Date',type='date',default=today(),required=True),
            dict(name='department',label='Department',type='select',options=[(x,x) for x in ('Laboratory','Radiology','Reception','Pharmacy','Admin')]),
            dict(name='itype',label='Type',type='select',options=[(x,x) for x in ('Nonconformity','Sample rejection','Equipment failure','Patient complaint','Safety','Other')]),
            dict(name='severity',label='Severity',type='select',options=[(x,x) for x in ('Minor','Major','Critical')]),
            dict(name='description',label='Description',type='textarea',full=True,required=True),
            dict(name='action',label='Corrective Action',type='textarea',full=True),
            dict(name='reported_by',label='Reported By'),
            dict(name='status',label='Status',type='select',options=[(x,x) for x in ('Open','Investigating','Closed')])],
    order=lambda: Incident.query.order_by(Incident.id.desc()), singular='Incident',
    search=['department','description'], date_field='date')

register('audits', InternalAudit, 'Internal Audits',
    columns=[('Date',lambda o:h(o.date)),('Area',lambda o:h(o.area or '—')),('Auditor',lambda o:h(o.auditor or '—')),
             ('Findings',lambda o:h((o.findings or '—')[:50])),('Due',lambda o:h(o.due or '—')),
             ('Status',lambda o:pill(o.status,'red' if o.status=='Open' else 'green'))],
    fields=[dict(name='date',label='Audit Date',type='date',default=today(),required=True),
            dict(name='area',label='Area / Process',required=True),dict(name='auditor',label='Auditor'),
            dict(name='findings',label='Findings',type='textarea',full=True),
            dict(name='due',label='Corrective Action Due',type='date'),
            dict(name='status',label='Status',type='select',options=[('Open','Open'),('Closed','Closed')])],
    order=lambda: InternalAudit.query.order_by(InternalAudit.id.desc()), singular='Audit')

register('feedback', Feedback, 'Patient Feedback',
    columns=[('When',lambda o:o.created.strftime('%d-%b-%y') if o.created else '—'),
             ('Patient',lambda o:h(o.patient.name if o.patient else 'Anonymous')),
             ('Rating',lambda o:pill('★'*(o.rating or 0)+'☆'*(5-(o.rating or 0)),'green' if (o.rating or 0)>=4 else ('amber' if (o.rating or 0)>=3 else 'red'))),
             ('Comment',lambda o:h((o.comment or '—')[:70]))],
    fields=[dict(name='patient_id',label='Patient',type='select',options_fn=lambda:[('','Anonymous')]+opt_patients()),
            dict(name='rating',label='Rating (1–5)',type='select',options=[(str(i),'★'*i) for i in (5,4,3,2,1)]),
            dict(name='comment',label='Comment',type='textarea',full=True)],
    order=lambda: Feedback.query.order_by(Feedback.id.desc()), singular='Feedback')


def _rad_reports(o):
    from .helpers import _radorder_count
    return _radorder_count(o.name)
def _rad_out(o):
    from ..models import CommissionAccrual
    return sum(a.balance for a in CommissionAccrual.query.filter_by(payee_kind='radiologist', payee_name=o.name).all())
def _rad_paid(o):
    from ..models import CommissionAccrual
    return sum((a.paid or 0) for a in CommissionAccrual.query.filter_by(payee_kind='radiologist', payee_name=o.name).all())

register('radiologists', Radiologist, 'Radiologists',
    columns=[('ID',lambda o:f"RAD-{o.id:03d}"),('Name',lambda o:f"<b>{h(o.name)}</b><br><small>{h(o.hospital or '')}</small>"),
             ('Specialty',lambda o:h(o.specialty or '—')),
             ('Fee',lambda o:(money(o.fee_value)+' /study' if o.fee_type=='Fixed' else (f'{o.fee_value:g}%' if o.fee_type=='Percent' else 'Service default'))),
             ('Schedule',lambda o:h(o.pay_schedule or 'Monthly')),
             ('Reports',lambda o:str(_rad_reports(o)),'num'),
             ('Outstanding',lambda o:money(_rad_out(o)),'num'),
             ('Paid',lambda o:money(_rad_paid(o)),'num'),
             ('Phone',lambda o:h(o.phone or '—')),
             ('Portal',lambda o:(pill(o.portal_user,'teal') if o.portal_user else '—')),
             ('Status',lambda o:pill('Active','green') if o.active else pill('Off','grey'))],
    fields=[dict(name='name',label='Full Name',required=True),
            dict(name='gender',label='Gender',type='select',options=[('',''),('Male','Male'),('Female','Female')]),
            dict(name='dob',label='Date of Birth',type='date'),
            dict(name='phone',label='Phone (SMS notifications)'),
            dict(name='email',label='Email'),
            dict(name='national_id',label='National ID / Passport'),
            dict(name='license_no',label='Medical License Number'),
            dict(name='specialty',label='Specialization'),
            dict(name='qualification',label='Qualification (e.g. MD, FRCR)'),
            dict(name='hospital',label='Hospital / Company'),
            dict(name='city',label='City'),
            dict(name='address',label='Address',full=True),
            dict(name='fee_type',label='Fee Rule',type='select',
                 options=[('','Service default'),('Fixed','Fixed $ per study'),('Percent','% of radiology amount')]),
            dict(name='fee_value',label='Reporting Fee ($ or %) — default 10',type='number',default=10),
            dict(name='pay_schedule',label='Payment Schedule',type='select',
                 options=[(x,x) for x in ['Daily','Weekly','Monthly','Custom']],default='Monthly'),
            dict(name='active',label='Active',type='checkbox',default=True),
            dict(name='portal_user',label='Portal Username (/rrad)'),
            dict(name='portal_pw_set',label='Set Portal Password (blank = keep current)')],
    order=lambda: Radiologist.query.order_by(Radiologist.name), singular='Radiologist',
    search=['name','specialty','phone'])


def _recur_acc_opts():
    return [('', '—')] + [(a.code, f'{a.code} · {a.name}') for a in Account.query.order_by(Account.code) if a.code]

register('recurjournals', RecurringJournal, 'Recurring Journals',
    columns=[('Memo',lambda o:h(o.memo or '—')),('Dr',lambda o:h(o.dr_account or '—')),
             ('Cr',lambda o:h(o.cr_account or '—')),('Amount',lambda o:money(o.amount or 0)),
             ('Day',lambda o:f"day {o.day or 1}"),('Last Run',lambda o:h(o.last_run or 'never')),
             ('Active',lambda o:pill('Active','green') if o.active else pill('Off','grey'))],
    fields=[dict(name='memo',label='Description',required=True),
            dict(name='dr_account',label='Debit Account',type='select',options_fn=_recur_acc_opts,required=True),
            dict(name='cr_account',label='Credit Account',type='select',options_fn=_recur_acc_opts,required=True),
            dict(name='amount',label='Amount',type='number',step='any',required=True),
            dict(name='day',label='Day of Month (1–28)',type='number',default='1'),
            dict(name='active',label='Active',type='checkbox',default=True)],
    order=lambda: RecurringJournal.query.order_by(RecurringJournal.id.desc()), singular='Recurring Journal')


# ---------------------------------------------------------------- list powers
# Odoo's list view lets a user sort, group and export any list without a
# developer. These helpers derive those options from the model itself, so every
# registered list gains them at once and behaves the same way.

_SKIP_FIELDS = {'id', 'pw', 'portal_pw', 'password', 'photo', 'signature', 'attachment'}


def list_fields(model):
    """(name, label, kind) for each scalar column worth sorting/grouping on."""
    from sqlalchemy import String, Integer, Float, Boolean, Date, DateTime, Text
    from .moneytype import Money
    out = []
    for c in model.__table__.columns:
        n = c.name
        if n in _SKIP_FIELDS or n.endswith('_pw') or n.endswith('_hash'):
            continue
        t = c.type
        if isinstance(t, Text):
            continue
        if isinstance(t, Money):
            kind = 'money'
        elif isinstance(t, Boolean):
            kind = 'bool'
        elif isinstance(t, (Integer, Float)):
            kind = 'num'
        elif isinstance(t, (Date, DateTime)):
            kind = 'date'
        elif isinstance(t, String):
            kind = 'text'
        else:
            continue
        label = n[:-3].replace('_', ' ').title() + ' (id)' if n.endswith('_id') else n.replace('_', ' ').title()
        out.append((n, label, kind))
    return out


# free-text / near-unique columns: grouping by them just makes one group per row
_UNIQUE_ISH = ('name', 'mrn', 'phone', 'email', 'address', 'note', 'notes', 'ref',
               'number', 'no', 'code', 'serial', 'title', 'desc', 'description',
               'reason', 'remarks', 'comment', 'user', 'by', 'username', 'id_no',
               'national_id', 'license_no', 'tax_no', 'bank_details', 'qualification',
               'item', 'memo', 'subject', 'result', 'report')


def groupable_fields(model):
    """Columns worth grouping by: statuses, categories, types, departments, dates.

    Free-text and near-unique columns are filtered out, since a group per row
    is noise rather than insight."""
    out = []
    for n, lb, k in list_fields(model):
        # real Date/DateTime columns carry a timestamp -> one group per row
        if k not in ('text', 'bool') or n.endswith('_id'):
            continue
        low = n.lower()
        if any(low == u or low.endswith('_' + u) for u in _UNIQUE_ISH):
            continue
        out.append((n, lb, k))
    return out


def money_fields(model):
    from .moneytype import Money
    return [c.name for c in model.__table__.columns if isinstance(c.type, Money)]


def is_month_col(name):
    """Business dates are stored as 'YYYY-MM-DD' strings; group those by month."""
    n = (name or '').lower()
    return n == 'date' or n.endswith('_date')


# ---------------------------------------------------------------------------
# Advanced search builder (Phase 17) — field/operator/value conditions joined
# by AND or OR, applied generically to any registered model.
# ---------------------------------------------------------------------------
ADV_OPS = [
    ('contains', 'contains'), ('ncontains', 'does not contain'),
    ('eq', '='), ('ne', '≠'), ('starts', 'starts with'), ('ends', 'ends with'),
    ('gt', '>'), ('lt', '<'), ('between', 'between'),
    ('empty', 'is empty'), ('nempty', 'is not empty'),
    ('true', 'is true'), ('false', 'is false'),
]


def filter_fields(model):
    """(name, label, kind) columns a user may build advanced conditions on."""
    return [(n, lb, k) for n, lb, k in list_fields(model)]


def _coerce(v, kind):
    if kind in ('num', 'money'):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return v


def apply_advanced(query, model, conds, join='and'):
    """Apply a list of {f,op,v,v2} conditions. Returns the filtered query.

    Unknown fields/operators are skipped. join is 'and' or 'or'."""
    from sqlalchemy import or_ as _or, and_ as _and, not_ as _not
    kinds = {n: k for n, _l, k in list_fields(model)}
    exprs = []
    for c in conds or []:
        f = c.get('f')
        op = c.get('op')
        if f not in kinds:
            continue
        col = getattr(model, f, None)
        if col is None:
            continue
        kind = kinds[f]
        v = _coerce(c.get('v', ''), kind)
        v2 = _coerce(c.get('v2', ''), kind)
        e = None
        if op == 'contains':
            e = col.ilike(f"%{c.get('v','')}%")
        elif op == 'ncontains':
            e = _not(col.ilike(f"%{c.get('v','')}%"))
        elif op == 'eq':
            e = (col == v)
        elif op == 'ne':
            e = (col != v)
        elif op == 'starts':
            e = col.ilike(f"{c.get('v','')}%")
        elif op == 'ends':
            e = col.ilike(f"%{c.get('v','')}")
        elif op == 'gt':
            e = (col > v) if v is not None else None
        elif op == 'lt':
            e = (col < v) if v is not None else None
        elif op == 'between':
            if v is not None and v2 is not None:
                e = col.between(v, v2)
        elif op == 'empty':
            e = (col.is_(None)) | (col == '')
        elif op == 'nempty':
            e = (col.isnot(None)) & (col != '')
        elif op == 'true':
            e = (col == True)   # noqa: E712
        elif op == 'false':
            e = (col == False)  # noqa: E712
        if e is not None:
            exprs.append(e)
    if not exprs:
        return query
    return query.filter(_or(*exprs) if join == 'or' else _and(*exprs))
