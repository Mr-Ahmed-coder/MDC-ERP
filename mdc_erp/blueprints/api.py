"""REST API with JWT authentication."""
import json
import datetime as dt
from flask import Blueprint, current_app, request, Response, jsonify
from werkzeug.security import check_password_hash
from ..extensions import db
from ..models import *
from ..core.security import log
from ..core.helpers import money, today, cur_year

from ..core.posting import repost_invoice, repost_payment

bp = Blueprint('api', __name__)

import hmac as _hmac, hashlib as _hashlib, base64 as _b64, time as _time

def _b64e(b): return _b64.urlsafe_b64encode(b).rstrip(b'=').decode()
def _b64d(s): return _b64.urlsafe_b64decode(s + '=' * (-len(s) % 4))

def jwt_encode(payload, exp_hours=24):
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = dict(payload); payload['exp'] = int(_time.time()) + exp_hours * 3600
    seg = _b64e(json.dumps(header).encode()) + '.' + _b64e(json.dumps(payload).encode())
    sig = _hmac.new(current_app.config['SECRET_KEY'].encode(), seg.encode(), _hashlib.sha256).digest()
    return seg + '.' + _b64e(sig)

def jwt_decode(token):
    try:
        h, p, s = token.split('.')
        seg = h + '.' + p
        good = _hmac.new(current_app.config['SECRET_KEY'].encode(), seg.encode(), _hashlib.sha256).digest()
        if not _hmac.compare_digest(good, _b64d(s)): return None
        payload = json.loads(_b64d(p))
        if payload.get('exp', 0) < _time.time(): return None
        return payload
    except Exception:
        return None

def api_user():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '): return None
    payload = jwt_decode(auth[7:].strip())
    if not payload: return None
    u = User.query.get(payload.get('uid'))
    return u if (u and u.active) else None

def api_error(msg, code=400):
    return Response(json.dumps({'ok': False, 'error': msg}), status=code, mimetype='application/json')

def api_json(data, code=200):
    return Response(json.dumps({'ok': True, 'data': data}, default=str), status=code, mimetype='application/json')

# ---------------------------------------------------------------------------
# Rate limiting (#18). Lightweight in-process sliding-window limiter keyed by
# API user (or client IP for unauthenticated endpoints like /api/login). No
# external store is required for the prototype; for a multi-worker production
# deploy this should move to a shared store (e.g. Redis).
_RL_BUCKETS = {}
_RL_DEFAULT = (120, 60)      # 120 requests / 60s for authenticated API calls
_RL_LOGIN = (10, 60)         # 10 login attempts / 60s per IP (brute-force guard)

def _rate_ok(key, limit, window):
    now = _time.time()
    hits = _RL_BUCKETS.get(key)
    if hits is None:
        hits = []; _RL_BUCKETS[key] = hits
    # drop timestamps outside the window
    cutoff = now - window
    while hits and hits[0] < cutoff:
        hits.pop(0)
    if len(hits) >= limit:
        return False, int(hits[0] + window - now) + 1   # retry-after seconds
    hits.append(now)
    return True, 0

def _rate_limit(key, limit, window):
    # Rate limiting is disabled in TESTING so the suite stays deterministic
    # (in-process buckets would otherwise accumulate across tests on one IP).
    try:
        if current_app.config.get('TESTING'):
            return None
    except Exception:
        pass
    ok, retry = _rate_ok(key, limit, window)
    if ok:
        return None
    r = api_error(f'Rate limit exceeded — try again in {retry}s', 429)
    r.headers['Retry-After'] = str(retry)
    return r

def _client_ip():
    return (request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request.remote_addr or 'unknown')

def api_auth(roles=None):
    def deco(f):
        from functools import wraps
        @wraps(f)
        def w(*a, **k):
            u = api_user()
            if not u: return api_error('Unauthorized — send Authorization: Bearer <token>', 401)
            if roles and u.role not in roles and u.role != 'super_admin':
                return api_error('Forbidden for role ' + u.role, 403)
            limited = _rate_limit(f'user:{u.id}', *_RL_DEFAULT)
            if limited: return limited
            request.api_user = u
            return f(*a, **k)
        return w
    return deco

