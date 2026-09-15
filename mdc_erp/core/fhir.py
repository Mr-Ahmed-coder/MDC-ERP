"""FHIR R4 resource serializers  (Phase 6, v8.0).

Maps the ERP's internal models to FHIR R4 JSON resources for a read-only
interoperability API: Patient, Practitioner, Encounter, Observation,
DiagnosticReport, ImagingStudy, Medication, MedicationRequest.

Pure serialization — no Flask, no DB queries here. The blueprint (blueprints/
fhir.py) does the lookups and wraps results in Bundles.
"""

_GENDER = {'m': 'male', 'male': 'male', 'f': 'female', 'female': 'female'}


def _gender(v):
    return _GENDER.get((v or '').strip().lower(), 'unknown')


def _split_name(full):
    parts = (full or '').split()
    if not parts:
        return {'text': full or ''}
    return {'text': full, 'family': parts[-1], 'given': parts[:-1] or [parts[0]]}


def _num(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None


# ------------------------------------------------------------------ resources
def patient(p):
    r = {'resourceType': 'Patient', 'id': str(p.id),
         'name': [_split_name(p.name)], 'gender': _gender(p.gender),
         'active': bool(p.active) if p.active is not None else True}
    ident = []
    if p.mrn:
        ident.append({'system': 'urn:mdc:mrn', 'value': p.mrn})
    if getattr(p, 'gov_id', None):
        ident.append({'system': 'urn:mdc:national-id', 'value': p.gov_id})
    if ident:
        r['identifier'] = ident
    if p.dob:
        r['birthDate'] = p.dob
    tel = []
    if p.phone:
        tel.append({'system': 'phone', 'value': p.phone, 'use': 'mobile'})
    if getattr(p, 'phone2', None):
        tel.append({'system': 'phone', 'value': p.phone2})
    if tel:
        r['telecom'] = tel
    if getattr(p, 'address', None):
        r['address'] = [{'text': p.address}]
    return r


def practitioner(d, prefix='doc'):
    r = {'resourceType': 'Practitioner', 'id': f'{prefix}-{d.id}',
         'name': [_split_name(d.name)],
         'active': bool(getattr(d, 'active', True))}
    if getattr(d, 'phone', None):
        r['telecom'] = [{'system': 'phone', 'value': d.phone}]
    spec = getattr(d, 'specialty', None)
    if spec:
        r['qualification'] = [{'code': {'text': spec}}]
    return r


def encounter(c):
    """From a Consultation (clinical visit)."""
    r = {'resourceType': 'Encounter', 'id': f'enc-{c.id}',
         'status': 'finished' if getattr(c, 'status', '') == 'Completed' else 'in-progress',
         'class': {'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode',
                   'code': 'AMB', 'display': 'ambulatory'},
         'subject': {'reference': f'Patient/{c.patient_id}'}}
    if c.date:
        r['period'] = {'start': c.date}
    dx = getattr(c, 'diagnosis', None)
    icd = getattr(c, 'icd_code', None)
    if dx or icd:
        code = {'text': dx or icd}
        if icd:
            code['coding'] = [{'system': 'http://hl7.org/fhir/sid/icd-10', 'code': icd}]
        r['reasonCode'] = [code]
    return r


def observation(v):
    """From a LabResultValue (structured analyte)."""
    r = {'resourceType': 'Observation', 'id': f'lrv-{v.id}', 'status': 'final',
         'category': [{'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/observation-category',
                                   'code': 'laboratory'}]}],
         'code': {'text': v.name}}
    if v.order is not None and v.order.patient_id:
        r['subject'] = {'reference': f'Patient/{v.order.patient_id}'}
        r['effectiveDateTime'] = v.order.date
    num = _num(v.value)
    if num is not None:
        r['valueQuantity'] = {'value': num, 'unit': v.unit or ''}
    else:
        r['valueString'] = v.value or ''
    if v.ref_low is not None or v.ref_high is not None:
        rr = {}
        if v.ref_low is not None:
            rr['low'] = {'value': v.ref_low, 'unit': v.unit or ''}
        if v.ref_high is not None:
            rr['high'] = {'value': v.ref_high, 'unit': v.unit or ''}
        r['referenceRange'] = [rr]
    if v.flag and v.flag != 'N':
        crit = v.flag in ('HH', 'LL')
        r['interpretation'] = [{'coding': [{
            'system': 'http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation',
            'code': v.flag, 'display': ('Critical ' if crit else '') + (
                'high' if v.flag.startswith('H') else 'low')}]}]
    return r


