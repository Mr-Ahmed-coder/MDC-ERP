"""Odoo-style document action dialog (Print/Download/Open) tests."""
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'da.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User, Patient, Invoice, InvoiceItem
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        p = Patient(name='Amina Yusuf', mrn='MRN-777')
        db.session.add(p)
        db.session.commit()
        inv = Invoice(patient_id=p.id, date='2026-08-03')
        db.session.add(inv)
        db.session.commit()
        db.session.add(InvoiceItem(invoice_id=inv.id, desc='CBC', qty=1, price=15))
        db.session.commit()
        app._iid = inv.id
        uid = u.id
    app._uid = uid
    return app


def _login(app, c):
    with c.session_transaction() as s:
        s['uid'] = app._uid


def test_dialog_injected_on_every_page(app):
    c = app.test_client()
    _login(app, c)
    d = c.get('/m/invoices').get_data(as_text=True)
    assert 'mdcdoc' in d and 'What do you want to do?' in d
    assert 'MDCDoc' in d and 'Print' in d and 'Download' in d and 'Open' in d


def test_invoice_view_triggers_dialog(app):
    c = app.test_client()
    _login(app, c)
    d = c.get(f'/invoice/{app._iid}').get_data(as_text=True)
    assert 'MDCDoc.open' in d
    # the three real targets are present
    assert f'/invoice/{app._iid}/print?auto=1' in d
    assert f'/invoice/{app._iid}/pdf' in d


def test_auto_print_on_print_view(app):
    c = app.test_client()
    _login(app, c)
    normal = c.get(f'/invoice/{app._iid}/print').get_data(as_text=True)
    auto = c.get(f'/invoice/{app._iid}/print?auto=1').get_data(as_text=True)
    assert 'window.print()' in auto
    # without ?auto the page does not force a print dialog on load
    assert 'setTimeout(function(){window.print()}' not in normal


def test_global_print_interceptor_present(app):
    c = app.test_client()
    _login(app, c)
    d = c.get('/m/invoices').get_data(as_text=True)
    # the interceptor that turns every print link into the dialog
    assert 'isDoc' in d and 'MDCDoc.open' in d and '/receipt/' in d


def test_auto_print_on_other_documents(app):
    c = app.test_client()
    _login(app, c)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Patient, Service, LabOrder, RadOrder
        p = Patient.query.first()
        sv = Service(code='CBC', name='CBC', department='Laboratory', price=7, active=True)
        db.session.add(sv)
        db.session.commit()
        lo = LabOrder(patient_id=p.id, service_id=sv.id, status='Resulted', date='2026-08-03', sample_no='S1')
        ro = RadOrder(patient_id=p.id, modality='X-ray', status='Reported', date='2026-08-03')
        db.session.add_all([lo, ro])
        db.session.commit()
        loid, roid, pid = lo.id, ro.id, p.id
    for url in (f'/lab/{loid}/print', f'/rad/{roid}/print', f'/patient/{pid}/card'):
        assert 'window.print()' in c.get(url + '?auto=1').get_data(as_text=True)