@bp.route('/api/login', methods=['POST'])
def api_login():
    limited = _rate_limit(f'login:{_client_ip()}', *_RL_LOGIN)
    if limited: return limited
    d = request.get_json(silent=True) or request.form
    u = User.query.filter_by(username=(d.get('username') or '').strip()).first()
    if not (u and u.active and check_password_hash(u.pw, d.get('password') or '')):
        return api_error('Invalid username or password', 401)
    tok = jwt_encode({'uid': u.id, 'username': u.username, 'role': u.role})
    return api_json({'token': tok, 'user': {'id': u.id, 'username': u.username, 'name': u.name, 'role': u.role}, 'expires_hours': 24})

def _pat(p):
    return {'id': p.id, 'mrn': p.mrn, 'name': p.name, 'phone': p.phone, 'gender': p.gender,
            'dob': p.dob, 'gov_id': p.gov_id, 'address': p.address}

@bp.route('/api/patients', methods=['GET', 'POST'])
@api_auth(['reception', 'accountant', 'doctor'])
def api_patients():
    if request.method == 'POST':
        d = request.get_json(silent=True) or {}
        if not d.get('name'): return api_error('name is required')
        p = Patient(mrn='MRN' + str((Patient.query.count() or 0) + 1001), name=d['name'],
                    phone=d.get('phone'), gender=d.get('gender'), dob=d.get('dob'),
                    gov_id=d.get('gov_id'), address=d.get('address'), notes=d.get('notes'))
        db.session.add(p); db.session.commit(); log(f"API: created patient {p.mrn}")
        return api_json(_pat(p), 201)
    q = (request.args.get('q') or '').strip()
    qry = Patient.query
    if q:
        like = f"%{q}%"
        qry = qry.filter(db.or_(Patient.name.ilike(like), Patient.phone.ilike(like), Patient.mrn.ilike(like)))
    return api_json([_pat(p) for p in qry.order_by(Patient.id.desc()).limit(100).all()])

@bp.route('/api/patients/<int:pid>')
@api_auth(['reception', 'accountant', 'doctor'])
def api_patient(pid):
    p = Patient.query.get_or_404(pid)
    labs = [{'id': o.id, 'date': o.date, 'test': (o.service.name if o.service else None), 'status': o.status,
             'result': (o.result if o.status == 'Approved' else None)} for o in LabOrder.query.filter_by(patient_id=pid).all()]
    rads = [{'id': o.id, 'date': o.date, 'study': (o.service.name if o.service else None), 'modality': o.modality,
             'status': o.status, 'report': (o.report if o.status == 'Reported' else None)} for o in RadOrder.query.filter_by(patient_id=pid).all()]
    invs = [{'id': i.id, 'number': f'INV-{i.id:04d}', 'date': i.date, 'total': i.total, 'paid': i.paid or 0,
             'balance': i.total - (i.paid or 0), 'status': i.status} for i in Invoice.query.filter_by(patient_id=pid).all()]
    d = _pat(p); d['lab_orders'] = labs; d['rad_orders'] = rads; d['invoices'] = invs
    return api_json(d)

@bp.route('/api/services')
@api_auth()
def api_services():
    return api_json([{'id': s.id, 'code': s.code, 'name': s.name, 'department': s.department,
                      'price': s.price, 'active': s.active} for s in Service.query.order_by(Service.department, Service.code).all()])

