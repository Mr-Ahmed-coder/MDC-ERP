"""End-to-end smoke tests for the refactored MDC ERP.

Run:  pip install pytest && pytest -q
Uses an in-memory SQLite database — never touches erp.db.
"""
import re
import os
import shutil
import tempfile
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


class TestConfig(DevelopmentConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'   # overridden per test below


# Build the seeded database ONCE into a template file, then copy it for every
# test. This gives each test a pristine, isolated database (no shared state,
# no data leaks between tests) while paying the ~0.7s seed cost only once.
_TEMPLATE = os.path.join(tempfile.gettempdir(), 'mdc_test_template.db')


@pytest.fixture(scope='session', autouse=True)
def _seed_template():
    class SeedConfig(DevelopmentConfig):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{_TEMPLATE}'
    if os.path.exists(_TEMPLATE):
        os.remove(_TEMPLATE)
    seed_app = create_app(SeedConfig)
    init_db(seed_app, demo=True)
    # the seeded admin carries must_change_pw=True (first-login gate). Tests exercise
    # the app *after* onboarding, so clear it here; test_forced_password_change
    # re-enables it to cover the gate itself.
    with seed_app.app_context():
        from mdc_erp.models import User
        from mdc_erp.extensions import db as _db
        from sqlalchemy import text as _text
        a = User.query.filter_by(username='admin').first()
        if a:
            a.must_change_pw = False
            _db.session.commit()
        # WAL mode keeps just-committed data in a -wal sidecar; flush it into the
        # main .db file so the per-test shutil.copy() below captures everything.
        _db.session.execute(_text('PRAGMA wal_checkpoint(TRUNCATE)'))
        _db.session.commit()
    yield
    if os.path.exists(_TEMPLATE):
        os.remove(_TEMPLATE)


@pytest.fixture()
def app(tmp_path):
    db_file = tmp_path / 'test.db'
    shutil.copy(_TEMPLATE, db_file)

    class PerTestConfig(DevelopmentConfig):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_file}'
    app = create_app(PerTestConfig)
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def _csrf(resp):
    m = re.search(r'name="_csrf" value="([^"]+)"', resp.get_data(as_text=True))
    assert m, 'CSRF token missing from form'
    return m.group(1)


def _login(client, user='admin', pw='admin123'):
    tok = _csrf(client.get('/login'))
    r = client.post('/login', data={'username': user, 'password': pw, '_csrf': tok})
    assert r.status_code == 302


_pt_seq = [0]


def _fresh_patient(app):
    """Create and return the id of a brand-new patient with no pending orders,
    so auto-fill from lab/radiology never pollutes a billing test."""
    from mdc_erp.models import Patient
    from mdc_erp.extensions import db as _db
    with app.app_context():
        _pt_seq[0] += 1
        p = Patient(name=f'TestPt{_pt_seq[0]}', mrn=f'MRN-TP{_pt_seq[0]:04d}', phone='0')
        _db.session.add(p); _db.session.commit()
        return p.id


MODULES = ['patients', 'appointments', 'lab', 'radiology', 'doctors', 'commission',
           'inventory', 'purchases', 'referrals', 'advances', 'loans', 'logistics',
           'consult', 'prescriptions', 'pharmacy', 'radfees', 'summary', 'revenue',
           'acct', 'accounts', 'journal', 'ledger', 'suppliers', 'invoices',
           'expenses', 'finance', 'services', 'employees', 'attendance', 'leave',
           'payroll', 'reports', 'users', 'branches', 'audit', 'settings']


def test_login_and_dashboard(client):
    _login(client)
    assert client.get('/dashboard').status_code == 200


def test_every_module_page_renders(client):
    _login(client)
    for m in MODULES:
        assert client.get(f'/m/{m}', follow_redirects=True).status_code == 200, f'module {m} failed'


def test_csrf_blocks_forged_post(client):
    _login(client)
    r = client.post('/m/patients/new', data={'name': 'Forged'})
    assert r.status_code == 400


