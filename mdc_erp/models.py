"""Database models — MDC Diagnostic ERP.

All SQLAlchemy models in one place, grouped by domain.
Relationships use string references so import order never matters.
"""
import datetime as dt
from .extensions import db
from .core.moneytype import Money

# ---------------------------------------------------------------------------
# NUMERIC COLUMN POLICY  (see core/moneytype.py)
#
#   Money  -> amounts of currency. Stored as INTEGER cents: exact, never drifts,
#             every write rounded half-up to 2dp.
#   Float  -> everything that is NOT currency. These MUST stay Float because
#             cent-rounding would destroy them:
#
#     exchange rates   Currency.rate            0.001754 -> 0.00   (wiped out)
#     QC statistics    QCRecord.value/mean/sd   0.0083   -> 0.01   (lab QC invalid)
#     measurements     Consultation temp/weight/height, LabParam low/high,
#                      Service.panic_low/high   70.456   -> 70.46
#     quantities       *.qty, supply_qty, qty_change   (2.375 ml -> 2.38)
#     percentages      Invoice.discount_pct, Doctor.percent_rate,
#                      Service.max_discount     (0.125% -> 0.13%)
#     dual-purpose     Service.comm_*_val, Radiologist.fee_value hold EITHER a
#                      percent OR a fixed amount depending on the matching
#                      *_type column, so they cannot be typed as Money.
#
# test_money_column_classification pins this split — if you change a column
# here, that test tells you whether it was deliberate.
# ---------------------------------------------------------------------------
class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20))
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(200))
    phone = db.Column(db.String(30))
    active = db.Column(db.Boolean, default=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(120))
    role = db.Column(db.String(30), default='reception')
    pw = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True)
    totp_secret = db.Column(db.String(64))
    totp_enabled = db.Column(db.Boolean, default=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    # force a password change at next sign-in (set for the seeded admin and
    # whenever an administrator resets someone's password)
    must_change_pw = db.Column(db.Boolean, default=False)
    branch = db.relationship('Branch')

class Setting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(255))

