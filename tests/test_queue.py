"""Smart Queue (Phase 5, v8.0) end-to-end tests.

Covers token issuance with priority/emergency ordering, call-to-room, the public
display feed, completion + analytics, the login-free display board, and RBAC.
Self-contained.
"""
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
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'q.db'}"
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


def _issue(client, dept='Consultation', prio='Normal', name='X'):
    return client.post('/tokenq/issue',
                       data={'_csrf': 'tok', 'department': dept, 'priority': prio, 'name': name},
                       follow_redirects=False)


def test_priority_ordering_and_call(app):
    client = app.test_client()
    _login(app, client)

    _issue(client, prio='Normal', name='Normal1')     # token 1
    _issue(client, prio='Normal', name='Normal2')     # token 2
    _issue(client, prio='Emergency', name='Emerg')    # token 3 but should be served first

    # call next in Consultation -> emergency jumps ahead of the two normals
    r = client.get('/tokenq/call/Consultation?room=Room 1', follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.models import QueueTicket
        called = QueueTicket.query.filter_by(status='Called').all()
        assert len(called) == 1
        assert called[0].name == 'Emerg' and called[0].room == 'Room 1'
        assert called[0].called_at


def test_display_feed_and_complete(app):
    client = app.test_client()
    _login(app, client)
    _issue(client, dept='Laboratory', prio='Normal', name='LabPt')
    client.get('/tokenq/call/Laboratory?room=Lab 2')

    # public feed (no login needed) shows the called token
    fresh = app.test_client()
    r = fresh.get('/display/feed')
    assert r.status_code == 200
    data = r.get_json()
    assert data['called'] and data['called'][0]['room'] == 'Lab 2'
    code = data['called'][0]['code']

    # complete it
    with app.app_context():
        from mdc_erp.models import QueueTicket
        tid = QueueTicket.query.filter_by(status='Called').first().id
    client.get(f'/tokenq/{tid}/done')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import QueueTicket
        t = db.session.get(QueueTicket, tid)
        assert t.status == 'Done' and t.done_at

    # analytics renders and counts the served token
    a = client.get('/tokenq/analytics')
    assert a.status_code == 200 and b'Laboratory' in a.data


def test_public_display_no_login(app):
    client = app.test_client()          # not logged in
    r = client.get('/display')
    assert r.status_code == 200 and b'Modern Diagnostic Center' in r.data
    assert b'SpeechSynthesisUtterance' in r.data      # voice announcement present


def test_room_scoped_feed(app):
    client = app.test_client()
    _login(app, client)
    _issue(client, dept='Radiology', name='RadPt')
    client.get('/tokenq/call/Radiology?room=CT Room')
    r = client.get('/display/feed/CT Room')
    data = r.get_json()
    assert data['called'] and data['called'][0]['room'] == 'CT Room'


def test_queue_rbac_denies(app):
    client = app.test_client()
    # accountant is not in the tokenq permission list
    if _login(app, client, role='accountant') is None:
        pytest.skip('no accountant role')
    assert client.get('/tokenq/issue').status_code == 403
