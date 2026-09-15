"""Search View on bespoke custom pages (Phase 18, v8.0). Self-contained.

Covers the reusable search_view() wired into patient invoices, the lab and
radiology worklists, and the doctor-requests board, plus favorites/recent on a
custom module.
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
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'cs.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User, Patient, Service, LabOrder, RadOrder, Invoice, Referral
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        p = Patient(name='Amina Yusuf', mrn='MRN-1')
        db.session.add(p)
        svc = Service(name='CBC', department='Lab', active=True)
        db.session.add(svc)
        db.session.commit()
        db.session.add_all([
            Invoice(patient_id=p.id, date='2026-02-01', guarantor='Takaful', status='Unpaid'),
            LabOrder(patient_id=p.id, service_id=svc.id, status='Requested', date='2026-02-01', sample_no='SAMP-500'),
            RadOrder(patient_id=p.id, status='Requested', date='2026-02-01', modality='CT'),
            Referral(patient_name='Amina Yusuf', doctor_name='Dr Warsame', date='2026-02-01', status='New'),
        ])
        db.session.commit()
    return app


def _login(app, client):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.commit()
        uid = u.id
    with client.session_transaction() as s:
        s['uid'] = uid
        s['_csrf'] = 'tok'
    return uid


def test_invoices_search_view(app):
    c = app.test_client()
    _login(app, c)
    r = c.get('/m/invoices')
    assert r.status_code == 200 and b'Filters:' in r.data and b'Favorites' in r.data
    r2 = c.get('/m/invoices?q=Takaful')
    assert b'<mark>' in r2.data and b'Takaful' in r2.data
    # status chip
    assert c.get('/m/invoices?status=Unpaid').status_code == 200


def test_lab_worklist_search_view(app):
    c = app.test_client()
    _login(app, c)
    r = c.get('/m/lab?q=SAMP-500')
    assert r.status_code == 200 and b'<mark>' in r.data and b'SAMP-500' in r.data
    assert b'Filters:' in r.data


def test_radiology_worklist_search_view(app):
    c = app.test_client()
    _login(app, c)
    r = c.get('/m/radiology?q=CT')
    assert r.status_code == 200 and b'Filters:' in r.data
    # advanced filter: modality equals CT
    import json
    import urllib.parse
    adv = 'adv=' + urllib.parse.quote(json.dumps([{'f': 'modality', 'op': 'eq', 'v': 'CT', 'v2': ''}]))
    assert c.get('/m/radiology?' + adv).status_code == 200


def test_reqboard_highlight_and_recent(app):
    c = app.test_client()
    _login(app, c)
    r = c.get('/m/reqboard?q=amina')
    assert r.status_code == 200 and b'<mark>' in r.data
    with app.app_context():
        from mdc_erp.models import SearchLog
        assert SearchLog.query.filter_by(module='reqboard').count() >= 1


def test_favorites_on_custom_module(app):
    c = app.test_client()
    _login(app, c)
    # save a favorite on a custom module (invoices)
    r = c.post('/m/invoices/fav/save', data={'_csrf': 'tok', 'name': 'Unpaid only',
                                             'args': 'status=Unpaid', 'shared': '1'})
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.models import SavedSearch
        f = SavedSearch.query.filter_by(module='invoices').first()
        assert f and f.name == 'Unpaid only'
        fid = f.id
    # it shows on the page and default redirect works
    assert b'Unpaid only' in c.get('/m/invoices').data
    c.get(f'/m/invoices/fav/{fid}/default')
    rr = c.get('/m/invoices', follow_redirects=False)
    assert rr.status_code == 302 and 'status=Unpaid' in rr.headers['Location']
