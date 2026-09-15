# Document Action Dialog — "What do you want to do?" (v8.0)

An Odoo-style dialog offering **Print / Download / Open** for generated
documents, matching the familiar Odoo prompt.

## How it works

A single reusable modal is injected into every page (`core/docactions.py`,
rendered via `page()` into `base.html`). Any button opens it:

    <button onclick="MDCDoc.open({print:'/invoice/1/print?auto=1',
                                  download:'/invoice/1/pdf',
                                  open:'/invoice/1/print',
                                  title:'Invoice INV-0001'})">🖨 Print</button>

- **Print** — opens the print view with `?auto=1`, which triggers the browser
  print dialog on load (works for every printable document, via the shared
  `printable()` helper).
- **Download** — downloads the server-generated PDF (falls back to the print
  view where server PDF isn't available).
- **Open** — opens the document in a new tab to view.

Any action with no URL is hidden automatically. The dialog follows dark/light
mode (app CSS variables) and is mobile-responsive (full-screen on phones).
Esc or Close dismisses it.

## Wired so far

- **Patient Invoices** — both the toolbar and header **Print** buttons open the
  dialog.

## Extending to other documents

Point any Print button at `MDCDoc.open({...})` with that document's print, PDF
and open URLs — receipts, lab results, imaging reports and statements can all
use the same dialog. Because auto-print lives in the shared `printable()`
helper, `?auto=1` already works for every document that renders through it.

## Applied to ALL print areas (global interceptor)

Rather than editing every Print button, the dialog is applied everywhere by a
single global click interceptor (in `core/docactions.py`, injected on every
page). Any click on a printable-document link — paths containing `/print`,
`/receipt/`, `/card`, `/label`, or `/statement` — opens the Print / Download /
Open dialog instead of navigating directly:

- **Print** → the document with `?auto=1` (browser print dialog opens on load).
- **Download** → a real PDF when the link provides `data-pdf` (e.g. invoices);
  otherwise the print view, where the browser's *Save as PDF* is available.
- **Open** → the document in a new tab.

This covers invoices, receipts, lab results, imaging reports, patient cards,
cash-close and daily-transaction prints, asset cards, statements and labels —
every print area at once. Modifier-clicks (Ctrl/Cmd/middle-click) still open the
document directly in a new tab, and a link can opt out with `data-nodoc`.
Because auto-print lives in the shared `printable()` helper, `?auto=1` works for
every document rendered through it.
