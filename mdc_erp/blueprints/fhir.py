"""FHIR R4 REST API (read + search)  (Phase 6, v8.0).

Read-only interoperability endpoints under /fhir, secured with the same JWT the
existing REST API issues (POST /api/login). GET is CSRF-exempt and read-only.

    GET /fhir/metadata                  CapabilityStatement (public)
    GET /fhir/{Type}/{id}               read one resource
    GET /fhir/{Type}?{params}           search -> Bundle(searchset)

Supported types: Patient, Practitioner, Encounter, Observation,
DiagnosticReport, ImagingStudy, Medication, MedicationRequest.
"""
import json
from flask import Blueprint, request, Response
from ..extensions import db
from ..models import (Patient, Doctor, Radiologist, Consultation, LabOrder,
                      LabResultValue, RadOrder, ImgStudy, Medicine, Prescription)
from ..core import fhir as F
from .api import api_user

bp = Blueprint('fhir', __name__)

FHIR_MIME = 'application/fhir+json'


def _resp(obj, code=200):
    return Response(json.dumps(obj, default=str), status=code, mimetype=FHIR_MIME)


def _oo(severity, code, msg, http=400):
    return _resp(F.operation_outcome(severity, code, msg), http)


def _auth():
    return api_user()


def _count():
    try:
        return max(1, min(int(request.args.get('_count', 50)), 200))
    except Exception:
        return 50


def _base():
    # external base URL for fullUrl links
    return request.url_root.rstrip('/') + '/fhir'


# ==================================================================== metadata
@bp.route('/fhir/metadata')
@bp.route('/fhir')
def metadata():
    """CapabilityStatement — public, so clients can discover the server."""
    types = ['Patient', 'Practitioner', 'Encounter', 'Observation',
             'DiagnosticReport', 'ImagingStudy', 'Medication', 'MedicationRequest']
    cs = {
        'resourceType': 'CapabilityStatement', 'status': 'active',
        'date': '2026-01-01', 'kind': 'instance',
        'software': {'name': 'MDC Diagnostic ERP FHIR', 'version': '8.0'},
        'fhirVersion': '4.0.1', 'format': ['json'],
        'rest': [{
            'mode': 'server',
            'security': {'description': 'Bearer JWT from POST /api/login'},
            'resource': [{'type': t, 'interaction': [{'code': 'read'}, {'code': 'search-type'}]}
                         for t in types],
        }],
    }
    return _resp(cs)


# ==================================================================== Patient
@bp.route('/fhir/Patient/<int:pid>')
def patient_read(pid):
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    p = db.session.get(Patient, pid)
    if not p:
        return _oo('error', 'not-found', f'Patient/{pid} not found', 404)
    return _resp(F.patient(p))


@bp.route('/fhir/Patient')
def patient_search():
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    q = Patient.query
    name = request.args.get('name')
    if name:
        q = q.filter(Patient.name.ilike(f'%{name}%'))
    ident = request.args.get('identifier')
    if ident:
        q = q.filter(Patient.mrn == ident.split('|')[-1])
    phone = request.args.get('phone') or request.args.get('telecom')
    if phone:
        q = q.filter(Patient.phone == phone)
    rows = q.order_by(Patient.id.desc()).limit(_count()).all()
    return _resp(F.bundle([F.patient(p) for p in rows], base=_base()))


# ================================================================ Practitioner
@bp.route('/fhir/Practitioner/<pid>')
def practitioner_read(pid):
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    prefix, _, num = pid.partition('-')
    num = num or prefix
    try:
        num = int(num)
    except ValueError:
        return _oo('error', 'not-found', 'Practitioner not found', 404)
    if pid.startswith('rad'):
        d = db.session.get(Radiologist, num)
        return _resp(F.practitioner(d, 'rad')) if d else _oo('error', 'not-found', 'not found', 404)
    d = db.session.get(Doctor, num)
    return _resp(F.practitioner(d, 'doc')) if d else _oo('error', 'not-found', 'not found', 404)


@bp.route('/fhir/Practitioner')
def practitioner_search():
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    name = request.args.get('name')
    docs = Doctor.query
    rads = Radiologist.query
    if name:
        docs = docs.filter(Doctor.name.ilike(f'%{name}%'))
        rads = rads.filter(Radiologist.name.ilike(f'%{name}%'))
    n = _count()
    res = [F.practitioner(d, 'doc') for d in docs.limit(n).all()]
    res += [F.practitioner(d, 'rad') for d in rads.limit(n).all()]
    return _resp(F.bundle(res, base=_base()))


# =================================================================== Encounter
@bp.route('/fhir/Encounter/<int:eid>')
def encounter_read(eid):
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    c = db.session.get(Consultation, eid)
    if not c:
        return _oo('error', 'not-found', 'Encounter not found', 404)
    return _resp(F.encounter(c))


