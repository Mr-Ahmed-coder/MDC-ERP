"""First-run bootstrap: tables, safe column migration for old SQLite files,
default admin user, default settings and the full chart of accounts."""
from werkzeug.security import generate_password_hash
from .extensions import db
from .models import *


def init_db(app, demo=False):
    with app.app_context():
        _production = not app.config.get('TESTING') and not app.config.get('DEBUG')
        if _production:
            from sqlalchemy import inspect as _inspect
            if not _inspect(db.engine).has_table('setting'):
                db.create_all()
        else:
            db.create_all()

        # Legacy SQLite compatibility migrations are never executed in production.
        if not _production:
            db.create_all()
            # --- dialect-agnostic column reader (works on SQLite AND PostgreSQL) ---
            from sqlalchemy import inspect as _inspect
            def _table_cols(_t):
                """Existing column names for a table on any backend. On a fresh
                PostgreSQL database create_all() has already built every column, so
                the legacy ALTER-TABLE back-fill below simply finds them all present
                and does nothing — while old SQLite files still get patched."""
                try:
                    return [c['name'] for c in _inspect(db.engine).get_columns(_t)]
                except Exception:
                    return []
            # safe column migration for older databases
            try:
                from sqlalchemy import text as _text
                cols=_table_cols("user")
                if 'totp_secret' not in cols:
                    db.session.execute(_text("ALTER TABLE user ADD COLUMN totp_secret VARCHAR(64)"))
                    db.session.execute(_text("ALTER TABLE user ADD COLUMN totp_enabled BOOLEAN DEFAULT 0"))
                    db.session.commit()
                if 'branch_id' not in cols:
                    db.session.execute(_text("ALTER TABLE user ADD COLUMN branch_id INTEGER")); db.session.commit()
                for _tbl in ('invoice','expense'):
                    _c=_table_cols(_tbl)
                    if _c and 'branch_id' not in _c:
                        db.session.execute(_text(f"ALTER TABLE {_tbl} ADD COLUMN branch_id INTEGER")); db.session.commit()
                # workflow-lock flag: completed invoices become immutable until admin reset
                _ic=_table_cols("invoice")
                if _ic and 'locked' not in _ic:
                    db.session.execute(_text("ALTER TABLE invoice ADD COLUMN locked BOOLEAN DEFAULT 0")); db.session.commit()
                if _ic and 'due_date' not in _ic:
                    db.session.execute(_text("ALTER TABLE invoice ADD COLUMN due_date VARCHAR(12)")); db.session.commit()
                if _ic and 'contrast_amount' not in _ic:
                    db.session.execute(_text("ALTER TABLE invoice ADD COLUMN contrast_amount FLOAT")); db.session.commit()
                if _ic and 'commission_amount' not in _ic:
                    db.session.execute(_text("ALTER TABLE invoice ADD COLUMN commission_amount FLOAT")); db.session.commit()
                if _ic and 'consumed' not in _ic:
                    db.session.execute(_text("ALTER TABLE invoice ADD COLUMN consumed BOOLEAN DEFAULT 0")); db.session.commit()
                # Odoo-style expense workflow columns
                _ec=_table_cols("expense")
                if _ec:
                    for _c, _ddl in (('description','VARCHAR(160)'), ('product','VARCHAR(120)'),
                                     ('qty','FLOAT'), ('unit_price','NUMERIC'), ('account','VARCHAR(80)'),
                                     ('employee','VARCHAR(80)'), ('paid_by','VARCHAR(20)'), ('status','VARCHAR(12)')):
                        if _c not in _ec:
                            db.session.execute(_text(f"ALTER TABLE expense ADD COLUMN {_c} {_ddl}")); db.session.commit()
                # who created the invoice
                _ic=_table_cols("invoice")
                if _ic:
                    for _col in ('created_by', 'created_at'):
                        if _col not in _ic:
                            db.session.execute(_text(f"ALTER TABLE invoice ADD COLUMN {_col} VARCHAR(80)")); db.session.commit()
                # purchase payment method (maps to the cash/bank/wallet account)
                _puc=_table_cols("purchase")
                if _puc and 'pay_method' not in _puc:
                    db.session.execute(_text("ALTER TABLE purchase ADD COLUMN pay_method VARCHAR(30) DEFAULT 'Cash'")); db.session.commit()
                _puc=_table_cols("purchase")
                if _puc:
                    for _c, _ddl in (('vendor_ref','VARCHAR(80)'), ('order_deadline','VARCHAR(20)'),
                                     ('expected_date','VARCHAR(20)'), ('terms','TEXT'), ('discount','NUMERIC'),
                                     ('bill_status','VARCHAR(12)')):
                        if _c not in _puc:
                            db.session.execute(_text(f"ALTER TABLE purchase ADD COLUMN {_c} {_ddl}")); db.session.commit()
                # asset lifecycle dates (in-service drives depreciation start)
                _ac=_table_cols("asset")
                if _ac:
                    for _col in ('in_service_date', 'capitalization_date'):
                        if _col not in _ac:
                            db.session.execute(_text(f"ALTER TABLE asset ADD COLUMN {_col} VARCHAR(12)")); db.session.commit()
                # clinical result lock (approved results are locked; amend-only)
                _lc=_table_cols("lab_order")
                if _lc and 'locked' not in _lc:
                    db.session.execute(_text("ALTER TABLE lab_order ADD COLUMN locked BOOLEAN DEFAULT 0")); db.session.commit()
                _rc=_table_cols("rad_order")
                if _rc and 'locked' not in _rc:
                    db.session.execute(_text("ALTER TABLE rad_order ADD COLUMN locked BOOLEAN DEFAULT 0")); db.session.commit()
                # fiscal period close/reopen audit trail
                _fc=_table_cols("fiscal_period")
                if _fc:
                    for _col, _ddl in (('closed_by','VARCHAR(80)'), ('closed_at','VARCHAR(30)'),
                                       ('reopened_by','VARCHAR(80)'), ('reopened_at','VARCHAR(30)'),
                                       ('reopen_reason','VARCHAR(200)')):
                        if _col not in _fc:
                            db.session.execute(_text(f"ALTER TABLE fiscal_period ADD COLUMN {_col} {_ddl}")); db.session.commit()
                # journal reversal audit trail (immutability / correction-by-reversal)
                _jc=_table_cols("journal_entry")
                if _jc:
                    for _col, _ddl in (('reverses_id','INTEGER'), ('reversed_at','VARCHAR(30)'),
                                       ('reversed_by_user','VARCHAR(80)'), ('reversal_reason','VARCHAR(200)'),
                                       ('posted_by','VARCHAR(80)')):
                        if _col not in _jc:
                            db.session.execute(_text(f"ALTER TABLE journal_entry ADD COLUMN {_col} {_ddl}")); db.session.commit()
                # entered patient age (when no exact date of birth is known)
                _pc=_table_cols("patient")
                if _pc and 'age_years' not in _pc:
                    db.session.execute(_text("ALTER TABLE patient ADD COLUMN age_years INTEGER")); db.session.commit()
                # manual referring-doctor code/number
                _dc=_table_cols("doctor")
                if _dc and 'code' not in _dc:
                    db.session.execute(_text("ALTER TABLE doctor ADD COLUMN code VARCHAR(30)")); db.session.commit()
                # radiology report template fields (Technique / Impression / Clinical data)
                _rc=_table_cols("rad_order")
                if _rc:
                    for _col,_type in (('technique','TEXT'),('impression','TEXT'),('clinical_data','VARCHAR(300)')):
                        if _col not in _rc:
                            db.session.execute(_text(f"ALTER TABLE rad_order ADD COLUMN {_col} {_type}")); db.session.commit()
                # enterprise fixed-assets fields on the asset register
                _ac=_table_cols("asset")
                if _ac:
                    for _col,_type in (('category_id','INTEGER'),('residual_value','INTEGER DEFAULT 0'),
                                       ('useful_life_months','INTEGER'),('depreciation_method','VARCHAR(24)'),
                                       ('department','VARCHAR(80)'),('custodian','VARCHAR(80)'),('supplier','VARCHAR(120)'),
                                       ('purchase_invoice','VARCHAR(60)'),('accumulated_dep','INTEGER DEFAULT 0'),
                                       ('reval_adjust','INTEGER DEFAULT 0'),('units_total','INTEGER'),
                                       ('units_used','INTEGER DEFAULT 0'),('activated','BOOLEAN DEFAULT 0'),
                                       ('opening','BOOLEAN DEFAULT 0')):
                        if _col not in _ac:
                            db.session.execute(_text(f"ALTER TABLE asset ADD COLUMN {_col} {_type}")); db.session.commit()
                # richer audit trail: type, entity, ip, old/new value, reason
                _ac=_table_cols("audit")
                if _ac:
                    for _col, _typ in [('action_type','VARCHAR(24)'), ('entity','VARCHAR(60)'),
                                       ('ip','VARCHAR(64)'), ('old_value','VARCHAR(255)'),
                                       ('new_value','VARCHAR(255)'), ('reason','VARCHAR(255)')]:
                        if _col not in _ac:
                            db.session.execute(_text(f"ALTER TABLE audit ADD COLUMN {_col} {_typ}")); db.session.commit()
                _mig={'service':[('price_insurance','FLOAT DEFAULT 0'),('price_corporate','FLOAT DEFAULT 0'),('price_vip','FLOAT DEFAULT 0'),('price_contract','FLOAT DEFAULT 0')],
                      'invoice':[('price_list',"VARCHAR(20) DEFAULT 'Cash'"),('discount_pct','FLOAT DEFAULT 0'),('pay_method',"VARCHAR(20) DEFAULT 'Cash'")],
                      'invoice_item':[('service_id','INTEGER')],
                      # --- Phase 2 columns ---
                      'appointment':[('queue_no','INTEGER'),('checkin_time','VARCHAR(8)')],
                      'consultation':[('icd_code','VARCHAR(20)')],
                      'rad_order':[('images','TEXT')],
                      'purchase':[('status','VARCHAR(20)'),('received_date','VARCHAR(12)'),
                                  ('medicine_id','INTEGER'),('warehouse_id','INTEGER')],
                      'journal_line':[('cleared','BOOLEAN')],
                      'expense':[('cost_center_id','INTEGER')],
                      # --- Phase 8 (clinical workflow) columns ---
                      'patient':[('phone2','VARCHAR(30)'),('blood_group','VARCHAR(5)'),('marital','VARCHAR(15)'),
                                 ('occupation','VARCHAR(80)'),('emerg_name','VARCHAR(120)'),('emerg_phone','VARCHAR(30)'),
                                 ('ins_company','VARCHAR(120)'),('ins_number','VARCHAR(60)'),('allergies','TEXT'),
                                 ('med_history','TEXT'),('photo','VARCHAR(120)'),('active','BOOLEAN DEFAULT 1'),('reg_by','VARCHAR(80)')]}
                _mig['appointment'] += [('service_id','INTEGER'),('visit_type','VARCHAR(15)'),('priority','VARCHAR(10)')]
                _mig['consultation'] += [('bp','VARCHAR(12)'),('temp_c','FLOAT'),('pulse','INTEGER'),('spo2','INTEGER'),
                                         ('weight_kg','FLOAT'),('height_cm','FLOAT'),('followup_date','VARCHAR(12)'),
                                         ('status','VARCHAR(15)')]
                _mig['invoice'] += [('disc_reason','VARCHAR(40)'),('disc_by','VARCHAR(80)'),('disc_date','VARCHAR(12)')]
                _mig['journal_entry'] = _mig.get('journal_entry',[]) + [('reversed_by','INTEGER'),('is_reversal','BOOLEAN DEFAULT 0')]
                _mig['service'] = _mig.get('service',[]) + [
                    ('short_name','VARCHAR(60)'),('category','VARCHAR(60)'),('subcategory','VARCHAR(60)'),
                    ('description','TEXT'),('price_emergency','FLOAT DEFAULT 0'),('price_home','FLOAT DEFAULT 0'),
                    ('discount_allowed','BOOLEAN DEFAULT 1'),('max_discount','FLOAT DEFAULT 0'),
                    ('comm_doctor_type','VARCHAR(8)'),('comm_doctor_val','FLOAT DEFAULT 0'),
                    ('comm_radiologist_type','VARCHAR(8)'),('comm_radiologist_val','FLOAT DEFAULT 0'),
                    ('comm_tech_type','VARCHAR(8)'),('comm_tech_val','FLOAT DEFAULT 0'),
                    ('comm_report_type','VARCHAR(8)'),('comm_report_val','FLOAT DEFAULT 0'),
                    ('workflow','VARCHAR(20)'),('report_template','VARCHAR(60)'),('equipment','VARCHAR(60)'),
                    ('time_collection','INTEGER'),('time_processing','INTEGER'),('time_reporting','INTEGER'),
                    ('avail_branches','VARCHAR(200)'),('modality','VARCHAR(30)')]
                _mig['invoice'] += [('referral_id','INTEGER')]
                _mig['invoice_item'] = _mig.get('invoice_item',[]) + [('lab_order_id','INTEGER'),('rad_order_id','INTEGER')]
                _mig['lab_order'] = _mig.get('lab_order',[]) + [('invoice_id','INTEGER'),('paid_gate','BOOLEAN DEFAULT 1')]
                _mig['rad_order'] = _mig.get('rad_order',[]) + [('invoice_id','INTEGER'),('paid_gate','BOOLEAN DEFAULT 1')]
                _mig['blood_unit'] = _mig.get('blood_unit',[]) + [('issued_to','INTEGER'),('issued_date','VARCHAR(12)')]
                _mig['doctor'] = _mig.get('doctor',[]) + [('portal_user','VARCHAR(60)'),('portal_pw','VARCHAR(200)')]
                _mig['referral'] = _mig.get('referral',[]) + [('complaint','TEXT'),('prov_dx','VARCHAR(200)'),('priority','VARCHAR(10)'),('instructions','VARCHAR(300)')]
                _mig['rad_order'] = _mig.get('rad_order',[]) + [('ref_id','INTEGER'),('assigned_rad_id','INTEGER'),('draft','TEXT'),('rad_approved_at','VARCHAR(20)')]
                _mig['lab_order'] = _mig.get('lab_order',[]) + [('ref_id','INTEGER'),('sample_no','VARCHAR(20)'),('specimen','VARCHAR(30)'),
                    ('collected_by','VARCHAR(50)'),('collected_at','VARCHAR(20)'),('received_at','VARCHAR(20)'),
                    ('panic','BOOLEAN DEFAULT 0'),('delta_flag','BOOLEAN DEFAULT 0')]
                _mig['service'] += [('panic_low','FLOAT'),('panic_high','FLOAT'),('specimen','VARCHAR(30)'),
                                    ('loinc','VARCHAR(20)'),('cpt','VARCHAR(12)')]
                _mig['patient'] += [('chronic','VARCHAR(200)')]
                _svc_cols=[('ref_range','VARCHAR(120)'),('unit','VARCHAR(30)')]
                _c=_table_cols("service")
                for _n,_t in _svc_cols:
                    if _c and _n not in _c:
                        db.session.execute(_text(f"ALTER TABLE service ADD COLUMN {_n} {_t}")); db.session.commit()
                _mig['supplier'] = _mig.get('supplier',[]) + [('contact_person','VARCHAR(120)'),('email','VARCHAR(120)'),
                    ('tax_no','VARCHAR(60)'),('bank_details','VARCHAR(200)'),('category','VARCHAR(60)')]
                _mig['expense'] = _mig.get('expense',[]) + [('supplier_id','INTEGER'),("pay_method","VARCHAR(20) DEFAULT 'Cash'")]
                _mig['invoice'] = _mig.get('invoice', []) + [('guarantor','VARCHAR(160)'),
                    ('guarantor_by','VARCHAR(80)'),('guarantor_at','VARCHAR(20)')]
                # --- v8.0 columns (RIS Phase 2 + LIS Phase 4) on existing tables ---
                _mig['rad_order'] = _mig.get('rad_order',[]) + [
                    ('priority','VARCHAR(10)'),('modality_id','INTEGER'),('scheduled_for','VARCHAR(20)'),
                    ('technician','VARCHAR(60)'),('requested_at','VARCHAR(20)'),('scheduled_at','VARCHAR(20)'),
                    ('acquired_at','VARCHAR(20)'),('reported_at','VARCHAR(20)'),('approved_at','VARCHAR(20)'),
                    ('approved_by','VARCHAR(60)'),('signature','VARCHAR(40)')]
                _mig['lab_order'] = _mig.get('lab_order',[]) + [('panic_ack','BOOLEAN DEFAULT 0')]
                # --- v8.0 Phase 5 (smart queue) columns on queue_ticket ---
                _mig['queue_ticket'] = _mig.get('queue_ticket',[]) + [
                    ('priority',"VARCHAR(10) DEFAULT 'Normal'"),('room','VARCHAR(30)'),
                    ('called_at','VARCHAR(20)'),('done_at','VARCHAR(20)'),
                    ('created_by','VARCHAR(60)'),('branch_id','INTEGER')]
                # --- v8.0 Phase 17 (Odoo search view): per-module search history ---
                _mig['search_log'] = _mig.get('search_log',[]) + [('module','VARCHAR(40)')]
                # --- v8.1 (cashier-friendly invoice UX): Draft → Confirmed step before payment ---
                _mig['invoice'] = _mig.get('invoice',[]) + [('confirmed','BOOLEAN DEFAULT 0')]
                # --- v8.2 (universal billable-service engine): consultation billing + line traceability ---
                _mig['consultation'] = _mig.get('consultation',[]) + [('service_id','INTEGER'),('invoice_id','INTEGER')]
                _mig['invoice_item'] = _mig.get('invoice_item',[]) + [('consult_id','INTEGER'),
                    ('manual_reason','VARCHAR(160)'),('manual_by','VARCHAR(80)'),('manual_at','VARCHAR(20)')]
                _mig['pay_receipt'] = _mig.get('pay_receipt',[]) + [('idempotency_key','VARCHAR(128)')]
                for _tbl,_cols in _mig.items():
                    _c=_table_cols(_tbl)
                    for _n,_t in _cols:
                        if _c and _n not in _c:
                            db.session.execute(_text(f"ALTER TABLE {_tbl} ADD COLUMN {_n} {_t}")); db.session.commit()
                # --- v8.0 Phase 16: indexes for Universal Global Search (idempotent) ---
                _idx = [
                    ('ix_patient_mrn', 'patient', 'mrn'), ('ix_patient_phone', 'patient', 'phone'),
                    ('ix_patient_gov_id', 'patient', 'gov_id'), ('ix_invoice_status', 'invoice', 'status'),
                    ('ix_lab_order_sample_no', 'lab_order', 'sample_no'),
                    ('ix_rad_order_modality', 'rad_order', 'modality'),
                    ('ix_prescription_doctor', 'prescription', 'doctor'),
                    ('ix_asset_code', 'asset', 'code'), ('ix_asset_serial', 'asset', 'serial'),
                    ('ix_ambulance_plate', 'ambulance', 'plate'),
                    ('ix_search_log_username', 'search_log', 'username'),
                ]
                for _ix, _t, _col in _idx:
                    if _table_cols(_t) and _col in _table_cols(_t):
                        try:
                            db.session.execute(_text(f"CREATE INDEX IF NOT EXISTS {_ix} ON {_t} ({_col})"))
                            db.session.commit()
                        except Exception:
                            db.session.rollback()
            except Exception: db.session.rollback()
    
            # ---- one-time conversion of legacy Float money columns to integer cents ----
            # Money columns are now stored as INTEGER cents (see core/moneytype.py).
            # Databases written by v7.1 and earlier hold dollars as REAL, so each value
            # must be multiplied by 100 exactly once. The marker row makes this safe to
            # re-run: a fresh database is marked immediately with nothing to convert.
            _MONEY_COLS_V1 = {
                'invoice': ['discount', 'vat', 'paid'],
                'invoice_item': ['price'],
                'journal_line': ['debit', 'credit'],
                'commission_accrual': ['amount', 'paid'],
                'commission_payment': ['amount'],
                'pay_receipt': ['amount'],
                'expense': ['amount', 'paid'],
                'purchase': ['unit_cost', 'total', 'paid'],
                'pharmacy_sale': ['total'],
                'credit_note': ['amount'],
                'debit_note': ['amount'],
                'account': ['opening'],
                'budget': ['amount'],
                'recurring_journal': ['amount'],
                'rad_order': ['fee'],
            }
            _MONEY_COLS_V2 = {
                'service': ['price', 'price_insurance', 'price_corporate', 'price_vip',
                            'price_contract', 'cost', 'price_emergency', 'price_home'],
                'medicine': ['price', 'cost'],
                'employee': ['base', 'allowance', 'deduction'],
                'emp_loan': ['amount', 'paid', 'installment'],
                'emp_contract': ['salary'],
                'salary_advance': ['amount'],
                'asset': ['cost'],
                'maintenance_job': ['parts_cost', 'labor_cost'],
                'svc_contract': ['cost'],
                'cash_closing': ['opening_cash', 'expected_cash', 'actual_cash',
                                 'withdrawals', 'difference', 'collected'],
                'doctor': ['fixed_rate'],
            }
            try:
                from sqlalchemy import text as _text
                _row = db.session.execute(
                    _text("SELECT value FROM setting WHERE key='money_cents_v'")).fetchone()
                _at = int(_row[0]) if _row and str(_row[0]).isdigit() else 0
                _TARGET = 2
                if _at < _TARGET:
                    _fresh = db.session.execute(_text('SELECT COUNT(*) FROM invoice')).scalar() == 0
                    _todo = {}
                    if _at < 1: _todo.update(_MONEY_COLS_V1)
                    if _at < 2: _todo.update(_MONEY_COLS_V2)
                    if not _fresh:
                        for _t_, _cs in _todo.items():
                            _have = _table_cols(_t_)
                            if not _have:
                                continue
                            for _col in _cs:
                                if _col in _have:
                                    db.session.execute(_text(
                                        f'UPDATE {_t_} SET {_col} = CAST(ROUND({_col} * 100) AS INTEGER) '
                                        f'WHERE {_col} IS NOT NULL'))
                        app.logger.warning('Money columns migrated to integer cents (v%s -> v%s).', _at, _TARGET)
                    if _row:
                        db.session.execute(_text(
                            f"UPDATE setting SET value='{_TARGET}' WHERE key='money_cents_v'"))
                    else:
                        db.session.execute(_text(
                            f"INSERT INTO setting (key, value) VALUES ('money_cents_v', '{_TARGET}')"))
                    db.session.commit()
            except Exception as _e:
                db.session.rollback()
                try: app.logger.warning('cents migration skipped: %s', _e)
                except Exception: pass
    
        if not Branch.query.first():
            db.session.add(Branch(code='HQ', name='Main Branch', active=True)); db.session.commit()
        if not Warehouse.query.first():
            db.session.add(Warehouse(code='MAIN', name='Main Store',
                                     branch_id=Branch.query.first().id, active=True))
            db.session.commit()
        # backfill per-warehouse levels for items created before multi-warehouse
        from .core.stock import ensure_levels
        for _m in Medicine.query.all():
            ensure_levels(_m)
        db.session.commit()
        if not User.query.first():
            import os
            initial_password = os.environ.get('INITIAL_ADMIN_PASSWORD', '')
            # Never create a known credential in a deployed environment. A
            # local developer may opt in explicitly; production must provide a
            # strong, unique bootstrap password through the environment.
            force_change = True
            if not initial_password:
                if app.config.get('TESTING', False):
                    # Test fixtures intentionally use their historical fixture
                    # credential; this branch is never active in production.
                    initial_password = 'admin123'
                elif app.config.get('DEBUG', False):
                    # Local/development convenience: simple known login (admin /
                    # admin123), no forced change. NOT used in production.
                    initial_password = 'admin123'
                    force_change = False
                else:
                    import secrets
                    initial_password = secrets.token_hex(8)  # 16-character secure fallback
            minimum_length = 4 if (app.config.get('TESTING', False) or app.config.get('DEBUG', False)) else 12
            if len(initial_password) < minimum_length:
                raise RuntimeError(f'INITIAL_ADMIN_PASSWORD must contain at least {minimum_length} characters.')
            db.session.add(User(username='admin', name='System Administrator',
                                role='super_admin', pw=generate_password_hash(initial_password),
                                active=True, branch_id=Branch.query.first().id,
                                must_change_pw=force_change))
        for k,v in [('company','Modern Diagnostic Center'),('currency','$'),('capital','0'),('vat','0'),('appname','MDC ERP'),('logo',''),('brand',''),('paper','A4'),('print_header',''),('print_footer','Thank you for choosing us.'),('dev_mode','0'),('rad_fee','10'),('login_logo',''),('login_bg',''),('favicon',''),('wm_on','1'),('ph_on','1'),('pf_on','1'),('wm_text','')]:
            if not Setting.query.get(k): db.session.add(Setting(key=k,value=v))
        if not Account.query.first():
            def A(code,name,typ,parent=None,group=False,opening=0):
                x=Account(code=code,name=name,type=typ,parent_id=(parent.id if parent else None),is_group=group,opening=opening,active=True)
                db.session.add(x); db.session.flush(); return x
            assets=A('1000','ASSETS','Asset',group=True)
            cb=A('1100','Cash and Bank','Asset',assets,group=True)
            A('1101','Main Account (USD)','Asset',cb,opening=56250); A('1102','Cash in Hand','Asset',cb,opening=5320); A('1103','Mobile Money','Asset',cb,opening=24750)
            # each mobile-money provider gets its own account so the ledger shows them separately
            A('1104','Sahal','Asset',cb); A('1105','EVC','Asset',cb); A('1106','E. Dahab','Asset',cb)
            A('1107','MyCash','Asset',cb); A('1108','Premier Wallet','Asset',cb)
            A('1200','Accounts Receivable','Asset',assets); A('1300','Medical Supplies Inventory','Asset',assets)
            fa=A('1500','Fixed Assets','Asset',assets,group=True); A('1510','Equipment','Asset',fa); A('1520','Accumulated Depreciation','Asset',fa)
            liab=A('2000','LIABILITIES','Liability',group=True)
            A('2100','Accounts Payable','Liability',liab); A('2200','Salaries Payable','Liability',liab); A('2300','Doctor Commission Payable','Liability',liab); A('2400','VAT Payable','Liability',liab); A('2500','Loans Payable','Liability',liab)
            eq=A('3000','EQUITY','Equity',group=True); A('3100',"Owner's Capital",'Equity',eq); A('3200','Retained Earnings','Equity',eq)
            inc=A('4000','INCOME','Income',group=True)
            A('4100','Laboratory Revenue','Income',inc); A('4200','Radiology Revenue','Income',inc); A('4300','Consultation Revenue','Income',inc); A('4400','Other Service Revenue','Income',inc); A('4450','Contrast Income','Income',inc)
            exp=A('5000','EXPENSES','Expense',group=True)
            cos=A('5100','Cost of Services','Expense',exp,group=True); A('5110','Direct Test Costs','Expense',cos); A('5120','Medical Supplies & Contrast','Expense',cos); A('5130','Doctor Commission','Expense',cos)
            oe=A('6000','Operating Expenses','Expense',exp,group=True)
            A('6100','Salaries & Wages','Expense',oe); A('6200','Rent','Expense',oe); A('6300','Utilities','Expense',oe); A('6400','Depreciation','Expense',oe); A('6500','Other Operating Expenses','Expense',oe)
            A('7000','Income Tax','Expense',exp)
        db.session.commit()
        if demo and Patient.query.count()==0:
            seed_demo()
        # Belt-and-suspenders: on every boot, make sure the structural seed this
        # version expects exists (branch, warehouse, stock levels, accounts). This
        # repairs a database restored from an older backup so inventory and the
        # ledger keep the current structure.
        try:
            ensure_seed()
        except Exception:
            db.session.rollback()


