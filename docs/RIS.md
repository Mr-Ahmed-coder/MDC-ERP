# RIS — Radiology Information System (Phase 2, v8.0)

A scheduling / workflow / sign-off layer built **on top of** the existing
`RadOrder`, `Radiologist` and the PACS study store — not a parallel system. It
adds no new `RadOrder.status` values, so the existing Radiology screen keeps
working unchanged; every RIS stage is derived from the current status plus new
timestamp columns.

## Pipeline

```
Requested ──► Scheduled ──► Acquired ──► Reported ──► Approved (signed)
   │             │             │            │            │
requested_at  scheduled_at  acquired_at  reported_at  approved_at   ← TAT anchors
```

- **Worklist board** (`/m/ris`, App Launcher → Radiology → RIS): every imaging
  request with priority, scheduled slot, assigned radiologist, derived stage and
  live turnaround time. Filter by modality and stage; stage-count chips across
  the top.
- **Schedule** — book an order onto an imaging resource (machine/room) and slot,
  set priority (Routine / Urgent / STAT).
- **Acquire** (technician workflow) — records the technician and acquisition
  time, moves the order to `Imaged`, then jumps straight to DICOM upload
  pre-linked to the order (feeds PACS from Phase 1).
- **Assign radiologist** — attach any active radiologist to the order.
- **Sign off** — a radiologist approves the written report; this stamps
  `approved_by`, `approved_at`, and an HMAC **digital signature** (via the
  existing `doc_sig` verification key), and engages the existing print lock so
  the report can no longer be silently edited.
- **Turnaround (TAT)** (`/ris/tat`) — fastest / average / slowest signed-study
  turnaround per modality, plus a live count of orders at each stage.

## New data

- **`ImgModality`** — an imaging resource the RIS schedules onto (e.g. "CT
  Scanner 1", "Ultrasound Room 2"). Managed at **Radiology → Imaging Modalities**
  (`/m/modalities`).
- **`RadOrder`** gains nullable RIS columns: `priority`, `modality_id`,
  `scheduled_for`, `technician`, the five TAT timestamps, `approved_by`,
  `signature`. All nullable — existing orders and code are unaffected.

## Permissions

| Key | Default roles |
|-----|---------------|
| `ris` | super_admin, radiologist, doctor, reception, lab_tech |
| `modalities` | super_admin, it_admin, branch_manager, radiologist |

Sign-off additionally requires the `radiologist` (or `super_admin`) role.

## Enabling on an existing install

```bash
flask init-db      # create_all() adds img_modality + the new RadOrder columns*
```

\* On SQLite, `create_all()` adds the new table. The new **columns** on the
existing `rad_order` table are picked up automatically on a fresh `init-db`; for
an in-place upgrade of a populated Postgres database, add them with a one-line
migration (`ALTER TABLE rad_order ADD COLUMN ...`) or an Alembic revision — they
are all nullable, so no data backfill is required.

Tests: `tests/test_ris.py` drives the full pipeline (schedule → acquire →
report → sign-off), asserts TAT tracking and the signature, and covers RBAC and
the "report required before sign-off" guard.
