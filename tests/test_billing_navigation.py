"""Billing & Cashier grouped navigation regression tests."""
import re

import pytest
from werkzeug.security import generate_password_hash

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'billing-nav.db'}"

    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User

        for role in ("super_admin", "accountant", "reception", "lab_tech"):
            user = User.query.filter_by(role=role).first()
            if user:
                user.must_change_pw = False
        if not User.query.filter_by(role="cashier").first():
            db.session.add(User(
                username="cashier_nav",
                name="Navigation Cashier",
                role="cashier",
                pw=generate_password_hash("test-only-password"),
                active=True,
                must_change_pw=False,
            ))
        db.session.commit()
    return app


def _client(app, role):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User

        user = User.query.filter_by(role=role).first()
        assert user is not None, f"missing seeded role {role}"
        user.must_change_pw = False
        db.session.commit()
        user_id = user.id
    client = app.test_client()
    with client.session_transaction() as session:
        session["uid"] = user_id
    return client


def _desktop(html):
    match = re.search(r'<nav class="mbar-desktop"[^>]*data-menu="billing".*?</nav>', html, re.S)
    assert match, "Billing desktop navigation is missing"
    return match.group(0)


def _mobile(html):
    start = html.find('<div class="mbar-mobile-wrap">')
    end = html.find('<script>', start)
    assert start >= 0 and end > start, "Billing mobile navigation is missing"
    return html[start:end]


def test_daily_transactions_is_not_duplicated_within_either_menu(app):
    html = _client(app, "super_admin").get("/m/invoices").get_data(as_text=True)
    assert _desktop(html).count('data-nav-key="dailytx"') == 1
    assert _mobile(html).count('data-nav-key="dailytx"') == 1


@pytest.mark.parametrize("role", ["super_admin", "accountant", "cashier", "reception"])
def test_authorized_roles_receive_billing_navigation(app, role):
    html = _client(app, role).get("/m/invoices").get_data(as_text=True)
    assert 'data-menu="billing"' in html
    assert "Billing &amp; Cashier" in html or "Billing & Cashier" in html
    assert "Daily Transactions" in html


def test_unauthorized_links_and_empty_groups_are_hidden(app):
    cashier_html = _client(app, "cashier").get("/m/invoices").get_data(as_text=True)
    desktop = _desktop(cashier_html)
    assert "Receive Payment" in desktop
    assert "Daily Cash Closing" in desktop
    assert "Credit Notes" not in desktop
    assert "Service Catalog" not in desktop
    assert "Doctor Commission" not in desktop
    assert "Commission Payables" not in desktop
    assert ">Commissions " not in desktop

    lab_html = _client(app, "lab_tech").get("/dashboard").get_data(as_text=True)
    assert 'data-menu="billing"' not in lab_html


def test_active_group_and_child_are_highlighted(app):
    html = _client(app, "super_admin").get("/m/dailytx").get_data(as_text=True)
    desktop = _desktop(html)
    mobile = _mobile(html)
    assert re.search(r'class="mb-top on"[^>]*>Payments &amp; Cashier', desktop)
    assert re.search(r'class="on"[^>]*data-nav-key="dailytx"', desktop)
    assert re.search(r'class="mbar-mobile-link on"[^>]*data-nav-key="dailytx"', mobile)


def test_all_existing_billing_destinations_still_render(app):
    client = _client(app, "super_admin")
    destinations = (
        "invoices",
        "creditnotes",
        "services",
        "payalloc",
        "dailytx",
        "cashclose",
        "paycenter",
        "commission",
        "payables",
    )
    for destination in destinations:
        response = client.get(f"/m/{destination}", follow_redirects=True)
        assert response.status_code == 200, f"Billing destination failed: {destination}"


def test_mobile_billing_menu_uses_shared_accessible_drawer(app):
    html = _client(app, "super_admin").get("/m/invoices").get_data(as_text=True)
    mobile = _mobile(html)
    assert "Billing Menu:" in mobile
    assert 'class="mbar-mobile-btn"' in mobile
    assert 'aria-expanded="false"' in mobile
    assert 'aria-controls="billing-mobile-drawer"' in mobile
    assert 'id="billing-mobile-drawer"' in mobile


def test_commission_payables_keeps_its_existing_permission(app):
    accountant = _desktop(_client(app, "accountant").get("/m/invoices").get_data(as_text=True))
    reception = _desktop(_client(app, "reception").get("/m/invoices").get_data(as_text=True))
    assert "Commission Payables" in accountant
    assert "Commission Payables" not in reception
