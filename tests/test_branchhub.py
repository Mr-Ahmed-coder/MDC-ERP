"""Multi-branch hub & focus (Phase 15, v8.0) tests. Self-contained.

Uses EDVisit for scope assertions because it carries branch_id (Patient does
not — patients are shared reference data, intentionally not branch-scoped).
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
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'bh.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.commit()
    return app


def _admin_id(app):
    with app.app_context():
        from mdc_erp.models import User
        return User.query.filter_by(role='super_admin').first().id


def _seed(app):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Branch, EDVisit
        a = Branch(name='Gaalkacyo', code='GAL', active=True)
        b = Branch(name='Bosaso', code='BOS', active=True)
        db.session.add_all([a, b])
        db.session.commit()
        db.session.add_all([
            EDVisit(unknown_name='A1', status='Waiting', branch_id=a.id),
            EDVisit(unknown_name='A2', status='Waiting', branch_id=a.id),
            EDVisit(unknown_name='B1', status='Waiting', branch_id=b.id),
        ])
        db.session.commit()
        return a.id, b.id


def _names(rows):
    return {r.unknown_name for r in rows}


def test_focus_narrows_branch_scope(app):
    a_id, b_id = _seed(app)
    admin = _admin_id(app)
    from mdc_erp.core.security import branch_scope
    from mdc_erp.models import EDVisit

    with app.test_request_context():
        from flask import session
        session['uid'] = admin

        assert {'A1', 'A2', 'B1'} <= _names(branch_scope(EDVisit.query, EDVisit).all())

        session['focus_branch'] = a_id
        n = _names(branch_scope(EDVisit.query, EDVisit).all())
        assert 'A1' in n and 'A2' in n and 'B1' not in n

        session['focus_branch'] = b_id
        n = _names(branch_scope(EDVisit.query, EDVisit).all())
        assert 'B1' in n and 'A1' not in n

        session.pop('focus_branch', None)
        assert {'A1', 'A2', 'B1'} <= _names(branch_scope(EDVisit.query, EDVisit).all())


def test_branch_scoped_user_ignores_focus(app):
    a_id, b_id = _seed(app)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        from werkzeug.security import generate_password_hash
        clerk = User(username='clerkA', name='Clerk A', role='reception',
                     pw=generate_password_hash('x'), active=True, branch_id=a_id)
        db.session.add(clerk)
        db.session.commit()
        cid = clerk.id
    from mdc_erp.core.security import branch_scope
    from mdc_erp.models import EDVisit
    with app.test_request_context():
        from flask import session
        session['uid'] = cid
        session['focus_branch'] = b_id
        n = _names(branch_scope(EDVisit.query, EDVisit).all())
        assert 'A1' in n and 'B1' not in n


def test_hub_and_focus_routes(app):
    a_id, b_id = _seed(app)
    client = app.test_client()
    with client.session_transaction() as s:
        s['uid'] = _admin_id(app)

    assert client.get('/m/branchhub').status_code == 200
    client.get(f'/branch/focus/{a_id}')
    with client.session_transaction() as s:
        assert s.get('focus_branch') == a_id
    client.get('/branch/focus/all')
    with client.session_transaction() as s:
        assert 'focus_branch' not in s


def test_focus_rbac_denies_non_cross(app):
    a_id, b_id = _seed(app)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        from werkzeug.security import generate_password_hash
        clerk = User(username='clerkB', role='reception',
                     pw=generate_password_hash('x'), active=True, branch_id=a_id)
        db.session.add(clerk)
        db.session.commit()
        cid = clerk.id
    client = app.test_client()
    with client.session_transaction() as s:
        s['uid'] = cid
    assert client.get(f'/branch/focus/{b_id}').status_code == 403
