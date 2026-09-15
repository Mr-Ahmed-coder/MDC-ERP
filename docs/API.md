# MDC Diagnostic ERP — Integration & API Notes

**Version 10.0 candidate**

MDC Diagnostic ERP is primarily a server-rendered web application, not a headless API product. This document describes the integration surfaces that **do** exist and how to work with them safely. It is deliberately honest about what is and is not available, so integrators are not misled.

---

## 1. Authentication model

All routes are protected by session-based authentication (login cookie) and role-based permission checks. There is **no separate API token system** in this release. Any programmatic access must:

1. Establish a session by posting valid credentials to the login route (respecting the CSRF token embedded in the login form), then
2. Reuse the returned session cookie on subsequent requests.

Because every state-changing form is CSRF-protected, automated clients must read the `_csrf` hidden field from the relevant page and include it in POST requests.

---

## 2. Data export endpoints (read)

Every list view exposes a CSV export that returns exactly the filtered/sorted rows on screen:

```
GET /m/<module>/export.csv?<same query params as the list>
```

Financial reports additionally export to Excel and PDF from their own screens (trial balance, general ledger, AR/AP, budgets — powered by `openpyxl` and `reportlab`). The Fixed Assets module exports its register and reports as CSV from **Fixed Assets → Reports**.

These export URLs are the supported, stable way to pull data out of the system for external analysis.

---

## 3. URL conventions (for deep-linking)

The application uses predictable, human-readable URLs, which are convenient for bookmarking and deep-linking from other internal tools:

| Pattern | Opens |
|---------|-------|
| `/patient/<id>` | Patient hub |
| `/invoice/<id>` | Invoice |
| `/m/<module>` | A module list (e.g. `/m/patients`, `/m/lab`) |
| `/fa/asset/<id>` | Fixed asset detail |
| `/fa/dashboard` | Fixed Assets dashboard |

Global search also accepts document numbers (INV-, RCT-, LAB-, RAD-) and opens the record directly, which makes it easy to jump from an external reference to the right screen.

---

## 4. Embedding Claude-powered features (in-app)

Where AI-assisted features are used inside the product, they call Anthropic's Messages API server-side. Integrators extending the system should keep any API keys server-side (never in the browser) and follow Anthropic's current API documentation for models, rate limits, and tool use.

---

## 5. Extending the system

The application is a modular Flask project:

- **Blueprints** under `mdc_erp/blueprints/` register feature areas.
- **Models** in `mdc_erp/models.py` (SQLAlchemy).
- **Accounting posting** via `post_journal(date, ref, memo, lines)` in `mdc_erp/core/posting.py` — the single, balanced, idempotent way to write to the ledger. Always post through this helper rather than writing journal rows directly.
- **Permissions** in `mdc_erp/core/security.py` (`PERMS`, `can(mod)`), enforced per route.
- **Audit** via `log(action, action_type, entity, old, new, reason)` — call it from any new action so the audit trail stays complete.

New modules should follow the existing patterns (blueprint + models + permission entry + navigation entry) to inherit the shared UI shell, breadcrumbs, search, and audit behaviour automatically.

---

## 6. What is *not* provided

To set expectations clearly:

- No public REST/JSON API with bearer tokens.
- No webhooks.
- No third-party OAuth provider.

If your deployment requires these, they can be added as a dedicated blueprint on top of the existing models — the data layer and posting/audit helpers are ready to support it.
