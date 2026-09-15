"""Blood Bank expansion (Phase 12, v8.0) end-to-end tests. Self-contained."""
import datetime as dt
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'bb.db'}"
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
        from mdc_erp.models import Patient, BloodUnit
        soon = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        past = (dt.date.today() - dt.timedelta(days=2)).isoformat()
        p = Patient(name='BB Pt', mrn='MRN-BB1', blood_group='A+', phone='0')
        u_ok = BloodUnit(unit_no='U-100', blood_group='O-', status='Available',
                         expiry=(dt.date.today() + dt.timedelta(days=20)).isoformat())
        u_soon = BloodUnit(unit_no='U-101', blood_group='A+', status='Available', expiry=soon)
        u_exp = BloodUnit(unit_no='U-102', blood_group='B+', status='Available', expiry=past)
        db.session.add_all([p, u_ok, u_soon, u_exp])
        db.session.commit()
        return p.id, u_ok.id, u_soon.id, u_exp.id


def test_dashboard_alerts_crossmatch_transfuse(app):
    client = app.test_client()
    _login(app, client)
    pid, u_ok, u_soon, u_exp = _seed(app)

    # dashboard shows stock and expiry alerts
    r = client.get('/m/bloodbank')
    assert r.status_code == 200
    assert b'Expiry alerts' in r.data and b'U-102' in r.data      # expired unit listed

    # cross-match O- unit to A+ patient (compatible) -> unit reserved
    r = client.post('/bloodbank/crossmatch',
                    data={'_csrf': 'tok', 'patient_id': pid, 'unit_id': u_ok, 'result': 'Compatible'},
                    follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import BloodUnit, CrossMatch
        assert db.session.get(BloodUnit, u_ok).status == 'Reserved'
        cm = CrossMatch.query.first()
        assert cm.result == 'Compatible' and cm.patient_id == pid

    # transfuse the reserved unit -> Used + issued
    r = client.post('/bloodbank/transfuse',
                    data={'_csrf': 'tok', 'patient_id': pid, 'unit_id': u_ok,
                          'volume_ml': '450', 'reaction': 'None'}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import BloodUnit, Transfusion
        u = db.session.get(BloodUnit, u_ok)
        assert u.status == 'Used' and u.issued_to == pid and u.issued_date
        assert Transfusion.query.count() == 1

    # expiry sweep marks the past-expiry unit Expired
    client.get('/bloodbank/expire')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import BloodUnit
        assert db.session.get(BloodUnit, u_exp).status == 'Expired'
        assert db.session.get(BloodUnit, u_soon).status == 'Available'   # not yet expired


def test_bloodbank_rbac_denies(app):
    client = app.test_client()
    if _login(app, client, role='accountant') is None:
        pytest.skip('no accountant role')
    assert client.get('/bloodbank/crossmatch').status_code == 403