class Favorite(db.Model):
    """Per-user pinned pages for the Favorites menu (Odoo-style bookmarks)."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), index=True)
    label = db.Column(db.String(120))
    url = db.Column(db.String(200))
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))


class Audit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    user = db.Column(db.String(50))
    action = db.Column(db.String(255))
    action_type = db.Column(db.String(24))   # Create/Edit/Delete/Cancel/Payment/…
    entity = db.Column(db.String(60))         # e.g. INV-0001, Patient MDC-0007
    ip = db.Column(db.String(64))
    old_value = db.Column(db.String(255))
    new_value = db.Column(db.String(255))
    reason = db.Column(db.String(255))

class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mrn = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30))
    gender = db.Column(db.String(10))
    dob = db.Column(db.String(12))
    age_years = db.Column(db.Integer)   # entered age when the exact date of birth is unknown
    gov_id = db.Column(db.String(40))
    address = db.Column(db.String(200))
    notes = db.Column(db.Text)
    phone2 = db.Column(db.String(30))
    blood_group = db.Column(db.String(5))
    marital = db.Column(db.String(15))
    occupation = db.Column(db.String(80))
    emerg_name = db.Column(db.String(120))
    emerg_phone = db.Column(db.String(30))
    ins_company = db.Column(db.String(120))
    ins_number = db.Column(db.String(60))
    allergies = db.Column(db.Text)
    med_history = db.Column(db.Text)
    chronic = db.Column(db.String(200))         # chronic diseases (HTN, DM, ...)
    photo = db.Column(db.String(120))
    active = db.Column(db.Boolean, default=True)
    reg_by = db.Column(db.String(80))
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    @property
    def age(self):
        # Prefer an exact date of birth; otherwise use the plain age that was
        # entered (e.g. from a doctor request) so it still shows on documents.
        if self.dob:
            try:
                b = dt.date.fromisoformat(self.dob); t = dt.date.today()
                return t.year - b.year - ((t.month, t.day) < (b.month, b.day))
            except Exception:
                pass
        try:
            return int(self.age_years) if self.age_years is not None else None
        except Exception:
            return None

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(30))  # Lab, Radiology, Consultation, Other
    price = db.Column(Money, default=0)           # Cash price
    price_insurance = db.Column(Money, default=0)
    price_corporate = db.Column(Money, default=0)
    price_vip = db.Column(Money, default=0)
    price_contract = db.Column(Money, default=0)
    cost = db.Column(Money, default=0)
    ref_range = db.Column(db.String(120))       # lab reference range, e.g. 4.0–11.0
    unit = db.Column(db.String(30))             # lab unit, e.g. x10^9/L
    panic_low = db.Column(db.Float)             # critical value thresholds
    panic_high = db.Column(db.Float)
    loinc = db.Column(db.String(20))            # LOINC lab code
    cpt = db.Column(db.String(12))              # CPT procedure code
    specimen = db.Column(db.String(30))         # default specimen type
    supply_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))
    supply_qty = db.Column(db.Float, default=0)
    active = db.Column(db.Boolean, default=True)
    # ---- extended service configuration (v4.5) ----
    short_name = db.Column(db.String(60))
    category = db.Column(db.String(60))          # e.g. CT Scan, Hematology
    subcategory = db.Column(db.String(60))
    description = db.Column(db.Text)
    price_emergency = db.Column(Money, default=0)
    price_home = db.Column(Money, default=0)
    discount_allowed = db.Column(db.Boolean, default=True)
    max_discount = db.Column(db.Float, default=0)     # percent
    # multi-role commission (type: Percent/Fixed ; value)
    comm_doctor_type = db.Column(db.String(8), default='Percent')
    comm_doctor_val = db.Column(db.Float, default=0)
    comm_radiologist_type = db.Column(db.String(8), default='Fixed')
    comm_radiologist_val = db.Column(db.Float, default=0)
    comm_tech_type = db.Column(db.String(8), default='Fixed')
    comm_tech_val = db.Column(db.Float, default=0)
    comm_report_type = db.Column(db.String(8), default='Fixed')
    comm_report_val = db.Column(db.Float, default=0)
    workflow = db.Column(db.String(20))          # Laboratory/Radiology/Consultation/Procedure/Cashier Only
    report_template = db.Column(db.String(60))   # template name for radiology reports
    equipment = db.Column(db.String(60))         # CT Scanner, MRI Scanner, etc.
    time_collection = db.Column(db.Integer)      # minutes
    time_processing = db.Column(db.Integer)
    time_reporting = db.Column(db.Integer)
    avail_branches = db.Column(db.String(200))   # comma list; blank = all
    modality = db.Column(db.String(30))          # CT/MRI/X-Ray/Ultrasound/ECG… (radiology routing)
    supply = db.relationship('Medicine')

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    queue_no = db.Column(db.Integer)            # daily queue token (Reception)
    checkin_time = db.Column(db.String(8))      # HH:MM when checked in
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    date = db.Column(db.String(12))
    time = db.Column(db.String(8))
    department = db.Column(db.String(30))
    doctor = db.Column(db.String(80))
    status = db.Column(db.String(20), default='Scheduled')  # Scheduled/Confirmed/Waiting/In Progress/Done/Cancelled/No Show
    notes = db.Column(db.String(200))
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))
    visit_type = db.Column(db.String(15), default='New')     # New / Follow-up / Emergency
    priority = db.Column(db.String(10), default='Normal')    # Normal / Urgent
    service = db.relationship('Service')
    patient = db.relationship('Patient')

class LabOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    status = db.Column(db.String(20), default='Requested')  # Requested→Collected→Received→Resulted→Approved
    result = db.Column(db.Text)
    result_by = db.Column(db.String(50))
    approved_by = db.Column(db.String(50))
    sample_no = db.Column(db.String(20))          # specimen barcode SMP-xxxxx
    specimen = db.Column(db.String(30))           # Blood/Serum/Urine/...
    collected_by = db.Column(db.String(50))
    collected_at = db.Column(db.String(20))
    received_at = db.Column(db.String(20))
    panic = db.Column(db.Boolean, default=False)      # critical value flag
    panic_ack = db.Column(db.Boolean, default=False)  # critical alert acknowledged (LIS)
    delta_flag = db.Column(db.Boolean, default=False) # large change vs previous result
    ref_id = db.Column(db.Integer, db.ForeignKey('referral.id'))  # doctor portal referral
    invoice_id = db.Column(db.Integer)       # billing link
    paid_gate = db.Column(db.Boolean, default=True)   # False until invoice paid/approved
    locked = db.Column(db.Boolean, default=False)     # True once Approved — no direct edits
    patient = db.relationship('Patient'); service = db.relationship('Service')


class ResultAmendment(db.Model):
    """An amendment to a LOCKED clinical result. The previous result is preserved
    here forever — clinical history is never overwritten."""
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10))           # 'lab' or 'rad'
    order_id = db.Column(db.Integer)          # LabOrder.id or RadOrder.id
    prev_result = db.Column(db.Text)          # the result BEFORE this amendment
    new_result = db.Column(db.Text)           # the result AFTER
    reason = db.Column(db.String(300))        # why the amendment was made (required)
    amended_by = db.Column(db.String(80))
    amended_at = db.Column(db.String(30))


class CriticalAlert(db.Model):
    """A critical / panic laboratory value and its acknowledgement trail:
    Critical Result -> Alert -> Clinician -> Acknowledgement -> Action -> Audit."""
    id = db.Column(db.Integer, primary_key=True)
    lab_order_id = db.Column(db.Integer)
    patient_id = db.Column(db.Integer)
    patient_name = db.Column(db.String(120))
    test_name = db.Column(db.String(120))
    value = db.Column(db.String(60))          # the critical value as recorded
    critical_range = db.Column(db.String(60)) # the panic low/high that was breached
    raised_at = db.Column(db.String(30))      # when the alert fired
    raised_by = db.Column(db.String(80))      # who entered the result
    notified_role = db.Column(db.String(40))  # who was alerted (e.g. doctor)
    acknowledged = db.Column(db.Boolean, default=False)
    ack_by = db.Column(db.String(80))         # clinician who acknowledged
    ack_at = db.Column(db.String(30))
    action = db.Column(db.String(400))        # action taken / comment (required to ack)

class RadOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    images = db.Column(db.Text)                # stored image filenames, comma-separated
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))
    modality = db.Column(db.String(20))  # CT, MRI, X-Ray, Ultrasound
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    status = db.Column(db.String(20), default='Requested')  # Requested, Imaged, Reported
    report = db.Column(db.Text)             # Findings (template)
    technique = db.Column(db.Text)          # Technique (template)
    impression = db.Column(db.Text)         # Impression / conclusion (template)
    clinical_data = db.Column(db.String(300))   # Clinical data / indication (template)
    reported_by = db.Column(db.String(50))
    radiologist = db.Column(db.String(80))
    fee = db.Column(Money, default=0)
    image_note = db.Column(db.String(200))
    patient = db.relationship('Patient'); service = db.relationship('Service')
    ref_id = db.Column(db.Integer, db.ForeignKey('referral.id'))
    invoice_id = db.Column(db.Integer)       # billing link
    paid_gate = db.Column(db.Boolean, default=True)   # False until invoice paid/approved
    assigned_rad_id = db.Column(db.Integer, db.ForeignKey('radiologist.id'))
    draft = db.Column(db.Text)                     # remote radiologist working draft
    rad_approved_at = db.Column(db.String(20))     # approval timestamp (locks report)
    assigned_rad = db.relationship('Radiologist')
    # --- RIS layer (Phase 2, v8.0): scheduling, workflow, sign-off, TAT ---
    priority = db.Column(db.String(10), default='Routine')   # Routine / Urgent / STAT
    modality_id = db.Column(db.Integer, db.ForeignKey('img_modality.id'))  # scheduled resource
    scheduled_for = db.Column(db.String(20))       # ISO datetime of the booked slot
    technician = db.Column(db.String(60))          # who acquired the images
    requested_at = db.Column(db.String(20))        # TAT anchor: request received
    scheduled_at = db.Column(db.String(20))        # TAT: slot booked
    acquired_at = db.Column(db.String(20))         # TAT: images acquired
    reported_at = db.Column(db.String(20))         # TAT: report written
    approved_at = db.Column(db.String(20))         # TAT: report signed off
    approved_by = db.Column(db.String(60))         # radiologist who signed
    signature = db.Column(db.String(40))           # HMAC signature of the signed report
    locked = db.Column(db.Boolean, default=False)  # True once Reported/finalized — amend-only
    ris_modality = db.relationship('ImgModality')

class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    batch = db.Column(db.String(40))
    expiry = db.Column(db.String(12))
    qty = db.Column(db.Integer, default=0)
    reorder = db.Column(db.Integer, default=10)
    price = db.Column(Money, default=0)
    cost = db.Column(Money, default=0)

class PharmacySale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    qty = db.Column(db.Integer, default=1)
    total = db.Column(Money, default=0)
    medicine = db.relationship('Medicine'); patient = db.relationship('Patient')

class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30))
    address = db.Column(db.String(200))
    contact_person = db.Column(db.String(120))
    email = db.Column(db.String(120))
    tax_no = db.Column(db.String(60))
    bank_details = db.Column(db.String(200))
    category = db.Column(db.String(60))   # Electricity/Water/Internet/Fuel/Medical Supplier/...

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20))
    name = db.Column(db.String(120), nullable=False)
    type = db.Column(db.String(20), default='Asset')
    parent_id = db.Column(db.Integer, db.ForeignKey('account.id'))
    is_group = db.Column(db.Boolean, default=False)
    opening = db.Column(Money, default=0)
    active = db.Column(db.Boolean, default=True)
    parent = db.relationship('Account', remote_side=[id], backref='children')

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    ref = db.Column(db.String(40))
    memo = db.Column(db.String(200))
    lines = db.relationship('JournalLine', backref='entry', cascade='all,delete')
    reversed_by = db.Column(db.Integer)     # id of the reversing entry
    is_reversal = db.Column(db.Boolean, default=False)
    reverses_id = db.Column(db.Integer)     # on a reversal: id of the entry it reverses
    reversed_at = db.Column(db.String(30))  # when the original was reversed
    reversed_by_user = db.Column(db.String(80))   # who reversed it
    reversal_reason = db.Column(db.String(200))   # why (required)
    posted_by = db.Column(db.String(80))    # who posted the original (best-effort)
    @property
    def total_debit(self): return sum(l.debit or 0 for l in self.lines)
    @property
    def total_credit(self): return sum(l.credit or 0 for l in self.lines)

class JournalLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cleared = db.Column(db.Boolean, default=False)   # bank reconciliation flag
    entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'))
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'))
    debit = db.Column(Money, default=0)
    credit = db.Column(Money, default=0)
    account = db.relationship('Account')

class Doctor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30))              # manual doctor code/number (you assign, e.g. DR-001)
    name = db.Column(db.String(120), nullable=False)
    specialty = db.Column(db.String(80))
    phone = db.Column(db.String(30))
    commission_type = db.Column(db.String(10), default='Percent')
    fixed_rate = db.Column(Money, default=0)
    percent_rate = db.Column(db.Float, default=0)
    active = db.Column(db.Boolean, default=True)
    portal_user = db.Column(db.String(60))       # doctor referral portal login
    portal_pw = db.Column(db.String(200))

class Referral(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    patient_name = db.Column(db.String(120))
    patient_phone = db.Column(db.String(30))
    patient_age = db.Column(db.String(20))
    patient_gender = db.Column(db.String(10))
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'))
    doctor_name = db.Column(db.String(120))
    hospital = db.Column(db.String(120))
    tests = db.Column(db.Text)
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='New')
    complaint = db.Column(db.Text)               # chief complaint
    prov_dx = db.Column(db.String(200))          # provisional diagnosis
    priority = db.Column(db.String(10), default='Routine')  # Routine/Urgent/STAT
    instructions = db.Column(db.String(300))
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    doctor_ref = db.relationship('Doctor')
    patient = db.relationship('Patient')

class SalaryAdvance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    amount = db.Column(Money, default=0)
    reason = db.Column(db.String(200))
    status = db.Column(db.String(20), default='Pending')
    employee = db.relationship('Employee')

class EmpLoan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    amount = db.Column(Money, default=0)
    paid = db.Column(Money, default=0)
    installment = db.Column(Money, default=0)
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='Active')
    employee = db.relationship('Employee')
    @property
    def balance(self):
        from .core.helpers import money_round
        return money_round((self.amount or 0) - (self.paid or 0))

class Logistic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    type = db.Column(db.String(30))
    ref = db.Column(db.String(120))
    origin = db.Column(db.String(120))
    destination = db.Column(db.String(120))
    driver = db.Column(db.String(80))
    status = db.Column(db.String(20), default='Pending')
    notes = db.Column(db.Text)

class Consultation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    icd_code = db.Column(db.String(20))         # ICD-10 diagnosis code
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    doctor = db.Column(db.String(120))
    complaint = db.Column(db.Text)
    diagnosis = db.Column(db.Text)
    icd_code = db.Column(db.String(12))            # ICD-10 diagnosis code
    notes = db.Column(db.Text)
    bp = db.Column(db.String(12))                  # vitals
    temp_c = db.Column(db.Float)
    pulse = db.Column(db.Integer)
    spo2 = db.Column(db.Integer)
    weight_kg = db.Column(db.Float)
    height_cm = db.Column(db.Float)
    followup_date = db.Column(db.String(12))
    status = db.Column(db.String(15), default='Open')   # Open / Completed
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))  # billable consultation fee, if any
    invoice_id = db.Column(db.Integer)       # billing link (mirrors LabOrder/RadOrder pattern)
    service = db.relationship('Service')
    patient = db.relationship('Patient')

class Prescription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))
    qty = db.Column(db.Float, default=1)
    dosage = db.Column(db.String(160))
    doctor = db.Column(db.String(120))
    status = db.Column(db.String(20), default='Pending')
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    patient = db.relationship('Patient')
    medicine = db.relationship('Medicine')

class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    item = db.Column(db.String(120))
    category = db.Column(db.String(40))
    qty = db.Column(db.Float, default=1)
    unit_cost = db.Column(Money, default=0)
    total = db.Column(Money, default=0)
    paid = db.Column(Money, default=0)
    pay_method = db.Column(db.String(30), default='Cash')   # how the paid portion was settled
    vendor_ref = db.Column(db.String(80))      # Vendor Reference (their quote/invoice no)
    order_deadline = db.Column(db.String(20))  # Order Deadline (Odoo)
    expected_date = db.Column(db.String(20))   # expected Receipt Date
    terms = db.Column(db.Text)                 # terms & conditions
    discount = db.Column(Money, default=0)     # order-level discount amount
    bill_status = db.Column(db.String(12), default='none')  # none → draft → posted (vendor bill)
    # --- PO workflow (Requested -> Ordered -> Received); NULL = legacy record
    status = db.Column(db.String(20), default='Requested')
    received_date = db.Column(db.String(12))
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))    # stock item to receive
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))  # receive into
    supplier = db.relationship('Supplier')
    medicine = db.relationship('Medicine')
    warehouse = db.relationship('Warehouse')

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    created_by = db.Column(db.String(80))     # user who created the invoice
    created_at = db.Column(db.String(30))     # when it was created
    discount = db.Column(Money, default=0)
    vat = db.Column(Money, default=0)
    paid = db.Column(Money, default=0)
    status = db.Column(db.String(20), default='Unpaid')
    price_list = db.Column(db.String(20), default='Cash')
    discount_pct = db.Column(db.Float, default=0)
    contrast_amount = db.Column(db.Float)   # manual contrast $ (None = auto-detect from 'with contrast' services)
    commission_amount = db.Column(db.Float)  # manual doctor-commission $ override (None = auto-calc)
    consumed = db.Column(db.Boolean, default=False)  # consumables already deducted from stock
    pay_method = db.Column(db.String(20), default='Cash')
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    branch = db.relationship('Branch')
    referring_doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'))
    referral_id = db.Column(db.Integer, db.ForeignKey('referral.id'))   # source Doctor Request
    locked = db.Column(db.Boolean, default=False)   # workflow completed → immutable until admin reset
    confirmed = db.Column(db.Boolean, default=False)   # cashier confirmed the reviewed invoice → unlocks payment step
    # who guarantees a credit sale: a partner hospital, a company, or a named
    # person. Printed on the invoice for credit sales only.
    guarantor = db.Column(db.String(160))
    guarantor_by = db.Column(db.String(80))     # staff member who granted the credit
    guarantor_at = db.Column(db.String(20))     # when it was recorded
    due_date = db.Column(db.String(12))         # credit/loan sale: when the balance is due
    disc_reason = db.Column(db.String(40))
    disc_by = db.Column(db.String(80))
    disc_date = db.Column(db.String(12))
    patient = db.relationship('Patient')
    doctor_ref = db.relationship('Doctor')
    items = db.relationship('InvoiceItem', backref='invoice', cascade='all,delete')
    @property
    def subtotal(self):
        from .core.helpers import money_round
        return money_round(sum(i.price*i.qty for i in self.items))
    @property
    def total(self):
        from .core.helpers import money_round
        sub=self.subtotal
        return money_round(sub - (self.discount or 0) - sub*(self.discount_pct or 0)/100.0 + (self.vat or 0))
    @property
    def commission(self):
        d=self.doctor_ref
        if not d: return 0
        if d.commission_type=='Fixed': return d.fixed_rate or 0
        from .core.helpers import money_round
        r=d.percent_rate or 0
        r=r/100.0 if r>1 else r   # accept 20 (=20%) or 0.20; never treat 20 as ×20
        return money_round(self.subtotal*r)
    @property
    def service_fees(self):
        """Per-service commission/fee breakdown from Service configuration.
        Returns dict with doctor/radiologist/technician/writer totals (GROSS, full line).
        Contrast is removed from the doctor/writer commission at the invoice level in
        posting.commission_preview (so a manual per-invoice contrast amount also works)."""
        out = {'doctor': 0.0, 'radiologist': 0.0, 'technician': 0.0, 'writer': 0.0}
        for it in self.items:
            svc = it.service
            if not svc:
                continue
            line = (it.qty or 1) * (it.price or 0)
            for role, ttype, rate in (
                ('doctor', getattr(svc, 'comm_doctor_type', None), getattr(svc, 'comm_doctor_val', 0)),
                ('radiologist', getattr(svc, 'comm_radiologist_type', None), getattr(svc, 'comm_radiologist_val', 0)),
                ('technician', getattr(svc, 'comm_tech_type', None), getattr(svc, 'comm_tech_val', 0)),
                ('writer', getattr(svc, 'comm_report_type', None), getattr(svc, 'comm_report_val', 0))):
                if not rate:
                    continue
                out[role] += (line * rate / 100.0) if ttype == 'Percent' else (rate * (it.qty or 1))
        return out
    @property
    def credits(self):
        return sum(cn.amount or 0 for cn in CreditNote.query.filter_by(invoice_id=self.id).all())
    @property
    def balance(self):
        from .core.helpers import money_round
        return money_round(self.total - (self.paid or 0) - self.credits)

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    lab_order_id = db.Column(db.Integer)     # traceability to LabOrder
    rad_order_id = db.Column(db.Integer)     # traceability to RadOrder
    consult_id = db.Column(db.Integer)       # traceability to Consultation (doctor consultation fee)
    manual_reason = db.Column(db.String(160))  # required when added via More ⋮ Add Service Manually
    manual_by = db.Column(db.String(80))       # who added it manually
    manual_at = db.Column(db.String(20))       # when
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))
    service = db.relationship('Service')
    desc = db.Column(db.String(160))
    qty = db.Column(db.Float, default=1)
    price = db.Column(Money, default=0)
    @property
    def source_label(self):
        if self.lab_order_id: return f'Laboratory Order #LAB-{self.lab_order_id:05d}'
        if self.rad_order_id: return f'Radiology Order #RAD-{self.rad_order_id:05d}'
        if self.consult_id: return f'Doctor Consultation #CON-{self.consult_id:05d}'
        if self.manual_reason: return f'Manual — {self.manual_reason}'
        return None

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    supplier = db.relationship('Supplier')
    pay_method = db.Column(db.String(20), default='Cash')
    cost_center_id = db.Column(db.Integer, db.ForeignKey('cost_center.id'))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    branch = db.relationship('Branch')
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    category = db.Column(db.String(40))
    amount = db.Column(Money, default=0)
    paid = db.Column(Money, default=0)
    note = db.Column(db.String(200))
    # --- Odoo-style expense workflow ---
    description = db.Column(db.String(160))     # what the expense is (title)
    product = db.Column(db.String(120))         # product / expense category label
    qty = db.Column(db.Float, default=1)
    unit_price = db.Column(Money, default=0)
    account = db.Column(db.String(80))          # GL expense account label
    employee = db.Column(db.String(80))         # who incurred it
    paid_by = db.Column(db.String(20), default='Company')   # Company | Employee
    status = db.Column(db.String(12), default='Draft')      # Draft→Submitted→Approved→Posted→Paid

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(120), nullable=False)
    position = db.Column(db.String(60))
    dept = db.Column(db.String(60))
    base = db.Column(Money, default=0)
    allowance = db.Column(Money, default=0)
    deduction = db.Column(Money, default=0)
    active = db.Column(db.Boolean, default=True)
    @property
    def gross(self): return (self.base or 0)+(self.allowance or 0)
    @property
    def net(self): return self.gross-(self.deduction or 0)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    status = db.Column(db.String(20), default='Present')  # Present, Absent, Leave
    employee = db.relationship('Employee')

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    start = db.Column(db.String(12)); end = db.Column(db.String(12))
    type = db.Column(db.String(30)); status = db.Column(db.String(20), default='Pending')
    employee = db.relationship('Employee')



class QueueTicket(db.Model):
    """Reception queue ticket (per-day, per-department numbering)."""
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer)                              # 1, 2, 3 ... per day+dept
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    department = db.Column(db.String(30), default='Consultation')
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    name = db.Column(db.String(120))                            # walk-in without record
    status = db.Column(db.String(20), default='Waiting')        # Waiting, Called, Done, Cancelled, NoShow
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    # --- smart queue (Phase 5, v8.0) ---
    priority = db.Column(db.String(10), default='Normal')        # Normal / Priority / Emergency
    room = db.Column(db.String(30))                              # counter / consulting room called to
    called_at = db.Column(db.String(20))
    done_at = db.Column(db.String(20))
    created_by = db.Column(db.String(60))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    patient = db.relationship('Patient')

    @property
    def code(self):
        return f"{(self.department or 'C')[0].upper()}-{self.number:03d}"


class LabParam(db.Model):
    """Reference-range parameter attached to a Laboratory service."""
    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))
    name = db.Column(db.String(80), nullable=False)             # e.g. WBC
    unit = db.Column(db.String(20))                             # e.g. x10^9/L
    low = db.Column(db.Float)                                   # reference low
    high = db.Column(db.Float)                                  # reference high
    position = db.Column(db.Integer, default=0)
    service = db.relationship('Service')


# ---------------------------------------------------------------- Phase 3
class Asset(db.Model):
    """Fixed asset register: medical equipment, computers, furniture, vehicles."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(30))          # Medical Equipment, Computer, ...
    serial = db.Column(db.String(60))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    location = db.Column(db.String(120))
    purchase_date = db.Column(db.String(12))
    in_service_date = db.Column(db.String(12))     # when the asset was put in use — depreciation starts here
    capitalization_date = db.Column(db.String(12)) # when it was capitalized on the books
    cost = db.Column(Money, default=0)
    useful_life = db.Column(db.Integer, default=5)    # years (straight-line)
    warranty_expiry = db.Column(db.String(12))
    calibration_due = db.Column(db.String(12))
    status = db.Column(db.String(20), default='Active')  # Draft, Active, Disposed, Sold, Retired, Under Repair
    notes = db.Column(db.Text)
    # --- enterprise fixed-assets fields ---
    category_id = db.Column(db.Integer, db.ForeignKey('asset_category.id'))
    residual_value = db.Column(Money, default=0)
    useful_life_months = db.Column(db.Integer)          # overrides years when set
    depreciation_method = db.Column(db.String(24), default='Straight Line')
    department = db.Column(db.String(80))
    custodian = db.Column(db.String(80))
    supplier = db.Column(db.String(120))
    purchase_invoice = db.Column(db.String(60))
    accumulated_dep = db.Column(Money, default=0)       # posted accumulated depreciation
    reval_adjust = db.Column(Money, default=0)          # cumulative revaluation adjustment
    units_total = db.Column(db.Integer)                 # for Units of Production
    units_used = db.Column(db.Integer, default=0)
    activated = db.Column(db.Boolean, default=False)    # approve → activate workflow
    opening = db.Column(db.Boolean, default=False)      # already owned before the system (opening balance)
    branch = db.relationship('Branch')
    cat = db.relationship('AssetCategory')

    @property
    def life_months(self):
        if self.useful_life_months:
            return max(int(self.useful_life_months), 1)
        return max(int(self.useful_life or 5) * 12, 1)

    @property
    def depreciable_base(self):
        return max((self.cost or 0) + (self.reval_adjust or 0) - (self.residual_value or 0), 0)

    @property
    def nbv(self):
        """Net book value = cost + revaluation − accumulated depreciation."""
        return round((self.cost or 0) + (self.reval_adjust or 0) - (self.accumulated_dep or 0), 2)

    @property
    def months_elapsed(self):
        try:
            start = dt.date.fromisoformat((self.purchase_date or '')[:10])
        except Exception:
            return 0
        t = dt.date.today()
        return max((t.year - start.year) * 12 + (t.month - start.month), 0)

    @property
    def remaining_months(self):
        return max(self.life_months - self.months_elapsed, 0)

    @property
    def book_value(self):
        """Straight-line current book value."""
        try:
            start = dt.date.fromisoformat(self.purchase_date)
        except (TypeError, ValueError):
            return self.cost or 0
        years = max((dt.date.today() - start).days / 365.25, 0)
        life = self.useful_life or 5
        remaining = max(1 - years / life, 0)
        return round((self.cost or 0) * remaining, 2)


