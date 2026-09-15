"""General Ledger module (Odoo-style) tests. Self-contained."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'gl.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User, Account
        from mdc_erp.core.posting import post_journal
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        a1 = Account.query.filter_by(type='Asset').first()
        a2 = Account.query.filter_by(type='Income').first()
        if a1 is None:
            a1 = Account(code='1000', name='Cash', type='Asset'); db.session.add(a1)
        if a2 is None:
            a2 = Account(code='4000', name='Revenue', type='Income'); db.session.add(a2)
        db.session.commit()
        post_journal('2026-08-03', 'JV-T1', 'Test posting', [(a1.code, 100, 0), (a2.code, 0, 100)])
        db.session.commit()
    return app


def _client(app, role='super_admin'):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role=role).first()
        if not u:
            return None
        u.must_change_pw = False
        db.session.commit()
        uid = u.id
    c = app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    return c


def test_all_gl_screens_render(app):
    c = _client(app)
    for mod, needle in [('gldash', b'Total Debit'), ('genledger', b'General Ledger'),
                        ('jitems', b'Journal Items'), ('jentries', b'Journal Entries'),
                        ('trialbal', b'Trial Balance')]:
        r = c.get('/m/' + mod)
        assert r.status_code == 200 and needle in r.data and b'subnav' in r.data


def test_ledger_filters_and_running_balance(app):
    c = _client(app)
    r = c.get('/m/genledger?group=account')
    assert b'Balance' in r.data and b'Total Debit' in r.data and b'Closing' in r.data
    # date filter to an empty window yields no transactions
    r = c.get('/m/genledger?from=2000-01-01&to=2000-01-02')
    assert b'No transactions' in r.data
    # account type filter
    assert c.get('/m/genledger?type=Income').status_code == 200
    # sorting
    assert c.get('/m/genledger?sort=debit&dir=desc').status_code == 200


def test_trial_balance_balanced(app):
    c = _client(app)
    d = c.get('/m/trialbal').get_data(as_text=True)
    assert 'balanced' in d          # debits == credits
    assert 'Opening' in d and 'Closing' in d


def test_journal_entry_drilldown(app):
    c = _client(app)
    with app.app_context():
        from mdc_erp.models import JournalEntry
        eid = JournalEntry.query.first().id
    r = c.get(f'/gl/entry/{eid}')
    assert r.status_code == 200 and b'Total' in r.data


def test_exports(app):
    c = _client(app)
    r = c.get('/gl/export.csv')
    assert r.status_code == 200 and 'text/csv' in r.headers['Content-Type']
    assert 'Account Code' in r.get_data(as_text=True)
    assert c.get('/gl/print').status_code == 200
    assert c.get('/gl/print?tb=1').status_code == 200


def test_auditor_readonly_access(app):
    c = _client(app, 'auditor')
    if c is None:
        pytest.skip('no auditor role')
    # auditor can view the GL (read-only reporting)
    assert c.get('/m/gldash').status_code == 200
    assert c.get('/m/trialbal').status_code == 200


def test_permission_denied_for_clinical_role(app):
    c = _client(app, 'lab_tech')
    if c is None:
        pytest.skip('no lab_tech role')
    assert b'No access' in c.get('/m/genledger').data
    assert c.get('/gl/export.csv').status_code == 403


def test_account_balances(app):
    c = _client(app)
    d = c.get('/m/acctbal').get_data(as_text=True)
    assert 'Account Balances' in d and 'Balance' in d and 'TOTAL' in d
    # every account listed with its balance; grouping + filters work
    assert 'Group by type' in d and 'Hide empty' in d
    assert c.get('/m/acctbal?nonzero=1').status_code == 200
    assert c.get('/m/acctbal?group=none').status_code == 200
    assert c.get('/m/acctbal?type=Income').status_code == 200
    # clicking an account drills into its ledger
    assert 'group=none' in d and 'account=' in d


def test_transactions_clickable_and_related(app):
    c = _client(app)
    # ledger + journal-items rows are clickable to the journal entry
    d = c.get('/m/genledger?group=none').get_data(as_text=True)
    assert 'glrow' in d and "location.href='/gl/entry/" in d
    assert 'account=' in d           # account cell drills to its ledger
    ji = c.get('/m/jitems').get_data(as_text=True)
    assert 'glrow' in ji and '/gl/entry/' in ji
    # entry detail is a hub: related source-doc links + per-account ledger links
    with app.app_context():
        from mdc_erp.models import JournalEntry
        eid = JournalEntry.query.first().id
    de = c.get(f'/gl/entry/{eid}').get_data(as_text=True)
    assert 'Ledger →' in de          # each account row links to its ledger
