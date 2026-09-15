# PACS — DICOM Imaging (Phase 1, v8.0)

Store, browse and view DICOM imaging inside the ERP, integrated with the
existing patient records and radiology reporting.

## What it does

- **Upload** one or more `.dcm` files, or a single `.zip` containing a whole
  study. Files are parsed with `pydicom` and organised automatically into a
  **Study → Series → Instance** hierarchy.
- **Organise by patient** — link an upload to a patient (and optionally to an
  existing radiology order, so the study appears alongside its report).
- **Web DICOM viewer** (offline, no external libraries — works on a LAN with no
  internet): zoom, pan, rotate, invert, brightness/contrast (approximates
  window/level on the rendered frame), length measurement (converts pixels → mm
  when pixel spacing is present), multi-frame scrolling and cine playback.
- **Download** the original study as a `.zip` of the untouched DICOM files
  (lossless — nothing is transcoded on the way out).
- **Radiologist reporting** reuses the existing Radiology report workflow via
  the linked order.
- **RBAC + audit + branch scoping** — same model as the rest of the ERP.
  Permission key: `pacs` (super_admin, radiologist, doctor, reception,
  lab_tech, it_admin by default; editable in the Users permission matrix).

## Where the files live

Rendered frames and original DICOMs are stored under
`<DATA_DIR>/uploads/pacs/<study_id>/<series_id>/<instance_id>/`:

```
frame_0.png … frame_N.png   rendered frames (default window applied)
thumb.png                    series thumbnail
orig.dcm                     untouched original for lossless download
```

## Enabling it on an existing install

The three PACS tables (`img_study`, `img_series`, `img_instance`) are created by
the standard bootstrap:

```bash
pip install -r requirements.txt      # adds pydicom, numpy, Pillow
flask init-db                        # create_all() adds only the new tables
```

`init-db` is safe to re-run: `create_all()` only creates missing tables and
never touches existing data.

## Compressed transfer syntaxes

Uncompressed DICOM renders out of the box. For **compressed** studies
(JPEG / JPEG2000 / RLE) install the optional `pylibjpeg` codecs listed
(commented) at the bottom of `requirements.txt`. Without them the study is still
fully catalogued and downloadable — only the in-browser preview shows a
"codec N/A" placeholder for those instances.

## Routes

| Route | Purpose |
|-------|---------|
| `/m/pacs` | Study worklist (App Launcher → Radiology → PACS) |
| `/pacs/upload` | Upload `.dcm` / `.zip` |
| `/pacs/study/<id>` | Study detail: series, thumbnails, metadata |
| `/pacs/study/<id>/viewer` | Web DICOM viewer |
| `/pacs/inst/<id>/frame/<n>.png` | A rendered frame |
| `/pacs/inst/<id>/thumb.png` | Series thumbnail |
| `/pacs/study/<id>/download` | Original study as `.zip` |
| `/pacs/study/<id>/reviewed` | Mark reviewed |
| `/pacs/study/<id>/delete` | Delete (super_admin / it_admin) |

Tests: `tests/test_pacs.py` synthesizes real DICOM objects and exercises the
full ingest → render → view → download path plus an RBAC denial.
