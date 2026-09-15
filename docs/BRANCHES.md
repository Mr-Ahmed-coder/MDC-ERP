# Multi-branch Hub & Focus (Phase 15, v8.0)

Adds a **branch focus switcher** and a per-branch overview on top of the
existing multi-branch foundation. No new tables.

## What already existed

The ERP was already multi-branch aware: a `Branch` registry, a `branch_id` on
branch-specific records, and `branch_scope`, which limits each user to their own
branch — while cross-branch roles (super_admin, it_admin, auditor) see every
branch merged together. What was missing was a way for those admins to **focus
on one branch at a time**.

## Branch focus

An administrator can now narrow the **entire system** to a single branch:

- `/m/branchhub` (Administration → Branch Hub & Focus) lists every branch with
  live counts — patients, staff, current inpatients, active ED, and cash
  collected — and a **Focus** button on each.
- Choosing **Focus** sets that branch as the active view; a banner shows which
  branch you're viewing. **View all branches** clears it.
- The focus is honoured everywhere: because it flows through the core
  `branch_scope`, every list, dashboard, and detail page in the system shows
  just that branch while the focus is on — exactly as a branch user would see
  it.

The focus lives in the session, so it lasts for the sign-in and never leaks
across users.

## Who can switch

Only cross-branch roles (super_admin, it_admin, auditor) can change focus;
the switch routes return 403 for anyone scoped to a single branch. Ordinary
branch users are unaffected — they always see their own branch and ignore any
focus value.

## Safety

- **No schema change** and **no change to default behaviour**: with no focus
  selected, cross-branch users still see all branches exactly as before, so
  existing installs and every existing screen behave identically until an admin
  deliberately picks a branch.
- Branch-less/shared reference rows (e.g. patients, price lists) remain visible
  under any focus, so focusing never hides shared data.

Permissions: `branchhub` → super_admin, it_admin, auditor, branch_manager (the
focus-switch routes additionally require a cross-branch role).

Tests: `tests/test_branchhub.py` proves focus narrows `branch_scope`, that a
branch-scoped user ignores focus, and that the hub and switch routes work with
RBAC.
