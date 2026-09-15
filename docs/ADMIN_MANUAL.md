# MDC Diagnostic ERP — Administrator Manual

**Version 10.0 candidate** · For system administrators and finance managers.

---

## 1. Roles & permissions

The system ships with these roles. Assign the narrowest role that lets a person do their job.

| Role | Typical use |
|------|-------------|
| **Super Admin** | Full access, including reset/unlock and system settings. |
| **Branch Manager** | Oversight of a branch; approvals, payables, reports. |
| **Accountant** | Accounting, payables, commissions, financial reports, fixed assets. |
| **Reception** | Patient registration, appointments, queue, order entry (view-only on finance). |
| **Cashier** | Invoicing and payments. |
| **Doctor** | Clinical requests, results review. |
| **Radiologist** | Radiology reporting. |
| **Lab Technician** | Laboratory results and QC. |
| **HR Manager** | Staff records and payroll. |
| **Storekeeper** | Inventory and stock. |
| **Maintenance Engineer** | Equipment maintenance jobs. |
| **IT Administrator** | System health, users, backups. |
| **Auditor** | Read-only access to records and the audit log. |

Manage accounts under **Admin → Users**: create users, set roles, reset passwords, and deactivate leavers. Permissions are enforced on every route — a user who lacks a permission is shown a clear "You do not have permission to perform this action" message, and the attempt is recorded.

---

## 2. Organization setup

**Settings → Organization:** clinic name, address, logo, currency, and print header. These appear on every printed document. Keep them accurate before issuing real invoices.

---

## 3. Accounting configuration

- **Chart of Accounts** — review before go-live. Key accounts used automatically:
  - 1510 Equipment · 1520 Accumulated Depreciation · 2100 Accounts Payable
  - 4000 Income · 6400 Depreciation Expense · 6450 Repairs & Maintenance
  - 4900 Gain on Disposal · 6600 Loss on Disposal · 3300 Revaluation Surplus
- **Fiscal periods** — postings are checked against open periods; close periods to lock history.
- **Opening balances** — enter through journal entries before transacting.

All automatic postings are balanced (total debit = total credit) and idempotent (re-running never double-posts).

---

## 4. Workflow locking & corrections

To prevent duplicate transactions:

- One doctor request maps to one active invoice.
- When an invoice is **completed**, it locks: no new items, no duplicate invoice, no duplicate payment.
- Only a **Super Admin** may **Reset to Draft** an invoice to re-enable editing. The action requires a reason and is fully recorded in the audit log; linked referrals are re-opened automatically.

Always prefer a correcting entry over deleting data. The audit trail is a compliance asset — keep it intact.

---

## 5. Fixed Assets administration

**Accounting → Fixed Assets** provides the full asset lifecycle: purchase → activate (capitalisation entry) → automatic monthly depreciation (Straight Line, Declining Balance, Units of Production) → maintenance → transfer → revaluation → disposal (gain/loss). Depreciation posts Dr Depreciation Expense / Cr Accumulated Depreciation using each category's configured accounts. Configure categories, useful life, residual value, and accounts under **Fixed Assets → Asset Categories**. See the module's own Reports tab for the register, depreciation schedule, NBV, and disposal reports.

---

## 6. Notifications

Events are routed to roles automatically (payments → cashier/accountant/manager; reports → reception/lab/radiology; low stock → storekeeper/lab/admin; backup failure → admin). No configuration is required; Super Admin sees all events.

---

## 7. Audit log

**Admin → Audit** records every meaningful action with the user, timestamp, IP address, action type, affected record, before/after values, and (where required) a reason. Use the tabs to filter by activity type. Auditors have read-only access to this log.

---

## 8. System health

**Admin → System Health** shows live CPU, RAM, and disk usage; database size and integrity; backup status; API status; active users; failed logins; unresolved errors; and the system version. Check it after every upgrade and as part of daily operations.

---

## 9. Backups

Configure and verify automatic backups under **Admin → Backup**. This is the single most important administrative duty — see [BACKUP_RESTORE.md](BACKUP_RESTORE.md) for the full procedure and a restore drill you should run before go-live.

---

## 10. Going live — checklist

1. Strong admin password set; demo data removed.
2. Organization details, logo, and currency configured.
3. Real users created with correct roles; leavers deactivated.
4. Chart of accounts reviewed; opening balances entered; current period open.
5. Fixed-asset categories and accounts configured.
6. Automatic backups running and a **restore drill completed successfully**.
7. Production WSGI server (Gunicorn/Waitress) behind TLS — never the dev server.
8. System Health reviewed; version confirmed.
