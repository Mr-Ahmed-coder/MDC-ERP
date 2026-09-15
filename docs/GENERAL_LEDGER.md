# General Ledger module (Odoo Community 18-style)

An accounting workspace built on the ERP's existing double-entry data —
`JournalEntry` (the move: date / ref / memo) and `JournalLine` (the item:
account / debit / credit) — plus the `Account` chart. It reports on posted data;
it does not duplicate it.

## Menu (sub-navigation on every GL screen)

Dashboard · General Ledger · Journal Items · Journal Entries · Trial Balance ·
Chart of Accounts.

- **Dashboard** (`/m/gldash`) — KPIs (Total Debit, Total Credit, Net Balance,
  #Entries/#Accounts), latest entries, and a 6-month posting-volume chart.
- **General Ledger** (`/m/genledger`) — journal items with a **running balance**,
  grouped by Account / Account Type / Month (or flat), with opening/closing and
  debit/credit totals.
- **Journal Items** (`/m/jitems`) — the flat line list.
- **Journal Entries** (`/m/jentries`) — the moves, each with its debit/credit
  totals and a Posted/Reversal status; opens a full entry view.
- **Trial Balance** (`/m/trialbal`) — per-account Opening / Debit / Credit /
  Closing with a totals row and a balanced check.

## Filters, search, group-by, sorting

- **Date**: from/to pickers plus period chips — Today, This Week, This Month,
  This Quarter, This Year.
- **Filters**: Account, Account Type.
- **Search**: account code, account name, move reference, and description
  (memo) in one box (instant, debounced).
- **Group by**: Account, Account Type, Month, or none.
- **Sorting**: Date, Account Code, Debit, Credit (click the column headers).
- **Pagination** on the ledger and journal items.

## Drill-down

Clicking a move opens its source: invoices/payments (`INV-`/`PAY-`) open the
invoice, receipts (`RCT-`) open the receipt, and anything else opens the full
journal-entry view with all its lines and totals.

## Export & print

CSV export and a print view (General Ledger and Trial Balance) that flows
through the shared print helper — so the Print/Download/Open dialog and
`?auto=1` auto-print work here too.

## Security & performance

Role-gated via `genledger` (super_admin, accountant, and **auditor** as
read-only); clinical roles are denied. Every view and export is audit-logged.
Date filters are applied in SQL; the ledger paginates (100 rows/page). Because
the schema stores posted double-entry lines, the whole module is inherently
read-only reporting.

## Hospital integration

Postings already flow into these journals automatically from billing (patient
invoices auto-post sales and payment entries via `post_journal`), and the same
`post_journal(date, ref, memo, lines)` helper is what any other source
(payroll, assets, bank, supplier bills) uses to feed the ledger.

## Honest scope vs. Odoo 18

This is built on the current journal schema, which stores date, ref, memo,
account, debit and credit. Fields Odoo shows that this schema does **not**
store on each line — per-line **branch, partner/patient, currency, department,
assigned user**, and a **draft** state (entries here are posted when created) —
are therefore not available as ledger columns or filters without a schema
migration and back-fill. Partner/patient is surfaced where the move reference
identifies a source document (e.g. an invoice). Everything else in the spec —
the menu, date/period filters, search, group-by, sorting, running balance,
opening/closing, drill-down, dashboard, trial balance, CSV/print, role-based
read-only access and audit logging — is implemented.