@bp.route('/api/invoices', methods=['GET', 'POST'])
@api_auth(['reception', 'cashier', 'accountant'])
def api_invoices():
    if request.method == 'POST':
        d = request.get_json(silent=True) or {}
        inv = Invoice(patient_id=d.get('patient_id'), date=d.get('date') or today())
        db.session.add(inv); db.session.commit()
        for it in d.get('items', []):
            if it.get('service_id'):
                s = Service.query.get(int(it['service_id']))
                if s:
                    db.session.add(InvoiceItem(invoice_id=inv.id, desc=s.name, qty=float(it.get('qty') or 1), price=s.price or 0))
                    if s.supply_id and (s.supply_qty or 0) > 0:
                        m = Medicine.query.get(s.supply_id)
                        if m: m.qty = int((m.qty or 0) - (s.supply_qty or 0) * float(it.get('qty') or 1))
            else:
                db.session.add(InvoiceItem(invoice_id=inv.id, desc=it.get('desc') or 'Item',
                                           qty=float(it.get('qty') or 1), price=float(it.get('price') or 0)))
        inv.discount = float(d.get('discount') or 0); inv.vat = float(d.get('vat') or 0)
        db.session.commit()
        try: repost_invoice(inv)
        except Exception: db.session.rollback()
        log(f"API: created invoice INV-{inv.id:04d}")
        return api_json({'id': inv.id, 'number': f'INV-{inv.id:04d}', 'total': inv.total}, 201)
    f = request.args.get('from', ''); t = request.args.get('to', '')
    out = []
    from ..core.security import branch_scope
    _q = branch_scope(Invoice.query, Invoice).order_by(Invoice.id.desc()).limit(200)
    for i in _q.all():
        d0 = i.date or ''
        if f and d0 < f: continue
        if t and d0 > t: continue
        out.append({'id': i.id, 'number': f'INV-{i.id:04d}', 'date': i.date,
                    'patient': (i.patient.name if i.patient else None), 'total': i.total,
                    'paid': i.paid or 0, 'balance': i.total - (i.paid or 0), 'status': i.status})
    return api_json(out)

@bp.route('/api/invoices/<int:iid>/pay', methods=['POST'])
@api_auth(['cashier', 'accountant', 'reception'])
def api_invoice_pay(iid):
    inv = Invoice.query.get_or_404(iid)
    from ..core.security import can_see
    if not can_see(inv):
        return api_error('Not found', 404)   # do not reveal another branch's invoice
    d = request.get_json(silent=True) or {}
    amt = float(d.get('amount') or 0)
    if amt <= 0:
        return api_error('amount must be > 0')

    # API clients must provide a stable retry key. A timeout after a successful
    # payment must be safe to replay, rather than creating a second receipt.
    idem = (request.headers.get('Idempotency-Key') or d.get('idempotency_key') or '').strip()
    if not idem or len(idem) > 128:
        return api_error('Idempotency-Key header or idempotency_key is required (8-128 characters)')
    if len(idem) < 8:
        return api_error('idempotency key must contain at least 8 characters')

    prior = PayReceipt.query.filter_by(idempotency_key=idem).first()
    if prior:
        if prior.invoice_id != inv.id or abs(float(prior.amount or 0) - amt) > 0.005:
            return api_error('idempotency key was already used for a different payment', 409)
        return api_json({'id': inv.id, 'paid': inv.paid, 'balance': inv.balance,
                         'status': inv.status, 'receipt_id': prior.id, 'replayed': True})

    outstanding = inv.balance
    if amt > outstanding + 0.005:
        return api_error('amount exceeds the invoice balance')
    inv.paid = (inv.paid or 0) + amt
    inv.status = 'Paid' if inv.balance <= 0.005 else 'Partial'
    receipt = PayReceipt(invoice_id=inv.id, amount=amt,
                         method=(d.get('method') or 'Cash')[:20],
                         ref=(d.get('ref') or '')[:60],
                         idempotency_key=idem,
                         cashier=(request.api_user.name or request.api_user.username))
    db.session.add(receipt)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        prior = PayReceipt.query.filter_by(idempotency_key=idem).first()
        if prior and prior.invoice_id == inv.id and abs(float(prior.amount or 0) - amt) <= 0.005:
            return api_json({'id': inv.id, 'paid': inv.paid, 'balance': inv.balance,
                             'status': inv.status, 'receipt_id': prior.id, 'replayed': True})
        raise
    try:
        repost_payment(inv)
    except Exception:
        # The payment is durable; accounting reconciliation can safely retry
        # posting because the receipt has a stable idempotency key.
        current_app.logger.exception('Accounting repost pending for receipt %s', receipt.id)
    log(f"API: payment {money(amt)} on INV-{iid:04d}")
    return api_json({'id': inv.id, 'paid': inv.paid, 'balance': inv.balance,
                     'status': inv.status, 'receipt_id': receipt.id, 'replayed': False})

