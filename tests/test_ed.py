"""Emergency Department (Phase 7, v8.0) end-to-end tests. Self-contained."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'ed.db'}"
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


def _patient(app):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Patient
        p = Patient(name='ED Pt', mrn='MRN-ED1', phone='0')
        db.session.add(p)
        db.session.commit()
        return p.id


def test_ed_full_flow(app):
    client = app.test_client()
    _login(app, client)
    pid = _patient(app)
    D = {'_csrf': 'tok'}

    # register an emergency arrival (triage level 1 -> resuscitation)
    r = client.post('/ed/new', data={**D, 'patient_id': pid, 'triage_level': '1',
                                     'chief_complaint': 'Chest pain', 'mode': 'Ambulance',
                                     'bp': '90/60', 'pulse': '120', 'spo2': '90'},
                    follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.models import EDVisit
        v = EDVisit.query.first()
        assert v.triage_level == 1 and v.status == 'Waiting' and v.chief_complaint == 'Chest pain'
        vid = v.id

    # board shows the active visit
    b = client.get('/m/ed')
    assert b.status_code == 200 and b'Chest pain' in b.data and b'Resuscitation' in b.data

    # start treatment
    client.get(f'/ed/{vid}/act/treat')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import EDVisit
        assert db.session.get(EDVisit, vid).status == 'InTreatment'

    # serial vitals + note
    client.post(f'/ed/{vid}/vitals', data={**D, 'bp': '100/70', 'pulse': '98', 'spo2': '96'})
    client.post(f'/ed/{vid}/note', data={**D, 'category': 'Doctor', 'text': 'ECG done, ASA given'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import EDVisit
        v = db.session.get(EDVisit, vid)
        assert len(v.vitals) == 1 and len(v.notes) == 1

    # emergency billing creates & links an invoice
    r = client.get(f'/ed/{vid}/bill', follow_redirects=False)
    assert r.status_code == 302 and '/invoice/' in r.headers['Location'] or 'inv' in r.headers['Location'].lower()
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import EDVisit, Invoice
        v = db.session.get(EDVisit, vid)
        assert v.invoice_id and db.session.get(Invoice, v.invoice_id) is not None

    # disposition -> admit
    r = client.post(f'/ed/{vid}/disposition', data={**D, 'disposition': 'Admit', 'note': 'to CCU'})
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import EDVisit
        v = db.session.get(EDVisit, vid)
        assert v.status == 'Admitted' and v.disposition_at


def test_unknown_patient_cannot_bill(app):
    client = app.test_client()
    _login(app, client)
    D = {'_csrf': 'tok'}
    client.post('/ed/new', data={**D, 'unknown_name': 'Unknown male', 'triage_level': '2',
                                 'chief_complaint': 'RTA'})
    with app.app_context():
        from mdc_erp.models import EDVisit
        v = EDVisit.query.first()
        assert v.patient_id is None and v.display_name == 'Unknown male'
        vid = v.id
    r = client.get(f'/ed/{vid}/bill', follow_redirects=False)
    # bounced back to the visit (no patient account to bill)
    assert r.status_code == 302 and f'/ed/{vid}' in r.headers['Location']
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import EDVisit
        assert db.session.get(EDVisit, vid).invoice_id is None


def test_ed_rbac_denies(app):
    client = app.test_client()
    # accountant is not in the ed permission list
    if _login(app, client, role='accountant') is None:
        pytest.skip('no accountant role')
    assert client.get('/ed/new').status_code == 403
