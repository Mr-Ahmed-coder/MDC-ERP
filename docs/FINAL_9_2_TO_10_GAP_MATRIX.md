# MDC Diagnostic ERP — Final 9.2 to 10.0 Gap and Acceptance Matrix

This matrix records the attached 9.2-to-10.0 enterprise-hardening specification and distinguishes code changes applied in the current candidate from production evidence that still requires PostgreSQL, Docker, HTTPS, backup infrastructure, or formal user acceptance testing.

## Applied in this candidate

| Requirement | Applied change | Evidence |
|---|---|---|
| Migration-first production startup | The WSGI entrypoint no longer calls `init_db()` or creates schema on import. Production bootstrap now refuses to continue when the migrated `setting` table is absent, while development/test compatibility setup remains available. | `wsgi.py`, `mdc_erp/bootstrap.py` |
| Alembic configuration | Added project-local `migrations/alembic.ini`, repaired Alembic logging initialization, and explicitly imported model metadata in `migrations/env.py`. | `migrations/alembic.ini`, `migrations/env.py` |
| Central RBAC consistency | Added `lab_supervisor` and `nurse` to the authoritative role registry because they were already referenced by permission entries. Added registry validation and a derived `ROLE_PERMISSIONS` index that fails early on orphan roles. | `mdc_erp/core/security.py` |
| Production secret management | Production now fails when `SECRET_KEY`, `JWT_SECRET_KEY`, `DB_PASSWORD`, or `ENCRYPTION_KEY` is absent or too short. | `mdc_erp/config.py` |
| Production Docker hardening | Production Compose no longer provides fallback secrets and requires all four secret classes; secure cookies and HTTPS URL scheme are enabled. | `docker-compose.yml` |
| HTTP security headers | Added CSP and production HSTS while preserving the existing UI’s same-origin inline styles/scripts. Existing `HttpOnly`, `SameSite`, frame, referrer, and content-type protections remain. | `mdc_erp/__init__.py` |
| Reproducible test environment | A PostgreSQL test Compose definition exists with isolated test credentials, health-gated startup, dependency installation, initialization, and pytest execution. | `docker-compose.test.yml` |
| Documentation | The complete attached specification and this matrix are stored in `docs/`. | `docs/FINAL_9_2_TO_10_ENTERPRISE_HARDENING.txt`, this file |

## Current implementation status

| Area | Status | Required certification evidence |
|---|---|---|
| Database migration authority | **Improved, not certified** | Generate and review a complete initial-schema Alembic revision; run fresh PostgreSQL migration and previous-version upgrade; prove rollback where safe. The existing historical bootstrap contains extensive SQLite compatibility `ALTER TABLE` logic that is now excluded from production but remains to be converted into versioned revisions. |
| RBAC and least privilege | **Improved, not certified** | Audit all direct role checks and every route/API/button/report/export; add negative tests for role escalation, clinical approval, financial actions, and administrative actions. |
| Multi-branch isolation | **Foundation exists, certification pending** | Execute UI, direct URL, API, search, report, and export tests proving Branch A cannot read or modify Branch B data. Preserve intentionally shared reference-data behavior such as patient search where applicable. |
| Accounting integrity | **Existing strong foundation** | Run all invoice, payment, refund, credit/debit note, purchase, expense, inventory/COGS, fixed-asset, depreciation, bank, insurance, and commission tests and verify debit equals credit for every posted journal. |
| Posted transaction protection | **Existing foundation** | Prove posted entries cannot be edited; every correction must be a referenced reversal/new transaction; verify fiscal period closing, reopening controls, and year-end behavior. |
| Inventory and FEFO | **Partial** | Verify movement traceability, negative-stock prevention, batch/expiry tracking, expired-stock rejection, and earliest-expiry-first selection for medicines, reagents, contrast, and consumables. |
| CT contrast | **Partial/pending** | Execute CT order→payment→contrast decision→batch→deduction→radiology report and confirm no deduction when contrast is not required, with cost, wastage, patient, operator, and audit records. |
| Clinical result safety | **Existing workflow foundation** | Verify Draft→Entered→Verified→Approved→Final→Locked, immutable history, amendment reason/approver/timestamp, and no silent overwrite for lab and radiology. |
| Critical results | **Partial/pending** | Verify alert, responsible clinician, acknowledgement, timestamp, notification method, action/comment, and audit trail. |
| Laboratory and radiology | **Strong foundation, breadth pending** | Execute full LIS and RIS/PACS acceptance workflows, including sample rejection, reference ranges, critical values, DICOM/PACS, report approval, final locking, and amendments. |
| API security | **Partial** | Standardize all public endpoints under `/api/v1/`; test invalid/expired tokens, missing permissions, wrong organization/branch, IDOR, injection, malformed requests, rate limits, and audit logging. |
| HTTPS and deployment | **Configuration improved, environment pending** | Deploy Nginx→Gunicorn→Flask→PostgreSQL, enforce port 80 redirect to 443, verify HSTS and secure cookies through the real proxy, and run health/readiness checks. |
| Backups and disaster recovery | **Documentation/foundation only** | Perform encrypted backup, retention, verification, destroy test database, restore, migrate if needed, validate data, and measure RPO/RTO. |
| Performance | **Partial foundation** | Run PostgreSQL query, N+1, search, dashboard, patient-history, financial-report, API, and large-export benchmarks; add background processing where thresholds require it. |
| UX and guided workflows | **Strong foundation** | Conduct role-based UAT for reception, doctor, laboratory, radiology, cashier, storekeeper, and accountant; verify minimal navigation and clear current/next action indicators. |

## Certification rule

> The application must not be labeled **10/10 Production Ready** until the acceptance evidence above is executed successfully. Passing the local SQLite regression suite demonstrates compatibility, not PostgreSQL migration safety, concurrency safety, HTTPS correctness, backup recoverability, or multi-branch isolation.

## Current local gate

The current candidate must pass Python compilation, Ruff, and the full regression suite after the applied changes. The sandbox does not provide Docker, so PostgreSQL Compose execution, migration execution against PostgreSQL, HTTPS proxy validation, concurrency tests, and backup/restore tests remain external acceptance gates.
