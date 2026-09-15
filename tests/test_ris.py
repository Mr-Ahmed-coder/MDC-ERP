"""RIS (Phase 2, v8.0) workflow tests.

Drives a single imaging request through the full RIS pipeline
(schedule -> acquire -> report -> sign off) at the HTTP layer and asserts the
derived stage, turnaround tracking and digital signature. Self-contained.
"""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'ris.db'}"
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


def _seed_order(app):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Patient, RadOrder, ImgModality
        p = Patient(name='RIS Pt', mrn='MRN-RIS1', phone='0')
        m = ImgModality(name='CT Scanner 1', modality='CT', room='R1', active=True)
        db.session.add_all([p, m])
        db.session.commit()
        o = RadOrder(patient_id=p.id, modality='CT', status='Requested')
        db.session.add(o)
        db.session.commit()
        return o.id, m.id


def test_ris_full_pipeline(app):
    client = app.test_client()
    _login(app, client)
    oid, mid = _seed_order(app)
    D = {'_csrf': 'tok'}

    # 1) schedule
    r = client.post(f'/ris/{oid}/schedule',
                    data={**D, 'modality_id': mid, 'scheduled_for': '2026-02-01T09:30', 'priority': 'Urgent'},
                    follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import RadOrder
        o = db.session.get(RadOrder, oid)
        assert o.scheduled_for == '2026-02-01 09:30'
        assert o.priority == 'Urgent'
        assert o.scheduled_at and o.requested_at

    # 2) acquire (technician) -> redirects to DICOM upload pre-linked
    r = client.post(f'/ris/{oid}/acquire', data={**D, 'technician': 'Tech A'}, follow_redirects=False)
    assert r.status_code == 302 and 'rad_order_id' in r.headers['Location']
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import RadOrder
        o = db.session.get(RadOrder, oid)
        assert o.status == 'Imaged' and o.acquired_at and o.technician == 'Tech A'

    # 3) report is written (radiology's job) — simulate the report existing
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import RadOrder
        o = db.session.get(RadOrder, oid)
        o.status = 'Reported'
        o.impression = 'No acute finding.'
        db.session.commit()

    # 4) sign off
    r = client.post(f'/ris/{oid}/approve', data=D, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import RadOrder
        o = db.session.get(RadOrder, oid)
        assert o.approved_at and o.approved_by == 'admin'
        assert o.signature and len(o.signature) >= 8      # HMAC verification stamp
        assert o.rad_approved_at == o.approved_at          # print lock engaged

    # worklist + TAT board render
    assert client.get('/m/ris').status_code == 200
    t = client.get('/ris/tat')
    assert t.status_code == 200 and b'CT' in t.data


def test_ris_rbac_denies_unprivileged(app):
    client = app.test_client()
    if _login(app, client, role='accountant') is None:
        pytest.skip('no accountant role')
    oid, _ = _seed_order(app)
    assert client.get(f'/ris/{oid}/schedule').status_code == 403


def test_ris_approve_requires_report(app):
    client = app.test_client()
    _login(app, client)
    oid, _ = _seed_order(app)          # still 'Requested', no report
    r = client.post(f'/ris/{oid}/approve', data={'_csrf': 'tok'}, follow_redirects=False)
    assert r.status_code == 302        # bounced back, not signed
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import RadOrder
        assert db.session.get(RadOrder, oid).approved_at is None