# ---------------------------------------------------------------------------
# The authoritative chart of accounts for THIS version. ensure_accounts() adds
# any of these that are missing WITHOUT touching existing rows — so when a user
# restores an older backup (which lacks accounts a new update added, e.g. the
# per-provider wallet accounts Sahal/EVC/E.Dahab), the new accounts are put back
# and the general ledger keeps the current update's structure.
_CHART = [
    ('1000', 'ASSETS', 'Asset', None, True),
    ('1100', 'Cash and Bank', 'Asset', '1000', True),
    ('1101', 'Main Account (USD)', 'Asset', '1100', False),
    ('1102', 'Cash in Hand', 'Asset', '1100', False),
    ('1103', 'Mobile Money', 'Asset', '1100', False),
    ('1104', 'Sahal', 'Asset', '1100', False),
    ('1105', 'EVC', 'Asset', '1100', False),
    ('1106', 'E. Dahab', 'Asset', '1100', False),
    ('1107', 'MyCash', 'Asset', '1100', False),
    ('1108', 'Premier Wallet', 'Asset', '1100', False),
    ('1200', 'Accounts Receivable', 'Asset', '1000', False),
    ('1250', 'Insurance Receivable', 'Asset', '1000', False),
    ('1300', 'Medical Supplies Inventory', 'Asset', '1000', False),
    ('1500', 'Fixed Assets', 'Asset', '1000', True),
    ('1510', 'Equipment', 'Asset', '1500', False),
    ('1520', 'Accumulated Depreciation', 'Asset', '1500', False),
    ('2000', 'LIABILITIES', 'Liability', None, True),
    ('2100', 'Accounts Payable', 'Liability', '2000', False),
    ('2200', 'Salaries Payable', 'Liability', '2000', False),
    ('2300', 'Doctor Commission Payable', 'Liability', '2000', False),
    ('2310', 'Radiologist Fee Payable', 'Liability', '2000', False),
    ('2400', 'VAT Payable', 'Liability', '2000', False),
    ('2500', 'Loans Payable', 'Liability', '2000', False),
    ('3000', 'EQUITY', 'Equity', None, True),
    ('3100', "Owner's Capital", 'Equity', '3000', False),
    ('3200', 'Retained Earnings', 'Equity', '3000', False),
    ('4000', 'INCOME', 'Income', None, True),
    ('4100', 'Laboratory Revenue', 'Income', '4000', False),
    ('4200', 'Radiology Revenue', 'Income', '4000', False),
    ('4300', 'Consultation Revenue', 'Income', '4000', False),
    ('4400', 'Other Service Revenue', 'Income', '4000', False),
    ('4450', 'Contrast Income', 'Income', '4000', False),
    ('5000', 'EXPENSES', 'Expense', None, True),
    ('5100', 'Cost of Services', 'Expense', '5000', True),
    ('5110', 'Direct Test Costs', 'Expense', '5100', False),
    ('5120', 'Medical Supplies & Contrast', 'Expense', '5100', False),
    ('5130', 'Doctor Commission', 'Expense', '5100', False),
    ('5140', 'Radiologist Fees', 'Expense', '5100', False),
    ('6000', 'Operating Expenses', 'Expense', '5000', True),
    ('6100', 'Salaries & Wages', 'Expense', '6000', False),
    ('6200', 'Rent', 'Expense', '6000', False),
    ('6300', 'Utilities', 'Expense', '6000', False),
    ('6400', 'Depreciation', 'Expense', '6000', False),
    ('6500', 'Other Operating Expenses', 'Expense', '6000', False),
    ('7000', 'Income Tax', 'Expense', '5000', False),
]


