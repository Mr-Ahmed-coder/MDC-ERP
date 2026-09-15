# Smart Queue (Phase 5, v8.0)

A token-based queue with priority/emergency handling, public lobby & room
displays with voice announcements, and analytics. Built on the existing
`QueueTicket` model and kept **separate from** the appointment-based Reception
Queue, which is unchanged.

## Token generation & priority

Issue a token (`/tokenq/issue`) for a walk-in (name) or a registered patient,
choosing a **department** (Consultation / Laboratory / Radiology / Pharmacy /
Cashier) and a **priority**:

- **Emergency** — served before everyone.
- **Priority** — elderly / disabled, served before Normal.
- **Normal** — first-come, first-served.

The waiting list always sorts Emergency → Priority → Normal, then by number.
Tokens number per day + department (e.g. `C-001`, `L-001`).

## Staff console

`/m/tokenq` shows live counts (waiting / being served / served / emergencies),
per-department **Call next** buttons, and the full token list. Calling a token
sets its room/counter, timestamps it, notifies reception & doctors, and pushes
it to the displays. Actions: Call, Recall, Done, Cancel.

## Public displays (no login)

- **Lobby board** — `/display` : full-screen dark board showing every token
  currently being served (big code + destination room) and the waiting list,
  auto-refreshing every 4 seconds.
- **Room / department board** — `/display/<room>` : same board filtered to one
  room or department (e.g. a screen outside a consulting room).
- **Voice announcement** — the board speaks *"Token C-005, please proceed to
  Room 2"* when a new token is called, using the browser's speech synthesis.
  Browsers block audio until interaction, so the board has a one-tap **Enable
  sound** button (press once per screen).

These pages need no login — put them on lobby/room screens. They show token
codes and rooms only (no clinical detail).

## Analytics

`/tokenq/analytics` — tokens issued, served, average wait (issue→call) and
average service (call→done) per department, over a date range.

## New data

Six nullable columns added to `queue_ticket`: `priority`, `room`, `called_at`,
`done_at`, `created_by`, `branch_id`. Added automatically on startup (see
below).

## Permissions

`tokenq` → super_admin, reception, doctor, nurse, lab_tech, cashier. The public
display routes are unauthenticated by design.

## Upgrade / self-heal

The new columns are added automatically on every startup by the existing
`init_db` auto-migration — an existing `erp.db` heals itself the first time the
app runs. (`scripts/upgrade_v8.py` also covers them for manual runs.)

Tests: `tests/test_queue.py` covers emergency ordering, call-to-room, the public
feed, completion + analytics, the login-free display board, and RBAC.
