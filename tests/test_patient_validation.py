"""Automated tests for New Patient form required-field stars and mandatory validation."""
import re
import pytest
from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig
from mdc_erp.models import User, Patient
from mdc_erp.extensions import db as _db

@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'pat_val_test.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        u = User.query.filter_by(role='super_admin').first()
        if u:
            u.must_change_pw = False
            _db.session.commit()
    return app

def _login(c, app, role='super_admin'):
    with app.app_context():
        u = User.query.filter_by(role=role).first()
        uid = u.id if u else None
    if uid:
        with c.session_transaction() as s:
            s['uid'] = uid
    return c

def _get_csrf(c):
    r = c.get('/m/patients/new')
    html = r.get_data(as_text=True)
    m = re.search(r'name=["\']_csrf["\']\s+value=["\']([^"\']+)["\']', html) or re.search(r'value=["\']([^"\']+)["\']\s+name=["\']_csrf["\']', html)
    return m.group(1) if m else ''

def test_new_patient_form_renders_required_stars(app):
    c = app.test_client()
    _login(c, app, 'super_admin')
    res = c.get('/m/patients/new')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Verify red required stars on labels
    assert 'Full Name <span style="color:var(--amber-dk)">*</span>' in html
    assert 'Phone <span style="color:var(--amber-dk)">*</span>' in html
    assert 'Gender <span style="color:var(--amber-dk)">*</span>' in html
    assert 'Date of Birth (age auto-calculated) <span style="color:var(--amber-dk)">*</span>' in html
    assert 'Age (years) — use if date of birth is unknown <span style="color:var(--amber-dk)">*</span>' in html

    # Verify Blood Group is optional (does NOT have required star)
    assert 'Blood Group' in html
    assert 'Blood Group <span style="color:var(--amber-dk)">*</span>' not in html

def test_missing_required_fields_rejected(app):
    c = app.test_client()
    _login(c, app, 'super_admin')
    tok = _get_csrf(c)

    # Missing Phone
    res1 = c.post('/m/patients/new', data={
        'name': 'Valid Name', 'phone': '', 'gender': 'Male',
        'age_years': '25', 'blood_group': 'O+', '_csrf': tok
    }, follow_redirects=True)
    assert 'Validation Error' in res1.get_data(as_text=True)

    # Missing Gender
    res2 = c.post('/m/patients/new', data={
        'name': 'Valid Name', 'phone': '0612345678', 'gender': '',
        'age_years': '25', 'blood_group': 'O+', '_csrf': tok
    }, follow_redirects=True)
    assert 'Validation Error' in res2.get_data(as_text=True)

    # Missing both DOB and Age
    res3 = c.post('/m/patients/new', data={
        'name': 'Valid Name', 'phone': '0612345678', 'gender': 'Male',
        'dob': '', 'age_years': '', 'blood_group': 'O+', '_csrf': tok
    }, follow_redirects=True)
    assert 'Validation Error' in res3.get_data(as_text=True)

def test_missing_blood_group_succeeds(app):
    c = app.test_client()
    _login(c, app, 'super_admin')
    tok = _get_csrf(c)

    # Missing Blood Group should succeed now (optional field)
    res = c.post('/m/patients/new', data={
        'name': 'No BloodGroup Patient', 'phone': '0612345999', 'gender': 'Male',
        'age_years': '25', 'blood_group': '', '_csrf': tok
    }, follow_redirects=True)
    assert res.status_code == 200
    assert 'Validation Error' not in res.get_data(as_text=True)
    with app.app_context():
        p = Patient.query.filter_by(name='No BloodGroup Patient').first()
        assert p is not None

def test_dob_or_age_either_succeeds(app):
    c = app.test_client()
    _login(c, app, 'super_admin')

    # 1. DOB only (no age_years)
    tok1 = _get_csrf(c)
    res1 = c.post('/m/patients/new', data={
        'name': 'DOB Patient', 'phone': '0611111111', 'gender': 'Female',
        'dob': '1995-06-15', 'age_years': '', 'blood_group': 'A+', '_csrf': tok1
    }, follow_redirects=True)
    assert res1.status_code == 200
    with app.app_context():
        p1 = Patient.query.filter_by(name='DOB Patient').first()
        assert p1 is not None

    # 2. Age only (no dob)
    tok2 = _get_csrf(c)
    res2 = c.post('/m/patients/new', data={
        'name': 'Age Patient', 'phone': '0622222222', 'gender': 'Male',
        'dob': '', 'age_years': '40', 'blood_group': 'B+', '_csrf': tok2
    }, follow_redirects=True)
    assert res2.status_code == 200
    with app.app_context():
        p2 = Patient.query.filter_by(name='Age Patient').first()
        assert p2 is not None
