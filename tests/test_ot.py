"""Operation Theatre (Phase 9, v8.0) end-to-end tests. Self-contained."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'ot.db'}"
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
        from mdc_erp.models import Patient, Theatre
        p = Patient(name='OT Pt', mrn='MRN-OT1', phone='0')
        t = Theatre(name='OT-1', active=True)
        db.session.add_all([p, t])
        db.session.commit()
        return p.id, t.id


def test_schedule_checklist_notes_and_flow(app):
    client = app.test_client()
    _login(app, client)
    pid, tid = _seed(app)
    D = {'_csrf': 'tok'}

    # schedule -> WHO checklist auto-seeded
    r = client.post('/ot/schedule', data={**D, 'patient_id': pid, 'theatre_id': tid,
                                          'procedure': 'Appendectomy', 'surgeon': 'Dr S',
                                          'anesthetist': 'Dr An', 'anesthesia_type': 'GA',
                                          'priority': 'Emergency'}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.models import Surgery, OTChecklistItem
        s = Surgery.query.first()
        assert s.status == 'Scheduled' and s.priority == 'Emergency'
        n = OTChecklistItem.query.filter_by(surgery_id=s.id).count()
        assert n >= 15                      # sign-in + time-out + sign-out items seeded
        sid = s.id
        cid = OTChecklistItem.query.filter_by(surgery_id=s.id).first().id

    # board shows it
    assert b'Appendectomy' in client.get('/m/ot').data

    # tick a checklist item
    client.get(f'/ot/{sid}/check/{cid}')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import OTChecklistItem
        c = db.session.get(OTChecklistItem, cid)
        assert c.checked and c.by == 'admin'

    # operative note
    client.post(f'/ot/{sid}/note', data={**D, 'kind': 'Operative', 'text': 'Uneventful, appendix removed'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Surgery
        assert len(db.session.get(Surgery, sid).op_notes) == 1

    # instrument count mismatch is flagged
    client.post(f'/ot/{sid}/item', data={**D, 'name': 'Swabs', 'count_before': '10', 'count_after': '9'})
    dv = client.get(f'/ot/{sid}')
    assert b'COUNT MISMATCH' in dv.data

    # start -> complete
    client.get(f'/ot/{sid}/status/start')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Surgery
        assert db.session.get(Surgery, sid).status == 'InProgress'
    client.get(f'/ot/{sid}/status/complete')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Surgery
        s = db.session.get(Surgery, sid)
        assert s.status == 'Completed' and s.started_at and s.ended_at

    # billing links an invoice
    client.get(f'/ot/{sid}/bill')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Surgery, Invoice
        s = db.session.get(Surgery, sid)
        assert s.invoice_id and db.session.get(Invoice, s.invoice_id) is not None


def test_ipd_to_ot_handoff(app):
    client = app.test_client()
    _login(app, client)
    pid, tid = _seed(app)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Ward, Bed, Admission
        w = Ward(name='W', active=True)
        db.session.add(w)
        db.session.commit()
        b = Bed(ward_id=w.id, label='B1', status='Occupied', active=True)
        db.session.add(b)
        db.session.commit()
        a = Admission(patient_id=pid, ward_id=w.id, bed_id=b.id, status='Admitted')
        db.session.add(a)
        db.session.commit()
        aid = a.id
    # the OT schedule form loads pre-filled from the admission
    r = client.get(f'/ot/schedule?admission={aid}')
    assert r.status_code == 200
    # and posting with the admission link stores it
    client.post('/ot/schedule', data={'_csrf': 'tok', 'patient_id': pid, 'theatre_id': tid,
                                      'procedure': 'Laparotomy', 'admission_id': aid})
    with app.app_context():
        from mdc_erp.models import Surgery
        s = Surgery.query.filter_by(procedure='Laparotomy').first()
        assert s and s.admission_id == aid


def test_ot_rbac_denies(app):
    client = app.test_client()
    if _login(app, client, role='accountant') is None:
        pytest.skip('no accountant role')
    assert client.get('/ot/schedule').status_code == 403
