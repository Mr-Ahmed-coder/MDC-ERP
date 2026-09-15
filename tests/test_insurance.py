"""Insurance (Phase 3, v8.0) end-to-end tests.

Covers the claim lifecycle (create -> submit -> respond -> reconcile), the
accounting posting that clears the 1250 Insurance Receivable, pre-auth, and RBAC.
Self-contained.
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
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'ins.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.commit()
    return app


def _login(app, client, role='super_admin'):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role=role).first()
        if not u:
            return None
        u.must_change_pw = False
        db.session.commit()
        uid = u.id
    with client.session_transaction() as s:
        s['uid'] = uid
        s['_csrf'] = 'tok'
    return uid


def _seed(app):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Patient, Insurer, InsuranceCard
        p = Patient(name='Ins Pt', mrn='MRN-INS1', phone='0')
        ins = Insurer(name='ACME Health', code='ACME', coverage_pct=80, ar_account='1250', active=True)
        db.session.add_all([p, ins])
        db.session.commit()
        card = InsuranceCard(patient_id=p.id, insurer_id=ins.id, policy_no='P123',
                             coverage_pct=80, active=True)
        db.session.add(card)
        db.session.commit()
        return p.id, ins.id


def test_claim_lifecycle_and_reconciliation(app):
    client = app.test_client()
    _login(app, client)
    pid, iid = _seed(app)
    D = {'_csrf': 'tok'}

    # create a Draft claim for 800
    r = client.post('/insurance/claim/new',
                    data={**D, 'patient_id': pid, 'insurer_id': iid, 'claimed': '800'},
                    follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Claim
        c = Claim.query.first()
        assert c and c.status == 'Draft' and c.claim_no
        cid = c.id

    # submit
    client.get(f'/insurance/claim/{cid}/submit')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Claim
        assert db.session.get(Claim, cid).status == 'Submitted'

    # payer approves 600 of 800 -> Partial
    r = client.post(f'/insurance/claim/{cid}/respond', data={**D, 'approved': '600'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Claim
        c = db.session.get(Claim, cid)
        assert c.status == 'Partial' and (c.approved or 0) == 600

    # reconcile: insurer pays the 600 -> Paid, and 1250 is credited
    r = client.post(f'/insurance/claim/{cid}/reconcile',
                    data={**D, 'amount': '600', 'method': 'Bank', 'date': '2026-02-01'})
    assert r.status_code == 302
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Claim, JournalEntry, JournalLine, Account
        c = db.session.get(Claim, cid)
        assert (c.paid or 0) == 600 and c.status == 'Paid'
        je = JournalEntry.query.filter_by(ref=f'CLAIM-PAY-{cid}').first()
        assert je is not None, 'reconciliation posted a journal'
        ar = Account.query.filter_by(code='1250').first()
        cr_to_ar = JournalLine.query.filter_by(entry_id=je.id, account_id=ar.id).first()
        assert cr_to_ar and (cr_to_ar.credit or 0) == 600, '1250 receivable credited (cleared)'


def test_claim_rejection(app):
    client = app.test_client()
    _login(app, client)
    pid, iid = _seed(app)
    D = {'_csrf': 'tok'}
    client.post('/insurance/claim/new', data={**D, 'patient_id': pid, 'insurer_id': iid, 'claimed': '500'})
    with app.app_context():
        from mdc_erp.models import Claim
        cid = Claim.query.first().id
    client.post(f'/insurance/claim/{cid}/reject', data={**D, 'reject_reason': 'Not covered'})
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import Claim
        c = db.session.get(Claim, cid)
        assert c.status == 'Rejected' and c.reject_reason == 'Not covered'


def test_preauth_approve(app):
    client = app.test_client()
    _login(app, client)
    pid, iid = _seed(app)
    D = {'_csrf': 'tok'}
    client.post('/insurance/preauth/new',
                data={**D, 'patient_id': pid, 'insurer_id': iid, 'description': 'MRI', 'est_amount': '300'})
    with app.app_context():
        from mdc_erp.models import PreAuth
        paid_ = PreAuth.query.first().id
    client.get(f'/insurance/preauth/{paid_}/approve')
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import PreAuth
        p = db.session.get(PreAuth, paid_)
        assert p.status == 'Approved' and p.auth_code and p.auth_code.startswith('PA-')


def test_insurance_rbac_denies(app):
    client = app.test_client()
    # lab_tech is not in the insurance permission list
    if _login(app, client, role='lab_tech') is None:
        pytest.skip('no lab_tech role')
    assert client.get('/insurance/claim/new').status_code == 403
