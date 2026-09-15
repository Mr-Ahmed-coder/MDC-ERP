# Operation Theatre (OT) (Phase 9, v8.0)

Surgery scheduling, the WHO Surgical Safety Checklist, operative & anaesthesia
notes, instrument/swab safety counts, and OT billing. All-new tables; links to
IPD admissions and reuses existing invoicing.

## Scheduling

`/ot/schedule` — book a surgery into a theatre with procedure, surgeon,
assistant, anaesthetist, anaesthesia type, priority (Elective / Emergency),
scheduled time, and diagnosis. Scheduling from an **IPD admission** (the
"Schedule surgery" button on the admission page) pre-fills the patient.

## WHO Surgical Safety Checklist

Every surgery is seeded with the three-phase checklist, tracked with a
completion count on the board:

- **Sign In** (before anaesthesia) — identity/site/consent, site marking,
  anaesthesia check, pulse oximeter, allergies, airway/aspiration risk, blood
  loss risk.
- **Time Out** (before incision) — team introductions, patient/site/procedure
  confirmation, antibiotic prophylaxis, critical events, imaging.
- **Sign Out** (before leaving) — procedure recorded, **instrument/sponge/needle
  counts correct**, specimen labelling, equipment issues, recovery concerns.

Tap any item to check/uncheck it; the person and time are stamped.

## Notes & instrument counts

- **Operative / Anaesthesia / Post-op / Nursing** notes on the surgery record.
- **Instrument, swab & gauze counts** — count-in vs count-out per item; any
  mismatch is flagged in red (a core theatre-safety control).

## Status & billing

Start → In progress → Complete stamps start/end times and shows the duration.
**Create bill** opens an invoice for the patient to add theatre & surgical
charges through the normal billing/accounting flow.

## The board

`/m/ot` — scheduled and in-progress surgeries with checklist progress, surgeon,
theatre and time, plus KPI tiles (scheduled / in progress / emergency /
completed).

## New data

`Theatre`, `Surgery`, `OTChecklistItem`, `SurgicalNote`, `SurgeryItem` — all new
tables. A fresh `flask init-db` (or the startup self-heal) creates them.

## Permissions

`ot` → super_admin, doctor, nurse. `theatres` → super_admin, doctor,
branch_manager.

Tests: `tests/test_ot.py` covers scheduling with auto-seeded checklist, ticking
items, notes, the instrument count-mismatch flag, the start→complete flow,
billing, the IPD→OT hand-off, and RBAC.
