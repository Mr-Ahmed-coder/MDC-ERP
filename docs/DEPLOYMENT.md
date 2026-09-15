# MDC Healthcare ERP — Production Deployment Guide

**Version 10.0 candidate**

This guide describes a migration-first deployment for the existing MDC Healthcare ERP. Production runs behind HTTPS, Gunicorn, and PostgreSQL. The WSGI import path is intentionally side-effect free: schema creation and upgrades must be completed explicitly before the application is started.

## Recommended topology

```text
Internet → HTTPS :443 → Nginx → Gunicorn → Flask → PostgreSQL
HTTP :80 → 301 redirect → HTTPS :443
```

Use PostgreSQL for multi-branch operations and concurrent writers. SQLite remains suitable for isolated development or a small single-site installation after its own backup and locking review.

## Required production secrets

| Variable | Requirement |
|---|---|
| `SECRET_KEY` | At least 32 random characters; used for Flask session/document signatures |
| `JWT_SECRET_KEY` | At least 32 random characters; required for API token configuration |
| `ENCRYPTION_KEY` | At least 32 random characters; required by production configuration |
| `DB_PASSWORD` | PostgreSQL password; required by Compose and production configuration |
| `INITIAL_ADMIN_PASSWORD` | Unique first-run password, at least 12 characters, rotated after first login |
| `BACKUP_ENCRYPTION_KEY` | Secret-manager key required by `deploy/backup.sh`; store separately from backups |
| `DATABASE_URL` | PostgreSQL URL, for example `postgresql://mdc:password@db:5432/mdc_erp` |

Production fails closed if the first four secrets are missing or too short. Never use `admin123`, `mdc_secret`, `change-this`, or any value copied from documentation examples.

## Clean installation and upgrade

Install dependencies, provision an empty PostgreSQL database, set the secret-manager environment, and run the authoritative migration chain:

```bash
pip install -r requirements-prod.txt
export FLASK_CONFIG=production
export DATABASE_URL='postgresql://mdc:password@db:5432/mdc_erp'
export SECRET_KEY='generated-by-secret-manager'
export JWT_SECRET_KEY='generated-by-secret-manager'
export ENCRYPTION_KEY='generated-by-secret-manager'
export DB_PASSWORD='provided-by-secret-manager'
export INITIAL_ADMIN_PASSWORD='provided-by-secret-manager'

flask --app 'mdc_erp:create_app()' db upgrade
flask --app 'mdc_erp:create_app()' init-db
gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app
```

The migration chain is versioned under `migrations/versions/`. The production WSGI entrypoint does not call `db.create_all()` and does not execute compatibility `ALTER TABLE` logic. If `flask init-db` is run before the migration has created the `setting` table, it fails with an explicit initialization error.

For an existing installation, take and verify a backup, run `flask db upgrade`, validate data counts and financial reconciliation, then perform the application smoke test before switching traffic.

## Docker Compose

The production stack is defined in `docker-compose.yml`. It requires all production secrets and sets secure cookies and the HTTPS URL scheme:

```bash
export SECRET_KEY='...'
export JWT_SECRET_KEY='...'
export ENCRYPTION_KEY='...'
export DB_PASSWORD='...'
docker compose up -d --build
```

Expose the application only through the reverse proxy. Do not publish the Gunicorn port directly to the public Internet. The database volume must be persistent, access-controlled, and included in the encrypted backup policy.

## HTTPS and Nginx

Use `deploy/nginx.conf` as the starting point. Replace the example hostname and certificate paths, obtain certificates through Certbot or an enterprise certificate authority, and validate the configuration with `nginx -t`. The configuration redirects port 80 to HTTPS, sets HSTS and proxy headers, and forwards `X-Forwarded-Proto: https`.

Secure cookies, `HttpOnly`, `SameSite`, CSP, HSTS, `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` must be verified through the real proxy rather than assumed from local development responses.

## PostgreSQL and concurrency

Run the reproducible test environment with:

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

The test runner installs development dependencies, initializes the test database, executes pytest, and generates JUnit and coverage reports. The final acceptance run must also include PostgreSQL concurrency tests for duplicate payments, billable-source claiming, branch isolation, and period locking.

## Backup and recovery

Use `deploy/backup.sh` with `BACKUP_ENCRYPTION_KEY`. It creates an encrypted, checksum-recorded backup and validates the compressed payload before reporting success. Use `deploy/restore.sh` for an isolated restore. Follow [BACKUP_RESTORE.md](BACKUP_RESTORE.md) and record restore timing, record validation, migration state, and application smoke-test results.

## Production acceptance checklist

| Gate | Evidence required |
|---|---|
| Secrets | Secret-manager values present; fail-fast test passes |
| Migration | Empty PostgreSQL `db upgrade` reaches the Alembic head |
| Upgrade | Prior production-like database upgrades without data loss |
| Administrator | First administrator created with the configured unique password |
| HTTPS | Port 80 redirects; secure cookie/HSTS/CSP headers verified through Nginx |
| RBAC | Role and branch negative tests pass for UI, API, reports, exports, and direct URLs |
| Accounting | Every posted journal balances; reversal and fiscal locks pass |
| Inventory | Batch, expiry, FEFO, negative-stock, and source-document tests pass |
| Clinical | Verification, approval, locking, amendment, and critical-result tests pass |
| API | Authentication, authorization, validation, rate-limit, IDOR, and audit tests pass |
| Backup | Encrypted backup, checksum verification, isolated restore, and data validation pass |
| Performance | PostgreSQL query, concurrency, search, dashboard, and report thresholds pass |
| UX | Reception, doctor, laboratory, radiology, cashier, storekeeper, and accountant UAT passes |

> Do not label the system **10/10 Production Ready** until every critical gate has recorded evidence in the release report.
