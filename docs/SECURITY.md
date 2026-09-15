# Security Center (Phase 14, v8.0)

A consolidated security-posture dashboard for administrators. It surfaces the
protections the system already enforces and adds admin recovery actions. No new
tables.

## What was already in place (and this builds on)

The auth system already enforces:
- **TOTP two-factor** (authenticator app) per user.
- **Brute-force lockout** — an account is blocked after repeated failed logins.
- **Password policy** — minimum 8 characters, must contain a number, common
  passwords blocked.
- **Forced password change** for accounts still on the default password.
- **Login history** — every success/failure recorded with IP and time.

The Security Center puts all of this in one place.

## Dashboard

`/m/security` (Administration → Security Center). Permission `security` →
super_admin, it_admin.

**Posture KPIs**
- 2FA adoption (enabled / active users, with %)
- Accounts still on the default password
- Accounts locked out right now
- Failed logins in the last 24 hours
- Inactive accounts

**Active policy** — a plain-language summary of the live password, lockout, 2FA
and session-timeout settings.

**Failed logins (7 days)** — username, IP, time, note.

**Accounts & posture** — every account with its role, security badges (2FA / no
2FA / default pw / inactive / LOCKED) and last login.

## Admin recovery actions

Per account (super_admin / it_admin, or anyone with `users`):

- **Require password change** — forces a new password at next login.
- **Clear lockout** — removes the recent failed-login records so a wrongly
  locked-out user can sign in again.
- **Reset 2FA** — clears a lost/broken authenticator so the user re-enrols on
  next login.

Each action is written to the audit log.

## Notes

- No schema change — the dashboard reads existing users and login history, so it
  carries no upgrade risk.
- Lockout thresholds come from the same `LOGIN_MAX_FAILS` / `LOGIN_LOCK_MIN`
  settings the login screen uses, so the numbers shown match real behaviour.

Tests: `tests/test_security_center.py` covers the posture KPIs, lockout display,
the three recovery actions, and RBAC.
