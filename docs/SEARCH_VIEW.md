# Module Search View (Phase 17, v8.0)

An Odoo-style search view built into the **generic list renderer**, so every
registry-backed module gets the same search bar, filters, group-by, sorting,
favorites, advanced builder and history at once — Patients, Suppliers, Doctors,
Employees, Assets, Vehicles, Insurers, Wards/Beds, Theatres, Machines, Supplies
and every other `/m/<module>` list.

## Search bar

- A search box at the top of the list searches the module's configured fields.
- **Instant** — typing auto-submits after a short debounce.
- **Highlighted** — matching text in the rows is wrapped in `<mark>`.
- Partial words match (substring), and the global palette (Ctrl+K) adds fuzzy
  typo tolerance across modules.
- Barcode/QR scanners type into the box like a keyboard, so scanning a code and
  pressing Enter finds the record.

## Quick-filter chips

One-click chips appear above the list, adapting to the module:

- **Dates** (when the list has a date field): Today, This Week, This Month, This
  Year — plus the existing All-dates / Yesterday / from–to range selector.
- **Active / Inactive** (when the model has an `active` flag).
- **Status values** actually present in the data (e.g. Draft, Pending,
  Confirmed, Completed, Cancelled) when the model has a `status` column.
- **Assigned to me** (when the model records a creator/owner/nurse/attending).

## Group By & Sorting

- Group by any status/category/department/branch/date-month field, with a group
  summary that totals counts and money columns; click a group to drill in.
- Sort by any column, ascending or descending.

(Both already existed on the list and remain available in the toolbar.)

## Favorites (saved searches)

Open **⭐ Favorites** to:

- **Save current** search — captures the whole view (text, filters, quick chips,
  advanced conditions, group-by and sort) as a named favorite.
- **Pin** (★) a favorite to the top.
- **Set as default** (⚑) — opening the module with no arguments applies it
  automatically.
- **Rename** (✎) and **Delete** (✕).
- **Share with team** (👥) — a shared favorite is visible to everyone using that
  module; managing it (pin/default/share/rename/delete) is restricted to its
  owner.

## Advanced search builder

Open **⚙ Advanced** to build conditions row by row: pick a **field**, an
**operator**, and a **value**, and combine rows with **Match ALL (AND)** or
**Match ANY (OR)**. Operators: contains, does not contain, =, ≠, starts with,
ends with, >, <, between, is empty, is not empty, is true, is false — covering
text, numeric ranges, dates and boolean fields. The built conditions serialize
into the URL (`?adv=…&join=…`), so an advanced search is shareable and can be
saved as a favorite.

## History

- **Recent** searches for the module show as chips under the filters.
- Every search is written to the audit log and a per-user, per-module search log.

## UX & technical

- **Mobile responsive**, **dark/light** (inherits the app theme), keyboard-
  friendly.
- **Fast** — every query is `LIMIT`/`OFFSET` paginated; searchable columns are
  indexed (patient MRN/phone/national-id, sample numbers, etc. from Phase 16).
- **Permissions** — the list is gated by the module's permission and every query
  is branch-scoped, so users only see records they may access.
- **New table** `SavedSearch`; new column `search_log.module` (added by the
  startup migration). No other schema changes.

## Honest scope

This search view is applied uniformly to the **registry-backed** list views
(the large majority of modules). Bespoke hand-built screens (the lab and imaging
worklists, billing, and the dashboards) keep their own purpose-built controls;
they can adopt the same component incrementally — the pieces here (advanced
builder, favorites model, quick chips, highlight helper) are written to be
reused, not re-implemented. "Instant" search is a debounced form submit, not a
separate XHR; nested parenthetical grouping in the advanced builder is a
practical AND/OR-across-conditions subset rather than arbitrary depth.

Tests: `tests/test_searchview.py` covers highlight, quick chips, the advanced
operators (contains/starts/eq/OR), the full favorites lifecycle
(save/default/pin/rename/delete), owner-gating, and recent-search recording.

## Custom views wired (Phase 17b)

The reusable `search_view(mod, model, query, search_cols=, date_field=)` helper
(in `blueprints/modules.py`, with `hl()` for highlighting) lets any bespoke page
adopt the full search view in ~3 lines. Now wired into these hand-built views:

- **Patient Invoices** (`invoices`) — search by invoice #, guarantor, status.
- **Doctor Requests / Referrals** (`referrals`) — search by patient, doctor,
  tests, status, hospital.
- **Laboratory requests** (`lab`) and **Imaging requests** (`radiology`).
- **Fixed Assets register** (`fa_register`) — search by code, name, category,
  serial, department, location, status; advanced filter e.g. department = X.

Each gets the search bar (instant + highlight), quick-filter chips, advanced
builder, favorites (save/pin/default/rename/delete/share) and recent searches,
with per-module audit + search logging. The favorite routes accept any module
the user can access (`can(mod)`), not just registry modules.

To wire another custom department list, inside its view function:

    from .modules import search_view, hl
    q = branch_scope(Model.query, Model)
    q, sq, filterbar = search_view('modkey', Model, q,
                                   search_cols=['name', 'code', 'status'],
                                   date_field='date')
    # render rows from q; wrap text cells with hl(cell, sq);
    # pass filterbar to list_page.html (or prepend it to the panel body).

## Laboratory Tests catalog + role-based price hiding

A read-only **Laboratory Tests** catalog (`/m/labtests`, Laboratory launcher)
lists active tests as Name / Code / Test Type / Price — the MDC equivalent of
Odoo's "Tests" list. Permission `labtests` (super_admin, lab_tech,
lab_supervisor, doctor, reception, accountant, radiologist).

**Price is hidden from lab technicians and lab supervisors.** For those roles
the Price column, its values, and any price field in the search/advanced panel
are all removed (the view falls back to a plain search box), and a "Prices are
hidden for your role" note is shown. Price-privileged roles keep the column.

The same is enforced generically: `register(..., hide_columns={'Price':
['lab_tech','lab_supervisor'], 'Cost':[...]})` on the Service Catalog hides
those columns for those roles anywhere the registry list renders them. Any
module can hide any column from any role the same way.
