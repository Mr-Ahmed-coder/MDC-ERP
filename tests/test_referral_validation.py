"""Comprehensive Doctor Request Form Validation Tests. Self-contained."""
import pytest
from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig
from mdc_erp.models import User, Patient, Doctor, Service, Referral
from mdc_erp.extensions import db as _db


def _csrf(c, path='/referral/new'):
    r = c.get(path)
    tok = ''
    if r.status_code == 200:
        html = r.get_data(as_text=True)
        if 'name="_csrf"' in html:
            tok = html.split('name="_csrf" value="')[1].split('"')[0]
    return tok


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'val_ref.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        # Ensure super_admin and test records exist
        u = User.query.filter_by(role='super_admin').first()
        if u:
            u.must_change_pw = False
            _db.session.commit()
        if not Patient.query.first():
            _db.session.add(Patient(name='Test Patient', phone='0615555555', age=30, gender='Male'))
        if not Doctor.query.first():
            _db.session.add(Doctor(name='Dr. Registered', specialty='Cardiology', active=True))
        if not Service.query.first():
            _db.session.add(Service(name='CBC', department='Laboratory', price=30, active=True))
        _db.session.commit()
    return app


def _client(app, role='super_admin'):
    with app.app_context():
        u = User.query.filter_by(role=role).first()
        if not u and role == 'no_perm':
            u = User(username='noperm_user', role='restricted', must_change_pw=False)
            _db.session.add(u)
            _db.session.commit()
        uid = u.id if u else None
    c = app.test_client()
    if uid:
        with c.session_transaction() as s:
            s['uid'] = uid
    return c


