# Insurance (Phase 3, v8.0)

Full payer workflow, integrated with the existing billing and accounting:
companies, patient cards, coverage rules, pre-authorization, claims and payment
reconciliation.

## How it ties into billing

An invoice paid with the **Insurance** method already posts an *Insurance
Receivable* to account **1250** (Dr 1250 / Cr 1200 AR control). A **Claim**
tracks what the payer owes against that invoice. When the payer pays,
**Reconcile Payment** posts Dr Cash/Bank / Cr 1250, clearing the receivable — so
insurance debt lives in the general ledger, not just a side table.

## Claim lifecycle

```
Draft ──submit──► Submitted ──record response──► Approved / Partial / Rejected
                                                     │
                                              reconcile payment ──► Paid
```

- **Approved** = payer approved the full claimed amount.
- **Partial** = payer approved less than claimed (short-pay); the shortfall
  stays outstanding on account 1250 until written off or billed to the patient.
- **Rejected** = nothing approved; a reason is recorded and shown on the claim.

The Claims dashboard (`/m/insurance`) shows outstanding receivable from payers
and live counts per status, with one-tap filters — including a **Rejected**
view.

## Pre-authorization

Request approval before rendering a service (`/insurance/preauth`). Approving
generates a verification **auth code** (`PA-XXXXXX`) and records the decision
time; rejecting records a reason.

## Coverage

Two levels: each **insurer** carries a default coverage %, each **card** can
override it, and **Coverage Rules** (`/m/coverage`) set per-category coverage,
patient copay %, annual caps and exclusions. When a claim is seeded from an
invoice, the patient's card coverage % is applied to compute the claimed amount.

## New data

`Insurer`, `InsuranceCard`, `CoverageRule`, `PreAuth`, `Claim` — all new tables
(no changes to existing tables), so a fresh `flask init-db` or
`python scripts/upgrade_v8.py` creates them with no migration of existing data.

## Permissions

| Key | Default roles |
|-----|---------------|
| `insurance` (claims, pre-auth) | super_admin, accountant, reception, cashier, branch_manager |
| `insurers` | super_admin, accountant, branch_manager |
| `inscards` | super_admin, accountant, reception, cashier |
| `coverage` | super_admin, accountant, branch_manager |

## Launcher

App Launcher → **Insurance**: Claims · Insurance Companies · Insurance Cards ·
Coverage Rules (Pre-Auth is reachable from the Claims dashboard toolbar).

Tests: `tests/test_insurance.py` covers the full lifecycle including the
accounting posting that credits account 1250, rejection, pre-auth approval, and
an RBAC denial.
