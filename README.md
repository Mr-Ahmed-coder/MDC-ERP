# MDC Diagnostic ERP — v7.9 (Modular / Blueprints)

Modern Diagnostic Center — Hospital ERP
Python · Flask Blueprints · SQLAlchemy · Alembic · SQLite (dev) / PostgreSQL (prod) · Docker

Login default: **admin / password set during initialization** — isla markiiba beddel (Users).

📚 **Full documentation:** see [`docs/`](docs/README.md) — Installation · User Manual · Administrator Manual · Backup & Restore · Deployment · API. Version history in [`docs/CHANGELOG.md`](docs/CHANGELOG.md).

---

## 1. Si degdeg ah u kicinta (Development — SQLite)

```bash
pip install -r requirements.txt
python run.py            # http://127.0.0.1:5000
python run.py --demo     # xog tijaabo ah (demo data)
python run.py --online   # LAN: kombiyuutarrada kale ee xafiiska
```

Windows: laba-guji `run.bat` · Linux/Mac: `./run.sh`

Database-kaagii hore ee `erp.db` **si toos ah ayuu ula shaqeynayaa** — schema-gu isma beddelin,
bootstrap-ku wuxuu leeyahay safe column migration sidii hore.

## 2. Production (Docker + PostgreSQL)

```bash
cp .env.example .env      # beddel SECRET_KEY iyo DB_PASSWORD
docker compose up -d --build
# http://<server>:8000
```

Compose-ku wuxuu wataa PostgreSQL 16 + gunicorn (4 workers) + healthcheck.
Haddii aad HTTPS isticmaasho (Nginx/Caddy horteeda), dej `COOKIE_SECURE=1`.

Render / Heroku: `render.yaml` iyo `Procfile` waa diyaar (`gunicorn wsgi:app`).

## 3. Qaab-dhismeedka (Architecture)

```
mdc_erp/
├── __init__.py          App factory: blueprints, CSRF, headers, logging, errors, CLI
├── config.py            Dev (SQLite) / Prod (PostgreSQL) — DATABASE_URL
├── extensions.py        db (SQLAlchemy) + migrate (Alembic)
├── models.py            30 models oo dhan (Patient, Invoice, Account, ...)
├── bootstrap.py         First-run: tables, admin, settings, chart of accounts, demo seed
├── core/
│   ├── security.py      Roles, RBAC (configurable), login/perm decorators, audit, CSRF token
│   ├── helpers.py       money(), today(), cur_year()
│   ├── ui.py            CSS theme, sidebar nav, page() shell, public_shell()
│   ├── crud.py          Generic CRUD engine + module registry (register(...))
│   ├── posting.py       Accounting engine: post_journal, repost_invoice/payment, hooks
│   └── printing.py      Printable A4 shell (logo/header/footer/watermark from Settings)
└── blueprints/
    ├── auth.py          Login, logout, dark mode, 2FA (TOTP), /security
    ├── dash.py          Dashboard KPIs + global search
    ├── modules.py       /m/<mod> generic list/new/edit/delete for all registered modules
    ├── patients.py      Patient chart, printable report, statements
    ├── lab.py           Laboratory workflow (order → collect → result → approve → print)
    ├── radiology.py     Radiology workflow (order → report → print)
    ├── pharmacy.py      Sales + prescription dispensing (stock + accounting)
    ├── billing.py       Invoices, items, payments, doctor commission
    ├── accounting.py    Journal, ledger, COA (hierarchical), P&L / TB / BS / Cash book
    ├── referrals.py     Public /refer form + internal referral management
    ├── reports.py       Overview, summary, revenue analysis, rad fees, CSV export
    ├── portal.py        Patient portal (MRN + phone login)
    ├── hr.py            Attendance, leave, payroll posting
    ├── api.py           REST API + JWT (/api/login, /api/patients, ...)
    └── admin.py         Users, audit log, settings, permissions matrix, backup/restore
```

## 4. Waxa cusub ee v2 (Upgrade highlights)

| Area | Hore (v1) | Hadda (v2) |
|---|---|---|
| Structure | 1 file, 2,900+ sadar | Package modular ah: 6 core + 15 blueprints |
| Database | SQLite kaliya | SQLite (dev) + **PostgreSQL** (prod), Alembic migrations |
| CSRF | Ma jirin | **Auto-injected token** POST form kasta + validation dhexe |
| Permissions | Hard-coded | **Configurable matrix** (`/permissions`) — Settings ku kaydsan |
| Roles | 9 | 12 (+ Branch Manager, IT Administrator, Auditor) |
| Errors | Flask default | Bogag 403/404/500 oo qurxoon + rollback |
| Logging | Ma jirin | Rotating file log (`mdc_erp.log`) |
| Headers | Ma jirin | X-Frame-Options, nosniff, Referrer-Policy |
| Docker | SQLite volume | **Compose: app + PostgreSQL 16** + healthcheck |
| Tests | Ma jirin | 9 automated smoke tests (`pytest`) |

Wax kasta oo v1 ka jiray — dashboard, lab, radiology, pharmacy, invoicing,
accounting (double-entry), commissions, referrals, portal, API/JWT, 2FA,
backup, HR — **way shaqeeyaan isla URL-adii hore** (endpoints ma beddelmin).

## 5. Database migrations (Alembic)

Marka aad model beddesho:

```bash
flask --app wsgi db init        # hal mar kaliya
flask --app wsgi db migrate -m "add column X"
flask --app wsgi db upgrade
```

## 6. Tests

```bash
pip install pytest
pytest -q        # 9 passed
```

## 7. CLI

```bash
flask --app wsgi init-db      # tables + admin + chart of accounts
flask --app wsgi seed-demo    # + demo data
```

## 8. Phase 2 — waxa lagu daray

| Feature | Halka laga isticmaalo |
|---|---|
| **Reception Queue** | Sidebar → Reception Queue: Check-in → token number maalinle ah → Call/Start → Done. Board weyn: *Now Serving / Next / Waiting / Done* |
| **ICD-10 diagnosis** | Consultation form: 40 code oo caadi ah (malaria B54, typhoid A01.0, hypertension I10...) — qor ama ka dooro, column-ka liiska ayuu ka muuqdaa |
| **Lab reference ranges** | Service Catalog: `Reference Range` + `Unit` fields — waxay ka muuqdaan result entry iyo warbixinta la daabaco |
| **Radiology image upload** | Write Report: JPG/PNG images (multiple). Thumbnails, print grid, iyo portal-ka bukaanka (kaliya lahaanaha). Faylasha khaldan waa la diidaa |
| **Barcode + QR daabacaad kasta** | Invoice/Lab/Rad/Patient reports: Code-128 barcode (MRN/INV no.), QR verification, taariikhda & qofka daabacay |
| **Document verification** | QR-ka waxa uu furaa `/verify?ref=...&sig=...` (public) — HMAC signature ayaa xaqiijinaya in dokumentigu nidaamkan ka baxay |

Images waxay ku kaydsan yihiin `DATA_DIR/uploads/rad/` (Docker: `/data/uploads/rad`).

## 9. Phase 3 — waxa lagu daray

| Feature | Halka laga isticmaalo |
|---|---|
| **Asset Management** | Sidebar → Assets & Maintenance: diiwaanka hantida (qalabka caafimaad, kombiyuutarrada, gawaarida...) oo leh cost, **book value (straight-line depreciation)**, warranty iyo calibration tracking |
| **Maintenance** | Work orders (Preventive/Corrective), engineer assignment, kharashka spare parts + labor, service history. Overview dashboard: calibration ≤30 maalmood, warranty ≤60 maalmood, open jobs — hal-guji "Mark Done" |
| **Branch Comparison** | Reports → Branch Comparison: dakhliga, lacagta la ururiyay, kharashka iyo net-ka **branch kasta + wadarta HQ**, sanad-doorasho iyo bar chart |
| **In-App Notifications** | 🔔 bell topbar-ka oo leh badge. Events: referral cusub (→ reception), lab result approved (→ reception), **low stock** (→ storekeeper), leave request (→ HR). Role kasta wuxuu arkaa kuwiisa oo keliya; Super Admin dhammaan |
| **Role cusub** | Maintenance Engineer — permissions matrix-ka ayaa lagu maamulaa |

## 10. Phase 4 — Billing / Accounting / Inventory (qoto dheer)

| Feature | Halka laga isticmaalo |
|---|---|
| **Daily Cash Closing** | Billing → Daily Cash Closing: lacagta la ururiyay habka lacag-bixinta (Cash/Bank/Mobile Money/Card), kharashka maalinta, NET CASH, "Close Day" (Audit Log ayaa lagu diiwaangeliyaa + accountant notification), iyo daabacaad saxiixyo leh |
| **Refunds** | Invoice → Payment panel: "Issue Refund" oo leh qadar + sabab. Validation buuxa (0 < refund ≤ paid), Audit Log, accountant notification, accounting-ka si toos ah ayuu isu saxaa |
| **Cash Flow Statement** | Accounting → Cash Flow: bil kasta cash in/out (accounts 1101/1102/1103), running balance, closing position |
| **AR Aging** | Accounting → AR Aging: invoices-ka aan la bixin oo buckets ah (0–30 / 31–60 / 61–90 / 90+ maalmood) |
| **AP Aging** | Accounting → AP Aging: purchases + expenses-ka deynta ah oo isla buckets-kaas ah |
| **Stock Adjustments** | Inventory → Stock Adjustments: sax tirakoob, dhaawac, expiry write-off — audit trail buuxa (yaa sameeyay, goorma, sababta), low-stock notification |
| **Consumption Report** | Inventory → Consumption Report: item kasta — la iibiyay, Rx lagu bixiyay, adjustments, stock hadda + **stock valuation** (qty × cost) |

## 11. Phase 5 — Multi-Warehouse, PO/GRN Workflow & Swagger

| Feature | Halka laga isticmaalo |
|---|---|
| **Warehouses** | Inventory → Warehouses: bakhaarro aan xadidnayn, branch kasta. "Main Store" si toos ah ayaa loo abuuraa, stock-gii hore-na si toos ah ayaa loogu wareejiyaa |
| **Multi-warehouse stock** | Inventory → Stock Transfers: matrix muujinaya item kasta bakhaar kasta + wadarta. Invariant: wadarta = isku-darka bakhaarrada (si toos ah ayaa loo ilaaliyaa) |
| **Stock Transfers** | Foom wareejin ah oo leh validation (in ka badan inta bakhaarka taal waa la diidaa, isla bakhaar → isla bakhaar waa la diidaa), history buuxa |
| **Purchase Orders (PO)** | Inventory → Purchase Orders: workflow saddex tallaabo ah — **Requested** (codsi) → **Ordered** (la ansixiyay) → **Received**. Accounting-ka waxaa la qoraa KALIYA marka la helo (Requested/Ordered kuma jiraan ledger-ka) |
| **Goods Received (GRN)** | Badhanka "Receive (GRN)": stock-gu si toos ah ayuu ugu koraa bakhaarka la doortay (haddii supply item lala xiriiriyay), accounting waa la qoraa, accountant notification, iyo **GRN daabacaad rasmi ah** (saxiixyo + barcode + QR) |
| **Warehouse-aware deductions** | Iibka farmashiga, Rx dispensing iyo invoice auto-deduct dhammaantood waxay ka gooyaan Main Store si invariant-ku u sii jiro |
| **Swagger API Docs** | `/api/docs` — Swagger UI interactive ah; `/api/openapi.json` — OpenAPI 3.0 spec (login, patients, services, invoices, payments, stats) |

