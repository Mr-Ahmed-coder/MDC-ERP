# Dialysis (Phase 10, v8.0)

Haemodialysis session scheduling with machine assignment, the full treatment
record, pre/post lab monitoring, and billing. All-new tables; reuses existing
invoicing.

## Scheduling & machines

- **Machines** (`/m/dmachines`) — each carries a status (Available / InUse /
  Maintenance), kept in sync automatically as sessions start and complete.
- **Schedule** (`/dialysis/schedule`) — patient, machine, time, vascular access
  (AV Fistula / AV Graft / Catheter), dialyzer, dry weight, and UF (fluid
  removal) goal.

## Treatment record

- **Start** captures pre-session data (pre weight, pre BP, blood flow, heparin)
  and marks the machine InUse.
- **Complete** captures post-session data (post weight, post BP, **UF
  achieved**, duration, complications, notes) and frees the machine.
- The session page shows the full record side by side: dry/pre/post weights,
  pre/post BP, UF goal vs achieved, blood flow, duration, dialyzer and access.

## Lab monitoring

Record **pre-** and **post-dialysis** lab values (Hb, K⁺, Urea, Creatinine, …)
against the session, so the reduction across the session is visible on one
screen.

## Billing

**Create bill** opens an invoice for the patient to add the dialysis session
charge through the normal billing/accounting flow.

## Board

`/m/dialysis` — sessions with patient, machine, access, UF achieved and status,
plus KPI tiles (scheduled / in progress / free machines / total machines).

## New data

`DialysisMachine`, `DialysisSession`, `DialysisLab` — all new tables. A fresh
`flask init-db` (or the startup self-heal) creates them.

## Permissions

`dialysis` → super_admin, doctor, nurse. `dmachines` → super_admin, doctor,
nurse, branch_manager.

Tests: `tests/test_dialysis.py` covers scheduling, start (machine→InUse with
pre-data), pre/post lab monitoring, complete (machine→Available with UF), and
billing, plus RBAC.
