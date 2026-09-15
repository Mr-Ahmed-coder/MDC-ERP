# Emergency Department (Phase 7, v8.0)

Triage-driven tracking for emergency arrivals — from the door to disposition —
with serial vitals, clinical notes, observation, and one-click emergency billing.
All-new tables; nothing in existing modules changes.

## Flow

```
Arrival (Walk-in / Ambulance / Referral)
   → Triage (level 1–5 + vitals)
   → Waiting → In treatment / Observation
   → Disposition: Discharge / Admit / Refer / LAMA / Deceased
```

## Triage

A 5-level priority scale, colour-coded on the board and used to sort it:

| Level | Name | Colour |
|-------|------|--------|
| 1 | Resuscitation | red |
| 2 | Emergency | orange |
| 3 | Urgent | yellow |
| 4 | Less urgent | green |
| 5 | Non-urgent | teal |

A **Level 1** arrival raises an immediate in-app alert to doctors and nurses.

## Tracking board

`/m/ed` — active patients sorted by triage priority, each row colour-striped by
level, showing complaint, arrival mode, attending, bed, **time in ED**, and
status. KPI tiles: Waiting / In treatment / Observation / Resuscitation.
"Show all today" reveals discharged/admitted patients too.

## Visit record

`/ed/<id>` — one screen with:
- header (identity, triage, status, attending, bed, time in ED, complaint,
  triage vitals),
- **serial vitals** timeline (BP, HR, Temp, SpO₂, RR, GCS, Pain) — add a new set
  any time,
- **notes** (Doctor / Nursing / Procedure),
- actions: start treatment, move to observation, assign clinician/bed,
  disposition, and billing.

Unidentified patients can be registered by description (e.g. "Unknown male") and
linked to a record later.

## Emergency billing

**Create bill** generates an invoice for the patient and links it to the visit,
then opens the existing invoice screen to add emergency services/charges — so ED
billing flows through the normal invoicing and accounting. (Unknown, unlinked
patients can't be billed until a patient record is attached.)

## Admission handoff

An **Admit** disposition marks the visit `Admitted` and stamps the time —
the hand-off point for a future Inpatient (IPD) module.

## New data

`EDVisit`, `EDVital`, `EDNote` — all new tables. A fresh `flask init-db` (or the
startup self-heal) creates them; no changes to existing tables.

## Permissions

`ed` → super_admin, doctor, nurse, reception.

Tests: `tests/test_ed.py` covers triage arrival, the board, the treatment flow,
serial vitals + notes, emergency billing (and the unknown-patient guard), and
admission disposition, plus RBAC.
