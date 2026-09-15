"""Bank Reconciliation (Odoo-18-style) tests. Self-contained."""
import io
import re
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'br.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User, Account, BankAccount
        from mdc_erp.core.posting import post_journal
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        a_bank = Account.query.filter_by(code='1102').first()
        if not a_bank:
            a_bank = Account(code='1102', name='Bank', type='Asset'); db.session.add(a_bank)
        a_rev = Account.query.filter_by(type='Income').first()
        if not a_rev:
            a_rev = Account(code='4000', name='Revenue', type='Income'); db.session.add(a_rev)
        db.session.commit()
        ba = BankAccount(name='Premier Bank', bank_name='Premier', number='0011',
                         account_id=a_bank.id, active=True)
        db.session.add(ba)
        db.session.commit()
        post_journal('2026-08-03', 'JV-DEP', 'Deposit EVC', [(a_bank.code, 290, 0), (a_rev.code, 0, 290)])
        db.session.commit()
        app._baid = ba.id
        app._rev = a_rev.code
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


def _tok(c):
    r = c.get('/bankrec/import')
    m = re.search(rb"name='_csrf' value='([^']+)'", r.data)
    return m.group(1).decode() if m else ''


def _import_csv(app, c):
    data = ('Date,Description,Ref,Amount\n'
            '2026-08-03,Deposit EVC,TX1001,290\n'
            '2026-08-03,Deposit EVC,TX1001,290\n'      # duplicate
            '2026-08-04,Bank charge,FEE,-5')
    return c.post('/bankrec/import', data={'bank': str(app._baid), 'name': 'Aug', 'opening': '0',
                                           'closing': '285', 'pasted': data, '_csrf': _tok(c)},
                  follow_redirects=True)


def test_import_csv_and_duplicate_detection(app):
    c = _client(app)
    r = _import_csv(app, c)
    assert r.status_code == 200
    with app.app_context():
        from mdc_erp.models import BankStatement
        st = BankStatement.query.first()
        assert len(st.lines) == 3
        assert sum(1 for l in st.lines if l.is_duplicate) == 1


def test_import_excel(app):
    c = _client(app)
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(['Date', 'Description', 'Ref', 'Amount'])
    ws.append(['2026-08-05', 'Transfer in', 'TX9', 500])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = c.post('/bankrec/import',
               data={'bank': str(app._baid), 'name': 'xl', 'opening': '0', 'closing': '500',
                     'file': (buf, 'stmt.xlsx'), '_csrf': _tok(c)},
               content_type='multipart/form-data', follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        from mdc_erp.models import BankStatementLine
        assert BankStatementLine.query.filter_by(ref='TX9').first() is not None


def test_automatch_clears_book_line(app):
    c = _client(app)
    _import_csv(app, c)
    with app.app_context():
        from mdc_erp.models import BankStatement
        sid = BankStatement.query.first().id
    c.get(f'/bankrec/{sid}/automatch', follow_redirects=True)
    with app.app_context():
        from mdc_erp.models import BankStatement, BankAccount, JournalLine
        st = BankStatement.query.get(sid)
        assert sum(1 for l in st.lines if l.matched) == 1     # only the 290 deposit
        acct_id = BankAccount.query.get(app._baid).account_id
        assert JournalLine.query.filter_by(account_id=acct_id, cleared=True).count() >= 1


def test_writeoff_and_payment_post_journals(app):
    c = _client(app)
    _import_csv(app, c)
    with app.app_context():
        from mdc_erp.models import BankStatement, BankStatementLine
        st = BankStatement.query.first()
        sid = st.id
        fee = [l for l in st.lines if (l.amount or 0) < 0][0].id
        dup = [l for l in st.lines if l.is_duplicate][0].id
    # write-off the fee
    c.post(f'/bankrec/line/{fee}/writeoff', data={'account': app._rev, 'amount': '-5', '_csrf': _tok(c)},
           follow_redirects=True)
    # create payment for the duplicate line
    c.post(f'/bankrec/line/{dup}/payment', data={'account': app._rev, '_csrf': _tok(c)},
           follow_redirects=True)
    with app.app_context():
        from mdc_erp.models import BankStatementLine
        assert BankStatementLine.query.get(fee).match_type == 'writeoff'
        assert BankStatementLine.query.get(dup).match_type == 'payment'
        assert BankStatementLine.query.get(fee).journal_entry_id is not None


def test_manual_match_and_unmatch(app):
    c = _client(app)
    _import_csv(app, c)
    with app.app_context():
        from mdc_erp.models import BankStatement, JournalLine, BankAccount
        st = BankStatement.query.first()
        sid = st.id
        dep = [l for l in st.lines if (l.amount or 0) > 0 and not l.is_duplicate][0].id
        jl = JournalLine.query.filter_by(account_id=BankAccount.query.get(app._baid).account_id).first().id
    c.get(f'/bankrec/line/{dep}/match/{jl}?m=1', follow_redirects=True)
    with app.app_context():
        from mdc_erp.models import BankStatementLine
        assert BankStatementLine.query.get(dep).matched is True
    c.get(f'/bankrec/line/{dep}/unmatch', follow_redirects=True)
    with app.app_context():
        from mdc_erp.models import BankStatementLine, JournalLine
        assert BankStatementLine.query.get(dep).matched is False
        assert JournalLine.query.get(jl).cleared in (False, None)


def test_approval_workflow_and_gate(app):
    c = _client(app)
    _import_csv(app, c)
    with app.app_context():
        from mdc_erp.models import BankStatement
        sid = BankStatement.query.first().id
    c.get(f'/bankrec/{sid}/automatch', follow_redirects=True)
    # match remaining lines so all matched
    with app.app_context():
        from mdc_erp.models import BankStatement
        st = BankStatement.query.get(sid)
        rest = [l.id for l in st.lines if not l.matched]
    for lid in rest:
        c.post(f'/bankrec/line/{lid}/payment', data={'account': app._rev, '_csrf': _tok(c)}, follow_redirects=True)
    c.get(f'/bankrec/{sid}/reconciled', follow_redirects=True)
    with app.app_context():
        from mdc_erp.models import BankStatement
        assert BankStatement.query.get(sid).status == 'Reconciled'
    # a non-approver (cashier) cannot approve
    cash = _client(app, 'cashier')
    if cash is not None:
        assert cash.get(f'/bankrec/{sid}/approve').status_code == 403
    # approver can
    c.get(f'/bankrec/{sid}/approve', follow_redirects=True)
    with app.app_context():
        from mdc_erp.models import BankStatement
        st = BankStatement.query.get(sid)
        assert st.status == 'Approved' and st.approved_by


def test_permission_denied(app):
    lt = _client(app, 'lab_tech')
    if lt is not None:
        assert b'No access' in lt.get('/m/bankrec').data
        assert lt.get('/bankrec/import').status_code == 403