Diiwaannadii hore ee purchases (v1) waxay u muuqdaan "Received" — accounting-koodii wuu sii jiraa, waxna ma beddelmaan.

## 12. Phase 6 — Enterprise Accounting

| Feature | Halka laga isticmaalo |
|---|---|
| **Bank Accounts** | Accounting → Bank Accounts: koontooyin bangi/mobile-money oo lala xiriiriyo COA (1101/1102/1103) |
| **Bank Reconciliation** | Accounting → Bank Reconciliation: calaamadee dhaqdhaqaaqa la xaqiijiyay (cleared), isbarbardhig ledger vs statement, kala-duwanaanshaha si toos ah |
| **Credit Notes** | Billing → Credit Notes: dhimis invoice (Dr 4400 Sales Returns / Cr 1200 AR) — status-ka invoice iyo AR Aging si toos ah ayay ula socdaan |
| **Debit Notes** | Inventory/AP → Debit Notes: celin alaab supplier (Dr 2100 AP / Cr 1300 Inventory), waxaa lagu xiraa Purchase la helay |
| **Payment Allocation** | Billing → Receive Payment: lacag bukaan laga helay oo si toos ah loogu qaybiyo invoices-ka ugu da'da weyn marka hore (oldest-first) |
| **Budgets** | Accounting → Budgets + Budget vs Actual report (koontada kharashka sanadkiiba) |
| **Cost Centers** | Accounting → Cost Centers: kharashaadka waaxyaha (Lab, Radiology, Admin…) + Cost Center report |
| **Fiscal Periods** | Accounting → Fiscal Periods: xir/fur bil kasta — bil xiran **nidaamka oo dhan** waa laga xannibay diiwaan-gelin (expenses, journal, invoices, purchases…) |
| **Year-End Close** | Depreciation run (DEP-YYYY, straight-line 1590/5900) → Close Year (CLS-YYYY → 3200 Retained Earnings, 12-ka bilood oo dhan waa la xiraa) |
| **Financial Ratios** | Accounting → Ratios: Current/Quick Ratio, Net Margin, Expense Ratio iyo kuwo kale + sharraxaad |
| **Tax Report** | Accounting → Tax/VAT: VAT bishiiba (2400 VAT Payable) |
| **Multi-Currency** | Admin → Currencies: sarrifka lacagaha (USD base) — ratios-ka waxaa lagu muujiyaa lacagaha kale |
| **Excel Exports** | `/export/xlsx/…` — Trial Balance, Ledger, AR/AP Aging, Budget (openpyxl, brand blue header) |
| **PDF Statements** | Accounting → Ratios → Downloads: Income Statement + Balance Sheet + Trial Balance hal PDF (reportlab, brand colors) |

**Sax muhiim ah (v2.5):** khariidaddii lacag-bixinta ee v1 waa la saxay — Cash→1101, Bank→1102, Mobile Money→1103, Card→1102 (hore waa kala rogneyd). Diiwaannadii hore lama taaban; kuwa cusub ayaa si sax ah loo qoraa.

## 13. Phase 7 — Shaqada Hal Meel (One-Place Workflow)

| Feature | Sharraxaad |
|---|---|
| **Patient Hub** | Liiska Patients magaca bukaanka guji (ama search-ka kore ka raadi) → bog keliya oo leh: xogta + balance, badhamada **+ Consultation / + Lab / + Radiology / + Invoice / 💵 Receive Payment / 🕐 Check-in** (bukaanku horey ayuu ugu buuxsan yahay foom kasta), iyo taariikhda oo dhan (consultations, lab, raajo, invoices) |
| **URL Prefill** | Foom kasta waxaa lagu buuxin karaa URL args (`/m/consult/new?patient_id=5`) — hub-ku sidaas ayuu foomamka ugu diyaariyaa |
| **Dashboard Quick Actions** | "Shaqo Degdeg ah" — badhamo waaweyn oo door kasta u gaar ah (reception wuxuu arkaa Bukaan Cusub/Queue/Invoice; accountant wuxuu arkaa Cash Closing/Receive Payment…) |
| **Global Search** | Sanduuqa raadinta ee kore (bog kasta): magac, telefoon, MRN, ID ama lambar invoice — natiijadu waxay ku geynaysaa Patient Hub |
| **COA ↔ Statements Link** | Opening Balance kasta oo Chart of Accounts lagu qoro wuxuu si toos ah uga muuqdaa: Trial Balance (calaamad "incl. opening"), Balance Sheet ("Opening Balances (COA)"), Cash Book, General Ledger (saf OPENING ah oo running balance-ka bilaaba), iyo Excel/PDF exports. Isu-dheellitirka waxaa hubiya koonto otomaatig ah **3199 Opening Balance Equity** — haddii aad labada dhinac (hanti + raasamaal) si sax ah u geliso, way libdhaa |

## 14. Phase 8 — Clinical Workflow (Registration → Receipt)

| Feature | Sharraxaad |
|---|---|
| **Patient Registration (buuxa)** | 20+ goobood: laba telefoon, blood group, marital, occupation, emergency contact, insurance (shirkad + lambar), allergies, medical history, **sawir bukaan** (upload), status Active/Inactive. Da'da si toos ah ayaa looga xisaabiyaa DOB, MRN + reg_by si toos ah |
| **Patient Card** | 🪪 kaadh daabacan (sawir, MRN barcode, QR verification, blood group, emergency, insurance, allergies) — liiska Patients iyo Patient Hub labadaba |
| **Appointments (buuxa)** | Service, Visit Type (New/Follow-up/Emergency), Priority (Normal/Urgent), 7 status: Scheduled → Confirmed → Waiting → In Progress → Done / Cancelled / No Show |
| **Check-in oo la hagaajiyay** | Badhamada Confirm / Check-in / No show; check-in kasta **dhakhtarka ayaa ogeysiis helaya** (token + magaca bukaanka) |
| **Consultation + Vitals** | BP, Temp, Pulse, SpO2, Miisaan, Dherer + ICD-10 + status Open/Completed; saf kasta wuxuu leeyahay badhamo 🧪 Lab / 📷 Rad / 💊 Rx / 🧾 Bill (bukaanku horey ugu buuxsan) |
| **Follow-up Automation** | Consultation followup date leh → **appointment si toos ah ayaa loo qorsheeyaa** (Follow-up) + reception notification |
| **Discount Authorization** | Discount kaliya waxaa oggolaan kara Admin/Accountant/Branch Manager; sabab (Staff/Charity/Promotion/Management/Insurance), approved-by + taariikh waa la duubaa, audit trail "DISCOUNT INV-…" |
| **Payment Receipts (RCT)** | Lacag-bixin kasta (split payments oo dhan) → **RCT-xxxxx** leh cashier, method, reference; daabacaad rasmi ah (logo, adeegyada, discount, balance, QR + barcode). Payalloc-guna receipts wuu abuuraa |
| **Insurance Payment** | Habka "Insurance" → 1250 Insurance Receivable (si toos ah ayaa loo abuuraa) |

Workflow buuxa: Registration → Appointment → Confirm → Check-in (token + doctor notify) → Consultation (vitals, ICD, orders) → Billing → Discount (oggolaansho) → Payment → Receipt → Follow-up (auto). Xog mar la geliyay lama soo celcelinayo.

## 15. Phase 9 — LIS, Security & Enterprise Extras

| Feature | Sharraxaad |
|---|---|
| **Sample Collection & Tracking** | Workflow buuxa: Requested → **Collect** (sample barcode SMP-xxxxx + specimen + cidda qaadday + waqtiga) → 🏷 **Label** daabacan (barcode) → **Receive** → Result → Approve |
| **Panic Values** | Service kasta panic low/high; natiijo halis ah → calaamad ⚠ PANIC (liiska + report-ka) + **dhakhtarka ogeysiis degdeg ah** |
| **Delta Checks** | Natiijada waxaa la barbardhigaa tii hore ee isla bukaanka/isla baaritaanka — isbeddel >50% → calaamad Δ |
| **Lab QC (IQC)** | Lab → QC: control runs (L1/L2) leh target mean ± SD; z-score si toos ah — In control / Warning (2–3SD) / OUT (>3SD) |
| **Report Signatures** | Report-ka lab wuxuu leeyahay Performed by (technician) + Verified & Approved (signatory) + sample chain |
| **Login History** | Admin → Security: 200-kii login ee u dambeeyay — user, IP, guul/FAILED |
| **IP Restriction** | Prefix allowlist (tusaale 192.168.1.) — shabakadda xafiiska oo keliya; 127.0.0.1 weligiis waa furan |
| **Backup Manager** | Admin → Backup: SQLite hal-guji download (mdc-erp-backup-YYYY-MM-DD.db); PostgreSQL: pg_dump tilmaamo |
| **Batch / Lot (FEFO)** | Inventory → Batches: batch no + expiry + qty; liisku wuxuu u kala horreeyaa kuwa ugu dhow inay dhacaan (FEFO), midab expiry |
| **HR Extras** | Contracts (nooc, muddo, mushahar), Performance Reviews (★1–5), Training Records |
| **Service Contracts** | Assets → Contracts: heshiisyada dayactirka qalabka; kuwa 60 maalmood gudahood dhammaanaya Maintenance Dashboard ayay ka muuqdaan |

**Waxa weli u baahan adeegyo dibadda ah (diyaar marka la helo):** SMS/WhatsApp gateway (API key), PACS/DICOM (server), HL7/ASTM analyzer interfaces, mobile apps, Redis/Nginx/HTTPS (production server), AI models.

## 16. Phase 10 — Messaging & Deployment Pack

| Feature | Sharraxaad |
|---|---|
| **SMS / WhatsApp Outbox** | Admin → Messages: fariin kasta oo baxda (xusuusin ballan 📱, "natiijadaadu waa diyaar" marka lab la ansixiyo) waxay gashaa Outbox leh status Pending/Sent/Failed |
| **Gateway pluggable** | URL + API key + Sender ID geli (Hormuud, Twilio bridge, gateway kasta oo JSON POST aqbala) — gateway la'aan fariimuhu waa **Pending** oo waxba ma lumaan; markaad key hesho "Retry all" guji |
| **Appointment Reminders** | Liiska Appointments: badhan 📱 SMS saf kasta (Scheduled/Confirmed) — xusuusin Somali ah oo taariikhda/waqtiga leh |
| **Result-ready SMS** | Lab Approve → bukaanka telefoonkiisa fariin si toos ah ayaa loogu diraa (Ref LAB-xxxx) |
| **deploy/nginx.conf** | Reverse proxy production (HTTPS via certbot tilmaamo, upload limit 25MB) |
| **deploy/backup.sh** | Backup maalinle ah (cron): SQLite ama PostgreSQL/Docker, 30 maalmood ayaa la haynaa |
| **.github/workflows/ci.yml** | CI pipeline: push kasta pytest si toos ah ayaa loo wadaa |

## 17. Phase 11 — Portal Booking, Auto-Reorder, Analytics & FHIR

