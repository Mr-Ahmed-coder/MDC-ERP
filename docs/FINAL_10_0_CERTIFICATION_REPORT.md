# MDC Healthcare ERP — Final 10.0 Certification Report

**Assessment date:** 15 August 2026  
**Candidate:** MDC Diagnostic ERP 9.2→10.0 hardening release  
**Assessment method:** Existing architecture was preserved; high-impact hardening was applied and verified through local regression, static analysis, migration execution, and backup/restore testing.

## Executive result

The current release is a **10/10 candidate for the verified sandbox scope**, but it is **not yet certified 10/10 Production Ready** because PostgreSQL, Docker, HTTPS proxy, concurrency, real branch-isolation, and production backup/restore evidence cannot be established in this sandbox alone.

> The system is certified only when the deployment acceptance tests pass in the target production-like environment. Feature breadth is not a substitute for evidence.

## Changes implemented

| Area | Implementation |
|---|---|
| Database architecture | Added `0000_initial_schema` as the authoritative complete metadata baseline, chained `0001_financial_integrity` and `0002_record_lifecycle`, repaired Alembic configuration/model loading, and made later index creation idempotent. |
| Production startup | Removed schema initialization from `wsgi.py`; production bootstrap now requires a migrated `setting` table and refuses to run against an uninitialized database. |
| RBAC | Defined all roles referenced by the central permission registry, including `nurse` and `lab_supervisor`; added orphan-role validation and derived role-permission indexing. |
| Secrets | Production fails closed unless `SECRET_KEY`, `JWT_SECRET_KEY`, `DB_PASSWORD`, and `ENCRYPTION_KEY` are present and strong. |
| HTTPS | Added CSP and production HSTS; hardened Nginx with HTTP→HTTPS redirect, TLS configuration, proxy headers, and security headers. |
| Backup/recovery | Replaced unverified backup copying with encrypted, checksum-recorded, decrypt-and-gzip-validated backups; added guarded PostgreSQL/SQLite restore utility. |
| Test orchestration | Updated the PostgreSQL test Compose workflow to install dependencies, run Alembic upgrade, initialize test data, execute pytest, and generate JUnit and coverage reports; declared DICOM support as a development dependency. |
| Test fixtures | Added the auditor demo account so accounting read-only acceptance is exercised rather than skipped. | 
| Documentation | Updated deployment and backup guides and retained the complete 9.2→10.0 specification and gap matrix. |

## Verification results

| Check | Result |
|---|---:|
| Python compilation | Passed |
| Ruff lint | Passed |
| Local regression suite | **256 passed** |
| Skipped tests | **0** |
| Warnings | 11 existing warnings, with no test failures |
| Alembic clean database upgrade | Passed through `0002_record_lifecycle` |
| Encrypted SQLite backup/restore round trip | Passed |
| Production fallback scan | No insecure production Compose fallback found; development-only `COOKIE_SECURE=0` remains intentionally scoped to `docker-compose.dev.yml` |

## Certification gates still requiring target infrastructure

| Gate | Required evidence |
|---|---|
| PostgreSQL | Empty database migration, previous-version upgrade, rollback review, and data-loss validation |
| Docker | `docker compose -f docker-compose.test.yml up --build --abort-on-container-exit` completes with PostgreSQL and coverage artifacts |
| HTTPS | Real Nginx/TLS deployment proves redirect, secure cookie, HSTS, CSP, and proxy behavior |
| Concurrency | Concurrent payment idempotency, billable-source claiming, branch access, and fiscal-period lock tests |
| Branch isolation | Branch A cannot read or modify Branch B through UI, direct URLs, APIs, searches, reports, or exports |
| Clinical safety | Full locked-result, amendment, and critical-result notification acceptance workflow |
| Inventory | FEFO, expiry rejection, negative-stock protection, CT-contrast deduction, and accounting linkage |
| Backup/restore | Production-like encrypted restore with record validation and measured RPO/RTO |
| Performance | PostgreSQL query, N+1, large-report, search, dashboard, and API benchmark results |
| UAT | Reception, doctor, laboratory, radiology, cashier, storekeeper, and accountant daily-workflow sign-off |

## Final readiness statement

The codebase has reached a materially stronger production candidate with a working migration chain, fail-closed production configuration, centralized RBAC consistency validation, encrypted backup round-trip validation, and a passing zero-skip local regression suite. It must remain labeled **10/10 candidate** rather than **10/10 Production Ready** until the environment-dependent gates above are executed and recorded.