def ensure_accounts():
    """Idempotently add any accounts from _CHART that are missing. Never edits or
    deletes existing accounts. Returns the number of accounts added."""
    added = 0
    existing = {a.code: a for a in Account.query.all()}
    if not existing:
        return 0   # a truly empty DB is handled by init_db's full seed
    for code, name, typ, parent_code, is_group in _CHART:
        if code in existing:
            continue
        parent = Account.query.filter_by(code=parent_code).first() if parent_code else None
        a = Account(code=code, name=name, type=typ,
                    parent_id=(parent.id if parent else None), is_group=is_group, active=True)
        db.session.add(a); db.session.flush()
        existing[code] = a
        added += 1
    if added:
        db.session.commit()
    # Retire the legacy combined "Mobile Money" (1103): deactivate it so it is
    # hidden from new selection and the ledger once it has no balance — payments
    # now use the per-provider accounts (Sahal, EVC, E. Dahab, MyCash, Premier
    # Wallet). Existing balances stay visible until moved with the Split tool.
    _mm = Account.query.filter_by(code='1103').first()
    if _mm and _mm.active:
        _mm.active = False
        db.session.commit()
    return added


def ensure_seed():
    """Re-apply the structural seed every version needs, WITHOUT touching data.
    Called after a restore (and on every boot) so a restored older backup keeps
    the current update's structure and the system stays operational:
      • at least one Branch and one Warehouse (needed for stock, users, scoping)
      • per-item stock levels for any medicines that lack them
      • the current chart of accounts (per-provider wallet accounts, etc.)
    Only ADDS what's missing; never edits or deletes existing rows."""
    made = {}
    # 1) branch — needed by warehouses, users and branch scoping
    if not Branch.query.first():
        db.session.add(Branch(code='HQ', name='Main Branch', active=True)); db.session.commit()
        made['branch'] = 1
    # 2) warehouse — every stock operation needs at least one
    if not Warehouse.query.filter_by(active=True).first():
        db.session.add(Warehouse(code='MAIN', name='Main Store',
                                 branch_id=Branch.query.first().id, active=True)); db.session.commit()
        made['warehouse'] = 1
    # 3) stock levels for medicines created/restored without them
    try:
        from .core.stock import ensure_levels
        _lv = 0
        for _m in Medicine.query.all():
            ensure_levels(_m); _lv += 1
        db.session.commit()
        if _lv:
            made['stock_levels_checked'] = _lv
    except Exception:
        db.session.rollback()
    # 4) chart of accounts (per-provider wallets, contrast income, etc.)
    n_acc = ensure_accounts()
    if n_acc:
        made['accounts'] = n_acc
    return made

