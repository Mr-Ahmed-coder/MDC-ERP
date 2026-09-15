# Blood Bank (Phase 12, v8.0)

Expands the existing donor + blood-unit registries with an **expiry-alert
dashboard**, **cross-matching**, and **transfusion records**. The existing
Donors and Stock registries are unchanged; this adds new tables on top.

## Dashboard

`/m/bloodbank` — at-a-glance blood-bank status:

- **Stock by group** — available unit count for each of the 8 ABO/Rh groups.
- **KPI tiles** — available / reserved / expiring within 7 days / expired.
- **Expiry alerts** — a list of units already expired or expiring soon, with a
  one-click **Mark expired** sweep.
- Quick links to Donors, Stock, Cross-match and Transfuse.

## Cross-matching

`/bloodbank/crossmatch` — pick a recipient patient and an available donor unit.
The form shows **ABO/Rh compatibility guidance** (compatible / incompatible)
based on the patient's and unit's groups, but the recorded **result** is the
technician's entry. A **Compatible** result **reserves** the unit for that
patient.

> Compatibility guidance is advisory for packed red cells and must always be
> confirmed serologically — it does not replace a laboratory cross-match.

## Transfusion

`/bloodbank/transfuse` — record an actual transfusion (patient, unit, volume,
any reaction, note). This marks the unit **Used** and issued to the patient, and
timestamps it. Reserved or available units can be transfused.

## Expiry handling

Units are flagged on the dashboard when within 7 days of expiry and highlighted
in red once past it; **Mark expired** moves all past-expiry available/reserved
units to `Expired` so they leave the usable stock.

## New data

`CrossMatch`, `Transfusion` — all new tables. The existing `Donor` and
`BloodUnit` models are untouched. A fresh `flask init-db` (or the startup
self-heal) creates the new tables.

## Permissions

`bloodbank` → super_admin, lab_tech, doctor, nurse. The existing `donors` and
`bloodunits` registries keep their own permissions.

Tests: `tests/test_bloodbank.py` covers the dashboard/expiry alerts,
cross-match (compatible → reserved), transfusion (unit → used/issued), the
expiry sweep, and RBAC.