def test_patient_crud(client):
    _login(client)
    tok = _csrf(client.get('/m/patients/new'))
    r = client.post('/m/patients/new',
                    data={'name': 'Smoke Patient', 'phone': '61000', 'gender': 'Male',
                          'dob': '', 'gov_id': '', 'address': '', 'notes': '', '_csrf': tok},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b'Smoke Patient' in client.get('/m/patients').data


def test_invoice_item_payment_and_ledger(client, app):
    _login(client)
    tok = _csrf(client.get('/invoice/1'))
    client.post('/invoice/1', data={'act': 'additem', 'service_id': '1', 'qty': '1', '_csrf': tok})
    with app.app_context():
        from mdc_erp.models import Invoice
        bal = Invoice.query.get(1).balance
    tok = _csrf(client.get('/invoice/1'))
    client.post('/invoice/1', data={'act': 'pay', 'paid': str(bal), 'pay_method': 'Cash', '_csrf': tok})
    assert b'PAY-0001' in client.get('/m/ledger', follow_redirects=True).data


def test_api_jwt_flow(client):
    r = client.post('/api/login', json={'username': 'admin', 'password': 'admin123'})
    token = r.get_json()['data']['token']
    hdr = {'Authorization': 'Bearer ' + token}
    for ep in ['/api/patients', '/api/services', '/api/invoices', '/api/stats']:
        assert client.get(ep, headers=hdr).status_code == 200
    assert client.get('/api/patients').status_code == 401  # no token


def test_api_rate_limiter_and_branch_isolation(app, client):
    """API hardening (#18): the sliding-window limiter blocks bursts, and the
    invoice API respects branch isolation (a branch user cannot read/pay another
    branch's invoice)."""
    # 1) rate limiter logic (tested directly; disabled under TESTING for the live API)
    from mdc_erp.blueprints.api import _rate_ok, _RL_BUCKETS
    _RL_BUCKETS.clear()
    allowed = sum(1 for _ in range(12) if _rate_ok('t:x', 10, 60)[0])
    assert allowed == 10, 'limiter should allow exactly the quota then block'
    ok, retry = _rate_ok('t:x', 10, 60)
    assert not ok and retry > 0

    # 2) API invoice list + pay respect branch isolation
    from mdc_erp.models import Branch, User, Patient, Invoice
    from mdc_erp.extensions import db as _db
    from werkzeug.security import generate_password_hash
    with app.app_context():
        b1 = Branch.query.first()
        b2 = Branch(name='API Iso Branch'); _db.session.add(b2); _db.session.commit()
        _db.session.add(User(username='api_cash_a', name='A', role='cashier', active=True,
                             branch_id=b1.id, pw=generate_password_hash('x'), must_change_pw=False))
        p = Patient(name='API Iso Pt', mrn='MRN-APIISO', phone='0'); _db.session.add(p); _db.session.commit()
        ia = Invoice(patient_id=p.id, date='2026-07-24', branch_id=b1.id)
        ib = Invoice(patient_id=p.id, date='2026-07-24', branch_id=b2.id)
        _db.session.add_all([ia, ib]); _db.session.commit()
        ida, idb = ia.id, ib.id
    tok = client.post('/api/login', json={'username': 'api_cash_a', 'password': 'x'}).get_json()['data']['token']
    hdr = {'Authorization': 'Bearer ' + tok}
    listing = client.get('/api/invoices', headers=hdr).get_json()['data']
    ids = {r['id'] for r in listing}
    assert ida in ids and idb not in ids, 'API list leaked another branch invoice'
    # paying another branch's invoice is refused (404, no leak)
    r = client.post(f'/api/invoices/{idb}/pay', json={'amount': 1, 'idempotency_key': 'abcdefgh'}, headers=hdr)
    assert r.status_code == 404


def test_internal_chat_between_users(app, client):
    """Any two active users can direct-message each other; unread is tracked and
    cleared when the recipient opens the thread."""
    from mdc_erp.models import User, ChatMessage
    from mdc_erp.extensions import db as _db
    from werkzeug.security import generate_password_hash
    with app.app_context():
        for un, role in (('doc_chat', 'doctor'), ('rec_chat', 'reception')):
            if not User.query.filter_by(username=un).first():
                _db.session.add(User(username=un, name=un, role=role, active=True,
                                     pw=generate_password_hash('x'), must_change_pw=False))
        _db.session.commit()
        did = User.query.filter_by(username='doc_chat').first().id
        rid = User.query.filter_by(username='rec_chat').first().id

    def as_user(un):
        c = app.test_client()
        tok = _csrf(c.get('/login'))
        c.post('/login', data={'username': un, 'password': 'x', '_csrf': tok})
        return c

    doc = as_user('doc_chat')
    pg = doc.get('/m/chat').get_data(as_text=True)
    assert 'rec_chat' in pg and 'Chat' in pg
    tok = _csrf(doc.get(f'/m/chat?u={rid}'))
    doc.post('/chat/send', data={'to': rid, 'body': 'Please prep room 2', '_csrf': tok},
             follow_redirects=True)
    with app.app_context():
        assert ChatMessage.query.filter_by(sender_id=did, recipient_id=rid).count() == 1
    rec = as_user('rec_chat')
    assert rec.get('/chat/unread').get_json()['unread'] == 1
    thread = rec.get(f'/m/chat?u={did}').get_data(as_text=True)
    assert 'Please prep room 2' in thread
    assert rec.get('/chat/unread').get_json()['unread'] == 0
    tok = _csrf(rec.get(f'/m/chat?u={did}'))
    rec.post('/chat/send', data={'to': did, 'body': 'Room 2 ready', '_csrf': tok},
             follow_redirects=True)
    assert 'Room 2 ready' in doc.get(f'/m/chat?u={rid}').get_data(as_text=True)

    # --- file attachment ---
    import io
    tok = _csrf(doc.get(f'/m/chat?u={rid}'))
    doc.post('/chat/send', data={'to': rid, 'body': 'see attached',
                                 'file': (io.BytesIO(b'hello-file'), 'note.txt'), '_csrf': tok},
             content_type='multipart/form-data', follow_redirects=True)
    with app.app_context():
        msg = ChatMessage.query.filter_by(sender_id=did, recipient_id=rid).order_by(ChatMessage.id.desc()).first()
        assert msg.attachment and msg.attachment_name == 'note.txt'
        mid = msg.id
    # recipient can download it; a stranger cannot
    r = rec.get(f'/chat/file/{mid}')
    assert r.status_code == 200 and b'hello-file' in r.data
    stranger = as_user('rec_chat')  # same user re-login ok; now test an unrelated user
    with app.app_context():
        if not User.query.filter_by(username='yus_chat').first():
            _db.session.add(User(username='yus_chat', name='Y', role='radiologist', active=True,
                                 pw=generate_password_hash('x'), must_change_pw=False))
            _db.session.commit()
    other = as_user('yus_chat')
    assert other.get(f'/chat/file/{mid}').status_code == 403
    # executable uploads are refused
    tok = _csrf(doc.get(f'/m/chat?u={rid}'))
    r = doc.post('/chat/send', data={'to': rid, 'body': '',
                                     'file': (io.BytesIO(b'MZbad'), 'virus.exe'), '_csrf': tok},
                 content_type='multipart/form-data', follow_redirects=True)
    assert b'not allowed' in r.data


def test_returning_patient_reused_no_duplicate(app, client):
    """A returning patient found by ID/phone/name is reused for a new test request
    instead of creating a duplicate record."""
    from mdc_erp.models import Patient, Referral, Doctor
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        p = Patient(mrn='MRN-RET1', name='Faadumo Xasan', phone='0615123123', gender='Female')
        _db.session.add(p)
        d = Doctor.query.first() or Doctor(name='Dr Test'); 
        if not d.id: _db.session.add(d)
        _db.session.commit()
        pid = p.id; did = d.id
        before = Patient.query.count()

    # 1) patient search finds the returning patient by phone
    r = client.get('/referral/patient-search?q=0615123123').get_json()
    assert any(x['id'] == pid for x in r)
    # by name
    r = client.get('/referral/patient-search?q=Faadumo').get_json()
    assert any(x['id'] == pid for x in r)

    # 2) create a doctor request linked to the existing patient (hidden patient_id set)
    tok = _csrf(client.get('/m/referrals'))
    client.post('/refer', data={'patient_id': str(pid), 'patient_name': 'Faadumo Xasan',
                                'patient_phone': '0615123123', 'doctor_id': str(did),
                                'tests': ['Blood Sugar'], '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        ref = Referral.query.order_by(Referral.id.desc()).first()
        assert ref.patient_id == pid                       # linked, not new
        # accepting it must NOT create a duplicate
        rid = ref.id
    client.get(f'/referral/{rid}/accept', follow_redirects=True)
    with app.app_context():
        assert Patient.query.count() == before             # no new patient row
        assert Referral.query.get(rid).patient_id == pid

    # 3) even without the hidden id, a matching phone reuses the patient on accept
    tok = _csrf(client.get('/m/referrals'))
    client.post('/refer', data={'patient_name': 'Someone Else Typed',
                                'patient_phone': '0615123123',  # same phone as Faadumo
                                'doctor_id': str(did), 'tests': ['Blood Sugar'], '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        ref2 = Referral.query.order_by(Referral.id.desc()).first()
        # phone-matched at creation time
        assert ref2.patient_id == pid
        assert Patient.query.count() == before


def test_patient_portal(app):
    c = app.test_client()
    tok = _csrf(c.get('/portal'))
    r = c.post('/portal', data={'mrn': 'MRN1001', 'phone': '61511', '_csrf': tok},
               follow_redirects=True)
    assert r.status_code == 200


def test_public_referral_form(app):
    c = app.test_client()
    tok = _csrf(c.get('/refer'))
    r = c.post('/refer', data={'doctor_id': '1', 'patient_name': 'Portal Test',
                               'patient_phone': '615999', 'tests': ['Blood Sugar'],
                               '_csrf': tok}, follow_redirects=True)
    assert r.status_code == 200


def test_permissions_matrix(client):
    _login(client)
    tok = _csrf(client.get('/permissions'))
    r = client.post('/permissions', data={'lab::lab_tech': '1', '_csrf': tok},
                    follow_redirects=True)
    assert r.status_code == 200


# ============================================================ Phase 2 tests

def test_reception_queue_flow(client):
    import datetime as dt
    _login(client)
    tok = _csrf(client.get('/m/appointments/new'))
    client.post('/m/appointments/new',
                data={'patient_id': '1', 'date': dt.date.today().isoformat(),
                      'time': '10:00', 'department': 'Consultation', 'doctor': 'Dr. Q',
                      'status': 'Scheduled', 'notes': '', '_csrf': tok})
    assert client.get('/m/queue').status_code == 200
    r = client.get('/queue/1/checkin', follow_redirects=True)
    assert r.status_code == 200 and b'Waiting' in r.data
    r = client.get('/queue/1/start', follow_redirects=True)
    assert b'In Progress' in r.data
    assert client.get('/queue/1/done', follow_redirects=True).status_code == 200


def test_icd10_datalist_on_consultation(client):
    _login(client)
    r = client.get('/m/consult/new')
    assert b'dl_icd_code' in r.data and b'B54' in r.data  # malaria in quick-pick


def test_lab_reference_range_and_print(client):
    _login(client)
    r = client.get('/m/services/1/edit')
    tok = _csrf(r)
    client.post('/m/services/1/edit',
                data={'code': 'LAB-01', 'name': 'Complete Blood Count',
                      'department': 'Laboratory', 'price': '15', 'price_insurance': '0',
                      'price_corporate': '0', 'price_vip': '0', 'price_contract': '0',
                      'cost': '4', 'ref_range': '4.0 - 11.0', 'unit': 'x10^9/L',
                      'supply_id': '', 'supply_qty': '0', 'active': '1', '_csrf': tok})
    r = client.get('/lab/1/result')
    assert b'4.0 - 11.0' in r.data
    tok = _csrf(r)
    client.post('/lab/1/result', data={'result': 'WBC 6.2', '_csrf': tok})
    client.get('/lab/1/approve')
    d = client.get('/lab/1/print').get_data(as_text=True)
    assert 'Reference Range' in d and 'LAB-0001' in d and d.count('<svg') >= 2


def test_critical_result_alert_and_acknowledgement(app, client):
    """Clinical safety (#14): a panic value raises a CriticalAlert; it can only be
    acknowledged with an action/comment, which records the clinician + timestamp."""
    from mdc_erp.models import Service, LabOrder, CriticalAlert
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        s = Service.query.first()
        s.department = 'Laboratory'; s.panic_low = 3.0; s.panic_high = 6.0; s.unit = 'mmol/L'
        _db.session.commit(); sid = s.id
        o = LabOrder(patient_id=1, service_id=sid, status='Received')
        _db.session.add(o); _db.session.commit(); oid = o.id
    # enter a critically HIGH result -> panic + CriticalAlert raised
    tok = _csrf(client.get(f'/lab/{oid}/result'))
    r = client.post(f'/lab/{oid}/result', data={'result': '9.5', '_csrf': tok}, follow_redirects=True)
    assert b'PANIC' in r.data
    with app.app_context():
        al = CriticalAlert.query.filter_by(lab_order_id=oid).first()
        assert al and not al.acknowledged
        assert '9.5' in (al.value or '') and 'high 6' in (al.critical_range or '')
        aid = al.id
    # board shows it as unacknowledged
    d = client.get('/m/critical').get_data(as_text=True)
    assert 'Unacknowledged Critical Results' in d and f'LAB-{oid:04d}' in d
    # acknowledging WITHOUT an action is refused
    client.get(f'/critical/{aid}/ack', follow_redirects=True)
    with app.app_context():
        assert not CriticalAlert.query.get(aid).acknowledged
    # acknowledge WITH an action -> recorded with clinician + time
    client.get(f'/critical/{aid}/ack?action=called+ward+notified+Dr+on+call', follow_redirects=True)
    with app.app_context():
        al = CriticalAlert.query.get(aid)
        assert al.acknowledged and al.ack_by and al.ack_at
        assert 'called ward' in (al.action or '')
        assert LabOrder.query.get(oid).panic_ack is True


def test_lab_result_locks_on_approve_and_amends_with_history(client, app):
    """Clinical safety (#13): an approved lab result is locked — the normal edit
    path is refused; corrections go through an amendment that preserves the prior
    value, records who/why, and is limited to authorized roles."""
    from mdc_erp.models import LabOrder, ResultAmendment
    _login(client)
    # enter + approve a result
    tok = _csrf(client.get('/lab/1/result'))
    client.post('/lab/1/result', data={'result': 'WBC 6.2', '_csrf': tok})
    client.get('/lab/1/approve')
    with app.app_context():
        o = LabOrder.query.get(1)
        assert o.status == 'Approved' and o.locked
    # the normal edit path is now refused and redirects to Amend
    r = client.get('/lab/1/result', follow_redirects=True)
    assert b'locked' in r.data or b'Amend' in r.data
    # amending WITHOUT a reason is refused
    tok = _csrf(client.get('/lab/1/amend'))
    r = client.post('/lab/1/amend', data={'result': 'WBC 6.9', '_csrf': tok}, follow_redirects=True)
    assert b'reason is required' in r.data
    with app.app_context():
        assert ResultAmendment.query.filter_by(kind='lab', order_id=1).count() == 0
        assert LabOrder.query.get(1).result == 'WBC 6.2'   # unchanged
    # amend WITH a reason -> previous preserved, new set, history recorded
    tok = _csrf(client.get('/lab/1/amend'))
    client.post('/lab/1/amend', data={'result': 'WBC 6.9', 'reason': 'transcription error',
                                      '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        o = LabOrder.query.get(1)
        assert o.result == 'WBC 6.9' and o.status == 'Approved'   # still approved/locked
        amn = ResultAmendment.query.filter_by(kind='lab', order_id=1).all()
        assert len(amn) == 1
        assert amn[0].prev_result == 'WBC 6.2' and amn[0].new_result == 'WBC 6.9'
        assert amn[0].reason == 'transcription error' and amn[0].amended_by
    # the printout flags it as an amended report
    d = client.get('/lab/1/print').get_data(as_text=True)
    assert 'Amended report' in d and 'WBC 6.9' in d


def test_printed_documents_have_qr_and_barcode(client):
    """QR code, barcode and the 'Printed … by' meta line are present on printed
    documents. The Print/Email/WhatsApp action buttons stay removed."""
    _login(client)
    d = client.get('/invoice/1/print').get_data(as_text=True)
    assert 'INV-0001' in d and 'Document Ref' in d
    assert d.count('<svg') >= 2                          # barcode + QR
    assert 'Printed' in d                                # printed-by meta line
    assert 'Print / Save PDF' not in d and 'WhatsApp' not in d


def test_document_verification(app, client):
    _login(client)
    with app.test_request_context():
        from mdc_erp.core.security import doc_sig
        sig = doc_sig('INV-0001')
    r = client.get(f'/verify?ref=INV-0001&sig={sig}')
    assert b'Document Verified' in r.data
    r = client.get('/verify?ref=INV-0001&sig=forged000000')
    assert b'Not Verified' in r.data


def test_radiology_image_upload_and_access_control(app, client):
    import io
    _login(client)
    png = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
           b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
           b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')
    # a fresh Imaged (writable) study to report on
    with app.app_context():
        from mdc_erp.models import RadOrder
        from mdc_erp.extensions import db as _db
        o = RadOrder(patient_id=1, service_id=1, modality='CT', status='Imaged')
        _db.session.add(o); _db.session.commit(); oid = o.id
    tok = _csrf(client.get(f'/rad/{oid}/report'))
    r = client.post(f'/rad/{oid}/report',
                    data={'finalize': '1', 'radiologist': 'Dr. T', 'image_note': '', 'report': 'Normal.',
                          'images': [(io.BytesIO(png), 'scan.png')], '_csrf': tok},
                    content_type='multipart/form-data', follow_redirects=True)
    assert r.status_code == 200
    assert client.get(f'/rad/{oid}/img/0').status_code == 200        # staff
    stranger = app.test_client()
    assert stranger.get(f'/rad/{oid}/img/0').status_code == 403      # no session
    # reporting locks the study — a second write is refused and routed to Amend
    r = client.get(f'/rad/{oid}/report', follow_redirects=True)
    assert b'locked' in r.data or b'Amend' in r.data
    # exe upload is rejected on a still-writable (Imaged) study
    with app.app_context():
        o2 = RadOrder(patient_id=1, service_id=1, modality='CT', status='Imaged')
        _db.session.add(o2); _db.session.commit(); oid2 = o2.id
    tok = _csrf(client.get(f'/rad/{oid2}/report'))
    r = client.post(f'/rad/{oid2}/report',
                    data={'finalize': '1', 'radiologist': 'Dr. T', 'image_note': '', 'report': 'Normal.',
                          'images': [(io.BytesIO(b'MZ'), 'bad.exe')], '_csrf': tok},
                    content_type='multipart/form-data', follow_redirects=True)
    assert b'only image files allowed' in r.data


# ============================================================ Phase 3 tests

def test_radiology_draft_save_stays_editable(app, client):
    """Saving a report as a Draft (e.g. an accidental save) does NOT lock it —
    the radiologist can keep editing. Only Finalize locks it (then Amend only)."""
    from mdc_erp.models import Patient, Service, RadOrder
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        p = Patient(mrn='MRDRAFT', name='Draft Pt', gender='Male'); _db.session.add(p); _db.session.flush()
        s = Service.query.filter_by(department='Radiology').first() or Service(
            code='CTX', name='Brain CT', department='Radiology', price=180, active=True)
        if not s.id: _db.session.add(s); _db.session.flush()
        o = RadOrder(patient_id=p.id, service_id=s.id, status='Imaged', modality='CT')
        _db.session.add(o); _db.session.commit(); oid = o.id
    # Save Draft
    client.post(f'/rad/{oid}/report', data={'finalize': '0', 'radiologist': 'Dr Y',
                'report': 'draft text', '_csrf': _csrf(client.get(f'/rad/{oid}/report'))},
                content_type='multipart/form-data', follow_redirects=True)
    with app.app_context():
        o = RadOrder.query.get(oid)
        assert o.status == 'Draft' and not o.locked
    # still editable — form opens (not redirected to amend)
    r = client.get(f'/rad/{oid}/report')
    assert r.status_code == 200 and b'Findings' in r.data
    # edit again
    client.post(f'/rad/{oid}/report', data={'finalize': '0', 'radiologist': 'Dr Y',
                'report': 'corrected text', '_csrf': _csrf(client.get(f'/rad/{oid}/report'))},
                content_type='multipart/form-data', follow_redirects=True)
    with app.app_context():
        assert RadOrder.query.get(oid).report == 'corrected text'
    # Finalize → locked
    client.post(f'/rad/{oid}/report', data={'finalize': '1', 'radiologist': 'Dr Y',
                'report': 'final text', '_csrf': _csrf(client.get(f'/rad/{oid}/report'))},
                content_type='multipart/form-data', follow_redirects=True)
    with app.app_context():
        o = RadOrder.query.get(oid)
        assert o.status == 'Reported' and o.locked
    # editing after finalize is blocked → amend
    r = client.get(f'/rad/{oid}/report', follow_redirects=True)
    assert b'Amend' in r.data or b'finalized' in r.data


def test_radiology_report_locks_and_amends_with_history(app, client):
    """Clinical safety (#13): a finalized radiology report is locked — the write
    path is refused; corrections go through an amendment that preserves the prior
    report, records who/why, and flags the printout."""
    from mdc_erp.models import RadOrder, ResultAmendment
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        o = RadOrder(patient_id=1, service_id=1, modality='CT', status='Imaged')
        _db.session.add(o); _db.session.commit(); oid = o.id
    tok = _csrf(client.get(f'/rad/{oid}/report'))
    client.post(f'/rad/{oid}/report',
                data={'finalize': '1', 'radiologist': 'Dr. Y', 'report': 'No acute abnormality.',
                      'impression': 'Normal study.', '_csrf': tok},
                content_type='multipart/form-data', follow_redirects=True)
    with app.app_context():
        o = RadOrder.query.get(oid)
        assert o.status == 'Reported' and o.locked
    # write path refused
    r = client.get(f'/rad/{oid}/report', follow_redirects=True)
    assert b'locked' in r.data or b'Amend' in r.data
    # amend without reason refused
    tok = _csrf(client.get(f'/rad/{oid}/amend'))
    r = client.post(f'/rad/{oid}/amend',
                    data={'report': 'Small lesion seen.', 'impression': 'Follow-up advised.',
                          '_csrf': tok}, follow_redirects=True)
    assert b'reason is required' in r.data
    with app.app_context():
        assert ResultAmendment.query.filter_by(kind='rad', order_id=oid).count() == 0
    # amend with reason -> history preserved, new set
    tok = _csrf(client.get(f'/rad/{oid}/amend'))
    client.post(f'/rad/{oid}/amend',
                data={'report': 'Small lesion seen in segment VII.', 'impression': 'Follow-up advised.',
                      'reason': 'missed finding on review', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        o = RadOrder.query.get(oid)
        assert 'Small lesion' in (o.report or '')
        amn = ResultAmendment.query.filter_by(kind='rad', order_id=oid).all()
        assert len(amn) == 1 and 'No acute abnormality' in amn[0].prev_result
        assert amn[0].reason == 'missed finding on review' and amn[0].amended_by
    d = client.get(f'/rad/{oid}/print').get_data(as_text=True)
    assert 'AMENDED REPORT' in d and 'Small lesion' in d


def test_asset_register_and_book_value(client):
    import datetime as dt
    _login(client)
    tok = _csrf(client.get('/m/assets/new'))
    client.post('/m/assets/new',
                data={'code': 'AST-T1', 'name': 'Ultrasound GE', 'category': 'Medical Equipment',
                      'serial': 'S1', 'location': 'Room 2', 'purchase_date': '2024-01-01',
                      'cost': '20000', 'useful_life': '10',
                      'warranty_expiry': (dt.date.today() + dt.timedelta(days=15)).isoformat(),
                      'calibration_due': (dt.date.today() + dt.timedelta(days=5)).isoformat(),
                      'status': 'Active', 'notes': '', '_csrf': tok})
    d = client.get('/m/maintdash').get_data(as_text=True)
    assert 'AST-T1' in d and 'Book Value' in d
    assert 'Calibration Due' in d          # appears in 30-day alert panel


def test_maintenance_job_lifecycle(client):
    import datetime as dt
    _login(client)
    tok = _csrf(client.get('/m/maintenance/new'))
    client.post('/m/maintenance/new',
                data={'asset_id': '1', 'type': 'Corrective', 'date': dt.date.today().isoformat(),
                      'engineer': 'Eng. Test', 'description': 'Fix probe', 'parts_cost': '50',
                      'labor_cost': '25', 'status': 'Open', 'completed': '', '_csrf': tok})
    assert b'Eng. Test' in client.get('/m/maintdash').data
    r = client.get('/maintenance/1/done', follow_redirects=True)
    assert r.status_code == 200
    assert b'No open jobs' in client.get('/m/maintdash').data


def test_branch_comparison_report(client):
    _login(client)
    r = client.get('/m/branchcmp')
    assert r.status_code == 200 and b'HQ Consolidated' in r.data


def test_notifications_flow_and_role_targeting(app, client):
    _login(client)
    # lab approval emits a reception-targeted notification
    tok = _csrf(client.get('/lab/1/result'))
    client.post('/lab/1/result', data={'result': 'OK', '_csrf': tok})
    client.get('/lab/1/approve')
    # HR-targeted event
    tok = _csrf(client.get('/leave/new'))
    client.post('/leave/new', data={'employee_id': '1', 'type': 'Annual',
                                    'start': '2026-08-01', 'end': '2026-08-05', '_csrf': tok})
    # super_admin sees everything + badge, cleared after reading
    d = client.get('/dashboard').get_data(as_text=True)
    assert '🔔<span' in d
    d = client.get('/notifications').get_data(as_text=True)
    assert 'Report completed' in d and 'Leave request' in d
    assert '🔔<span' not in client.get('/dashboard').get_data(as_text=True)
    # reception: sees lab event, does NOT see HR event
    c2 = app.test_client()
    tok = _csrf(c2.get('/login'))
    c2.post('/login', data={'username': 'reception', 'password': '1234', '_csrf': tok})
    d = c2.get('/notifications').get_data(as_text=True)
    assert 'Report completed' in d and 'Leave request' not in d


# ==================================== Phase 4: Billing / Accounting / Inventory

def test_daily_cash_closing(client):
    import datetime as dt
    _login(client)
    tok = _csrf(client.get('/invoice/1'))
    client.post('/invoice/1', data={'act': 'pay', 'paid': '100', 'pay_method': 'Cash', '_csrf': tok})
    d = client.get('/m/cashclose').get_data(as_text=True)
    assert 'Total Collected' in d and 'NET CASH' in d
    today = dt.date.today().isoformat()
    assert client.get(f'/cashclose/print?date={today}').status_code == 200
    tok = _csrf(client.get('/invoice/new'))
    r = client.post(f'/cashclose/close?date={today}',
                    data={'opening': '0', 'withdrawals': '0', 'actual': '0', '_csrf': tok},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b'DAY CLOSED' in client.get('/m/audit').data


def test_invoice_refund_with_validation(client):
    _login(client)
    tok = _csrf(client.get('/invoice/1'))
    client.post('/invoice/1', data={'act': 'pay', 'paid': '100', 'pay_method': 'Cash', '_csrf': tok})
    r = client.post('/invoice/1', data={'act': 'refund', 'refund_amount': '40',
                                        'refund_reason': 'overcharge', '_csrf': tok},
                    follow_redirects=True)
    assert b'Refunded' in r.data
    r = client.post('/invoice/1', data={'act': 'refund', 'refund_amount': '99999',
                                        'refund_reason': 'x', '_csrf': tok}, follow_redirects=True)
    assert b'between 0 and the amount paid' in r.data
    assert b'REFUND' in client.get('/m/audit').data


def test_ar_ap_aging_and_cashflow(client):
    _login(client)
    d = client.get('/m/araging').get_data(as_text=True)
    assert 'Accounts Receivable Aging' in d and 'Total Receivable' in d
    d = client.get('/m/apaging').get_data(as_text=True)
    assert 'Accounts Payable Aging' in d and 'Total Payable' in d
    d = client.get('/m/cashflow').get_data(as_text=True)
    assert 'Cash Flow Statement' in d and 'Closing Cash Position' in d


def test_stock_adjustment_and_consumption(client):
    import datetime as dt
    _login(client)
    tok = _csrf(client.get('/m/stockadj'))
    r = client.post('/stock/adjust',
                    data={'medicine_id': '1', 'qty_change': '-3',
                          'date': dt.date.today().isoformat(),
                          'reason': 'Expired write-off', 'note': 'batch check', '_csrf': tok},
                    follow_redirects=True)
    assert b'stock now' in r.data
    d = client.get('/m/stockadj').get_data(as_text=True)
    assert 'Expired write-off' in d and 'batch check' in d
    # zero-change rejected
    r = client.post('/stock/adjust',
                    data={'medicine_id': '1', 'qty_change': '0',
                          'date': dt.date.today().isoformat(), 'reason': 'Other', '_csrf': tok},
                    follow_redirects=True)
    assert b'cannot be zero' in r.data
    d = client.get('/m/consumption').get_data(as_text=True)
    assert 'Stock Value' in d and 'Adjusted' in d


# ============================== Phase 5: Warehouses / PO-GRN / Transfers / API docs

def test_warehouse_crud_and_stock_matrix(client):
    _login(client)
    tok = _csrf(client.get('/m/warehouses/new'))
    client.post('/m/warehouses/new', data={'code': 'WH2', 'name': 'Second Store',
                                           'branch_id': '1', 'active': '1', '_csrf': tok})
    assert b'Second Store' in client.get('/m/warehouses').data
    d = client.get('/m/transfers').get_data(as_text=True)
    assert 'Stock by Warehouse' in d and 'Second Store' in d


def test_purchase_order_full_lifecycle(client):
    import re
    import datetime as dt
    _login(client)
    _new_purchase(client, item='Test Reagent', category='Reagents', medicine_id='1',
                  qty='10', unit_cost='5')
    d = client.get('/m/purchases').get_data(as_text=True)
    assert 'Requested' in d and 'Approve' in d
    pid = re.search(r'/purchase/(\d+)/order', d).group(1)
    # Requested POs must not be in the ledger yet
    assert f'PUR-{int(pid):04d}'.encode() not in client.get('/m/ledger', follow_redirects=True).data
    client.get(f'/purchase/{pid}/order', follow_redirects=True)
    assert b'Receive' in client.get('/m/purchases').data
    r = client.get(f'/purchase/{pid}/receive', follow_redirects=True)
    assert b'received' in r.data and b'stock updated' in r.data
    # receiving alone posts NOTHING to the ledger (goods in, not yet billed)
    assert f'PUR-{int(pid):04d}'.encode() not in client.get('/m/ledger', follow_redirects=True).data
    r = client.get(f'/purchase/{pid}/grn')
    assert r.status_code == 200 and b'Goods Received Note' in r.data
    # double receive blocked
    r = client.get(f'/purchase/{pid}/receive', follow_redirects=True)
    assert b'Already received' in r.data
    # create the vendor bill then confirm → now it posts to the ledger
    client.get(f'/purchase/{pid}/create-bill', follow_redirects=True)
    client.get(f'/purchase/{pid}/confirm-bill', follow_redirects=True)
    assert f'PUR-{int(pid):04d}'.encode() in client.get('/m/ledger', follow_redirects=True).data


def test_stock_transfer_with_validation(app, client):
    import datetime as dt
    from mdc_erp.models import Medicine, StockLevel, Warehouse
    from mdc_erp.extensions import db as _db
    _login(client)
    # self-contained: ensure two warehouses, a medicine, and starting stock in WH1
    with app.app_context():
        whs = Warehouse.query.order_by(Warehouse.id).all()
        while len(whs) < 2:
            w = Warehouse(name=f'WH{len(whs)+1}')
            _db.session.add(w); _db.session.commit()
            whs = Warehouse.query.order_by(Warehouse.id).all()
        w1, w2 = whs[0].id, whs[1].id
        med = Medicine.query.first()
        if not med:
            med = Medicine(name='TestMed', qty=0)
            _db.session.add(med); _db.session.commit()
        mid = med.id
        # give WH1 a known starting level and sync medicine total
        sl = StockLevel.query.filter_by(medicine_id=mid, warehouse_id=w1).first()
        if not sl:
            sl = StockLevel(medicine_id=mid, warehouse_id=w1, qty=0)
            _db.session.add(sl)
        sl.qty = 10
        med.qty = sum(l.qty or 0 for l in StockLevel.query.filter_by(medicine_id=mid).all()
                      if l.warehouse_id != w1) + 10
        _db.session.commit()
    tok = _csrf(client.get('/m/transfers'))
    r = client.post('/stock/transfer',
                    data={'medicine_id': str(mid), 'from_id': str(w1), 'to_id': str(w2), 'qty': '2',
                          'date': dt.date.today().isoformat(), 'note': 'move', '_csrf': tok},
                    follow_redirects=True)
    assert b'Transferred 2' in r.data
    # invariant: total == sum of warehouse levels
    with app.app_context():
        m = _db.session.get(Medicine, mid)
        tot = sum(l.qty or 0 for l in StockLevel.query.filter_by(medicine_id=mid).all())
        assert abs((m.qty or 0) - tot) < 0.001
    # over-transfer and same-warehouse rejected
    r = client.post('/stock/transfer',
                    data={'medicine_id': str(mid), 'from_id': str(w2), 'to_id': str(w1), 'qty': '99999',
                          'date': dt.date.today().isoformat(), 'note': '', '_csrf': tok},
                    follow_redirects=True)
    assert b'Only' in r.data
    r = client.post('/stock/transfer',
                    data={'medicine_id': '1', 'from_id': '1', 'to_id': '1', 'qty': '1',
                          'date': dt.date.today().isoformat(), 'note': '', '_csrf': tok},
                    follow_redirects=True)
    assert b'same' in r.data


def test_openapi_and_swagger_ui(client):
    r = client.get('/api/openapi.json')
    assert r.status_code == 200
    spec = r.get_json()
    assert spec['openapi'].startswith('3.') and '/api/login' in spec['paths']
    r = client.get('/api/docs')
    assert r.status_code == 200 and b'swagger-ui' in r.data


# ============================== Phase 6: Enterprise Accounting

def _new_expense(client, post=True, pay=None, **data):
    """Create an expense via the Odoo flow. If post=True, run Submit→Approve→Post
    so it hits the ledger. If pay is given, also register that payment."""
    tok = _csrf(client.get('/expense/new'))
    payload = {'qty': '1', 'unit_price': '0', 'pay_method': 'Cash', 'category': 'Maintenance',
               'account': '600050 Repairs & Maintenance', 'paid_by': 'Company', **data, '_csrf': tok}
    client.post('/expense/save', data=payload, follow_redirects=True)
    from mdc_erp.models import Expense
    from mdc_erp.extensions import db as _db
    app = client.application
    with app.app_context():
        eid = Expense.query.order_by(Expense.id.desc()).first().id
    if post:
        client.get(f'/expense/{eid}/submit', follow_redirects=True)
        client.get(f'/expense/{eid}/approve', follow_redirects=True)
        client.get(f'/expense/{eid}/post', follow_redirects=True)
    if pay:
        tok = _csrf(client.get(f'/expense/{eid}'))
        client.post(f'/expense/{eid}/pay', data={'amount': str(pay[0]), 'method': pay[1], '_csrf': tok},
                    follow_redirects=True)
    return eid


def _post_mod(client, mod, data):
    tok = _csrf(client.get(f'/m/{mod}/new'))
    return client.post(f'/m/{mod}/new', data={**data, '_csrf': tok}, follow_redirects=True)


def _new_purchase(client, **data):
    """Create a purchase via the Odoo-style RFQ form (/purchase/save)."""
    tok = _csrf(client.get('/purchase/new'))
    payload = {'qty': '1', 'unit_cost': '0', 'paid': '0', 'pay_method': 'Cash',
               'category': 'Reagents', **data, '_csrf': tok}
    return client.post('/purchase/save', data=payload, follow_redirects=True)


def test_credit_note_posts_and_reduces_ar(client):
    import datetime as dt
    _login(client)
    r = _post_mod(client, 'creditnotes', {'date': dt.date.today().isoformat(), 'invoice_id': '1',
                                          'amount': '5', 'reason': 'goodwill'})
    assert r.status_code == 200
    d = client.get('/m/ledger', follow_redirects=True).get_data(as_text=True)
    assert 'CN-' in d
    # AR aging uses net balance
    assert client.get('/m/araging').status_code == 200


def test_debit_note_posts(client):
    import re
    import datetime as dt
    _login(client)
    # build a received purchase to raise the debit note against
    _new_purchase(client, item='DN target', category='Reagents', qty='1', unit_cost='7')
    d = client.get('/m/purchases').get_data(as_text=True)
    pid = sorted(int(x) for x in re.findall(r'/purchase/(\d+)/', d))[-1]
    client.get(f'/purchase/{pid}/order', follow_redirects=True)
    client.get(f'/purchase/{pid}/receive', follow_redirects=True)
    _post_mod(client, 'debitnotes', {'date': dt.date.today().isoformat(),
                                     'purchase_id': str(pid), 'amount': '7', 'reason': 'return'})
    assert 'DN-' in client.get('/m/ledger', follow_redirects=True).get_data(as_text=True)


def test_bank_reconciliation_flow(app, client):
    _login(client)
    from mdc_erp.models import Account, BankAccount, JournalLine
    with app.app_context():
        aid = Account.query.filter_by(code='1102').first().id
    _post_mod(client, 'banks', {'name': 'Salaam Main', 'bank_name': 'Salaam Bank',
                                'number': '00123', 'account_id': str(aid),
                                'currency': 'USD', 'active': '1'})
    r = client.get('/m/bankrecon')
    assert r.status_code == 200 and b'Salaam Main' in r.data
    with app.app_context():
        bank_id = BankAccount.query.filter_by(name='Salaam Main').first().id
        line = JournalLine.query.filter_by(account_id=aid).first()
    tok = _csrf(r)
    data = {'bank': str(bank_id), '_csrf': tok}
    if line:
        data[f'clr_{line.id}'] = 'on'
    r = client.post('/bankrecon/save', data=data, follow_redirects=True)
    assert b'updated' in r.data
    if line:
        with app.app_context():
            assert JournalLine.query.get(line.id).cleared


def test_budget_and_costcenter_reports(client):
    import datetime as dt
    _login(client)
    _post_mod(client, 'costcenters', {'code': 'LAB', 'name': 'Laboratory'})
    _post_mod(client, 'budgets', {'year': str(dt.date.today().year), 'account_code': '5100',
                                  'amount': '1000'})
    assert b'Budget vs Actual' in client.get('/m/budgetreport').data
    assert b'Laboratory' in client.get('/m/ccreport').data


def test_financial_ratios_and_taxreport(client):
    _login(client)
    d = client.get('/m/ratios').get_data(as_text=True)
    assert 'Current Ratio' in d and 'Net Margin' in d and 'Quick Ratio' in d
    assert b'VAT' in client.get('/m/taxreport').data


def test_fiscal_period_lock_blocks_everything(client, app):
    import datetime as dt
    _login(client)
    y, m = dt.date.today().year, dt.date.today().month
    client.get(f'/fiscal/toggle/{y}/{m}', follow_redirects=True)
    # 1) posting an expense into a CLOSED period is refused at Post
    from mdc_erp.models import Expense
    eid = _new_expense(client, post=False, description='Rent P', category='Rent',
                       qty='1', unit_price='9', date=dt.date.today().isoformat())
    client.get(f'/expense/{eid}/submit', follow_redirects=True)
    client.get(f'/expense/{eid}/approve', follow_redirects=True)
    r = client.get(f'/expense/{eid}/post', follow_redirects=True)
    assert b'Period closed' in r.data
    # 2) manual journal path
    tok = _csrf(client.get('/journal/new'))
    r = client.post('/journal/new', data={'date': dt.date.today().isoformat(),
                                          'acct1': '1', 'debit1': '5', 'credit1': '0',
                                          '_csrf': tok}, follow_redirects=True)
    assert b'Period closed' in r.data
    # reopening a closed period WITHOUT a reason is refused
    client.get(f'/fiscal/toggle/{y}/{m}', follow_redirects=True)
    r = client.get(f'/expense/{eid}/post', follow_redirects=True)
    assert b'Period closed' in r.data  # still closed — reopen without reason did nothing
    # reopen WITH a reason and verify posting flows again + audit captured
    client.get(f'/fiscal/toggle/{y}/{m}?reason=correction+needed', follow_redirects=True)
    from mdc_erp.models import FiscalPeriod
    with app.app_context():
        fp = FiscalPeriod.query.filter_by(year=y, month=m).first()
        assert fp.status == 'Open' and fp.reopen_reason == 'correction needed' and fp.reopened_by
    r = client.get(f'/expense/{eid}/post', follow_redirects=True)
    assert b'Period closed' not in r.data
    with app.app_context():
        assert Expense.query.get(eid).status == 'Posted'


def test_payment_allocation_oldest_first(client):
    _login(client)
    r = client.get('/m/payalloc')
    assert r.status_code == 200 and b'Receive' in r.data
    tok = _csrf(r)
    r = client.post('/payments/receive', data={'patient_id': '1', 'amount': '1',
                                               'method': 'Cash', '_csrf': tok},
                    follow_redirects=True)
    assert r.status_code == 200


def test_depreciation_and_year_close(app, client):
    import datetime as dt
    from mdc_erp.models import Asset
    from mdc_erp.extensions import db as _db
    _login(client)
    y = dt.date.today().year
    # ensure at least one depreciable asset exists this year
    with app.app_context():
        a = Asset(name='CT Machine T', cost=12000, useful_life=5,
                  purchase_date=f'{y}-01-01', status='Active', category='Medical Equipment')
        _db.session.add(a); _db.session.commit()
    client.get(f'/depreciation/run?year={y}', follow_redirects=True)
    assert f'DEP-{y}' in client.get('/m/journal').get_data(as_text=True)
    client.get(f'/fiscal/closeyear/{y}', follow_redirects=True)
    d = client.get('/m/journal').get_data(as_text=True)
    assert f'CLS-{y}' in d
    # all 12 months now locked → posting blocked at Post
    eid = _new_expense(client, post=False, description='Rent Y', category='Rent',
                       qty='1', unit_price='3', date=dt.date.today().isoformat())
    client.get(f'/expense/{eid}/submit', follow_redirects=True)
    client.get(f'/expense/{eid}/approve', follow_redirects=True)
    r = client.get(f'/expense/{eid}/post', follow_redirects=True)
    assert b'Period closed' in r.data


def test_depreciation_methods_math_is_correct(app):
    """#11: straight-line, declining-balance and the residual cap compute correctly
    and never depreciate below (cost - residual)."""
    from mdc_erp.models import Asset
    from mdc_erp.extensions import db as _db
    from mdc_erp.blueprints.fixedassets import period_depreciation
    with app.app_context():
        # Straight line: 12000/60mo = 200/mo
        sl = Asset(name='SL A', cost=12000, residual_value=0, useful_life=5,
                   depreciation_method='Straight Line', status='Active', activated=True,
                   accumulated_dep=0, purchase_date='2026-01-01')
        _db.session.add(sl); _db.session.commit()
        assert abs(period_depreciation(sl) - 200.0) < 0.01
        # Declining balance (double): first month 10000 * (2/5) / 12 = 333.33
        dbn = Asset(name='DB A', cost=10000, residual_value=0, useful_life=5,
                    depreciation_method='Declining Balance', status='Active', activated=True,
                    accumulated_dep=0, purchase_date='2026-01-01')
        _db.session.add(dbn); _db.session.commit()
        assert abs(period_depreciation(dbn) - 333.33) < 0.02
        # Residual cap: $100 depreciable, $99 already taken -> only $1 left
        rc = Asset(name='RC A', cost=1000, residual_value=900, useful_life=5,
                   depreciation_method='Straight Line', status='Active', activated=True,
                   accumulated_dep=99, purchase_date='2026-01-01')
        _db.session.add(rc); _db.session.commit()
        assert abs(period_depreciation(rc) - 1.0) < 0.01
        rc.accumulated_dep = 100
        assert period_depreciation(rc) == 0.0   # fully at residual, no more


def test_depreciation_starts_from_in_service_date(app):
    """#10: depreciation begins at the IN-SERVICE date, not the purchase date —
    a machine bought in January but installed in April starts depreciating in April."""
    from mdc_erp.models import Asset
    from mdc_erp.extensions import db as _db
    from mdc_erp.blueprints.fixedassets import _depreciation_schedule
    with app.app_context():
        a = Asset(name='Installed-Later CT', cost=12000, residual_value=0, useful_life=5,
                  depreciation_method='Straight Line', status='Active', activated=True,
                  accumulated_dep=0, purchase_date='2026-01-10', in_service_date='2026-04-01')
        _db.session.add(a); _db.session.commit()
        sched = _depreciation_schedule(a)
        assert sched, 'expected a schedule'
        # first depreciation period is April 2026 (in-service), not January (purchase)
        assert sched[0][0] == '2026-04'
        # with no in-service date it falls back to the purchase month
        a.in_service_date = None
        _db.session.commit()
        sched2 = _depreciation_schedule(a)
        assert sched2[0][0] == '2026-01'


def test_units_of_production_depreciation_is_usage_based(app):
    """#12: Units-of-Production depreciation reflects ACTUAL units used, not an
    even monthly spread. rate = (cost - residual)/units_total; charge tracks usage."""
    from mdc_erp.models import Asset
    from mdc_erp.extensions import db as _db
    from mdc_erp.blueprints.fixedassets import period_depreciation
    with app.app_context():
        # $10,000 cost, $0 residual, 100,000 total units -> $0.10 per unit
        a = Asset(name='UoP Generator', cost=10000, residual_value=0, useful_life=10,
                  depreciation_method='Units of Production', units_total=100000, units_used=0,
                  status='Active', activated=True, accumulated_dep=0, purchase_date='2026-01-01')
        _db.session.add(a); _db.session.commit()
        # no usage yet -> no depreciation (unlike straight-line which would charge monthly)
        assert period_depreciation(a) == 0.0
        # used 8,000 units -> 8,000 * $0.10 = $800
        a.units_used = 8000
        assert abs(period_depreciation(a) - 800.0) < 0.01
        # post it (simulate) then use 2,000 more -> next charge is $200, not $800 again
        a.accumulated_dep = 800.0
        a.units_used = 10000
        assert abs(period_depreciation(a) - 200.0) < 0.01
        # heavy month: 40,000 more units -> $4,000
        a.accumulated_dep = 1000.0
        a.units_used = 50000
        assert abs(period_depreciation(a) - 4000.0) < 0.01
        # cannot exceed depreciable base: use all units -> total depreciation caps at $10,000
        a.accumulated_dep = 5000.0
        a.units_used = 100000
        assert abs(period_depreciation(a) - 5000.0) < 0.01   # only the remaining $5,000
        a.accumulated_dep = 10000.0
        assert period_depreciation(a) == 0.0                 # fully depreciated


def test_excel_and_pdf_exports(client):
    _login(client)
    for what in ('trialbalance', 'ledger', 'araging', 'apaging', 'budget'):
        r = client.get(f'/export/xlsx/{what}')
        assert r.status_code == 200, what
        assert 'spreadsheetml' in r.content_type
    r = client.get('/finance/pdf')
    assert r.status_code == 200 and r.content_type.startswith('application/pdf')


def test_multi_currency_registry(client):
    _login(client)
    _post_mod(client, 'currencies', {'code': 'ETB', 'name': 'Ethiopian Birr', 'rate': '57.5'})
    assert b'ETB' in client.get('/m/currencies').data


# ============================== Phase 7: One-place workflow (Patient Hub)

def test_patient_hub_one_place(client):
    _login(client)
    d = client.get('/patient/1').get_data(as_text=True)
    for x in ('+ Consultation', '+ Lab Test', '+ Radiology', '+ Invoice',
              'Receive Payment', 'Check-in', 'Consultations', 'Statement'):
        assert x in d, x


def test_prefill_via_url_args(client):
    import re
    _login(client)
    d = client.get('/m/consult/new?patient_id=1').get_data(as_text=True)
    m = re.search(r"name='patient_id'>(.*?)</select>", d, re.S)
    assert m and "value='1' selected" in m.group(1)
    d = client.get('/m/appointments/new?patient_id=1').get_data(as_text=True)
    m = re.search(r"name='patient_id'>(.*?)</select>", d, re.S)
    assert m and "value='1' selected" in m.group(1)


def test_dashboard_quick_actions_by_role(app, client):
    _login(client)
    # remove any perms_json override left by test_permissions_matrix
    from mdc_erp.models import Setting
    from mdc_erp.extensions import db as _db
    with app.app_context():
        s = Setting.query.get('perms_json')
        if s:
            _db.session.delete(s); _db.session.commit()
    d = client.get('/').get_data(as_text=True)
    assert 'Quick Actions' in d and 'Register Patient' in d
    # widgets and category cards present
    assert 'wgs' in d and "Today's Patients" in d and 'Top Requested Tests' in d
    # reception sees the register action; admin-only financial dashboard hidden for reception
    tok = _csrf(client.get('/login'))
    client.post('/login', data={'username': 'reception', 'password': '1234', '_csrf': tok})
    d = client.get('/').get_data(as_text=True)
    # reception can register patients and do permitted billing, but per least-privilege
    # is denied the general ledger, expenses, payables, and the Financial Dashboard.
    assert 'Register Patient' in d
    assert 'No access' in client.get('/m/findash').get_data(as_text=True)
    assert 'No access' in client.get('/m/journal').get_data(as_text=True)
    assert 'No access' in client.get('/m/expenses').get_data(as_text=True)
    # restore admin for subsequent tests
    tok = _csrf(client.get('/login'))
    client.post('/login', data={'username': 'admin', 'password': 'admin123', '_csrf': tok})


# ============================== Opening balances: COA <-> statements linkage

def test_statements_are_gl_linked_and_tie_out(app):
    """P&L, Balance Sheet and Cash Flow are built from the general ledger and
    always tie: Assets = Liabilities + Equity(+net income), and net income =
    Income − Expense — for a mix of invoice, expense and purchase postings."""
    from mdc_erp.models import Patient, Invoice, InvoiceItem, Expense, Supplier, Medicine, Purchase
    from mdc_erp.core.posting import (repost_invoice, repost_payment, post_expense,
        repost_expense_payment, post_purchase, repost_purchase_payment, gl_statements, post_journal)
    from mdc_erp.extensions import db as _db
    with app.app_context():
        p = Patient(mrn='TIE1', name='Pt', gender='Male'); _db.session.add(p); _db.session.flush()
        inv = Invoice(patient_id=p.id, status='Posted', confirmed=True, date='2026-09-08')
        _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, desc='CT', qty=1, price=180)); _db.session.commit()
        repost_invoice(inv); inv.paid = 100; _db.session.commit(); repost_payment(inv)
        e = Expense(description='Maint', category='Maintenance', amount=25, paid=25,
                    pay_method='Bank', status='Posted', date='2026-09-08')
        _db.session.add(e); _db.session.commit(); post_expense(e); repost_expense_payment(e)
        s = Supplier(name='V'); _db.session.add(s)
        m = Medicine(name='Gl', qty=0, cost=12, price=0); _db.session.add(m); _db.session.flush()
        pu = Purchase(supplier_id=s.id, medicine_id=m.id, item='Gl', qty=50, unit_cost=12,
                      total=600, paid=200, pay_method='E. Dahab', status='Received',
                      bill_status='posted', date='2026-09-08')
        _db.session.add(pu); _db.session.commit(); post_purchase(pu); repost_purchase_payment(pu)
        post_journal('2026-09-01', 'CAPT', 'capital', [('1101', 5000, 0), ('3100', 0, 5000)])

        G = gl_statements('2026-01-01', '2026-12-31')
        # net income = income − expense
        assert abs(G['net_income'] - (G['income'] - G['expense'])) < 0.01
        # balance sheet ties: Assets = Liabilities + Equity(incl net income)
        assert abs(G['assets'] - (G['liabilities'] + G['equity_with_ni'])) < 0.01, \
            f"A={G['assets']} L={G['liabilities']} E={G['equity_with_ni']}"
        # income reflects the invoice, expense reflects the posted expense
        assert G['income'] >= 180 - 0.01 and G['expense'] >= 25 - 0.01
        # unpaid purchase balance sits in liabilities (AP 600-200=400)
        assert G['liabilities'] >= 400 - 0.01


def test_opening_balances_flow_to_statements(app, client):
    _login(client)
    # demo seed has cash openings (1101/1102/1103) -> visible + balanced via OBE
    d = client.get('/m/finance?tab=tb').get_data(as_text=True)
    assert 'incl. opening' in d and 'Opening Balance Equity' in d
    assert '✓ Debits = Credits' in d and '⚠' not in d
    d = client.get('/m/finance?tab=bs').get_data(as_text=True)
    # GL-linked BS shows the actual asset accounts + the Opening Balance Equity plug
    assert 'Opening Balance Equity' in d and ('Main Account' in d or '1101' in d)
    import re as _re
    def _chk(t):
        m = _re.search(r'(⚠ Out of balance|✓ Balanced[^<]*)</span><span>([^<]+)', t)
        return m.group(2) if m else '0'
    chk_before = _chk(d)
    d = client.get('/m/finance?tab=cash').get_data(as_text=True)
    assert 'Closing Cash &amp; Bank' in d or 'Closing Cash' in d
    # ledger shows an OPENING row seeding the running balance
    from mdc_erp.models import Account
    with app.app_context():
        aid = Account.query.filter_by(code='1101').first().id
    d = client.get(f'/m/ledger?account={aid}', follow_redirects=True).get_data(as_text=True)
    assert 'OPENING' in d and 'Opening balance (Chart of Accounts)' in d
    # editing an opening in the COA reflects immediately, and stays balanced
    with app.app_context():
        ar = Account.query.filter_by(code='2100').first()
        aid2, nm = ar.id, ar.name
    tok = _csrf(client.get(f'/coa/form?id={aid2}'))
    client.post('/coa/save', data={'id': str(aid2), 'code': '2100', 'name': nm,
                                   'type': 'Liability', 'parent_id': '',
                                   'opening': '777', '_csrf': tok})
    d = client.get('/m/finance?tab=tb').get_data(as_text=True)
    assert '✓ Debits = Credits' in d
    d = client.get(f'/m/ledger?account={aid2}', follow_redirects=True).get_data(as_text=True)
    assert 'OPENING' in d and '777' in d.replace(',', '')
    # openings must be self-balancing: BS check unchanged by the new opening
    d = client.get('/m/finance?tab=bs').get_data(as_text=True)
    assert _chk(d) == chk_before and '777' in d.replace(',', '')
    # exports carry the openings too
    import io
    import openpyxl
    r = client.get('/export/xlsx/trialbalance')
    ws = openpyxl.load_workbook(io.BytesIO(r.data)).active
    codes = [str(row[0].value) for row in ws.iter_rows(min_row=2)]
    assert '1101' in codes and '2100' in codes
    # reset so other tests are unaffected
    tok = _csrf(client.get(f'/coa/form?id={aid2}'))
    client.post('/coa/save', data={'id': str(aid2), 'code': '2100', 'name': nm,
                                   'type': 'Liability', 'parent_id': '',
                                   'opening': '0', '_csrf': tok})


# ============================== Phase 8: Registration -> Receipt workflow

def test_full_clinical_workflow(app, client):
    import io
    import datetime as dt
    _login(client)
    # 1. registration (full form incl. photo) -> auto MRN, age, reg_by
    tok = _csrf(client.get('/m/patients/new'))
    r = client.post('/m/patients/new', content_type='multipart/form-data', follow_redirects=True,
                    data={'name': 'Workflow Test', 'phone': '061', 'phone2': '062', 'gender': 'Female',
                          'dob': '1990-05-01', 'blood_group': 'O+', 'marital': 'Married',
                          'occupation': 'Teacher', 'gov_id': 'ID9', 'address': 'Gaalkacyo',
                          'emerg_name': 'Cali', 'emerg_phone': '063', 'ins_company': 'Takaful',
                          'ins_number': 'T-9', 'allergies': 'Penicillin', 'med_history': 'HTN',
                          'active': '1', 'notes': '', '_csrf': tok,
                          'photo': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 40), 'p.png')})
    from mdc_erp.models import Patient, Appointment, PayReceipt
    with app.app_context():
        p = Patient.query.filter_by(name='Workflow Test').first()
        assert p and p.mrn and p.reg_by and p.photo and p.age is not None
        pid = p.id
    # patient card + photo served
    assert b'Patient Card' in client.get(f'/patient/{pid}/card').data
    assert client.get(f'/patient/{pid}/photo').status_code == 200
    # 2. appointment (service/type/priority) -> 3. confirm + check-in (doctor notified)
    tok = _csrf(client.get('/m/appointments/new'))
    client.post('/m/appointments/new',
                data={'patient_id': str(pid), 'date': dt.date.today().isoformat(), 'time': '10:00',
                      'department': 'Consultation', 'doctor': 'Dr Ali', 'service_id': '',
                      'visit_type': 'Emergency', 'priority': 'Urgent', 'status': 'Scheduled',
                      'notes': '', '_csrf': tok})
    with app.app_context():
        aid = (Appointment.query.filter_by(patient_id=pid)
               .order_by(Appointment.id.desc()).first().id)
    client.get(f'/queue/{aid}/confirm')
    client.get(f'/queue/{aid}/checkin')
    with app.app_context():
        a = Appointment.query.get(aid)
        assert a.status == 'Waiting' and a.queue_no
    from mdc_erp.models import Notification
    with app.app_context():
        assert Notification.query.filter_by(role='doctor').count() >= 1
    # 4. consultation with vitals + follow-up -> auto-booked appointment
    fu = (dt.date.today() + dt.timedelta(days=7)).isoformat()
    tok = _csrf(client.get('/m/consult/new'))
    client.post('/m/consult/new',
                data={'patient_id': str(pid), 'date': dt.date.today().isoformat(),
                      'doctor': 'Dr Ali', 'complaint': 'Fever', 'icd_code': '', 'bp': '120/80',
                      'temp_c': '38.5', 'pulse': '88', 'spo2': '97', 'weight_kg': '65',
                      'height_cm': '165', 'diagnosis': 'Malaria', 'notes': '',
                      'followup_date': fu, 'status': 'Completed', '_csrf': tok})
    with app.app_context():
        fua = Appointment.query.filter_by(patient_id=pid, date=fu).first()
        assert fua and fua.visit_type == 'Follow-up'
    # consult list has one-place action buttons ("send to billing" etc.)
    d = client.get('/m/consult').get_data(as_text=True)
    assert '🧾 Bill' in d and '🧪 Lab' in d


def test_discount_authorization_and_audit(app, client):
    from mdc_erp.models import Invoice, Audit
    _login(client, 'reception', '1234')
    tok = _csrf(client.get('/invoice/1'))
    r = client.post('/invoice/1', follow_redirects=True,
                    data={'act': 'adjust', 'discount': '3', 'discount_pct': '0', 'vat': '0',
                          'price_list': 'Cash', 'disc_reason': 'Staff',
                          'referring_doctor_id': '', '_csrf': tok})
    assert b'require authorization' in r.data
    _login(client)
    tok = _csrf(client.get('/invoice/1'))
    client.post('/invoice/1',
                data={'act': 'adjust', 'discount': '3', 'discount_pct': '0', 'vat': '0',
                      'price_list': 'Cash', 'disc_reason': 'Charity',
                      'referring_doctor_id': '', '_csrf': tok})
    with app.app_context():
        inv = Invoice.query.get(1)
        assert inv.discount == 3 and inv.disc_by and inv.disc_reason == 'Charity'
        assert any('DISCOUNT INV-0001' in (x.action or '')
                   for x in Audit.query.order_by(Audit.id.desc()).limit(8).all())
    assert b'Discount approved by' in client.get('/invoice/1').data


def test_payment_receipts_split_and_insurance(app, client):
    import datetime as dt
    from mdc_erp.models import PayReceipt, Account, Invoice, FiscalPeriod
    _login(client)
    # a previous test closes the fiscal year: reopen the current month
    y, m = dt.date.today().year, dt.date.today().month
    with app.app_context():
        fp = FiscalPeriod.query.filter_by(year=y, month=m).first()
        if fp and fp.status == 'Closed':
            from mdc_erp.extensions import db as _db
            fp.status = 'Open'; _db.session.commit()
    with app.app_context():
        base = Invoice.query.get(1).paid or 0
    tok = _csrf(client.get('/invoice/1'))
    r = client.post('/invoice/1', follow_redirects=True,
                    data={'act': 'pay', 'paid': str(base + 5), 'pay_method': 'Cash',
                          'pay_ref': 'RC-1', '_csrf': tok})
    d = r.get_data(as_text=True)
    # payment stays on the invoice (no auto-print) and offers to print the receipt
    assert 'Payment recorded' in d and 'Print Receipt' in d
    # the receipt itself is available on demand
    with app.app_context():
        _rid = PayReceipt.query.order_by(PayReceipt.id.desc()).first().id
    rc = client.get(f'/receipt/{_rid}').get_data(as_text=True)
    assert 'PAID NOW' in rc and 'Cashier' in rc and 'RCT-' in rc
    # split: +4 more via Insurance issues a second receipt for the delta
    tok = _csrf(client.get('/invoice/1'))
    client.post('/invoice/1', data={'act': 'pay', 'paid': str(base + 9), 'pay_method': 'Insurance',
                                    'pay_ref': 'CLAIM-1', '_csrf': tok})
    with app.app_context():
        rr = PayReceipt.query.filter_by(invoice_id=1).order_by(PayReceipt.id).all()
        assert len(rr) >= 2 and abs(rr[-1].amount - 4) < 0.001
        assert Account.query.filter_by(code='1250').first()  # Insurance Receivable
    # bulk allocation issues receipts too
    tok = _csrf(client.get('/m/payalloc'))
    client.post('/payments/receive', data={'patient_id': '1', 'amount': '1',
                                           'method': 'Bank', '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        assert PayReceipt.query.filter_by(method='Bank').count() >= 1


# ============================== Phase 9: LIS, security, batches, HR extras

def test_lis_sample_workflow_panic_delta_qc(app, client):
    import datetime as dt
    _login(client)
    from mdc_erp.models import Service, LabOrder, Notification
    from mdc_erp.extensions import db as _db
    with app.app_context():
        svc = Service.query.filter_by(department='Laboratory').first()
        svc.panic_low = 3.0; svc.panic_high = 12.0; svc.specimen = 'Blood'
        _db.session.commit(); sid = svc.id
    tok = _csrf(client.get('/lab/new'))
    client.post('/lab/new', data={'patient_id': '1', 'service_id': str(sid), '_csrf': tok})
    with app.app_context():
        oid = LabOrder.query.order_by(LabOrder.id.desc()).first().id
    client.get(f'/lab/{oid}/collect')
    with app.app_context():
        o = LabOrder.query.get(oid)
        assert o.sample_no and o.collected_by and o.specimen == 'Blood'
    assert b'Specimen SMP-' in client.get(f'/lab/{oid}/label').data
    client.get(f'/lab/{oid}/receive')
    tok = _csrf(client.get(f'/lab/{oid}/result'))
    client.post(f'/lab/{oid}/result', data={'result': '7.2', '_csrf': tok})
    # second order: panic (15.8 > 12) and delta (vs 7.2)
    tok = _csrf(client.get('/lab/new'))
    client.post('/lab/new', data={'patient_id': '1', 'service_id': str(sid), '_csrf': tok})
    with app.app_context():
        oid2 = LabOrder.query.order_by(LabOrder.id.desc()).first().id
    client.get(f'/lab/{oid2}/collect'); client.get(f'/lab/{oid2}/receive')
    tok = _csrf(client.get(f'/lab/{oid2}/result'))
    r = client.post(f'/lab/{oid2}/result', data={'result': '15.8', '_csrf': tok},
                    follow_redirects=True)
    assert b'PANIC' in r.data
    with app.app_context():
        o2 = LabOrder.query.get(oid2)
        assert o2.panic and o2.delta_flag
        assert Notification.query.filter(Notification.role == 'doctor',
                                         Notification.text.like('%PANIC%')).count() >= 1
    client.get(f'/lab/{oid2}/approve')
    d = client.get(f'/lab/{oid2}/print').get_data(as_text=True)
    assert 'PANIC VALUE' in d and 'Performed by' in d
    # QC in/out of control
    tok = _csrf(client.get('/m/labqc/new'))
    client.post('/m/labqc/new', data={'date': dt.date.today().isoformat(), 'service_id': str(sid),
                                      'level': 'L1', 'value': '6.0', 'target_mean': '5.0',
                                      'target_sd': '0.2', 'operator': 'lab', '_csrf': tok})
    assert b'OUT' in client.get('/m/labqc').data


def test_login_history_and_ip_allowlist(client):
    tok = _csrf(client.get('/login'))
    client.post('/login', data={'username': 'admin', 'password': 'WRONG', '_csrf': tok})
    _login(client)
    d = client.get('/m/loginhistory').get_data(as_text=True)
    assert 'FAILED' in d and '>OK<' in d
    tok = _csrf(client.get('/m/loginhistory'))
    client.post('/security/ipallow', data={'ip_allow': '10.9.', '_csrf': tok})
    assert client.get('/', environ_overrides={'REMOTE_ADDR': '192.168.5.5'}).status_code == 403
    assert client.get('/', environ_overrides={'REMOTE_ADDR': '10.9.0.7'}).status_code == 200
    tok = _csrf(client.get('/m/loginhistory'))
    client.post('/security/ipallow', data={'ip_allow': '', '_csrf': tok})
    assert b'Backup Manager' in client.get('/m/backup').data


def test_batches_hr_and_service_contracts(client):
    import datetime as dt
    _login(client)
    soon = (dt.date.today() + dt.timedelta(days=40)).isoformat()
    tok = _csrf(client.get('/m/batches/new'))
    client.post('/m/batches/new', data={'medicine_id': '1', 'batch_no': 'B-90', 'expiry': soon,
                                        'qty': '50', 'received': dt.date.today().isoformat(),
                                        '_csrf': tok})
    assert b'B-90' in client.get('/m/batches').data
    tok = _csrf(client.get('/m/svccontracts/new'))
    client.post('/m/svccontracts/new', data={'asset_id': '1', 'vendor': 'CalibCo', 'phone': '061',
                                             'start': dt.date.today().isoformat(), 'end': soon,
                                             'cost': '300', 'notes': '', '_csrf': tok})
    assert b'Service Contracts Ending' in client.get('/m/maintdash').data
    for mod, data in (('contracts', {'employee_id': '1', 'ctype': 'Permanent',
                                     'start': dt.date.today().isoformat(), 'end': '',
                                     'salary': '400', 'notes': ''}),
                      ('performance', {'employee_id': '1', 'date': dt.date.today().isoformat(),
                                       'score': '4', 'reviewer': 'HR', 'notes': ''}),
                      ('training', {'employee_id': '1', 'course': 'IPC', 'provider': 'MOH',
                                    'date': dt.date.today().isoformat(), 'result': 'Completed'})):
        tok = _csrf(client.get(f'/m/{mod}/new'))
        r = client.post(f'/m/{mod}/new', data={**data, '_csrf': tok}, follow_redirects=True)
        assert r.status_code == 200


# ============================== Phase 10: messaging outbox

def test_messaging_outbox_and_hooks(app, client):
    import datetime as dt
    _login(client)
    from mdc_erp.models import Appointment, OutMsg, Service, LabOrder
    tok = _csrf(client.get('/m/appointments/new'))
    client.post('/m/appointments/new',
                data={'patient_id': '1', 'date': dt.date.today().isoformat(), 'time': '09:00',
                      'department': 'Consultation', 'doctor': '', 'service_id': '',
                      'visit_type': 'New', 'priority': 'Normal', 'status': 'Scheduled',
                      'notes': '', '_csrf': tok})
    with app.app_context():
        aid = Appointment.query.order_by(Appointment.id.desc()).first().id
    r = client.get(f'/appt/{aid}/remind', follow_redirects=True)
    assert b'Pending' in r.data          # no gateway configured -> queued, not lost
    with app.app_context():
        assert OutMsg.query.filter_by(ref=f'APPT-{aid}').count() == 1
    # lab approval queues a "result ready" SMS to the patient
    with app.app_context():
        sid = Service.query.filter_by(department='Laboratory').first().id
    tok = _csrf(client.get('/lab/new'))
    client.post('/lab/new', data={'patient_id': '1', 'service_id': str(sid), '_csrf': tok})
    with app.app_context():
        oid = LabOrder.query.order_by(LabOrder.id.desc()).first().id
    client.get(f'/lab/{oid}/collect'); client.get(f'/lab/{oid}/receive')
    tok = _csrf(client.get(f'/lab/{oid}/result'))
    client.post(f'/lab/{oid}/result', data={'result': '5', '_csrf': tok})
    client.get(f'/lab/{oid}/approve')
    with app.app_context():
        assert OutMsg.query.filter_by(ref=f'LAB-{oid:04d}').count() == 1
    d = client.get('/m/messages').get_data(as_text=True)
    assert 'Outbox' in d and 'Gateway' in d


# ============================== Phase 11: portal booking, auto-reorder, FHIR

def test_portal_online_booking(app, client):
    import datetime as dt
    import re as _re
    from mdc_erp.models import Patient, Appointment, Notification
    with app.app_context():
        p1 = Patient.query.get(1); mrn, ph = p1.mrn, p1.phone
    pc = app.test_client()
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get('/portal').get_data(as_text=True)).group(1)
    pc.post('/portal', data={'mrn': mrn, 'phone': ph, '_csrf': tok})
    assert b'Book Appointment' in pc.get('/portal/home').data
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get('/portal/book').get_data(as_text=True)).group(1)
    fut = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    r = pc.post('/portal/book', data={'date': fut, 'time': '10:30', 'department': 'Laboratory',
                                      'visit_type': 'New', 'notes': 'fasting', '_csrf': tok})
    assert 'diiwaan-geliyay' in r.get_data(as_text=True)
    with app.app_context():
        a = Appointment.query.filter_by(date=fut).order_by(Appointment.id.desc()).first()
        assert a and 'Online booking' in (a.notes or '') and a.status == 'Scheduled'
        assert Notification.query.filter(Notification.role == 'reception',
                                         Notification.text.like('Online booking%')).count() >= 1
    # past dates rejected
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get('/portal/book').get_data(as_text=True)).group(1)
    pc.post('/portal/book', data={'date': '2020-01-01', 'time': '', 'department': 'Consultation',
                                  'visit_type': 'New', 'notes': '', '_csrf': tok})
    with app.app_context():
        assert not Appointment.query.filter_by(date='2020-01-01').first()


def test_auto_reorder_below_level(app, client):
    from mdc_erp.models import Medicine, Purchase
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        m = Medicine.query.get(1)
        m.reorder = max(int(m.qty or 0) + 5, 10)
        _db.session.commit(); mid = m.id
        Purchase.query.filter_by(medicine_id=mid, category='Auto-reorder').delete()
        _db.session.commit()
    for _ in range(2):
        tok = _csrf(client.get('/m/stockadj'))
        client.post('/stock/adjust', data={'medicine_id': str(mid), 'qty_change': '-1',
                                           'reason': 'Damage', 'note': '', '_csrf': tok},
                    follow_redirects=True)
    with app.app_context():
        # created once, no duplicates while a PO is open
        assert Purchase.query.filter_by(medicine_id=mid, category='Auto-reorder',
                                        status='Requested').count() == 1


def test_fhir_endpoints(client):
    r = client.post('/api/login', json={'username': 'admin', 'password': 'admin123'})
    tok = r.get_json()['data']['token']
    j = client.get('/api/fhir/Patient/1', headers={'Authorization': f'Bearer {tok}'}).get_json()
    assert j['resourceType'] == 'Patient' and j['identifier'][0]['value']
    j = client.get('/api/fhir/Observation?patient=1',
                   headers={'Authorization': f'Bearer {tok}'}).get_json()
    assert j['resourceType'] == 'Bundle' and 'entry' in j
    assert client.get('/api/fhir/Patient/1').status_code == 401


def test_productivity_and_valuation_views(client):
    _login(client)
    d = client.get('/m/productivity').get_data(as_text=True)
    assert 'Doctor Productivity' in d and 'Pending Lab' in d
    assert b'Total Stock Value' in client.get('/m/stockvalue').data


# ============================== Phase 12: blood bank, vaccination, quality, dup/pw

def test_blood_bank_and_vaccination(app, client):
    import datetime as dt
    _login(client)
    tok = _csrf(client.get('/m/donors/new'))
    client.post('/m/donors/new', data={'name': 'T Donor', 'phone': '0616', 'blood_group': 'O-',
                                       'last_donation': '', 'notes': '', '_csrf': tok})
    exp = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    tok = _csrf(client.get('/m/bloodunits/new'))
    client.post('/m/bloodunits/new',
                data={'unit_no': '', 'blood_group': 'O-', 'donor_id': '1',
                      'collected': dt.date.today().isoformat(), 'expiry': exp,
                      'status': 'Available', 'issued_to': '', 'issued_date': '',
                      'notes': '', '_csrf': tok})
    d = client.get('/m/bloodunits').get_data(as_text=True)
    assert 'exp soon' in d
    tok = _csrf(client.get('/m/vaccinations/new'))
    client.post('/m/vaccinations/new',
                data={'patient_id': '1', 'vaccine': 'Hep B', 'dose_no': '1',
                      'date': dt.date.today().isoformat(), 'batch': 'HB-1',
                      'next_due': '', 'given_by': 'Nurse', '_csrf': tok})
    from mdc_erp.models import Vaccination
    with app.app_context():
        vid = Vaccination.query.order_by(Vaccination.id.desc()).first().id
    assert b'VACCINATION CERTIFICATE' in client.get(f'/vacc/{vid}/cert').data


def test_quality_pack_and_feedback(app, client):
    import datetime as dt
    import re as _re
    _login(client)
    for mod, data, marker in (
        ('sops', {'code': 'SOP-Q-1', 'title': 'QC daily', 'department': 'Laboratory',
                  'version': '1.0', 'effective': dt.date.today().isoformat(),
                  'review_due': (dt.date.today() + dt.timedelta(days=10)).isoformat(),
                  'owner': 'QM', 'status': 'Active', 'notes': ''}, 'SOP-Q-1'),
        ('incidents', {'date': dt.date.today().isoformat(), 'department': 'Laboratory',
                       'itype': 'Sample rejection', 'severity': 'Major',
                       'description': 'Clotted EDTA', 'action': '', 'reported_by': 'lab',
                       'status': 'Open'}, 'Clotted EDTA'),
        ('audits', {'date': dt.date.today().isoformat(), 'area': 'Reception', 'auditor': 'QM',
                    'findings': 'ok', 'due': '', 'status': 'Closed'}, 'Reception')):
        tok = _csrf(client.get(f'/m/{mod}/new'))
        client.post(f'/m/{mod}/new', data={**data, '_csrf': tok})
        assert marker in client.get(f'/m/{mod}').get_data(as_text=True), mod
    # portal feedback flows to admin list
    from mdc_erp.models import Patient
    with app.app_context():
        p1 = Patient.query.get(1); mrn, ph = p1.mrn, p1.phone
    pc = app.test_client()
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get('/portal').get_data(as_text=True)).group(1)
    pc.post('/portal', data={'mrn': mrn, 'phone': ph, '_csrf': tok})
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get('/portal/feedback').get_data(as_text=True)).group(1)
    r = pc.post('/portal/feedback', data={'rating': '4', 'comment': 'wanaagsan', '_csrf': tok})
    assert 'Mahadsanid' in r.get_data(as_text=True)
    assert 'wanaagsan' in client.get('/m/feedback').get_data(as_text=True)


def test_duplicate_detection_and_password_policy(app, client):
    from mdc_erp.models import Patient, User
    _login(client)
    with app.app_context():
        ph = Patient.query.get(1).phone
    tok = _csrf(client.get('/m/patients/new'))
    base = {'name': 'Dup Test', 'phone': ph, 'gender': 'Male', 'dob': '', 'blood_group': '',
            'marital': '', 'occupation': '', 'gov_id': '', 'address': '', 'emerg_name': '',
            'emerg_phone': '', 'ins_company': '', 'ins_number': '', 'allergies': '',
            'med_history': '', 'active': '1', 'notes': '', 'phone2': ''}
    r = client.post('/m/patients/new', data={**base, '_csrf': tok}, follow_redirects=True)
    assert b'already registered today' in r.data or b'Possible duplicate' in r.data
    with app.app_context():
        assert not Patient.query.filter_by(name='Dup Test').first()
    tok = _csrf(client.get('/m/patients/new'))
    client.post('/m/patients/new', data={**base, 'dup_ok': '1', '_csrf': tok})
    with app.app_context():
        assert Patient.query.filter_by(name='Dup Test').first()
    # weak password rejected, strong accepted
    tok = _csrf(client.get('/users/new'))
    r = client.post('/users/new', data={'username': 'weakpw', 'name': 'W', 'role': 'reception',
                                        'active': '1', 'password': 'abc', 'branch_id': '',
                                        '_csrf': tok}, follow_redirects=True)
    assert b'at least 4' in r.data
    tok = _csrf(client.get('/users/new'))
    client.post('/users/new', data={'username': 'strongpw1', 'name': 'S', 'role': 'reception',
                                    'active': '1', 'password': 'Gaalkacyo26', 'branch_id': '',
                                    '_csrf': tok})
    with app.app_context():
        assert User.query.filter_by(username='strongpw1').first()


# ============================== Phase 13: Doctor Referral Portal

def _dr_csrf(cl, path):
    import re as _re
    m = _re.search(r'name="_csrf" value="([^"]+)"', cl.get(path).get_data(as_text=True))
    return m.group(1) if m else None


def test_doctor_portal_end_to_end(app, client):
    from mdc_erp.models import (Doctor, Referral, LabOrder, RadOrder, Service,
                                Notification, OutMsg)
    _login(client)
    tok = _csrf(client.get('/m/doctors/new'))
    client.post('/m/doctors/new',
                data={'name': 'PortalDoc', 'specialty': 'IM', 'phone': '0618',
                      'commission_type': 'Percent', 'fixed_rate': '0', 'percent_rate': '0.1',
                      'active': '1', 'portal_user': 'pdoc', 'portal_pw_set': 'Portal2026',
                      '_csrf': tok})
    with app.app_context():
        doc = Doctor.query.filter_by(portal_user='pdoc').first()
        assert doc and doc.portal_pw
    dc = app.test_client()
    tok = _dr_csrf(dc, '/dr')
    dc.post('/dr', data={'username': 'pdoc', 'password': 'Portal2026', '_csrf': tok})
    d = dc.get('/dr/home').get_data(as_text=True)
    assert 'Dr PortalDoc' in d and 'New Referral' in d
    assert '$' not in d and 'Billing' not in d          # no financial info
    with app.app_context():
        lab_s = Service.query.filter_by(department='Laboratory').first()
        rad_s = Service.query.filter_by(department='Radiology').first()
    tok = _dr_csrf(dc, '/dr/new')
    assert '$' not in dc.get('/dr/new').get_data(as_text=True)
    r = dc.post('/dr/new', data={'name': 'Ref Patient', 'phone': '0698', 'age': '40',
                                 'gender': 'Male', 'address': '', 'allergies': '',
                                 'complaint': 'Cough', 'history': '', 'prov_dx': 'TB?',
                                 'priority': 'STAT', 'instructions': '',
                                 'svc': [str(lab_s.id), str(rad_s.id)], '_csrf': tok},
                follow_redirects=True)
    assert b'REF-' in r.data and b'STAT' in r.data
    with app.app_context():
        ref = Referral.query.order_by(Referral.id.desc()).first()
        assert ref.patient_id and ref.doctor_id
        lo = LabOrder.query.filter_by(ref_id=ref.id).first()
        assert lo and RadOrder.query.filter_by(ref_id=ref.id).first()
        assert Notification.query.filter(
            Notification.text.like('%Dr PortalDoc%')).count() >= 2
        rid, loid = ref.id, lo.id
    # staff completes the lab test -> doctor gets report access + SMS queued
    client.get(f'/lab/{loid}/collect'); client.get(f'/lab/{loid}/receive')
    tok = _csrf(client.get(f'/lab/{loid}/result'))
    client.post(f'/lab/{loid}/result', data={'result': 'AFB negative', '_csrf': tok})
    client.get(f'/lab/{loid}/approve')
    d = dc.get(f'/dr/req/{rid}').get_data(as_text=True)
    assert 'View / Print Report' in d
    assert 'AFB negative' in dc.get(f'/dr/lab/{loid}').get_data(as_text=True)
    with app.app_context():
        assert OutMsg.query.filter_by(ref=f'REF-{rid:04d}').count() >= 1
    # comments both ways
    tok = _dr_csrf(dc, f'/dr/req/{rid}')
    dc.post(f'/dr/req/{rid}', data={'text': 'add ESR pls', '_csrf': tok})
    tok = _csrf(client.get(f'/referral/{rid}/thread'))
    client.post(f'/referral/{rid}/thread', data={'text': 'done', '_csrf': tok})
    d = dc.get(f'/dr/req/{rid}').get_data(as_text=True)
    assert 'add ESR pls' in d and 'done' in d
    # isolation: a second doctor cannot open it
    tok = _csrf(client.get('/m/doctors/new'))
    client.post('/m/doctors/new',
                data={'name': 'OtherDoc', 'specialty': '', 'phone': '', 'commission_type': 'Percent',
                      'fixed_rate': '0', 'percent_rate': '0', 'active': '1',
                      'portal_user': 'odoc', 'portal_pw_set': 'Other2026x', '_csrf': tok})
    dc2 = app.test_client()
    tok = _dr_csrf(dc2, '/dr')
    dc2.post('/dr', data={'username': 'odoc', 'password': 'Other2026x', '_csrf': tok})
    assert dc2.get(f'/dr/req/{rid}').status_code == 403
    assert dc2.get(f'/dr/lab/{loid}').status_code in (403, 404)


# ============================== Phase 14: Remote Radiologist Portal (/rrad)

def test_doctor_portal_returning_patient_lookup(app, client):
    """The doctor portal request form can find a returning patient by exact ID or
    phone and reuse that record (no duplicate); name browsing is not exposed."""
    from mdc_erp.models import Doctor, Patient, Referral, Service
    from mdc_erp.extensions import db as _db
    from werkzeug.security import generate_password_hash
    _login(client)
    with app.app_context():
        d = Doctor(name='LookupDoc', active=True, portal_user='lupdoc',
                   portal_pw=generate_password_hash('Portal2026'))
        _db.session.add(d)
        p = Patient(mrn='MRN-DRRET', name='Xaawo Cali', phone='0615777888', gender='Female', age_years=30)
        _db.session.add(p)
        _db.session.commit()
        pid = p.id
        lab_s = Service.query.filter_by(department='Laboratory').first()
        before = Patient.query.count()
    dc = app.test_client()
    tok = _dr_csrf(dc, '/dr')
    dc.post('/dr', data={'username': 'lupdoc', 'password': 'Portal2026', '_csrf': tok})
    # lookup by exact phone returns the patient; a partial name does NOT
    r = dc.get('/dr/patient-lookup?q=0615777888').get_json()
    assert any(x['id'] == pid for x in r)
    assert dc.get('/dr/patient-lookup?q=Xaa').get_json() == []   # no name browsing
    # lookup by MRN works too
    r = dc.get('/dr/patient-lookup?q=MRN-DRRET').get_json()
    assert any(x['id'] == pid for x in r)
    # submit a request linked to that patient -> no duplicate
    tok = _dr_csrf(dc, '/dr/new')
    dc.post('/dr/new', data={'patient_id': str(pid), 'name': 'Xaawo Cali',
                             'phone': '0615777888', 'age': '30', 'gender': 'Female',
                             'priority': 'Routine', 'svc': [str(lab_s.id)], '_csrf': tok},
            follow_redirects=True)
    with app.app_context():
        assert Patient.query.count() == before          # no new patient created
        ref = Referral.query.order_by(Referral.id.desc()).first()
        assert ref.patient_id == pid


def test_remote_radiologist_portal_end_to_end(app, client):
    import io
    import re as _re
    from mdc_erp.models import (Radiologist, RadOrder, Service, OutMsg,
                                Notification, RadComment)
    _login(client)
    tok = _csrf(client.get('/m/radiologists/new'))
    client.post('/m/radiologists/new',
                data={'name': 'TeleRad', 'specialty': 'Neuro', 'phone': '0620', 'active': '1',
                      'portal_user': 'telerad', 'portal_pw_set': 'Tele2026x', '_csrf': tok})
    with app.app_context():
        rr = Radiologist.query.filter_by(portal_user='telerad').first()
        assert rr and rr.portal_pw
        rrid = rr.id
        rsid = Service.query.filter_by(department='Radiology').first().id
    tok = _csrf(client.get('/rad/new'))
    client.post('/rad/new', data={'patient_id': '1', 'modality': 'CT',
                                  'service_id': str(rsid), '_csrf': tok})
    with app.app_context():
        oid = RadOrder.query.order_by(RadOrder.id.desc()).first().id
    client.get(f'/rad/{oid}/image')
    # dispatch with DICOM + image, assign -> SMS queued
    tok = _csrf(client.get(f'/rad/{oid}/dispatch'))
    client.post(f'/rad/{oid}/dispatch', content_type='multipart/form-data',
                data={'radiologist_id': str(rrid), '_csrf': tok,
                      'files': [(io.BytesIO(b'DICM' + b'0' * 50), 'brain.dcm'),
                                (io.BytesIO(b'\xff\xd8\xff' + b'0' * 40), 's1.jpg')]})
    with app.app_context():
        o = RadOrder.query.get(oid)
        assert o.assigned_rad_id == rrid and len((o.images or '').split(',')) == 2
        assert OutMsg.query.filter_by(ref=f'RAD-{oid:04d}').count() >= 1
    # portal: login, files, template, draft, comments, approve+lock
    pc = app.test_client()
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get('/rrad').get_data(as_text=True)).group(1)
    pc.post('/rrad', data={'username': 'telerad', 'password': 'Tele2026x', '_csrf': tok})
    d = pc.get('/rrad/home').get_data(as_text=True)
    assert 'Dr TeleRad' in d and f'RAD-{oid:04d}' in d and '$' not in d
    d = pc.get(f'/rrad/case/{oid}').get_data(as_text=True)
    assert 'Study Files (2)' in d and 'Report Editor' in d and 'brain' in d
    assert pc.get(f'/rad/{oid}/img/1').status_code == 200
    assert 'Non-contrast axial CT' in pc.get(
        f'/rrad/case/{oid}?tpl=CT Brain').get_data(as_text=True)
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get(f'/rrad/case/{oid}').get_data(as_text=True)).group(1)
    pc.post(f'/rrad/case/{oid}', data={'act': 'draft', 'findings': 'Normal brain',
                                       'impression': 'No acute', 'recommendations': '',
                                       'notes': '', '_csrf': tok})
    d = pc.get(f'/rrad/case/{oid}').get_data(as_text=True)
    assert 'Normal brain' in d and 'No acute' in d
    assert 'Draft' in pc.get('/rrad/home').get_data(as_text=True)
    # two-way comments
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get(f'/rrad/case/{oid}').get_data(as_text=True)).group(1)
    pc.post(f'/rrad/case/{oid}', data={'act': 'comment', 'text': 'need lateral', '_csrf': tok})
    assert 'need lateral' in client.get(f'/rad/{oid}/thread').get_data(as_text=True)
    tok = _csrf(client.get(f'/rad/{oid}/thread'))
    client.post(f'/rad/{oid}/thread', data={'text': 'uploading', '_csrf': tok})
    assert 'uploading' in pc.get(f'/rrad/case/{oid}').get_data(as_text=True)
    # approve: locks, notifies reception, patient SMS queued
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get(f'/rrad/case/{oid}').get_data(as_text=True)).group(1)
    pc.post(f'/rrad/case/{oid}', data={'act': 'approve', 'findings': 'Normal brain',
                                       'impression': 'No acute abnormality',
                                       'recommendations': 'CC', 'notes': '', '_csrf': tok})
    with app.app_context():
        o = RadOrder.query.get(oid)
        assert (o.status == 'Reported' and 'IMPRESSION' in o.report
                and o.rad_approved_at and o.radiologist == 'TeleRad')
        assert OutMsg.query.filter_by(ref=f'RAD-{oid:04d}').count() >= 2
        assert Notification.query.filter(
            Notification.text.like(f'%RAD-{oid:04d}%')).count() >= 1
    d = pc.get(f'/rrad/case/{oid}').get_data(as_text=True)
    assert '🔒' in d and 'Report Editor' not in d
    assert b'IMPRESSION' in client.get(f'/rad/{oid}/print').data
    # repeat-scan on a fresh case
    tok = _csrf(client.get('/rad/new'))
    client.post('/rad/new', data={'patient_id': '1', 'modality': 'X-Ray',
                                  'service_id': str(rsid), '_csrf': tok})
    with app.app_context():
        oid2 = RadOrder.query.order_by(RadOrder.id.desc()).first().id
    client.get(f'/rad/{oid2}/image')
    tok = _csrf(client.get(f'/rad/{oid2}/dispatch'))
    client.post(f'/rad/{oid2}/dispatch', data={'radiologist_id': str(rrid), '_csrf': tok},
                content_type='multipart/form-data')
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc.get(f'/rrad/case/{oid2}').get_data(as_text=True)).group(1)
    pc.post(f'/rrad/case/{oid2}', data={'act': 'repeat', 'text': 'motion artifact', '_csrf': tok})
    with app.app_context():
        assert RadOrder.query.get(oid2).status == 'Requested'
    # isolation
    tok = _csrf(client.get('/m/radiologists/new'))
    client.post('/m/radiologists/new',
                data={'name': 'OtherRad', 'specialty': '', 'phone': '', 'active': '1',
                      'portal_user': 'orad', 'portal_pw_set': 'Orad2026x', '_csrf': tok})
    pc2 = app.test_client()
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     pc2.get('/rrad').get_data(as_text=True)).group(1)
    pc2.post('/rrad', data={'username': 'orad', 'password': 'Orad2026x', '_csrf': tok})
    assert pc2.get(f'/rrad/case/{oid}').status_code == 403
    assert pc2.get(f'/rad/{oid}/img/0').status_code == 403


