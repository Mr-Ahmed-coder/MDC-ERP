# MDC Healthcare ERP — Backup and Restore Guide

**Version 10.0 candidate**

A backup is not considered protective until it has been decrypted, validated, restored into an isolated environment, and checked by the application. Production backups must be encrypted, integrity-checked, retained off-site, and periodically restore-tested.

## Protected data

| Data | PostgreSQL deployment | SQLite deployment |
|---|---|---|
| Clinical, financial, user, audit, inventory, and configuration records | PostgreSQL database dump | `DATA_DIR/erp.db` |
| Uploaded documents and imaging files | Persistent upload/PACS storage | `DATA_DIR/uploads/` and configured imaging storage |
| Deployment secrets | Root-only secret manager or environment file | Root-only environment file; never place secrets in the archive |

## Automated encrypted backup

The production utility is `deploy/backup.sh`. It requires `BACKUP_ENCRYPTION_KEY` and refuses to produce an unencrypted backup. It creates a gzip-compressed database backup, encrypts it with OpenSSL AES-256-CBC using PBKDF2 and a random salt, validates the decrypted gzip stream, writes a SHA-256 sidecar, and removes files older than `BACKUP_RETENTION_DAYS`.

Example scheduled invocation:

```bash
BACKUP_ENCRYPTION_KEY='provided-by-secret-manager' \
DATABASE_URL='postgresql://mdc:password@db:5432/mdc_erp' \
BACKUP_DIR=/var/backups/mdc \
/opt/mdc-erp/deploy/backup.sh
```

The backup key must be stored separately from the backup destination. Use a root-only environment file and an off-site, access-controlled copy. The example key above is illustrative only and must not be reused.

## Restore procedure

The `deploy/restore.sh` utility verifies the sidecar checksum when present, decrypts the backup, validates gzip integrity, and restores either PostgreSQL or SQLite data. Restore into a disposable staging database or data directory first.

```bash
BACKUP_ENCRYPTION_KEY='provided-by-secret-manager' \
DATABASE_URL='postgresql://mdc:password@staging-db:5432/mdc_erp' \
./deploy/restore.sh /var/backups/mdc/mdc-postgres-YYYY-MM-DDTHHMMSSZ.gz.enc
```

For SQLite:

```bash
BACKUP_ENCRYPTION_KEY='provided-by-secret-manager' \
SQLITE_DB_PATH=/srv/mdc-staging/erp.db \
./deploy/restore.sh /var/backups/mdc/mdc-sqlite-YYYY-MM-DDTHHMMSSZ.gz.enc
```

After PostgreSQL restoration, run the current migration command against the restored database, verify the Alembic head, run `flask --app wsgi audit-finance`, and complete a clinical/financial smoke test. Do not overwrite the original production database until validation has passed.

## Restore drill and acceptance evidence

Before go-live and at least quarterly thereafter, take a production-like backup, destroy an isolated test database, restore it, run migrations if required, validate record counts and representative patient/invoice/result/inventory records, log in, and exercise the health, finance, clinical, and branch-isolation checks. Record the start/end times to establish **RPO** and **RTO**.

| Control | Minimum acceptance |
|---|---|
| Daily backup | One successful encrypted backup every 24 hours |
| Weekly backup | A separate retained weekly copy |
| Retention | At least 30 days by default, with longer financial retention where policy requires |
| Encryption | Backup cannot be opened without the secret-manager key |
| Integrity | SHA-256 sidecar and successful decrypt/gzip validation |
| Restore | Successful isolated restore with application validation |
| Off-site protection | At least one copy outside the production host/volume |
| Alerting | Failed backup or stale-backup alert reaches the responsible administrator |

> Production certification must not claim backup protection until a real restore drill has passed and its evidence has been retained.
