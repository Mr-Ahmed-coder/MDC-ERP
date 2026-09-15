"""Inpatient / IPD (Phase 8, v8.0) end-to-end tests. Self-contained."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'ipd.db'}"
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


def _seed(app):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Patient, Ward, Bed
        p = Patient(name='IPD Pt', mrn='MRN-IPD1', phone='0')
        w = Ward(name='General Ward', kind='General', active=True)
        db.session.add_all([p, w])
        db.session.commit()
        b1 = Bed(ward_id=w.id, label='G-01', status='Available', daily_rate=20, active=True)
        b2 = Bed(ward_id=w.id, label='G-02', status='Available', daily_rate=20, active=True)
        db.session.add_all([b1, b2])
        db.session.commit()
        return p.id, w.id, b1.id, b2.id


def test_admit_transfer_discharge_and_bill(app):
    client = app.test_client()
    _login(app, client)
    pid, wid, b1, b2 = _seed(app)
    D = {'_csrf': 'tok'}

    # admit -> bed occupied
    r = client.post('/ipd/admit', data={**D, 'patient_id': pid, 'ward_id': wid, 'bed_id': b1,
                                        'admitting_doctor': 'Dr A', 'diagnosis': 'Pneumonia'},
                    follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Admission, Bed
        a = Admission.query.first()
        assert a.status == 'Admitted' and a.bed_id == b1
        assert db.session.get(Bed, b1).status == 'Occupied'
        aid = a.id

    # board shows the inpatient
    assert b'IPD Pt' in client.get('/m/ipd').data

    # nursing note + medication administration
    client.post(f'/ipd/{aid}/note', data={**D, 'category': 'Nursing', 'text': 'Comfortable overnight'})
    client.post(f'/ipd/{aid}/med', data={**D, 'medicine': 'Ceftriaxone', 'dose': '1 g', 'route': 'IV'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Admission
        a = db.session.get(Admission, aid)
        assert len(a.ipd_notes) == 1 and len(a.meds) == 1

    # transfer to bed 2 -> b1 freed, b2 occupied
    client.post(f'/ipd/{aid}/transfer', data={**D, 'bed_id': b2, 'reason': 'window bed'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Admission, Bed
        a = db.session.get(Admission, aid)
        assert a.bed_id == b2
        assert db.session.get(Bed, b1).status == 'Available'
        assert db.session.get(Bed, b2).status == 'Occupied'
        assert len(a.transfers) == 1

    # bill -> invoice with an auto bed-charge line
    client.get(f'/ipd/{aid}/bill')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Admission, InvoiceItem
        a = db.session.get(Admission, aid)
        assert a.invoice_id
        items = InvoiceItem.query.filter_by(invoice_id=a.invoice_id).all()
        assert any('Bed charge' in (it.desc or '') for it in items)

    # discharge -> bed freed
    r = client.post(f'/ipd/{aid}/discharge', data={**D, 'discharge_type': 'Home', 'summary': 'Recovered'})
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Admission, Bed
        a = db.session.get(Admission, aid)
        assert a.status == 'Discharged' and a.discharge_at
        assert db.session.get(Bed, b2).status == 'Available'


def test_ed_to_ipd_handoff(app):
    client = app.test_client()
    _login(app, client)
    pid, wid, b1, b2 = _seed(app)
    D = {'_csrf': 'tok'}
    # ED arrival then Admit disposition should route into IPD admit prefilled
    client.post('/ed/new', data={**D, 'patient_id': pid, 'triage_level': '2', 'chief_complaint': 'SOB'})
    with app.app_context():
        from mdc_erp.models import EDVisit
        vid = EDVisit.query.first().id
    r = client.post(f'/ed/{vid}/disposition', data={**D, 'disposition': 'Admit'}, follow_redirects=False)
    assert r.status_code == 302 and f'/ipd/admit' in r.headers['Location'] and f'ed={vid}' in r.headers['Location']
    # the admit form loads with the ED context
    form = client.get(f'/ipd/admit?ed={vid}')
    assert form.status_code == 200 and b'Admitting from ED' in form.data


def test_ipd_rbac_denies(app):
    client = app.test_client()
    if _login(app, client, role='accountant') is None:
        pytest.skip('no accountant role')
    assert client.get('/ipd/admit').status_code == 403
