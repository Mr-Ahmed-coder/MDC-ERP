# Inpatient / IPD (Phase 8, v8.0)

Ward & bed management, admissions (including hand-off from the Emergency
Department), nursing/progress notes, medication administration, bed transfer,
discharge, and inpatient billing with automatic bed charges. All-new tables;
reuses the existing invoicing and accounting.

## Wards & beds

- **Wards** (`/m/wards`) — General / Private / ICU / Maternity / Pediatric /
  Isolation.
- **Beds** (`/m/beds`) — each bed belongs to a ward, carries a **daily rate**,
  and a live status (Available / Occupied / Maintenance). Occupancy is kept in
  sync automatically on admit / transfer / discharge.

## Admission

`/ipd/admit` — admit a patient to a ward + bed with an admitting doctor and
diagnosis. Only **available** beds are listed; choosing one marks it occupied.

**ED hand-off:** dispositioning an ED visit as *Admit* jumps straight to this
form, pre-filled with the patient and complaint from the emergency visit — a
continuous record from ambulance to ward.

## Admission record

`/ipd/<id>` shows the patient, ward/bed, day count, and:

- **Notes** — Nursing / Doctor / Vitals progress notes.
- **Medication Administration Record (MAR)** — drug, dose, route, who gave it,
  and when.
- **Bed transfer** — move to another available bed; the old bed is freed, the
  new one occupied, and the move is logged with a reason.
- **Discharge** — Home / Referred / LAMA / Deceased, with a discharge summary;
  the bed is freed automatically.

## Inpatient billing

**Create bill** opens an invoice for the patient and automatically adds a **bed
charge** line (days × the bed's daily rate); add any other services and settle
through the normal billing/accounting flow.

## The tracking board

`/m/ipd` — current inpatients with ward/bed, doctor, diagnosis, admission date
and length of stay, plus KPI tiles for inpatients and free / occupied / total
beds.

## New data

`Ward`, `Bed`, `Admission`, `IPDNote`, `MedAdmin`, `BedTransfer` — all new
tables. A fresh `flask init-db` (or the startup self-heal) creates them; no
changes to existing tables.

## Permissions

| Key | Default roles |
|-----|---------------|
| `ipd` | super_admin, doctor, nurse, reception |
| `wards`, `beds` | super_admin, doctor, nurse, branch_manager |

Tests: `tests/test_ipd.py` covers admit + bed occupancy, notes & MAR, bed
transfer, discharge (bed freed), billing with the auto bed-charge line, the
ED→IPD hand-off, and RBAC.