def seed_demo():
    # services
    svcs=[('LAB-01','Complete Blood Count','Laboratory',15,4),('LAB-02','Blood Sugar','Laboratory',8,2),
          ('RAD-CT','CT Scan - Head','Radiology',120,30),('RAD-XR','X-Ray Chest','Radiology',25,6),
          ('CON-01','Doctor Consultation','Consultation',20,0)]
    for c,n,d,p,co in svcs: db.session.add(Service(code=c,name=n,department=d,price=p,cost=co,active=True))
    for i,(nm,ph,g) in enumerate([('Omar Ali','61511','Male'),('Sahra Yusuf','61522','Female'),('Ahmed Nur','61533','Male')]):
        db.session.add(Patient(mrn=f'MRN{1001+i}',name=nm,phone=ph,gender=g))
    for nm,pos,b,a in [('Fatima Aden','Lab Tech',400,50),('Hassan Ali','Radiographer',450,60),('Amina Omar','Receptionist',300,30)]:
        db.session.add(Employee(code='EMP'+str(Employee.query.count()+1),name=nm,position=pos,base=b,allowance=a,active=True))
    db.session.add(Medicine(name='Contrast Media (Iohexol)',batch='B2401',expiry='2026-12-31',qty=40,reorder=10,price=0,cost=12))
    db.session.add(Medicine(name='X-Ray Film Sheets',batch='B2402',expiry='2027-06-30',qty=120,reorder=30,price=0,cost=1.5))
    db.session.add(Medicine(name='CBC Reagent Kit',batch='B2403',expiry='2026-09-30',qty=8,reorder=10,price=0,cost=45))
    _m1=Medicine(name='Paracetamol 500mg',batch='P2401',expiry='2027-03-31',qty=200,reorder=50,price=1,cost=0.3)
    _m2=Medicine(name='Amoxicillin 500mg',batch='P2402',expiry='2026-11-30',qty=90,reorder=30,price=3,cost=1.1)
    db.session.add(_m1); db.session.add(_m2); db.session.commit()
    db.session.add(Prescription(patient_id=(Patient.query.first().id if Patient.query.first() else None), medicine_id=_m1.id, qty=10, dosage='1x3 for 3 days', doctor='Dr. Yusuf Warsame', status='Pending'))
    d1=Doctor(name='Dr. Yusuf Warsame',specialty='General Practitioner',phone='615700',commission_type='Percent',percent_rate=0.10,active=True)
    d2=Doctor(name='Dr. Halima Aden',specialty='Physician',phone='615711',commission_type='Fixed',fixed_rate=5,active=True)
    db.session.add(d1); db.session.add(d2); db.session.commit()
    db.session.add(Referral(patient_name='Khadija Nur',patient_phone='6152233',patient_age='34',patient_gender='Female',doctor_id=d1.id,hospital='General Hospital',tests='CT Scan - Head, Complete Blood Count',notes='Headache',status='New'))
    db.session.add(Referral(patient_name='Ahmed Farah',patient_phone='6154455',patient_age='51',patient_gender='Male',doctor_name='Dr. Samatar',hospital='Medina Clinic',tests='Chest X-Ray',notes='Cough 2 weeks',status='New'))
    db.session.commit()
    _p=Patient.query.first(); _s=Service.query.filter_by(code='RAD-CT').first()
    _inv=Invoice(patient_id=_p.id if _p else None, referring_doctor_id=d1.id, vat=0, discount=0, paid=0, status='Unpaid', branch_id=(Branch.query.first().id if Branch.query.first() else None))
    db.session.add(_inv); db.session.commit()
    db.session.add(InvoiceItem(invoice_id=_inv.id, desc=(_s.name if _s else 'CT Scan - Head'), qty=1, price=(_s.price if _s else 120)))
    _rs=Service.query.filter_by(code='RAD-CT').first()
    db.session.add(RadOrder(patient_id=_p.id if _p else None, service_id=_rs.id if _rs else None, modality='CT', status='Reported', report='No acute abnormality detected. Normal study.', radiologist='Dr. Yusuf Warsame', fee=10.0))
    _ls=Service.query.filter_by(code='LAB-01').first()
    db.session.add(LabOrder(patient_id=_p.id if _p else None, service_id=_ls.id if _ls else None, status='Requested'))
    for un,nm,role in [('accountant','Aisha Finance','accountant'),('reception','Khadija Front','reception'),('lab','Lab User','lab_tech'),('radio','Rad User','radiologist'),('auditor','Audit User','auditor')]:
        if not User.query.filter_by(username=un).first():
            db.session.add(User(username=un,name=nm,role=role,pw=generate_password_hash('1234'),active=True))
    db.session.commit()
