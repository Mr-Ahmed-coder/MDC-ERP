"""Accounting Guide + enhanced manual journal entry tests."""
import pytest
from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'ag.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.commit()
    return app


def _client(app, role='super_admin'):
    with app.app_context():
        from mdc_erp.models import User
        u = User.query.filter_by(role=role).first()
        if not u:
            return None
        uid = u.id
    c = app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    return c


def test_guide_renders_steps(app):
    d = _client(app).get('/m/acctguide').get_data(as_text=True)
    assert 'Step by step' in d
    assert 'Manual journal entry' in d and 'Billing transaction' in d
    assert 'cheat-sheet' in d
    # links to the real forms + ledger
    assert '/journal/new' in d and '/invoice/new' in d and 'genledger' in d


def test_manual_journal_form_has_live_balance(app):
    d = _client(app).get('/journal/new').get_data(as_text=True)
    assert 'function jbal' in d and 'Balanced' in d
    assert 'acct8' in d          # 8 entry rows


def test_manual_journal_posts_balanced_entry(app):
    c = _client(app)
    with c.session_transaction() as s:
        s['_csrf'] = 'tok'
    with app.app_context():
        from mdc_erp.models import Account
        a1 = Account.query.filter_by(type='Asset').first()
        a2 = Account.query.filter_by(type='Equity').first() or Account.query.filter_by(type='Income').first()
        a1id, a2id = a1.id, a2.id
    r = c.post('/journal/new', data={'_csrf': 'tok', 'date': '2026-08-04', 'ref': 'JV-TEST', 'memo': 'Capital',
                                     'acct1': a1id, 'debit1': '1000', 'credit1': '',
                                     'acct2': a2id, 'debit2': '', 'credit2': '1000'},
               follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from mdc_erp.models import JournalEntry
        e = JournalEntry.query.filter_by(ref='JV-TEST').first()
        assert e is not None and len(e.lines) == 2


def test_guide_permission(app):
    lt = _client(app, 'lab_tech')
    if lt is not None:
        assert b'No access' in lt.get('/m/acctguide').data