def diagnostic_report_lab(o, obs_ids=None):
    """From a LabOrder."""
    r = {'resourceType': 'DiagnosticReport', 'id': f'lab-{o.id}',
         'status': 'final' if o.status in ('Resulted', 'Approved') else 'partial',
         'category': [{'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/v2-0074',
                                   'code': 'LAB'}]}],
         'code': {'text': o.service.name if o.service else 'Lab test'},
         'subject': {'reference': f'Patient/{o.patient_id}'},
         'effectiveDateTime': o.date}
    if o.result:
        r['conclusion'] = o.result
    if obs_ids:
        r['result'] = [{'reference': f'Observation/lrv-{i}'} for i in obs_ids]
    return r


def diagnostic_report_rad(o):
    """From a RadOrder (imaging report)."""
    r = {'resourceType': 'DiagnosticReport', 'id': f'rad-{o.id}',
         'status': 'final' if o.status == 'Reported' else 'partial',
         'category': [{'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/v2-0074',
                                   'code': 'RAD'}]}],
         'code': {'text': o.service.name if o.service else (o.modality or 'Imaging')},
         'subject': {'reference': f'Patient/{o.patient_id}'},
         'effectiveDateTime': o.date}
    concl = getattr(o, 'impression', None) or getattr(o, 'report', None) or getattr(o, 'draft', None)
    if concl:
        r['conclusion'] = concl
    return r


def imaging_study(s):
    """From an ImgStudy (PACS)."""
    r = {'resourceType': 'ImagingStudy', 'id': str(s.id), 'status': 'available',
         'subject': {'reference': f'Patient/{s.patient_id}'},
         'numberOfSeries': s.num_series or 0, 'numberOfInstances': s.num_instances or 0}
    if s.study_date or s.created:
        r['started'] = s.study_date or (s.created.isoformat() if s.created else None)
    if s.description:
        r['description'] = s.description
    if s.modality:
        r['modality'] = [{'system': 'http://dicom.nema.org/resources/ontology/DCM',
                          'code': s.modality}]
    series = []
    for ser in s.series:
        series.append({'uid': ser.series_uid or f'series.{ser.id}',
                       'number': ser.series_number or 0,
                       'modality': {'code': ser.modality or s.modality or 'OT'},
                       'numberOfInstances': ser.num_instances or 0,
                       'description': ser.description or ''})
    if series:
        r['series'] = series
    return r


def medication(m):
    return {'resourceType': 'Medication', 'id': str(m.id),
            'code': {'text': m.name}, 'status': 'active'}


def medication_request(pr):
    """From a Prescription."""
    r = {'resourceType': 'MedicationRequest', 'id': str(pr.id),
         'status': 'active' if pr.status in ('Pending', 'Dispensed') else 'completed',
         'intent': 'order',
         'subject': {'reference': f'Patient/{pr.patient_id}'},
         'authoredOn': pr.date}
    if pr.medicine_id:
        r['medicationReference'] = {'reference': f'Medication/{pr.medicine_id}'}
    if pr.dosage:
        r['dosageInstruction'] = [{'text': pr.dosage}]
    if getattr(pr, 'doctor', None):
        r['requester'] = {'display': pr.doctor}
    return r


# --------------------------------------------------------------- wrappers
def bundle(resources, total=None, base=''):
    return {'resourceType': 'Bundle', 'type': 'searchset',
            'total': total if total is not None else len(resources),
            'entry': [{'fullUrl': f'{base}/{r["resourceType"]}/{r["id"]}', 'resource': r}
                      for r in resources]}


def operation_outcome(severity, code, diagnostics):
    return {'resourceType': 'OperationOutcome',
            'issue': [{'severity': severity, 'code': code, 'diagnostics': diagnostics}]}