class MaintenanceJob(db.Model):
    """Preventive/corrective maintenance work orders with service history."""
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    type = db.Column(db.String(20), default='Corrective')   # Preventive, Corrective
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    engineer = db.Column(db.String(80))
    description = db.Column(db.Text)
    parts_cost = db.Column(Money, default=0)
    labor_cost = db.Column(Money, default=0)
    status = db.Column(db.String(20), default='Open')       # Open, In Progress, Done
    completed = db.Column(db.String(12))
    asset = db.relationship('Asset')


# ==================== Enterprise Fixed Assets ====================
class AssetCategory(db.Model):
    """Depreciation & accounting defaults for a class of assets."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True)
    useful_life = db.Column(db.Integer, default=5)          # years
    method = db.Column(db.String(24), default='Straight Line')
    residual_pct = db.Column(db.Float, default=0)           # % of cost
    asset_account = db.Column(db.String(10), default='1510')        # Dr on purchase
    accum_account = db.Column(db.String(10), default='1520')        # Cr on depreciation
    expense_account = db.Column(db.String(10), default='6400')      # Dr on depreciation
    active = db.Column(db.Boolean, default=True)


class AssetDepreciation(db.Model):
    """One posted depreciation period for an asset."""
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), index=True)
    period = db.Column(db.String(7))          # YYYY-MM
    date = db.Column(db.String(12))
    amount = db.Column(Money, default=0)
    accumulated = db.Column(Money, default=0)
    book_value = db.Column(Money, default=0)
    journal_ref = db.Column(db.String(24))
    posted = db.Column(db.Boolean, default=True)
    asset = db.relationship('Asset')


class AssetTransfer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), index=True)
    date = db.Column(db.String(12))
    from_dept = db.Column(db.String(80)); to_dept = db.Column(db.String(80))
    from_branch = db.Column(db.Integer); to_branch = db.Column(db.Integer)
    from_location = db.Column(db.String(120)); to_location = db.Column(db.String(120))
    reason = db.Column(db.String(200))
    by = db.Column(db.String(50))
    asset = db.relationship('Asset')


class AssetRevaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), index=True)
    date = db.Column(db.String(12))
    old_value = db.Column(Money, default=0)
    new_value = db.Column(Money, default=0)
    delta = db.Column(Money, default=0)          # + increase, - decrease
    reason = db.Column(db.String(200))
    journal_ref = db.Column(db.String(24))
    by = db.Column(db.String(50))
    asset = db.relationship('Asset')


class AssetDisposal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), index=True)
    date = db.Column(db.String(12))
    method = db.Column(db.String(20))            # Sale, Retirement, Donation, Write-Off
    proceeds = db.Column(Money, default=0)
    book_value = db.Column(Money, default=0)     # NBV at disposal
    gain_loss = db.Column(Money, default=0)      # + gain, - loss
    reason = db.Column(db.String(200))
    journal_ref = db.Column(db.String(24))
    by = db.Column(db.String(50))
    asset = db.relationship('Asset')


class Notification(db.Model):
    """In-app notification, optionally targeted at a role (None = everyone)."""
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    role = db.Column(db.String(30))              # target role, None = all users
    text = db.Column(db.String(255))
    link = db.Column(db.String(200))
    seen_by = db.Column(db.Text, default='')     # comma-separated user ids


class ChatMessage(db.Model):
    """A direct chat message between two staff users (internal messaging)."""
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    body = db.Column(db.Text)
    attachment = db.Column(db.String(255))       # stored filename under uploads/chat
    attachment_name = db.Column(db.String(255))  # original filename for display
    ts = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    read = db.Column(db.Boolean, default=False)
    sender = db.relationship('User', foreign_keys=[sender_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])


class ServiceConsumable(db.Model):
    """Bill of materials: a consumable (Medicine/supply) a Service uses, so its usage is
    auto-deducted from stock when the service is performed/paid (contrast, gloves, cannula...)."""
    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))
    qty = db.Column(db.Float, default=1)
    service = db.relationship('Service')
    item = db.relationship('Medicine')


class StockAdj(db.Model):
    """Stock adjustment: physical count correction, damage, expiry write-off."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))
    qty_change = db.Column(db.Float, default=0)      # +in / -out
    reason = db.Column(db.String(120))
    user = db.Column(db.String(50))
    medicine = db.relationship('Medicine')


