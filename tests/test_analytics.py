"""Advanced Analytics Dashboard (Phase 13, v8.0) tests. Self-contained."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'an.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.commit()
    return app


def _login(app, client, role='super_admin'):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role=role).first()
        if not u:
            return None
        u.must_change_pw = False
        db.session.commit()
        uid = u.id
    with client.session_transaction() as s:
        s['uid'] = uid
        s['_csrf'] = 'tok'
    return uid


def test_analytics_aggregates_across_modules(app):
    # seed a little data in several modules
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import (Patient, EDVisit, Admission, Ward, Bed, BloodUnit)
        p = Patient(name='An Pt', mrn='MRN-AN1', phone='0')
        db.session.add(p)
        db.session.commit()
        db.session.add(EDVisit(patient_id=p.id, status='Waiting', triage_level=2,
                               arrival_at='2026-08-02 09:00', chief_complaint='x'))
        w = Ward(name='W', active=True)
        db.session.add(w)
        db.session.commit()
        b = Bed(ward_id=w.id, label='B1', status='Occupied', active=True)
        db.session.add(b)
        db.session.commit()
        db.session.add(Admission(patient_id=p.id, ward_id=w.id, bed_id=b.id, status='Admitted'))
        db.session.add(BloodUnit(unit_no='U1', blood_group='O+', status='Available'))
        db.session.commit()

    client = app.test_client()
    _login(app, client)
    r = client.get('/m/analytics')
    assert r.status_code == 200
    # section headers + KPI labels + charts present
    for needle in (b'Financial', b'Clinical', b'ED active', b'Inpatients',
                   b'Blood units', b'Trends', b'<svg'):
        assert needle in r.data


def test_analytics_rbac_denies(app):
    client = app.test_client()
    # lab_tech is not in the analytics permission list
    if _login(app, client, role='lab_tech') is None:
        pytest.skip('no lab_tech role')
    r = client.get('/m/analytics')
    # centralized dispatch gate returns a friendly "No access" page, not the dashboard
    assert b'No access' in r.data and b'Collected today' not in r.data
