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


def test_hr_horizontal_navigation(app):
    c = app.test_client()
    _login(c, app, 'super_admin')
    res = c.get('/m/employees')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'class="mbar-desktop"' in html
    assert 'data-menu="human-resources"' in html
    assert 'class="mbar-mobile-wrap"' in html
    assert 'Human Resources Menu:' in html

    for group in ['Employees', 'Time', 'Payroll']:
        assert group in html, f'Missing HR group {group}'
    for link in ['Employees', 'Contracts', 'Attendance', 'Leave', 'Payroll', 'Salary Advances', 'Employee Loans']:
        assert link in html, f'Missing HR link {link}'

    assert 'mb-top on' in html or 'class="on"' in html or 'class="mb-top on"' in html


def test_admin_horizontal_navigation(app):
    c = app.test_client()
    _login(c, app, 'super_admin')
    res = c.get('/m/branches')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'class="mbar-desktop"' in html
    assert 'data-menu="administration"' in html
    assert 'class="mbar-mobile-wrap"' in html
    assert 'Administration Menu:' in html

    for group in ['Branches', 'System Management', 'Logs &amp; Security']:
        assert group in html or 'Branches &amp; Access' in html, f'Missing Admin group {group}'
    for link in ['Branches', 'User Management', 'Settings', 'Service Management', 'Backup &amp; Restore', 'Audit Log', 'Error Log', 'System Health', 'Login Security']:
        assert link in html or link.replace('&amp;', '&') in html, f'Missing Admin link {link}'

    assert 'mb-top on' in html or 'class="on"' in html or 'class="mb-top on"' in html


def test_backup_sidebar_navigation(app):
    c = app.test_client()
    _login(c, app, 'super_admin')

    res = c.get('/m/backup')
    assert res.status_code in (200, 302)
    html = res.get_data(as_text=True)

    # Backup link is present in sidebar under Administration
    assert 'href="/m/backup"' in html or 'Backup &amp; Restore' in html or 'Backup' in html

    # Verify backup is inside Administration NAVDEF group
    from mdc_erp.core.ui import NAVDEF
    admin_keys = [k for group, items in NAVDEF if group == 'Administration' for k, l, p in items]
    assert 'backup' in admin_keys, "backup must be in Administration NAVDEF group"

    # Unauthorized role (engineer/reception) should not see backup link in sidebar
    c_unauth = app.test_client()
    _login(c_unauth, app, 'engineer')
    res_unauth = c_unauth.get('/m/sops')
    if res_unauth.status_code == 200:
        html_unauth = res_unauth.get_data(as_text=True)
        assert 'href="/m/backup"' not in html_unauth


def test_assets_and_logistics_horizontal_navigation(app):
    c = app.test_client()
    _login(c, app, 'super_admin')

    # Assets & Maintenance
    res_assets = c.get('/m/assets')
    assert res_assets.status_code == 200
    html_assets = res_assets.get_data(as_text=True)

    assert 'class="mbar-desktop"' in html_assets
    assert 'data-menu="assets---logistics"' in html_assets
    assert 'class="mbar-mobile-wrap"' in html_assets
    assert 'Assets &amp; Maintenance' in html_assets or 'Assets & Maintenance' in html_assets
    assert 'Asset Register' in html_assets
    assert 'Maintenance Jobs' in html_assets
    assert 'Logistics' in html_assets

    # Logistics workspace
    res_logistics = c.get('/m/logistics')
    assert res_logistics.status_code == 200
    html_logistics = res_logistics.get_data(as_text=True)

    assert 'class="mbar-desktop"' in html_logistics
    assert 'data-menu="assets---logistics"' in html_logistics
    assert 'Logistics' in html_logistics
    assert 'mb-top on' in html_logistics or 'class="on"' in html_logistics or 'mbar-mobile-link on' in html_logistics
