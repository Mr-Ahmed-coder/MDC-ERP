# MDC Diagnostic ERP — Enterprise Upgrade Gap Matrix

## Purpose

The uploaded enterprise specification is now stored in `docs/ENTERPRISE_UPGRADE_SPECIFICATION.txt` and is treated as the project’s controlled upgrade baseline. It is a broad target specification, not a safe single patch: applying every item at once would risk regressions, data loss, and unverified financial or clinical behavior. This matrix translates it into staged implementation gates while preserving working modules.

## Current assessment

| Capability area | Current state | Evidence in current release | Next gate |
|---|---|---|---|
| Security and authentication | **Strong / mostly implemented** | Fail-closed production configuration, secure cookies, password-change gate, lockout tracking, TOTP support, protected routes, audit events, and no known default production secret. | Enforce target-role MFA policy, secret rotation, dependency scan, and independent penetration testing. |
| HTTPS and web security | **Partial** | Secure session settings, CSRF protection, security headers, health/readiness endpoints, and production configuration exist. | Enforce HTTPS/HSTS and a reviewed CSP at the reverse proxy and application boundary; validate CORS policy. |
| Role-based access control | **Partial-to-strong** | Central permission helpers, role-aware Quick Create and Apps menus, lifecycle permissions, and server-side route checks exist. | Replace remaining module-level role strings with a complete action-level registry and test every sensitive route/branch combination. |
| Audit trail and protected lifecycle | **Strong** | Audit model, archive ledger, archive/restore/safe-delete services, protected financial/clinical deletion rules, and reasons for lifecycle actions exist. | Make audit storage append-only at the database/operations layer and complete coverage sampling for inventory, procurement, configuration, and report changes. |
| Database migrations | **Partial-to-strong** | Flask-Migrate/Alembic tree includes financial-integrity and record-lifecycle migrations. | Run clean-install and upgrade migrations against PostgreSQL; remove remaining scattered bootstrap schema alterations. |
| Accounting integrity | **Strong core / partial breadth** | Double-entry posting helpers, period controls, reconciliation, idempotent receipts, atomic billable claims, and finance audit command exist. | Add acceptance coverage for refunds, credit/debit notes, inventory accounting, depreciation, bank reconciliation, fiscal-year close, and external finance sign-off. |
| Inventory | **Partial** | Inventory and purchasing modules exist. | Implement and verify warehouse/location/batch/expiry/serial/FEFO flows with traceable stock movements and accounting integration. |
| CT contrast inventory | **Pending or partial** | No verified end-to-end contrast-specific consumption gate is included in the current release evidence. | Add order-to-batch-to-consumption workflow, no-contrast branch, operator/patient linkage, expiry controls, wastage, and cost reports. |
| Clinical safety | **Partial-to-strong** | Workflow registry, report edit controls, radiology image access control, audit records, and role protection exist. | Add finalized-result amendment records, critical-result escalation, patient duplicate detection, approval locks, and clinical safety acceptance tests. |
| Laboratory workflow | **Strong core / partial breadth** | Laboratory routes and declarative transitions exist with regression coverage. | Complete reference-range, critical-value, sample rejection, repeat-test, verification, approval, and portal/notification acceptance coverage. |
| Radiology/RIS/PACS | **Partial** | Radiology workflow, image upload/access, reporting, approval-related fields, and image persistence are implemented. | Validate DICOM/PACS integration, worklists, finalized-report amendment history, modality scheduling, and production object storage. |
| Billing workflow | **Strong** | Role-aware creation, atomic source claims, idempotent payments, duplicate prevention, overpayment protection, and reconciliation exist. | Add unified patient-to-service-to-invoice-to-payment workflow and full refund/insurance/credit acceptance coverage. |
| Procurement | **Partial** | Supplier, purchase, inventory, and accounting components exist. | Complete request-to-approval-to-RFQ-to-PO-to-GRN-to-AP-to-payment state model, partial receiving, returns, backorders, and supplier performance. |
| User experience | **Strong foundation** | Odoo-style Apps, grouped menus, Quick Create, search, favorites, recent records, breadcrumbs, status workflows, and record actions exist. | Add role-specific dashboards, keyboard/accessibility testing, mobile testing, and daily-workflow UAT. |
| Dashboards and reporting | **Partial** | Management and module reporting surfaces exist. | Add drill-down KPI definitions, branch/department/user/service filters, scheduled reports, AR/AP aging, cash flow, and validated financial statements. |
| API and integrations | **Partial** | Protected API routes, payment idempotency, reconciliation endpoint, portal-related routes, and notification infrastructure exist. | Version API under `/api/v1`, publish OpenAPI, add rate limits, webhook signing, integration contract tests, and external-system adapters. |
| FHIR readiness | **Pending architecture gate** | Current models map to several healthcare concepts but no verified FHIR resource layer is included. | Define resource mappings and versioned adapters for Patient, Practitioner, Organization, Encounter, Observation, DiagnosticReport, ServiceRequest, Medication, Invoice, and Appointment. |
| Performance | **Partial evidence** | Query compatibility modernization, indexes, pagination patterns, and SQLite concurrency pragmas exist. | Run PostgreSQL load tests, identify N+1 queries, benchmark dashboards/reports, and move heavy exports/PDF jobs to background workers. |
| Backup and disaster recovery | **Partial** | Backup guidance and health/readiness documentation exist. | Execute encrypted scheduled backups, verification, clean-environment restore, RPO/RTO timing, and alert tests. |
| Testing | **Strong functional baseline / incomplete production evidence** | Latest full suite: 253 passed, 2 skipped; compilation and Ruff pass. | Resolve optional PACS and auditor fixture skips, run PostgreSQL, concurrency, browser, accessibility, load, recovery, and security tests. |
| Deployment | **Strong candidate / not certified** | Docker/Gunicorn, production configuration, migrations, health/readiness, clean packaging, and deployment guide exist. | Run staging deployment through reverse proxy/HTTPS with secrets, monitoring, rollback, and operator handover. |
| Admin configuration | **Partial** | Settings, services, users, roles, branches, and operational configuration exist. | Complete configurable taxes, insurance, approval workflows, number sequences, templates, warehouses, reorder rules, and report templates. |
| Multi-branch architecture | **Partial** | Branch model and permissions exist. | Prove row-level branch isolation, cross-branch reporting, branch-aware numbering, and branch-specific configuration in PostgreSQL. |