class Warehouse(db.Model):
    """Physical storage location; stock is tracked per warehouse via StockLevel."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20))
    name = db.Column(db.String(120), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    active = db.Column(db.Boolean, default=True)
    branch = db.relationship('Branch')


class StockLevel(db.Model):
    """Quantity of one supply item held in one warehouse.
    Invariant: sum(levels for a medicine) == Medicine.qty (the grand total)."""
    id = db.Column(db.Integer, primary_key=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    qty = db.Column(db.Float, default=0)
    medicine = db.relationship('Medicine')
    warehouse = db.relationship('Warehouse')


class StockTransfer(db.Model):
    """Movement of stock between warehouses (total quantity unchanged)."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))
    from_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    to_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    qty = db.Column(db.Float, default=0)
    note = db.Column(db.String(120))
    user = db.Column(db.String(50))
    medicine = db.relationship('Medicine')
    from_wh = db.relationship('Warehouse', foreign_keys=[from_id])
    to_wh = db.relationship('Warehouse', foreign_keys=[to_id])


# ------------------------------------------------------- Enterprise Accounting
class BankAccount(db.Model):
    """Bank/mobile-money account mapped to a COA cash account for reconciliation."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    bank_name = db.Column(db.String(120))
    number = db.Column(db.String(60))
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'))   # COA link
    currency = db.Column(db.String(10), default='USD')
    active = db.Column(db.Boolean, default=True)
    account = db.relationship('Account')


class Budget(db.Model):
    """Annual budget per COA account (revenue or expense)."""
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'))
    amount = db.Column(Money, default=0)
    note = db.Column(db.String(120))
    account = db.relationship('Account')


class CostCenter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20))
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True)


class CreditNote(db.Model):
    """Reduces a patient invoice balance (Dr Revenue / Cr Accounts Receivable)."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    amount = db.Column(Money, default=0)
    reason = db.Column(db.String(160))
    user = db.Column(db.String(50))
    invoice = db.relationship('Invoice')


class DebitNote(db.Model):
    """Reduces a supplier purchase payable (Dr Accounts Payable / Cr Inventory)."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'))
    amount = db.Column(Money, default=0)
    reason = db.Column(db.String(160))
    user = db.Column(db.String(50))
    purchase = db.relationship('Purchase')


class FiscalPeriod(db.Model):
    """Month lock: no journal postings allowed into a Closed period.
    Closing and reopening are audited (who / when / why)."""
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)   # 1..12
    status = db.Column(db.String(10), default='Open')  # Open / Closed
    closed_by = db.Column(db.String(80))
    closed_at = db.Column(db.String(30))
    reopened_by = db.Column(db.String(80))
    reopened_at = db.Column(db.String(30))
    reopen_reason = db.Column(db.String(200))


class Currency(db.Model):
    """Display currencies with exchange rate per 1 unit of the base currency."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(60))
    rate = db.Column(db.Float, default=1.0)   # e.g. 1 USD = 26500 SOS -> rate 26500
    active = db.Column(db.Boolean, default=True)


