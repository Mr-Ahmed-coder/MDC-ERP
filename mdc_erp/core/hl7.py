"""Minimal HL7 v2 support for analyzer result import  (Phase 4, v8.0).

Pure-python parsing of the ORU^R01 (observation result) message that clinical
analyzers / LIS middleware emit — no external HL7 library. Handles the common
pipe-delimited encoding; segments may be separated by \\r, \\n or \\r\\n.

Parsed shape:
    {
      'msg_id': str,
      'sample_id': str,      # OBR-3 specimen no (falls back to OBR-2 placer order)
      'patient_mrn': str,    # PID-3
      'results': [ {'name','value','unit','ref','flag'} , ... ]  # from OBX-NM/ST rows
    }
"""


def _split_segments(raw):
    raw = (raw or '').replace('\r\n', '\r').replace('\n', '\r')
    return [s for s in raw.split('\r') if s.strip()]


def parse_oru(raw):
    """Parse an ORU^R01 message. Returns the dict above, or None if not ORU."""
    segs = _split_segments(raw)
    if not segs or not segs[0].startswith('MSH'):
        return None
    msh = segs[0].split('|')
    msg_type = msh[8] if len(msh) > 8 else ''
    if 'ORU' not in msg_type:
        return None
    msg_id = msh[9] if len(msh) > 9 else ''

    out = {'msg_id': msg_id, 'sample_id': '', 'patient_mrn': '', 'results': []}
    for seg in segs:
        f = seg.split('|')
        tag = f[0]
        if tag == 'PID':
            # PID-3 patient identifier list (first component of first repetition)
            if len(f) > 3 and f[3]:
                out['patient_mrn'] = f[3].split('^')[0].split('~')[0]
        elif tag == 'OBR':
            spec = f[3] if len(f) > 3 else ''
            placer = f[2] if len(f) > 2 else ''
            out['sample_id'] = (spec or placer).split('^')[0].strip()
        elif tag == 'OBX':
            vtype = f[2] if len(f) > 2 else ''
            if vtype not in ('NM', 'ST', 'SN', 'TX', ''):
                continue
            name = (f[3].split('^')[1] if (len(f) > 3 and '^' in f[3])
                    else (f[3].split('^')[0] if len(f) > 3 else '')).strip()
            if not name and len(f) > 3:
                name = f[3].strip()
            value = f[5].strip() if len(f) > 5 else ''
            unit = f[6].strip() if len(f) > 6 else ''
            ref = f[7].strip() if len(f) > 7 else ''
            flag = f[8].strip() if len(f) > 8 else ''
            if name:
                out['results'].append({'name': name, 'value': value,
                                       'unit': unit, 'ref': ref, 'flag': flag})
    return out


def build_ack(msg_id, code='AA', text=''):
    """Build a minimal HL7 ACK (MSH + MSA). code: AA accept, AE error, AR reject."""
    import datetime as dt
    ts = dt.datetime.now().strftime('%Y%m%d%H%M%S')
    msh = f'MSH|^~\\&|LIS|MDC|ANALYZER|LAB|{ts}||ACK|{msg_id or ts}|P|2.3.1'
    msa = f'MSA|{code}|{msg_id}' + (f'|{text}' if text else '')
    return msh + '\r' + msa
