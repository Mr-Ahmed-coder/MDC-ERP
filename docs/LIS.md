# LIS — Laboratory Information System (Phase 4, v8.0)

Adds a structured-result and analyzer-integration layer over the existing lab
module (which already has barcoded samples, collection tracking and panic
flags). Reuses the existing **QC** module and **LabParam** reference ranges.

## Analyzer / HL7 result import

Results are matched to open lab orders by **sample barcode** (the existing
`LabOrder.sample_no`). Three ingest paths:

1. **Paste / upload** (`/lis/import`) — an HL7 v2 **ORU^R01** message, or a CSV
   (`sample_no,test,value,unit,ref,flag`).
2. **Analyzer API** — `POST /api/lis/hl7` for an analyzer or middleware to push
   HL7 directly. Protected by a shared token: set **`lis_hl7_token`** in
   Settings and send it as the `X-LIS-Token` header (or `?token=`). Returns a
   proper HL7 **ACK** (`AA` accept / `AE` error / `AR` auth-reject).

The HL7 parser (`core/hl7.py`) is pure-python — no external HL7 library — and
reads PID-3 (MRN), OBR-3 (sample id) and OBX result rows.

## Critical values

Each imported analyte is flagged automatically: `H`/`L` from the reference
range, and `HH`/`LL` (critical) from an analyzer abnormal-flag or from the
`Service.panic_low` / `panic_high` thresholds. A critical result raises an
in-app **alert** to lab_tech / doctor / reception, sets `LabOrder.panic`, and
lands on the **Critical Value Alerts** board (`/lis/critical`) until a human
**acknowledges** it (`panic_ack`).

## Verification & release

Imported values are **unverified** until a tech reviews them on
`/lis/order/<id>/verify` — edit if needed, then **Verify & release**. This
stamps the verifier, recomputes the panic state, moves the order to `Resulted`,
and writes a human-readable summary into the existing `LabOrder.result` field so
the current lab report/print continues to work unchanged.

## Sample tracking & labels

`/lis/samples` shows active specimens by stage (Requested → Collected → Received
→ Resulted). `/lis/order/<id>/label` prints a **Code-128 barcode label** for the
sample (reuses `core/barcodes.py`).

## New data

- `LabInstrument` — analyzer registry (`/m/instruments`).
- `LabResultValue` — one structured analyte per row (value, unit, reference,
  flag, source Manual/Analyzer, verified).
- `LabOrder.panic_ack` — new nullable column (critical-alert acknowledgement).

## Permissions

| Key | Default roles |
|-----|---------------|
| `lis` | super_admin, lab_tech, doctor, reception |
| `instruments` | super_admin, lab_tech, it_admin, branch_manager |

The analyzer API endpoint is authenticated by the shared token, not a session.

## Upgrade

`python scripts/upgrade_v8.py` creates the new tables and adds
`lab_order.panic_ack` in place (idempotent; existing data preserved).

Tests: `tests/test_lis.py` covers HL7 import with a critical value, the alert
board and acknowledge flow, verification/release, CSV import, the token-protected
analyzer API (accept + reject), barcode label, and RBAC.