@bp.route('/api/finance/integrity')
@api_auth(['accountant'])
def api_finance_integrity():
    from ..core.reconciliation import summary
    return api_json(summary())


@bp.route('/api/stats')
@api_auth(['accountant'])
def api_stats():
    y = str(cur_year()); ym = dt.date.today().isoformat()[:7]
    inv = Invoice.query.all()
    return api_json({
        'revenue_month': sum(i.total for i in inv if (i.date or '').startswith(ym)),
        'revenue_year': sum(i.total for i in inv if (i.date or '').startswith(y)),
        'outstanding': sum(i.total - (i.paid or 0) for i in inv if i.status != 'Paid'),
        'patients': Patient.query.count(),
        'new_referrals': Referral.query.filter_by(status='New').count(),
        'pending_lab': LabOrder.query.filter(LabOrder.status != 'Approved').count(),
        'pending_rad': RadOrder.query.filter(RadOrder.status != 'Reported').count(),
        'low_stock': sum(1 for m in Medicine.query.all() if (m.qty or 0) <= (m.reorder or 0)),
    })

@bp.route('/api')
def api_docs():
    docs = {
        'name': 'MDC Diagnostic ERP API', 'version': '1.0', 'auth': 'POST /api/login {username,password} -> token; then header Authorization: Bearer <token>',
        'endpoints': {
            'POST /api/login': 'Get JWT token (24h)',
            'GET /api/patients?q=': 'List/search patients',
            'POST /api/patients': 'Create patient {name, phone, gender, ...}',
            'GET /api/patients/<id>': 'Patient + lab/rad results + invoices',
            'GET /api/services': 'Service catalog with prices',
            'GET /api/invoices?from=&to=': 'List invoices',
            'POST /api/invoices': 'Create invoice {patient_id, items:[{service_id,qty}|{desc,qty,price}], discount, vat} — auto-posts to Accounting + deducts stock',
            'POST /api/invoices/<id>/pay': 'Record payment {amount} — auto-posts to Accounting',
            'GET /api/stats': 'Dashboard KPIs (accountant/admin)',
        }}
    return Response(json.dumps(docs, indent=2), mimetype='application/json')



