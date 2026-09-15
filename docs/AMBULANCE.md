# Ambulance (Phase 11, v8.0)

Vehicle & driver registries, dispatch with a timestamped status flow, location
tracking, and billing. All-new tables; reuses existing invoicing.

## Fleet & drivers

- **Ambulances** (`/m/vehicles`) — unit name, plate, type (BLS / ALS / Patient
  transport) and a status (Available / OnTrip / Maintenance) kept in sync
  automatically as dispatches run.
- **Drivers** (`/m/drivers_amb`) — name, phone, licence.

## Dispatch

`/ambulance/new` — log a call: patient (optional) or caller name/phone, pickup,
destination, priority (Emergency / Non-emergency), and assign a vehicle + driver.

The status flow is one tap at a time, each stamped with the time:

```
Requested → Dispatched → OnScene → Transporting → Completed   (or Cancelled)
```

Dispatching marks the vehicle **OnTrip**; completing or cancelling frees it.

## Location tracking

> **On GPS:** the ERP provides the ingest endpoint and map links — it is not a
> telematics network. A GPS device or a phone running a tracker app in the
> vehicle posts coordinates to the ERP; there is no hardware bundled.

- **Manual** — staff can enter a lat/lng with a note; the dispatch shows the
  **last known location** with an "Open in Maps" link and a breadcrumb trail.
- **Device / phone push** — `POST /api/ambulance/<id>/location` with a shared
  token (set **`amb_gps_token`** in Settings, sent as the `X-AMB-Token` header
  or `?token=`), body `{"lat":.., "lng":.., "note":".."}` as JSON or form.
  Returns JSON; each push adds a breadcrumb tagged **GPS** and updates the last
  known position. A phone's browser geolocation or any GPS tracker app can drive
  this.

## Billing

**Create bill** opens an invoice for the patient to add the ambulance charge
through the normal billing/accounting flow.

## Board

`/m/ambulance` — active calls with route, unit, driver and status, plus KPI
tiles (active calls / emergency / available units / total units).

## New data

`Ambulance`, `AmbulanceDriver`, `Dispatch`, `DispatchLocation` — all new tables.
A fresh `flask init-db` (or the startup self-heal) creates them.

## Permissions

| Key | Default roles |
|-----|---------------|
| `ambulance` | super_admin, reception, nurse, doctor, branch_manager |
| `vehicles` | super_admin, branch_manager, it_admin |
| `drivers_amb` | super_admin, branch_manager, hr |

The GPS endpoint is authenticated by the shared token, not a session.

Tests: `tests/test_ambulance.py` covers dispatch, the status flow with vehicle
sync, manual + token-protected GPS location (accept + reject), and billing, plus
RBAC.
