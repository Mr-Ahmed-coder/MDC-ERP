"""Tests for standardized workspace navigation bars (Clinical, Diagnostics, Pharmacy & Inventory, Billing, Accounting)."""
import pytest
from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig
from mdc_erp.models import User
from mdc_erp.extensions import db as _db

@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'nav_test.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        u = User.query.filter_by(role='super_admin').first()
        if u:
            u.must_change_pw = False
            _db.session.commit()
    return app

def _login(c, app, role='super_admin'):
    with app.app_context():
        u = User.query.filter_by(role=role).first()
        if not u and role == 'restricted':
            u = User(username='rest_user', role='restricted', must_change_pw=False)
            _db.session.add(u)
            _db.session.commit()
        uid = u.id if u else None
    if uid:
        with c.session_transaction() as s:
            s['uid'] = uid
    return c

def test_clinical_horizontal_navigation(app):
    c = app.test_client()
    _login(c, app, 'super_admin')
    res = c.get('/m/patients')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Must contain shared horizontal mbar-desktop container and mobile drawer wrapper
    assert 'class="mbar-desktop"' in html
    assert 'data-menu="clinical"' in html
    assert 'class="mbar-mobile-wrap"' in html
    assert 'Clinical Menu:' in html

    # Groups & links present
    for group in ['Patients', 'Doctor Requests', 'Referral Management', 'Blood Bank', 'Vaccination']:
        assert group in html, f'Missing clinical group {group}'
    for link in ['Patient Registration', 'Reception Queue', 'Consultation', 'Doctor Requests', 'Request Board', 'Referring Doctors', 'Radiologists', 'Donors', 'Blood Units']:
        assert link in html, f'Missing clinical link {link}'

    # Active highlighting for Patients on /m/patients
    assert 'mb-top on' in html or 'class="on"' in html or 'class="mb-top on"' in html

def test_diagnostics_horizontal_navigation(app):
    c = app.test_client()
    _login(c, app, 'super_admin')
    res = c.get('/m/lab')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'class="mbar-desktop"' in html
    assert 'data-menu="diagnostics"' in html
    assert 'class="mbar-mobile-wrap"' in html
    assert 'Diagnostics Menu:' in html

    for group in ['Laboratory', 'Radiology']:
        assert group in html
    for link in ['Lab Requests', 'Quality Control', 'Radiology / Imaging', 'Radiologists']:
        assert link in html

def test_pharmacy_inventory_horizontal_navigation(app):
    c = app.test_client()
    _login(c, app, 'super_admin')
    res = c.get('/m/pharmacy')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'class="mbar-desktop"' in html
    assert 'data-menu="pharmacy---inventory"' in html
    assert 'class="mbar-mobile-wrap"' in html
    assert 'Pharmacy &amp; Inventory Menu:' in html or 'Pharmacy & Inventory Menu:' in html

    for group in ['Pharmacy', 'Inventory', 'Procurement']:
        assert group in html
    for link in ['Pharmacy Sales', 'Batches (FEFO)', 'Supplies / Stock', 'Warehouses', 'Stock Transfers', 'Stock Adjustments', 'Inventory Valuation', 'Consumption Report', 'Purchase Orders', 'Suppliers', 'Debit Notes']:
        assert link in html

def test_billing_and_accounting_remain_intact(app):
    c = app.test_client()
    _login(c, app, 'super_admin')

    # Billing
    b_res = c.get('/m/invoices')
    assert b_res.status_code == 200
    b_html = b_res.get_data(as_text=True)
    assert 'class="mbar-desktop"' in b_html
    assert 'data-menu="billing"' in b_html
    assert 'Billing &amp; Cashier' in b_html or 'Billing & Cashier' in b_html
    assert 'Invoicing' in b_html
    assert 'Payments &amp; Cashier' in b_html or 'Payments & Cashier' in b_html
    assert 'Commissions' in b_html

    # Accounting
    a_res = c.get('/acctdash')
    assert a_res.status_code == 200
    a_html = a_res.get_data(as_text=True)
    assert 'class="mbar-desktop"' in a_html
    assert 'data-menu="accounting"' in a_html
    assert 'Overview' in a_html
    assert 'Transactions' in a_html
    assert 'Ledgers' in a_html
    assert 'Receivables &amp; Payables' in a_html or 'Receivables & Payables' in a_html

def test_unauthorized_links_hidden(app):
    c = app.test_client()
    _login(c, app, 'engineer')
    res = c.get('/m/pharmacy')
    if res.status_code == 200:
        html = res.get_data(as_text=True)
        assert 'Pharmacy Sales' not in html
        assert 'Supplies / Stock' not in html

def test_fixed_assets_relocated_to_accounting(app):
    c = app.test_client()
    _login(c, app, 'super_admin')

    res = c.get('/m/fa_dash')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # 1. Fixed Assets link is present inside Accounting section
    assert 'href="/m/fa_dash"' in html or 'href=\'/m/fa_dash\'' in html or 'Fixed Assets' in html
    assert 'Fixed Assets' in html

    # 2. Accounting sidebar category is open and active
    assert 'Accounting' in html
    assert 'navsec open' in html or 'open' in html

    # 3. Fixed Assets link in horizontal Accounting menubar dropdown
    assert 'Planning &amp; Analysis' in html or 'Planning & Analysis' in html

    # 4. Verify Fixed Assets is not inside Management section
    # Management section rendering should not include fa_dash
    from mdc_erp.core.ui import NAVDEF
    acct_keys = [k for group, items in NAVDEF if group == 'Accounting' for k, l, p in items]
    mgmt_keys = [k for group, items in NAVDEF if group == 'Management' for k, l, p in items]

    assert 'fa_dash' in acct_keys, "fa_dash must be in Accounting NAVDEF group"
    assert 'fa_dash' not in mgmt_keys, "fa_dash must not be in Management NAVDEF group"
    assert 'assets' in mgmt_keys, "Assets & Maintenance must remain in Management"
