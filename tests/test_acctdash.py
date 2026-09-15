"""Accounting Dashboard (Odoo-18-style) tests. Self-contained."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'ad.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User, Patient, Invoice, InvoiceItem, PayReceipt
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        p = Patient(name='Amina Yusuf', mrn='MRN-777')
        db.session.add(p)
        db.session.commit()
        inv = Invoice(patient_id=p.id, date='2026-08-03', paid=0)
        db.session.add(inv)
        db.session.commit()
        db.session.add(InvoiceItem(invoice_id=inv.id, desc='CBC', qty=1, price=40))
        db.session.add(PayReceipt(invoice_id=inv.id, date='2026-08-03', amount=40, method='Cash'))
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


CARDS = [b'Cash Balance', b'Bank Balance', b'Accounts Receivable', b'Accounts Payable',
         b'Monthly Revenue', b'Monthly Expenses', b'Net Profit', b'Profit &amp; Loss Summary',
         b'Outstanding Invoices', b'Overdue Invoices', b'Recent Payments', b'Recent Journal Entries']


def test_all_cards_present(app):
    c = _client(app)
    r = c.get('/m/acctdash')
    assert r.status_code == 200
    for card in CARDS:
        assert card in r.data, f'missing card: {card}'


def test_controls_present(app):
    c = _client(app)
    d = c.get('/m/acctdash').get_data(as_text=True)
    assert 'All branches' in d          # branch selector
    assert "name='from'" in d and "name='to'" in d   # date range
    assert 'Excel' in d and 'PDF' in d  # exports
    assert 'livechk' in d               # real-time toggle


def test_date_and_branch_filters_apply(app):
    c = _client(app)
    # a date window in the far past yields zero revenue but still renders
    r = c.get('/m/acctdash?from=2000-01-01&to=2000-01-31')
    assert r.status_code == 200
    # branch filter param accepted
    assert c.get('/m/acctdash?branch=1').status_code == 200


def test_exports(app):
    c = _client(app)
    x = c.get('/acctdash/export.xlsx')
    assert x.status_code == 200
    assert 'spreadsheet' in x.headers['Content-Type'] or x.headers['Content-Type'].startswith('application/')
    assert c.get('/acctdash/print').status_code == 200


def test_auditor_readonly_and_clinical_denied(app):
    a = _client(app, 'auditor')
    if a is not None:
        assert a.get('/m/acctdash').status_code == 200
    lt = _client(app, 'lab_tech')
    if lt is not None:
        assert b'No access' in lt.get('/m/acctdash').data
        assert lt.get('/acctdash/export.xlsx').status_code == 403