| Feature | Sharraxaad |
|---|---|
| **Online Appointment Booking** | Bukaanku portal-ka (MRN + telefoon) ayuu ka qabsan karaa ballan: taariikh (mustaqbal keliya), waqti, waax — reception si toos ah ayaa ogeysiis u helaya, ballanku wuxuu galaa Appointments (Scheduled, "Online booking") |
| **Auto-Reorder** | Stock kasta oo hoos u dhaca reorder level → **PO (Requested) si toos ah** ayaa loo abuuraa (tiro = 2×reorder − hadda) + storekeeper notification; PO furan hadduu jiro mid labaad lama abuuro |
| **Productivity Report** | Reports → Productivity: dhakhtar kasta consultations bishiiba, lab staff (natiijooyin la geliyay / la ansixiyay), KPIs Pending Lab/Radiology |
| **Inventory Valuation** | Inventory → Valuation: item kasta qty × cost + wadarta qiimaha bakhaarka |
| **FHIR R4 API** | `/api/fhir/Patient/<id>` iyo `/api/fhir/Observation?patient=<id>` (JWT) — isku-xirka nidaamyada caafimaadka ee FHIR taageera (caymis, MOH, HIS kale) |

## 18. Phase 12 — Blood Bank, Vaccination & Quality (ISO 15189)