## Safe application rule

The specification must be implemented in release-gated increments. Financial, clinical, inventory, and identity changes require a migration, focused acceptance tests, audit behavior, rollback consideration, and a full regression run. No requirement should be satisfied by merely adding a menu or model without proving its transaction and authorization behavior.

## Recommended implementation sequence

| Phase | Scope | Exit criterion |
|---|---|---|
| A | PostgreSQL migration, constraints, branch isolation, and concurrency tests | Clean install, upgrade, and concurrent billing/payment tests pass. |
| B | Accounting breadth and inventory traceability | Every tested financial and stock movement balances and is source-traceable. |
| C | Clinical safety and LIS/RIS/PACS reliability | Final clinical records are approval-locked, amendable only with reason, and integration tests pass. |
| D | Role dashboards, accessibility, API versioning, and reporting | Representative users complete daily workflows with no Critical/High accessibility or authorization findings. |
| E | Backup, restore, monitoring, load, security, and go-live | RPO/RTO, rollback, alerting, penetration, and production deployment gates pass. |

## Release interpretation

The current system is an advanced, hardened ERP candidate with strong billing, audit, workflow, and usability foundations. The uploaded specification expands the target into a full healthcare ERP/HIS/LIS/RIS/PACS, pharmacy, inventory, procurement, accounting, HR, reporting, and integration platform. The remaining work is therefore a roadmap of controlled product increments rather than a single safe “apply all” operation.
