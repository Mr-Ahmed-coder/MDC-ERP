"""Dialysis (Phase 10, v8.0) end-to-end tests. Self-contained."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'dia.db'}"
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
        from mdc_erp.models import Patient, DialysisMachine
        p = Patient(name='Dia Pt', mrn='MRN-DIA1', phone='0')
        m = DialysisMachine(name='HD-1', status='Available', active=True)
        db.session.add_all([p, m])
        db.session.commit()
        return p.id, m.id


def test_dialysis_full_session(app):
    client = app.test_client()
    _login(app, client)
    pid, mid = _seed(app)
    D = {'_csrf': 'tok'}

    # schedule
    r = client.post('/dialysis/schedule', data={**D, 'patient_id': pid, 'machine_id': mid,
                                                'access_type': 'AV Fistula', 'dry_weight': '70',
                                                'uf_goal': '2.5'}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.models import DialysisSession
        s = DialysisSession.query.first()
        assert s.status == 'Scheduled' and s.uf_goal == 2.5
        sid = s.id

    assert b'Dia Pt' in client.get('/m/dialysis').data

    # start -> machine InUse, pre-data captured
    client.post(f'/dialysis/{sid}/start', data={**D, 'pre_weight': '72.5', 'pre_bp': '150/90',
                                                'blood_flow': '300', 'heparin': '2000u'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import DialysisSession, DialysisMachine
        s = db.session.get(DialysisSession, sid)
        assert s.status == 'InProgress' and s.pre_weight == 72.5 and s.started_at
        assert db.session.get(DialysisMachine, mid).status == 'InUse'

    # pre & post lab monitoring
    client.post(f'/dialysis/{sid}/lab', data={**D, 'phase': 'Pre', 'name': 'K+', 'value': '5.8', 'unit': 'mmol/L'})
    client.post(f'/dialysis/{sid}/lab', data={**D, 'phase': 'Post', 'name': 'K+', 'value': '4.1', 'unit': 'mmol/L'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import DialysisSession
        assert len(db.session.get(DialysisSession, sid).labs) == 2

    # complete -> machine Available, post-data captured
    client.post(f'/dialysis/{sid}/complete', data={**D, 'post_weight': '70.1', 'post_bp': '130/80',
                                                   'uf_achieved': '2.4', 'duration_min': '240',
                                                   'complications': 'None'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import DialysisSession, DialysisMachine
        s = db.session.get(DialysisSession, sid)
        assert s.status == 'Completed' and s.uf_achieved == 2.4 and s.ended_at
        assert db.session.get(DialysisMachine, mid).status == 'Available'

    # billing
    client.get(f'/dialysis/{sid}/bill')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import DialysisSession, Invoice
        s = db.session.get(DialysisSession, sid)
        assert s.invoice_id and db.session.get(Invoice, s.invoice_id) is not None


def test_dialysis_rbac_denies(app):
    client = app.test_client()
    if _login(app, client, role='accountant') is None:
        pytest.skip('no accountant role')
    assert client.get('/dialysis/schedule').status_code == 403
