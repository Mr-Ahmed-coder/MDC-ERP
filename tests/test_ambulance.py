"""Ambulance (Phase 11, v8.0) end-to-end tests. Self-contained."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'amb.db'}"
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
        from mdc_erp.models import Patient, Ambulance, AmbulanceDriver
        p = Patient(name='Amb Pt', mrn='MRN-AMB1', phone='0')
        v = Ambulance(label='Ambulance 1', plate='SL-123', status='Available', active=True)
        d = AmbulanceDriver(name='Driver A', phone='615', active=True)
        db.session.add_all([p, v, d])
        db.session.commit()
        return p.id, v.id, d.id


def test_dispatch_flow_location_and_bill(app):
    client = app.test_client()
    _login(app, client)
    pid, vid, did_ = _seed(app)
    D = {'_csrf': 'tok'}

    # create dispatch
    r = client.post('/ambulance/new', data={**D, 'patient_id': pid, 'vehicle_id': vid,
                                            'driver_id': did_, 'pickup': 'Market', 'destination': 'MDC',
                                            'priority': 'Emergency'}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.models import Dispatch
        d = Dispatch.query.first()
        assert d.status == 'Requested' and d.priority == 'Emergency'
        did = d.id

    assert b'Amb Pt' in client.get('/m/ambulance').data

    # advance: Dispatched -> vehicle OnTrip
    client.get(f'/ambulance/{did}/advance/Dispatched')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Dispatch, Ambulance
        d = db.session.get(Dispatch, did)
        assert d.status == 'Dispatched' and d.dispatched_at
        assert db.session.get(Ambulance, vid).status == 'OnTrip'

    # manual location update
    client.post(f'/ambulance/{did}/locate', data={**D, 'lat': '6.77', 'lng': '47.43', 'note': 'en route'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Dispatch
        d = db.session.get(Dispatch, did)
        assert d.last_lat == 6.77 and len(d.breadcrumbs) == 1

    # GPS device push via token endpoint
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Setting
        db.session.add(Setting(key='amb_gps_token', value='gpssecret'))
        db.session.commit()
    # wrong token -> 401
    assert client.post(f'/api/ambulance/{did}/location', json={'lat': 1, 'lng': 2},
                       headers={'X-AMB-Token': 'nope'}).status_code == 401
    # correct token -> 200 and breadcrumb added
    r = client.post(f'/api/ambulance/{did}/location', json={'lat': 6.80, 'lng': 47.40},
                    headers={'X-AMB-Token': 'gpssecret'})
    assert r.status_code == 200 and r.get_json()['ok'] is True
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Dispatch
        d = db.session.get(Dispatch, did)
        assert d.last_lat == 6.80 and any(b.source == 'GPS' for b in d.breadcrumbs)

    # complete -> vehicle Available
    client.get(f'/ambulance/{did}/advance/Completed')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Dispatch, Ambulance
        assert db.session.get(Dispatch, did).status == 'Completed'
        assert db.session.get(Ambulance, vid).status == 'Available'

    # billing
    client.get(f'/ambulance/{did}/bill')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Dispatch, Invoice
        d = db.session.get(Dispatch, did)
        assert d.invoice_id and db.session.get(Invoice, d.invoice_id) is not None


def test_ambulance_rbac_denies(app):
    client = app.test_client()
    if _login(app, client, role='lab_tech') is None:
        pytest.skip('no lab_tech role')
    assert client.get('/ambulance/new').status_code == 403
