# MDC Diagnostic ERP — Documentation

**Version 10.0 candidate**

Complete documentation for installing, using, administering, and deploying MDC Diagnostic ERP.

| Guide | For | Contents |
|-------|-----|----------|
| [INSTALLATION.md](INSTALLATION.md) | IT / installers | Requirements, quick start, production install, first-run checklist, upgrading. |
| [USER_MANUAL.md](USER_MANUAL.md) | Reception, cashier, lab, radiology, clinical | Navigation, the core workflow, patient hub, lists, printing, notifications. |
| [ADMIN_MANUAL.md](ADMIN_MANUAL.md) | Administrators, finance managers | Roles, accounting setup, workflow locking, fixed assets, audit, go-live checklist. |
| [BACKUP_RESTORE.md](BACKUP_RESTORE.md) | Administrators | Automatic & manual backups, restore procedure, restore drill, retention. |
| [DEPLOYMENT.md](DEPLOYMENT.md) | IT / DevOps | Gunicorn, Waitress, reverse proxy/TLS, Docker, PostgreSQL, hardening. |
| [API.md](API.md) | Integrators / developers | Auth model, CSV/Excel/PDF exports, URL conventions, extending the system. |
| [CHANGELOG.md](CHANGELOG.md) | Everyone | What changed in each release. |

The top-level [`../README.md`](../README.md) remains the technical/architecture reference for the codebase.

---

**Default login (change immediately):** `admin` / `INITIAL_ADMIN_PASSWORD`
**Development server:** `python run.py --demo` → http://127.0.0.1:5000
**Production:** `gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app` behind HTTPS.
