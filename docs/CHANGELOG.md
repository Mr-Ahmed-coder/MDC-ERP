# MDC Diagnostic ERP — Changelog

Version numbers here match the **System Version** shown at **Admin → System Health**.

---

## 7.9 — Enterprise polish & Fixed Assets

**Fixed Assets Management (new module, Accounting → Fixed Assets)**
- Full lifecycle: purchase → activate (capitalisation entry) → automatic depreciation → maintenance → transfer → revaluation → disposal.
- Depreciation engine: Straight Line, Declining Balance, Units of Production; automatic accumulated depreciation, net book value, and remaining life.
- Automatic, balanced journal entries (Dr Depreciation Expense / Cr Accumulated Depreciation) using each category's configured accounts; capitalisation on activation; gain/loss on disposal; revaluation surplus/loss.
- 12 sub-menus (Dashboard, Asset Register, Purchase Assets, Categories, Depreciation Schedule, Depreciation Journal, Transfer, Maintenance, Disposal, Revaluation, Reports, Settings), 19 seeded categories, role-based access, and full audit trail.

**Workflow & usability**
- **Reset to Draft** now automatically reverses the invoice's live accounting (sales + payment) with a full reversal trail; books net to zero while the invoice is re-worked and are refreshed cleanly on re-confirmation (no double-counting). Administrator-only, reason-required, fully audited.
- **Next step** guidance across the patient → invoice → payment → laboratory/radiology → report journey; patient registration now opens the patient hub directly, cutting clicks.
- **Favorites** menu — pin any page to the top bar.
- Rich patient **activity timeline** and **related records** panel with live counts.
- Enhanced **global search** that opens matching records directly.
- Professional, plain-language **error messages** in place of technical errors.
- **Notification center** routing events (payments, reports, low stock, backups, referrals) to the right roles.
- **Digital signatures** and verification barcodes/QR on printed invoices, receipts, vouchers, and lab/radiology reports.
- Structured **radiology report** template (technique / findings / impression) with radiologist signature block.
- **System Health** dashboard: CPU, RAM, disk, database size & integrity, backup status, active users, failed logins, errors, and version.

**Infrastructure & production readiness**
- **Security hardening:** sliding **session timeout** (auto-logout on inactivity, `SESSION_TIMEOUT_MIN`) and **brute-force login lockout** (per-username, `LOGIN_MAX_FAILS` / `LOGIN_LOCK_MIN`). Password policy, CSRF protection, per-route permission checks, optional IP allow-list, and 2FA (TOTP) were already in place.
- **PostgreSQL support hardened:** first-run column migrations are now dialect-aware (SQLAlchemy inspector instead of SQLite `PRAGMA`), so the app initialises cleanly on PostgreSQL as well as SQLite. `gunicorn` and `psycopg2-binary` are in `requirements-prod.txt`.
- **SQLite → PostgreSQL migration script** (`scripts/migrate_to_postgres.py`): copies existing data row-by-row, builds the target schema from the models, refuses to overwrite a non-empty database, and resets PostgreSQL sequences.
- **Opt-in foreign-key enforcement** for SQLite via `SQLITE_FK=1` (default off for backward compatibility).

**Documentation**
- Added a full documentation set under `docs/`: Installation, User Manual, Administrator Manual, Backup & Restore, Deployment, and Integration/API notes.

**Compatibility**
- No existing features removed; full backward compatibility maintained. All automated tests passing.
