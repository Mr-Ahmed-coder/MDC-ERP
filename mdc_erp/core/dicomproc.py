"""DICOM ingestion & frame rendering for the PACS module.

Parses a DICOM Part-10 file with pydicom, extracts the Study -> Series ->
Instance metadata that the PACS models store, and renders each frame to a
grayscale/RGB PNG so the browser viewer can show images with zero client-side
DICOM tooling (important for offline LAN use at the centre).

Design notes
------------
* Metadata is ALWAYS captured, even when pixel data cannot be decoded (e.g. a
  compressed transfer syntax with no codec installed). In that case the
  instance is still catalogued and the viewer shows a "pixel data needs a
  decoder" placeholder instead of crashing. This keeps ingest robust against
  whatever a real scanner produces.
* Window/Level: the DICOM-declared WindowCenter/WindowWidth is used when
  present; otherwise a min/max auto-window is computed. The chosen values are
  saved on the instance so the viewer can label them and so re-render is
  reproducible.
* MONOCHROME1 (inverted) is honoured. Multi-frame instances render every frame.
"""
import os

MAX_FRAMES = 512          # safety cap for pathological multi-frame objects
THUMB_MAX = 220           # px, longest edge of the series thumbnail


def available():
    """True if the optional DICOM stack (pydicom/numpy/Pillow) is installed.

    PACS storage, browsing and the viewer work without it; only DICOM *ingest*
    (parsing + frame rendering) needs these libraries. Kept optional so the ERP
    starts and runs normally on installs that predate v8.0."""
    try:
        import pydicom  # noqa: F401
        import numpy    # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def _is_dicom(path):
    """Cheap check for the 'DICM' magic at offset 128 (Part-10 preamble)."""
    try:
        with open(path, 'rb') as fh:
            fh.seek(128)
            return fh.read(4) == b'DICM'
    except Exception:
        return False


def _first(ds, *names, default=''):
    for n in names:
        v = getattr(ds, n, None)
        if v not in (None, ''):
            return v
    return default


def _num(v, default=None):
    try:
        if isinstance(v, (list, tuple)) and v:
            v = v[0]
        return float(v)
    except Exception:
        return default


def read_metadata(path):
    """Return a flat dict of the metadata PACS stores, without touching pixels."""
    import pydicom
    ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    spacing = getattr(ds, 'PixelSpacing', None)
    px = None
    if spacing:
        try:
            px = float(spacing[0])       # row spacing in mm; good enough for length tools
        except Exception:
            px = None
    sd = str(_first(ds, 'StudyDate', default=''))
    if len(sd) == 8:
        sd = f'{sd[0:4]}-{sd[4:6]}-{sd[6:8]}'
    return {
        'study_uid':   str(_first(ds, 'StudyInstanceUID', default='')),
        'series_uid':  str(_first(ds, 'SeriesInstanceUID', default='')),
        'sop_uid':     str(_first(ds, 'SOPInstanceUID', default='')),
        'accession':   str(_first(ds, 'AccessionNumber', default=''))[:40],
        'modality':    str(_first(ds, 'Modality', default='OT'))[:16],
        'study_desc':  str(_first(ds, 'StudyDescription', 'SeriesDescription', default=''))[:200],
        'series_desc': str(_first(ds, 'SeriesDescription', default=''))[:200],
        'body_part':   str(_first(ds, 'BodyPartExamined', default=''))[:40],
        'referring':   str(_first(ds, 'ReferringPhysicianName', default=''))[:80],
        'patient_name': str(_first(ds, 'PatientName', default='')).replace('^', ' ').strip()[:120],
        'patient_id':  str(_first(ds, 'PatientID', default=''))[:40],
        'study_date':  sd,
        'series_no':   int(_num(getattr(ds, 'SeriesNumber', 0), 0) or 0),
        'instance_no': int(_num(getattr(ds, 'InstanceNumber', 0), 0) or 0),
        'rows':        int(_num(getattr(ds, 'Rows', 0), 0) or 0),
        'cols':        int(_num(getattr(ds, 'Columns', 0), 0) or 0),
        'pixel_spacing': px,
        'win_center':  _num(getattr(ds, 'WindowCenter', None)),
        'win_width':   _num(getattr(ds, 'WindowWidth', None)),
    }


def render_frames(path, out_dir):
    """Decode pixel data and write frame_0.png .. frame_N.png into out_dir.

    Returns (frame_count, win_center, win_width). frame_count == 0 means the
    pixels could not be decoded (metadata ingest still succeeds upstream).
    """
    import numpy as np
    import pydicom
    from PIL import Image

    os.makedirs(out_dir, exist_ok=True)
    try:
        ds = pydicom.dcmread(path, force=True)
        arr = ds.pixel_array                      # may raise if codec missing
    except Exception:
        return 0, None, None

    arr = np.asarray(arr)
    photometric = str(getattr(ds, 'PhotometricInterpretation', 'MONOCHROME2'))
    is_color = photometric.startswith('RGB') or photometric.startswith('YBR') or (
        arr.ndim == 3 and arr.shape[-1] == 3) or (arr.ndim == 4 and arr.shape[-1] == 3)

    # Normalise to a list of 2-D (grayscale) or 3-D (RGB) frames.
    if is_color:
        frames = arr if arr.ndim == 4 else arr[None, ...]
    else:
        frames = arr if arr.ndim == 3 else arr[None, ...]

    n = min(len(frames), MAX_FRAMES)

    # --- grayscale windowing -------------------------------------------------
    wc = ww = None
    if not is_color:
        slope = float(getattr(ds, 'RescaleSlope', 1) or 1)
        intercept = float(getattr(ds, 'RescaleIntercept', 0) or 0)
        stack = frames[:n].astype(np.float64) * slope + intercept

        wc = _num(getattr(ds, 'WindowCenter', None))
        ww = _num(getattr(ds, 'WindowWidth', None))
        if not ww or ww <= 0:
            lo, hi = float(stack.min()), float(stack.max())
            wc = (hi + lo) / 2.0
            ww = max(hi - lo, 1.0)
        lo = wc - ww / 2.0
        invert = photometric == 'MONOCHROME1'

    for i in range(n):
        if is_color:
            img = Image.fromarray(frames[i].astype('uint8'), 'RGB')
        else:
            f = stack[i]
            out = ((f - lo) / ww) * 255.0
            out = np.clip(out, 0, 255)
            if invert:
                out = 255.0 - out
            img = Image.fromarray(out.astype('uint8'), 'L')
        img.save(os.path.join(out_dir, f'frame_{i}.png'), optimize=True)

    # series thumbnail = first frame, downscaled
    try:
        first = Image.open(os.path.join(out_dir, 'frame_0.png'))
        first.thumbnail((THUMB_MAX, THUMB_MAX))
        first.convert('RGB').save(os.path.join(out_dir, 'thumb.png'))
    except Exception:
        pass

    return n, (round(wc, 1) if wc is not None else None), (round(ww, 1) if ww is not None else None)


def iter_dicom_files(paths):
    """Yield DICOM file paths from a mixed list of files / extracted archives."""
    for p in paths:
        if os.path.isfile(p) and (_is_dicom(p) or p.lower().endswith('.dcm')):
            yield p
