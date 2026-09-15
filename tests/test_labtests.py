"""Laboratory Tests catalog — role-based price hiding.

Lab technicians and lab supervisors see the test names but NOT the price;
price-privileged roles (admin, doctor, radiologist, accountant) see it.
Also exercises the generic register(hide_columns=) mechanism.
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
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'lt.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User, Service
        from werkzeug.security import generate_password_hash
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.add_all([
            Service(code='CBC', name='CBC', department='Laboratory', price=7, active=True),
            Service(code='GLU', name='Blood Glucose', department='Laboratory', price=5, active=True),
        ])
        for r in ('lab_tech', 'lab_supervisor', 'radiologist'):
            if not User.query.filter_by(role=r).first():
                db.session.add(User(username=r + '1', name=r, role=r,
                                    pw=generate_password_hash('x'), active=True))
        db.session.commit()
    return app


def _client(app, role):
    with app.app_context():
        from mdc_erp.models import User
        u = User.query.filter_by(role=role).first()
        uid = u.id if u else None
    if uid is None:
        return None
    c = app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    return c


def test_admin_sees_price(app):
    c = _client(app, 'super_admin')
    d = c.get('/m/labtests').get_data(as_text=True)
    assert 'CBC' in d and 'Blood Glucose' in d
    assert '>Price<' in d or '<th>Price</th>' in d
    assert '$7' in d                      # price value visible


def test_lab_tech_price_hidden(app):
    c = _client(app, 'lab_tech')
    d = c.get('/m/labtests').get_data(as_text=True)
    assert d and 'CBC' in d               # can see the tests
    assert '$7' not in d and '$5' not in d  # but not the prices
    assert 'Prices are hidden' in d       # explanatory note
    # no advanced-filter field list exposing price fields
    assert 'advpanel' not in d


def test_lab_supervisor_price_hidden(app):
    c = _client(app, 'lab_supervisor')
    if c is None:
        pytest.skip('no lab_supervisor role seeded')
    d = c.get('/m/labtests').get_data(as_text=True)
    assert 'CBC' in d and '$7' not in d


def test_radiologist_sees_price(app):
    c = _client(app, 'radiologist')
    if c is None:
        pytest.skip('no radiologist role')
    d = c.get('/m/labtests').get_data(as_text=True)
    assert '$7' in d                      # price-privileged role keeps the column


def test_service_catalog_hide_columns_admin_unaffected(app):
    # the generic hide_columns must not affect a privileged role
    c = _client(app, 'super_admin')
    d = c.get('/m/services').get_data(as_text=True)
    assert 'Price' in d
