"""Per-module Odoo-style Search View (Phase 17, v8.0) tests. Self-contained.

Exercises the generic registry list view that every REG module shares:
highlight, quick-filter chips, the advanced condition builder, favorites
(save/default/pin/rename/delete/share), recent searches, and RBAC.
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
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'sv.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User, Supplier, Doctor
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.add_all([
            Supplier(name='Zamzam Traders', phone='615', category='Reagents'),
            Supplier(name='Alpha Medical', phone='618', category='Consumables'),
            Doctor(name='Dr Active', specialty='Cardiology', active=True),
            Doctor(name='Dr Retired', specialty='Cardiology', active=False),
        ])
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


def _adv(conds, join='and'):
    return 'adv=' + urllib.parse.quote(json.dumps(conds)) + '&join=' + join


def test_search_highlight_and_chips(app):
    c = app.test_client()
    _login(app, c)
    r = c.get('/m/suppliers?q=zamzam')
    assert r.status_code == 200 and b'<mark>' in r.data
    # toolbar has the odoo-view controls
    for needle in (b'Filters:', b'Favorites', b'advpanel', b'Advanced'):
        assert needle in r.data


def test_quick_filter_active_chip(app):
    c = app.test_client()
    _login(app, c)
    # active chip narrows to active doctors only
    r = c.get('/m/doctors?active=1')
    assert b'Dr Active' in r.data and b'Dr Retired' not in r.data
    r0 = c.get('/m/doctors?active=0')
    assert b'Dr Retired' in r0.data and b'Dr Active' not in r0.data


def test_advanced_builder_operators(app):
    c = app.test_client()
    _login(app, c)
    # contains
    r = c.get('/m/suppliers?' + _adv([{'f': 'category', 'op': 'contains', 'v': 'Reagent', 'v2': ''}]))
    assert b'Zamzam' in r.data and b'Alpha Medical' not in r.data
    # starts with
    r = c.get('/m/suppliers?' + _adv([{'f': 'name', 'op': 'starts', 'v': 'Alpha', 'v2': ''}]))
    assert b'Alpha Medical' in r.data and b'Zamzam' not in r.data
    # equals
    r = c.get('/m/suppliers?' + _adv([{'f': 'category', 'op': 'eq', 'v': 'Consumables', 'v2': ''}]))
    assert b'Alpha Medical' in r.data and b'Zamzam' not in r.data
    # OR join across two conditions returns both
    r = c.get('/m/suppliers?' + _adv([
        {'f': 'name', 'op': 'contains', 'v': 'Zamzam', 'v2': ''},
        {'f': 'name', 'op': 'contains', 'v': 'Alpha', 'v2': ''}], join='or'))
    assert b'Zamzam' in r.data and b'Alpha Medical' in r.data


def test_favorites_lifecycle(app):
    c = app.test_client()
    _login(app, c)
    adv = _adv([{'f': 'category', 'op': 'contains', 'v': 'Reagent', 'v2': ''}])
    # save current
    r = c.post('/m/suppliers/fav/save', data={'_csrf': 'tok', 'name': 'Reagent vendors',
                                              'args': adv, 'shared': '1'}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.models import SavedSearch
        f = SavedSearch.query.first()
        assert f.name == 'Reagent vendors' and f.shared is True
        fid = f.id
    # favorite shows in the toolbar
    assert b'Reagent vendors' in c.get('/m/suppliers').data
    # set default -> opening with no args redirects to the saved args
    c.get(f'/m/suppliers/fav/{fid}/default')
    r = c.get('/m/suppliers', follow_redirects=False)
    assert r.status_code == 302 and 'adv=' in r.headers['Location']
    # pin + rename
    c.get(f'/m/suppliers/fav/{fid}/pin')
    c.get(f'/m/suppliers/fav/{fid}/rename?name=Reagents%20only')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import SavedSearch
        f = db.session.get(SavedSearch, fid)
        assert f.pinned is True and f.name == 'Reagents only' and f.is_default is True
    # delete
    c.get(f'/m/suppliers/fav/{fid}/del')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import SavedSearch
        assert db.session.get(SavedSearch, fid) is None


def test_favorite_owner_gate(app):
    # a favorite saved by super_admin cannot be deleted by another user
    su = app.test_client()
    _login(su, su) if False else _login(app, su, 'super_admin')
    adv = _adv([{'f': 'name', 'op': 'contains', 'v': 'Zamzam', 'v2': ''}])
    su.post('/m/suppliers/fav/save', data={'_csrf': 'tok', 'name': 'mine', 'args': adv})
    with app.app_context():
        from mdc_erp.models import SavedSearch
        fid = SavedSearch.query.first().id
    other = app.test_client()
    if _login(app, other, 'accountant') is None:
        pytest.skip('no accountant role')
    # accountant may not even have suppliers perm -> 403; if they do, still owner-gated 403
    assert other.get(f'/m/suppliers/fav/{fid}/del').status_code == 403
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import SavedSearch
        assert db.session.get(SavedSearch, fid) is not None


def test_recent_searches_recorded(app):
    c = app.test_client()
    _login(app, c)
    c.get('/m/suppliers?q=alpha')
    with app.app_context():
        from mdc_erp.models import SearchLog
        assert SearchLog.query.filter_by(module='suppliers', q='alpha').count() == 1
    # recent chip appears
    assert b'Recent:' in c.get('/m/suppliers').data
