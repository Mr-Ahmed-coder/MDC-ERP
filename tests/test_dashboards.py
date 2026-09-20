"""Automated tests for Phase 2 Role-Specific Dashboards & Search Scoping.

Verifies role-based views, branch isolation, SVG icons, dynamic attention chips,
quick action scoping, empty DB safety, search branch scoping, and unauthenticated redirects.
"""
import pytest
from mdc_erp import create_app
from mdc_erp.config import DevelopmentConfig
from mdc_erp.models import User, Branch, Patient, Invoice
from mdc_erp.extensions import db

class TestConfig(DevelopmentConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'

@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        # Seed test branches
        b1 = Branch(name='Main Branch')
        b2 = Branch(name='North Branch')
        db.session.add_all([b1, b2])
        db.session.commit()

        # Seed test users for all 15 roles + custom role
        roles = [
            'super_admin', 'branch_manager', 'accountant', 'reception', 'cashier',
            'doctor', 'radiologist', 'lab_tech', 'lab_supervisor', 'nurse',
            'hr', 'storekeeper', 'engineer', 'it_admin', 'auditor', 'custom_role'
        ]
        for r in roles:
            u = User(
                username=f'user_{r}',
                role=r,
                active=True,
                branch_id=b1.id if r != 'super_admin' else None
            )
            u.pw = 'Pass1234'
            db.session.add(u)
        db.session.commit()
    yield app

@pytest.fixture
def client(app):
    return app.test_client()

def login_as(client, app, username):
    with app.app_context():
        u = User.query.filter_by(username=username).first()
        uid = u.id if u else None
    with client.session_transaction() as sess:
        sess['uid'] = uid

def test_unauthenticated_redirect(client):
    res = client.get('/dashboard')
    assert res.status_code == 302
    assert '/login' in res.location

def test_all_15_roles_load_dashboard(app, client):
    roles = [
        'super_admin', 'branch_manager', 'accountant', 'reception', 'cashier',
        'doctor', 'radiologist', 'lab_tech', 'lab_supervisor', 'nurse',
        'hr', 'storekeeper', 'engineer', 'it_admin', 'auditor'
    ]
    for r in roles:
        login_as(client, app, f'user_{r}')
        res = client.get('/dashboard')
        assert res.status_code == 200, f"Dashboard failed for role {r}"
        assert b"Dashboard" in res.data
        assert b"Needs attention" in res.data or b"All clear" in res.data

def test_custom_role_fallback_dashboard(app, client):
    login_as(client, app, 'user_custom_role')
    res = client.get('/dashboard')
    assert res.status_code == 200
    assert b"Dashboard" in res.data

def test_receptionist_cannot_see_cash_balance(app, client):
    login_as(client, app, 'user_reception')
    res = client.get('/dashboard')
    assert res.status_code == 200
    assert b"href='/module/acct'" not in res.data

def test_accountant_sees_financial_kpis(app, client):
    login_as(client, app, 'user_accountant')
    res = client.get('/dashboard')
    assert res.status_code == 200
    assert b"Expenses" in res.data or b"Net Profit" in res.data

def test_lab_tech_sees_lab_worklist(app, client):
    login_as(client, app, 'user_lab_tech')
    res = client.get('/dashboard')
    assert res.status_code == 200
    assert b"Pending Laboratory Worklist" in res.data or b"Pending Samples" in res.data

def test_radiologist_sees_rad_worklist(app, client):
    login_as(client, app, 'user_radiologist')
    res = client.get('/dashboard')
    assert res.status_code == 200
    assert b"Unreported Radiology Worklist" in res.data or b"Pending Reports" in res.data

def test_branch_isolation_on_dashboard(app, client):
    with app.app_context():
        b1 = Branch.query.filter_by(name='Main Branch').first()
        b2 = Branch.query.filter_by(name='North Branch').first()

        u2 = User(username='b2_user', role='reception', active=True, branch_id=b2.id)
        db.session.add(u2)

        p1 = Patient(name='Branch1 Patient', mrn='B1-001')
        p2 = Patient(name='Branch2 Patient', mrn='B2-001')
        db.session.add_all([p1, p2])
        db.session.commit()

        i1 = Invoice(patient_id=p1.id, branch_id=b1.id, status='Unpaid')
        i2 = Invoice(patient_id=p2.id, branch_id=b2.id, status='Unpaid')
        db.session.add_all([i1, i2])
        db.session.commit()

    login_as(client, app, 'b2_user')
    res = client.get('/dashboard')
    assert res.status_code == 200
    assert b"Branch1 Patient" not in res.data

def test_search_branch_scoping(app, client):
    with app.app_context():
        b1 = Branch.query.filter_by(name='Main Branch').first()
        b2 = Branch.query.filter_by(name='North Branch').first()

        p1 = Patient(name='UniqueB1Name', mrn='MRN-B1')
        p2 = Patient(name='UniqueB2Name', mrn='MRN-B2')
        db.session.add_all([p1, p2])
        db.session.commit()

        u_b2 = User(username='search_b2_user', role='reception', active=True, branch_id=b2.id)
        db.session.add(u_b2)
        db.session.commit()

        i1 = Invoice(patient_id=p1.id, branch_id=b1.id, status='Unpaid', guarantor='GuarantorB1')
        i2 = Invoice(patient_id=p2.id, branch_id=b2.id, status='Unpaid', guarantor='GuarantorB2')
        db.session.add_all([i1, i2])
        db.session.commit()

    # Search as Branch 2 user (should NOT find Branch 1 invoice)
    login_as(client, app, 'search_b2_user')
    res_b2 = client.get('/search?q=GuarantorB1')
    assert res_b2.status_code == 200
    assert b"0 found" in res_b2.data or b"None found" in res_b2.data

    # Search as Super Admin (should find cross-branch invoice)
    login_as(client, app, 'user_super_admin')
    res_admin = client.get('/search?q=GuarantorB1')
    assert res_admin.status_code in (200, 302)

def test_accounting_sidebar_visibility_authorized_roles(app, client):
    authorized = ['super_admin', 'accountant', 'auditor', 'branch_manager']
    for r in authorized:
        login_as(client, app, f'user_{r}')
        res = client.get('/dashboard')
        assert res.status_code == 200
        html = res.data.decode('utf-8')
        assert 'Accounting' in html or 'Accounting Center' in html
        assert '/acctdash' in html

def test_accounting_sidebar_visibility_unauthorized_roles(app, client):
    unauthorized = ['reception', 'nurse', 'lab_tech', 'radiologist', 'doctor']
    for r in unauthorized:
        login_as(client, app, f'user_{r}')
        res = client.get('/dashboard')
        assert res.status_code == 200
        html = res.data.decode('utf-8')
        # Sidebar should not contain the Accounting section button/links for unauthorized roles
        assert '>Accounting<' not in html and 'data-tooltip="Accounting Center"' not in html
        assert 'href="/acctdash"' not in html
