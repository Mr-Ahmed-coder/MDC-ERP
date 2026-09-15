# MDC Diagnostic ERP — Final 9.1 to 10.0 Production-Hardening Gap Matrix

The uploaded 9.1-to-10.0 specification is stored in `docs/FINAL_9_1_TO_10_PRODUCTION_HARDENING.txt`. It is applied as a controlled production-hardening baseline. The matrix below prevents unsupported claims and distinguishes implemented code from deployment evidence that must still be executed in a real staging environment.

## Current status

| Hardening area | Current state | Verified evidence | Required 10.0 gate |
|---|---|---|---|
| Production secrets | **Strong** | Fail-closed production configuration, explicit administrator initialization, no known production fallback secret, clean archive scan. | Verify `SECRET_KEY`, `JWT_SECRET_KEY`, `DB_PASSWORD`, and `ENCRYPTION_KEY` through the production secret manager; test fail-fast startup. |
| Docker separation | **Partial** | Development and production compose/Docker assets exist. | Add and execute a dedicated `docker-compose.test.yml`; add production PostgreSQL, restart policy, health checks, resource limits, and secret-required behavior. |
| HTTPS | **Partial** | Secure cookies and security headers exist; health/readiness probes exist. | Deploy behind Nginx or an equivalent reverse proxy, force HTTP-to-HTTPS redirect, enable HSTS/CSP, and prove `COOKIE_SECURE=0` cannot be used in production. |
| Central RBAC | **Partial-to-strong** | Central permission helpers, role-aware menus, server-side route checks, lifecycle permissions, and API protection exist. | Consolidate all action-level permissions in one registry; test every sensitive route, API endpoint, branch, and escalation path. |
| Branch isolation | **Partial** | Branch fields and branch-aware creation paths exist. | Add centralized query/access filters and automated tests proving Branch A cannot read or modify Branch B data. |
| Immutable audit | **Strong core** | Audit records, actor, timestamp, IP, entity, old/new values, lifecycle reason, archive ledger, and protected deletion exist. | Add role/session/device fields consistently, append-only database/operations controls, and audit coverage for inventory, procurement, HR, permissions, and configuration. |
| Migration authority | **Partial** | Alembic/Flask-Migrate migrations exist for financial integrity and lifecycle. | Move scattered bootstrap `ALTER TABLE` behavior into versioned migrations, then prove clean install and previous-version upgrade without data loss. |
| Clean installation | **Partial** | Bootstrap initialization and production setup documentation exist. | Create a clean PostgreSQL installation path that requires no manual SQL or undocumented edits. |
| Upgrade safety | **Pending environment evidence** | Migration structure exists. | Back up a previous-version database, migrate it, validate patient, accounting, inventory, and clinical data, and record checksums/counts. |
| Accounting balance | **Strong core** | Double-entry posting, reconciliation, period controls, reversals, and payment idempotency exist. | Add automated tests for invoice, payment, refund, purchase, inventory/COGS, asset, depreciation, bank, and supplier transactions; reject all unbalanced posting. |
| Posted-entry protection | **Partial-to-strong** | Period-close and reversal patterns exist. | Prove posted entries cannot be edited and that corrections require reversal plus a new transaction. |
| Inventory traceability | **Partial** | Inventory, warehouses, batches, expiry-related views, transfers, and procurement foundations exist. | Require source document, warehouse/location, quantity/unit, batch/expiry, user/date for every movement; prevent unauthorized negative stock. |
| FEFO | **Pending verification** | Batch/expiry concepts exist; no complete tested FEFO gate is evidenced. | Implement earliest-expiry selection, expired-stock rejection, authorized exception handling, and automated tests. |
| CT contrast | **Pending/partial** | Radiology and inventory foundations exist. | Implement contrast-required decision, product/batch/quantity/operator/patient/cost capture, automatic deduction, expiry/wastage reports, and accounting linkage. |
| Clinical result safety | **Partial-to-strong** | Workflow registry, lab/radiology transitions, report controls, image access, and audit exist. | Add strict Draft→Entered→Verified→Approved→Final→Locked lifecycle, amendment reason/history, approver, and no silent edits. |
| Critical results | **Partial** | Panic/critical fields and notification infrastructure exist. | Implement detection→alert→acknowledgement→responsible clinician→notification record→audit with method, result, action, and timestamp. |
| Laboratory | **Strong core / partial breadth** | Orders and status transitions are implemented and tested. | Complete sample rejection, reference ranges, critical values, repeat testing, verification, approval, final locking, and portal/send checks. |
| Radiology/PACS | **Partial** | Radiology worklist/reporting, image persistence, access control, and workflow transitions exist. | Validate scheduling, modality, DICOM/PACS, radiologist worklist, final report locking, and amendment history. |
| Billing | **Strong** | Atomic billable-source claims, idempotent payments, duplicate prevention, overpayment protection, and reconciliation exist. | Add full service→invoice→insurance/discount→payment→receipt→delivery/result acceptance chain for all configured services. |
| Insurance | **Partial/pending verification** | Insurance references and dashboard surfaces exist. | Implement eligibility→authorization→service→claim→submission→approval/rejection→reconciliation with patient/insurer responsibility and approved/rejected amounts. |
| Role-based UX | **Strong foundation** | Apps, grouped menus, Quick Create, dashboards, search, favorites, recent records, breadcrumbs, status actions, and guided next-step patterns exist. | Conduct role-based UAT for reception, cashier, doctor, lab, radiology, storekeeper, and accountant; complete accessibility and mobile tests. |
| Guided workflow | **Partial** | Declarative workflow registry and next-action helpers exist. | Add a unified patient journey with current step, completed steps, required action, next action, and status from registration through result delivery. |
| Performance | **Partial evidence** | Query modernization, indexes, pagination patterns, and compatibility query layer exist. | Run N+1 audit, large-report benchmarks, PostgreSQL load tests, and background jobs for exports/PDF/notifications/backups. |
| API security | **Partial-to-strong** | Protected API routes, idempotency, reconciliation endpoint, and Swagger UI exist. | Standardize public APIs under `/api/v1`, define token/JWT strategy, rate limits, validation, pagination, error schema, audit logging, and negative branch/organization tests. |
| Backup/recovery | **Partial** | Backup guidance and health/readiness endpoints exist. | Execute encrypted daily/weekly backup, verification, restore, validation, retention, RPO/RTO timing, and alerting. |
| Reproducible testing | **Partial** | Full suite passes locally: 253 passed, 2 skipped; Ruff and compilation pass. | Add `docker-compose.test.yml` that starts PostgreSQL, runs migrations/seeds/tests/coverage in one command; remove or resolve the two skips. |
| Documentation | **Strong baseline** | Deployment, security, user, Odoo-style, lifecycle, enterprise, and gap documents exist. | Synchronize model/module/API/test counts with the actual code and publish final acceptance evidence. |

## Priority order

The specification’s priority is adopted as: **security → database/migrations → reproducible testing → accounting integrity → inventory integrity → clinical safety → API security → backup/recovery → performance → UX → documentation → final acceptance**.

## Production certification rule

The system must not be labeled production-certified 10/10 merely because it starts or has broad feature coverage. Certification requires all Critical gates to pass and requires evidence for PostgreSQL installation/upgrade, branch isolation, balanced accounting, traceable inventory, FEFO, clinical locking/amendments, API security, backup restore, HTTPS, role-based UAT, and performance.

## Immediate safe implementation package

The next safe code package should focus on: removing or isolating remaining bootstrap schema alterations behind an explicit development-only compatibility path, adding a test compose file and migration runner, centralizing branch-access checks, adding posted-entry protection tests, implementing FEFO as a reusable inventory service, formalizing clinical amendment/critical-result records, and standardizing API v1/error/rate-limit behavior. Each change requires a migration where schema changes occur, focused tests, full regression, and clean release scanning.