# ------------------------------------------------------- OpenAPI / Swagger UI
@bp.route('/api/openapi.json')
def api_openapi():
    host = request.host_url.rstrip('/')
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "MDC Diagnostic ERP API", "version": "2.4",
                 "description": "JWT-secured REST API. Call POST /api/login first, "
                                "then send `Authorization: Bearer <token>`."},
        "servers": [{"url": host}],
        "components": {"securitySchemes": {"bearerAuth": {
            "type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}},
        "security": [{"bearerAuth": []}],
        "paths": {
            "/api/login": {"post": {"summary": "Obtain a JWT token", "security": [],
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["username", "password"],
                    "properties": {"username": {"type": "string", "example": "admin"},
                                   "password": {"type": "string", "example": "INITIAL_ADMIN_PASSWORD"}}}}}},
                "responses": {"200": {"description": "token + user"},
                              "401": {"description": "invalid credentials"}}}},
            "/api/patients": {
                "get": {"summary": "List patients (roles: reception/accountant/doctor)",
                        "responses": {"200": {"description": "patient list"}}},
                "post": {"summary": "Create a patient (MRN auto-generated)",
                         "requestBody": {"content": {"application/json": {"schema": {
                             "type": "object", "required": ["name"],
                             "properties": {"name": {"type": "string"}, "phone": {"type": "string"},
                                            "gender": {"type": "string"}, "dob": {"type": "string"},
                                            "gov_id": {"type": "string"}, "address": {"type": "string"}}}}}},
                         "responses": {"200": {"description": "created patient"}}}},
            "/api/patients/{pid}": {"get": {"summary": "Get one patient",
                "parameters": [{"name": "pid", "in": "path", "required": True,
                                "schema": {"type": "integer"}}],
                "responses": {"200": {"description": "patient"}, "404": {"description": "not found"}}}},
            "/api/services": {"get": {"summary": "Active service catalog with prices",
                "responses": {"200": {"description": "services"}}}},
            "/api/invoices": {
                "get": {"summary": "List invoices", "responses": {"200": {"description": "invoices"}}},
                "post": {"summary": "Create invoice with service items",
                         "requestBody": {"content": {"application/json": {"schema": {
                             "type": "object",
                             "properties": {"patient_id": {"type": "integer"},
                                            "items": {"type": "array", "items": {"type": "object",
                                                "properties": {"service_id": {"type": "integer"},
                                                               "qty": {"type": "number"}}}}}}}}},
                         "responses": {"200": {"description": "created invoice"}}}},
            "/api/invoices/{iid}/pay": {"post": {"summary": "Record a payment",
                "parameters": [{"name": "iid", "in": "path", "required": True,
                                "schema": {"type": "integer"}}],
                "requestBody": {"content": {"application/json": {"schema": {
                    "type": "object", "properties": {"amount": {"type": "number"},
                                                     "method": {"type": "string"}}}}}},
                "responses": {"200": {"description": "updated invoice"}}}},
            "/api/stats": {"get": {"summary": "Dashboard statistics",
                "responses": {"200": {"description": "totals"}}}},
        },
    }
    return Response(json.dumps(spec, indent=2), mimetype='application/json')


@bp.route('/api/docs')
def api_swagger_ui():
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>MDC ERP API · Swagger</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.17.14/swagger-ui.min.css">
</head><body style="margin:0"><div id="ui"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.17.14/swagger-ui-bundle.min.js"></script>
<script>SwaggerUIBundle({{url:'/api/openapi.json',dom_id:'#ui',deepLinking:true,
  presets:[SwaggerUIBundle.presets.apis],layout:'BaseLayout'}});</script></body></html>"""


# --------------------------------------------------------- FHIR R4 (read-only)
@bp.route('/api/fhir/Patient/<int:pid>')
def fhir_patient(pid):
    payload = jwt_decode((request.headers.get('Authorization', '')[7:] or '').strip())
    if not payload: return jsonify(error='unauthorized'), 401
    p = Patient.query.get_or_404(pid)
    return jsonify({
        'resourceType': 'Patient', 'id': str(p.id),
        'identifier': [{'system': 'urn:mdc:mrn', 'value': p.mrn or ''}],
        'name': [{'text': p.name}],
        'gender': (p.gender or '').lower() or None,
        'birthDate': p.dob or None,
        'telecom': ([{'system': 'phone', 'value': p.phone}] if p.phone else []),
        'address': ([{'text': p.address}] if p.address else []),
    })


@bp.route('/api/fhir/Observation')
def fhir_observations():
    payload = jwt_decode((request.headers.get('Authorization', '')[7:] or '').strip())
    if not payload: return jsonify(error='unauthorized'), 401
    pid = request.args.get('patient', type=int)
    if not pid: return jsonify(error='patient parameter required'), 400
    obs = []
    for o in (LabOrder.query.filter_by(patient_id=pid, status='Approved')
              .order_by(LabOrder.id.desc()).limit(100).all()):
        obs.append({'resourceType': 'Observation', 'id': str(o.id),
                    'status': 'final',
                    'code': {'text': o.service.name if o.service else 'Lab Test'},
                    'subject': {'reference': f'Patient/{pid}'},
                    'effectiveDateTime': o.date,
                    'valueString': o.result or '',
                    'referenceRange': ([{'text': o.service.ref_range}]
                                       if o.service and o.service.ref_range else [])})
    return jsonify({'resourceType': 'Bundle', 'type': 'searchset',
                    'total': len(obs), 'entry': [{'resource': r} for r in obs]})
