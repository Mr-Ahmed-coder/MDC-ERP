# MDC Diagnostic ERP — Installation Guide

**Version 10.0 candidate** · Applies to Windows, Linux, macOS, and Docker.

---

## 1. System requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.10 | 3.12 |
| RAM | 1 GB | 4 GB |
| Disk | 2 GB free | 20 GB free (grows with backups & documents) |
| OS | Windows 10 / Ubuntu 20.04 / macOS 12 | Ubuntu 22.04 LTS |
| Browser (client) | Any modern browser | Chrome / Edge / Firefox (latest) |

No external database server is required for a standard single-site installation — the system ships with SQLite. For multi-site or high-concurrency deployments, see [DEPLOYMENT.md](DEPLOYMENT.md) for PostgreSQL.

---

## 2. Quick start (development / evaluation)

```bash
# 1. Unzip the release package and enter the folder
cd MDC-Diagnostic-ERP

# 2. Create an isolated Python environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the server (loads demo data on first run)
python run.py --demo
```

Open **http://127.0.0.1:5000** and sign in with:

```
Username: admin
Password: set through the initialization environment
```

You will be required to change this password on first login.

### run.py flags

| Flag | Effect |
|------|--------|
| `--demo` | Seed demonstration data (patients, services, accounts) |
| `--online` | Listen on `0.0.0.0` so other machines on the LAN can connect |
| `--debug` | Flask debug mode (development only — never in production) |

The port can be overridden with the `PORT` environment variable (default `5000`).

`python run.py` also loads a local `.env` automatically (via python-dotenv) — handy for setting `SECRET_KEY`, `DATABASE_URL`, etc. in development. A ready-made `.env` ships with SQLite defaults; it never overrides variables already set in your shell.

### One-command development with PostgreSQL

To develop against PostgreSQL with a single command (app + database, live code reload, demo data):

```bash
docker compose -f docker-compose.dev.yml up --build
# Open http://localhost:5000   (admin / password set during initialization)
```

The source folder is mounted, so edits reload automatically. PostgreSQL is also published on `localhost:5432`, so you can instead run the app on the host (`python run.py`) against the same database by uncommenting the `DATABASE_URL` line in `.env`. Reset the dev database at any time with `docker compose -f docker-compose.dev.yml down -v`.

---

## 3. Production installation

For a real clinic, do **not** use `run.py` (the Flask development server). Use a production WSGI server instead.

**Linux / Docker** — Gunicorn:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app
```

**Windows** — Waitress (bundled in requirements):

```bash
waitress-serve --port=8000 wsgi:app
```

Then place Nginx / IIS / Caddy in front for TLS. Full instructions, including Docker Compose and PostgreSQL, are in [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 4. Data location

| Item | Default path | Override |
|------|--------------|----------|
| Database | `./data/erp.db` (SQLite) | `DATA_DIR` env var |
| Automatic backups | `./data/backups/` | `DATA_DIR` env var |
| Uploaded documents | `./data/uploads/` | `DATA_DIR` env var |
| Application log | `mdc_erp.log` | — |

Set `DATA_DIR=/var/lib/mdc-erp` (or any persistent path) to keep data outside the application folder — essential so upgrades never touch clinic data.

---

## 5. First-run checklist

1. Sign in as `admin` and set a strong password.
2. Open **Settings → Organization** and enter the clinic name, address, logo, and currency.
3. Create real user accounts under **Admin → Users** and assign roles (see [ADMIN_MANUAL.md](ADMIN_MANUAL.md)).
4. Review the **Chart of Accounts** and opening balances under **Accounting**.
5. Configure automatic backups (**Admin → Backup**) — see [BACKUP_RESTORE.md](BACKUP_RESTORE.md).
6. If you loaded `--demo`, clear demo records before going live, or start a fresh database without the `--demo` flag.

---

## 6. Upgrading

1. Back up the database first (**Admin → Backup → Backup now**).
2. Stop the server.
3. Replace the application files with the new release — **keep your `data/` folder**.
4. Restart. Schema migrations run automatically at startup (idempotent — safe to run repeatedly).

Version numbers are shown at **Admin → System Health → System Version** and must match the release you deployed.

---

## 7. Troubleshooting

| Symptom | Resolution |
|---------|------------|
| `ModuleNotFoundError` | Activate the virtual environment and re-run `pip install -r requirements.txt`. |
| Port already in use | Set a different `PORT`, e.g. `PORT=5001 python run.py`. |
| Cannot log in after upgrade | Confirm you kept the original `data/` folder; the database holds all accounts. |
| Blank page / assets missing | Hard-refresh the browser (Ctrl+F5); confirm the server started without errors in `mdc_erp.log`. |

For deeper diagnostics, open **Admin → System Health** for live CPU, memory, database, backup, and error status.