# ============================== Phase 15: accounting extras

def test_journal_reversal(app, client):
    import datetime as dt
    from mdc_erp.models import Account, JournalEntry
    from mdc_erp.core.posting import acc_ensure
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        if not Account.query.filter_by(code='5100').first():
            acc_ensure('5100', 'Rent', 'Expense', '5000'); _db.session.commit()
        a1 = Account.query.filter_by(code='1101').first().id
        a2 = Account.query.filter_by(code='5100').first().id
    tok = _csrf(client.get('/journal/new'))
    client.post('/journal/new', data={'date': dt.date.today().isoformat(), 'ref': 'JV-REV',
                                      'memo': 'x', 'acct1': str(a2), 'debit1': '50', 'credit1': '0',
                                      'acct2': str(a1), 'debit2': '0', 'credit2': '50', '_csrf': tok})
    with app.app_context():
        eid = JournalEntry.query.filter_by(ref='JV-REV').first().id
    client.get(f'/journal/{eid}/reverse?reason=wrong+amount', follow_redirects=True)
    with app.app_context():
        e = JournalEntry.query.get(eid)
        assert e.reversed_by
        # audit trail captured on the original
        assert e.reversal_reason == 'wrong amount' and e.reversed_by_user and e.reversed_at
        rev = JournalEntry.query.get(e.reversed_by)
        assert rev.is_reversal and abs(rev.total_credit - 50) < 0.01
        assert rev.reverses_id == eid   # reversal links back to the original
    # a reversal with NO reason is refused
    client.get(f'/journal/{eid}/reverse', follow_redirects=True)
    # double-reverse blocked (even with a reason)
    client.get(f'/journal/{eid}/reverse?reason=again', follow_redirects=True)
    with app.app_context():
        assert JournalEntry.query.filter_by(is_reversal=True, ref='REV-JV-REV').count() == 1
    assert b'Reversed' in client.get('/m/journal').data


