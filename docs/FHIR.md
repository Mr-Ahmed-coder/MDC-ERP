# FHIR R4 API (Phase 6, v8.0)

A read-only **FHIR R4** interoperability layer over the ERP, so external systems
(HIEs, national registries, referral partners, research tools) can pull clinical
data in a standard format.

## Base & authentication

- Base URL: **`/fhir`**
- Format: `application/fhir+json`
- Auth: the same **JWT** the existing REST API issues. Get a token:
  ```
  POST /api/login   {"username": "...", "password": "..."}
  → { "data": { "token": "<jwt>" } }
  ```
  then send it on every FHIR call:
  ```
  Authorization: Bearer <jwt>
  ```
- `GET /fhir/metadata` (the CapabilityStatement) is **public** so clients can
  discover the server; every resource endpoint requires the token.

All endpoints are **GET** (read + search). No data is written through FHIR.

## Resources

| Resource | Source model | Read | Search params |
|----------|--------------|------|---------------|
| `Patient` | Patient | `/fhir/Patient/{id}` | `name`, `identifier`, `phone` |
| `Practitioner` | Doctor, Radiologist | `/fhir/Practitioner/{doc\|rad}-{id}` | `name` |
| `Encounter` | Consultation | `/fhir/Encounter/{id}` | `patient` |
| `Observation` | LabResultValue | `/fhir/Observation/lrv-{id}` | `patient` |
| `DiagnosticReport` | LabOrder, RadOrder | `/fhir/DiagnosticReport/{lab\|rad}-{id}` | `patient` |
| `ImagingStudy` | ImgStudy (PACS) | `/fhir/ImagingStudy/{id}` | `patient` |
| `Medication` | Medicine | `/fhir/Medication/{id}` | `code`/`name` |
| `MedicationRequest` | Prescription | `/fhir/MedicationRequest/{id}` | `patient` |

Search responses are FHIR **Bundles** (`type: searchset`). Use `_count` (max
200) to limit results. `patient` accepts `Patient/{id}` or a bare id.

## Examples

```
GET /fhir/metadata
GET /fhir/Patient?name=Amina                       Authorization: Bearer …
GET /fhir/Patient/42                               Authorization: Bearer …
GET /fhir/Observation?patient=42                   Authorization: Bearer …
GET /fhir/DiagnosticReport?patient=42              Authorization: Bearer …
GET /fhir/ImagingStudy?patient=42                  Authorization: Bearer …
GET /fhir/MedicationRequest?patient=42             Authorization: Bearer …
```

## Notes on the mapping

- **Observation** carries the analyte value as a `valueQuantity` (or
  `valueString` for non-numeric), the reference range, and — importantly — the
  critical-value interpretation (`HH`/`LL`) from the LIS, so downstream systems
  see criticals.
- **DiagnosticReport** ids are prefixed `lab-` or `rad-` to distinguish lab and
  imaging reports; lab reports link their `Observation` results.
- **ImagingStudy** exposes the Study→Series counts and modality from PACS.
- **Encounter** carries the ICD-10 diagnosis as `reasonCode` when present.
- Errors return a FHIR **OperationOutcome** with the right HTTP status
  (401 unauthenticated, 404 not-found).

Two earlier minimal stubs remain at `/api/fhir/Patient/{id}` and
`/api/fhir/Observation` for backward compatibility; the full R4 API lives at
`/fhir`.

Tests: `tests/test_fhir.py` covers the public CapabilityStatement, auth
enforcement, and read/search for every resource type.
