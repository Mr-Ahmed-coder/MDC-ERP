import pytest

pytest_plugins = ['test_smoke']

from mdc_erp.extensions import db
from mdc_erp.models import Patient, Invoice, RecordArchive
from mdc_erp.core.record_lifecycle import archive_record, restore_archive, delete_record


def test_archive_and_restore_preserves_record(app):
    with app.app_context():
        patient = Patient(mrn='ARCH-0001', name='Archive Test')
        db.session.add(patient)
        db.session.commit()

        archive = archive_record(patient, 'Duplicate test record', label='Archive Test')
        db.session.commit()
        assert archive.active is True
        assert patient.active is False
        assert RecordArchive.query.count() >= 1

        restored = restore_archive(archive)
        db.session.commit()
        assert restored.id == patient.id
        assert patient.active is True
        assert archive.active is False


def test_financial_records_cannot_be_hard_deleted(app):
    with app.app_context():
        invoice = Invoice(status='Draft')
        db.session.add(invoice)
        db.session.commit()
        with pytest.raises(ValueError, match='protected'):
            delete_record(invoice, 'Must not delete accounting history')
        db.session.rollback()