class PayReceipt(db.Model):
    """One row per payment event (split payments supported) -> printable receipt."""
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    amount = db.Column(Money, default=0)
    method = db.Column(db.String(20), default='Cash')
    ref = db.Column(db.String(60))
    # Client-supplied retry key; unique across receipts so a network retry
    # cannot create a second financial event.
    idempotency_key = db.Column(db.String(128), unique=True, index=True)
    cashier = db.Column(db.String(80))
    invoice = db.relationship('Invoice', backref='receipts')


class CashClosing(db.Model):
    """A closed cash day/shift with opening float, actual count and over/short."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    opening_cash = db.Column(Money, default=0)
    expected_cash = db.Column(Money, default=0)   # opening + cash collected - refunds - withdrawals
    actual_cash = db.Column(Money, default=0)     # counted by cashier
    withdrawals = db.Column(Money, default=0)
    difference = db.Column(Money, default=0)      # actual - expected (over=+, short=-)
    collected = db.Column(Money, default=0)       # total across all methods
    note = db.Column(db.String(200))
    closed_by = db.Column(db.String(80))
    closed_at = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    reopened_by = db.Column(db.String(80))
    reopened_at = db.Column(db.DateTime)
    status = db.Column(db.String(12), default='Closed')  # Closed / Reopened


class QCRecord(db.Model):
    """Internal quality control run (Levey-Jennings style flags)."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))
    level = db.Column(db.String(10), default='L1')   # control level
    value = db.Column(db.Float, default=0)
    target_mean = db.Column(db.Float, default=0)
    target_sd = db.Column(db.Float, default=0)
    operator = db.Column(db.String(50))
    service = db.relationship('Service')
    @property
    def z(self):
        try: return (self.value - self.target_mean) / self.target_sd if self.target_sd else 0.0
        except Exception: return 0.0


class LoginHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    when = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    username = db.Column(db.String(80))
    ip = db.Column(db.String(45))
    ok = db.Column(db.Boolean, default=False)
    note = db.Column(db.String(80))


class MedBatch(db.Model):
    """Batch / lot tracking with expiry (FEFO)."""
    id = db.Column(db.Integer, primary_key=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'))
    batch_no = db.Column(db.String(40))
    expiry = db.Column(db.String(12))
    qty = db.Column(db.Float, default=0)
    received = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    medicine = db.relationship('Medicine')

class EmpContract(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    ctype = db.Column(db.String(20), default='Permanent')  # Permanent/Fixed-term/Probation
    start = db.Column(db.String(12)); end = db.Column(db.String(12))
    salary = db.Column(Money, default=0)
    notes = db.Column(db.String(200))
    employee = db.relationship('Employee')

class Performance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    score = db.Column(db.Integer, default=3)   # 1-5
    reviewer = db.Column(db.String(80))
    notes = db.Column(db.Text)
    employee = db.relationship('Employee')

class Training(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    course = db.Column(db.String(120))
    provider = db.Column(db.String(120))
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    result = db.Column(db.String(30), default='Completed')
    employee = db.relationship('Employee')

class SvcContract(db.Model):
    """Equipment service / maintenance contract."""
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    vendor = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    start = db.Column(db.String(12)); end = db.Column(db.String(12))
    cost = db.Column(Money, default=0)
    notes = db.Column(db.String(200))
    asset = db.relationship('Asset')


class OutMsg(db.Model):
    """Outbound SMS / WhatsApp queue. Sends via the configured HTTP gateway;
    without a gateway the messages wait as Pending (nothing is lost)."""
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    to = db.Column(db.String(30))
    channel = db.Column(db.String(12), default='SMS')     # SMS / WhatsApp
    body = db.Column(db.String(480))
    status = db.Column(db.String(12), default='Pending')  # Pending / Sent / Failed
    info = db.Column(db.String(160))
    ref = db.Column(db.String(40))


class SOPDoc(db.Model):
    """Document control: SOPs, policies, manuals (ISO 15189 / 9001)."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20))
    title = db.Column(db.String(160))
    department = db.Column(db.String(40), default='Laboratory')
    version = db.Column(db.String(10), default='1.0')
    effective = db.Column(db.String(12))
    review_due = db.Column(db.String(12))
    owner = db.Column(db.String(80))
    status = db.Column(db.String(15), default='Active')   # Draft/Active/Obsolete
    notes = db.Column(db.Text)

class Incident(db.Model):
    """Quality incident / nonconformity reporting."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    department = db.Column(db.String(40))
    itype = db.Column(db.String(40), default='Nonconformity')
    severity = db.Column(db.String(10), default='Minor')   # Minor/Major/Critical
    description = db.Column(db.Text)
    action = db.Column(db.Text)                            # corrective action
    reported_by = db.Column(db.String(80))
    status = db.Column(db.String(15), default='Open')      # Open/Investigating/Closed

class Donor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    blood_group = db.Column(db.String(5))
    last_donation = db.Column(db.String(12))
    notes = db.Column(db.String(200))

class BloodUnit(db.Model):
    """Blood bank stock unit."""
    id = db.Column(db.Integer, primary_key=True)
    unit_no = db.Column(db.String(20))
    blood_group = db.Column(db.String(5))
    donor_id = db.Column(db.Integer, db.ForeignKey('donor.id'))
    collected = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    expiry = db.Column(db.String(12))
    status = db.Column(db.String(12), default='Available')  # Available/Reserved/Used/Expired/Discarded
    notes = db.Column(db.String(200))
    issued_to = db.Column(db.Integer, db.ForeignKey('patient.id'))
    issued_date = db.Column(db.String(12))
    donor = db.relationship('Donor'); patient = db.relationship('Patient', foreign_keys=[issued_to])

class Feedback(db.Model):
    """Patient feedback from the portal."""
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    rating = db.Column(db.Integer, default=5)   # 1-5
    comment = db.Column(db.String(400))
    patient = db.relationship('Patient')


class Vaccination(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    vaccine = db.Column(db.String(80)); dose_no = db.Column(db.Integer, default=1)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    batch = db.Column(db.String(40)); next_due = db.Column(db.String(12))
    given_by = db.Column(db.String(80))
    patient = db.relationship('Patient')

class InternalAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12), default=lambda: dt.date.today().isoformat())
    area = db.Column(db.String(80)); auditor = db.Column(db.String(80))
    findings = db.Column(db.Text); due = db.Column(db.String(12))
    status = db.Column(db.String(10), default='Open')


class RefComment(db.Model):
    """Discussion thread on a doctor-portal referral."""
    id = db.Column(db.Integer, primary_key=True)
    referral_id = db.Column(db.Integer, db.ForeignKey('referral.id'))
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    author = db.Column(db.String(80))
    is_doctor = db.Column(db.Boolean, default=False)
    text = db.Column(db.String(500))
    referral = db.relationship('Referral', backref='comments')


class Radiologist(db.Model):
    """Remote radiologist (teleradiology portal /rrad)."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    specialty = db.Column(db.String(80))
    phone = db.Column(db.String(30))
    active = db.Column(db.Boolean, default=True)
    portal_user = db.Column(db.String(60))
    portal_pw = db.Column(db.String(200))
    # per-radiologist fee rule (same idea as referring-doctor commission);
    # blank fee_type = use the per-service configuration
    fee_type = db.Column(db.String(10), default='')     # '' | 'Fixed' | 'Percent'
    fee_value = db.Column(db.Float, default=0.0)        # $ per study, or % of radiology lines
    gender = db.Column(db.String(10))
    dob = db.Column(db.String(12))
    email = db.Column(db.String(120))
    national_id = db.Column(db.String(60))
    license_no = db.Column(db.String(60))
    qualification = db.Column(db.String(120))
    hospital = db.Column(db.String(120))
    city = db.Column(db.String(80))
    address = db.Column(db.String(200))
    pay_schedule = db.Column(db.String(12), default='Monthly')  # Daily/Weekly/Monthly/Custom

class RadComment(db.Model):
    """Case discussion: technician / radiologist / staff."""
    id = db.Column(db.Integer, primary_key=True)
    rad_id = db.Column(db.Integer, db.ForeignKey('rad_order.id'))
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    author = db.Column(db.String(80))
    is_remote = db.Column(db.Boolean, default=False)
    text = db.Column(db.String(500))
    order = db.relationship('RadOrder', backref='case_comments')


class RecurringJournal(db.Model):
    """Template posted automatically each month (rent, depreciation accruals…)."""
    id = db.Column(db.Integer, primary_key=True)
    memo = db.Column(db.String(200))
    dr_account = db.Column(db.String(20))
    cr_account = db.Column(db.String(20))
    amount = db.Column(Money, default=0)
    day = db.Column(db.Integer, default=1)      # day of month to post
    active = db.Column(db.Boolean, default=True)
    last_run = db.Column(db.String(12))


class ErrorLog(db.Model):
    """Captured application errors for administrator review (Admin → Error Log)."""
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    user = db.Column(db.String(80))
    screen = db.Column(db.String(200))       # request path
    action = db.Column(db.String(10))        # HTTP method
    err_type = db.Column(db.String(120))     # exception class
    detail = db.Column(db.Text)              # message + short traceback
    ip = db.Column(db.String(45))
    browser = db.Column(db.String(200))
    resolved = db.Column(db.Boolean, default=False)


class CommissionAccrual(db.Model):
    """A doctor commission or radiologist/tech/writer fee accrued when a patient pays.
    Becomes an outstanding payable until settled through the payment screen."""
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    date = db.Column(db.String(12))
    role = db.Column(db.String(16))          # doctor / radiologist / technician / writer
    payee_kind = db.Column(db.String(16))    # 'doctor' or 'radiologist' (who is owed)
    payee_name = db.Column(db.String(120))   # referring doctor or radiologist name
    amount = db.Column(Money, default=0)  # accrued amount
    paid = db.Column(Money, default=0)    # amount settled so far
    status = db.Column(db.String(10), default='Unpaid')   # Unpaid / Partial / Paid
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    invoice = db.relationship('Invoice', backref='accruals')

    @property
    def balance(self):
        from .core.helpers import money_round
        return money_round((self.amount or 0) - (self.paid or 0))


class CommissionPayment(db.Model):
    """A settlement paid to a doctor or radiologist against one or more accruals."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(12))
    payee_kind = db.Column(db.String(16))    # doctor / radiologist
    payee_name = db.Column(db.String(120))
    amount = db.Column(Money, default=0)
    method = db.Column(db.String(20), default='Cash')
    ref = db.Column(db.String(40))
    note = db.Column(db.String(200))
    user = db.Column(db.String(80))
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))