| Feature | Sharraxaad |
|---|---|
| **Blood Bank 🩸** | Clinical → Blood Bank: diiwaanka deeq-bixiyeyaasha (screening notes) + Blood Units (unit no, group, expiry midab leh "exp soon" ≤7 maalmood, status Available/Reserved/Used, cidda la siiyay) |
| **Vaccination 💉** | Diiwaan tallaal (nooc, dose #, batch, next due) + **Certificate rasmi ah** oo daabacan (QR + barcode) |
| **SOPs & Document Control** | Quality → SOPs: code, version, review due (OVERDUE/30d midab) — ISO 15189 document control |
| **Incidents / Nonconformities** | Sample rejection, equipment failure, cabasho… severity + corrective action + status |
| **Internal Audits** | Diiwaanka hanti-dhawrka gudaha + findings + corrective action due |
| **Patient Feedback ⭐** | Portal-ka bukaanku ★1–5 + faallo — branch manager notification, liiska Quality → Feedback |
| **Duplicate Patient Detection** | Bukaan cusub oo telefoon/magac jira leh → digniin + tixraaca kii jiray; laba-gujin ayaa loo baahan yahay si loo abuuro |
| **Password Policy** | Ugu yaraan 8 xaraf + lambar, passwords caadiga ah waa la diidaa |
| **LOINC / CPT** | Service kasta LOINC + CPT codes; LOINC-gu report-ka lab ayuu ka muuqdaa (interoperability) |

## 19. Phase 13 — Doctor Referral Portal (/dr)

| Feature | Sharraxaad |
|---|---|
| **Doctor Login** | Dhakhtar kasta oo dibadda ah (isbitaal/clinic kale) akoon: Clinical → Referring Doctors → Portal Username + Password (policy: 8+ xaraf). Portal-ka: `/dr` |
| **Dashboard** | Dr dashboard gooni ah: My Referrals / Pending / Completed, raadinta bukaannadiisa — **qiimo, biil, accounting midna MA arko** |
| **New Referral** | Hal foom: bukaan (telefoon jira → diiwaankii hore ayaa la isticmaalaa, MRN auto), clinical info (complaint, history, prov. dx, **priority Routine/Urgent/STAT**), iyo baaritaannada Lab + Radiology (magacyo keliya, qiimo la'aan) |
| **Auto-workflow** | Submit → Patient + Referral (REF-xxxx) + Lab/Rad orders si toos ah; reception + lab + radiology ogeysiisyo (STAT/Urgent waa ku calaamadaysan yihiin) |
| **Status Tracking** | Waiting → Sample Collected → Under Testing → Under Reporting → Completed (magacyo dhakhtar-u-fudud) |
| **Reports & Images** | Natiijo la ansixiyay → dhakhtarku wuu arkaa/daabacaa (QR + barcode), raajada sawirradeeda wuu arki karaa — kaliya bukaannadiisa (isolation waa la tijaabiyay) |
| **Doctor SMS** | Report la ansixiyo → dhakhtarka telefoonkiisa fariin (outbox) |
| **Comments (2-dhinac)** | Dhakhtarku su'aal/faallo wuu ku dari karaa REF kasta; shaqaaluhu waxay kaga jawaabaan Referrals → Thread — labada dhinacba waa arkaan |
| **Security** | Session gooni ah (staff nav ma jiro), dhakhtar kastaa wuxuu arkaa bukaannadiisa iyo codsiyada uu diray oo KELIYA (403 kuwa kale) |

## 20. Phase 14 — Remote Radiologist Portal (/rrad) — Teleradiology

| Feature | Sharraxaad |
|---|---|
| **Radiologist Accounts** | Radiology → Radiologists: radiologist fog (magaalo/dal kale) — Portal Username + Password. Portal: `/rrad` |
| **Case Dispatch 📤** | Technician-ku study-ga (Imaged) wuxuu gujiyaa Dispatch: files upload (**DICOM .dcm, ZIP, RAR, PDF, JPG, PNG**) + radiologist doorasho → SMS ayaa loo diraa |
| **Radiologist Dashboard** | New Cases / In Progress (Drafts) / Completed + filter/search — kiisaska loo qoondeeyay KELIYA, qiimo/biil ma jiraan |
| **Case Page** | Xogta bukaanka (magac, da', jinsi), clinical history + referring doctor (haddii referral yahay, priority STAT/Urgent), files (sawirro inline, DICOM/ZIP/PDF download), **warbixinnadii hore ee isla bukaanka** (comparison) |
| **Report Editor** | 12 templates (CT Brain/Chest/Abdomen/Spine, MRI Brain/Spine/Knee, X-Ray, Ultrasound Abd/Pelvis/OB…) + Findings / Impression / Recommendations / Notes |
| **Draft → Approve 🔒** | Save Draft (dib ayaa loo furan karaa) → Approve: report-ku wuu xirmaa (timestamp), reception ogeysiis, dhakhtarkii gudbiyay SMS + portal-kiisa, bukaanka SMS |
| **Repeat Scan ↺** | Radiologist-ku sawir xun wuu dib u codsan karaa (sabab) → status Requested + shaqaalaha ogeysiis |
| **Case Discussion 💬** | Technician ↔ Radiologist labada dhinac (staff: Radiology → 💬; radiologist: case page) |
| **Isolation & Security** | Session gooni ah; radiologist kastaa wuxuu arkaa kiisaskiisa oo keliya (403 kuwa kale — files-ka sidoo kale) |

## 21. Phase 15 — Accounting Extras (Reversal, Recurring, Petty Cash, Dashboard)

| Feature | Sharraxaad |
|---|---|
| **Journal Reversal ↺** | Journal Entries: dib-u-celin qalad — reversing entry (debit/credit rogan) si toos ah, labaduna "Reversed"/"Reversal" ayaa lagu calaamadeeyaa; laba-jibbaar iyo bil xiran waa la diidaa |
| **Recurring Journals** | Journal → Recurring: template bille ah (kiro, accruals) — Dr/Cr accounts + amount + maalin; "Run" ayaa bishii hal mar qoraya (labo-post ma dhacdo) |
| **Petty Cash / Bank Transfer** | Journal → Cash Transfer: wareejin hagaagsan Cash ↔ Bank ↔ Petty Cash (1104 auto) — double-entry si toos ah |
| **Revenue & Expense Analysis** | Accounting → Revenue Analysis: dakhli waax/adeeg kasta + kharash qayb kasta + % bishii, KPIs Revenue/Expenses/Net |
| **Financial Dashboard 📊** | Accounting → Financial Dashboard: Revenue (maanta/bishii), Expenses, Net Profit, Cash & Bank balance, AR/AP, Budget — hal shaashad oo maamul |

## 22. Phase 16 — Doctor Request → Registration → Invoice → Payment Gate

| Feature | Sharraxaad |
|---|---|
| **Create Invoice from Doctor Request** | Referral → badhanka **+ Invoice**: adeegyada codsiga (lab + rad) si toos ah ayaa loo geliyaa invoice, qiimaha catalog-ga la isticmaalo — reception dib uma qorayso |
| **Payment Gate 🔒** | Codsi dhakhtar ka yimid → lab/rad orders waa **gated** (qarsoon) ilaa invoice-ku la bixiyo. Lab & Radiology waxay arkaan KELIYA kuwa la bixiyay; kuwa aan la bixin banner "waiting for payment" ("Show them" ayaa ka muujinaya) |
| **Auto Gate Release** | Invoice buuxa marka la bixiyo → orders-ka si toos ah ayaa loo furaa oo lab/radiology-ga ka soo muuqda |
| **Traceability** | Invoice ↔ Referral ↔ Lab/Rad orders ↔ Payment ee dhammaystiran: invoice item kastaa wuxuu xiran yahay order-kii uu ka yimid; invoice screen wuxuu muujiyaa "Doctor Request REF-xxxx · Dr · Priority" |
| **Doctor Requests Board** | Doctor Requests menu: buckets (New / Waiting Registration / Waiting Invoice / Waiting Payment / Paid / Under Laboratory / Under Radiology / Completed / Cancelled) + raadin (req#, patient, doctor, date) + badhan Invoice saf kasta |
| **Backward compatible** | Diiwaannadii hore (paid_gate NULL) waa la arki karaa oo lama xannibo — kaliya kuwa cusub ee referral-ka portal-ka ka yimaada ayaa la gate-gareeyaa |

Workflow buuxa: Doctor Request (portal) → Patient auto-registered → reception invoice hal-guji → Payment → gate furmo → Lab/Radiology → Report → dhakhtar/bukaan. Xog mar la geliyo lama celceliyo, biilna dhakhtarku ma arko.

## 23. Phase 17 — Modern Dashboard Redesign (Odoo-style)

| Feature | Sharraxaad |
|---|---|
| **Live Widget Cards** | 10 kaadh oo midab-koodhaysan: Today's Patients, Waiting, Lab/Radiology Requests, Completed/Pending Reports, Revenue Today, Cash Collected, Outstanding, Stock Alerts — mid kastaa wuu gujin karaa |
| **Quick Actions** | Hal saf oo degdeg ah (Register Patient, Doctor Requests, Create Invoice, Receive Payment, Lab, Radiology, Queue, Financial Dashboard) — role-aware |
| **Category Cards** | Modules-ka waxaa loo kala saaray 8 qaybood oo Odoo-style ah (Patient Management, Laboratory, Radiology, Billing & Finance, Inventory & Pharmacy, HR, Quality, Administration) — icon + links, role-filtered |
| **Widgets (11)** | + Pending Reports card |
| **Charts (5)** | Revenue by Month, Top Requested Tests, Daily Patients (7-day), Laboratory Workload, Radiology Workload |
| **Color Coding** | Blue=New, Amber=Pending, Green=Completed, Red=Urgent, Grey=Cancelled |
| **Light + Dark + Responsive** | Labada mode; 5→3→2→1 column grid marka shaashadu yaraato (mobile/tablet) |
| **Backward compatible** | Wax module ah l- kama saarin; nav-gii hore, search-gii, notifications-kii dhammaan way sii shaqeeyaan |

## 24. Phase 18 — Odoo-style Doctor Request Detail Page

| Feature | Sharraxaad |
|---|---|
| **Status Chevron Progress Bar** | Draft → Submitted → Invoiced → Paid → Sample Collected → Processing → Completed (Odoo-style chevrons; done=cagaar, active=petrol, Cancelled=casaan) |
| **Smart Buttons (Linked Records)** | Kaadhadh xiran: Invoice (INV-xxxx + status), Paid-of-Total, Patient Hub (MRN), Lab Results (done/total), Radiology — hal-guji ayaa loo gudbaa diiwaanka xiran |
| **Requested Services Table** | Adeeg kasta qiimihiisa + status + calaamad "unpaid" haddii aan la bixin |
| **Timeline / Audit View** | Dhacdo kasta oo taariikhaysan: request created, registered, invoice, payment, sample collected, lab approved, radiology reported — cidda sameysay + audit log |
| **Detail from Board** | Doctor Requests board → badhan "Open" oo furaya detail page-ka buuxa |
| **Full traceability** | Hal shaashad: request → invoice → payment → orders → reports, dhammaan xiran oo la socon karo |

## 25. Phase 19 — Billing & Accounting Separated

| Change | Sharraxaad |
|---|---|
| **Two distinct nav sections** | "Billing · Biil" (reception/cashier) iyo "Accounting · Xisaab" (accountant) hadda waa laba qaybood oo kala go'an sidebar-ka, halkii ay ku wada jireen "Management" |
| **Billing subnav** | Invoices · Receive Payment · Credit Notes · Daily Cash Closing · Doctor Commission · Service Catalog — hawlaha maalinlaha ah ee lacag-qaadista |
| **Accounting subnav** | Dashboard · Financial Dashboard · Chart of Accounts · Journal Entries · Recurring Journals · General Ledger · Expenses · Cash Flow · AR/AP Aging · Banks · Reconciliation · Budgets · Cost Centers · Ratios · Revenue Analysis · Tax · Fiscal Periods · Currencies · Financial Statements |
| **No overlap** | Accounting-ga laga saaray "Sales Invoices" oo billing la mid ahaa; Financial Dashboard + Recurring + Revenue Analysis lagu daray meeshii saxda ahayd |
| **Permissions preserved** | Billing = reception/cashier/accountant; Accounting = accountant/super_admin oo keliya (sidii hore) |
| **Backward compatible** | Wax module ah lama saarin; dhammaan 62-ka test way sii shaqeeyaan; v1 database ✓ |

## 26. Phase 20 — Billing ↔ Accounting Linked (Bidirectional)

Billing iyo accounting way kala go'an yihiin (Phase 19) laakiin hadda waa **isku xiran** — navigation labo-dhinac ah:

| Direction | Sharraxaad |
|---|---|
| **Billing → Accounting** | Invoice screen kasta wuxuu leeyahay panel "Accounting" oo muujinaya journal entries-ka uu si toos ah ugu qoray (INV-/PAY-/CN-xxxx) — account code + name + debit/credit; ref kastaa wuxuu link u yahay journal entry detail-ka |
| **Accounting → Billing** | Journal entry detail (cusub, `/journal/<id>`) wuxuu muujiyaa lines-ka oo dhan + smart button "Source Invoice" oo dib ugu celinaya invoice-ka; journal list-kana ref kastaa wuxuu link yahay, INV-/PAY- refs-na waxay leeyihiin badhan 🧾 Invoice |
| **Double-entry** | Invoice/payment kastaa horey ayuu si toos ah ugu qori jiray General Ledger-ka (repost_invoice/repost_payment); hadda xiriirku waa **muuqda oo la gujin karo** labada dhinacba |
| **Reversal links** | Journal entry-ga la rogay wuxuu ku xiran yahay reversing entry-giisa (labada dhinac) |

Natiijo: hal-guji ayaad uga gudbi kartaa invoice → journal entry → dib invoice, oo aad la socon kartaa sida biil kastaa xisaabaadka uu u galo (audit trail buuxa).

## 27. Phase 21 — Daily Transactions Module (+ CSV export)

Global Search iyo Daily Cash Closing horey ayay u jireen (waaweyn). Waxaa lagu daray **Daily Transactions** oo dhammaystiran:

| Feature | Sharraxaad |
|---|---|
| **Daily Transactions** | Billing → Daily Transactions: dhaqdhaqaaq kasta oo maalinta la sameeyay (receipt kasta) — MRN, patient, invoice, receipt no., amount, method, cashier, ref |
| **Income by Payment Method** | Wadar habka kasta: Cash / Mobile Money / Bank / Card / Insurance / Credit — kaadhadh la gujin karo |
| **Day summary** | Patients, Gross Collected, Discounts, Net Revenue KPIs + xiriir Cash Closing |
| **Date picker + filter** | Maalin kasta dib loo eegi karo; filter habka-bixinta |
| **Exports** | Print (professional report + QR), **CSV export** (Excel-compatible) — audit-logged |
| **Cash Closing link** | Toos ugu gudubka maalinta xiritaanka |

Nidaamku hore u lahaa: Global Search (patients/invoices/lab/rad/doctors/employees/suppliers), Daily Cash Closing (opening float, over/short, lock+reopen), advanced list filters. Kani wuxuu dhammaystiray Daily Transactions-ka.

## 28. Phase 22 — Advanced List Filters (search + date + status on every list)

Prompt-kii Daily Transactions wuxuu codsaday "Advanced Filters on every list page" — kan ayaa dhammaystiray:

| Filter | Sharraxaad |
|---|---|
| **Text Search** | Sanduuq raadin oo generic ah oo ka shaqeeya list kasta oo la diiwaangeliyay — patients (name/phone/MRN/ID), doctors, radiologists, suppliers, employees, SOPs, incidents |
| **Date Period** | Dropdown: Today / Yesterday / This Week / This Month / This Year + custom range (From–To) — modules-ka taariikhda leh (sida incidents) |
| **Dropdown Filters** | Patients: Gender + Blood Group; wax kastaa waa la kordhin karaa iyada oo la isticmaalayo `filters=[...]` register() dhexdeeda |
| **Combine + Reset + Count** | Filter dhowr ah way isku dari karaan, badhan Reset, iyo tirada natiijada ("N result(s)") |
| **Reusable** | Filter-ku wuxuu ka dhaqmaa `register(..., search=[...], filters=[...], date_field='...')` — mustaqbalka module cusub si fudud ayaa loogu dari karaa |

Ka hor, filter-ku wuxuu ku jiray kaliya bogag gaar ah (patients search, reqboard, dailytx). Hadda waa **generic** oo list kasta wuu ka shaqeeyaa.

## 29. Phase 23 — Universal Error Handling + Error Log

Global Search, Advanced Filters (v4.2), Audit Trail, Duplicate detection, Notifications — dhammaan horey ayay u jireen. Kani wuxuu ku daray **error handling oo dhammaystiran**:

| Feature | Sharraxaad |
|---|---|
| **Friendly Errors** | Khalad kasta (500) → bog nadiif ah oo leh fariin macquul ah + badhan "Back to Dashboard". User weligiis MA arko Python/SQL/traceback |
| **Safe Rollback** | Khalad kasta ka hor → `db.session.rollback()` — xogtu ma kharribmi karto (integrity preserved) |
| **Error Log (Admin only)** | Admin → Error Log: khalad kastaa waa la diiwaangeliyaa — ERR-xxxx, waqti, user, screen (path+method), error type, IP, browser, technical traceback |
| **Detail + Resolve** | Admin wuxuu arki karaa faahfaahin buuxda + "Mark resolved"; Open/All tabs |
| **Admin Notification** | Khalad markuu dhaco → IT admin ogeysiis toos ah |
| **Existing preserved** | 404/403/Fiscal-period handlers, audit log, duplicate-patient detection, IP allowlist, password policy — dhammaan way sii shaqeeyaan |

Tan ka hor, 500 wuxuu tusi jiray fariin guud oo aan la diiwaangelin. Hadda waa la qabtaa, la rogaa, la diiwaangeliyaa, oo admin waa la ogeysiiyaa.

## 30. Phase 24 — App Launcher (Hal meel wax kastaa laga helo)

Nidaamku waa awood badan laakiin complex — App Launcher wuxuu ka dhigayaa mid fudud: **hal badhan → wax kastaa**.

| Feature | Sharraxaad |
|---|---|
| **Grid button (⊞)** | Top bar-ka badhan cusub; guji → overlay leh dhammaan modules-ka |
| **Type-to-find** | Sanduuq raadin: qor "lab", "invoice", "patient"… → si degdeg ah ayaa loo sifeeyaa; hal-guji ayaad u tagtaa |
| **Grouped tiles** | Dhammaan modules-ka oo icon leh, loo kala saaray qaybaha (Overview, Clinical, Quality, Billing, Accounting, Management, Admin) + Quick Actions kor |
| **Ctrl / Cmd + K** | Keyboard shortcut si degdeg ah loo furo meel kasta; Esc si loo xiro |
| **Role-aware** | User kastaa wuxuu arkaa kaliya waxa uu heli karo (permissions la ilaaliyay) |
| **Light + Dark + Mobile** | Labada mode; 4→3 column marka mobile |

Sidebar-kii hore, subnav-kii, iyo global search-kii dhammaan way sii jiraan — App Launcher-ku waa dariiq dheeraad ah oo fudud, ma aha bedelka. User cusub uma baahna inuu barto qaab-dhismeedka nav-ka: Ctrl+K, qor, guji.

## 30. Phase 24 — Unified App Launcher (Dhammaan Qaybaha hal meel)

Nidaamku wuu ballaaran yahay; si loo fududeeyo, waxaa lagu daray **hal bog oo dhammaan qaybaha laga helo**:

| Feature | Sharraxaad |
|---|---|
| **All Modules page** | `/apps` (nav-ka sare "All Modules"): dhammaan 60+ qaybood hal shaashad, oo loo kala saaray 11 koox (Patient / Lab / Radiology / Billing / Accounting / Inventory / HR / Assets / Quality / Reports / Admin) |
| **Live Search** | Qor magaca (Af-Soomaali ama Ingiriis: "invoice", "bukaan", "raajo", "journal") → filter degdeg ah oo JS ah, kaararka aan ku habboonayn way qarsoomaan |
| **Bilingual labels** | Qayb kastaa magac Ingiriisi + Soomaali (tusaale: Patient Registration · Diiwaangelin bukaan) |
| **Role-filtered** | Shaqaale kastaa wuxuu arkaa oo keliya qaybaha uu awoodo — reception xisaabaadka ma arko |
| **One-click** | Kaadh kasta hal-guji ayuu kuu geeynayaa qaybta |

Sidaas, isticmaaluhu uma baahna inuu raadiyo qaybo badan oo sidebar-ka ku kala firirsan — hal meel (**All Modules**) ayuu wax kasta ka helaa oo ka raadiyaa. Nav-gii hore iyo dashboard-kii category cards weli way jiraan.

## 31. Phase 25 — Dynamic Service Configuration (no-code Service Management)

Configuration → **Service Management** (admin/manager oo keliya): adeeg cusub samee UI-ga, koodh la'aan.

| Section | Fields |
|---|---|
| **General** | Service Code (auto ama manual), Name, Short Name, Department (Lab/CT/MRI/X-Ray/Ultrasound/ECG/Echo/Endoscopy/Consultation/Procedure/Vaccination/Other), Category, Subcategory, Description, Active/Inactive |
| **Pricing** | Standard, Corporate, Insurance, Emergency, VIP, Home Service, Discount Allowed, Max Discount |
| **Commission** | 4 door: Referring Doctor / Radiologist / Lab Technician / Report Writer — Percent ama Fixed — si toos ah loo xisaabiyo lacag-bixinta kadib |
| **Workflow** | Laboratory / Radiology / Consultation / Procedure / Cashier Only — codsiga si toos ah loogu diro qaybta saxda ah |
| **Equipment / Template / Timing** | Equipment (CT/MRI/X-Ray/Ultrasound/Analyzer), Report Template, wakhtiga (collection/processing/reporting) |
| **Availability** | Available Branches |

**Auto-integration:** adeeg cusub markuu la keydiyo, isla markiiba wuxuu ka muuqdaa Doctor Requests, Billing/Invoice catalog, Radiology (CT/MRI/X-Ray/Ultrasound → si toos ah loo diro raajada via workflow), Lab, iyo Reports. **Edit:** qiimo/commission/workflow beddel — biilasha hore MA saameeyaan (line-price waa la qabtaa). **Search/Filter:** name/code/category/department/equipment/status. **Security:** admin/it_admin/branch_manager oo keliya ayaa config-ga arka; reception waa la diiday.

Backward compatible: Service model-kii hore + adeegyadii + qiimayaashii dhammaan waa la ilaaliyay; field cusub oo keliya ayaa lagu daray (no duplicate columns).

## 31. Phase 25 — Dynamic Service Configuration Module (verified)

Service Management (no-code service configuration) wuxuu ka jiraa nidaamka. Waxaa la xaqiijiyay in uu si buuxda u shaqeeyo:

| Feature | Sharraxaad |
|---|---|
| **Configuration → Service Management** | Nav + `/m/svcconfig`; admin/manager oo keliya (`svcconfig` perm: super_admin/it_admin/branch_manager) |
| **+ New Service (no code)** | Foom UI ah oo dhammaystiran — code auto/manual, name, short name, department (Lab/CT/MRI/X-Ray/Ultrasound/ECG/Echo/Endoscopy/Consultation/Procedure/Vaccination/Other), category, subcategory, description, active |
| **Pricing tiers** | Standard/Cash · Corporate · Insurance · Emergency · VIP · Home · Contract · Cost · Discount allowed + Max discount |
| **Commission (4 roles)** | Referring Doctor · Radiologist · Lab Technician · Report Writer — mid kastaa Fixed ama Percent; si toos ah loo xisaabiyo kadib bixinta (Invoice.service_fees) |
| **Workflow routing** | Laboratory/Radiology/Consultation/Procedure/Cashier Only — auto-routing department-ka; modality auto (CT/MRI/...) |
| **Equipment · Report template · Timing** | Qalabka, template-ka warbixinta, waqtiga (collection/processing/reporting) |
| **Availability + Barcode/QR** | Available branches; barcode + QR code auto-generated (`/svcconfig/<id>/barcode`, `/qr`) |
| **Auto-integration** | Adeeg cusub isla markiiba wuxuu ka muuqdaa Doctor Request, Billing, Invoice, Cashier, Lab/Radiology, Reports, Accounting, Revenue Dashboard |
| **Historical safety** | Qiimo/commission wax ka beddelku MA saameeyo biilasha/warbixinnada hore (InvoiceItem.price waa la kaydiyaa) — la xaqiijiyay |
| **Search & Filter** | Magaca, code, department, category, equipment, active status |

Backward compatible: 5-tii adeeg ee hore way sii jiraan; wax model ah lama kharribin. 69 test (test_service_configuration ku jira).

## 32. Phase 26 — Auto Commission & Radiologist Fee Payables

Commission accrual + accounting horey ayay u shaqaynayeen (posting.py accrue_commissions). Waxaa lagu daray **payment screens iyo dashboard** oo dhammaystiran:

| Feature | Sharraxaad |
|---|---|
| **Auto-accrual on payment** | Marka bukaanku bixiyo invoice buuxa → CommissionAccrual si toos ah loo abuuro: doctor commission + radiologist fee, status Unpaid (payable) |
| **Auto accounting (4 lines)** | COMM-xxxx: Dr Commission Expense (5130) → Payable (2300); Radiologist Fee (5140) → Payable (2310). Tusaale: $150 CT → doctor $30, rad $10, net $110 |
| **Payables screen** | Accounting → Commission Payables: tabs Doctor / Radiologist, KPI cards (Outstanding, Paid, Today, This month), Open/All |
| **Pay / Pay Selected / Pay All** | Bixin hal-mar ah, kuwa la doortay (checkbox), ama dhammaan — status → Paid, CommissionPayment diiwaan gashan |
| **Settlement accounting** | CMPAY-xxx: Debit Payable, Credit Cash (1000) — deynta la yareeyo |
| **Dashboard widgets** | "Doctor Commission Due" + "Radiologist Fees Due" (financial roles) oo toos ugu xidhan payables |
| **Historical safe** | Accrual la settle-gareeyay lama taabto haddii dib loo bixiyo invoice |

Payment gacanta lama sameeyo si toos ah — accountant ayaa gudbiya screen-ka gaarka ah (financial control + audit).

## 33. Phase 27 — Doctor Request Workflow + Branded Print Layout

| Change | Sharraxaad |
|---|---|
| **Hal menu oo Doctor Request ah** | Labadii menu (Doctor Request + Doctor Requests) waa la mideeyay; "Doctor Requests" (reqboard) waa laga saaray sidebar-ka (weli waa la geli karaa) |
| **Liiska hore (updated)** | Markuu user gujiyo "Doctor Request" → liiska (Incoming Referrals) ayaa furmaya; badhan "+ New Doctor Request" ayaa furaya foomka diiwaangelinta (`/referral/new`) |
| **Back to list** | Foomku wuxuu leeyahay badhan "← Back to Doctor Requests" |
| **Staff create → board** | Marka staff-ku abuuro codsi, wuxuu u gudbaa board-ka (public doctor form wuxuu sii hayaa thank-you page) |
| **Branded print (dhammaan)** | printable(): header (logo + magaca Ingiriisi + Carabi + address/phone/email/website), footer (contact + page meta), watermark, QR verify, barcode |
| **Print preview buttons** | Print/Save PDF · Email · WhatsApp · Cancel |
| **A4 professional** | Company brand color, Space Grotesk + Inter fonts, print-color-adjust, watermark "Modern Diagnostic Center" |
| **Settings-driven** | company_arabic / company_address / company_phone / company_email / company_web ka yimaadaan settings; dhammaan documents-ka isku layout (invoice, receipt, lab/radiology report, referral, quotation) |

Backward compatible: wax feature ah lama saarin; reqboard route + detail page way sii shaqeeyaan. 72 test.

## 34. Phase 28 — Accounting Home (Odoo-style KPIs) + Partner Ledger

Accounting-gu horey wuu u lahaa: COA, Journals, General Ledger, Trial Balance, P&L, Balance Sheet, Cash Flow, AR/AP Aging, Bank Recon, Budgets, Cost Centers, Ratios, Tax, Fiscal Periods, Petty Cash, Excel exports, Commission Payables, auto-posting. Waxaa lagu daray:

| Feature | Sharraxaad |
|---|---|
| **Accounting Home KPIs (10)** | Cash Balance · Bank Balance · Today's Income · Today's Expenses · Net Profit · Monthly Revenue · Outstanding Invoices · **Pending Dr Commission** (link payables) · **Pending Radiologist Fees** (link) · **Insurance Receivables** |
| **Partner Ledger (cusub)** | Accounting → Partner Ledger: statement per bukaan (customer) ama supplier (vendor) — invoice/payment kasta, debit/credit, running balance, wadar; INV- links; Print |
| **Customers / Vendors tabs** | Patients-ka biil leh + Suppliers-ka; dropdown si degdeg loo doorto |

Prompt-ka Accounting Module: qaybihiisa kale (auto-posting patient/lab/rad/pharmacy/commission, reports, configuration) horey ayay u jireen oo shaqeeyaan.

## 35. Phase 29 — Odoo-style Accounting Menubar (dropdown menus)

Sida Odoo Accounting-ka dhabta ah, shaashadaha accounting-ka oo dhan waxaa kor yaal **menubar madow oo dropdown leh**:

| Menu | Hoos-yaallada |
|---|---|
| **Dashboard** | Accounting home (KPIs + kaararka) |
| **Customers ▾** | Patient Invoices · Credit Notes · Customer Payments · Daily Transactions · Products & Services · Customer List |
| **Vendors ▾** | Vendor Bills · Vendor Refunds (Debit Notes) · Expenses · Vendor List |
| **Accounting ▾** | Journal Entries · Recurring · **Ledgers** (General/Partner) · **Management** (Budgets, Assets, Banks, Statements/Reconciliation, Cash Registers, Cost Centers) |
| **Reporting ▾** | Financial Dashboard · P&L/BS/TB · Cash Flow · AR/AP Aging · Revenue Analysis · **Commission** (Payables, Doctor, Radiologist) · **Analysis** (Budget vs Actual, Cost Centers, Ratios, Tax) |
| **Configuration ▾** | Chart of Accounts · Currencies · Fiscal Periods · Service & Commission Rules · Banks · Settings |

Hover → dropdown furma (sida Odoo); qayb kastaa role-filtered; mobile-ka waa scroll + full-width dropdown. Menubar-ku wuxuu ka muuqdaa 32 shaashadood oo accounting/billing ah oo keliya — bogagga kale (Patients, Lab...) subnav-kii caadiga ayay hayaan.

## 36. Phase 30 — System-wide Odoo-style Menubars

Habkii Odoo-style ee Accounting (v5.0) waxaa lagu dabaqay **system-ka oo dhan** — app area kastaa menubar dropdown leh:

| App | Menus |
|---|---|
| **Clinical** (patients/queue/consult/referrals/reqboard/doctors/donors/vaccinations) | Patients ▾ · Doctor Requests ▾ · Blood Bank ▾ · Vaccination |
| **Diagnostics** (lab/labqc/radiology/radiologists) | Laboratory ▾ · Radiology ▾ |
| **Inventory** (pharmacy/batches/inventory/warehouses/transfers/stockadj/stockvalue/consumption/purchases/suppliers) | Pharmacy ▾ · Inventory ▾ · Procurement ▾ |
| **HR** (employees/contracts/attendance/leave/payroll) | Employees ▾ · Time ▾ · Payroll |
| **Quality** (sops/incidents/audits/feedback) | Quality ▾ |
| **Assets** (maintdash/assets/maintenance/logistics) | Assets ▾ · Logistics |
| **Reports** (reports/summary/revenue/productivity/branchcmp) | Reports ▾ |
| **Admin** (users/branches/settings/backup/messages/audit/errorlog/loginhistory) | Users & Access ▾ · System ▾ · Logs ▾ |
| **Accounting** (32 screens — v5.0) | Dashboard · Customers ▾ · Vendors ▾ · Accounting ▾ · Reporting ▾ · Configuration ▾ |

Dhammaan: hover-dropdown, active=amber, role-filtered, mobile scroll. 75 test.

## 37. Phase 31 — Advanced Financial Reports: Date Filters, Comparison, Vendor Management

Prompt-ka "Advanced Financial Reports": statements-ka, COA-da, opening balances (Account.opening), invoice statuses, exports, iyo automation horey ayay u jireen. Waxaa lagu daray waxa maqnaa:

| Feature | Sharraxaad |
|---|---|
| **Date filters (statements)** | Financial Statements (P&L/Cash Book/Balance Sheet/Trial Balance) hadda waxay leeyihiin 10 preset: Today · Yesterday · This/Last Week · This/Last Month · This/Last Quarter · This/Last Year + **Custom Range** (From → To) |
| **Period comparison** | Bar muujinaya Current vs Previous period (isla dherer): Revenue/Expenses/Net + ▲▼ % isbeddel |
| **Payroll pro-rating** | P&L-ka payroll-ku wuxuu u dhigmaa dhererka xilliga (maalmo/365) |
| **Tabs keep period** | Marka statements loo kala gudbo, xilliga la doortay wuu raacaa |
| **Vendor Management (extended)** | Supplier: Category (13 nooc: Electricity/Water/Internet/Fuel/Medical Supplier...) · Contact Person · Email · Tax Number · Bank Details + search + category filter |
| **Vendor Expenses (enriched)** | Expense: **Vendor** (supplier link) · 23 categories (Electricity, Water, Fuel, Diesel, Generator, Internet, Telephone, Rent, Cleaning, Stationery, Medical Supplies, Security, Marketing, Training...) · **Payment Method** (Cash/Bank/Mobile Money/Cheque/Credit) · date filter · category filter; liisku wuxuu tusaa Vendor + Method |
| **Migrations** | supplier (contact_person/email/tax_no/bank_details/category), expense (supplier_id/pay_method) — v1 DB si nabad ah ayay u socdaan |

76 test.

## 37. Phase 31 — Advanced Financial Reports: Date Filters, Comparison, Vendor Management

Bayaannada maaliyadeed (P&L, Balance Sheet, Trial Balance, Cash Book, GL, Partner Ledger, Cash Flow, AR/AP, Budgets, Assets/Depreciation, Tax, exports Excel) horey ayay u jireen. Waxaa lagu daray:

| Feature | Sharraxaad |
|---|---|
| **Date filters (Odoo-style)** | Financial Statements: Today · Yesterday · This/Last Week · This/Last Month · This/Last Quarter · This/Last Year · **Custom range** (From → To). Preset select + date inputs; tabs-ka (P&L/Cash/BS/TB) period-ka way sitaan |
| **Period comparison** | Bar muujinaya Revenue/Expenses/Net ee xilliga + **▲▼% vs previous period** (isla dhererka xilli hore) |
| **Payroll pro-rated** | P&L-ka xilliyada gaagaaban payroll-ka waa loo qaybiyaa maalmaha (annual × days/365) |
| **Vendor Management (extended)** | Supplier: Category (13 nooc: Electricity/Water/Internet/Fuel/Medical Supplier/...) · Contact Person · Email · Tax Number · Bank Details; search + category filter |
| **Vendor Expenses** | Expense: **Vendor** (supplier link) · 23 categories (Electricity, Water, Fuel, Diesel, Generator, Internet, Telephone, Rent, Cleaning, Medical Supplies, Security, Marketing, Training...) · **Payment Method** (Cash/Bank/Mobile Money/Cheque/Credit) · date filter · category filter; liiska wuxuu tusaa Vendor + Method |
| **Migrations** | supplier: contact_person/email/tax_no/bank_details/category; expense: supplier_id/pay_method — v1 DB si nabdoon ayay u socdaan |

Chart of Accounts (buuxa oo opening balance leh), invoice statuses (Draft/Posted/Partial/Paid/Cancelled), exports, automation — horey ayay u jireen. 76 test.

## 37. Phase 31 — Advanced Financial Reports: Date Filters, Comparison, Vendor Management

Bayaannadii maaliyadeed (P&L, Balance Sheet, Trial Balance, Cash Book, GL, Partner Ledger, AR/AP, Budgets, Tax, Exports) horey ayay u jireen. Waxaa lagu daray:

| Feature | Sharraxaad |
|---|---|
| **Date presets (10)** | Financial Statements: Today · Yesterday · This/Last Week · This/Last Month · This/Last Quarter · This/Last Year — dropdown |
| **Custom range** | From → To (date pickers); tabs-ku (P&L/Cash/BS/TB) period-ka way sitaan |
| **Period comparison** | Bar sare: Revenue / Expenses / Net + ▲▼% vs previous period (isla dherer) + prev period figures |
| **Payroll pro-rating** | P&L-ka period-gaaban: mushaharka waa la saami-qaybshaa (days/365) |
| **Vendor Management** | Supplier: Contact Person · Email · Tax Number · Bank Details · Category (13 nooc: Electricity/Water/Internet/Fuel/Medical Supplier/...) + search + category filter |
| **Vendor Expenses** | Expense: **Vendor** (supplier link) · 23 categories (Electricity, Water, Fuel, Diesel, Generator, Internet, Telephone, Rent...) · **Payment Method** (Cash/Bank/Mobile Money/Cheque/Credit) · liiska wuxuu tusaa Vendor+Method |
| **Migrations** | supplier: contact_person/email/tax_no/bank_details/category; expense: supplier_id/pay_method — v1 DB si nabdoon ayay u socdaan |

76 test. Qaybaha kale ee prompt-ka (COA buuxa oo opening balance leh, invoice statuses, exports, dashboard, automation) horey ayay u jireen.

## 38. Phase 32 — Simple Service Management (Settings → Service Management)

Nooc fudud oo Service Management ah (svcconfig-ga ballaarani wuu sii jiraa — "Advanced" button ayaa loo gudbaa):

| Feature | Sharraxaad |
|---|---|
| **Menu** | Sidebar "Service Management" + Admin menubar System ▾ + Accounting Configuration ▾ — dhammaantood waxay furaan foomka fudud (`/m/svcmgmt`). Foomkii ballaarnaa (svcconfig: pricing tiers/commission/workflow/barcode) waa off-menu, route-kiisu wuu shaqeeyaa (backward compat) |
| **Liiska** | Code, Name, Department, Category, Sale/Cost Price, Status + search; buttons: Edit · Activate/Deactivate · Delete |
| **Foom fudud (7 fields)** | 🆔 Code (auto: horqodka department + tirsi, tusaale MRI→M0006) · 🏥 Name · 📂 Department (12 doorasho) · 📑 Category · 💰 Sale Price · 💵 Cost Price · 📋 Status |
| **Buttons** | Save · **Save & New** (foom madhan ayaa dib kuugu furma) · Cancel |
| **Auto-integration** | Marka la kaydiyo isla markiiba wuxuu ka muuqdaa Doctor Request, Billing/Invoice, Lab/Radiology options, Reports, Search (opt_services active-only) |
| **Safe delete** | Adeeg biil ku jira lama tirtiri karo (deactivate ayaa lagu taliyaa); kan aan la isticmaalin waa la tirtiri karaa |
| **Deactivate** | Isla markiiba wuu ka baxaa options-ka billing/doctor request; Activate ayaa soo celisa |

77 test.

## 39. Phase 33 — Add New Radiologist + Assignment Dropdowns

| Feature | Sharraxaad |
|---|---|
| **+ New Radiologist** | Badhan cusub oo ku yaal Radiology header-ka → `/m/radiologists/new` (foom: Name, Specialty, Phone, Active, Portal user/password) |
| **Report form dropdown** | "Radiologist / Report reader" hadda waa **dropdown** radiologists-ka firfircoon (ma aha qoraal xor ah) — qofka hore loo qoray weli wuu muuqdaa |
| **Dispatch dropdown** | Radiologist cusub isla markiiba wuxuu ka muuqdaa dispatch-ka (teleradiology) |
| **Fee flow** | Radiologist-ka la doorto → RadOrder.radiologist → CommissionAccrual payee (radiologist fee payables) |

78 test.

## 40. Phase 34 — Odoo-style Billing Workflow (Waiting for Billing)

Habka Odoo 18: cashier-ku wax ma qoro — hal-guji ayuu invoice ku abuuraa:

| Feature | Sharraxaad |
|---|---|
| **Waiting for Billing panel** | Billing & Cashier bogga korkiisa: referrals-ka aan weli biil lahayn — Referral#, Patient, MRN, Doctor, Services, Date, Status pill (Blue=New, Amber=Waiting), Actions |
| **One-click Create Invoice** | Badhan "Create Invoice" → invoice si toos ah ayaa loo abuuraa; adeegyadu si toos ah ayay u soo galaan (lab/rad orders; haddii aanay jirin, tests-ka referral-ka ayaa lagu beegaa catalog-ka) — cashier-ku dib uma qoro |
| **Register First** | Referral aan bukaan lahayn → badhan "Register First" (accept + patient auto) |
| **Referral column** | Liiska invoices-ka: tiirka Referral (REF-xxxx) — isku xirka dhammaystiran |
| **Sticky action bar** | Invoice screen: bar sare oo sticky ah (INV#, status badge, Balance, Register Payment, Print, +New, Back) — scroll-ka wuu la socdaa |
| **Keyboard shortcuts** | Ctrl+N = New Invoice · Ctrl+P = Print · Ctrl+Enter = Register Payment focus |

Workflow: Doctor Request → (Register) → Waiting for Billing → Create Invoice (auto lines) → Review → Pay → Accounting auto. 79 test.

## 41. Phase 35 — Per-Radiologist Fee Rules (sida Doctor Commission)

Radiologist kastaa hadda wuxuu yeelan karaa qaanuun khidmad oo u gaar ah — isla fikradda Doctor Commission:

| Feature | Sharraxaad |
|---|---|
| **Fee Rule (foomka radiologist)** | Service default · **Fixed $ per study** · **Percent % of radiology amount** + Fee Value; liiska radiologists-ku tiirka "Fee" ayuu tusaa |
| **Awoodda kala sarreynta** | Per-radiologist rule > per-service config (comm_radiologist) > wax la'aan. Tusaale ($150 CT, service default $10): Dr Pct 15% → **$22.50**; Dr Fix $18/study → **$18**; radiologist aan rule lahayn → **$10** |
| **Auto-accrual** | Marka biilka la bixiyo → CommissionAccrual (payee = radiologist-ka) + accounting (5140/2310) — sida doctor commission |
| **Bugfix** | Invoice aan referring doctor lahayn hore accrual-ku si aamusan ayuu u fashilmi jiray (AttributeError swallowed) — radiologist fee-gu ma dhalan jirin. Waa la saxay: hadda dhammaan invoices-ka way accrue-gareeyaan |

80 test.

## 42. Phase 36 — Automatic Invoice (Add Item la saaray)

| Change | Sharraxaad |
|---|---|
| **Invoice automatic (referral)** | Invoice ka yimid Doctor Request: foomka "Add Item" gebi ahaan waa laga saaray — waxaa lagu beddelay ogeysiis "⚡ Automatic invoice — adeegyadu waxay ka yimaadeen REF-xxxx" |
| **Walk-in (gacanta)** | Invoice aan referral lahayn: foomku wuu qarsoon yahay `<details>` gudihiisa ("＋ Add line manually — walk-in only") — waa la furi karaa haddii loo baahdo |
| **Backward compat** | Route-ka act=additem wuu shaqeeyaa (tests-ka hore + walk-ins) |

81 test.

## 43. Phase 37 — Payment Schedules, Partial Pay, History & Voucher

Commission Payables (v4.6) waxaa lagu daray qaybihii ka maqnaa prompt-ka:

| Feature | Sharraxaad |
|---|---|
| **Partial Payment** | Foomka "Partial Payment: Amount $" → lacagta waxaa loo qaybiyaa accruals-ka ugu da'da weyn marka hore; status → **Partial** (Partially Paid) ilaa dhammaystir |
| **Pay Monthly** | Month picker + "Pay Month" → dhammaan accruals-ka bishaas (default schedule-ka radiologist) hal mar ayaa la bixiyaa. Daily/Weekly/Custom: isla habka (Pay All today / Pay Selected / month) |
| **Payment History tab** | Tab saddexaad: Date, Payee, Amount, Method, Paid by + **Monthly Payment Summary** (bishii wadarta la bixiyay) |
| **Print Voucher** | Payment kastaa voucher printable ah (CMV-xxxxx): branded header, jadwal, Received/Approved by signature lines, barcode |
| **Audit** | Settlement kastaa log + CMPAY journal (Debit Payable / Credit Cash) — sidii hore |

82 test.

## 44. Phase 38 — Radiologist Management Module (sida Referring Doctors)

| Feature | Sharraxaad |
|---|---|
| **Referral Management menu** | Clinical menubar: **Referral Management ▾ → Referring Doctors · Radiologists** |
| **Diiwaangelin buuxa** | + New Radiologist: RAD-ID auto · Full Name · Gender · DOB · Phone · Email · National ID/Passport · Medical License · Specialization · Qualification · Hospital/Company · City · Address · **Reporting Fee (default $10)** · **Payment Schedule** (Daily/Weekly/Monthly/Custom, default Monthly) · Status · Portal user/password |
| **Liiska tirakoob leh** | RAD-ID · Name+Hospital · Specialty · Fee · Schedule · **Reports** (tirada la dhammeeyay) · **Outstanding** · **Paid** · Phone · Status + Edit/Delete |
| **By Radiologist summary** | Payables (Radiologist tab): jadwal kooban — Radiologist · Reports · Amount Due · Paid · Outstanding · Status (Pending/Partial/Paid) |
| **Isku-dhafan** | Assignment dropdowns (report/dispatch), portal /rrad, $10 auto-accrual, Pay/PayMonthly/Voucher, accounting — dhammaan horey u jiray oo la xiriira |

83 test.

## 45. Phase 39 — Commission After Discount + Auto Amount + Radiologist Fee Row

| Feature | Sharraxaad |
|---|---|
| **Commission after discount** | Doctor commission (percent) hadda waxaa lagu xisaabiyaa qiimaha **discount ka dib**: $150 CT − $50 discount → 20% × $100 = **$20** (ma aha $30). Helper cusub `commission_preview()` — shaashadda iyo accrual-ku isku tiro |
| **Radiologist Fee row (Totals)** | Totals card-ka waxaa lagu daray saf "Radiologist Fee" (magaca radiologist-ka + qiimaha) — barbar Doctor Commission. Fixed fee ($10/study) discount ma saameeyo; Percent rule waa la saamiyaa |
| **Amount Paid auto-fill** | Payment card: Amount Paid si toos ah ayaa loogu buuxiyaa **lacagta buuxda ee la rabo** (total ka dib discount). Update discount → auto amount-kuna wuu cusboonaadaa ($150 → $100). Qayb-bixin: cashier-ku wuu wax ka beddeli karaa |

Tijaabo: $150, discount $50 → screen "after discount" $20, amount auto $100, accruals doctor $20 + rad $10. 84 test.

## 46. Phase 40 — Automatic Invoice Lines (walk-in-na automatic)

| Feature | Sharraxaad |
|---|---|
| **Auto-pull orders** | Invoice kasta (referral iyo walk-in labadaba): marka la abuuro AMA la furo, adeegyada bukaanka ee aan weli la biilin (Lab orders + Radiology orders) **si toos ah** ayay u soo galaan — cashier-ku waxba ma qoro |
| **Idempotent** | Order kastaa invoice-ka ayuu ku xirmaa (invoice_id) — furitaan kasta laba jeer laguma daro |
| **Late orders** | Order cusub oo yimaada ka dib markii invoice-ka la abuuray → furitaanka xiga si toos ah ayuu u soo galaa |
| **Flash** | "⚡ N pending order(s) auto-added from Lab/Radiology" |

Tijaabo: bukaan leh 1 lab + 1 rad order → invoice cusub = 2 lines auto; order saddexaad yimid → furitaanka = 3 lines. 85 test.

## 47. Phase 41 — Commission Fallbacks + Pay Center (Deynaha oo hal meel)

| Feature | Sharraxaad |
|---|---|
| **Commission fallback** | Haddii adeeggu aanu lahayn commission config: doctor-level rate (Doctor.commission_type/percent_rate — 20 ama 0.20 labadaba waa la aqbalaa) ayaa la isticmaalaa → discount ka dib. Tusaale: $130 CT, doctor 20% → **$26** (mar hore $0 ayuu ahaa) |
| **Radiologist fallback** | Haddii aanu jirin service config ama per-radiologist rule: global Settings `rad_fee` (default **$10**) per report |
| **Pay Center (cusub)** | Accounting → 💳 Pay Center: hal meel oo dhammaan deynaha lagu arko — Doctor Commission · Radiologist Fees · **Vendor Expenses (Utilities/Electricity/Water/Internet...)** · Purchases + **TOTAL DEBTS** |
| **Pay buttons** | Pay All Doctor Commission · Pay All Radiologist Fees · Pay (expense kasta) · Pay (purchase kasta) — mid kastaa accounting si toos ah ayuu u galaa (EXP/PUR/CMPAY journals) |

Tijaabo: doctor $26 + rad $10 shaashadda ka muuqda; Pay Center bixiyay biil koronto $200 + commission. 86 test.

## 48. Phase 42-43 — Quality Hardening (test isolation, auto-backup, XSS)

Dib-u-eegis daacad ah kadib, saddex dhaliil oo dhab ah oo la hagaajiyay (system core-ku isma beddelin):

| Fix | Sharraxaad |
|---|---|
| **Test isolation** | Testyadu hore hal database ayay wadaageen (module-scope) → bug qarsoon (data leak). Hadda: DB template hal mar la seed-gareeyo, test **kastaa** nuqul nadiif ah ayuu helaa (function-scope + tmp copy). 6 test oo dhab ahaan bug qariyay ayaa la saxay (fresh-patient helper) |
| **Auto-backup** | `core/autobackup.py`: background thread oo maalinle ah + on-startup snapshot JSON ah → `instance/backups/`, retention (default 14). Settings: "💾 Run Auto-Backup Now" + liiska backups-ka. Manual download-kii wuu sii jiraa |
| **XSS fix** | Referral `doctor_name` (public `/refer` field) billing waiting-panel-ka `h()` la'aan ayuu u soo bixi jiray → XSS dhab ah. La escape-gareeyay + regression test (`<script>` payload lama render-gareeyo) |

88 test (function-isolated). Waxa weli hadhay (mustaqbal): money Float→cents, billing.py kala-qaybin, Jinja templates — kuwaas waa dib-u-qorid weyn oo "do not rewrite" ka hor imanaya.

## 49. Phase 44-46 — Reconciliation, Validation, Idempotency

Dhaliilihii aan xigay ee "production-readiness" oo la hagaajiyay:

| Fix | Sharraxaad |
|---|---|
| **Integrity / Reconciliation Health Check** | Accounting → Reporting → 🩺 Health Check (`/m/integrity`): 5 hubin — (1) journal kastaa isku dheeli tiran (debit=credit), (2) invoice total = lines − discount + VAT, (3) invoice aan la over-pay-garayn, (4) commission accrual aan la over-pay-garayn, (5) invoice la bixiyay journal buu leeyahay. Hero panel cagaar/jaalle/casaan + jadwal ✓/⚠/✗. Bug lacag hor joogsad |
| **Input validation** | Invoice: qty negative/garbage → diidmo (flash "greater than zero"); qty madhan → default 1; price negative → 0; payment negative → diidmo. Crash-ka `float()` la xakameeyay |
| **Payment idempotency** | Double/triple-submit "Record Payment" → ma abuuro accrual ama journal labanlaab ah (accrue idempotent: kuwii hore la tirtiraa, unless la bixiyay). Tijaabo: 3x bixin → accruals=2, journals=1, paid=150 (ma aha 450) |

91 test. Waxa weli hadhay (dib-u-qorid weyn, session gaar u baahan): money Float→cents, billing.py kala-qaybin, Jinja templates.

## 50. Phase 47-49 — Full Restore, Financial Audit Trail, Soft-Delete

Dhaliilihii hadhay ee "operational" oo la hagaajiyay (system core weli isma beddelin):

| Fix | Sharraxaad |
|---|---|
| **Full database restore** | Restore-kii hore wuu tirtiri jiray oo dib uma soo celin jirin (halis!). Hadda: transactional restore dhab ah — model kastaa dib buu u soo rogaa (children→parents order), datetime-ka si sax ah loo beddelaa, pre-restore snapshot la sameeyaa, cilad → rollback buuxa (data ma luntid). Wuu aqbalaa labada format (download + auto-backup wrapped). super_admin oo keliya |
| **Financial audit trail** | Audit Log: tab "💰 Financial Only" — payment/discount/refund/cancel/restore oo keliya. Payment-ku hadda wuxuu qoraa **before→after** ($10 → $150). Cancel-na wuu qoraa (was paid X). Hospital audit-ka ayuu u shaqeeyaa |
| **Soft-delete (archive)** | Wax leh `active` flag (Doctor, Patient, Service, Radiologist...) la "tirtiro" → **archived** (active=False), row-gu waa la hayaa audit/history awgeed. Kuwa aan `active` lahayn → hard-delete sida hore. Restore = Active dib u dhig |

94 test. Waxa weli hadhay (session gaar u baahan): money Float→cents (kan ugu weyn), server-side PDF/email, SMS gateway dhab ah, billing.py kala-qaybin, Jinja templates.

## 51. Phase 50-52 — Money Rounding, Server-side PDF, CSV Exports

| Fix | Sharraxaad |
|---|---|
| **Money rounding discipline** | `money_round()` helper (Decimal, half-up → cents). Lagu dabaqay: Invoice subtotal/total/balance, CommissionAccrual/Advance balance, commission_preview (doctor+rad), payables settlement math. Khatartii float-drift (0.1+0.2≠0.3) waa la baabbi'iyay iyada oo aan schema la beddelin (backward-compatible — legacy drifted floats way bogsadaan marka la akhriyo). Tijaabo: 3×19.99=59.97 sax, balance saafi 0 |
| **Server-side PDF** | `core/pdfgen.py` (reportlab): invoice PDF dhab ah oo la download-gareeyo (`/invoice/<id>/pdf`, badhan 📄 PDF). Ma aha browser-print — waa `%PDF` dhab ah. Fallback nabdoon haddii reportlab maqan yahay |
| **CSV exports** | `/export/csv/<what>`: Trial Balance · General Ledger · AR Aging · All Invoices. Barbar Excel-kii hore (accountants CSV bay doorbidaan). Finance exports panel-ka |

97 test. Money→cents oo schema ah (full integer-cents migration) weli waa dib-u-qorid weyn; laakiin khatartii dhabta ah (drift) hadda waa la xakameeyay.

Waxa hadhay oo dhab ah: money→cents schema (dib-u-qorid), billing.py kala-qaybin, Jinja templates, production infra (Postgres/gunicorn/Docker).

## 52. Phase 53 — Deployment Health Probes

| Fix | Sharraxaad |
|---|---|
| **/healthz (liveness)** | Load balancer/Docker/K8s probe — process wuu shaqeynayaa. 200 `{status:ok}`, login uma baahna |
| **/readyz (readiness)** | DB-ga ma la gaari karaa? `SELECT 1` → 200 `{status:ready,db:ok}` ama 503 haddii DB hoos u dhaco. Load balancer-ku wuxuu ku ogaadaa goorta uu traffic u diro |
| **Container healthcheck** | docker-compose: `erp` service hadda wuxuu isticmaalaa `/readyz` (interval 15s, start_period 20s) — Docker/K8s auto-restart haddii DB xiriir go'o |
| **Prod deps xaqiijin** | reportlab (server PDF) requirements.txt wuu ku jiraa → Docker-ka PDF-gu wuu shaqeeyaa. Postgres config (DATABASE_URL) la tijaabiyay |

98 test. Infra: Dockerfile + docker-compose (Postgres 16) + gunicorn + wsgi.py + .env.example — dhammaan diyaar.

Waxa hadhay oo dhab ah (rewrite/infra, ma aha bug): money→cents schema, billing.py kala-qaybin, Jinja templates, email/SMS integration (API key dibadeed u baahan).

## 53. Phase 54 — Forced Password Change (default-credentials risk closed)

Dhaliishii ammaan ee ugu weyneyd deployment kasta: `admin/INITIAL_ADMIN_PASSWORD` weli shaqeyn karta ilaa weligeed.

| Fix | Sharraxaad |
|---|---|
| **Password gate (fulin)** | Route-kii `/change-password` horeba wuu jiray laakiin **lama fulin jirin** — user-ku wuu iska dhaafi karay. Hadda `before_request` hook: user kasta oo leh `must_change_pw` **bog kasta** wuxuu ku laabtaa change-password ilaa uu beddelo. Banned: dashboard, modules, invoices — wax walba |
| **Waxa la oggol yahay** | change-password, logout, login, 2FA, static, `/healthz`, `/readyz` (probes-ka lama xannibo) |
| **Password policy** | ≥8 xaraf, ma aha mid caan ah, tiro ku jirto — weak waa la diidaa ("at least 8") |
| **Login hint** | "admin / password set during initialization" hadda wuxuu muuqdaa **kaliya** ilaa la beddelo; ka dib waa la qariyaa (ma aha inaad default creds u tusto qof kasta oo login-ka arka) |

100 test. Deployment cusub: `admin/INITIAL_ADMIN_PASSWORD` → isla markiiba password cusub ayaa lagaa rabaa, ka hor inta aanad wax gelin.

## 54. Phase 55 — Money → Integer Cents (schema)

Kii ugu weynaa ee liiska: lacagtu hadda **INTEGER cents** ayay ku kaydsan tahay database-ka.

| Qayb | Sharraxaad |
|---|---|
| **`core/moneytype.py`** | `Money` SQLAlchemy type: INTEGER cents kaydka, float dollars Python-ka. Qoraal kasta half-up ayaa loo soo koobaa — jajab-senti lama kaydin karo. Business logic isma beddelin (float weli Python-ka) |
| **51 money column** | Invoice/InvoiceItem/JournalLine/CommissionAccrual/CommissionPayment/PayReceipt/Expense/Purchase/PharmacySale/CreditNote/DebitNote/Account.opening/Budget/RecurringJournal/RadOrder.fee + Service (8 price/cost) · Medicine · Employee · EmpLoan · EmpContract · SalaryAdvance · Asset · MaintenanceJob · SvcContract · CashClosing · Doctor.fixed_rate |
| **27 Float oo hadhay** | Si ula kac ah: qty, percent/rate (discount_pct, percent_rate, max_discount, Currency.rate), cabbirro caafimaad (temp/weight/height), lab ranges (panic_low/high, LabParam), QC stats, iyo `comm_*_val`/`fee_value` (laba-ujeeddo: % ama $) |
| **Migration (version-aware)** | DB hore (float dollars) → cents **hal mar oo keliya**, marker `money_cents_v`. Saddex wadiiqo la tijaabiyay: fresh (marker v2, waxba lama beddelin) · legacy (batch 1+2) · v1-partial (batch 2 kaliya, core lama taabto). Dib-u-boot laba-jeer-beddelasho ma keeno |
| **Bug la helay & la saxay** | Markii hore waxaan u maleeyay in SQL aggregates ay cents soo celiyaan oo aan 100 u qaybiyay — **khalad**: SQLAlchemy result-processor-ka wuu ku dabaqaa `func.sum()` sidoo kale, sidaas balance kastaa 100-jibbaar ayuu u yaraan lahaa. Tijaabadu way qabatay; waa la laalay + test difaac ah (`test_money_aggregates_return_dollars`) |

Tijaabo: 3×19.99 → kaydka `1999` (integer) × 3, subtotal 59.97 sax, journal dheelitiran, payables saafi, backup/restore dollars ilaaliya, DB hore $150.00 wuu sii yahay $150.00.

103 test.

## 55. Phase 56 — Full Audit Sweep: restore data-loss bug found & fixed

Baaris buuxda oo nidaamka ah (route sweep + hawl kasta oo lacag ah) kadib:

| Natiijo | Sharraxaad |
|---|---|
| **Route sweep** | 133 GET route + 92 module route — **500 midna ma jirin**, link jabanna ma jirin |
| **Money flows** | Purchase · Expense · Payroll · Depreciation · Pharmacy — dhammaantood cents-ka kadib sax: $12.35, $249.99, base $850.75 → gross $971.00, depreciation $2,400.10 journal dheelitiran |
| **🐞 BUG HALIS AH oo la helay** | `dump_db` waa la ballaariyay (69 shax, magacyo shax dhab ah) laakiin **`restore` weli wuxuu raadinayay magacyadii hore** ('patients' halkii 'patient'). Natiijo: restore wuxuu **tirtiri lahaa xogta oo dhan oo eber soo celin lahaa** — ledger-ka, receipts-ka, accruals-ka oo dhan lumi lahaayeen |
| **Xalka** | Restore hadda wuxuu isticmaalaa isla `_all_models_in_fk_order()` ee dump-ku isticmaalo (hal ilo). Sidoo kale: fayl aan shaxdayada waafaqsanayn waa la diidaa halkii la tirtiri lahaa. Test difaac ah: `test_backup_and_restore_cover_every_table` |
| **La xaqiijiyay** | Ledger (3 journal, 6 line), receipts, accruals — dhammaan si buuxda ayay u soo noqdaan; lacagtu saxdeeda ($399.98); integrity cagaar |

105 test.

## 56. Phase 57 — Letterhead on every printed document

Farshaxankii rasmiga ahaa ee xarunta (header Ingiriisi+Carabi + logo, footer taleefan/goob/social) hadda wuxuu ka soo baxaa warqad kasta oo la daabaco.

| Qayb | Sharraxaad |
|---|---|
| **Faylasha** | `mdc_erp/static/brand/letterhead-header.jpg` + `letterhead-footer.jpg` (1800px, la habeeyay si degdeg loo daabaco) |
| **Meel walba** | Invoice · rasiid · lab/radiology report · voucher · referral — dhammaantood `printable()` ayay isticmaalaan, sidaas mid walba letterhead-ka wuu leeyahay |
| **Bog kasta** | `position:fixed` — warqad kasta oo daabacan (xitaa bogga 2aad) header/footer-ku wuu ku soo noqdaa |
| **Meel banaan** | Nuxurka waxaa laga fogeeyay farshaxanka: 38mm kor / 27mm hoos (hore 33/25 — 3mm oo cidhiidhi ah) |
| **🐞 Bug la saxay** | Badhamada (Print / Email / WhatsApp / Back) **warqadda ayay ku daabacmi jireen**: `.noprint{display:none}` waxaa ka adkaan jiray `style="display:flex"` ee inline ah. Hadda waa `!important` |
| **Ikhtiyaar** | Settings → `letterhead=0` haddii aad rabto qoraal-header kii hore (tusaale marka aad warqad madhan daabacayso) |

Tijaabo: PDF A4 dhab ah — 1 bog, farshaxan kor iyo hoos, badhan lagama arko. 106 test.

## 57. Phase 58 — Radiologist fee set on the scan (like doctor commission)

Foomka adeegga fudud (Settings → Service Management) hadda wuxuu leeyahay qayb **Commission & Fees**:

| Field | Doorasho |
|---|---|
| 🩺 **Doctor Commission** | none · Fixed $ per service · % of service price + Value |
| 🔬 **Radiologist Fee** | none · Fixed $ per service · % of service price + Value |

Labaduba isku hab: scan-ka ayaad ku dhex dejisaa, marka biilka la bixiyona si toos ah ayay u dhalaan payable.

**Tusaale (la tijaabiyay):** CT Scan — Brain, $150 · Doctor `Percent 20` · Radiologist `Fixed 10`
→ marka la bixiyo: doctor **$30**, radiologist **$10** (magaca radiologist-ka warbixinta qoray).

Kala sarreynta marka field-ku faaruq yahay: qaanuunka radiologist-ka gaarka ah (Radiologists → Fee Rule) → `rad_fee` guud ($10).

107 test.

## 57. Phase 58 — Pagination + Row-Level Branch Security

Laba dhib oo dhab ah (la cabbiray, ma aha malo) oo la xalliyay:

| Dhib | Ka hor | Ka dib |
|---|---|---|
| **Pagination** | 5,003 bukaan → **2.73 MB** bog, 5,004 saf, 0.20s | **85 KB**, 51 saf, 0.03s — **32x yaraansho**. 50 saf/bog (`list_page_size`), pager (‹ Prev · 1 2 3 · Next ›) oo haya search/filter, "51–100 of 5,003" |
| **Row-level security** | Ogolaanshuhu wuxuu ahaa **route-level** oo keliya: cashier kasta oo Billing furi kara wuxuu arkaa invoice kasta oo laan kasta ah | `branch_scope()` + `can_see()`: qofku wuxuu arkaa laantiisa oo keliya, **URL toos ahna** 403 (ma aha liiska oo keliya). `super_admin`/`it_admin`/`auditor` waxay arkaan dhammaan. Diiwaanka aan laan lahayn (xog hore) qof walba wuu arkaa si aan wax u lumin |

Lagu dabaqay: liisaska guud (patients, doctors, services...), Edit/Delete, Invoice list + detail.
Tijaabo: laba cashier oo laba laan ah — mid kastaa kaliya kiisa ayuu arkaa; URL isdhaafsi = 403; admin labadaba wuu arkaa.

109 test.

## 58. Phase 59 — Odoo-style list powers: Sort · Group By · Export

Waxa Odoo ugu fudud yahay ma aha muuqaalka — waa in **isticmaaluhu xogtiisa isagu kala saaro, code la'aan**. Taasi hadda liis **kasta** way ku jirtaa.

| Awood | Sharraxaad |
|---|---|
| **Sort** | "Sort: [field] ↓/↑" — column kasta oo scalar ah (magac, taariikh, lacag, status). URL-ka ayuu ku jiraa, sidaas la wadaagi karo |
| **Group By** | "Group by [Status / Category / Payment Method / Gender / Modality...]" → saf kasta = koox, tirada, **wadarta lacagta koox kasta** + safka Total. Taariikhda bishii ayaa lagu kooxeeyaa |
| **Drill-down** | Kooxda gujis → liiskii caadiga ah oo la sifeeyay (pagination weli shaqeynaysa) |
| **⭳ CSV** | Wax alla wixii shaashadda ku jira — search, taariikh, filter, group, sort — dhammaan **natiijada oo dhan** (ma aha bogga oo keliya). Password-yada waligood lagama saaro |
| **Config la'aan** | Dhammaan waxaa laga soo saaray model-ka: liis cusub oo la diiwaangeliyo isla markiiba wuu helayaa. Column-yada qiimahoodu gaar yahay (magac, MRN, taleefan) group-by lagama bixiyo — koox kasta hal saf macno ma laha |

Tusaale: `/m/expenses?group=category` → Electricity 6 · $1,140 · Water 6 · $1,182 … + Total.
`/m/patients?group=gender&gv=Female` → dumarka oo keliya. `⭳ CSV` → isla xogtaas.

111 test.

---

*Roadmap ikhtiyaari ah: lab QC (Levey-Jennings), SMS/WhatsApp gateway (Twilio/Hormuud API key ayay u baahan tahay),
Redis + Celery background jobs, appointment reminders, PACS/DICOM viewer.*
