# Universal Global Search (Phase 16, v8.0)

A permission-aware command palette that searches the whole ERP from anywhere,
Odoo-style. Open it with the search box in the top bar or **Ctrl + K**
(**Cmd + K** on macOS).

## Opening it

- Click the **Search…** box in the top navigation, or
- Press **Ctrl + K** / **Cmd + K** anywhere.
- (The App Launcher moved to **Ctrl + Shift + K** so Ctrl + K is search.)

Keyboard inside the palette: **↑ / ↓** move, **Enter** opens, **Esc** closes.

## What it searches

Across modules simultaneously — **Patients, Appointments, Laboratory, Radiology
(X-ray/CT/MRI/Ultrasound), Pharmacy, Billing/Invoices, Insurance, Suppliers,
Assets, Vehicles, Staff (doctors/employees/users)** — plus a **Navigate**
category that jumps to any screen (Reports, Settings, Audit Logs, Accounting,
HR, Inventory, User Accounts, …) by name in English or Somali.

Searchable fields include name, MRN (patient ID), invoice number, phone,
national ID / passport, lab sample number, imaging/modality, prescription,
employee ID, plates, serials and codes. **Barcode/QR scanners** work out of the
box — a scanner types the code into the box like a keyboard; press Enter to open
the top match.

## Results

Results are grouped by category with an icon, and each row shows **title,
description, module, status and last-updated**. Matching text is **highlighted**.
Clicking (or Enter) opens the record's page immediately.

- **Fuzzy matching** tolerates misspellings on names (e.g. *amena* → *Amina*).
- **Unicode-safe** — substring search works for Latin, **Arabic** and any script.
- **Recent searches**, **frequently used** searches, and **pinned records** show
  when the box is empty. Pin any result with the 📌 icon (click again to unpin).

## Permissions & privacy

The palette only ever returns records the signed-in user is allowed to open:
each category is gated by that module's permission and every query is
**branch-scoped**, so a branch user sees only their branch, and a user without
(say) Laboratory access gets no lab results. Every search is written to the
**audit log** and to a per-user search log (which powers recent/frequent).

## Performance & architecture

- **Backend** — `core/search.py` holds a provider registry (one per entity, each
  declaring its permission and query) plus the ranking, highlighting and fuzzy
  logic; the palette markup/JS live here too.
- **API** — `blueprints/search.py`: `GET /api/gsearch?q=`, `GET
  /api/gsearch/context`, `POST /api/gsearch/pin` (session-authed; 401 otherwise).
- **Frontend** — a single dependency-free palette injected into every page,
  styled with the app's CSS variables so it follows **dark/light mode** and is
  **mobile responsive** (full-screen on phones).
- **Speed** — every provider query is `LIMIT`-ed and the fuzzy candidate pool is
  capped; typical responses are tens of milliseconds, well under the 500 ms
  budget. Type-ahead is debounced (~140 ms) and stale responses are discarded.
- **Indexes** — the startup migration adds indexes on the hot search columns
  (patient MRN/phone/national-id, lab sample number, imaging modality, asset
  code/serial, plate, …) idempotently, so existing databases pick them up on
  first run.
- **New tables** — `SearchLog`, `PinnedRecord` (created automatically). No
  changes to existing tables.

## Honest limitations

- "Fuzzy" is a lightweight difflib pass on name fields, not a full search engine
  (Elasticsearch-style) — it handles everyday typos, not semantic search.
- Arabic support means Unicode-correct substring/among-tokens matching, not
  linguistic stemming or diacritic folding.
- GPS/barcode hardware isn't bundled; barcode scanners work because they behave
  as keyboards.

Tests: `tests/test_search.py` covers field searches (name/MRN/phone/national-id/
sample), highlighting, fuzzy, Arabic, permission gating, audit + search logging,
recent/frequent/pinned context, pin toggle, the sub-500 ms budget, auth (401),
and palette injection.