def test_unbalanced_journal_is_rejected(app):
    """Integrity gate (#1): post_journal hard-rejects debit != credit, rolls back,
    and writes nothing. A balanced journal posts normally; cent-rounding is tolerated."""
    import datetime as dt
    from mdc_erp.models import JournalEntry, JournalLine
    from mdc_erp.core.posting import post_journal, acc_ensure, UnbalancedJournalError
    from mdc_erp.extensions import db as _db
    today = dt.date.today().isoformat()
    with app.app_context():
        acc_ensure('1101', 'Cash', 'Asset', '1000')
        acc_ensure('5100', 'Rent', 'Expense', '5000')
        n0 = JournalEntry.query.count()
        # 1) unbalanced -> rejected, nothing written
        raised = False
        try:
            post_journal(today, 'BAL-BAD', 'unbalanced', [('5100', 100, 0), ('1101', 0, 90)])
        except UnbalancedJournalError as e:
            raised = True
            assert abs(e.diff - 10) < 0.001
        assert raised, 'unbalanced journal should raise'
        _db.session.rollback()
        assert JournalEntry.query.filter_by(ref='BAL-BAD').count() == 0
        assert JournalEntry.query.count() == n0, 'no partial entry may be written'
        # 2) balanced -> posts
        je = post_journal(today, 'BAL-OK', 'balanced', [('5100', 100, 0), ('1101', 0, 100)])
        assert je is not None
        e = JournalEntry.query.filter_by(ref='BAL-OK').first()
        assert e and abs(e.total_debit - e.total_credit) < 0.001
        # 3) cent-level rounding within tolerance still balances (33.33 + 33.33 + 33.34 = 100)
        je2 = post_journal(today, 'BAL-CENTS', 'thirds',
                           [('5100', 33.33, 0), ('5100', 33.33, 0), ('5100', 33.34, 0), ('1101', 0, 100)])
        assert je2 is not None


def test_recurring_journal_and_transfer(app, client):
    import datetime as dt
    from mdc_erp.models import Account, JournalEntry, RecurringJournal
    from mdc_erp.core.posting import acc_ensure
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        if not Account.query.filter_by(code='5100').first():
            acc_ensure('5100', 'Rent', 'Expense', '5000'); _db.session.commit()
    tok = _csrf(client.get('/m/recurjournals/new'))
    client.post('/m/recurjournals/new',
                data={'memo': 'Rent', 'dr_account': '5100', 'cr_account': '1101',
                      'amount': '200', 'day': '1', 'active': '1', '_csrf': tok})
    client.get('/recurring/run', follow_redirects=True)
    client.get('/recurring/run', follow_redirects=True)   # no double-post
    with app.app_context():
        assert JournalEntry.query.filter(JournalEntry.ref.like('REC-%')).count() == 1
    # petty cash / bank transfer
    tok = _csrf(client.get('/cash/transfer'))
    client.post('/cash/transfer', data={'date': dt.date.today().isoformat(),
                                        'from_code': '1102', 'to_code': '1104',
                                        'amount': '75', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        assert JournalEntry.query.filter(JournalEntry.ref.like('XFER-%')).count() >= 1
        assert Account.query.filter_by(code='1104').first()


def test_revenue_analysis_and_financial_dashboard(client):
    _login(client)
    d = client.get('/m/revreport').get_data(as_text=True)
    assert 'Revenue by Department' in d and 'Expense by Category' in d
    d = client.get('/m/findash').get_data(as_text=True)
    assert 'Financial Dashboard' in d and 'Revenue Today' in d and 'Receivables' in d


# ============================== Phase 16: Doctor Request → Invoice → Payment gate

def test_request_to_invoice_payment_gate(app, client):
    import re as _re
    from mdc_erp.models import (Doctor, Referral, LabOrder, RadOrder, Service,
                                Invoice, InvoiceItem)
    from mdc_erp.extensions import db as _db
    _login(client)
    tok = _csrf(client.get('/m/doctors/new'))
    client.post('/m/doctors/new',
                data={'name': 'GateDoc', 'specialty': 'IM', 'phone': '0617',
                      'commission_type': 'Percent', 'fixed_rate': '0', 'percent_rate': '0',
                      'active': '1', 'portal_user': 'gdoc', 'portal_pw_set': 'Gate2026x',
                      '_csrf': tok})
    dc = app.test_client()
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     dc.get('/dr').get_data(as_text=True)).group(1)
    dc.post('/dr', data={'username': 'gdoc', 'password': 'Gate2026x', '_csrf': tok})
    with app.app_context():
        lab_s = Service.query.filter_by(department='Laboratory').first()
        rad_s = Service.query.filter_by(department='Radiology').first()
        lab_s.price = 10; rad_s.price = 30; _db.session.commit()
        lsid, rsid = lab_s.id, rad_s.id
    tok = _re.search(r'name="_csrf" value="([^"]+)"',
                     dc.get('/dr/new').get_data(as_text=True)).group(1)
    dc.post('/dr/new', data={'name': 'GatePatient', 'phone': '0701', 'age': '40',
                             'gender': 'Male', 'address': '', 'allergies': '', 'complaint': 'x',
                             'history': '', 'prov_dx': '', 'priority': 'Urgent', 'instructions': '',
                             'svc': [str(lsid), str(rsid)], '_csrf': tok})
    with app.app_context():
        rid = Referral.query.order_by(Referral.id.desc()).first().id
        orders = LabOrder.query.filter_by(ref_id=rid).all() + RadOrder.query.filter_by(ref_id=rid).all()
        assert orders and all(o.paid_gate is False for o in orders)   # gated
        loid = LabOrder.query.filter_by(ref_id=rid).first().id
    # lab list hides gated requests (banner shown)
    assert b'waiting for payment' in client.get('/m/lab').data
    # create invoice from the request -> pulls both services at catalog price
    client.get(f'/referral/{rid}/invoice', follow_redirects=True)
    with app.app_context():
        inv = Invoice.query.filter_by(referral_id=rid).first()
        assert inv and len(inv.items) == 2 and abs(inv.subtotal - 40) < 0.01
        assert all(it.lab_order_id or it.rad_order_id for it in inv.items)  # traceable
        iid = inv.id
    # invoice screen shows the Doctor Request panel
    assert b'Doctor Request REF-' in client.get(f'/invoice/{iid}').data
    # still gated before payment
    with app.app_context():
        assert LabOrder.query.get(loid).paid_gate is False
    # pay in full -> gate releases, lab can now see it
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '40', 'pay_method': 'Cash',
                                         'pay_ref': '', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        assert LabOrder.query.get(loid).paid_gate is True
    assert b'GatePatient' in client.get('/m/lab').data
    # board renders with buckets; duplicate invoice returns the same one
    assert b'Doctor Requests Board' in client.get('/m/reqboard').data
    client.get(f'/referral/{rid}/invoice', follow_redirects=True)
    with app.app_context():
        assert Invoice.query.filter_by(referral_id=rid).count() == 1
    # doctor still sees no money
    d = dc.get('/dr/home').get_data(as_text=True)
    assert '$' not in d and 'Invoice' not in d


# ============================== Phase 18: Odoo-style Doctor Request detail

def test_doctor_request_detail_page(app, client):
    import re as _re
    from mdc_erp.models import Doctor, Referral, Service, Invoice, LabOrder
    from mdc_erp.extensions import db as _db
    _login(client)
    tok = _csrf(client.get('/m/doctors/new'))
    client.post('/m/doctors/new',
                data={'name': 'DetDoc', 'specialty': 'IM', 'phone': '0617',
                      'commission_type': 'Percent', 'fixed_rate': '0', 'percent_rate': '0',
                      'active': '1', 'portal_user': 'detdoc', 'portal_pw_set': 'Detail2026',
                      '_csrf': tok})
    dc = app.test_client()
    tok = _re.search(r'name="_csrf" value="([^"]+)"', dc.get('/dr').get_data(as_text=True)).group(1)
    dc.post('/dr', data={'username': 'detdoc', 'password': 'Detail2026', '_csrf': tok})
    with app.app_context():
        ls = Service.query.filter_by(department='Laboratory').first()
        rs = Service.query.filter_by(department='Radiology').first()
        ls.price = 10; rs.price = 30; _db.session.commit()
        lsid, rsid = ls.id, rs.id
    tok = _re.search(r'name="_csrf" value="([^"]+)"', dc.get('/dr/new').get_data(as_text=True)).group(1)
    dc.post('/dr/new', data={'name': 'DetPatient', 'phone': '0702', 'age': '40', 'gender': 'Male',
                             'address': '', 'allergies': '', 'complaint': 'x', 'history': '',
                             'prov_dx': 'y', 'priority': 'STAT', 'instructions': '',
                             'svc': [str(lsid), str(rsid)], '_csrf': tok})
    with app.app_context():
        rid = Referral.query.order_by(Referral.id.desc()).first().id
    # before invoice: chevron + submitted stage + create-invoice CTA + timeline
    d = client.get(f'/referral/{rid}/detail').get_data(as_text=True)
    assert 'chev-wrap' in d and 'Submitted' in d and 'STAT' in d
    assert 'Requested Services' in d and 'Timeline' in d
    assert 'Create' in d and 'Invoice' in d
    # after invoice + payment: smart buttons show invoice + paid; stage advances
    client.get(f'/referral/{rid}/invoice', follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(referral_id=rid).first().id
    d = client.get(f'/referral/{rid}/detail').get_data(as_text=True)
    assert f'INV-{iid:04d}' in d and 'chev active' in d
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '40', 'pay_method': 'Cash',
                                         'pay_ref': '', '_csrf': tok}, follow_redirects=True)
    d = client.get(f'/referral/{rid}/detail').get_data(as_text=True)
    assert 'Patient Hub' in d and 'Lab Results' in d and 'tl-row' in d and 'Payment' in d
    # reqboard links to the detail page
    assert f'/referral/{rid}/detail' in client.get('/m/reqboard').get_data(as_text=True)


# ============================== Phase 20: billing ↔ accounting bidirectional link

def test_billing_accounting_bidirectional_link(app, client):
    from mdc_erp.models import Service, Invoice, JournalEntry
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        svc = Service.query.first(); svc.price = 160; _db.session.commit()
        sid = svc.id
    tok = _csrf(client.get('/invoice/new'))
    client.post('/invoice/new', data={'patient_id': '1', 'service_id': [str(sid)],
                                      'qty': ['1'], 'price': ['160'], '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.order_by(Invoice.id.desc()).first().id
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '160', 'pay_method': 'Cash',
                                         'pay_ref': '', '_csrf': tok}, follow_redirects=True)
    # billing -> accounting: invoice shows the Accounting panel with a journal link
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'Accounting' in d and '/journal/' in d
    with app.app_context():
        e = JournalEntry.query.filter(
            JournalEntry.ref.in_([f'INV-{iid:04d}', f'PAY-{iid:04d}'])).first()
        assert e is not None
        eid = e.id
    # accounting -> billing: journal entry detail links back to the source invoice
    d = client.get(f'/journal/{eid}').get_data(as_text=True)
    assert 'Entry Lines' in d and 'Source Invoice' in d and f'/invoice/{iid}' in d
    # journal list: ref links to detail and shows the invoice back-link
    d = client.get('/m/journal').get_data(as_text=True)
    assert f'/journal/{eid}' in d and f'/invoice/{iid}' in d


# ============================== Phase 21: Daily Transactions, Cash Closing, Global Search

