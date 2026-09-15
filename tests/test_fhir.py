"""FHIR R4 API (Phase 6, v8.0) end-to-end tests.

Exercises the public CapabilityStatement, JWT auth enforcement, and read/search
for every supported resource type against seeded data. Self-contained.
"""
import json
import pytest

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


@pytest.fixture()
def app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'fhir.db'}"
    app = create_app(Cfg)
    init_db(app, demo=True)
    return app


@pytest.fixture()
def token(app):
    c = app.test_client()
    r = c.post('/api/login', json={'username': 'admin', 'password': 'admin123'})
    assert r.status_code == 200, r.data
    return r.get_json()['data']['token']


def _hdr(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture()
def seeded(app):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import (Patient, Service, LabOrder, LabResultValue,
                                     RadOrder, ImgStudy, Doctor, Consultation,
                                     Medicine, Prescription)
        p = Patient(name='Amina Yusuf', mrn='MRN-FHIR1', gender='Female', dob='1990-05-01', phone='615')
        svc = Service(name='CBC', department='Lab', active=True)
        med = Medicine(name='Paracetamol')
        doc = Doctor(name='Dr Ali Hassan', specialty='Cardiology', active=True)
        db.session.add_all([p, svc, med, doc])
        db.session.commit()
        lo = LabOrder(patient_id=p.id, service_id=svc.id, status='Resulted', date='2026-02-01')
        db.session.add(lo)
        db.session.commit()
        db.session.add(LabResultValue(order_id=lo.id, name='Hemoglobin', value='6.5',
                                      unit='g/dL', ref_low=13, ref_high=17, flag='LL', source='Analyzer'))
        ro = RadOrder(patient_id=p.id, modality='CT', status='Reported', date='2026-02-02')
        study = ImgStudy(patient_id=p.id, modality='CT', description='Brain CT',
                         num_series=2, num_instances=3, study_date='2026-02-02')
        con = Consultation(patient_id=p.id, doctor='Dr Ali Hassan', diagnosis='Anemia',
                           icd_code='D64.9', date='2026-02-01', status='Completed')
        db.session.add_all([ro, study, con])
        db.session.commit()
        db.session.add(Prescription(patient_id=p.id, medicine_id=med.id, dosage='1 tab BD',
                                    doctor='Dr Ali Hassan', status='Pending', date='2026-02-01'))
        db.session.commit()
        return {'pid': p.id, 'study': study.id, 'med': med.id, 'doc': doc.id}


def test_metadata_public(app):
    c = app.test_client()
    r = c.get('/fhir/metadata')                      # no token needed
    assert r.status_code == 200
    assert r.headers['Content-Type'].startswith('application/fhir+json')
    cs = r.get_json()
    assert cs['resourceType'] == 'CapabilityStatement' and cs['fhirVersion'] == '4.0.1'


def test_auth_required(app):
    c = app.test_client()
    r = c.get('/fhir/Patient/1')
    assert r.status_code == 401
    assert r.get_json()['resourceType'] == 'OperationOutcome'


def test_patient_read_and_search(app, token, seeded):
    c = app.test_client()
    r = c.get(f"/fhir/Patient/{seeded['pid']}", headers=_hdr(token))
    assert r.status_code == 200
    p = r.get_json()
    assert p['resourceType'] == 'Patient' and p['gender'] == 'female'
    assert p['identifier'][0]['value'] == 'MRN-FHIR1'

    r = c.get('/fhir/Patient?name=Amina', headers=_hdr(token))
    b = r.get_json()
    assert b['resourceType'] == 'Bundle' and b['total'] >= 1
    assert b['entry'][0]['resource']['resourceType'] == 'Patient'


def test_observation_and_report(app, token, seeded):
    c = app.test_client()
    pid = seeded['pid']
    r = c.get(f'/fhir/Observation?patient={pid}', headers=_hdr(token))
    obs = r.get_json()['entry']
    assert obs and obs[0]['resource']['resourceType'] == 'Observation'
    o = obs[0]['resource']
    assert o['valueQuantity']['value'] == 6.5
    assert o['interpretation'][0]['coding'][0]['code'] == 'LL'      # critical carried through

    r = c.get(f'/fhir/DiagnosticReport?patient={pid}', headers=_hdr(token))
    reps = [e['resource'] for e in r.get_json()['entry']]
    kinds = {rr['id'].split('-')[0] for rr in reps}
    assert 'lab' in kinds and 'rad' in kinds          # both lab and imaging reports


def test_imaging_practitioner_encounter_medication(app, token, seeded):
    c = app.test_client()
    pid = seeded['pid']

    s = c.get(f"/fhir/ImagingStudy/{seeded['study']}", headers=_hdr(token)).get_json()
    assert s['resourceType'] == 'ImagingStudy' and s['numberOfSeries'] == 2
    assert s['modality'][0]['code'] == 'CT'

    pr = c.get('/fhir/Practitioner?name=Hassan', headers=_hdr(token)).get_json()
    quals = [e['resource'].get('qualification', [{}])[0].get('code', {}).get('text')
             for e in pr['entry']]
    assert 'Cardiology' in quals

    enc = c.get(f'/fhir/Encounter?patient={pid}', headers=_hdr(token)).get_json()
    e = enc['entry'][0]['resource']
    assert e['resourceType'] == 'Encounter'
    assert e['reasonCode'][0]['coding'][0]['code'] == 'D64.9'

    med = c.get(f"/fhir/Medication/{seeded['med']}", headers=_hdr(token)).get_json()
    assert med['resourceType'] == 'Medication' and med['code']['text'] == 'Paracetamol'

    mr = c.get(f'/fhir/MedicationRequest?patient={pid}', headers=_hdr(token)).get_json()
    m = mr['entry'][0]['resource']
    assert m['resourceType'] == 'MedicationRequest'
    assert m['medicationReference']['reference'] == f"Medication/{seeded['med']}"
    assert m['dosageInstruction'][0]['text'] == '1 tab BD'
