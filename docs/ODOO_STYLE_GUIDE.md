# Odoo-Style MDC ERP Guide

## What changed

The interface now follows an Odoo-inspired application pattern while retaining the MDC-specific clinical and financial workflows. The **Apps** switcher opens a searchable module launcher. The sidebar groups modules by business area, and module pages expose contextual horizontal menus, breadcrumbs, back navigation, saved searches, favorites, recent records, smart buttons, and workflow status bars where the domain supports them.

The top-bar **＋ New** menu provides role-aware creation shortcuts. Global search is available with `Ctrl+K` or `Cmd+K`, and the module launcher is available with `Ctrl+Shift+K`. These controls reduce the need to navigate through deep menus.

## Odoo-style concepts mapped to MDC

| Odoo-style concept | MDC ERP implementation |
|---|---|
| Apps | Searchable All Modules launcher and explicit Apps button |
| App menus | Clinical, Diagnostic, Billing, Accounting, Inventory, HR, Reports, Admin, and other grouped menus |
| Workspace dashboard | Role-aware Dashboard with workload, KPI, queue, and financial widgets |
| List view | Existing searchable, filterable, paginated list pages |
| Form view | Existing validated creation and edit forms |
| Search views | Global search, module filters, saved searches, pinned filters, and favorites |
| Smart buttons | Related-record and workflow shortcut buttons on patient and invoice pages |
| Status bar | Clinical and referral workflow status bars, plus next-step prompts |
| Chatter/activity history | Audit log, notifications, recent records, and domain timelines |
| Record actions | Add, edit, archive, restore, protected delete, print, and contextual actions |
| Access control | Role permissions, branch scope, audit logging, and protected financial history |

## Important difference

This is an **Odoo-style interaction model**, not an Odoo database or module clone. Healthcare-specific entities such as patients, consultations, laboratory orders, radiology studies, referrals, and clinical records remain native to MDC ERP. Financial safeguards such as atomic billing claims, payment idempotency, reconciliation, and protected deletion remain in force.

## Recommended rollout

Train each role using its own dashboard and workspace first. Reception, cashier, laboratory, radiology, accounting, and administrator users should not be shown every application by default. Use role permissions and saved searches to keep each workspace focused. Before production rollout, validate the complete path from patient registration through clinical service, invoice creation, payment, receipt, reconciliation, and archival.
