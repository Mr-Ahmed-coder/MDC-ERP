"""Search View on CUSTOM views (Phase 17b): fixed assets, doctor requests, etc.

Confirms the reusable search_view() component works on bespoke pages that render
their own tables (not the registry list) — search bar, highlight, advanced
filter, per-module recent logging, and favorites on a custom module key.
"""
import json
import urllib.parse
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'svc.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User, Asset, Referral
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.add_all([
            Asset(code='FA-001', name='Ultrasound Machine', category='Medical Equipment',
                  status='Active', cost=12000, department='Radiology'),
            Asset(code='FA-002', name='Office Desk', category='Furniture',
                  status='Active', cost=200, department='Admin'),
            Referral(patient_name='Amina Yusuf', doctor_name='Dr Ali', tests='CBC, X-ray',
                     status='New', date='2026-02-01'),
        ])
        db.session.commit()
    return app


def _login(app, c):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.commit()
        uid = u.id
    with c.session_transaction() as s:
        s['uid'] = uid
        s['_csrf'] = 'tok'


def _adv(conds, join='and'):
    return 'adv=' + urllib.parse.quote(json.dumps(conds)) + '&join=' + join


def test_fixed_assets_search_view(app):
    c = app.test_client()
    _login(app, c)
    r = c.get('/m/fa_register')
    assert r.status_code == 200
    assert b'lb-input' in r.data and b'Favorites' in r.data and b'advpanel' in r.data
    # search + highlight
    r = c.get('/m/fa_register?q=Ultrasound')
    assert b'<mark>' in r.data and b'Ultrasound' in r.data
    # advanced: department = Radiology -> only FA-001
    r = c.get('/m/fa_register?' + _adv([{'f': 'department', 'op': 'eq', 'v': 'Radiology', 'v2': ''}]))
    assert b'FA-001' in r.data and b'FA-002' not in r.data


def test_doctor_requests_search_view(app):
    c = app.test_client()
    _login(app, c)
    r = c.get('/m/referrals?q=Amina')
    assert r.status_code == 200
    assert b'lb-input' in r.data and b'<mark>' in r.data


def test_custom_module_recent_and_favorite(app):
    c = app.test_client()
    _login(app, c)
    c.get('/m/fa_register?q=desk')
    with app.app_context():
        from mdc_erp.models import SearchLog
        assert SearchLog.query.filter_by(module='fa_register', q='desk').count() == 1
    # favorites work on a custom module key too
    r = c.post('/m/fa_register/fav/save', data={'_csrf': 'tok', 'name': 'Radiology assets',
                                               'args': _adv([{'f': 'department', 'op': 'eq', 'v': 'Radiology', 'v2': ''}])},
               follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.models import SavedSearch
        assert SavedSearch.query.filter_by(module='fa_register').count() == 1
