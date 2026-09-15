# Development with PostgreSQL — Step-by-Step Guide
### Hage tallaabo-tallaabo ah · MDC Diagnostic ERP

This guide sets up a full **development** environment (app + PostgreSQL) so you can
start coding against Postgres. Hage kani wuxuu kuu dejinayaa deegaan development oo
buuxa (app + PostgreSQL).

---

## Before you start · Ka hor intaadan bilaabin

You need **one** of these installed:
- **Docker Desktop** (recommended / lagula talinayo) — for the one-command path, OR
- **Python 3.10+** + a **PostgreSQL** server — for the host path.

Check / hubi:
```bash
docker --version
python --version
```

---

## PATH A — One command with Docker  ·  Hal amar (lagula talinayo)

Everything (app + database) runs in Docker. Wax kastaa Docker ayuu ku shaqeeyaa.

### Step 1 — Open a terminal in the project folder
Fur terminal-ka galinterka MDC-Diagnostic-ERP.
```bash
cd MDC-Diagnostic-ERP
```

### Step 2 — Start the stack
Kici stack-ga (marka ugu horreysa way qaadan doontaa daqiiqado image-yada la soo dejinayo).
```bash
docker compose -f docker-compose.dev.yml up --build
```
This starts:
- `db` — PostgreSQL 16 (port 5432)
- `erp-dev` — the app in dev mode (port 5000, demo data, live reload)

### Step 3 — Open the app
Fur browser-ka:
```
http://localhost:5000
```
Login / gal:  **admin  /  password set during initialization**  (isla markiiba beddel).

### Step 4 — Edit code live
Wax ka bedel fayl kasta oo `mdc_erp/` ku jira → kaydso → app-ku si toos ah ayuu u
reload-gareeyaa (Flask debug reloader). Ma jirto dib-u-kicin gacanta ah.

### Step 5 — Stop / Reset
```bash
# Jooji (xogtu way sii jiraysaa) — stop, keep data
docker compose -f docker-compose.dev.yml down

# Nadiifi database-ka gebi ahaan — wipe the database
docker compose -f docker-compose.dev.yml down -v
```

✅ **Done.** You are developing against PostgreSQL. Waad ku shaqaynaysaa Postgres.

---

## PATH B — App on your machine, Postgres in Docker
### Habka labaad — app-ka host-ka, Postgres Docker-ka

Use this for a faster debugger / native Python. Ku wanaagsan debugger degdeg ah.

### Step 1 — Start only the database
Kici database-ka kaliya:
```bash
docker compose -f docker-compose.dev.yml up -d db
```

### Step 2 — Install Python dependencies
Ku rakib shayada Python (mar keliya):
```bash
python -m venv venv
source venv/bin/activate        # Windows:  venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3 — Point the app at Postgres
Fur faylka **`.env`**, kadibna **uncomment** (ka saar `#`) sadarkan:
```
DATABASE_URL=postgresql://mdc:mdc_dev@localhost:5432/mdc_erp
```

### Step 4 — Run the app
Kici app-ka:
```bash
python run.py --demo
```
`.env` si toos ah ayaa loo akhriyaa. Fur **http://127.0.0.1:5000**.

### Step 5 — Verify it is really using Postgres
Xaqiiji inuu dhab ahaan Postgres isticmaalayo:
```bash
python -c "from mdc_erp import create_app; from mdc_erp.extensions import db; \
app=create_app(); ctx=app.app_context(); ctx.push(); \
print('dialect:', db.engine.dialect.name)"
```
Waa inuu soo saaraa:  `dialect: postgresql`

---

## Bring existing SQLite data across (optional)
### Keen xogtii SQLite hore (ikhtiyaari)

If you already have data in `data/erp.db` and want it in Postgres:
```bash
export DATABASE_URL=postgresql://mdc:mdc_dev@localhost:5432/mdc_erp
python scripts/migrate_to_postgres.py --sqlite data/erp.db
```
The script copies rows only, refuses to overwrite a non-empty database, and resets
Postgres sequences. Marka hore staging ku tijaabi.

---

## Troubleshooting · Xallinta cilladaha

| Problem · Dhibaato | Fix · Xal |
|--------------------|-----------|
| Port 5000 or 5432 already in use | Change the left number in `docker-compose.dev.yml` ports, e.g. `5001:5000`. |
| `could not connect to server` | Wait a few seconds — Postgres takes a moment to become healthy on first start. |
| App uses SQLite, not Postgres | In Path B, confirm the `DATABASE_URL` line in `.env` is **uncommented**. |
| `psycopg` install error | Ensure Python 3.10+ and run `pip install --upgrade pip` first. |
| Changes not reloading (Path A) | Confirm the folder is mounted; on some systems Docker file-watching needs polling. |

---

## Quick reference · Tixraac degdeg ah

```bash
# Full dev stack (app + db)          → hal amar
docker compose -f docker-compose.dev.yml up --build

# Database only                      → app runs on host
docker compose -f docker-compose.dev.yml up -d db
python run.py --demo

# Stop                               → keep data
docker compose -f docker-compose.dev.yml down

# Reset database                     → wipe
docker compose -f docker-compose.dev.yml down -v
```

Default login for demo data:  **admin / password set during initialization**  — change it immediately.
