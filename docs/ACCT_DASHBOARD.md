# Accounting Dashboard (Odoo Community 18-style)

A modern accounting overview at `/m/acctdash` (Accounting launcher). Permission
`acctdash` — super_admin, accountant, branch_manager, and auditor (read-only).

## Cards & panels
- **Cash Balance** (account 1101) and **Bank Balance** (account 1102).
- **Accounts Receivable** (unpaid live-invoice balances) and **Accounts Payable**
  (open supplier bills).
- **Monthly Revenue**, **Monthly Expenses**, **Net Profit** for the selected
  period (from Income/Expense journal totals).
- **Profit & Loss Summary** — revenue, expenses, net.
- **Outstanding Invoices** and **Overdue Invoices** (unpaid > 30 days).
- **Recent Payments** (receipts) and **Recent Journal Entries** — both drill
  through to the source document / journal entry.

## Controls
- **Branch selector** — scopes the invoice-based cards to a branch.
- **Date-range filter** — from/to (defaults to the current month).
- **Export** — Excel (.xlsx, real workbook with Summary / Outstanding / Payments
  sheets) and PDF (print view, works with the Print/Download/Open dialog).
- **Live** toggle — periodic auto-refresh (every 30s) for a near-real-time view.
- **Dark/Light** (inherits the app theme) and a **responsive** card grid that
  collapses to one column on phones.

## Honest notes
Figures reuse the same helpers as the rest of the system, so they reconcile with
the ledger. Because journal lines don't carry a branch tag, the branch selector
scopes the **invoice-based** cards (AR, outstanding, overdue, payments); the
journal-derived revenue/expenses are company-wide. There is no invoice due-date
field, so "overdue" means unpaid for more than 30 days. "Live" is a periodic
refresh, not a websocket push.