# ---------------------------------------------------------------------------
# PACS — DICOM Study / Series / Instance hierarchy  (Phase 1, v8.0)
# ---------------------------------------------------------------------------
class ImgStudy(db.Model):
    """A DICOM study: the top of the Study -> Series -> Instance tree."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    rad_order_id = db.Column(db.Integer, db.ForeignKey('rad_order.id'))  # optional RIS link
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    study_uid = db.Column(db.String(120), index=True)
    accession = db.Column(db.String(40))
    modality = db.Column(db.String(16))          # CT/MR/CR/US/... (may be MIXED)
    description = db.Column(db.String(200))
    body_part = db.Column(db.String(40))
    referring = db.Column(db.String(80))
    study_date = db.Column(db.String(12))
    num_series = db.Column(db.Integer, default=0)
    num_instances = db.Column(db.Integer, default=0)
    size_kb = db.Column(db.Integer, default=0)
    status = db.Column(db.String(12), default='New')   # New / Reviewed
    uploaded_by = db.Column(db.String(50))
    created = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    patient = db.relationship('Patient')
    rad_order = db.relationship('RadOrder')
    series = db.relationship('ImgSeries', backref='study',
                             cascade='all, delete-orphan', order_by='ImgSeries.series_number')


class ImgSeries(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(db.Integer, db.ForeignKey('img_study.id'))
    series_uid = db.Column(db.String(120))
    series_number = db.Column(db.Integer, default=0)
    modality = db.Column(db.String(16))
    description = db.Column(db.String(200))
    body_part = db.Column(db.String(40))
    num_instances = db.Column(db.Integer, default=0)
    instances = db.relationship('ImgInstance', backref='series',
                                cascade='all, delete-orphan', order_by='ImgInstance.instance_number')


class ImgInstance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    series_id = db.Column(db.Integer, db.ForeignKey('img_series.id'))
    sop_uid = db.Column(db.String(120))
    instance_number = db.Column(db.Integer, default=0)
    frames = db.Column(db.Integer, default=1)      # rendered PNG frames (0 = pixels undecodable)
    rows = db.Column(db.Integer, default=0)
    cols = db.Column(db.Integer, default=0)
    win_center = db.Column(db.Float)
    win_width = db.Column(db.Float)
    pixel_spacing = db.Column(db.Float)            # mm per pixel, for length tool
    rel_dir = db.Column(db.String(200))            # storage folder relative to pacs root
    orig_name = db.Column(db.String(160))


class ImgModality(db.Model):
    """An imaging resource the RIS schedules onto: a machine or room.

    e.g. 'CT Scanner 1', 'Ultrasound Room 2'. Distinct from the DICOM modality
    code (CT/MR/US) which is stored as `modality` for grouping/worklist filters.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    modality = db.Column(db.String(16))            # CT / MRI / X-Ray / Ultrasound / ECG ...
    room = db.Column(db.String(40))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))


# ---------------------------------------------------------------------------
# Insurance — companies, cards, coverage, pre-auth, claims  (Phase 3, v8.0)
# ---------------------------------------------------------------------------
class Insurer(db.Model):
    """An insurance company / payer."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(20))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    contact_person = db.Column(db.String(80))
    address = db.Column(db.String(200))
    coverage_pct = db.Column(db.Float, default=80.0)     # default plan coverage
    ar_account = db.Column(db.String(10), default='1250')  # Insurance Receivable
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))


class InsuranceCard(db.Model):
    """A patient's policy with an insurer."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    insurer_id = db.Column(db.Integer, db.ForeignKey('insurer.id'))
    policy_no = db.Column(db.String(60))
    plan = db.Column(db.String(60))
    holder_name = db.Column(db.String(120))
    relation = db.Column(db.String(20), default='Self')   # Self/Spouse/Child/Other
    coverage_pct = db.Column(db.Float)                    # overrides insurer default when set
    valid_from = db.Column(db.String(12))
    valid_to = db.Column(db.String(12))
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))
    patient = db.relationship('Patient')
    insurer = db.relationship('Insurer')


class CoverageRule(db.Model):
    """Per-insurer coverage rule for a service category."""
    id = db.Column(db.Integer, primary_key=True)
    insurer_id = db.Column(db.Integer, db.ForeignKey('insurer.id'))
    category = db.Column(db.String(40))          # Laboratory / Radiology / Pharmacy / Consultation ...
    coverage_pct = db.Column(db.Float, default=80.0)
    copay_pct = db.Column(db.Float, default=0.0)
    annual_cap = db.Column(Money, default=0)     # 0 = no cap
    excluded = db.Column(db.Boolean, default=False)
    notes = db.Column(db.String(200))
    insurer = db.relationship('Insurer')


class PreAuth(db.Model):
    """Pre-authorization request to an insurer before a service is rendered."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    insurer_id = db.Column(db.Integer, db.ForeignKey('insurer.id'))
    card_id = db.Column(db.Integer, db.ForeignKey('insurance_card.id'))
    description = db.Column(db.String(200))
    est_amount = db.Column(Money, default=0)
    status = db.Column(db.String(12), default='Pending')   # Pending/Approved/Rejected
    auth_code = db.Column(db.String(40))
    valid_to = db.Column(db.String(12))
    reject_reason = db.Column(db.String(200))
    requested_by = db.Column(db.String(60))
    requested_at = db.Column(db.String(20), default=lambda: dt.date.today().isoformat())
    decided_at = db.Column(db.String(20))
    notes = db.Column(db.String(200))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    patient = db.relationship('Patient')
    insurer = db.relationship('Insurer')
    card = db.relationship('InsuranceCard')


class Claim(db.Model):
    """A claim submitted to an insurer against an invoice."""
    id = db.Column(db.Integer, primary_key=True)
    claim_no = db.Column(db.String(24), index=True)
    insurer_id = db.Column(db.Integer, db.ForeignKey('insurer.id'))
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    card_id = db.Column(db.Integer, db.ForeignKey('insurance_card.id'))
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    preauth_id = db.Column(db.Integer, db.ForeignKey('pre_auth.id'))
    claimed = db.Column(Money, default=0)
    approved = db.Column(Money, default=0)
    paid = db.Column(Money, default=0)
    # Draft / Submitted / Approved / Partial / Rejected / Paid
    status = db.Column(db.String(12), default='Draft')
    submitted_at = db.Column(db.String(20))
    responded_at = db.Column(db.String(20))
    reject_reason = db.Column(db.String(200))
    notes = db.Column(db.String(200))
    created_by = db.Column(db.String(60))
    created_at = db.Column(db.String(20), default=lambda: dt.date.today().isoformat())
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    insurer = db.relationship('Insurer')
    patient = db.relationship('Patient')
    card = db.relationship('InsuranceCard')
    invoice = db.relationship('Invoice')


# ---------------------------------------------------------------------------
# LIS — analyzer instruments & structured results  (Phase 4, v8.0)
# ---------------------------------------------------------------------------
class LabInstrument(db.Model):
    """A laboratory analyzer the LIS receives results from (HL7 / CSV)."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)      # e.g. Sysmex XN-550
    code = db.Column(db.String(20))                      # short id used in HL7 MSH-3
    kind = db.Column(db.String(40))                      # Hematology / Chemistry / ...
    connection = db.Column(db.String(120))               # host:port or serial note
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))


class LabResultValue(db.Model):
    """One structured analyte result on a LabOrder (manual or analyzer-imported)."""
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('lab_order.id'))
    name = db.Column(db.String(80))
    value = db.Column(db.String(40))
    unit = db.Column(db.String(20))
    ref_low = db.Column(db.Float)
    ref_high = db.Column(db.Float)
    ref_text = db.Column(db.String(40))                  # raw reference range if non-numeric
    flag = db.Column(db.String(4))                       # '', H, L, HH, LL (critical), A
    source = db.Column(db.String(10), default='Manual')  # Manual / Analyzer
    instrument_id = db.Column(db.Integer, db.ForeignKey('lab_instrument.id'))
    verified = db.Column(db.Boolean, default=False)
    verified_by = db.Column(db.String(60))
    created_at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    order = db.relationship('LabOrder', backref=db.backref('values', cascade='all, delete-orphan'))
    instrument = db.relationship('LabInstrument')


