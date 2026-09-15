"""Universal Global Search (Phase 16, v8.0) end-to-end tests. Self-contained."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'gs.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User, Patient, Service, LabOrder
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.add_all([
            Patient(name='Amina Yusuf', mrn='MRN-777', phone='615123456', gov_id='SL9988'),
            Patient(name='محمد علي', mrn='MRN-778', phone='612000000'),   # Arabic name
        ])
        svc = Service(name='CBC', department='Lab', active=True)
        db.session.add(svc)
        db.session.commit()
        p = Patient.query.filter_by(mrn='MRN-777').first()
        db.session.add(LabOrder(patient_id=p.id, service_id=svc.id, status='Resulted',
                                date='2026-02-01', sample_no='SAMP-500'))
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
    return uid


def _hits(data, cat=None):
    if cat:
        g = [x for x in data['groups'] if x['cat'] == cat]
        return g[0]['hits'] if g else []
    return [hh for g in data['groups'] for hh in g['hits']]


def test_search_fields_and_highlight(app):
    c = app.test_client()
    _login(app, c)
    # by name
    d = c.get('/api/gsearch?q=amina').get_json()
    pats = _hits(d, 'Patients')
    assert pats and '<mark>' in pats[0]['title']
    assert pats[0]['module'] == 'Patients' and 'url' in pats[0]
    # by MRN
    assert _hits(c.get('/api/gsearch?q=MRN-777').get_json())
    # by phone
    assert _hits(c.get('/api/gsearch?q=615123456').get_json())
    # by national id
    assert _hits(c.get('/api/gsearch?q=SL9988').get_json())
    # by lab sample number
    assert _hits(c.get('/api/gsearch?q=SAMP-500').get_json(), 'Laboratory')


def test_fuzzy_and_unicode(app):
    c = app.test_client()
    _login(app, c)
    # typo tolerance
    assert _hits(c.get('/api/gsearch?q=amena').get_json(), 'Patients')
    # Arabic substring search
    d = c.get('/api/gsearch?q=محمد').get_json()
    assert _hits(d, 'Patients')


def test_response_time_budget(app):
    c = app.test_client()
    _login(app, c)
    d = c.get('/api/gsearch?q=amina').get_json()
    assert d['took_ms'] < 500


def test_permission_gating(app):
    # add a lab order sample; an accountant lacks the 'lab' permission,
    # so Laboratory results must not appear for them — but do for super_admin.
    su = app.test_client()
    _login(app, su, 'super_admin')
    assert _hits(su.get('/api/gsearch?q=SAMP-500').get_json(), 'Laboratory')

    acc = app.test_client()
    if _login(app, acc, 'accountant') is None:
        pytest.skip('no accountant role')
    from mdc_erp.core.security import PERMS
    if 'accountant' in PERMS.get('lab', []):
        pytest.skip('accountant has lab in this config')
    assert not _hits(acc.get('/api/gsearch?q=SAMP-500').get_json(), 'Laboratory')


def test_audit_and_searchlog_written(app):
    c = app.test_client()
    _login(app, c)
    c.get('/api/gsearch?q=amina')
    with app.app_context():
        from mdc_erp.models import SearchLog
        assert SearchLog.query.filter(SearchLog.q == 'amina').count() >= 1


def test_context_and_pin_toggle(app):
    c = app.test_client()
    _login(app, c)
    c.get('/api/gsearch?q=amina')                 # seed recent
    ctx = c.get('/api/gsearch/context').get_json()
    assert any(r['q'] == 'amina' for r in ctx['recent'])

    # pin then unpin (toggle)
    r1 = c.post('/api/gsearch/pin', json={'url': '/patient/1', 'title': 'Amina', 'icon': 'P', 'module': 'Patients'})
    assert r1.get_json()['pinned'] is True
    ctx2 = c.get('/api/gsearch/context').get_json()
    assert any(p['url'] == '/patient/1' for p in ctx2['pinned'])
    r2 = c.post('/api/gsearch/pin', json={'url': '/patient/1'})
    assert r2.get_json()['pinned'] is False


def test_requires_auth(app):
    c = app.test_client()                          # not logged in
    assert c.get('/api/gsearch?q=x').status_code == 401
    assert c.get('/api/gsearch/context').status_code == 401
    assert c.post('/api/gsearch/pin', json={'url': '/x'}).status_code == 401


def test_palette_injected_on_pages(app):
    c = app.test_client()
    _login(app, c)
    page = c.get('/m/patients')
    assert b'gsp-q' in page.data and b'Global search' in page.data