@bp.route('/fhir/Encounter')
def encounter_search():
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    q = Consultation.query
    pid = _patient_param()
    if pid:
        q = q.filter(Consultation.patient_id == pid)
    rows = q.order_by(Consultation.id.desc()).limit(_count()).all()
    return _resp(F.bundle([F.encounter(c) for c in rows], base=_base()))


# ================================================================= Observation
def _patient_param():
    p = request.args.get('patient') or request.args.get('subject') or ''
    p = p.split('/')[-1]
    try:
        return int(p)
    except (ValueError, TypeError):
        return None


@bp.route('/fhir/Observation/<oid>')
def observation_read(oid):
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    num = oid.split('-')[-1]
    try:
        v = db.session.get(LabResultValue, int(num))
    except ValueError:
        v = None
    if not v:
        return _oo('error', 'not-found', 'Observation not found', 404)
    return _resp(F.observation(v))


@bp.route('/fhir/Observation')
def observation_search():
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    pid = _patient_param()
    q = LabResultValue.query.join(LabOrder, LabResultValue.order_id == LabOrder.id)
    if pid:
        q = q.filter(LabOrder.patient_id == pid)
    rows = q.order_by(LabResultValue.id.desc()).limit(_count()).all()
    return _resp(F.bundle([F.observation(v) for v in rows], base=_base()))


# ============================================================ DiagnosticReport
@bp.route('/fhir/DiagnosticReport/<rid>')
def report_read(rid):
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    kind, _, num = rid.partition('-')
    try:
        num = int(num)
    except ValueError:
        return _oo('error', 'not-found', 'DiagnosticReport not found', 404)
    if kind == 'rad':
        o = db.session.get(RadOrder, num)
        return _resp(F.diagnostic_report_rad(o)) if o else _oo('error', 'not-found', 'not found', 404)
    o = db.session.get(LabOrder, num)
    if not o:
        return _oo('error', 'not-found', 'not found', 404)
    obs = [v.id for v in o.values]
    return _resp(F.diagnostic_report_lab(o, obs))


@bp.route('/fhir/DiagnosticReport')
def report_search():
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    pid = _patient_param()
    n = _count()
    labs = LabOrder.query
    rads = RadOrder.query
    if pid:
        labs = labs.filter(LabOrder.patient_id == pid)
        rads = rads.filter(RadOrder.patient_id == pid)
    res = [F.diagnostic_report_lab(o, [v.id for v in o.values])
           for o in labs.order_by(LabOrder.id.desc()).limit(n).all()]
    res += [F.diagnostic_report_rad(o)
            for o in rads.order_by(RadOrder.id.desc()).limit(n).all()]
    return _resp(F.bundle(res, base=_base()))


# ================================================================ ImagingStudy
@bp.route('/fhir/ImagingStudy/<int:sid>')
def imaging_read(sid):
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    s = db.session.get(ImgStudy, sid)
    if not s:
        return _oo('error', 'not-found', 'ImagingStudy not found', 404)
    return _resp(F.imaging_study(s))


@bp.route('/fhir/ImagingStudy')
def imaging_search():
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    q = ImgStudy.query
    pid = _patient_param()
    if pid:
        q = q.filter(ImgStudy.patient_id == pid)
    rows = q.order_by(ImgStudy.id.desc()).limit(_count()).all()
    return _resp(F.bundle([F.imaging_study(s) for s in rows], base=_base()))


# ================================================= Medication / MedicationRequest
@bp.route('/fhir/Medication/<int:mid>')
def medication_read(mid):
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    m = db.session.get(Medicine, mid)
    if not m:
        return _oo('error', 'not-found', 'Medication not found', 404)
    return _resp(F.medication(m))


@bp.route('/fhir/Medication')
def medication_search():
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    q = Medicine.query
    name = request.args.get('code') or request.args.get('name')
    if name:
        q = q.filter(Medicine.name.ilike(f'%{name}%'))
    rows = q.order_by(Medicine.name).limit(_count()).all()
    return _resp(F.bundle([F.medication(m) for m in rows], base=_base()))


@bp.route('/fhir/MedicationRequest/<int:rid>')
def medreq_read(rid):
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    pr = db.session.get(Prescription, rid)
    if not pr:
        return _oo('error', 'not-found', 'MedicationRequest not found', 404)
    return _resp(F.medication_request(pr))


@bp.route('/fhir/MedicationRequest')
def medreq_search():
    if not _auth():
        return _oo('error', 'login', 'Unauthorized — Bearer token required', 401)
    q = Prescription.query
    pid = _patient_param()
    if pid:
        q = q.filter(Prescription.patient_id == pid)
    rows = q.order_by(Prescription.id.desc()).limit(_count()).all()
    return _resp(F.bundle([F.medication_request(pr) for pr in rows], base=_base()))