# ---------------------------------------------------------------------------
# Emergency Department — visits, triage, vitals, notes  (Phase 7, v8.0)
# ---------------------------------------------------------------------------
class EDVisit(db.Model):
    """An emergency-department encounter (triage → treatment → disposition)."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))   # nullable: unknown patient
    unknown_name = db.Column(db.String(120))     # for unidentified arrivals
    age = db.Column(db.String(12))
    gender = db.Column(db.String(10))
    arrival_at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    mode = db.Column(db.String(20), default='Walk-in')   # Walk-in / Ambulance / Referral
    chief_complaint = db.Column(db.String(200))
    # triage: 1 Resuscitation, 2 Emergency, 3 Urgent, 4 Less-urgent, 5 Non-urgent
    triage_level = db.Column(db.Integer)
    triage_by = db.Column(db.String(60))
    triage_at = db.Column(db.String(20))
    # Waiting / InTreatment / Observation / Admitted / Discharged / Referred / LAMA / Deceased
    status = db.Column(db.String(14), default='Waiting')
    attending = db.Column(db.String(120))
    bed = db.Column(db.String(30))
    disposition = db.Column(db.String(30))
    disposition_at = db.Column(db.String(20))
    disposition_note = db.Column(db.String(200))
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    # triage vitals
    bp = db.Column(db.String(12))
    pulse = db.Column(db.Integer)
    temp_c = db.Column(db.Float)
    spo2 = db.Column(db.Integer)
    resp = db.Column(db.Integer)
    gcs = db.Column(db.Integer)
    pain = db.Column(db.Integer)
    created_by = db.Column(db.String(60))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    patient = db.relationship('Patient')
    invoice = db.relationship('Invoice')
    notes = db.relationship('EDNote', backref='visit', cascade='all, delete-orphan',
                            order_by='EDNote.id')
    vitals = db.relationship('EDVital', backref='visit', cascade='all, delete-orphan',
                             order_by='EDVital.id')

    @property
    def display_name(self):
        return (self.patient.name if self.patient else None) or self.unknown_name or 'Unknown'


class EDVital(db.Model):
    """A serial set of vital signs recorded during an ED visit."""
    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey('ed_visit.id'))
    at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    bp = db.Column(db.String(12))
    pulse = db.Column(db.Integer)
    temp_c = db.Column(db.Float)
    spo2 = db.Column(db.Integer)
    resp = db.Column(db.Integer)
    gcs = db.Column(db.Integer)
    pain = db.Column(db.Integer)
    by = db.Column(db.String(60))


class EDNote(db.Model):
    """A clinical / nursing / procedure note on an ED visit."""
    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey('ed_visit.id'))
    at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    category = db.Column(db.String(16), default='Doctor')   # Nursing / Doctor / Procedure
    author = db.Column(db.String(60))
    text = db.Column(db.Text)


# ---------------------------------------------------------------------------
# Inpatient (IPD) — wards, beds, admissions, notes, MAR, transfers (Phase 8)
# ---------------------------------------------------------------------------
class Ward(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    kind = db.Column(db.String(20))              # General/Private/ICU/Maternity/Pediatric
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))


class Bed(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ward_id = db.Column(db.Integer, db.ForeignKey('ward.id'))
    label = db.Column(db.String(30), nullable=False)     # bed number/label
    status = db.Column(db.String(14), default='Available')   # Available/Occupied/Maintenance
    daily_rate = db.Column(Money, default=0)
    active = db.Column(db.Boolean, default=True)
    ward = db.relationship('Ward')


class Admission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    ward_id = db.Column(db.Integer, db.ForeignKey('ward.id'))
    bed_id = db.Column(db.Integer, db.ForeignKey('bed.id'))
    ed_visit_id = db.Column(db.Integer, db.ForeignKey('ed_visit.id'))   # ED → IPD handoff
    admitted_at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    admitting_doctor = db.Column(db.String(120))
    attending = db.Column(db.String(120))
    diagnosis = db.Column(db.String(200))
    status = db.Column(db.String(12), default='Admitted')   # Admitted / Discharged
    discharge_at = db.Column(db.String(20))
    discharge_type = db.Column(db.String(20))               # Home/Referred/LAMA/Deceased
    discharge_summary = db.Column(db.Text)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    created_by = db.Column(db.String(60))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    patient = db.relationship('Patient')
    ward = db.relationship('Ward')
    bed = db.relationship('Bed')
    invoice = db.relationship('Invoice')
    ipd_notes = db.relationship('IPDNote', backref='admission', cascade='all, delete-orphan',
                                order_by='IPDNote.id')
    meds = db.relationship('MedAdmin', backref='admission', cascade='all, delete-orphan',
                           order_by='MedAdmin.id')
    transfers = db.relationship('BedTransfer', backref='admission', cascade='all, delete-orphan',
                                order_by='BedTransfer.id')

    @property
    def days(self):
        try:
            start = dt.datetime.strptime((self.admitted_at or '')[:16], '%Y-%m-%d %H:%M')
            end = (dt.datetime.strptime(self.discharge_at[:16], '%Y-%m-%d %H:%M')
                   if self.discharge_at else dt.datetime.now())
            return max((end - start).days, 0) + 1
        except Exception:
            return 1


class IPDNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey('admission.id'))
    at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    category = db.Column(db.String(16), default='Nursing')   # Nursing / Doctor / Vitals
    author = db.Column(db.String(60))
    text = db.Column(db.Text)


class MedAdmin(db.Model):
    """Medication Administration Record (MAR) entry."""
    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey('admission.id'))
    at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    medicine = db.Column(db.String(120))
    dose = db.Column(db.String(60))
    route = db.Column(db.String(20))            # PO/IV/IM/SC/...
    given_by = db.Column(db.String(60))
    note = db.Column(db.String(200))


class BedTransfer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey('admission.id'))
    at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    from_bed = db.Column(db.String(60))
    to_bed = db.Column(db.String(60))
    by = db.Column(db.String(60))
    reason = db.Column(db.String(200))


# ---------------------------------------------------------------------------
# Operation Theatre (OT) — theatres, surgeries, checklist, notes  (Phase 9)
# ---------------------------------------------------------------------------
class Theatre(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)      # OT-1, OT-2 ...
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))


class Surgery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    admission_id = db.Column(db.Integer, db.ForeignKey('admission.id'))   # optional IPD link
    theatre_id = db.Column(db.Integer, db.ForeignKey('theatre.id'))
    procedure = db.Column(db.String(200))
    surgeon = db.Column(db.String(120))
    assistant = db.Column(db.String(120))
    anesthetist = db.Column(db.String(120))
    anesthesia_type = db.Column(db.String(30))           # GA / Spinal / Local / Sedation
    priority = db.Column(db.String(12), default='Elective')   # Elective / Emergency
    scheduled_at = db.Column(db.String(20))
    started_at = db.Column(db.String(20))
    ended_at = db.Column(db.String(20))
    status = db.Column(db.String(12), default='Scheduled')   # Scheduled/InProgress/Completed/Cancelled
    diagnosis = db.Column(db.String(200))
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    created_by = db.Column(db.String(60))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    patient = db.relationship('Patient')
    theatre = db.relationship('Theatre')
    admission = db.relationship('Admission')
    invoice = db.relationship('Invoice')
    checklist = db.relationship('OTChecklistItem', backref='surgery',
                                cascade='all, delete-orphan', order_by='OTChecklistItem.id')
    op_notes = db.relationship('SurgicalNote', backref='surgery',
                               cascade='all, delete-orphan', order_by='SurgicalNote.id')
    items = db.relationship('SurgeryItem', backref='surgery',
                            cascade='all, delete-orphan', order_by='SurgeryItem.id')


class OTChecklistItem(db.Model):
    """WHO Surgical Safety Checklist item (Sign-in / Time-out / Sign-out)."""
    id = db.Column(db.Integer, primary_key=True)
    surgery_id = db.Column(db.Integer, db.ForeignKey('surgery.id'))
    phase = db.Column(db.String(10))             # SignIn / TimeOut / SignOut
    item = db.Column(db.String(160))
    checked = db.Column(db.Boolean, default=False)
    by = db.Column(db.String(60))
    at = db.Column(db.String(20))


class SurgicalNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    surgery_id = db.Column(db.Integer, db.ForeignKey('surgery.id'))
    kind = db.Column(db.String(16), default='Operative')   # Operative/Anesthesia/PostOp/Nursing
    at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    author = db.Column(db.String(60))
    text = db.Column(db.Text)


class SurgeryItem(db.Model):
    """Instrument / swab / consumable used, with safety counts."""
    id = db.Column(db.Integer, primary_key=True)
    surgery_id = db.Column(db.Integer, db.ForeignKey('surgery.id'))
    name = db.Column(db.String(120))
    count_before = db.Column(db.Integer)
    count_after = db.Column(db.Integer)
    note = db.Column(db.String(200))


# ---------------------------------------------------------------------------
# Dialysis — machines, sessions, treatment record, lab monitoring  (Phase 10)
# ---------------------------------------------------------------------------
class DialysisMachine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)      # HD-1, HD-2 ...
    status = db.Column(db.String(14), default='Available')   # Available/InUse/Maintenance
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))


class DialysisSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    machine_id = db.Column(db.Integer, db.ForeignKey('dialysis_machine.id'))
    scheduled_at = db.Column(db.String(20))
    started_at = db.Column(db.String(20))
    ended_at = db.Column(db.String(20))
    status = db.Column(db.String(12), default='Scheduled')  # Scheduled/InProgress/Completed/Cancelled/Missed
    access_type = db.Column(db.String(20))               # AV Fistula / Catheter / Graft
    dialyzer = db.Column(db.String(40))
    duration_min = db.Column(db.Integer)
    dry_weight = db.Column(db.Float)
    pre_weight = db.Column(db.Float)
    post_weight = db.Column(db.Float)
    uf_goal = db.Column(db.Float)                        # litres
    uf_achieved = db.Column(db.Float)
    blood_flow = db.Column(db.Integer)                   # ml/min
    heparin = db.Column(db.String(40))
    pre_bp = db.Column(db.String(12))
    post_bp = db.Column(db.String(12))
    complications = db.Column(db.String(200))
    nurse = db.Column(db.String(60))
    notes = db.Column(db.Text)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    created_by = db.Column(db.String(60))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    patient = db.relationship('Patient')
    machine = db.relationship('DialysisMachine')
    invoice = db.relationship('Invoice')
    labs = db.relationship('DialysisLab', backref='session',
                           cascade='all, delete-orphan', order_by='DialysisLab.id')


class DialysisLab(db.Model):
    """Pre/Post lab monitoring value for a dialysis session."""
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('dialysis_session.id'))
    phase = db.Column(db.String(6), default='Pre')       # Pre / Post
    name = db.Column(db.String(40))                      # Hb, K+, Urea, Creatinine ...
    value = db.Column(db.String(30))
    unit = db.Column(db.String(20))


# ---------------------------------------------------------------------------
# Ambulance — vehicles, drivers, dispatch, location tracking  (Phase 11)
# ---------------------------------------------------------------------------
class Ambulance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(20))
    label = db.Column(db.String(60), nullable=False)     # e.g. Ambulance 1
    kind = db.Column(db.String(20))                      # BLS / ALS / Patient transport
    status = db.Column(db.String(14), default='Available')   # Available/OnTrip/Maintenance
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))


class AmbulanceDriver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30))
    license_no = db.Column(db.String(40))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))


class Dispatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('ambulance.id'))
    driver_id = db.Column(db.Integer, db.ForeignKey('ambulance_driver.id'))
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    caller_name = db.Column(db.String(120))
    caller_phone = db.Column(db.String(30))
    pickup = db.Column(db.String(200))
    destination = db.Column(db.String(200))
    priority = db.Column(db.String(14), default='Emergency')   # Emergency / Non-emergency
    # Requested / Dispatched / OnScene / Transporting / Completed / Cancelled
    status = db.Column(db.String(14), default='Requested')
    requested_at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    dispatched_at = db.Column(db.String(20))
    onscene_at = db.Column(db.String(20))
    transporting_at = db.Column(db.String(20))
    completed_at = db.Column(db.String(20))
    reason = db.Column(db.String(200))
    last_lat = db.Column(db.Float)
    last_lng = db.Column(db.Float)
    last_loc_at = db.Column(db.String(20))
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    created_by = db.Column(db.String(60))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    vehicle = db.relationship('Ambulance')
    driver = db.relationship('AmbulanceDriver')
    patient = db.relationship('Patient')
    invoice = db.relationship('Invoice')
    breadcrumbs = db.relationship('DispatchLocation', backref='dispatch',
                                  cascade='all, delete-orphan', order_by='DispatchLocation.id')


class DispatchLocation(db.Model):
    """A location breadcrumb for a dispatch (manual or GPS-device push)."""
    id = db.Column(db.Integer, primary_key=True)
    dispatch_id = db.Column(db.Integer, db.ForeignKey('dispatch.id'))
    at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    note = db.Column(db.String(120))
    source = db.Column(db.String(10), default='Manual')   # Manual / GPS


# ---------------------------------------------------------------------------
# Blood Bank expansion — cross-match & transfusion  (Phase 12, v8.0)
# (builds on existing Donor + BloodUnit)
# ---------------------------------------------------------------------------
class CrossMatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    unit_id = db.Column(db.Integer, db.ForeignKey('blood_unit.id'))
    result = db.Column(db.String(14))            # Compatible / Incompatible
    technician = db.Column(db.String(60))
    date = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    note = db.Column(db.String(200))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    patient = db.relationship('Patient')
    unit = db.relationship('BloodUnit')


class Transfusion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'))
    unit_id = db.Column(db.Integer, db.ForeignKey('blood_unit.id'))
    crossmatch_id = db.Column(db.Integer, db.ForeignKey('cross_match.id'))
    started_at = db.Column(db.String(20), default=lambda: dt.datetime.now().strftime('%Y-%m-%d %H:%M'))
    ended_at = db.Column(db.String(20))
    volume_ml = db.Column(db.Integer)
    reaction = db.Column(db.String(200))         # None / description of reaction
    by = db.Column(db.String(60))
    note = db.Column(db.String(200))
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'))
    patient = db.relationship('Patient')
    unit = db.relationship('BloodUnit')


# ---------------------------------------------------------------------------
# Universal Global Search — recent queries & pinned records  (Phase 16, v8.0)
# ---------------------------------------------------------------------------
class SearchLog(db.Model):
    """One row per global-search query (for recent + frequently-used)."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), index=True)
    q = db.Column(db.String(120))
    module = db.Column(db.String(40))          # '' = global search; else per-module list
    at = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))