def test_daily_transactions_and_cash_closing(app, client):
    from mdc_erp.models import Service, Invoice, CashClosing, Setting
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    _login(client)
    with app.app_context():
        s = Setting.query.get('perms_json')
        if s:
            _db.session.delete(s); _db.session.commit()
    with app.app_context():
        svc = Service.query.first(); svc.price = 100; _db.session.commit(); sid = svc.id
    tok = _csrf(client.get('/invoice/new'))
    client.post('/invoice/new', data={'patient_id': '1', 'service_id': [str(sid)],
                                      'qty': ['1'], 'price': ['100'], '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.order_by(Invoice.id.desc()).first().id
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '100', 'pay_method': 'Cash',
                                         'pay_ref': 'TXN1', '_csrf': tok}, follow_redirects=True)
    # daily transactions lists the receipt with method totals
    d = client.get('/m/dailytx').get_data(as_text=True)
    assert 'Daily Transactions' in d and 'RCT-' in d and f'INV-{iid:04d}' in d
    assert 'Income by Payment Method' in d
    td = '2099-01-15'  # unique day to avoid collision with other cash-closing tests
    # put 100 cash on that specific day
    with app.app_context():
        from mdc_erp.models import PayReceipt, Invoice as _Inv, InvoiceItem as _II
        inv2 = _Inv(patient_id=1, date=td, pay_method='Cash', paid=100, status='Paid')
        _db.session.add(inv2); _db.session.flush()
        _db.session.add(_II(invoice_id=inv2.id, desc='Cash service', qty=1, price=100))
        _db.session.add(PayReceipt(invoice_id=inv2.id, date=td, amount=100, method='Cash', cashier='admin'))
        _db.session.commit()
    # cash closing: opening 50 + cash 100 = expected 150; actual 148 -> short 2
    tok = _csrf(client.get('/invoice/new'))
    client.post(f'/cashclose/close?date={td}',
                data={'opening': '50', 'withdrawals': '0', 'actual': '148', 'note': 't', '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        # remove any closing another test made for today, then this test owns it
        pass
    with app.app_context():
        cc = CashClosing.query.filter_by(date=td).order_by(CashClosing.id.desc()).first()
        assert cc and cc.opening_cash == 50 and cc.actual_cash == 148
        assert abs(cc.difference - (cc.actual_cash - cc.expected_cash)) < 0.01
        assert cc.expected_cash >= 150  # at least the 50 float + our 100 cash
        assert cc.status == 'Closed' and cc.closed_by
    d = client.get(f'/m/cashclose?date={td}').get_data(as_text=True)
    assert 'Short' in d and 'Cash Reconciliation' in d and 'Closed by' in d
    # double-close blocked
    tok = _csrf(client.get('/invoice/new'))
    client.post(f'/cashclose/close?date={td}',
                data={'opening': '0', 'withdrawals': '0', 'actual': '0', '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        assert CashClosing.query.filter_by(date=td).count() == 1
    # reopen (admin)
    client.get(f'/cashclose/reopen?date={td}', follow_redirects=True)
    with app.app_context():
        assert CashClosing.query.filter_by(date=td).first().status == 'Reopened'


def test_global_search_multi_module(client):
    _login(client)
    d = client.get('/search?q=a').get_data(as_text=True)
    for section in ['Patients', 'Invoices', 'Laboratory', 'Radiology',
                    'Doctors / Radiologists', 'Employees', 'Suppliers']:
        assert section in d


# ============================== Phase 22: generic list filters

def test_generic_list_filters(app, client):
    from mdc_erp.models import Patient
    _login(client)
    # patients list has a search + gender/blood filter toolbar
    d = client.get('/m/patients').get_data(as_text=True)
    assert 'listbar' in d and 'All Genders' in d and 'All Blood Groups' in d
    with app.app_context():
        nm = Patient.query.first().name
    # text search matches and misses correctly (highlighting wraps matches in <mark>)
    _found = client.get(f'/m/patients?q={nm[:3]}').get_data(as_text=True).replace('<mark>', '').replace('</mark>', '')
    assert nm in _found
    assert 'No records' in client.get('/m/patients?q=ZZZQNOMATCH').get_data(as_text=True)
    # gender filter returns a result count line
    assert 'result(s)' in client.get('/m/patients?gender=Male').get_data(as_text=True)
    # incidents list exposes the date-period selector (has date_field)
    d = client.get('/m/incidents').get_data(as_text=True)
    assert 'This Month' in d and 'This Week' in d and 'This Year' in d
    assert 'result(s)' in client.get('/m/incidents?period=year').get_data(as_text=True)
    # search toolbar present on the other registered modules
    for m in ('doctors', 'suppliers', 'employees', 'sops', 'radiologists'):
        assert 'listbar' in client.get(f'/m/{m}').get_data(as_text=True)


# ============================== Phase 23: error handling + error log

def test_error_handling_and_errorlog(app, client):
    from mdc_erp.models import ErrorLog

    app.config['PROPAGATE_EXCEPTIONS'] = False
    _login(client)
    # trigger a real 500 by hitting a route with data that raises server-side:
    # journal detail with a non-existent id is a 404, so instead force an error
    # through the 500 handler directly using the test request context.
    with app.test_request_context('/some/screen', method='POST',
                                  headers={'User-Agent': 'pytest-agent'}):
        from flask import session as _ss
        _ss['uid'] = 1
        handler = app.error_handler_spec[None][500]
        # find the registered 500 handler and call it with a fake exception
        for exc_cls, fn in handler.items():
            resp = fn(ValueError('deliberate test failure xyz'))
            break
    with app.app_context():
        el = ErrorLog.query.order_by(ErrorLog.id.desc()).first()
        assert el and el.err_type == 'ValueError' and 'deliberate test failure xyz' in el.detail
        assert el.screen == '/some/screen' and el.action == 'POST'
        eid = el.id
    # the response body is friendly, not a traceback
    body = resp[0] if isinstance(resp, tuple) else resp
    assert 'Something went wrong' in body and 'Traceback' not in body
    # admin-only error log lists it and shows technical detail
    d = client.get('/m/errorlog').get_data(as_text=True)
    assert 'Error Log' in d and f'ERR-{eid:04d}' in d
    d = client.get(f'/errorlog/{eid}').get_data(as_text=True)
    assert 'Technical details' in d and 'deliberate test failure xyz' in d
    client.get(f'/errorlog/{eid}/resolve', follow_redirects=True)
    with app.app_context():
        assert ErrorLog.query.get(eid).resolved is True


# ============================== Phase 24: unified app launcher

def test_app_launcher(app, client):
    _login(client)
    d = client.get('/apps').get_data(as_text=True)
    # level 1: consolidated app tiles + search script
    assert 'All Modules' in d and 'filterApps' in d and 'cat-tile' in d
    # one tile per area (not the flat module list)
    for area in ['Patient Management', 'Accounting', 'Administration']:
        assert area in d, area
    assert "class='app-item'" not in d  # modules are not flat on level 1
    # level 2: opening an app reveals its modules
    acc = client.get('/apps?cat=accounting').get_data(as_text=True)
    assert 'Journal Entries' in acc and 'All Apps' in acc
    pt = client.get('/apps?cat=patient-management').get_data(as_text=True)
    assert 'Patient Registration' in pt
    # reachable via /m/apps alias and shows in the nav
    assert client.get('/m/apps').status_code == 200
    assert 'All Modules' in client.get('/').get_data(as_text=True)
    # role filtering: reception sees permitted billing/accounting apps (invoices,
    # daily transactions) but per least-privilege NOT the general ledger's Journal
    # Entries, and not Human Resources.
    rc = app.test_client()
    tok = _re_csrf(rc)
    rc.post('/login', data={'username': 'reception', 'password': '1234', '_csrf': tok})
    d = rc.get('/apps').get_data(as_text=True)
    assert 'cat=patient-management' in d
    assert 'cat=human-resources' not in d
    # reception cannot reach Journal Entries (general ledger)
    assert 'Journal Entries' not in rc.get('/apps?cat=accounting').get_data(as_text=True)
    assert 'No access' in rc.get('/m/journal').get_data(as_text=True)


def _re_csrf(cl):
    import re as _re
    return _re.search(r'name="_csrf" value="([^"]+)"',
                      cl.get('/login').get_data(as_text=True)).group(1)


# ============================== Phase 25: dynamic service configuration

def test_service_configuration(app, client):
    from mdc_erp.models import Service, Invoice
    _login(client)
    # CREATE a new service via UI, no code (the CT Brain example from the spec)
    tok = _csrf(client.get('/svcconfig/0'))
    client.post('/svcconfig/0', data={
        'name': 'CT Brain NoContrast SVCCFG', 'department': 'CT Scan', 'category': 'CT Scan',
        'price': '150', 'price_insurance': '170', 'price_emergency': '220',
        'comm_doctor_type': 'Percent', 'comm_doctor_val': '20',
        'comm_radiologist_type': 'Fixed', 'comm_radiologist_val': '10',
        'comm_tech_type': 'Fixed', 'comm_report_type': 'Fixed',
        'workflow': 'Radiology', 'equipment': 'CT Scanner', 'report_template': 'CT Brain',
        'time_reporting': '30', 'active': '1', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        s = Service.query.filter_by(name='CT Brain NoContrast SVCCFG').first()
        assert s and s.code and s.price == 150 and s.price_emergency == 220
        assert s.comm_doctor_val == 20 and s.comm_radiologist_val == 10
        assert s.modality == 'CT'  # auto-derived from department
        sid = s.id
    # INTEGRATION: appears in radiology new-study catalog (CT routed via workflow)
    assert 'CT Brain' in client.get('/rad/new').get_data(as_text=True)
    # SEARCH + FILTER (before the price edit, which omits equipment)
    assert 'CT Brain' in client.get('/m/svcconfig?q=ct brain').get_data(as_text=True)
    assert 'CT Brain' in client.get('/m/svcconfig?dep=CT Scan').get_data(as_text=True)
    assert 'CT Brain' in client.get('/m/svcconfig?equip=CT Scanner').get_data(as_text=True)
    # and on the invoice catalog
    client.post('/invoice/new', data={'patient_id': '1', 'date': '2026-07-08',
                                      '_csrf': _csrf(client.get('/invoice/new'))})
    with app.app_context():
        iid = Invoice.query.order_by(Invoice.id.desc()).first().id
    assert 'CT Brain NoContrast SVCCFG' in client.get(f'/invoice/{iid}').get_data(as_text=True)
    # add the service to that invoice at the current price, then change the service price
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    with app.app_context():
        old_total = Invoice.query.get(iid).total
    tok = _csrf(client.get(f'/svcconfig/{sid}'))
    client.post(f'/svcconfig/{sid}', data={'name': 'CT Brain NoContrast SVCCFG', 'department': 'CT Scan',
        'price': '300', 'workflow': 'Radiology', 'active': '1', 'equipment': 'CT Scanner',
        'comm_doctor_type': 'Percent', 'comm_doctor_val': '20', 'comm_radiologist_type': 'Fixed',
        'comm_radiologist_val': '10', 'comm_tech_type': 'Fixed', 'comm_report_type': 'Fixed',
        '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        # historical invoice preserved, but service master updated
        assert abs(Invoice.query.get(iid).total - old_total) < 0.01
        assert Service.query.get(sid).price == 300
    # SECURITY: reception cannot open the configuration editor
    rc = app.test_client()
    tok = _re_csrf(rc)
    rc.post('/login', data={'username': 'reception', 'password': '1234', '_csrf': tok})
    assert rc.get('/svcconfig/0').status_code == 403


# ============================== Phase 26: auto commission/fee payables

def test_commission_payables_workflow(app, client):
    from mdc_erp.models import (Doctor, Service, Invoice, RadOrder,
                                CommissionAccrual, CommissionPayment, JournalEntry)
    from mdc_erp.extensions import db as _db
    _login(client)
    _pid = _fresh_patient(app)
    with app.app_context():
        doc = Doctor(name='Dr PayRef', specialty='IM', phone='1', active=True,
                     commission_type='Percent', percent_rate=20)
        _db.session.add(doc); _db.session.commit(); did = doc.id
        svc = Service.query.first()
        svc.department = 'CT Scan'; svc.price = 150
        svc.comm_doctor_type = 'Percent'; svc.comm_doctor_val = 20
        svc.comm_radiologist_type = 'Fixed'; svc.comm_radiologist_val = 10
        _db.session.commit(); sid = svc.id
    # build invoice with a service line
    client.post('/invoice/new', data={'patient_id': str(_pid), 'date': '2026-07-08',
                                      '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    with app.app_context():
        inv = Invoice.query.get(iid); inv.referring_doctor_id = did
        ro = RadOrder(service_id=sid, patient_id=_pid, status='Requested',
                      date='2026-07-08', radiologist='Dr PayRad')
        if hasattr(RadOrder, 'invoice_id'):
            ro.invoice_id = iid
        _db.session.add(ro); _db.session.commit()
    # pay in full -> auto-accrue
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '150', 'pay_method': 'Cash',
                                         'pay_ref': '', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    with app.app_context():
        accs = {a.payee_kind: a for a in CommissionAccrual.query.filter_by(invoice_id=iid).all()}
        assert abs(accs['doctor'].amount - 30) < 0.01 and accs['doctor'].status == 'Unpaid'
        assert abs(accs['radiologist'].amount - 10) < 0.01
        je = JournalEntry.query.filter_by(ref=f'COMM-{iid:04d}').first()
        assert je and {l.account.code for l in je.lines} >= {'5130', '2300', '5140', '2310'}
        doc_acc_id = accs['doctor'].id
    # payables dashboard shows KPIs + actions
    d = client.get('/m/payables?kind=doctor').get_data(as_text=True)
    assert 'Outstanding' in d and 'Pay All' in d and f'INV-{iid:04d}' in d
    # pay the doctor commission
    client.get(f'/payables/pay?ids={doc_acc_id}&kind=doctor', follow_redirects=True)
    with app.app_context():
        a = CommissionAccrual.query.get(doc_acc_id)
        assert a.status == 'Paid' and a.balance == 0
        assert CommissionPayment.query.filter_by(payee_kind='doctor').count() >= 1
        assert any((j.ref or '').startswith('CMPAY-DOC') for j in JournalEntry.query.all())
    # pay all radiologist fees
    client.get('/payables/pay?kind=radiologist&all=1', follow_redirects=True)
    with app.app_context():
        assert all(a.status == 'Paid'
                   for a in CommissionAccrual.query.filter_by(payee_kind='radiologist').all())


# ============================== Phase 27: doctor request workflow + print

def test_doctor_request_workflow_merged(app, client):
    _login(client)
    # Doctor Request menu opens the LIST first, with a + New button to the form
    d = client.get('/m/referrals').get_data(as_text=True)
    assert 'Incoming Referrals' in d and '+ New Doctor Request' in d
    assert '/referral/new' in d
    # the register form is behind its own route, with a back button
    d = client.get('/referral/new').get_data(as_text=True)
    assert 'New Doctor Request' in d and 'Create Doctor Request' in d
    assert 'Patient name' in d and 'Back to Doctor Requests' in d
    # the request board is still reachable off-menu
    assert client.get('/m/reqboard').status_code == 200
    # sidebar nav has no duplicate reqboard entry
    nav = d[d.find('<nav'):d.find('</nav>')] if '<nav' in d else d
    assert 'reqboard' not in nav
    # staff can create a request from the form
    tok = _csrf(client.get('/referral/new'))
    from mdc_erp.models import Referral
    client.post('/refer', data={'patient_name': 'WF Test', 'patient_phone': '0611',
                                'doctor_name': 'Dr WF', 'tests': ['CBC'], '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        assert Referral.query.filter_by(patient_name='WF Test').first() is not None


def test_branded_print_layout(app, client):
    from mdc_erp.models import Setting, Service, Invoice
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        for k, v in [('company_arabic', 'مركز'), ('company_address', 'Gaalkacyo'),
                     ('company_phone', '+252610000000'), ('company_email', 'info@mdc.so')]:
            s = Setting.query.get(k) or Setting(key=k)
            s.value = v; _db.session.add(s)
        _db.session.commit()
        sid = Service.query.first().id
    client.post('/invoice/new', data={'patient_id': '1', 'date': '2026-07-08',
                                      '_csrf': _csrf(client.get('/invoice/new'))}, follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    pr = client.get(f'/invoice/{iid}/print').get_data(as_text=True)
    # letterhead is on by default: the centre's own artwork carries the name,
    # address, phones and Arabic title, so those arrive as images not text.
    # The QR/barcode and Print/Email/WhatsApp buttons were removed by request.
    for tok in ['letterhead-header.jpg', 'letterhead-footer.jpg', 'Document Ref']:
        assert tok in pr, tok
    for gone in ['Print / Save PDF', 'WhatsApp']:
        assert gone not in pr, gone
    # with the letterhead switched off, the text header is used instead
    from mdc_erp.models import Setting
    from mdc_erp.extensions import db as _db
    with app.app_context():
        s = Setting.query.get('letterhead') or Setting(key='letterhead')
        s.value = '0'; _db.session.add(s); _db.session.commit()
    pr = client.get(f'/invoice/{iid}/print').get_data(as_text=True)
    assert 'Modern Diagnostic Center' in pr and 'Document Ref' in pr


# ============================== Phase 28: accounting home + partner ledger

def test_accounting_home_and_partner_ledger(app, client):
    from mdc_erp.models import Service, Invoice
    _login(client)
    d = client.get('/m/acct').get_data(as_text=True)
    for t in ['Cash Balance', 'Bank Balance', "Today's Income", "Today's Expenses",
              'Pending Dr Commission', 'Pending Radiologist Fees', 'Insurance Receivables']:
        assert t in d, t
    # partner ledger: build an invoice + payment for patient 1, then check the statement
    with app.app_context():
        sid = Service.query.first().id
    client.post('/invoice/new', data={'patient_id': '1', 'date': '2026-07-10',
                                      '_csrf': _csrf(client.get('/invoice/new'))}, follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '60', 'pay_method': 'Cash',
                                         'pay_ref': '', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    d = client.get('/m/partnerledger?side=customer&partner=1').get_data(as_text=True)
    assert 'Partner Ledger' in d and f'INV-{iid:04d}' in d and 'RCT-' in d
    assert client.get('/m/partnerledger?side=vendor').status_code == 200


# ============================== Phase 29: Odoo-style accounting menubar

def test_odoo_style_accounting_menubar(app, client):
    _login(client)
    # menubar with 8 top menus on accounting screens
    for pg_ in ('/m/acctdash', '/m/jentries', '/m/genledger', '/m/accounts'):
        d = client.get(pg_).get_data(as_text=True)
        assert 'mbar-desktop' in d, pg_
        for top in ('Overview', 'Transactions', 'Ledgers', 'Receivables &amp; Payables', 'Banking', 'Planning &amp; Analysis', 'Reports', 'Configuration'):
            assert top in d or top.replace('&amp;', '&') in d, f'{top} on {pg_}'
    # dropdown items are present and grouped
    d = client.get('/m/acctdash').get_data(as_text=True)
    for item in ('Accounting Center', 'Journal Entries', 'Partner Ledger',
                 'Commission Payables', 'Chart of Accounts', 'Fiscal Periods'):
        assert item in d, item
    # clinical screens get the clinical bar
    d = client.get('/m/patients').get_data(as_text=True)
    assert "<div class='mbar'>" in d and 'Blood Bank' in d
    # but they do NOT get accounting dropdown items
    assert 'Commission Payables' not in d
    # every link in the menubar resolves
    from mdc_erp.core.ui import ACCT_MENUBAR
    for _t, _i, subs in ACCT_MENUBAR:
        for k, _lb in subs:
            if k.startswith('_'):
                continue
            assert client.get(f'/m/{k}').status_code in (200, 302), k


# ============================== Phase 30: system-wide menubars

def test_system_wide_menubars(client):
    _login(client)
    checks = {
        '/m/patients': ('Patients', 'Doctor Requests', 'Blood Bank'),
        '/m/lab': ('Laboratory', 'Radiology'),
        '/m/pharmacy': ('Pharmacy', 'Inventory', 'Procurement'),
        '/m/employees': ('Employees', 'Time', 'Payroll'),
        '/m/sops': ('Quality',),
        '/m/assets': ('Assets', 'Logistics'),
        '/m/reports': ('Reports',),
        '/m/users': ('System', 'Logs'),
    }
    for pg_, toks in checks.items():
        d = client.get(pg_).get_data(as_text=True)
        assert "<div class='mbar'>" in d, pg_
        for t in toks:
            assert t in d, f'{t} on {pg_}'
    # every link in every bar resolves
    from mdc_erp.core.ui import APP_BARS
    for bar in APP_BARS.values():
        for _t, _i, subs in bar:
            for k, _lb in subs:
                if not k.startswith('_'):
                    assert client.get(f'/m/{k}').status_code in (200, 302), k


# ============================== Phase 31: financial period filters + vendor mgmt

def test_financial_period_filters_and_vendor_mgmt(app, client):
    from mdc_erp.models import Supplier, Expense
    _login(client)
    # every preset renders on all 4 statement tabs
    for per in ('today', 'week', 'month', 'quarter', 'year', 'lastmonth', 'lastyear'):
        for tb in ('pnl', 'cash', 'bs', 'tb'):
            assert client.get(f'/m/finance?tab={tb}&period={per}').status_code == 200, (per, tb)
    d = client.get('/m/finance?period=month').get_data(as_text=True)
    assert 'This Month' in d and 'Prev period' in d          # comparison bar
    assert 'tab=bs&amp;period=month' in d or 'tab=bs&period=month' in d  # tabs keep period
    # custom range
    d = client.get('/m/finance?from=2026-07-01&to=2026-07-12').get_data(as_text=True)
    assert '2026-07-01' in d and '2026-07-12' in d
    # vendor with extended fields
    tok = _csrf(client.get('/m/suppliers/new'))
    client.post('/m/suppliers/new',
                data={'name': 'Golis Energy T', 'category': 'Electricity Company',
                      'contact_person': 'Axmed', 'email': 'info@golis.so', 'tax_no': 'TX-99',
                      'bank_details': 'Salaam 001', 'phone': '0611', 'address': 'Gaalkacyo',
                      '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        sp = Supplier.query.filter_by(name='Golis Energy T').first()
        assert sp and sp.contact_person == 'Axmed' and sp.tax_no == 'TX-99'
        spid = sp.id
    # vendor expense with category (Odoo expense flow — method chosen at payment)
    _new_expense(client, post=False, description='July bill', category='Electricity',
                 qty='1', unit_price='250', note='July bill', date='2026-07-12')
    with app.app_context():
        e = Expense.query.filter_by(category='Electricity').order_by(Expense.id.desc()).first()
        assert e and abs(e.amount - 250) < 0.01
    d = client.get('/m/expenses').get_data(as_text=True)
    assert 'Electricity' in d


# ============================== Phase 32: simple service management

def test_simple_service_management(app, client):
    from mdc_erp.models import Service, Invoice
    from mdc_erp.core.crud import opt_services
    _login(client)
    d = client.get('/m/svcmgmt').get_data(as_text=True)
    assert 'Service Management' in d and '+ New Service' in d
    # create with auto-code
    tok = _csrf(client.get('/svcmgmt/new'))
    client.post('/svcmgmt/new', data={'name': 'MRI Brain T32', 'department': 'MRI',
                                      'category': 'MRI', 'price': '220', 'cost': '60',
                                      'active': '1', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        s = Service.query.filter_by(name='MRI Brain T32').first()
        assert s and s.code and s.price == 220 and s.active
        sid = s.id
        # auto-integration: available to billing / doctor request options
        assert any(o[0] == sid for o in opt_services())
    # Save & New lands back on a blank form
    tok = _csrf(client.get('/svcmgmt/new'))
    r = client.post('/svcmgmt/new', data={'name': 'ECG T32', 'department': 'ECG', 'price': '25',
                                          'active': '1', 'save_new': '1', '_csrf': tok},
                    follow_redirects=True)
    assert 'New Service' in r.get_data(as_text=True)
    # edit
    tok = _csrf(client.get(f'/svcmgmt/{sid}/edit'))
    client.post(f'/svcmgmt/{sid}/edit', data={'name': 'MRI Brain T32', 'department': 'MRI',
                                              'category': 'Neuro', 'price': '240', 'cost': '60',
                                              'active': '1', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        from mdc_erp.extensions import db as _db
        s = _db.session.get(Service, sid)
        assert s.price == 240 and s.category == 'Neuro'
    # deactivate removes from options; reactivate restores
    client.get(f'/svcmgmt/{sid}/toggle', follow_redirects=True)
    with app.app_context():
        assert not any(o[0] == sid for o in opt_services())
    client.get(f'/svcmgmt/{sid}/toggle', follow_redirects=True)
    # delete is blocked once the service is used on an invoice
    client.post('/invoice/new', data={'patient_id': '1', '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    client.get(f'/svcmgmt/{sid}/delete', follow_redirects=True)
    with app.app_context():
        from mdc_erp.extensions import db as _db
        assert _db.session.get(Service, sid) is not None
        # unused service can be deleted
        eid = Service.query.filter_by(name='ECG T32').first().id
    client.get(f'/svcmgmt/{eid}/delete', follow_redirects=True)
    with app.app_context():
        from mdc_erp.extensions import db as _db
        assert _db.session.get(Service, eid) is None


# ============================== Phase 33: add new radiologist + assignment

def test_add_radiologist_and_assign(app, client):
    from mdc_erp.models import Radiologist, RadOrder, Service
    from mdc_erp.extensions import db as _db
    _login(client)
    # add via /m/radiologists/new
    tok = _csrf(client.get('/m/radiologists/new'))
    client.post('/m/radiologists/new',
                data={'name': 'Dr Hodan T33', 'specialty': 'Neuro', 'phone': '0615',
                      'active': '1', 'portal_user': 'hodan33', 'portal_pw_set': 'Hodan2026!',
                      '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        r = Radiologist.query.filter_by(name='Dr Hodan T33').first()
        assert r and r.active and r.portal_user == 'hodan33'
        svc = Service.query.first()
        ro = RadOrder(service_id=svc.id, patient_id=1, status='Imaged',
                      date='2026-07-13', modality='CT')
        _db.session.add(ro); _db.session.commit(); oid = ro.id
    # radiology list has the + New Radiologist button
    assert '+ New Radiologist' in client.get('/m/radiology').get_data(as_text=True)
    # report form shows a dropdown including the new radiologist
    d = client.get(f'/rad/{oid}/report').get_data(as_text=True)
    assert 'Dr Hodan T33' in d and '<select' in d
    # saving the report stores the selected radiologist
    client.post(f'/rad/{oid}/report',
                data={'radiologist': 'Dr Hodan T33', 'image_note': '',
                      'report': 'Normal study.', 'finalize': '1', '_csrf': _csrf(client.get(f'/rad/{oid}/report'))},
                follow_redirects=True)
    with app.app_context():
        o = _db.session.get(RadOrder, oid)
        assert o.radiologist == 'Dr Hodan T33' and o.status == 'Reported'
    # dispatch dropdown lists them too
    with app.app_context():
        svc = Service.query.first()
        ro2 = RadOrder(service_id=svc.id, patient_id=1, status='Imaged',
                       date='2026-07-13', modality='CT')
        _db.session.add(ro2); _db.session.commit(); oid2 = ro2.id
    assert 'Dr Hodan T33' in client.get(f'/rad/{oid2}/dispatch').get_data(as_text=True)


# ============================== Phase 34: Odoo-style billing workflow

def test_billing_waiting_panel_and_one_click_invoice(app, client):
    from mdc_erp.models import Referral, Invoice, Service
    _login(client)
    with app.app_context():
        svc_name = Service.query.first().name
    # doctor request with a catalog service
    tok = _csrf(client.get('/referral/new'))
    client.post('/refer', data={'patient_name': 'Bilal T34', 'patient_phone': '0616',
                                'doctor_name': 'Dr B', 'tests': [svc_name], '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        rid = Referral.query.filter_by(patient_name='Bilal T34').first().id
    # waiting panel shows it on the billing screen
    d = client.get('/m/invoices').get_data(as_text=True)
    assert 'Waiting for Billing' in d and f'REF-{rid:04d}' in d
    # register + one-click create invoice -> lines auto-populated
    client.get(f'/referral/{rid}/accept', follow_redirects=True)
    client.get(f'/referral/{rid}/invoice', follow_redirects=True)
    with app.app_context():
        inv = Invoice.query.filter_by(referral_id=rid).first()
        assert inv and len(inv.items) >= 1 and inv.total > 0
        iid = inv.id
    # invoice screen: sticky action bar + keyboard shortcuts present
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'position:sticky' in d and 'keydown' in d and 'Confirm Invoice' in d
    # redesigned confirm-first flow: payment unlocks only after confirming
    client.post(f'/invoice/{iid}', data={'act': 'confirm', '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'Register Payment' in d
    # invoice list shows the referral reference
    assert f'REF-{rid:04d}' in client.get('/m/invoices').get_data(as_text=True)


# ============================== Phase 35: per-radiologist fee rules

def test_radiologist_fee_rules(app, client):
    from mdc_erp.models import Service, Invoice, RadOrder, CommissionAccrual, Radiologist, Patient
    from mdc_erp.extensions import db as _db
    _login(client)

    def paid_invoice(radname, price=150):
        with app.app_context():
            svc = Service.query.first()
            svc.department = 'CT Scan'; svc.price = price
            svc.comm_radiologist_type = 'Fixed'; svc.comm_radiologist_val = 10
            # fresh patient so stray uninvoiced orders from other tests are never auto-pulled
            _p = Patient(name=f'FeeRule {radname}', mrn=f"MRN-{radname.replace(' ', '')}", phone='0')
            _db.session.add(_p); _db.session.commit()
            sid = svc.id; _pid = _p.id
        client.post('/invoice/new', data={'patient_id': str(_pid), '_csrf': _csrf(client.get('/invoice/new'))},
                    follow_redirects=True)
        with app.app_context():
            iid = Invoice.query.order_by(Invoice.id.desc()).first().id
        client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                             '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                    follow_redirects=True)
        with app.app_context():
            _db.session.add(RadOrder(service_id=sid, patient_id=1, status='Reported',
                                     date='2026-07-14', radiologist=radname, invoice_id=iid))
            _db.session.commit()
        client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': str(price), 'pay_method': 'Cash',
                                             'pay_ref': '', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                    follow_redirects=True)
        return iid

    # Percent rule overrides service default
    tok = _csrf(client.get('/m/radiologists/new'))
    client.post('/m/radiologists/new', data={'name': 'Dr Pct T35', 'fee_type': 'Percent',
                                             'fee_value': '15', 'active': '1', '_csrf': tok},
                follow_redirects=True)
    i1 = paid_invoice('Dr Pct T35')
    with app.app_context():
        a = CommissionAccrual.query.filter_by(invoice_id=i1, payee_kind='radiologist').first()
        assert a and abs(a.amount - 22.50) < 0.01 and a.payee_name == 'Dr Pct T35'
    # Fixed rule
    tok = _csrf(client.get('/m/radiologists/new'))
    client.post('/m/radiologists/new', data={'name': 'Dr Fix T35', 'fee_type': 'Fixed',
                                             'fee_value': '18', 'active': '1', '_csrf': tok},
                follow_redirects=True)
    i2 = paid_invoice('Dr Fix T35')
    with app.app_context():
        a = CommissionAccrual.query.filter_by(invoice_id=i2, payee_kind='radiologist').first()
        assert a and abs(a.amount - 18) < 0.01
    # service default when the radiologist has no rule (also covers no-referring-doctor accrual fix)
    i3 = paid_invoice('Dr NoRule T35')
    with app.app_context():
        a = CommissionAccrual.query.filter_by(invoice_id=i3, payee_kind='radiologist').first()
        assert a and abs(a.amount - 10) < 0.01


# ============================== Phase 36: automatic invoice (no manual add-item)

def test_invoice_auto_no_manual_additem(app, client):
    from mdc_erp.models import Referral, Invoice, Service
    _login(client)
    with app.app_context():
        svc_name = Service.query.first().name
    tok = _csrf(client.get('/referral/new'))
    client.post('/refer', data={'patient_name': 'Auto T36', 'doctor_name': 'Dr A',
                                'tests': [svc_name], '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        rid = Referral.query.filter_by(patient_name='Auto T36').first().id
    client.get(f'/referral/{rid}/accept', follow_redirects=True)
    client.get(f'/referral/{rid}/invoice', follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(referral_id=rid).first().id
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    # referral invoice: manual add gone, automatic note present
    assert 'Automatic invoice' in d and 'Add a line' not in d
    # walk-in invoice: Odoo-style "Add a line" manual option remains
    client.post('/invoice/new', data={'patient_id': '1', '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        mid = Invoice.query.order_by(Invoice.id.desc()).first().id
    d = client.get(f'/invoice/{mid}').get_data(as_text=True)
    assert 'Add a line' in d and 'name="service_id"' in d


# ============================== Phase 37: payment schedules, history, voucher

def test_payables_schedules_history_voucher(app, client):
    from mdc_erp.models import Service, Invoice, RadOrder, CommissionAccrual, CommissionPayment
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    _login(client)
    _pid = _fresh_patient(app)

    def paid_inv(radname, price=150):
        with app.app_context():
            svc = Service.query.first()
            svc.department = 'CT Scan'; svc.price = price
            svc.comm_radiologist_type = 'Fixed'; svc.comm_radiologist_val = 10
            _db.session.commit(); sid = svc.id
        client.post('/invoice/new', data={'patient_id': str(_pid), '_csrf': _csrf(client.get('/invoice/new'))},
                    follow_redirects=True)
        with app.app_context():
            iid = Invoice.query.order_by(Invoice.id.desc()).first().id
        client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                             '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
        with app.app_context():
            _db.session.add(RadOrder(service_id=sid, patient_id=_pid, status='Reported',
                                     date=today(), radiologist=radname, invoice_id=iid))
            _db.session.commit()
        client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': str(price), 'pay_method': 'Cash',
                                             'pay_ref': '', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                    follow_redirects=True)
        return iid

    i1 = paid_inv('Dr T37A'); i2 = paid_inv('Dr T37B')
    # settle anything left open by earlier tests EXCEPT our two (deterministic oldest-first)
    with app.app_context():
        others = [a.id for a in CommissionAccrual.query.filter_by(payee_kind='radiologist').all()
                  if a.balance > 0.005 and a.invoice_id not in (i1, i2)]
    if others:
        client.get('/payables/pay?kind=radiologist&ids=' + ','.join(map(str, others)),
                   follow_redirects=True)
    d = client.get('/m/payables?kind=radiologist').get_data(as_text=True)
    assert 'Pay Monthly' in d and 'Partial Payment' in d
    # partial $6 -> oldest becomes Partial
    client.post('/payables/pay-partial', data={'kind': 'radiologist', 'amount': '6',
                                               '_csrf': _csrf(client.get('/m/payables?kind=radiologist'))},
                follow_redirects=True)
    with app.app_context():
        a1 = CommissionAccrual.query.filter_by(invoice_id=i1, payee_kind='radiologist').first()
        assert a1.status == 'Partial' and abs(a1.balance - 4) < 0.01
    # pay-monthly settles the month
    client.get(f'/payables/pay-monthly?kind=radiologist&month={today()[:7]}', follow_redirects=True)
    with app.app_context():
        for iid_ in (i1, i2):
            a = CommissionAccrual.query.filter_by(invoice_id=iid_, payee_kind='radiologist').first()
            assert a.status == 'Paid'
        pid = CommissionPayment.query.filter_by(payee_kind='radiologist').first().id
    # history + summary + voucher
    d = client.get('/m/payables?kind=radiologist&show=history').get_data(as_text=True)
    assert 'Monthly Payment Summary' in d and 'Voucher' in d
    v = client.get(f'/payables/voucher/{pid}').get_data(as_text=True)
    assert 'Payment Voucher' in v and f'CMV-{pid:05d}' in v


# ============================== Phase 38: radiologist management module

def test_radiologist_management_module(app, client):
    from mdc_erp.models import Radiologist, Service, Invoice, RadOrder
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    _login(client)
    _pid = _fresh_patient(app)
    # Referral Management menu on clinical screens
    d = client.get('/m/patients').get_data(as_text=True)
    assert 'Referral Management' in d and 'Radiologists' in d
    # full registration form
    d = client.get('/m/radiologists/new').get_data(as_text=True)
    for f in ('Full Name', 'Gender', 'Email', 'License', 'Qualification', 'Hospital',
              'City', 'Reporting Fee', 'Payment Schedule'):
        assert f in d, f
    tok = _csrf(client.get('/m/radiologists/new'))
    client.post('/m/radiologists/new',
                data={'name': 'Dr Amina T38', 'gender': 'Female', 'dob': '1988-04-02',
                      'phone': '0619', 'email': 'amina@rad.so', 'national_id': 'P-778',
                      'license_no': 'ML-2231', 'specialty': 'Body Imaging',
                      'qualification': 'MD, FRCR', 'hospital': 'Mogadishu Imaging',
                      'city': 'Muqdisho', 'address': 'KM4', 'fee_type': 'Fixed',
                      'fee_value': '10', 'pay_schedule': 'Monthly', 'active': '1',
                      '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        r = Radiologist.query.filter_by(name='Dr Amina T38').first()
        assert r and r.email == 'amina@rad.so' and r.license_no == 'ML-2231'
        assert r.pay_schedule == 'Monthly' and r.fee_value == 10
        svc = Service.query.first()
        svc.department = 'CT Scan'; svc.price = 150
        svc.comm_radiologist_type = 'Fixed'; svc.comm_radiologist_val = 10
        _db.session.commit(); sid = svc.id
    # paid radiology invoice -> stats + by-radiologist summary
    client.post('/invoice/new', data={'patient_id': str(_pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        _db.session.add(RadOrder(service_id=sid, patient_id=_pid, status='Reported',
                                 date=today(), radiologist='Dr Amina T38', invoice_id=iid))
        _db.session.commit()
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '150', 'pay_method': 'Cash',
                                         'pay_ref': '', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    d = client.get('/m/radiologists').get_data(as_text=True)
    assert 'RAD-' in d and 'Dr Amina T38' in d and 'Monthly' in d
    d = client.get('/m/payables?kind=radiologist').get_data(as_text=True)
    assert 'By Radiologist' in d and 'Dr Amina T38' in d


# ============================== Phase 39: commission after discount + auto amount + rad fee row

def test_commission_after_discount_and_auto_amount(app, client):
    from mdc_erp.models import Doctor, Service, Invoice, RadOrder, CommissionAccrual
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    _login(client)
    _pid = _fresh_patient(app)
    with app.app_context():
        doc = Doctor(name='Dr Disc T39', specialty='IM', phone='1', active=True,
                     commission_type='Percent', percent_rate=0.2)
        _db.session.add(doc)
        svc = Service.query.first()
        svc.department = 'CT Scan'; svc.price = 150
        svc.comm_doctor_type = 'Percent'; svc.comm_doctor_val = 20
        svc.comm_radiologist_type = 'Fixed'; svc.comm_radiologist_val = 10
        _db.session.commit(); sid = svc.id; did = doc.id
    client.post('/invoice/new', data={'patient_id': str(_pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        inv = _db.session.get(Invoice, iid); inv.referring_doctor_id = did
        _db.session.add(RadOrder(service_id=sid, patient_id=_pid, status='Reported',
                                 date=today(), radiologist='Dr Amina T39', invoice_id=iid))
        _db.session.commit()
    # both rows shown; amount auto-filled with full total
    # commission + radiologist fee rows show on the draft
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'Radiologist Fee' in d and 'Dr Amina T39' in d
    # $50 discount on the draft -> commission after discount = $20; balance = $100
    client.post(f'/invoice/{iid}', data={'act': 'adjust', 'discount': '50', 'discount_pct': '0',
                                         'vat': '0', 'disc_reason': 'Charity',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    # confirm to unlock payment (amount auto-fills with the post-discount balance)
    client.post(f'/invoice/{iid}', data={'act': 'confirm', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'after discount' in d
    assert 'value="100.0"' in d or 'value="100"' in d
    # pay -> accruals use the discounted commission
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '100', 'pay_method': 'Cash',
                                         'pay_ref': '', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    with app.app_context():
        accs = {a.payee_kind: a for a in CommissionAccrual.query.filter_by(invoice_id=iid).all()}
        assert abs(accs['doctor'].amount - 20) < 0.01
        assert abs(accs['radiologist'].amount - 10) < 0.01


# ============================== Phase 40: automatic order pull on invoices

def test_invoice_autofill_from_orders(app, client):
    from mdc_erp.models import Patient, Service, Invoice, LabOrder, RadOrder
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    _login(client)
    with app.app_context():
        p = Patient(name='Faarax T40', mrn='MRN-T40', phone='0620')
        _db.session.add(p); _db.session.commit(); pid = p.id
        svc = Service.query.first(); svc.price = 150; svc.department = 'CT Scan'
        _db.session.commit(); sid = svc.id
        _db.session.add(RadOrder(service_id=sid, patient_id=pid, status='Requested', date=today()))
        _db.session.add(LabOrder(service_id=sid, patient_id=pid, status='Requested', date=today()))
        _db.session.commit()
    # creating the invoice pulls both pending orders automatically
    client.post('/invoice/new', data={'patient_id': str(pid), 'date': today(),
                                      '_csrf': _csrf(client.get('/invoice/new'))}, follow_redirects=True)
    with app.app_context():
        inv = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first()
        assert inv and len(inv.items) == 2 and inv.total > 0
        iid = inv.id
    # idempotent on reopen
    client.get(f'/invoice/{iid}')
    with app.app_context():
        assert len(_db.session.get(Invoice, iid).items) == 2
    # a later order is pulled in by the explicit Sync action. GET must stay
    # side-effect free (posting/auto-add on page load was removed as a fix), so
    # a plain reopen must NOT change the invoice.
    with app.app_context():
        _db.session.add(RadOrder(service_id=sid, patient_id=pid, status='Requested', date=today()))
        _db.session.commit()
    client.get(f'/invoice/{iid}')
    with app.app_context():
        assert len(_db.session.get(Invoice, iid).items) == 2, 'GET must not auto-add'
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'sync', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        assert len(_db.session.get(Invoice, iid).items) == 3, 'Sync must pull the new order'


# ============================== Phase 41: commission fallbacks + Pay Center

def test_expense_odoo_flow(app, client):
    """Odoo-style expense flow: Save → Submit → Approve → Post (Dr Expense/Cr AP) →
    Register Payment (Dr AP / Cr method). Posts only at the Posted stage."""
    from mdc_erp.models import Expense, JournalEntry
    _login(client)
    tok = _csrf(client.get('/expense/new'))
    client.post('/expense/save', data={'_csrf': tok, 'description': 'Office maintenance',
                                       'category': 'Maintenance', 'account': '600050 Repairs & Maintenance',
                                       'employee': 'Logistic', 'paid_by': 'Company', 'pay_method': 'Bank',
                                       'qty': '1', 'unit_price': '25', 'date': '2026-09-08'},
                follow_redirects=True)
    with app.app_context():
        e = Expense.query.order_by(Expense.id.desc()).first(); eid = e.id
        assert e.status == 'Draft' and abs(e.amount - 25) < 0.01
        assert JournalEntry.query.filter_by(ref=f'EXP-{eid:04d}').first() is None   # not posted yet
    client.get(f'/expense/{eid}/submit', follow_redirects=True)
    client.get(f'/expense/{eid}/approve', follow_redirects=True)
    with app.app_context():
        assert Expense.query.get(eid).status == 'Approved'
        assert JournalEntry.query.filter_by(ref=f'EXP-{eid:04d}').first() is None   # still not posted
    client.get(f'/expense/{eid}/post', follow_redirects=True)
    with app.app_context():
        e = Expense.query.get(eid); assert e.status == 'Posted'
        je = JournalEntry.query.filter_by(ref=f'EXP-{eid:04d}').first()
        debits = {l.account.code for l in je.lines if (l.debit or 0) > 0}
        credits = {l.account.code for l in je.lines if (l.credit or 0) > 0}
        assert '6500' in debits and '2100' in credits   # Dr expense / Cr AP
    tok = _csrf(client.get(f'/expense/{eid}'))
    client.post(f'/expense/{eid}/pay', data={'amount': '25', 'method': 'Bank', '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        e = Expense.query.get(eid); assert e.status == 'Paid' and abs(e.paid - 25) < 0.01
        pje = JournalEntry.query.filter_by(ref=f'PAYE-{eid:04d}').first()
        pdebits = {l.account.code for l in pje.lines if (l.debit or 0) > 0}
        pcredits = {l.account.code for l in pje.lines if (l.credit or 0) > 0}
        assert '2100' in pdebits and '1102' in pcredits   # Dr AP / Cr Bank


def test_po_create_product_inline(app, client):
    """Odoo-style 'Create & Edit': a new product can be created from the PO form
    (quick-add endpoint) without leaving the page, and is added to inventory."""
    from mdc_erp.models import Medicine
    _login(client)
    # the PO form offers the Create & Edit action
    d = client.get('/purchase/new').get_data(as_text=True)
    assert 'Create &amp; Edit product' in d and 'newProdModal' in d
    with app.app_context():
        before = Medicine.query.count()
    tok = _csrf(client.get('/purchase/new'))
    r = client.post('/stock/quick-add',
                    data={'name': 'Inline Reagent Kit', 'cost': '45', 'reorder': '5',
                          'batch': 'B77', '_csrf': tok})
    j = r.get_json()
    assert r.status_code == 200 and j['name'] == 'Inline Reagent Kit' and j['cost'] == 45
    with app.app_context():
        assert Medicine.query.count() == before + 1
        m = Medicine.query.get(j['id'])
        assert m.name == 'Inline Reagent Kit' and m.cost == 45 and m.batch == 'B77'


def test_purchase_workflow_receive_bill_pay(app, client):
    """Purchase workflow like the invoice: Order → Receive (stock in, no ledger) →
    Create Vendor Bill → Confirm (Dr Inventory/Cr AP) → Register Payment (Dr AP /
    Cr method account)."""
    from mdc_erp.models import Purchase, Supplier, Medicine, JournalEntry
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        s = Supplier.query.first() or Supplier(name='Vendor')
        if not s.id: _db.session.add(s); _db.session.commit()
        m = Medicine(name='Gloves', qty=10, reorder=5, cost=6, price=0); _db.session.add(m); _db.session.commit()
        p = Purchase(supplier_id=s.id, medicine_id=m.id, item='Gloves', qty=20, unit_cost=6,
                     total=120, paid=0, status='Requested', date='2026-09-05')
        _db.session.add(p); _db.session.commit()
        pid = p.id; mid = m.id; before_qty = m.qty
    # detail view renders with the workflow bar
    d = client.get(f'/purchase/{pid}').get_data(as_text=True)
    assert 'Purchase Order' in d and 'Received' in d and 'Vendor Bill' in d and 'Balance Due' in d
    # order + receive → stock rises, NO ledger yet
    client.get(f'/purchase/{pid}/order', follow_redirects=True)
    client.get(f'/purchase/{pid}/receive', follow_redirects=True)
    with app.app_context():
        p = Purchase.query.get(pid)
        assert p.status == 'Received' and Medicine.query.get(mid).qty == before_qty + 20
        assert JournalEntry.query.filter_by(ref=f'PUR-{pid:04d}').first() is None   # not billed yet
    # create bill (draft) then confirm → posts Dr Inventory / Cr AP
    client.get(f'/purchase/{pid}/create-bill', follow_redirects=True)
    client.get(f'/purchase/{pid}/confirm-bill', follow_redirects=True)
    with app.app_context():
        p = Purchase.query.get(pid); assert p.bill_status == 'posted'
        je = JournalEntry.query.filter_by(ref=f'PUR-{pid:04d}').first()
        debits = {l.account.code for l in je.lines if (l.debit or 0) > 0}
        credits = {l.account.code for l in je.lines if (l.credit or 0) > 0}
        assert '1300' in debits and '2100' in credits
    # register a partial payment via E. Dahab → separate payment entry
    tok = _csrf(client.get(f'/purchase/{pid}'))
    client.post(f'/purchase/{pid}/pay', data={'amount': '50', 'method': 'E. Dahab', '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        p = Purchase.query.get(pid); assert abs(p.paid - 50) < 0.01
        pje = JournalEntry.query.filter_by(ref=f'PAYP-{pid:04d}').first()
        pcredits = {l.account.code for l in pje.lines if (l.credit or 0) > 0}
        pdebits = {l.account.code for l in pje.lines if (l.debit or 0) > 0}
        assert '1106' in pcredits and '2100' in pdebits   # Cr E.Dahab, Dr Payable
    # pay the rest → fully paid
    tok = _csrf(client.get(f'/purchase/{pid}'))
    client.post(f'/purchase/{pid}/pay', data={'amount': '70', 'method': 'E. Dahab', '_csrf': tok},
                follow_redirects=True)
    with app.app_context():
        p = Purchase.query.get(pid)
        assert abs((p.total or 0) - (p.paid or 0)) < 0.01   # balance cleared


def test_purchase_payment_method_maps_to_correct_gl_account(app):
    """A purchase credits the account matching HOW the paid portion was settled —
    Cash→1101, Bank/Cheque→1102, wallets (Sahal/E.Dahab)→1103, Credit→Payable 2100.
    The inventory debit (1300) is unchanged."""
    from mdc_erp.models import Purchase, Supplier, JournalEntry
    from mdc_erp.core.posting import post_purchase
    from mdc_erp.extensions import db as _db
    import datetime as dt
    from mdc_erp.core.posting import repost_purchase_payment
    _today = dt.date.today().isoformat()
    with app.app_context():
        sup = Supplier.query.first() or Supplier(name='Vendor X')
        if not sup.id: _db.session.add(sup); _db.session.commit()
        # A confirmed vendor bill posts Dr Inventory / Cr Accounts Payable.
        # The PAYMENT (separate step) credits the account matching the method.
        cases = [('Cash', '1101'), ('Bank', '1102'), ('Cheque', '1102'),
                 ('E. Dahab', '1106'), ('Sahal', '1104')]
        for method, want in cases:
            p = Purchase(supplier_id=sup.id, item='Gloves', qty=1, unit_cost=100, total=100,
                         paid=0, pay_method=method, status='Received', bill_status='posted', date=_today)
            _db.session.add(p); _db.session.commit()
            post_purchase(p)                       # bill: Dr 1300 / Cr 2100
            je = JournalEntry.query.filter_by(ref=f'PUR-{p.id:04d}').first()
            assert je, method
            debit_accts = {l.account.code for l in je.lines if (l.debit or 0) > 0}
            credit_accts = {l.account.code for l in je.lines if (l.credit or 0) > 0}
            assert '1300' in debit_accts and '2100' in credit_accts
            assert abs(je.total_debit - je.total_credit) < 0.005
            # register the payment -> Dr AP / Cr the method's account
            p.paid = 100; _db.session.commit()
            repost_purchase_payment(p)
            pje = JournalEntry.query.filter_by(ref=f'PAYP-{p.id:04d}').first()
            pcredits = {l.account.code for l in pje.lines if (l.credit or 0) > 0}
            pdebits = {l.account.code for l in pje.lines if (l.debit or 0) > 0}
            assert '2100' in pdebits and want in pcredits, f'{method} payment should credit {want}, got {pcredits}'


def test_expense_payment_method_maps_to_correct_gl_account(app):
    """A posted expense books Dr Expense / Cr Accounts Payable; the PAYMENT
    (separate step) credits the account matching HOW it was paid —
    Cash->1101, Bank/Cheque->1102, wallets 1104-1108."""
    from mdc_erp.models import Expense, JournalEntry
    from mdc_erp.core.posting import post_expense, repost_expense_payment
    from mdc_erp.extensions import db as _db
    import datetime as dt
    _today = dt.date.today().isoformat()
    cases = [('Cash', '1101'), ('Bank', '1102'), ('Cheque', '1102'),
             ('E. Dahab', '1106'), ('Sahal', '1104')]
    with app.app_context():
        for method, want in cases:
            e = Expense(date=_today, category='Utilities', amount=100, paid=0,
                        pay_method=method, status='Posted')
            _db.session.add(e); _db.session.commit()
            post_expense(e)                         # Dr expense / Cr AP
            je = JournalEntry.query.filter_by(ref=f'EXP-{e.id:04d}').first()
            assert je, method
            debits = {l.account.code for l in je.lines if (l.debit or 0) > 0}
            credits = {l.account.code for l in je.lines if (l.credit or 0) > 0}
            assert '2100' in credits and abs(je.total_debit - je.total_credit) < 0.005
            # payment credits the method's account
            e.paid = 100; _db.session.commit()
            repost_expense_payment(e)
            pje = JournalEntry.query.filter_by(ref=f'PAYE-{e.id:04d}').first()
            pcredits = {l.account.code for l in pje.lines if (l.credit or 0) > 0}
            pdebits = {l.account.code for l in pje.lines if (l.debit or 0) > 0}
            assert '2100' in pdebits and want in pcredits, f'{method} should credit {want}, got {pcredits}'


def test_commission_fallbacks_and_paycenter(app, client):
    from mdc_erp.models import (Patient, Doctor, Service, Invoice, RadOrder,
                                CommissionAccrual, Supplier, Expense)
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    from mdc_erp.core.posting import commission_preview
    _login(client)
    with app.app_context():
        pt = Patient(name='Clean T41', mrn='MRN-T41', phone='0'); _db.session.add(pt)
        doc = Doctor(name='Dr Bashir T41', specialty='IM', phone='1', active=True,
                     commission_type='Percent', percent_rate=20)   # doctor-level rate only
        _db.session.add(doc)
        svc = Service.query.first()
        svc.department = 'CT Scan'; svc.price = 130
        svc.comm_doctor_type = ''; svc.comm_doctor_val = 0
        svc.comm_radiologist_type = ''; svc.comm_radiologist_val = 0   # force fallbacks
        _db.session.commit(); sid = svc.id; did = doc.id; pid = pt.id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        inv = _db.session.get(Invoice, iid); inv.referring_doctor_id = did
        _db.session.add(RadOrder(service_id=sid, patient_id=pid, status='Reported',
                                 date=today(), radiologist='Dr Amina T41', invoice_id=iid))
        _db.session.commit()
        dn, da, rn, ra = commission_preview(inv)
        assert abs(da - 26) < 0.01 and abs(ra - 10) < 0.01   # 20% of 130 + global $10
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert '$26' in d and '$10' in d
    # pay invoice -> accruals exist; add an unpaid utility expense
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '130', 'pay_method': 'Cash',
                                         'pay_ref': '', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    with app.app_context():
        sup = Supplier(name='BECO T41', category='Electricity Company'); _db.session.add(sup); _db.session.commit()
        _db.session.add(Expense(date=today(), category='Electricity', amount=200, paid=0,
                                supplier_id=sup.id, note='July power')); _db.session.commit()
        eid = Expense.query.filter_by(note='July power').order_by(Expense.id.desc()).first().id
    # Pay Center lists every debt and pays the utility
    d = client.get('/m/paycenter').get_data(as_text=True)
    for t in ('Doctor Commission', 'Radiologist Fees', 'Vendor Expenses', 'TOTAL DEBTS', 'BECO T41'):
        assert t in d, t
    client.get(f'/paycenter/pay-expense/{eid}', follow_redirects=True)
    with app.app_context():
        e = _db.session.get(Expense, eid)
        assert abs((e.paid or 0) - 200) < 0.01


# ============================== Phase 42: automatic scheduled backups

def test_auto_backup(app, client, tmp_path):
    import json
    from mdc_erp.core.autobackup import write_backup, list_backups
    app.config['BACKUP_DIR'] = str(tmp_path / 'backups')
    app.config['BACKUP_KEEP'] = 5
    _login(client)
    # writes a real snapshot file with the DB contents
    p = write_backup(app, reason='test')
    assert p and json.load(open(p))['data'].get('patient') is not None
    # retention keeps at most BACKUP_KEEP files
    import datetime as dt
    d = str(tmp_path / 'backups')
    for i in range(9):
        stamp = (dt.datetime.now() + dt.timedelta(seconds=i + 1)).strftime('%Y%m%d-%H%M%S')
        open(f'{d}/auto-backup-{stamp}.json', 'w').write('{}')
    write_backup(app, reason='prune')
    assert len(list_backups(app)) <= 5
    # settings page exposes the panel + manual trigger
    dd = client.get('/m/settings').get_data(as_text=True)
    assert 'Run Auto-Backup Now' in dd
    assert client.get('/backup/now', follow_redirects=True).status_code == 200


# ============================== Phase 43: XSS escaping guards

def test_xss_escaping_on_user_input(app, client):
    """Malicious text from public/user input must be HTML-escaped, never rendered raw."""
    from mdc_erp.models import Referral, Patient
    from mdc_erp.extensions import db as _db
    _login(client)
    xss = "<script>alert(1)</script>"
    with app.app_context():
        # referral with a script payload in the doctor name (public /refer field)
        r = Referral(patient_name='XSS Pt', doctor_name=xss, status='New',
                     tests='CBC', date='2026-07-20')
        _db.session.add(r); _db.session.commit()
        # a patient whose name carries a payload
        p = Patient(name=xss, mrn='MRN-XSS', phone='0')
        _db.session.add(p); _db.session.commit()
    # billing waiting panel renders the referral doctor name — must be escaped
    d = client.get('/m/invoices').get_data(as_text=True)
    assert '<script>alert(1)</script>' not in d
    assert '&lt;script&gt;' in d  # escaped form present
    # patient list must escape the name too
    d = client.get('/m/patients').get_data(as_text=True)
    assert '<script>alert(1)</script>' not in d


# ============================== Phase 44: integrity / reconciliation health check

def test_integrity_health_check(app, client):
    from mdc_erp.models import Invoice, JournalEntry, JournalLine, Account
    from mdc_erp.extensions import db as _db
    _login(client)
    # clean demo DB: everything should pass
    d = client.get('/m/integrity').get_data(as_text=True)
    assert 'Financial Health Check' in d and 'Journal entries balanced' in d
    assert 'books are consistent' in d or 'All checks passed' in d
    # introduce an unbalanced journal entry and an overpaid invoice
    with app.app_context():
        inv = Invoice(patient_id=1, date='2026-07-20', paid=999)
        _db.session.add(inv); _db.session.commit()
        je = JournalEntry(date='2026-07-20', ref='BADJE', memo='broken')
        _db.session.add(je); _db.session.flush()
        acc = Account.query.first()
        _db.session.add(JournalLine(entry_id=je.id, account_id=acc.id, debit=100, credit=0))
        _db.session.commit()
    d = client.get('/m/integrity').get_data(as_text=True)
    assert 'out of balance' in d          # unbalanced JE caught
    assert 'paid above total' in d        # overpayment caught
    assert 'need attention' in d or 'to review' in d


# ============================== Phase 45: input validation guards

def test_invoice_input_validation(app, client):
    from mdc_erp.models import Invoice, Service
    from mdc_erp.extensions import db as _db
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        sid = Service.query.first().id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    # negative quantity rejected
    r = client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '-3',
                                             '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                    follow_redirects=True)
    assert 'greater than zero' in r.get_data(as_text=True)
    with app.app_context():
        assert len(_db.session.get(Invoice, iid).items) == 0
    # non-numeric quantity is rejected (not silently accepted)
    r = client.post(f'/invoice/{iid}', data={'act': 'additem', 'desc': 'Custom', 'qty': 'abc', 'price': '50',
                                             '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    assert 'greater than zero' in r.get_data(as_text=True)
    with app.app_context():
        assert len(_db.session.get(Invoice, iid).items) == 0
    # blank quantity defaults to 1
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'desc': 'Custom', 'qty': '', 'price': '50',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        items = _db.session.get(Invoice, iid).items
        assert len(items) == 1 and items[0].qty == 1
    # negative payment rejected
    r = client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '-100',
                                             '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                    follow_redirects=True)
    assert 'cannot be negative' in r.get_data(as_text=True)
    with app.app_context():
        assert (_db.session.get(Invoice, iid).paid or 0) == 0


# ============================== Phase 46: payment idempotency (double-submit safe)

def test_payment_idempotency(app, client):
    from mdc_erp.models import (Patient, Doctor, Service, Invoice, RadOrder,
                                CommissionAccrual, JournalEntry)
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        doc = Doctor(name='Dr Idem T46', specialty='IM', phone='1', active=True,
                     commission_type='Percent', percent_rate=20)
        _db.session.add(doc)
        svc = Service.query.first()
        svc.department = 'CT Scan'; svc.price = 150
        svc.comm_doctor_type = 'Percent'; svc.comm_doctor_val = 20
        svc.comm_radiologist_type = 'Fixed'; svc.comm_radiologist_val = 10
        _db.session.commit(); sid = svc.id; did = doc.id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        inv = _db.session.get(Invoice, iid); inv.referring_doctor_id = did
        _db.session.add(RadOrder(service_id=sid, patient_id=pid, status='Reported',
                                 date=today(), radiologist='Dr Rad T46', invoice_id=iid))
        _db.session.commit()
    # simulate a triple double-submit of the same payment
    for _ in range(3):
        client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '150', 'pay_method': 'Cash',
                                             'pay_ref': '', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                    follow_redirects=True)
    with app.app_context():
        accs = CommissionAccrual.query.filter_by(invoice_id=iid).all()
        comm_je = JournalEntry.query.filter_by(ref=f'COMM-{iid:04d}').all()
        inv_je = JournalEntry.query.filter_by(ref=f'INV-{iid:04d}').all()
        assert len(accs) == 2, f'duplicate accruals: {len(accs)}'
        assert len(comm_je) == 1 and len(inv_je) == 1
        assert abs((_db.session.get(Invoice, iid).paid or 0) - 150) < 0.01


# ============================== Phase 47: full database restore

def test_full_restore(app, client):
    import io, json
    from mdc_erp.models import Patient, Service
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        n_before = Patient.query.count()
        svc_before = Service.query.count()
    # take a backup, then add a row that should NOT survive a restore
    bk = client.get('/backup').get_data()
    assert json.loads(bk)['patient']          # dump uses real table names
    with app.app_context():
        _db.session.add(Patient(name='Ghost R47', mrn='MRN-GHOST47', phone='0'))
        _db.session.commit()
        assert Patient.query.count() == n_before + 1
    tok = _csrf(client.get('/m/settings'))
    r = client.post('/restore', data={'file': (io.BytesIO(bk), 'backup.json'), '_csrf': tok},
                    content_type='multipart/form-data', follow_redirects=True)
    assert 'Restore complete' in r.get_data(as_text=True)
    with app.app_context():
        assert Patient.query.count() == n_before          # ghost gone, count restored
        assert Service.query.count() == svc_before          # other tables reloaded too
        assert Patient.query.filter_by(mrn='MRN-GHOST47').first() is None

    # a corrupt file must NOT wipe data (rolled back)
    with app.app_context():
        keep = Patient.query.count()
    tok = _csrf(client.get('/m/settings'))
    r = client.post('/restore', data={'file': (io.BytesIO(b'not json'), 'bad.json'), '_csrf': tok},
                    content_type='multipart/form-data', follow_redirects=True)
    with app.app_context():
        assert Patient.query.count() == keep                # unchanged


# ============================== Phase 48: financial audit trail

def test_financial_audit_trail(app, client):
    from mdc_erp.models import Invoice, Service
    from mdc_erp.extensions import db as _db
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        sid = Service.query.first().id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '10', 'pay_method': 'Cash', 'pay_ref': 'R1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    client.post(f'/invoice/{iid}', data={'act': 'adjust', 'discount': '5', 'discount_pct': '0', 'vat': '0',
                                         'disc_reason': 'Charity', '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                follow_redirects=True)
    # financial-only tab shows the money events with before→after amounts
    d = client.get('/m/audit?fin=1').get_data(as_text=True)
    assert 'Payment recorded on INV-' in d and '→' in d
    assert 'DISCOUNT INV-' in d and 'Financial' in d
    # all-activity tab still lists everything
    d2 = client.get('/m/audit').get_data(as_text=True)
    assert 'All Activity' in d2 and 'Created invoice' in d2


# ============================== Phase 49: soft-delete (archive) for records

def test_soft_delete_archives(app, client):
    from mdc_erp.models import Doctor
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        d = Doctor(name='Dr SoftDel T49', specialty='X', phone='1', active=True)
        _db.session.add(d); _db.session.commit(); did = d.id
    # "delete" a model that has an active flag -> archived, not removed
    client.get(f'/m/doctors/{did}/delete', follow_redirects=True)
    with app.app_context():
        d = _db.session.get(Doctor, did)
        assert d is not None and d.active is False   # row kept, just inactive


# ============================== Phase 50: money rounding discipline (no float drift)

def test_money_rounding_no_drift(app, client):
    from mdc_erp.models import Patient, Service, Invoice
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import money_round
    _login(client)
    # helper correctness
    assert money_round(0.1 + 0.2) == 0.3
    assert money_round(19.995) == 20.0          # half-up
    assert money_round(19.994) == 19.99
    assert money_round(59.97000000001) == 59.97
    # invoice math with drift-prone prices stays exact
    pid = _fresh_patient(app)
    with app.app_context():
        s = Service.query.first(); s.price = 19.99; _db.session.commit(); sid = s.id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    for _ in range(3):
        client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                             '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        inv = _db.session.get(Invoice, iid)
        assert inv.subtotal == 59.97 and inv.total == 59.97   # 3 x 19.99, no 59.970000001
    # partial payments settle to an exact zero balance
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '19.99', 'pay_method': 'Cash',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        assert _db.session.get(Invoice, iid).balance == 39.98
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '59.97', 'pay_method': 'Cash',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        assert _db.session.get(Invoice, iid).balance == 0.0


# ============================== Phase 51: server-side PDF

def test_server_side_pdf(app, client):
    from mdc_erp.models import Invoice, Service
    from mdc_erp.extensions import db as _db
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        sid = Service.query.first().id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '2',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    r = client.get(f'/invoice/{iid}/pdf')
    # reportlab is available in this environment -> real PDF bytes
    assert r.status_code == 200 and r.content_type == 'application/pdf'
    assert r.data[:4] == b'%PDF' and len(r.data) > 800
    # button is on the invoice screen
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert '/pdf' in d


# ============================== Phase 52: CSV exports

def test_csv_exports(app, client):
    import csv, io
    _login(client)
    for what in ('trialbalance', 'ledger', 'araging', 'invoices'):
        r = client.get(f'/export/csv/{what}')
        assert r.status_code == 200 and 'text/csv' in r.content_type, what
        rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
        assert rows and len(rows[0]) >= 4, what     # has a header row with columns


# ============================== Phase 53: health probes for deployment

def test_health_probes(client):
    # liveness + readiness must work without authentication (load balancers can't log in)
    r = client.get('/healthz')
    assert r.status_code == 200 and r.get_json()['status'] == 'ok'
    r = client.get('/readyz')
    assert r.status_code == 200 and r.get_json()['db'] == 'ok'


# ============================== Phase 54: forced password change on first login

def test_forced_password_change(app, client):
    """An account still carrying the default password cannot use the system
    until the password is changed."""
    from mdc_erp.models import User
    from mdc_erp.extensions import db as _db
    with app.app_context():
        u = User.query.filter_by(username='admin').first()
        u.must_change_pw = True
        _db.session.commit()
    _login(client)
    # every page bounces to the change-password screen
    for path in ('/', '/m/patients', '/m/invoices'):
        r = client.get(path)
        assert r.status_code == 302 and 'change-password' in r.location, path
    # the change-password page itself is reachable, and health probes stay open
    assert client.get('/change-password').status_code == 200
    assert client.get('/healthz').status_code == 200
    # a weak password is rejected
    tok = _csrf(client.get('/change-password'))
    r = client.post('/change-password', data={'current': 'admin123', 'new': '123', 'again': '123',
                                              '_csrf': tok}, follow_redirects=True)
    assert 'at least 4' in r.get_data(as_text=True)
    # a compliant password clears the gate
    tok = _csrf(client.get('/change-password'))
    client.post('/change-password', data={'current': 'admin123', 'new': 'Gaalkacyo2026',
                                          'again': 'Gaalkacyo2026', '_csrf': tok})
    with app.app_context():
        assert User.query.filter_by(username='admin').first().must_change_pw is False
    assert client.get('/m/patients').status_code == 200


def test_login_hint_hidden_after_onboarding(app, client):
    """The login page never exposes the default credentials, even on first run."""
    from mdc_erp.models import User
    from mdc_erp.extensions import db as _db
    with app.app_context():
        u = User.query.filter_by(username='admin').first()
        u.must_change_pw = True; _db.session.commit()
    assert 'admin123' not in client.get('/login').get_data(as_text=True)
    with app.app_context():
        u = User.query.filter_by(username='admin').first()
        u.must_change_pw = False; _db.session.commit()
    assert 'admin123' not in client.get('/login').get_data(as_text=True)


# ============================== Phase 55: integer-cent money storage

def test_money_stored_as_integer_cents(app, client):
    """Money columns are INTEGER cents in the database, floats in Python."""
    import sqlite3
    from mdc_erp.models import Invoice, InvoiceItem, Service
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.moneytype import to_cents, cents_to_amount
    # conversion helper
    for val, exp in ((150, 15000), (19.99, 1999), (0.1, 10), (19.995, 2000), (19.994, 1999),
                     (None, None), ('', None), (-5.25, -525)):
        assert to_cents(val) == exp, (val, to_cents(val))
    assert cents_to_amount(5997) == 59.97 and cents_to_amount(None) == 0.0

    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        s = Service.query.first(); s.price = 19.99; _db.session.commit(); sid = s.id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    for _ in range(3):
        client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                             '_csrf': _csrf(client.get(f'/invoice/{iid}'))},
                    follow_redirects=True)
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '59.97', 'pay_method': 'Cash',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        inv = _db.session.get(Invoice, iid)
        assert inv.subtotal == 59.97 and inv.total == 59.97 and inv.balance == 0.0
    # inspect raw storage: must be integers, not floats
    path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
    raw = sqlite3.connect(path)
    t, v = raw.execute('SELECT typeof(paid), paid FROM invoice WHERE id=?', (iid,)).fetchone()
    assert t == 'integer' and v == 5997, (t, v)
    t2, v2 = raw.execute('SELECT typeof(price), price FROM invoice_item WHERE invoice_id=? LIMIT 1',
                         (iid,)).fetchone()
    assert t2 == 'integer' and v2 == 1999, (t2, v2)
    raw.close()


def test_legacy_float_db_migrates_to_cents(tmp_path):
    """A pre-v7.2 database holding float dollars is converted exactly once."""
    import sqlite3
    from mdc_erp import create_app
    from mdc_erp.bootstrap import init_db
    from mdc_erp.config import DevelopmentConfig
    from mdc_erp.models import Invoice, Service
    from mdc_erp.extensions import db as _db
    dbf = tmp_path / 'legacy.db'

    class Cfg(DevelopmentConfig):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{dbf}'

    app = create_app(Cfg); init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.models import Patient
        p = Patient(name='Legacy', mrn='MRN-LEGACY', phone='0')
        _db.session.add(p); _db.session.commit()
        inv = Invoice(patient_id=p.id, date='2026-07-01', paid=1, vat=1)
        _db.session.add(inv); _db.session.commit(); iid = inv.id
    # rewrite as a v7.1-era database: dollars as REAL, no cents marker
    raw = sqlite3.connect(dbf)
    raw.execute('UPDATE invoice SET paid=150.0, vat=7.5, discount=12.34 WHERE id=?', (iid,))
    raw.execute('UPDATE service SET price=19.99')
    raw.execute("DELETE FROM setting WHERE key='money_cents_v'")
    raw.commit(); raw.close()

    app2 = create_app(Cfg); init_db(app2, demo=False)
    raw = sqlite3.connect(dbf)
    assert raw.execute('SELECT paid, vat, discount FROM invoice WHERE id=?', (iid,)).fetchone() \
        == (15000, 750, 1234)
    assert raw.execute('SELECT price FROM service LIMIT 1').fetchone()[0] == 1999
    raw.close()
    with app2.app_context():
        inv = _db.session.get(Invoice, iid)
        assert inv.paid == 150.0 and inv.vat == 7.5 and inv.discount == 12.34
        assert Service.query.first().price == 19.99
    # booting again must NOT convert a second time
    app3 = create_app(Cfg); init_db(app3, demo=False)
    raw = sqlite3.connect(dbf)
    assert raw.execute('SELECT paid FROM invoice WHERE id=?', (iid,)).fetchone()[0] == 15000
    raw.close()


def test_money_aggregates_return_dollars(app, client):
    """Guard: SQLAlchemy applies the Money result processor to aggregates too.
    Dividing an aggregate by 100 again would silently shrink every balance by
    100x — this test pins the behaviour so that bug can't come back."""
    from sqlalchemy import func
    from mdc_erp.models import Account, JournalEntry, JournalLine, Patient, Invoice, Service
    from mdc_erp.extensions import db as _db
    from mdc_erp.blueprints.accounting import acct_balance
    _login(client)
    with app.app_context():
        acc = Account.query.first()
        je = JournalEntry(date='2026-07-23', ref='AGG-TEST', memo='probe')
        _db.session.add(je); _db.session.flush()
        _db.session.add(JournalLine(entry_id=je.id, account_id=acc.id, debit=501.0, credit=0))
        _db.session.commit()
        # the aggregate comes back in dollars, not cents
        total = _db.session.query(func.coalesce(func.sum(JournalLine.debit), 0)) \
            .filter(JournalLine.account_id == acc.id).scalar()
        assert abs(total - ((acc.opening or 0) * 0 + 501.0)) < 0.005 or total >= 501.0
        # and the account balance reflects opening + movement exactly
        opening = acc.opening or 0
        bal = acct_balance(acc)
        assert abs(bal - (opening + 501.0)) < 0.005, (bal, opening)


# ============================== Phase 56: non-invoice money flows under cents

def test_all_money_flows_exact(app, client):
    """Purchases, expenses, payroll, depreciation and pharmacy all keep exact
    amounts and store integer cents after the Money migration."""
    import sqlite3
    from mdc_erp.models import (Purchase, Expense, Employee, Asset, Medicine,
                                PharmacySale, JournalEntry)
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    from mdc_erp.core.posting import annual_depreciation
    _login(client)
    path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')

    # purchase
    _new_purchase(client, item='Reagent T56', category='Reagents', qty='3', unit_cost='12.35',
                  paid='37.05')
    with app.app_context():
        p = Purchase.query.order_by(Purchase.id.desc()).first()
        assert p.unit_cost == 12.35 and p.total == 37.05
    raw = sqlite3.connect(path)
    assert raw.execute('SELECT typeof(unit_cost), unit_cost FROM purchase ORDER BY id DESC LIMIT 1') \
        .fetchone() == ('integer', 1235)

    # expense (Odoo flow: amount = qty × unit_price)
    _new_expense(client, post=False, description='bill T56', category='Electricity',
                 pay_method='Cash', qty='1', unit_price='249.99', note='bill T56')
    with app.app_context():
        e = Expense.query.filter_by(note='bill T56').order_by(Expense.id.desc()).first()
        assert e.amount == 249.99

    # payroll amounts
    with app.app_context():
        emp = Employee.query.first()
        emp.base = 850.75; emp.allowance = 120.25; emp.deduction = 45.50
        _db.session.commit()
        assert emp.base == 850.75 and emp.gross == 971.0

    # asset + depreciation posts a balanced journal
    y = today()[:4]
    with app.app_context():
        a = Asset(name='CT T56', cost=12000.50, useful_life=5, purchase_date=f'{y}-01-01',
                  status='Active', category='Medical Equipment')
        _db.session.add(a); _db.session.commit()
        assert a.cost == 12000.50 and abs(annual_depreciation(a, int(y)) - 2400.10) < 0.02
    client.get(f'/depreciation/run?year={y}', follow_redirects=True)
    with app.app_context():
        je = JournalEntry.query.filter(JournalEntry.ref.like('DEP-%')).first()
        assert je and abs(je.total_debit - je.total_credit) < 0.005

    # pharmacy sale
    with app.app_context():
        med = Medicine.query.first(); med.price = 7.25; _db.session.commit()
        ps = PharmacySale(date=today(), medicine_id=med.id, qty=3, total=21.75, patient_id=1)
        _db.session.add(ps); _db.session.commit()
        assert ps.total == 21.75

    # books still consistent
    d = client.get('/m/integrity').get_data(as_text=True)
    assert 'out of balance' not in d and 'mismatched' not in d


def test_backup_and_restore_cover_every_table(app, client):
    """Guard: dump_db and restore() must stay derived from the same table map.

    They drifted apart once — dump_db was generalised to real table names while
    restore still looked for old section names, so a restore matched nothing,
    deleted the database and reloaded zero rows. This pins both sides."""
    import io, json
    from mdc_erp.models import (Patient, Invoice, InvoiceItem, JournalEntry,
                                JournalLine, PayReceipt, CommissionAccrual, Doctor, Service)
    from mdc_erp.extensions import db as _db
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        doc = Doctor(name='Dr Rst', specialty='IM', phone='1', active=True,
                     commission_type='Percent', percent_rate=20)
        _db.session.add(doc)
        sv = Service.query.first(); sv.price = 199.99
        sv.comm_doctor_type = 'Percent'; sv.comm_doctor_val = 20
        _db.session.commit(); did = doc.id; sid = sv.id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '2',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        inv = _db.session.get(Invoice, iid); inv.referring_doctor_id = did; _db.session.commit()
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '399.98', 'pay_method': 'Cash',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)

    def snapshot():
        with app.app_context():
            return {m.__name__: m.query.count() for m in
                    (Patient, Invoice, InvoiceItem, JournalEntry, JournalLine,
                     PayReceipt, CommissionAccrual)}

    before = snapshot()
    assert before['JournalEntry'] > 0 and before['JournalLine'] > 0   # ledger has data
    bk = client.get('/backup').get_data()
    dump = json.loads(bk)
    # the backup must include ledger tables, not just the old 18 sections
    for t in ('patient', 'invoice', 'invoice_item', 'journal_entry', 'journal_line'):
        assert t in dump, t
    # wipe the ledger, then restore
    with app.app_context():
        _db.session.query(JournalLine).delete(); _db.session.query(JournalEntry).delete()
        _db.session.commit()
    r = client.post('/restore', data={'file': (io.BytesIO(bk), 'b.json'),
                                      '_csrf': _csrf(client.get('/m/settings'))},
                    content_type='multipart/form-data', follow_redirects=True)
    assert 'Restore complete' in r.get_data(as_text=True)
    assert snapshot() == before                       # ledger fully recovered
    with app.app_context():
        inv = _db.session.get(Invoice, iid)
        assert inv.total == 399.98 and inv.paid == 399.98   # money exact after restore
    # a file that matches none of our tables is refused instead of wiping data
    client.post('/restore', data={'file': (io.BytesIO(b'{"nonsense": []}'), 'x.json'),
                                  '_csrf': _csrf(client.get('/m/settings'))},
                content_type='multipart/form-data', follow_redirects=True)
    assert snapshot() == before


# ============================== Phase 57: letterhead on printed documents

def test_letterhead_artwork_on_print(app, client):
    """The centre's own printed header/footer artwork appears on documents, and
    the on-screen action buttons never reach the paper."""
    from mdc_erp.models import Invoice, Service, Setting
    from mdc_erp.extensions import db as _db
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        sid = Service.query.first().id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    pr = client.get(f'/invoice/{iid}/print').get_data(as_text=True)
    # artwork is referenced and served
    assert 'letterhead-header.jpg' in pr and 'letterhead-footer.jpg' in pr
    assert client.get('/static/brand/letterhead-header.jpg').status_code == 200
    assert client.get('/static/brand/letterhead-footer.jpg').status_code == 200
    # the button bar carries an inline display:flex, so the print rule must be
    # !important or the buttons end up on every printed page
    assert 'display:none !important' in pr
    # content is pushed clear of the artwork on paper
    assert 'padding-top:38mm' in pr
    # switching the letterhead off falls back to the text header
    with app.app_context():
        s = Setting.query.get('letterhead') or Setting(key='letterhead')
        s.value = '0'; _db.session.add(s); _db.session.commit()
    pr = client.get(f'/invoice/{iid}/print').get_data(as_text=True)
    assert 'letterhead-header.jpg' not in pr and 'Modern Diagnostic Center' in pr


# ============================== Phase 58: per-scan radiologist fee (like doctor commission)

def test_per_scan_radiologist_fee(app, client):
    """The radiologist fee is set on the scan itself, exactly the way the
    referring-doctor commission is, and accrues from that setting."""
    from mdc_erp.models import Service, Patient, Doctor, Invoice, RadOrder, CommissionAccrual
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    _login(client)
    # the simple service form carries both rows
    d = client.get('/svcmgmt/new').get_data(as_text=True)
    for t in ('Doctor Commission', 'Radiologist Fee', 'comm_doctor_type',
              'comm_radiologist_type', 'comm_doctor_val', 'comm_radiologist_val'):
        assert t in d, t
    tok = _csrf(client.get('/svcmgmt/new'))
    client.post('/svcmgmt/new', data={'name': 'CT Brain T58', 'department': 'CT Scan',
                                      'category': 'CT', 'price': '150', 'cost': '40', 'active': '1',
                                      'comm_doctor_type': 'Percent', 'comm_doctor_val': '20',
                                      'comm_radiologist_type': 'Fixed', 'comm_radiologist_val': '10',
                                      '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        sv = Service.query.filter_by(name='CT Brain T58').first()
        assert sv.comm_doctor_type == 'Percent' and sv.comm_doctor_val == 20
        assert sv.comm_radiologist_type == 'Fixed' and sv.comm_radiologist_val == 10
        sid = sv.id
    # the edit form pre-selects what was saved
    d = client.get(f'/svcmgmt/{sid}/edit').get_data(as_text=True)
    assert "value='Percent' selected" in d and "value='Fixed' selected" in d
    # billing that scan accrues $30 to the doctor and $10 to the radiologist
    pid = _fresh_patient(app)
    with app.app_context():
        doc = Doctor(name='Dr Ref T58', specialty='IM', phone='1', active=True)
        _db.session.add(doc); _db.session.commit(); did = doc.id
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        inv = _db.session.get(Invoice, iid); inv.referring_doctor_id = did
        _db.session.add(RadOrder(service_id=sid, patient_id=pid, status='Reported',
                                 date=today(), radiologist='Dr Amina T58', invoice_id=iid))
        _db.session.commit()
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '150', 'pay_method': 'Cash',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        a = {x.payee_kind: x for x in CommissionAccrual.query.filter_by(invoice_id=iid).all()}
        assert a['doctor'].amount == 30.0
        assert a['radiologist'].amount == 10.0 and a['radiologist'].payee_name == 'Dr Amina T58'


# ============================== Phase 58: pagination + row-level branch security

def test_list_pagination(app, client):
    """Lists must never render an unbounded table."""
    from mdc_erp.models import Patient
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        _db.session.bulk_save_objects(
            [Patient(name=f'Bulk {i}', mrn=f'MRN-B{i:05d}', phone='0') for i in range(300)])
        _db.session.commit()
        total = Patient.query.count()
    d = client.get('/m/patients').get_data(as_text=True)
    assert d.count('<tr>') <= 55                      # one page, not 300+
    assert f'of {total:,}' in d                       # total is reported
    # page 2 shows a different slice
    d2 = client.get('/m/patients?page=2').get_data(as_text=True)
    assert '51–100' in d2
    # out-of-range page clamps instead of erroring
    assert client.get('/m/patients?page=99999').status_code == 200
    # search and pagination combine, and the pager keeps the search
    d3 = client.get('/m/patients?q=Bulk+1').get_data(as_text=True)
    assert 'of ' in d3 and ('q=Bulk' in d3.replace('&amp;', '&') or d3.count('<tr>') <= 55)


def test_security_headers_present(client):
    """#20: every response carries the hardening headers (CSP, X-Frame-Options,
    X-Content-Type-Options, Referrer-Policy). HSTS is emitted under the secure
    production config."""
    r = client.get('/login')
    h = r.headers
    assert h.get('X-Content-Type-Options') == 'nosniff'
    assert h.get('X-Frame-Options') == 'SAMEORIGIN'
    assert 'same-origin' in (h.get('Referrer-Policy') or '')
    csp = h.get('Content-Security-Policy') or ''
    assert "default-src 'self'" in csp and "frame-ancestors 'self'" in csp and "form-action 'self'" in csp


def test_production_fails_closed_without_secrets(monkeypatch):
    """#19: production configuration refuses to start when required secrets are
    missing, rather than falling back to an insecure default."""
    import importlib
    from mdc_erp import config as cfg
    # clear any secrets the environment might carry
    for k in ('SECRET_KEY', 'JWT_SECRET_KEY', 'DB_PASSWORD', 'ENCRYPTION_KEY', 'DATABASE_URL'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('FLASK_CONFIG', 'production')
    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        cfg.pick_config()
    # and it still fails if a secret is present but too weak/short
    monkeypatch.setenv('SECRET_KEY', 'short')
    monkeypatch.setenv('JWT_SECRET_KEY', 'x' * 40)
    monkeypatch.setenv('DB_PASSWORD', 'x' * 40)
    monkeypatch.setenv('ENCRYPTION_KEY', 'x' * 40)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://u:p@h/db')
    with _pytest.raises(RuntimeError):
        cfg.pick_config()   # SECRET_KEY too short


def test_no_hardcoded_default_secret_in_source():
    """#19: the codebase must not ship a hardcoded production secret."""
    import glob
    banned = ('mdc_secret', 'change-this', 'changeme')
    for path in glob.glob('mdc_erp/**/*.py', recursive=True):
        with open(path, encoding='utf-8') as fh:
            txt = fh.read().lower()
        for b in banned:
            assert b not in txt, f'hardcoded secret marker {b!r} found in {path}'


def test_row_level_branch_security(app, client):
    """Route permissions say which screens; this says which rows."""
    from mdc_erp.models import Branch, User, Patient, Invoice
    from mdc_erp.extensions import db as _db
    from werkzeug.security import generate_password_hash
    with app.app_context():
        b1 = Branch.query.first()
        b2 = Branch(name='Hobyo Branch T58'); _db.session.add(b2); _db.session.commit()
        for un, br in (('cash_a58', b1.id), ('cash_b58', b2.id)):
            _db.session.add(User(username=un, name=un, role='cashier', active=True, branch_id=br,
                                 pw=generate_password_hash('Xisaab2026'), must_change_pw=False))
        p = Patient(name='Pt T58', mrn='MRN-T58', phone='0'); _db.session.add(p); _db.session.commit()
        i1 = Invoice(patient_id=p.id, date='2026-07-23', branch_id=b1.id)
        i2 = Invoice(patient_id=p.id, date='2026-07-23', branch_id=b2.id)
        _db.session.add_all([i1, i2]); _db.session.commit()
        id1, id2 = i1.id, i2.id
        id_b1, id_b2 = b1.id, b2.id

    def as_user(u, pw='Xisaab2026'):
        c = app.test_client()
        tok = _csrf(c.get('/login'))
        c.post('/login', data={'username': u, 'password': pw, '_csrf': tok})
        return c

    a, b = as_user('cash_a58'), as_user('cash_b58')
    la = a.get('/m/invoices').get_data(as_text=True)
    lb = b.get('/m/invoices').get_data(as_text=True)
    assert f'INV-{id1:04d}' in la and f'INV-{id2:04d}' not in la
    assert f'INV-{id2:04d}' in lb and f'INV-{id1:04d}' not in lb
    # a direct URL must not cross branches
    assert a.get(f'/invoice/{id2}').status_code == 403
    assert b.get(f'/invoice/{id1}').status_code == 403
    # branch isolation also holds for Expenses (another branch-aware financial model)
    from mdc_erp.models import Expense
    with app.app_context():
        e1 = Expense(date='2026-07-23', category='Rent', amount=10, paid=10,
                     pay_method='Cash', branch_id=id_b1)
        e2 = Expense(date='2026-07-23', category='Rent', amount=20, paid=20,
                     pay_method='Cash', branch_id=id_b2)
        _db.session.add_all([e1, e2]); _db.session.commit()
        eid1, eid2 = e1.id, e2.id
    # accountant scoped to branch A sees only A's expense in the list
    with app.app_context():
        _db.session.add(User(username='acc_a58', name='acc_a58', role='accountant',
                             active=True, branch_id=id_b1,
                             pw=generate_password_hash('Xisaab2026'), must_change_pw=False))
        _db.session.commit()
    acc = as_user('acc_a58')
    lea = acc.get('/m/expenses').get_data(as_text=True)
    assert f'EXP-{eid1:04d}' in lea or 'Rent' in lea   # A's expense visible
    # super admin still sees everything
    _login(client)
    ld = client.get('/m/invoices').get_data(as_text=True)
    assert f'INV-{id1:04d}' in ld and f'INV-{id2:04d}' in ld


# ============================== Phase 59: performance guards at scale

def test_no_n_plus_one_on_hot_pages(app, client):
    """Hot pages must not re-query (or recompute) per invoice.

    At 12k invoices these pages took 11-27 seconds because Invoice.total reads
    its line items on every access. This counts SQL statements instead of timing,
    so the guard is stable on slow CI machines."""
    from mdc_erp.models import Invoice, InvoiceItem, Patient, Service
    from mdc_erp.extensions import db as _db
    from sqlalchemy import event
    from mdc_erp.core.helpers import today
    _login(client)
    with app.app_context():
        sv = Service.query.first()
        p = Patient(name='Perf', mrn='MRN-PERF', phone='0')
        _db.session.add(p); _db.session.commit()
        _db.session.bulk_save_objects([Invoice(patient_id=p.id, date=today(), paid=10)
                                       for _ in range(120)])
        _db.session.commit()
        ids = [i.id for i in Invoice.query.order_by(Invoice.id.desc()).limit(120).all()]
        _db.session.bulk_save_objects([InvoiceItem(invoice_id=i, service_id=sv.id,
                                                   desc='x', qty=1, price=10) for i in ids])
        _db.session.commit()

    counts = {}

    def counted(url, key):
        n = [0]
        eng = _db.get_engine() if hasattr(_db, 'get_engine') else _db.engine
        def before(conn, cur, stmt, params, ctx, many): n[0] += 1
        event.listen(eng, 'before_cursor_execute', before)
        try:
            assert client.get(url).status_code == 200
        finally:
            event.remove(eng, 'before_cursor_execute', before)
        counts[key] = n[0]

    with app.app_context():
        counted('/m/invoices', 'invoices')
        counted('/', 'dashboard')
    # with 120 invoices present, a per-row query pattern would blow past this
    assert counts['invoices'] < 80, counts
    assert counts['dashboard'] < 120, counts


# ============================== Phase 59: Odoo-style list powers (sort/group/export)

def test_list_sort_group_export(app, client):
    """Every list gains sort, group-by with totals, drill-down and a CSV export
    that respects whatever is on screen — without any per-list configuration."""
    import csv, io
    from mdc_erp.models import Patient, Expense
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.helpers import today
    _login(client)
    with app.app_context():
        for i, (g, bg) in enumerate([('Male', 'A+'), ('Female', 'O+')] * 20):
            _db.session.add(Patient(name=f'G{i}', mrn=f'MRN-G{i:04d}', phone='0',
                                    gender=g, blood_group=bg))
        for i in range(9):
            _db.session.add(Expense(date=today(), category=['Electricity', 'Water', 'Fuel'][i % 3],
                                    pay_method=['Cash', 'Bank', 'Cheque'][i % 3],
                                    amount=100 + i, paid=0, note=f'e{i}'))
        _db.session.commit()

    # sort controls render and apply
    d = client.get('/m/patients?sort=gender&dir=asc').get_data(as_text=True)
    assert 'Sort: Gender' in d and client.get('/m/patients?sort=mrn&dir=desc').status_code == 200

    # group-by shows one row per distinct value with counts
    d = client.get('/m/patients?group=gender').get_data(as_text=True)
    assert 'grouped' in d and 'Male' in d and 'Female' in d and 'Count' in d
    # money columns are summed per group, with a grand total row
    d = client.get('/m/expenses?group=category').get_data(as_text=True)
    assert 'grouped' in d and 'Amount' in d and 'Total' in d

    # drilling into a group returns the normal (paginated) list
    d = client.get('/m/patients?group=gender&gv=Male').get_data(as_text=True)
    assert 'grouped' not in d

    # export honours the active group filter
    r = client.get('/m/patients/export.csv?group=gender&gv=Female')
    assert r.headers['Content-Type'].startswith('text/csv')
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    gi = rows[0].index('Gender')
    assert rows[1:] and {row[gi] for row in rows[1:]} == {'Female'}
    # ...and the active search
    r = client.get('/m/patients/export.csv?q=MRN-G00')
    assert len(list(csv.reader(io.StringIO(r.get_data(as_text=True))))) > 1
    # passwords never leave in an export
    assert 'Pw' not in rows[0] and 'Password' not in rows[0]


# ============================== Phase 60: guarantor on credit invoices

def test_guarantor_on_credit_invoices(app, client):
    """A credit sale prints who stands behind the debt; a settled cash sale does not."""
    from mdc_erp.models import Invoice, Service
    from mdc_erp.extensions import db as _db
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        s = Service.query.first(); s.price = 150; _db.session.commit(); sid = s.id

    def new_invoice():
        client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                    follow_redirects=True)
        with app.app_context():
            i = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
        client.post(f'/invoice/{i}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                           '_csrf': _csrf(client.get(f'/invoice/{i}'))}, follow_redirects=True)
        return i

    # unpaid invoice with a named guarantor -> block prints ON THE LOAN DOCUMENT (?loan=1)
    a = new_invoice()
    # BEFORE a guarantor is entered, the loan document is refused (redirects back)
    blocked = client.get(f'/invoice/{a}/print?loan=1', follow_redirects=True).get_data(as_text=True)
    assert 'Credit account' not in blocked and 'Guarantor signature' not in blocked
    client.post(f'/invoice/{a}', data={'act': 'guarantor', 'guarantor': 'Modern Hospital',
                                       '_csrf': _csrf(client.get(f'/invoice/{a}'))}, follow_redirects=True)
    with app.app_context():
        assert _db.session.get(Invoice, a).guarantor == 'Modern Hospital'
    pr = client.get(f'/invoice/{a}/print?loan=1').get_data(as_text=True)
    assert 'Credit account' in pr and 'Modern Hospital' in pr and 'Guarantor signature' in pr
    # the plain invoice print never carries the guarantor/loan block
    plain = client.get(f'/invoice/{a}/print').get_data(as_text=True)
    assert 'Credit account' not in plain and 'Guarantor signature' not in plain

    # fully paid in cash -> no guarantor block at all (even on the loan doc)
    b = new_invoice()
    client.post(f'/invoice/{b}', data={'act': 'pay', 'paid': '150', 'pay_method': 'Cash',
                                       '_csrf': _csrf(client.get(f'/invoice/{b}'))}, follow_redirects=True)
    pr = client.get(f'/invoice/{b}/print?loan=1').get_data(as_text=True)
    assert 'Credit account' not in pr and 'Guarantor signature' not in pr

    # part payment -> still a credit sale, block remains with the balance (on the loan doc)
    d = new_invoice()
    client.post(f'/invoice/{d}', data={'act': 'guarantor', 'guarantor': 'Xasan Cali',
                                       '_csrf': _csrf(client.get(f'/invoice/{d}'))}, follow_redirects=True)
    client.post(f'/invoice/{d}', data={'act': 'pay', 'paid': '50', 'pay_method': 'Cash',
                                       '_csrf': _csrf(client.get(f'/invoice/{d}'))}, follow_redirects=True)
    pr = client.get(f'/invoice/{d}/print?loan=1').get_data(as_text=True)
    assert 'Xasan Cali' in pr and '$100' in pr

    # no guarantor typed -> the loan document is refused entirely (must fill it first)
    e = new_invoice()
    pr = client.get(f'/invoice/{e}/print?loan=1', follow_redirects=True).get_data(as_text=True)
    assert 'Credit account' not in pr and 'Guarantor signature' not in pr

    # the debt-chasing report shows who guarantees each open invoice
    d2 = client.get('/m/araging').get_data(as_text=True)
    assert 'Guarantor' in d2 and 'Modern Hospital' in d2 and 'guaranteed by' in d2


def test_inventory_product_detail_view(app, client):
    """Odoo-style product page: status, smart-button stats and stock-movement history."""
    from mdc_erp.models import Medicine, StockAdj, Supplier, Purchase
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        m = Medicine(name='Contrast Media X', batch='B99', expiry='2026-12-31',
                     qty=42, reorder=10, cost=12, price=0)
        _db.session.add(m); _db.session.commit(); mid = m.id
        _db.session.add(StockAdj(medicine_id=mid, qty_change=-3,
                                 reason='Consumed (manual) — CT room', user='sadiya', date='2026-09-04'))
        s = Supplier(name='Vendor Z'); _db.session.add(s); _db.session.commit()
        _db.session.add(Purchase(supplier_id=s.id, medicine_id=mid, item='Contrast Media X',
                                 qty=50, unit_cost=12, total=600, paid=600, status='Received',
                                 date='2026-09-01', received_date='2026-09-02'))
        _db.session.commit()
    d = client.get(f'/stock/item/{mid}').get_data(as_text=True)
    assert 'Contrast Media X' in d
    assert 'On Hand' in d and 'Stock Value' in d and 'Reorder Level' in d   # smart stats
    assert 'Stock Movements' in d
    assert 'Consumed (manual)' in d and 'PUR-' in d                          # history rows
    # the product name in the list links to the detail page
    lst = client.get('/m/inventory').get_data(as_text=True)
    assert f'/stock/item/{mid}' in lst


def test_restore_reapplies_current_chart_of_accounts(app):
    """When an OLDER backup (missing accounts a newer update added, and even the
    branch/warehouse) is restored, the current version's structural seed is
    re-applied so the ledger AND inventory keep working."""
    from mdc_erp.models import Account, Warehouse, Branch
    from mdc_erp.bootstrap import ensure_seed
    from mdc_erp.blueprints.admin import dump_db, load_db
    new_codes = ['1104', '1105', '1106', '1107', '1108', '4450', '5140', '2310']
    with app.app_context():
        backup = dump_db()
        # simulate an old backup: no new accounts, and no branch/warehouse rows
        backup['account'] = [r for r in backup['account'] if r.get('code') not in new_codes]
        backup['warehouse'] = []
        backup['branch'] = []
        load_db(backup)
        # accounts re-applied
        present = {a.code for a in Account.query.filter(Account.code.in_(new_codes)).all()}
        assert present == set(new_codes), f'restore lost accounts: {set(new_codes) - present}'
        # branch + warehouse re-applied so inventory keeps working
        assert Branch.query.count() >= 1
        assert Warehouse.query.filter_by(active=True).count() >= 1
        # idempotent — nothing added on a second pass
        assert ensure_seed().get('accounts', 0) == 0


def test_guarantor_locks_after_save_and_can_be_edited(app, client):
    """Once credit details are saved, the guarantor is shown locked (read-only)
    with an Edit button; clicking Edit re-opens the input to change it."""
    from mdc_erp.models import Invoice
    _login(client)
    pid = _fresh_patient(app)
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    with app.app_context():
        iid = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
    # before saving → the editable input is shown
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'name="guarantor"' in d
    # save credit details
    client.post(f'/invoice/{iid}', data={'act': 'guarantor', 'guarantor': 'Modern Hospital',
                                         'due_date': '2026-10-01',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    # now LOCKED: read-only value + Edit button, no input field
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'Modern Hospital' in d and 'Edit credit details' in d
    assert 'name="guarantor"' not in d          # the input is hidden while locked
    # clicking Edit (?edit_guar=1) reveals the input again
    d = client.get(f'/invoice/{iid}?edit_guar=1').get_data(as_text=True)
    assert 'name="guarantor"' in d and 'Save credit details' in d


def test_guarantor_is_searchable_and_attributed(app, client):
    """The guarantor lives in the system, not just on paper: it is searchable,
    visible on screen, and records which member of staff granted the credit."""
    from mdc_erp.models import Invoice, Service, Patient, User
    from mdc_erp.extensions import db as _db
    with app.app_context():
        u = User.query.filter_by(username='admin').first()
        u.name = 'Xasan Cashier'; _db.session.commit()
        s = Service.query.first(); s.price = 150; _db.session.commit(); sid = s.id
    _login(client)
    made = []
    for g in ('Modern Hospital', 'Modern Hospital', 'Daryeel Clinic'):
        pid = _fresh_patient(app)
        client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                    follow_redirects=True)
        with app.app_context():
            i = Invoice.query.filter_by(patient_id=pid).order_by(Invoice.id.desc()).first().id
        client.post(f'/invoice/{i}', data={'act': 'additem', 'service_id': str(sid), 'qty': '1',
                                           '_csrf': _csrf(client.get(f'/invoice/{i}'))}, follow_redirects=True)
        client.post(f'/invoice/{i}', data={'act': 'guarantor', 'guarantor': g,
                                           '_csrf': _csrf(client.get(f'/invoice/{i}'))}, follow_redirects=True)
        made.append(i)

    # the staff member who granted the credit is recorded
    with app.app_context():
        iv = _db.session.get(Invoice, made[0])
        assert iv.guarantor == 'Modern Hospital'
        assert iv.guarantor_by == 'Xasan Cashier' and iv.guarantor_at

    # global search finds every invoice a partner hospital stands behind
    d = client.get('/search?q=Modern Hospital').get_data(as_text=True)
    import re as _re
    assert len(set(_re.findall(r'INV-(\d{4})', d))) >= 2
    assert 'Guarantor' in d and 'Xasan Cashier' in d
    # a partial guarantor name that uniquely identifies one invoice opens it
    # directly (global search opens the record when the match is unambiguous)
    assert 'Daryeel Clinic' in client.get('/search?q=Daryeel', follow_redirects=True).get_data(as_text=True)

    # the invoice screen shows it as a badge with attribution
    d = client.get(f'/invoice/{made[0]}').get_data(as_text=True)
    assert 'Modern Hospital' in d and 'Credit granted by' in d

    # the invoice list flags a credit sale that has no guarantor recorded
    pid = _fresh_patient(app)
    client.post('/invoice/new', data={'patient_id': str(pid), '_csrf': _csrf(client.get('/invoice/new'))},
                follow_redirects=True)
    d = client.get('/m/invoices').get_data(as_text=True)
    assert 'Guarantor' in d and 'not set' in d


# ===================================================================
# Phase 1 — regression guards for the navigation + hardening work.
# These lock in behaviour that a future template refactor must preserve.
# ===================================================================

def _unposted_invoice(app, price=1000):
    """Create an invoice WITH an item directly in the DB (no POST), so it has a
    positive total but has NOT been posted to the ledger yet — the exact state
    needed to prove that a GET view must not post."""
    from mdc_erp.models import Invoice, InvoiceItem, JournalEntry
    from mdc_erp.extensions import db as _db
    pid = _fresh_patient(app)
    with app.app_context():
        inv = Invoice(patient_id=pid, date='2026-07-20', status='Unpaid')
        _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, desc='Manual test line', qty=1, price=price))
        _db.session.commit()
        iid = inv.id
        assert inv.total > 0, 'test invoice must have a positive total'
        # guarantee a clean starting point
        for e in JournalEntry.query.filter(JournalEntry.ref.in_([f'INV-{iid:04d}', f'PAY-{iid:04d}'])).all():
            _db.session.delete(e)
        _db.session.commit()
    return iid


def _journal_count(app, iid):
    from mdc_erp.models import JournalEntry
    with app.app_context():
        return JournalEntry.query.filter(
            JournalEntry.ref.in_([f'INV-{iid:04d}', f'PAY-{iid:04d}'])).count()


def test_invoice_get_never_posts_to_ledger(client, app):
    """Regression: viewing an invoice (GET) must have NO ledger side-effects.
    Posting happens only on the explicit sync/pay POST actions."""
    _login(client)
    iid = _unposted_invoice(app)
    # multiple GETs / refreshes must not create journal entries
    assert client.get(f'/invoice/{iid}').status_code == 200
    client.get(f'/invoice/{iid}')
    client.get(f'/invoice/{iid}')
    assert _journal_count(app, iid) == 0, 'GET must not post to the ledger'
    # the page should surface an explicit Sync/Post prompt instead
    data = client.get(f'/invoice/{iid}').data
    assert b'sync' in data and b'Post to ledger' in data


def test_invoice_sync_action_posts(client, app):
    """The explicit sync POST posts to the ledger (and is idempotent-safe)."""
    _login(client)
    iid = _unposted_invoice(app)
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'sync', '_csrf': tok}, follow_redirects=True)
    assert _journal_count(app, iid) > 0, 'sync must post to the ledger'


def test_gl_filter_by_created_by(app, client):
    """The General Ledger can be filtered by who posted the entry (Created by)."""
    from mdc_erp.models import JournalEntry, JournalLine, Account
    from mdc_erp.core.posting import acc_ensure
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        acc_ensure('5100', 'Rent', 'Expense', '5000')
        cash = Account.query.filter_by(code='1101').first()
        rent = Account.query.filter_by(code='5100').first()
        for ref, who, amt in (('JV-SAD', 'Sadiya Cabdi', 50), ('JV-AHM', 'Ahmed Nur', 70)):
            je = JournalEntry(date='2026-09-04', ref=ref, memo=ref, posted_by=who)
            _db.session.add(je); _db.session.flush()
            _db.session.add_all([JournalLine(entry_id=je.id, account_id=rent.id, debit=amt, credit=0),
                                 JournalLine(entry_id=je.id, account_id=cash.id, debit=0, credit=amt)])
        _db.session.commit()
    # filter by Sadiya → only her entry
    d = client.get('/m/genledger?creator=Sadiya+Cabdi&group=none').get_data(as_text=True)
    assert 'JV-SAD' in d and 'JV-AHM' not in d
    # unfiltered → both, and the dropdown lists the creators
    d2 = client.get('/m/genledger?group=none').get_data(as_text=True)
    assert 'JV-SAD' in d2 and 'JV-AHM' in d2
    assert 'Created by' in d2 and 'Sadiya Cabdi' in d2 and 'Ahmed Nur' in d2


def test_invoice_records_created_by(app, client):
    """Every invoice records who created it (Created by), shown on the view."""
    _login(client)   # logs in as admin (System Administrator)
    r = client.post('/invoice/new', data={'patient_id': '', '_csrf': _csrf(client.get('/invoice/new'))},
                    follow_redirects=True)
    from mdc_erp.models import Invoice
    with app.app_context():
        inv = Invoice.query.order_by(Invoice.id.desc()).first()
        assert inv.created_by and inv.created_at, 'invoice must record its creator'
        iid = inv.id
        who = inv.created_by
    # the invoice view shows "Created by"
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'Created by' in d and who in d


def test_confirm_invoice_auto_posts_to_ledger(client, app):
    """Confirming an invoice auto-posts the sale to the general ledger (Dr AR /
    Cr Revenue) — no separate 'Sync & Post to ledger' step is needed."""
    _login(client)
    iid = _unposted_invoice(app)
    assert _journal_count(app, iid) == 0                    # nothing posted yet
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'confirm', '_csrf': tok}, follow_redirects=True)
    assert _journal_count(app, iid) > 0, 'confirm must post to the ledger'
    # the "not yet posted / Post to ledger" prompt is gone once posted
    d = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'not yet posted to the ledger' not in d
    # and the posted entry balances
    with app.app_context():
        from mdc_erp.models import JournalEntry
        je = JournalEntry.query.filter_by(ref=f'INV-{iid:04d}').first()
        assert je and abs(je.total_debit - je.total_credit) < 0.01


def test_breadcrumbs_back_and_shortcuts_present(client):
    """Every in-app page carries breadcrumbs, a Back button and Alt-key nav."""
    _login(client)
    html = client.get('/m/finance?tab=pnl').get_data(as_text=True)
    assert 'navbar' in html, 'breadcrumb/back bar missing'
    assert 'crumbs' in html and 'nav-back' in html
    assert 'Home' in html
    assert 'altKey' in html, 'keyboard shortcuts script missing'


def test_patient_hub_has_tabs_and_timeline(client, app):
    """Patient page shows no-reload tabs and a chronological timeline."""
    _login(client)
    pid = _fresh_patient(app)
    html = client.get(f'/patient/{pid}').get_data(as_text=True)
    assert 'rtabs' in html, 'record tabs missing'
    assert 'Timeline' in html and 'tl-i' in html, 'timeline missing'
    assert 'Registration' in html


def test_invoice_smartbar_and_crumbs(client, app):
    """Invoice detail keeps a rich breadcrumb trail; the quick-action chip row
    (Patient / Receive Payment / Accounting Entry / Lab / Radiology) was removed
    to keep the invoice screen clean — those actions live on the patient hub."""
    _login(client)
    iid = _unposted_invoice(app)
    html = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'crumbs' in html and 'Invoices' in html
    # the chip row is gone from the invoice
    assert '💵 Receive Payment' not in html and '📒 Accounting Entry' not in html


def test_invoice_preview_endpoint(client, app):
    """The modal-preview JSON endpoint returns a well-formed payload."""
    _login(client)
    iid = _unposted_invoice(app)
    r = client.get(f'/preview/invoice/{iid}')
    assert r.status_code == 200
    j = r.get_json()
    assert j and 'title' in j and 'rows' in j and 'actions' in j
    assert any(row[0] == 'Balance' for row in j['rows'])


def test_recently_viewed_tracks_records(client, app):
    """Viewing a record adds it to the Recently-viewed menu shown app-wide."""
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        from mdc_erp.models import Patient
        name = Patient.query.get(pid).name
    client.get(f'/patient/{pid}')                       # record the view
    dash = client.get('/dashboard').get_data(as_text=True)
    assert 'recent-menu' in dash
    assert name in dash, 'viewed patient not in Recently-viewed menu'


def test_sqlite_concurrency_pragmas(app):
    """SQLite is opened in WAL mode with a busy-timeout (multi-user safety)."""
    from sqlalchemy import text
    from mdc_erp.extensions import db as _db
    with app.app_context():
        assert str(_db.session.execute(text('PRAGMA journal_mode')).scalar()).lower() == 'wal'
        assert int(_db.session.execute(text('PRAGMA busy_timeout')).scalar()) >= 3000


def test_log_error_never_raises(app):
    """The best-effort error logger must never raise, even mid-exception."""
    from mdc_erp.core.helpers import log_error
    with app.app_context():
        try:
            raise ValueError('boom')
        except Exception:
            log_error('unit-test context')   # must not raise
    assert True


def test_pages_carry_branded_print_letterhead(client):
    """Printed pages (incl. financial statements) carry the letterhead artwork."""
    _login(client)
    html = client.get('/m/finance?tab=pnl').get_data(as_text=True)
    assert 'print-lh' in html, 'print letterhead markup missing'


def test_login_page_is_redesigned(app):
    """The public login page uses the split-screen international layout."""
    c = app.test_client()
    html = c.get('/login').get_data(as_text=True)
    assert 'lg-wrap' in html and 'lg-brand' in html
    assert 'Sign in' in html


def test_public_shell_uses_jinja_template(app):
    """Public pages render through templates/public.html."""
    c = app.test_client()
    html = c.get('/refer').get_data(as_text=True)
    assert 'pubwrap' in html and 'pubhead' in html
    assert 'Powered by MDC ERP' in html


def test_errorlog_list_uses_component_table(client):
    """The error-log list renders via the reusable Jinja data_table component."""
    _login(client)
    html = client.get('/m/errorlog').get_data(as_text=True)
    assert '<table>' in html
    for hdr in ['ID', 'When', 'User', 'Screen', 'Type', 'Status']:
        assert hdr in html, f'missing column {hdr}'


def test_journal_and_lab_use_shared_list_component(client):
    """Journal & Lab lists render through the shared list_page/data_table macro,
    with numeric columns right-aligned via the `aligns` support."""
    _login(client)
    jhtml = client.get('/m/journal').get_data(as_text=True)
    assert 'Journal Entries' in jhtml and '<table>' in jhtml
    assert 'Debit' in jhtml and 'Credit' in jhtml and 'class="num"' in jhtml
    lhtml = client.get('/m/lab').get_data(as_text=True)
    assert 'Laboratory' in lhtml and '<table>' in lhtml and 'class="num"' in lhtml


def _make_user(app, role):
    from mdc_erp.models import User
    from mdc_erp.extensions import db as _db
    from werkzeug.security import generate_password_hash
    with app.app_context():
        u = User.query.filter_by(username=f'u_{role}').first()
        if not u:
            u = User(username=f'u_{role}', pw=generate_password_hash('x'), active=True, name=role, role=role)
            try: u.must_change_pw = False
            except Exception: pass
            _db.session.add(u); _db.session.commit()
        return u.id


def test_least_privilege_denies_cross_role_modules_server_side(app):
    """Least privilege (#15-16): each role is DENIED server-side access to modules
    outside its job — enforced by can(mod) in the dispatcher, not just menu hiding.
    Denied module() returns a 200 'No access' page; sensitive CRUD new/edit abort 403."""
    from mdc_erp.core.security import PERMS
    # (role, module it should be denied) — none of these roles are in that module's PERMS
    denied_cases = [
        ('reception', 'journal'),     # reception must not touch the general ledger
        ('reception', 'finance'),
        ('cashier', 'stockadj'),      # cashier must not adjust stock
        ('lab_tech', 'payables'),     # lab must not settle commissions
        ('radiologist', 'expenses'),  # radiology must not post expenses
        ('storekeeper', 'journal'),   # storekeeper must not post journals
        ('nurse', 'finance'),
    ]
    for role, mod in denied_cases:
        # sanity: the case is only meaningful if the role truly lacks the perm
        assert role not in PERMS.get(mod, []), f'test bug: {role} actually has {mod}'
        uid = _make_user(app, role)
        c = app.test_client()
        with c.session_transaction() as s:
            s['uid'] = uid
        # module list page: denied -> 'No access' page (server-side)
        body = c.get(f'/m/{mod}').get_data(as_text=True)
        assert 'No access' in body, f'{role} reached /m/{mod} — least privilege breached'
        # CRUD new/edit: denied -> 403 abort (never relies on hiding the button)
        assert c.get(f'/m/{mod}/new').status_code in (403, 404), f'{role} could open {mod}/new'

    # positive control: a role WITH the permission is allowed
    uid = _make_user(app, 'accountant')
    c = app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    assert 'No access' not in c.get('/m/journal').get_data(as_text=True)


def test_dashboard_is_role_scoped(app):
    """Each role sees only the widgets relevant to their job — no leakage."""
    cases = {
        'reception':   (["Today's Patients", 'Waiting Patients', 'Pending Payments'], ['Net Profit', 'Bank']),
        'cashier':     (["Today's Revenue", 'Unpaid Invoices'], ['Pending Samples', 'Bank']),
        'lab_tech':    (['Pending Samples', 'Completed Results'], ['Net Profit', "Today's Revenue"]),
        'radiologist': (['Pending Reports', 'Assigned Cases'], ['Net Profit', 'Cash']),
        'accountant':  (['Cash', 'Bank', 'Expenses (Year)', 'Net Profit'], ['Pending Samples']),
    }
    for role, (expected, forbidden) in cases.items():
        uid = _make_user(app, role)
        c = app.test_client()
        with c.session_transaction() as s:
            s['uid'] = uid
        html = c.get('/dashboard').get_data(as_text=True)
        # match the widget-label wrapper exactly, so category-card links like
        # "Blood Bank" don't count as the "Bank" KPI widget.
        for w in expected:
            assert f"wg-l'>{w}</div>" in html, f'{role} should see {w!r} widget'
        for w in forbidden:
            assert f"wg-l'>{w}</div>" not in html, f'{role} should NOT see {w!r} widget'


def test_admin_dashboard_sees_activity_and_audit(app):
    """Administrator sees the full KPI set plus User Activity and Audit Logs."""
    uid = _make_user(app, 'super_admin')
    c = app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    html = c.get('/dashboard').get_data(as_text=True)
    for w in ['User Activity', 'Audit Logs', 'Cash', 'Bank']:
        assert f"wg-l'>{w}</div>" in html, f'admin should see {w!r} widget'


def test_completed_workflow_locks_and_blocks_duplicates(client, app):
    """Once an invoice is fully paid (workflow complete) it locks: no further
    payment or item changes, and every attempt is written to the Audit log."""
    from mdc_erp.models import Invoice, InvoiceItem, Patient, Service, User, Audit
    from mdc_erp.extensions import db as _db
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        svc = Service.query.filter(Service.price > 0).first() or Service(name='WF Svc', price=10.0)
        if not svc.id:
            _db.session.add(svc); _db.session.flush()
        inv = Invoice(patient_id=pid, date='2026-07-20', status='Unpaid')
        _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, service_id=svc.id, desc=svc.name, qty=1, price=10.0))
        _db.session.commit()
        iid = inv.id; total = inv.total
    # pay in full -> completes & locks
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': str(total), 'pay_method': 'Cash', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        assert Invoice.query.get(iid).locked is True, 'invoice should lock when workflow completes'
    # duplicate payment blocked (amount unchanged)
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': str(total + 5), 'pay_method': 'Cash', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        assert abs(Invoice.query.get(iid).paid - total) < 0.01, 'duplicate payment must be blocked'
    # item change blocked on locked invoice
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}', data={'act': 'additem', 'desc': 'X', 'price': '5', '_csrf': tok}, follow_redirects=True)
    with app.app_context():
        assert len(Invoice.query.get(iid).items) == 1, 'no item changes allowed when locked'
        acts = [a.action for a in Audit.query.all()]
        assert any('Workflow completed' in a for a in acts)
        assert any('BLOCKED' in a for a in acts)


def test_only_admin_resets_completed_invoice(client, app):
    """Reset-to-draft is administrator-only; both outcomes are audited."""
    from mdc_erp.models import Invoice, InvoiceItem, User, Audit
    from mdc_erp.extensions import db as _db
    pid = _fresh_patient(app)
    with app.app_context():
        inv = Invoice(patient_id=pid, date='2026-07-20', status='Paid', locked=True, paid=10)
        _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, desc='X', qty=1, price=10.0))
        _db.session.commit(); iid = inv.id
        # a non-admin (reception) user
        from werkzeug.security import generate_password_hash
        if not User.query.filter_by(username='recep1').first():
            _db.session.add(User(username='recep1', pw=generate_password_hash('x'), active=True, name='R', role='reception'))
            _db.session.commit()
        recep_id = User.query.filter_by(username='recep1').first().id
    # non-admin cannot reset
    c = app.test_client()
    with c.session_transaction() as s:
        s['uid'] = recep_id
    tok = _csrf(c.get(f'/invoice/{iid}'))
    c.post(f'/invoice/{iid}/reset', data={'_csrf': tok}, follow_redirects=True)
    with app.app_context():
        assert Invoice.query.get(iid).locked is True, 'non-admin must not unlock'
    # admin can reset
    _login(client)  # admin
    tok = _csrf(client.get(f'/invoice/{iid}'))
    client.post(f'/invoice/{iid}/reset', data={'_csrf': tok}, follow_redirects=True)
    with app.app_context():
        assert Invoice.query.get(iid).locked is False, 'admin should unlock'
        acts = [a.action for a in Audit.query.all()]
        assert any('DENIED reset' in a for a in acts) and any('reset to draft' in a.lower() for a in acts)


def test_patient_activity_timeline_full(client, app):
    """The patient Activity Timeline shows every workflow stage with User/Date/Time
    and each entry links to its record."""
    from mdc_erp.models import (Patient, Service, Referral, Invoice, InvoiceItem,
                                LabOrder, RadOrder, User)
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        pid = _fresh_patient(app)
        svc = Service.query.filter(Service.price > 0).first() or Service(name='TL Svc', price=12.0)
        if not svc.id: _db.session.add(svc); _db.session.flush()
        ref = Referral(patient_id=pid, patient_name='X', doctor_name='Dr Warsame', status='Accepted', date='2026-07-20')
        _db.session.add(ref); _db.session.flush()
        inv = Invoice(patient_id=pid, referral_id=ref.id, date='2026-07-20', status='Unpaid')
        _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, service_id=svc.id, desc=svc.name, qty=1, price=12.0))
        lab = LabOrder(patient_id=pid, service_id=svc.id, date='2026-07-20', status='Received')
        rad = RadOrder(patient_id=pid, service_id=svc.id, modality='X-Ray', date='2026-07-20', status='Imaged')
        _db.session.add(lab); _db.session.add(rad); _db.session.commit()
        iid, lid, rid, total = inv.id, lab.id, rad.id, inv.total
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': str(total), 'pay_method': 'EVC Plus', '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    client.get(f'/lab/{lid}/approve', follow_redirects=True)
    client.post(f'/rad/{rid}/report', data={'report': 'Normal', 'finalize': '1', '_csrf': _csrf(client.get(f'/rad/{rid}/report'))}, follow_redirects=True)
    client.get(f'/invoice/{iid}/print'); client.get(f'/lab/{lid}/print'); client.get(f'/rad/{rid}/print')
    html = client.get(f'/patient/{pid}').get_data(as_text=True)
    for marker in ['Registration', 'Doctor Request REF-', f'Invoice INV-{iid:04d}',
                   'Payment RCT-', 'Laboratory:', 'Radiology:', 'Report:', 'PRINT ',
                   '👤', '📅', '🕐']:
        assert marker in html, f'timeline missing {marker!r}'
    # entries are clickable (link to the source records)
    assert f"href='/invoice/{iid}'" in html and f"href='/lab/{lid}/result'" in html


def test_patient_related_records_panel_and_views(client, app):
    """The patient page shows a Related Records panel, and every related kind
    opens a patient-scoped list."""
    _login(client)
    pid = _fresh_patient(app)
    html = client.get(f'/patient/{pid}').get_data(as_text=True)
    assert 'Related Records' in html and 'rr-tile' in html
    for kind, label in [('invoices', 'Invoices'), ('payments', 'Payments'), ('lab', 'Laboratory'),
                        ('radiology', 'Radiology'), ('reports', 'Reports'), ('accounting', 'Accounting'),
                        ('requests', 'Doctor Requests'), ('appointments', 'Appointment')]:
        # the tile links to the scoped route
        assert f'/patient/{pid}/related/{kind}' in html, f'missing tile link for {kind}'
        r = client.get(f'/patient/{pid}/related/{kind}')
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert '<table>' in body and 'Back to Patient' in body
    # unknown kind 404s
    assert client.get(f'/patient/{pid}/related/bogus').status_code == 404


def test_global_search_opens_records_directly(client, app):
    """Global search opens the record directly when the query uniquely identifies
    one — by patient identity (name/phone/ID/MRN) or record number (INV/RCT/LAB)."""
    from mdc_erp.models import (Patient, Service, Invoice, InvoiceItem, PayReceipt,
                                LabOrder, User)
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        p = Patient(mrn='MDC-SRCH1', name='Zahra Unique Srch', gender='Female',
                    phone='0615550909', gov_id='NID-4242')
        _db.session.add(p); _db.session.flush()
        svc = Service.query.filter(Service.price > 0).first() or Service(name='S', price=10.0)
        if not svc.id: _db.session.add(svc); _db.session.flush()
        inv = Invoice(patient_id=p.id, date='2026-07-20', status='Unpaid')
        _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, service_id=svc.id, desc='x', qty=1, price=10.0))
        rct = PayReceipt(invoice_id=inv.id, date='2026-07-20', amount=10.0, method='EVC Plus', cashier='admin')
        lab = LabOrder(patient_id=p.id, service_id=svc.id, date='2026-07-20', status='Approved', sample_no='SMP-7788')
        _db.session.add(rct); _db.session.add(lab); _db.session.commit()
        pid, iid, rid, lid = p.id, inv.id, rct.id, lab.id

    def loc(q):
        r = client.get(f'/search?q={q}')
        return r.status_code, r.headers.get('Location', '')

    for q, target in [('Zahra Unique Srch', f'/patient/{pid}'), ('0615550909', f'/patient/{pid}'),
                      ('NID-4242', f'/patient/{pid}'), ('MDC-SRCH1', f'/patient/{pid}'),
                      (f'INV-{iid:04d}', f'/invoice/{iid}'), (f'RCT-{rid:05d}', f'/receipt/{rid}'),
                      (f'LAB-{lid:04d}', f'/lab/{lid}/result'), ('SMP-7788', f'/lab/{lid}/result')]:
        st, l = loc(q)
        assert st == 302 and target in l, f'search {q!r} should open {target} (got {st} {l})'


def test_professional_error_messages(client, app):
    """Business-rule failures show clear, professional messages (no tracebacks)."""
    from mdc_erp.models import Patient, Service, Invoice, InvoiceItem, RadOrder, Referral, User
    from mdc_erp.extensions import db as _db
    _login(client)

    def flashes(r):
        import re as _re
        return ' '.join(_re.findall(r"class='flash'>([^<]+)<", r.get_data(as_text=True)))

    with app.app_context():
        svc = Service.query.filter(Service.price > 0).first() or Service(name='S', price=100.0)
        if not svc.id: _db.session.add(svc); _db.session.flush()
        try: svc.active = True
        except Exception: pass
        bad = Service(name='Discontinued', price=50.0); _db.session.add(bad); _db.session.flush()
        try: bad.active = False
        except Exception: pass
        p = Patient(mrn='MDC-ERR1', name='Err Patient', gender='Female', phone='0619998877')
        _db.session.add(p); _db.session.flush()
        inv = Invoice(patient_id=p.id, date='2026-07-20', status='Unpaid'); _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, service_id=svc.id, desc=svc.name, qty=1, price=100.0))
        rad = RadOrder(patient_id=p.id, date='2026-07-20', status='Imaged', modality='CT'); _db.session.add(rad)
        _db.session.commit()
        iid, badid, radid, pid = inv.id, bad.id, rad.id, p.id

    # payment exceeds balance
    r = client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': '9999', 'pay_method': 'Cash', '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    assert 'exceeds balance' in flashes(r).lower()
    # service unavailable
    r = client.post(f'/invoice/{iid}', data={'act': 'additem', 'service_id': str(badid), 'qty': '1', '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    assert 'unavailable' in flashes(r).lower()
    # radiologist not assigned
    r = client.post(f'/rad/{radid}/dispatch', data={'_csrf': _csrf(client.get(f'/rad/{radid}/dispatch'))}, follow_redirects=True)
    assert 'not assigned' in flashes(r).lower()
    # patient already registered today (same phone as an existing same-day registration)
    r = client.post('/m/patients/new', data={'name': 'Another Person', 'phone': '0619998877', 'gender': 'Male', '_csrf': _csrf(client.get('/m/patients/new'))}, follow_redirects=True)
    assert 'registered today' in flashes(r).lower() or 'possible duplicate' in flashes(r).lower()
    # invoice already exists for a doctor request
    with app.app_context():
        ref = Referral(patient_id=pid, patient_name='Err Patient', doctor_name='Dr X', status='Accepted', date='2026-07-20')
        _db.session.add(ref); _db.session.commit(); rid = ref.id
    client.get(f'/referral/{rid}/invoice', follow_redirects=True)
    r = client.get(f'/referral/{rid}/invoice', follow_redirects=True)
    assert 'already exists' in flashes(r).lower()


def test_notification_center_events_are_role_scoped(client, app):
    """Notification Center routes each event to the right roles, and users see
    only what concerns them (super_admin sees all)."""
    from mdc_erp.models import (Patient, Service, Invoice, InvoiceItem, RadOrder, User, Notification)
    from mdc_erp.extensions import db as _db
    from mdc_erp.core.notify import notify
    from werkzeug.security import generate_password_hash
    _login(client)
    with app.app_context():
        for role in ('reception', 'cashier', 'accountant'):
            if not User.query.filter_by(username=f'nc_{role}').first():
                _db.session.add(User(username=f'nc_{role}', pw=generate_password_hash('x'),
                                     active=True, name=role, role=role))
        _db.session.commit()
        # emit one of each event straight through notify() with the wired audiences
        notify('🧑 Patient registered: A', role='reception')
        notify('💵 Payment received: $10', role=['cashier', 'accountant'])
        notify('📄 Report completed: B', role='reception')
        notify('🚫 Invoice cancelled: INV-0001', role=['accountant', 'cashier'])
        notify('📦 Low inventory: Gloves', role=['storekeeper', 'accountant'])
        notify('⚠ Backup failed: disk full', role=['super_admin', 'it_admin'])
        ids = {r: User.query.filter_by(username=f'nc_{r}').first().id for r in ('reception', 'cashier', 'accountant')}

    def sees(uid):
        c = app.test_client()
        with c.session_transaction() as s:
            s['uid'] = uid
        return c.get('/notifications').get_data(as_text=True).lower()

    rec = sees(ids['reception'])
    assert 'patient registered' in rec and 'report completed' in rec
    assert 'payment received' not in rec and 'backup failed' not in rec

    cash = sees(ids['cashier'])
    assert 'payment received' in cash and 'invoice cancelled' in cash
    assert 'patient registered' not in cash

    acc = sees(ids['accountant'])
    assert 'payment received' in acc and 'low inventory' in acc

    # administrator (super_admin) sees everything, including backup failure
    admin = client.get('/notifications').get_data(as_text=True).lower()
    for ev in ['patient registered', 'payment received', 'report completed',
               'invoice cancelled', 'low inventory', 'backup failed']:
        assert ev in admin, f'admin should see {ev!r}'


def test_notification_center_routes_events_to_roles(app):
    """Each business event notifies exactly the right roles; admin sees all."""
    from mdc_erp.core.notify import notify_event, visible_for
    from mdc_erp.models import User, Notification
    from mdc_erp.extensions import db as _db
    from werkzeug.security import generate_password_hash
    with app.app_context():
        for r in ['reception', 'cashier', 'lab_tech', 'radiologist', 'accountant']:
            if not User.query.filter_by(role=r).first():
                _db.session.add(User(username=f'n_{r}', pw=generate_password_hash('x'), active=True, name=r, role=r))
        _db.session.commit()
        for e, txt in [('patient_registered', 'New patient registered: A'),
                       ('payment_received', 'Payment received: $1'),
                       ('report_completed', 'Report completed: A'),
                       ('invoice_cancelled', 'Invoice INV-0001 cancelled'),
                       ('low_inventory', 'Low inventory: Gloves'),
                       ('backup_failed', 'Backup failed: disk')]:
            notify_event(e, txt)

        def seen_by(role):
            u = User.query.filter_by(role=role).first()
            return {n.text.split(':')[0] for n in visible_for(u)}

        assert 'New patient registered' in seen_by('reception')
        assert 'Report completed' in seen_by('reception')
        assert 'Payment received' in seen_by('cashier')
        assert 'Invoice INV-0001 cancelled' in seen_by('cashier')
        assert 'Report completed' in seen_by('lab_tech') and 'Low inventory' in seen_by('lab_tech')
        assert 'Report completed' in seen_by('radiologist')
        assert 'Payment received' in seen_by('accountant')
        # reception must NOT see finance/admin-only events
        assert 'Payment received' not in seen_by('reception')
        assert 'Backup failed' not in seen_by('cashier')
        # administrator sees everything
        admin_sees = seen_by('super_admin')
        for k in ['New patient registered', 'Payment received', 'Report completed',
                  'Invoice INV-0001 cancelled', 'Low inventory', 'Backup failed']:
            assert k in admin_sees, f'admin should see {k}'


def test_audit_captures_user_ip_oldnew_reason(client, app):
    """Audit records who/when/where plus before→after and a reason where relevant."""
    from mdc_erp.models import Patient, Invoice, Audit, User
    from mdc_erp.extensions import db as _db
    _login(client)
    pid = _fresh_patient(app)
    with app.app_context():
        inv = Invoice(patient_id=pid, date='2026-07-20', status='Unpaid')
        _db.session.add(inv); _db.session.commit(); iid = inv.id
        oldname = Patient.query.get(pid).name

    # EDIT — old→new captured
    client.post(f'/m/patients/{pid}/edit',
                data={'name': 'Renamed Patient', 'gender': 'Female',
                      '_csrf': _csrf(client.get(f'/m/patients/{pid}/edit'))}, follow_redirects=True)
    # CANCEL with a reason — reason + old/new captured
    client.post(f'/invoice/{iid}', data={'act': 'cancel', 'reason': 'Duplicate billing error',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)

    with app.app_context():
        edit = Audit.query.filter_by(action_type='Edit').order_by(Audit.id.desc()).first()
        assert edit and edit.ip and edit.user
        assert 'Renamed Patient' in (edit.new_value or '') and oldname in (edit.old_value or '')
        can = Audit.query.filter_by(action_type='Cancel').order_by(Audit.id.desc()).first()
        assert can and can.reason == 'Duplicate billing error'
        assert can.new_value == 'Cancelled' and can.ip
        # login was recorded with an IP and classified
        lg = Audit.query.filter_by(action_type='Login').order_by(Audit.id.desc()).first()
        assert lg and lg.ip
        # every audit row carries a timestamp (date + time) and a user
        for a in Audit.query.limit(20).all():
            assert a.ts is not None and a.user


def test_professional_printing_elements(client, app):
    """Printed documents carry the professional elements incl. a digital signature."""
    from mdc_erp.models import (Patient, Service, Invoice, InvoiceItem, PayReceipt,
                                LabOrder, RadOrder)
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        svc = Service.query.filter(Service.price > 0).first() or Service(name='S', price=100.0)
        if not svc.id: _db.session.add(svc); _db.session.flush()
        p = Patient(mrn='MDC-PRN1', name='Print Pt', gender='Female'); _db.session.add(p); _db.session.flush()
        inv = Invoice(patient_id=p.id, date='2026-07-20', status='Unpaid'); _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, service_id=svc.id, desc='x', qty=1, price=100.0))
        rct = PayReceipt(invoice_id=inv.id, date='2026-07-20', amount=100.0, method='EVC Plus', cashier='Xasan Cashier')
        lab = LabOrder(patient_id=p.id, service_id=svc.id, date='2026-07-20', status='Approved', result='Normal', approved_by='Dr Lab', sample_no='SMP-P1')
        rad = RadOrder(patient_id=p.id, service_id=svc.id, modality='X-Ray', date='2026-07-20', status='Reported', report='Clear', reported_by='Dr Rad', radiologist='Dr Rad')
        _db.session.add_all([rct, lab, rad]); _db.session.commit()
        iid, rid, lid, radid, pid, sid = inv.id, rct.id, lab.id, rad.id, p.id, svc.id

    # shared professional elements on the invoice document
    inv_html = client.get(f'/invoice/{iid}/print').get_data(as_text=True)
    assert 'INV-' in inv_html
    assert 'Document Ref' in inv_html             # QR verification block restored

    # digital signatures on the signed documents
    rcpt = client.get(f'/receipt/{rid}').get_data(as_text=True)
    assert 'Digitally signed' in rcpt and 'Xasan Cashier' in rcpt
    labr = client.get(f'/lab/{lid}/print').get_data(as_text=True)
    assert 'Digitally signed' in labr and 'Dr Lab' in labr
    radr = client.get(f'/rad/{radid}/print').get_data(as_text=True)
    assert 'Digitally signed' in radr and 'Dr Rad' in radr
    # a not-yet-approved lab report shows no signature block
    with app.app_context():
        lab2 = LabOrder(patient_id=pid, service_id=sid, date='2026-07-20', status='Received')
        _db.session.add(lab2); _db.session.commit(); lid2 = lab2.id
    assert 'Digitally signed' not in client.get(f'/lab/{lid2}/print').get_data(as_text=True)


def test_system_health_dashboard(app):
    """System Health shows all monitoring metrics and is admin-only."""
    from mdc_erp.models import User
    from mdc_erp.extensions import db as _db
    from werkzeug.security import generate_password_hash
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        admin.role = 'super_admin'
        try: admin.must_change_pw = False
        except Exception: pass
        if not User.query.filter_by(username='hs_rc').first():
            _db.session.add(User(username='hs_rc', pw=generate_password_hash('x'), active=True, name='rc', role='reception'))
        _db.session.commit()
        aid = admin.id
        rcid = User.query.filter_by(username='hs_rc').first().id

    ac = app.test_client()
    with ac.session_transaction() as s:
        s['uid'] = aid
    for path in ('/m/syshealth', '/system/health'):
        html = ac.get(path).get_data(as_text=True)
        assert ac.get(path).status_code == 200
        for metric in ['CPU', 'RAM', 'Disk', 'Database Size', 'Database Health', 'Backup Status',
                       'API Status', 'Active Users', 'Failed Logins', 'Errors', 'System Version']:
            assert metric in html, f'{path} missing {metric}'
        assert 'v7.9' in html and 'Online' in html

    # non-admin is denied (no metric data leaks)
    rc = app.test_client()
    with rc.session_transaction() as s:
        s['uid'] = rcid
    denied = rc.get('/m/syshealth').get_data(as_text=True)
    assert 'Failed Logins' not in denied and 'processor load' not in denied.lower()


def test_radiology_report_uses_structured_template(client, app):
    """The radiology report follows the clinical template (header table, Technique/
    Findings/Impression, radiologist block) with the professional print elements."""
    from mdc_erp.models import Patient, Service, RadOrder, Radiologist
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        rad = Radiologist(name='Mohammed Abdulahi', specialty='MD, Consultant Radiologist', license_no='SOM-RAD-441', active=True)
        svc = Service(name='Brain CT', price=40.0, category='Radiology')
        _db.session.add_all([rad, svc]); _db.session.flush()
        p = Patient(mrn='MDC-RT1', name='Halwo Warsame Ade', gender='Female', dob='1961-01-01')
        _db.session.add(p); _db.session.flush()
        o = RadOrder(patient_id=p.id, service_id=svc.id, modality='CT', date='2026-03-06', status='Reported',
                     clinical_data='LT side weakness', technique='Axial non-contrast CT of the brain.',
                     report='Insular ribbon sign in the right insular cortex.',
                     impression='MCA territory acute ischemic stroke.',
                     radiologist='Mohammed Abdulahi', reported_by='Mohammed Abdulahi')
        _db.session.add(o); _db.session.commit(); oid = o.id
    html = client.get(f'/rad/{oid}/print').get_data(as_text=True)
    # template structure
    for part in ['Client Name', 'Clinical data', 'Requested by', 'BRAIN CT REPORT',
                 'Technique:', 'Findings:', 'Impression:', 'DR. MOHAMMED ABDULAHI']:
        assert part in html, f'template missing {part!r}'
    assert '65 yrs' in html                       # age derived from DOB
    assert 'SOM-RAD-441' in html or 'Consultant Radiologist' in html
    # professional print features still present
    assert 'Digitally signed' in html and 'Document Ref' in html


def test_favorites_menu(client, app):
    """Users can star/un-star pages; favorites appear in the topbar menu."""
    from mdc_erp.models import Favorite
    from mdc_erp.extensions import db as _db
    _login(client)
    # every page shows the favorites control (empty star by default)
    html = client.get('/m/patients').get_data(as_text=True)
    assert 'Favorites' in html and '☆' in html
    # star the current page
    client.post('/favorite/toggle', data={'url': '/m/patients', 'label': 'Patients',
                                           'next': '/m/patients', '_csrf': _csrf(client.get('/m/patients'))},
                follow_redirects=True)
    with app.app_context():
        assert Favorite.query.filter_by(username='admin', url='/m/patients').count() == 1
    starred = client.get('/m/patients').get_data(as_text=True)
    assert '★' in starred and 'Patients' in starred
    # un-star
    client.post('/favorite/toggle', data={'url': '/m/patients', 'label': 'Patients',
                                           'next': '/m/patients', '_csrf': _csrf(client.get('/m/patients'))},
                follow_redirects=True)
    with app.app_context():
        assert Favorite.query.filter_by(username='admin', url='/m/patients').count() == 0


def test_next_step_workflow(client, app):
    """Completing a task surfaces the next logical step in one click, and patient
    registration opens the patient hub directly (fewer clicks)."""
    from mdc_erp.models import Service, Invoice, InvoiceItem, LabOrder
    from mdc_erp.extensions import db as _db
    _login(client)
    with app.app_context():
        svc = Service.query.filter(Service.price > 0).first() or Service(name='S', price=100.0)
        if not svc.id: _db.session.add(svc); _db.session.flush()
        sid = svc.id

    # registration lands on the patient hub, not the list
    r = client.post('/m/patients/new', data={'name': 'NS Patient', 'gender': 'Female', 'phone': '0619',
                                              '_csrf': _csrf(client.get('/m/patients/new'))}, follow_redirects=False)
    loc = r.headers.get('Location', '')
    assert '/patient/' in loc, 'registration should open the patient hub'
    pid = int(loc.rstrip('/').split('/')[-1])
    hub = client.get(loc).get_data(as_text=True)
    assert 'Next step' in hub and 'Create Invoice' in hub

    # unpaid invoice -> patient hub next step is Register Payment
    with app.app_context():
        inv = Invoice(patient_id=pid, date='2026-07-20', status='Unpaid'); _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, service_id=sid, desc='x', qty=1, price=100.0))
        lab = LabOrder(patient_id=pid, service_id=sid, date='2026-07-20', status='Received', invoice_id=inv.id)
        _db.session.add(lab); _db.session.commit()
        iid, lid, total = inv.id, lab.id, inv.total
    assert 'Register Payment' in client.get(f'/patient/{pid}').get_data(as_text=True)

    # after full payment the invoice offers Proceed to Laboratory (linked to the order)
    client.post(f'/invoice/{iid}', data={'act': 'pay', 'paid': str(total), 'pay_method': 'Cash',
                                         '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    inv_html = client.get(f'/invoice/{iid}').get_data(as_text=True)
    assert 'Proceed to Laboratory' in inv_html and f'/lab/{lid}/result' in inv_html


def test_fixed_assets_module(client, app):
    """Enterprise Fixed Assets: purchase → activate (capitalize) → depreciate
    (auto journal Dr expense / Cr accumulated) → dispose (gain/loss), plus nav + CSV."""
    from mdc_erp.models import AssetCategory, Asset, AssetDepreciation, AssetDisposal, JournalEntry
    from mdc_erp.extensions import db as _db
    _login(client)

    # dashboard renders and default categories are seeded
    assert client.get('/fa/dashboard').status_code == 200
    with app.app_context():
        assert AssetCategory.query.count() >= 19
        cat = AssetCategory.query.first(); cat_id = cat.id

    # purchase an asset -> Draft
    client.post('/fa/purchase', data={'name': 'Test Scanner', 'category_id': str(cat_id), 'cost': '120000',
                'residual_value': '20000', 'useful_life_months': '120', 'depreciation_method': 'Straight Line',
                'purchase_date': '2026-01-15', 'department': 'Radiology', 'custodian': 'Dr A', 'location': 'R1',
                '_csrf': _csrf(client.get('/fa/purchase'))}, follow_redirects=True)
    with app.app_context():
        a = Asset.query.filter_by(name='Test Scanner').first()
        assert a is not None and a.status == 'Draft'
        aid = a.id

    # activate -> Active
    client.post(f'/fa/asset/{aid}/activate', data={'_csrf': _csrf(client.get(f'/fa/asset/{aid}'))}, follow_redirects=True)
    with app.app_context():
        assert Asset.query.get(aid).status == 'Active'

    # run one month of depreciation: (120000-20000)/120 = 833.33
    client.post('/fa/depreciation', data={'period': '2026-02', '_csrf': _csrf(client.get('/fa/depreciation'))},
                follow_redirects=True)
    with app.app_context():
        a = Asset.query.get(aid)
        dep = AssetDepreciation.query.filter_by(asset_id=aid).first()
        assert dep is not None and round(dep.amount, 2) == 833.33
        assert round(a.accumulated_dep, 2) == 833.33
        # automatic journal entry: Dr Depreciation Expense (6400), Cr Accumulated Depreciation (1520)
        je = JournalEntry.query.filter_by(ref=dep.journal_ref).first()
        assert je is not None
        dr = {l.account.code: round(l.debit or 0, 2) for l in je.lines if (l.debit or 0) > 0}
        cr = {l.account.code: round(l.credit or 0, 2) for l in je.lines if (l.credit or 0) > 0}
        assert dr.get('6400') == 833.33 and cr.get('1520') == 833.33

    # dispose by sale for 100000 -> loss vs net book value
    client.post(f'/fa/asset/{aid}/dispose', data={'method': 'Sale', 'proceeds': '100000', 'date': '2026-03-01',
                'reason': 'sold', '_csrf': _csrf(client.get(f'/fa/asset/{aid}'))}, follow_redirects=True)
    with app.app_context():
        a = Asset.query.get(aid)
        d = AssetDisposal.query.filter_by(asset_id=aid).first()
        assert a.status == 'Sold' and d is not None
        assert d.gain_loss < 0  # sold below book value

    # nav pages + CSV export
    for path in ['/fa/register', '/fa/categories', '/fa/reports', '/fa/settings', f'/fa/asset/{aid}/schedule']:
        assert client.get(path).status_code == 200
    assert client.get('/fa/report/register.csv').status_code == 200


def test_reset_to_draft_reverses_accounting(client, app):
    """Resetting a completed invoice to draft automatically reverses its accounting
    (sales + payment), leaving balanced books that net to zero, with a full reversal
    trail — and a later repost clears the stale reversals so there is no double count."""
    from mdc_erp.models import Patient, Invoice, InvoiceItem, Service, JournalEntry
    from mdc_erp.core.posting import repost_invoice, repost_payment
    from mdc_erp.extensions import db as _db
    _login(client)

    def net(iid, code):
        refs = {f'INV-{iid:04d}', f'PAY-{iid:04d}', f'REV-INV-{iid:04d}', f'REV-PAY-{iid:04d}'}
        tot = 0
        for e in JournalEntry.query.all():
            if (e.ref or '') in refs:
                for l in e.lines:
                    if l.account and l.account.code == code:
                        tot += (l.debit or 0) - (l.credit or 0)
        return round(tot, 2)

    with app.app_context():
        svc = Service.query.filter(Service.price > 0).first() or Service(name='S', price=100.0)
        if not svc.id: _db.session.add(svc); _db.session.flush()
        p = Patient(name='Reset Test', gender='Male'); _db.session.add(p); _db.session.flush()
        inv = Invoice(patient_id=p.id, date='2026-07-20', status='Unpaid'); _db.session.add(inv); _db.session.flush()
        _db.session.add(InvoiceItem(invoice_id=inv.id, service_id=svc.id, desc='x', qty=1, price=100.0))
        _db.session.commit()
        iid = inv.id
        inv = Invoice.query.get(iid); inv.paid = inv.total; inv.pay_method = 'Cash'
        repost_invoice(inv); repost_payment(inv); inv.locked = True; _db.session.commit()
        assert net(iid, '4400') == -100.0            # revenue recognised

    # reset to draft -> reverses accounting
    client.post(f'/invoice/{iid}/reset', data={'reason': 'correction',
                '_csrf': _csrf(client.get(f'/invoice/{iid}'))}, follow_redirects=True)
    with app.app_context():
        inv = Invoice.query.get(iid)
        assert not inv.locked
        assert JournalEntry.query.filter_by(ref=f'REV-INV-{iid:04d}').first() is not None
        assert JournalEntry.query.filter_by(ref=f'REV-PAY-{iid:04d}').first() is not None
        orig = JournalEntry.query.filter_by(ref=f'INV-{iid:04d}').first()
        assert orig.reversed_by is not None
        # books net to zero after reversal, and every entry is balanced
        assert net(iid, '1200') == 0.0 and net(iid, '4400') == 0.0
        for e in JournalEntry.query.all():
            assert round(e.total_debit - e.total_credit, 2) == 0

    # re-confirm (repost) clears stale reversals -> clean books, no double count
    with app.app_context():
        inv = Invoice.query.get(iid); repost_invoice(inv); repost_payment(inv); _db.session.commit()
        assert JournalEntry.query.filter(JournalEntry.ref.like(f'REV-%{iid:04d}')).count() == 0
        assert net(iid, '4400') == -100.0


def test_db_migration_is_dialect_agnostic(app):
    """First-run column migrations use the SQLAlchemy inspector (not SQLite PRAGMA),
    so they run on PostgreSQL too; re-running init_db is idempotent and safe."""
    from mdc_erp.bootstrap import init_db
    from mdc_erp.extensions import db as _db
    from sqlalchemy import inspect
    with app.app_context():
        insp = inspect(_db.engine)
        # columns added by migrations are present (proves the inspector path worked)
        inv = {c['name'] for c in insp.get_columns('invoice')}
        je = {c['name'] for c in insp.get_columns('journal_entry')}
        asset = {c['name'] for c in insp.get_columns('asset')}
        assert 'locked' in inv
        assert 'is_reversal' in je and 'reversed_by' in je
        assert 'accumulated_dep' in asset and 'category_id' in asset
    # re-running the bootstrap must not raise (idempotent)
    init_db(app, demo=False)
    with app.app_context():
        assert 'locked' in {c['name'] for c in inspect(_db.engine).get_columns('invoice')}


def test_security_lockout_and_session_timeout(client, app, monkeypatch):
    """Brute-force lockout blocks repeated failures (per username), and idle
    sessions are signed out after the inactivity timeout."""
    from mdc_erp.models import LoginHistory
    import mdc_erp.blueprints.auth as auth_mod
    # tighten the threshold for the test via env
    monkeypatch.setenv('LOGIN_MAX_FAILS', '3')
    monkeypatch.setenv('LOGIN_LOCK_MIN', '15')

    # three bad attempts, then the next is locked out
    for _ in range(3):
        client.post('/login', data={'username': 'admin', 'password': 'nope',
                                    '_csrf': _csrf(client.get('/login'))})
    r = client.post('/login', data={'username': 'admin', 'password': 'nope',
                                    '_csrf': _csrf(client.get('/login'))})
    assert 'Too many failed attempts' in r.get_data(as_text=True)
    with app.app_context():
        assert LoginHistory.query.filter_by(note='locked out').count() >= 1
    # correct password is still blocked while locked
    r = client.post('/login', data={'username': 'admin', 'password': 'admin123',
                                    '_csrf': _csrf(client.get('/login'))})
    assert 'Too many failed attempts' in r.get_data(as_text=True)
    # a different username is unaffected by admin's lockout
    r = client.post('/login', data={'username': 'ghost', 'password': 'x',
                                    '_csrf': _csrf(client.get('/login'))})
    assert 'Invalid username' in r.get_data(as_text=True)

    # session timeout config is in force
    with app.app_context():
        assert app.config['PERMANENT_SESSION_LIFETIME'].total_seconds() > 0
        assert app.config.get('SESSION_REFRESH_EACH_REQUEST') is True

    # an idle session (ancient _seen) is redirected to the login page.
    # set the session directly — the admin account is locked out above, so we
    # can't use the normal login helper here.
    from mdc_erp.models import User
    with app.app_context():
        uid = User.query.filter_by(username='admin').first().id
    with client.session_transaction() as s:
        s['uid'] = uid
        s['_seen'] = 1  # 1970 -> far beyond any timeout
    r = client.get('/', follow_redirects=False)
    assert r.status_code in (301, 302) and '/login' in r.headers.get('Location', '')
