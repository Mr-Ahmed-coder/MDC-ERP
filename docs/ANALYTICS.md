# Analytics Dashboard (Phase 13, v8.0)

A read-only, hospital-wide executive overview that aggregates KPIs across every
module in one screen, with dependency-free inline charts. No new tables — it
reads existing data.

## Access

`/m/analytics` — under **Accounting** in the App Launcher. Permission
`analytics` → super_admin, accountant, branch_manager.

## What it shows

**Financial**
- Cash collected today and this month
- Billed this month
- Outstanding receivable
- Insurance amount due (from claims approved but not yet paid)

**Clinical & Operational**
- Patients registered today (and total)
- ED active / ED today
- Current inpatients and free beds
- Bed occupancy %
- Surgeries today and scheduled
- Dialysis sessions today
- Active ambulance dispatches
- Blood units available
- Lab orders today (and pending)
- Imaging orders today

**Trends (last 7 days)** — inline bar charts for cash collected, new patients,
lab orders and imaging orders.

## Notes

- Everything is **branch-scoped** like the rest of the ERP, so a branch user
  sees their branch's numbers.
- Charts are hand-rendered inline **SVG** — no external chart libraries, so the
  dashboard works fully offline.
- The financial figures reuse the same invoice-walk logic as the existing
  Financial Dashboard, so the numbers reconcile.

Tests: `tests/test_analytics.py` seeds data across several modules and asserts
the dashboard renders every section and chart, plus RBAC.