class SavedSearch(db.Model):
    """An Odoo-style saved search (favorite) for a module list view."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), index=True)
    module = db.Column(db.String(40), index=True)
    name = db.Column(db.String(80))
    args = db.Column(db.String(600))           # the querystring (filters+group+sort+adv)
    pinned = db.Column(db.Boolean, default=False)
    is_default = db.Column(db.Boolean, default=False)
    shared = db.Column(db.Boolean, default=False)   # visible to all users of the module
    at = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))


class BankStatement(db.Model):
    """An imported bank statement to reconcile against the books."""
    id = db.Column(db.Integer, primary_key=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_account.id'))
    name = db.Column(db.String(120))
    date = db.Column(db.String(12))
    filename = db.Column(db.String(200))
    opening = db.Column(Money, default=0)
    closing = db.Column(Money, default=0)
    status = db.Column(db.String(20), default='Draft')   # Draft / Reconciled / Approved
    created_by = db.Column(db.String(60))
    created_at = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    approved_by = db.Column(db.String(60))
    approved_at = db.Column(db.String(30))
    bank_account = db.relationship('BankAccount')
    lines = db.relationship('BankStatementLine', backref='statement',
                            cascade='all, delete-orphan', order_by='BankStatementLine.id')


class BankStatementLine(db.Model):
    """One transaction on an imported bank statement."""
    id = db.Column(db.Integer, primary_key=True)
    statement_id = db.Column(db.Integer, db.ForeignKey('bank_statement.id'))
    date = db.Column(db.String(12))
    label = db.Column(db.String(200))
    ref = db.Column(db.String(80))
    amount = db.Column(Money, default=0)          # signed: + deposit, - withdrawal
    matched = db.Column(db.Boolean, default=False)
    match_type = db.Column(db.String(12))         # auto / manual / payment / writeoff
    match_note = db.Column(db.String(200))
    journal_entry_id = db.Column(db.Integer)
    is_duplicate = db.Column(db.Boolean, default=False)


class PinnedRecord(db.Model):
    """A record a user pinned to the top of global search."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), index=True)
    url = db.Column(db.String(300))
    title = db.Column(db.String(200))
    icon = db.Column(db.String(8))
    module = db.Column(db.String(40))
    at = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
    __table_args__ = (db.UniqueConstraint('username', 'url', name='uq_pin_user_url'),)


class RecordArchive(db.Model):
    """Lifecycle ledger for archived records.

    The original row remains available for audit and financial history. This
    table records who archived it, why, a safe JSON snapshot, and whether it
    was restored. Hard deletion is intentionally handled separately and is
    blocked for protected financial/clinical entities.
    """
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(80), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    label = db.Column(db.String(200))
    snapshot = db.Column(db.Text)
    reason = db.Column(db.String(255), nullable=False)
    archived_by = db.Column(db.String(80), nullable=False)
    archived_at = db.Column(db.DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None), nullable=False)
    restored_by = db.Column(db.String(80))
    restored_at = db.Column(db.DateTime)
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)


# ---------------------------------------------------------------------------
# Stamp who created an invoice (Created by) automatically on insert, so every
# creation path (billing, referral, pharmacy, ED/IPD/OT, API, …) records it
# without each one needing to set it. Falls back gracefully outside a request.
from sqlalchemy import event as _sa_event


@_sa_event.listens_for(Invoice, 'before_insert')
def _stamp_invoice_creator(mapper, connection, target):
    if getattr(target, 'created_by', None):
        return
    try:
        from .core.security import cur_user
        u = cur_user()
        if u:
            target.created_by = (u.name or u.username)
    except Exception:
        pass
    if not getattr(target, 'created_at', None):
        try:
            target.created_at = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass


@_sa_event.listens_for(JournalEntry, 'before_insert')
def _stamp_journal_creator(mapper, connection, target):
    """Record who posted each journal entry, so the General Ledger can be filtered
    by 'Created by'. A reversal keeps the posted_by it was given explicitly."""
    if getattr(target, 'posted_by', None):
        return
    try:
        from .core.security import cur_user
        u = cur_user()
        if u:
            target.posted_by = (u.name or u.username)
    except Exception:
        pass