def test_empty_submission_rejected(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        cnt_before = Referral.query.count()

    res = c.post('/refer', data={'_csrf': tok})
    assert res.status_code == 400
    html = res.get_data(as_text=True)
    assert '⚠️ Please fix the following errors' in html

    with app.app_context():
        assert Referral.query.count() == cnt_before


def test_whitespace_only_values_rejected(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        cnt_before = Referral.query.count()

    res = c.post('/refer', data={
        'doctor_id': '',
        'doctor_name': '   ',
        'hospital': '   ',
        'patient_name': '   ',
        'patient_phone': '   ',
        'patient_age': '   ',
        'patient_gender': '',
        'other_tests': '   ',
        'notes': '   ',
        '_csrf': tok,
    })
    assert res.status_code == 400
    with app.app_context():
        assert Referral.query.count() == cnt_before


def test_registered_doctor_path_succeeds(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        doc = Doctor.query.filter_by(active=True).first()
        did = doc.id
        cnt_before = Referral.query.count()

    res = c.post('/refer', data={
        'doctor_id': str(did),
        'patient_name': 'Valid Reg Patient',
        'patient_phone': '061999111',
        'patient_age': '28',
        'patient_gender': 'Male',
        'tests': ['CBC'],
        'notes': 'Reg doctor test notes',
        '_csrf': tok,
    }, follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        assert Referral.query.count() == cnt_before + 1
        ref = Referral.query.order_by(Referral.id.desc()).first()
        assert ref.doctor_id == did
        assert ref.patient_name == 'Valid Reg Patient'


def test_manual_doctor_without_name_rejected(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    res = c.post('/refer', data={
        'doctor_id': '',
        'doctor_name': '',
        'hospital': 'City Hospital',
        'patient_name': 'Test Pat',
        'patient_phone': '061111222',
        'patient_age': '22',
        'patient_gender': 'Female',
        'tests': ['CBC'],
        'notes': 'Some notes',
        '_csrf': tok,
    })
    assert res.status_code == 400
    assert "Doctor Name is required when 'Other' is selected" in res.get_data(as_text=True)


def test_manual_doctor_without_hospital_rejected(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    res = c.post('/refer', data={
        'doctor_id': '',
        'doctor_name': 'Dr. External',
        'hospital': '',
        'patient_name': 'Test Pat',
        'patient_phone': '061111222',
        'patient_age': '22',
        'patient_gender': 'Female',
        'tests': ['CBC'],
        'notes': 'Some notes',
        '_csrf': tok,
    })
    assert res.status_code == 400
    assert "Hospital / Clinic is required for external doctors" in res.get_data(as_text=True)


def test_existing_patient_path_succeeds(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        pat = Patient.query.first()
        pid = pat.id
        doc = Doctor.query.first()
        did = doc.id
        cnt_before = Referral.query.count()

    res = c.post('/refer', data={
        'doctor_id': str(did),
        'patient_id': str(pid),
        'tests': ['CBC'],
        'notes': 'Existing patient referral notes',
        '_csrf': tok,
    }, follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        assert Referral.query.count() == cnt_before + 1
        ref = Referral.query.order_by(Referral.id.desc()).first()
        assert ref.patient_id == pid


def test_manual_patient_missing_fields_rejected(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        did = Doctor.query.first().id

    # Missing name
    r1 = c.post('/refer', data={'doctor_id': str(did), 'patient_phone': '0611', 'patient_age': '25', 'patient_gender': 'Male', 'tests': ['CBC'], 'notes': 'N1', '_csrf': tok})
    assert r1.status_code == 400
    assert "Patient Name cannot be blank" in r1.get_data(as_text=True)

    # Missing phone
    r2 = c.post('/refer', data={'doctor_id': str(did), 'patient_name': 'Pat X', 'patient_age': '25', 'patient_gender': 'Male', 'tests': ['CBC'], 'notes': 'N2', '_csrf': tok})
    assert r2.status_code == 400
    assert "Phone number is required" in r2.get_data(as_text=True)

    # Missing age
    r3 = c.post('/refer', data={'doctor_id': str(did), 'patient_name': 'Pat X', 'patient_phone': '0611', 'patient_gender': 'Male', 'tests': ['CBC'], 'notes': 'N3', '_csrf': tok})
    assert r3.status_code == 400
    assert "Age is required" in r3.get_data(as_text=True)

    # Missing gender
    r4 = c.post('/refer', data={'doctor_id': str(did), 'patient_name': 'Pat X', 'patient_phone': '0611', 'patient_age': '25', 'patient_gender': '', 'tests': ['CBC'], 'notes': 'N4', '_csrf': tok})
    assert r4.status_code == 400
    assert "select a valid Gender" in r4.get_data(as_text=True)


def test_invalid_age_rejected(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        did = Doctor.query.first().id

    # Negative age
    r1 = c.post('/refer', data={'doctor_id': str(did), 'patient_name': 'Age Test', 'patient_phone': '0612', 'patient_age': '-5', 'patient_gender': 'Male', 'tests': ['CBC'], 'notes': 'N', '_csrf': tok})
    assert r1.status_code == 400
    assert "Age must be a valid non-negative number" in r1.get_data(as_text=True)

    # Out of range age (>150)
    r2 = c.post('/refer', data={'doctor_id': str(did), 'patient_name': 'Age Test', 'patient_phone': '0612', 'patient_age': '200', 'patient_gender': 'Male', 'tests': ['CBC'], 'notes': 'N', '_csrf': tok})
    assert r2.status_code == 400

    # Non-numeric age
    r3 = c.post('/refer', data={'doctor_id': str(did), 'patient_name': 'Age Test', 'patient_phone': '0612', 'patient_age': 'abc', 'patient_gender': 'Male', 'tests': ['CBC'], 'notes': 'N', '_csrf': tok})
    assert r3.status_code == 400


def test_no_selected_service_and_empty_other_tests_rejected(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        did = Doctor.query.first().id

    res = c.post('/refer', data={
        'doctor_id': str(did),
        'patient_name': 'Pat Tests',
        'patient_phone': '061222',
        'patient_age': '30',
        'patient_gender': 'Female',
        'other_tests': '   ',
        'notes': 'Notes',
        '_csrf': tok,
    })
    assert res.status_code == 400
    assert "At least one requested test/scan or 'Other tests' description is required" in res.get_data(as_text=True)


def test_other_tests_allows_submission_when_no_services_exist(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        Service.query.delete()
        _db.session.commit()
        did = Doctor.query.first().id
        cnt_before = Referral.query.count()

    res = c.post('/refer', data={
        'doctor_id': str(did),
        'patient_name': 'No Services Pat',
        'patient_phone': '061333',
        'patient_age': '45',
        'patient_gender': 'Male',
        'other_tests': 'MRI Brain Scan',
        'notes': 'Notes for MRI',
        '_csrf': tok,
    }, follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        assert Referral.query.count() == cnt_before + 1
        ref = Referral.query.order_by(Referral.id.desc()).first()
        assert 'MRI Brain Scan' in ref.tests


def test_empty_clinical_notes_rejected(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        did = Doctor.query.first().id

    res = c.post('/refer', data={
        'doctor_id': str(did),
        'patient_name': 'Pat Notes',
        'patient_phone': '061444',
        'patient_age': '50',
        'patient_gender': 'Male',
        'tests': ['CBC'],
        'notes': '   ',
        '_csrf': tok,
    })
    assert res.status_code == 400
    assert "Clinical Notes are required" in res.get_data(as_text=True)


def test_valid_complete_submission_succeeds_exactly_once(app):
    c = _client(app, 'super_admin')
    tok = _csrf(c)
    with app.app_context():
        did = Doctor.query.first().id
        cnt_before = Referral.query.count()

    res = c.post('/refer', data={
        'doctor_id': str(did),
        'patient_name': 'Complete Valid Pat',
        'patient_phone': '061555',
        'patient_age': '33',
        'patient_gender': 'Female',
        'tests': ['CBC'],
        'other_tests': 'X-Ray Chest',
        'notes': 'Complete validation test notes',
        '_csrf': tok,
    }, follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        assert Referral.query.count() == cnt_before + 1
        ref = Referral.query.order_by(Referral.id.desc()).first()
        assert ref.patient_name == 'Complete Valid Pat'
        assert 'CBC' in ref.tests and 'X-Ray Chest' in ref.tests


def test_unauthorized_user_rejected(app):
    # Log in as a user role without referral permissions (e.g. restricted)
    c = _client(app, 'no_perm')
    tok = _csrf(c)
    res = c.post('/refer', data={
        'doctor_name': 'Dr Ext',
        'hospital': 'Ext Hosp',
        'patient_name': 'Unauth Pat',
        'patient_phone': '061666',
        'patient_age': '30',
        'patient_gender': 'Male',
        'other_tests': 'CBC',
        'notes': 'Unauth test',
        '_csrf': tok,
    })
    assert res.status_code == 403


def test_csrf_remains_enforced(app):
    c = _client(app, 'super_admin')
    with app.app_context():
        did = Doctor.query.first().id

    res = c.post('/refer', data={
        'doctor_id': str(did),
        'patient_name': 'No CSRF Pat',
        'patient_phone': '061777',
        'patient_age': '30',
        'patient_gender': 'Male',
        'tests': ['CBC'],
        'notes': 'No CSRF notes',
    })
    # CSRF failure yields 400 or 403
    assert res.status_code in (400, 403)


def test_doctor_request_form_renders_required_star(app):
    c = _client(app, 'super_admin')
    res = c.get('/referral/new')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "<label>Select registered doctor <span style='color:var(--red)'>*</span></label>" in html or "<label>Select registered doctor <span style=\"color:var(--red)\">*</span></label>" in html
