"""LIS (Phase 4, v8.0) end-to-end tests.

Covers HL7 ORU import matched to a barcoded sample, critical-value detection,
verification/release, the acknowledge flow, CSV import, the token-protected
analyzer API endpoint, and RBAC. Self-contained.
"""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig

HL7 = ("MSH|^~\\&|SYSMEX|LAB|LIS|MDC|20260201||ORU^R01|M1|P|2.3.1\r"
       "PID|1||MRN9||DOE^JANE\r"
       "OBR|1|ORD1|SMP-00042|CBC\r"
       "OBX|1|NM|WBC^White Blood Cell||7.2|x10^9/L|4.0-11.0|N|||F\r"
       "OBX|2|NM|HGB^Hemoglobin||6.5|g/dL|13.0-17.0|LL|||F")


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'lis.db'}"
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


def _seed_sample(app, sample_no='SMP-00042'):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Patient, Service, LabOrder
        p = Patient(name='Lab Pt', mrn='MRN9', phone='0')
        s = Service(name='CBC', department='Lab', active=True)
        db.session.add_all([p, s])
        db.session.commit()
        o = LabOrder(patient_id=p.id, service_id=s.id, status='Collected',
                     sample_no=sample_no, specimen='Blood')
        db.session.add(o)
        db.session.commit()
        return o.id


def test_hl7_import_critical_and_verify(app):
    client = app.test_client()
    _login(app, client)
    oid = _seed_sample(app)

    # import HL7 -> structured values + critical alert
    r = client.post('/lis/import', data={'_csrf': 'tok', 'fmt': 'hl7', 'payload': HL7},
                    follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import LabOrder, LabResultValue
        o = db.session.get(LabOrder, oid)
        assert len(o.values) == 2
        assert o.panic is True and o.panic_ack is False        # LL flag -> critical
        assert any(v.flag == 'LL' for v in o.values)
        assert all(v.source == 'Analyzer' and not v.verified for v in o.values)

    # critical board shows it
    cb = client.get('/lis/critical')
    assert cb.status_code == 200 and b'SMP-00042' in cb.data

    # verify & release
    r = client.post(f'/lis/order/{oid}/verify', data={'_csrf': 'tok'}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import LabOrder
        o = db.session.get(LabOrder, oid)
        assert all(v.verified for v in o.values)
        assert o.status == 'Resulted'
        assert o.result and 'Hemoglobin' in o.result       # summary written for lab print

    # acknowledge the critical alert
    client.get(f'/lis/order/{oid}/ack')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import LabOrder
        assert db.session.get(LabOrder, oid).panic_ack is True


def test_csv_import(app):
    client = app.test_client()
    _login(app, client)
    oid = _seed_sample(app, 'SMP-CSV1')
    csv_data = "sample_no,test,value,unit,ref,flag\nSMP-CSV1,Glucose,95,mg/dL,70-110,N"
    r = client.post('/lis/import', data={'_csrf': 'tok', 'fmt': 'csv', 'payload': csv_data})
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import LabOrder
        o = db.session.get(LabOrder, oid)
        assert len(o.values) == 1 and o.values[0].name == 'Glucose'


def test_analyzer_api_endpoint(app):
    client = app.test_client()
    oid = _seed_sample(app)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Setting
        db.session.add(Setting(key='lis_hl7_token', value='secret123'))
        db.session.commit()

    # wrong token -> 401 AR
    r = client.post('/api/lis/hl7', data=HL7, headers={'X-LIS-Token': 'nope'},
                    content_type='text/plain')
    assert r.status_code == 401 and b'MSA|AR' in r.data

    # correct token -> AA ack, results applied
    r = client.post('/api/lis/hl7', data=HL7, headers={'X-LIS-Token': 'secret123'},
                    content_type='text/plain')
    assert r.status_code == 200 and b'MSA|AA' in r.data
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import LabOrder
        assert len(db.session.get(LabOrder, oid).values) == 2


def test_barcode_label(app):
    client = app.test_client()
    _login(app, client)
    oid = _seed_sample(app)
    r = client.get(f'/lis/order/{oid}/label')
    assert r.status_code == 200 and b'SMP-00042' in r.data and b'<svg' in r.data


def test_lis_rbac_denies(app):
    client = app.test_client()
    # accountant is not in the lis permission list
    if _login(app, client, role='accountant') is None:
        pytest.skip('no accountant role')
    assert client.get('/lis/import').status_code == 403
