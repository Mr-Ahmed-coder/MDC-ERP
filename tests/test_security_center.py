"""Security Center (Phase 14, v8.0) end-to-end tests. Self-contained."""
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
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'sec.db'}"
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


def _mkuser(app, username, **kw):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        from werkzeug.security import generate_password_hash
        u = User(username=username, name=username, role='reception',
                 pw=generate_password_hash('secret123'), active=True, **kw)
        db.session.add(u)
        db.session.commit()
        return u.id


def test_security_dashboard_and_actions(app):
    client = app.test_client()
    _login(app, client)

    # a user still on the default password
    uid = _mkuser(app, 'newbie', must_change_pw=True)

    # simulate 5 failed logins for a locked account
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import LoginHistory
        for _ in range(5):
            db.session.add(LoginHistory(username='newbie', ip='1.2.3.4', ok=False, note='bad pw'))
        db.session.commit()

    r = client.get('/m/security')
    assert r.status_code == 200
    assert b'2FA enabled' in r.data and b'Default password' in r.data
    assert b'Active policy' in r.data and b'newbie' in r.data
    assert b'LOCKED' in r.data                       # lockout surfaced

    # clear lockout removes the failed entries
    client.get(f'/security/user/{uid}/clear-lockout')
    with app.app_context():
        from mdc_erp.models import LoginHistory
        assert LoginHistory.query.filter_by(username='newbie', ok=False).count() == 0

    # require password change on an account that isn't currently flagged
    uid2 = _mkuser(app, 'clerk')
    client.get(f'/security/user/{uid2}/require-change')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        assert db.session.get(User, uid2).must_change_pw is True

    # reset 2FA
    uid3 = _mkuser(app, 'nurse2', totp_enabled=True, totp_secret='ABC123')
    client.get(f'/security/user/{uid3}/reset-2fa')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = db.session.get(User, uid3)
        assert u.totp_enabled is False and u.totp_secret is None


def test_security_rbac_denies(app):
    client = app.test_client()
    if _login(app, client, role='reception') is None:
        pytest.skip('no reception role')
    # dispatch gate denies the dashboard
    assert b'No access' in client.get('/m/security').data
    # and the action routes 403
    uid = _mkuser(app, 'victim')
    assert client.get(f'/security/user/{uid}/require-change').status_code == 403
