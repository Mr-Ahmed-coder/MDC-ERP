# MDC Diagnostic ERP — Final 9.0 to 10.0 Gap Matrix

The uploaded specification is stored in `docs/FINAL_9_TO_10_ENTERPRISE_SPECIFICATION.txt`. This document applies it as a controlled release baseline. It distinguishes capabilities already present from those that still require implementation or deployment evidence.

## Current coverage

| Specification phase | Current assessment | Existing evidence | 10.0 gate |
|---|---|---|---|
| Security hardening | **Strong, with production gates pending** | Fail-closed production secrets, secure cookies, CSRF, lockout, login history, session controls, password-change gate, TOTP support, and clean release scans. | Enforce HTTPS/HSTS/CSP in the target reverse proxy, require MFA for privileged roles, rotate secrets, and complete penetration/dependency scans. |
| Centralized RBAC | **Partial-to-strong** | Central permission helpers, role-aware menus/actions, lifecycle permissions, and route-level checks. | Complete one authoritative action-level registry and test all sensitive routes, APIs, and branch combinations. |
| Multi-branch isolation | **Partial** | Branch fields, branch-aware creation paths, and branch-related authorization patterns exist. | Prove row-level isolation and cross-branch reporting in PostgreSQL with leakage tests. |
| Audit and traceability | **Strong core** | Audit records, archive ledger, protected lifecycle service, reasons, actors, timestamps, and protected clinical/financial deletion behavior. | Make audit append-only operationally and complete coverage for inventory, procurement, HR, permissions, and configuration changes. |
| Accounting integrity | **Strong core, partial breadth** | Double-entry posting, period controls, reversals, payment idempotency, finance reconciliation, and audit command. | Add full acceptance coverage for refunds, credit/debit notes, inventory/COGS, depreciation, bank reconciliation, year-end close, and posted-entry immutability. |
| Inventory accuracy | **Partial** | Inventory, batches, expiry-related views, warehouses, stock levels, transfers, and procurement foundations exist. | Complete verified FEFO, serial tracking, stock valuation, traceable movement source, and accounting integration. |
| CT contrast control | **Pending/partial** | Radiology and inventory foundations exist; no verified end-to-end contrast-specific consumption gate is present in the current evidence. | Implement contrast-required decision, product/batch/quantity capture, automatic deduction, operator/patient/cost linkage, expiry, wastage, and reports. |
| Procurement integrity | **Partial** | Supplier, purchase, inventory, and accounting components exist. | Complete request-to-approval-to-RFQ-to-comparison-to-PO-to-GRN-to-AP-to-payment workflow and over-receipt controls. |
| Clinical safety | **Partial-to-strong** | Workflow registry, radiology report controls, image access checks, audit trail, and role protection exist. | Add duplicate-patient detection, allergy/critical-result handling, final-result locks, amendment history, and approval acceptance tests. |
| Laboratory | **Strong core, partial breadth** | Lab orders and status transitions are implemented and tested. | Complete reference-range, critical-value, sample rejection, repeat test, verification, approval, and portal/send coverage. |
| Radiology/RIS/PACS | **Partial** | Radiology worklist/reporting, image persistence/access control, and report transitions exist. | Validate scheduling, DICOM/PACS integration, worklists, finalized-report amendments, and production file storage. |
| Billing | **Strong** | Atomic billable-source claiming, idempotent payments, overpayment protection, reconciliation, and protected financial records. | Add one guided patient-to-service-to-invoice-to-payment flow and complete insurance/refund/credit acceptance coverage. |
| Insurance | **Partial or pending verification** | Insurance/claims references and dashboard surfaces exist, but full eligibility, authorization, claim reconciliation, and patient-responsibility flow are not evidenced. | Implement and test insurer, policy, eligibility, preauthorization, claim status, approved/rejected amounts, and reconciliation. |
| Role-based UX | **Strong foundation** | Apps launcher, role-aware Quick Create, grouped menus, search, favorites, recent records, dashboards, breadcrumbs, and status actions. | Complete role-specific UAT, keyboard/accessibility checks, responsive testing, and guided workflow completion. |
| Guided workflows | **Partial** | Declarative workflow registry and next-action labels exist for key clinical flows. | Build a patient journey wizard with completed/current/next indicators across registration, service, billing, order, result, approval, and delivery. |
| Dashboards and analytics | **Partial** | Role-specific KPI selection and management dashboard patterns exist. | Add validated drill-down from dashboard to report to transaction to source record, with branch/department filters. |
| Reporting | **Partial** | Many operational and financial reports exist. | Standardize filters, pagination, print/PDF/Excel export, and report acceptance against approved financial totals. |
| API | **Partial-to-strong** | Protected API routes, idempotency, reconciliation endpoint, and Swagger UI exist. | Standardize all public endpoints under `/api/v1`, add JWT or approved token strategy, rate limiting, pagination, error schema, and maintained OpenAPI. |
| Integrations/FHIR | **Pending architecture gate** | Portal, notification, PACS-related, and integration foundations exist. | Define versioned adapters and mappings for Patient, Practitioner, Organization, Encounter, Observation, DiagnosticReport, ServiceRequest, Medication, Invoice, and Appointment. |
| Performance | **Partial** | Query modernization, indexes, pagination patterns, and SQLite concurrency settings exist. | Run PostgreSQL load tests, remove N+1 hotspots, benchmark reports/dashboards, and move heavy work to background jobs. |
| Migrations | **Strong baseline, environment pending** | Alembic/Flask-Migrate tree contains financial-integrity and lifecycle migrations. | Run clean-install and previous-version upgrade against PostgreSQL; remove or document scattered bootstrap alterations. |
| Testing | **Strong functional baseline, incomplete production evidence** | Latest suite: 253 passed, 2 skipped; compilation and Ruff pass. | Resolve PACS and auditor skips, add PostgreSQL, concurrency, browser, accessibility, load, recovery, and API contract tests. |
| Backup and recovery | **Partial** | Backup/deployment guidance and health/readiness probes exist. | Execute encrypted backup, verify, restore, validate, RPO/RTO timing, and failure alert tests. |
| Documentation | **Strong baseline** | Deployment, user, Odoo-style, record-options, roadmap, and enterprise specification docs exist. | Keep model/API/test counts synchronized with code and publish the final gap report after each release. |
| Code quality | **Improved** | Duplicate radiology mapping fixed, unused imports reduced, workflow service added, lint passes. | Continue service extraction, route slimming, dependency scanning, and full warning cleanup. |

## Safe implementation order

The new specification should be applied in this order: **reliability, security, data integrity, clinical safety, accounting accuracy, inventory accuracy, user experience, performance, then new features**. This sequence prevents an attractive feature such as insurance, contrast reporting, or a new dashboard from masking unresolved transaction, authorization, or recovery risks.

## Immediate 10.0 gates

The next implementation package should focus on PostgreSQL migration/upgrade testing, branch leakage tests, posted-entry protection, inventory FEFO and traceable movement tests, clinical final-result amendment history, API `/api/v1` standardization, guided patient workflow navigation, and backup-restore execution. The uploaded specification explicitly requires validation rather than merely application startup; these gates are therefore mandatory for production certification.

## Honest release interpretation

The current system is an advanced **9.0-to-10.0 candidate** with strong security, billing, audit, workflow, and user-experience foundations. The uploaded specification expands the target into a full enterprise healthcare platform. The remaining work is a controlled sequence of migrations, domain increments, integrations, and environment tests—not a safe single bulk patch.
