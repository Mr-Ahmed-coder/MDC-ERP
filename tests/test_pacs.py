"""PACS (Phase 1, v8.0) end-to-end tests.

Synthesizes real DICOM objects with pydicom (no scanner needed), pushes them
through the upload -> ingest -> render pipeline, and exercises every PACS route
with a logged-in client. Skips cleanly if the optional DICOM stack is absent.
"""
import os
import io
import glob
import tempfile
import pytest

pydicom = pytest.importorskip('pydicom')
np = pytest.importorskip('numpy')
pytest.importorskip('PIL')

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, CTImageStorage

from mdc_erp import create_app
from mdc_erp.bootstrap import init_db
from mdc_erp.config import DevelopmentConfig


def _make_dicom(path, frames=1, rows=48, cols=48, series_uid=None,
                series_no=1, inst_no=1, study_uid=None):
    fm = Dataset()
    fm.MediaStorageSOPClassUID = CTImageStorage
    fm.MediaStorageSOPInstanceUID = generate_uid()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(path, {}, file_meta=fm, preamble=b"\0" * 128)
    ds.PatientName = "TEST^PACS"
    ds.PatientID = "MRN-PACS"
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
    ds.SOPClassUID = CTImageStorage
    ds.Modality = "CT"
    ds.StudyDescription = "Test CT"
    ds.SeriesDescription = f"Series {series_no}"
    ds.StudyDate = "20260115"
    ds.SeriesNumber = series_no
    ds.InstanceNumber = inst_no
    ds.Rows, ds.Columns = rows, cols
    ds.PixelSpacing = [0.5, 0.5]
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.WindowCenter = 40
    ds.WindowWidth = 400
    if frames > 1:
        ds.NumberOfFrames = frames
        vol = np.zeros((frames, rows, cols), dtype=np.uint16)
        for f in range(frames):
            yy, xx = np.mgrid[0:rows, 0:cols]
            vol[f] = ((xx + yy + f * 20) % 1000).astype(np.uint16)
        ds.PixelData = vol.tobytes()
    else:
        yy, xx = np.mgrid[0:rows, 0:cols]
        ds.PixelData = (((xx + yy) * 4) % 4000).astype(np.uint16).tobytes()
    ds.save_as(path, write_like_original=False)


@pytest.fixture()
def pacs_app(tmp_path):
    class Cfg(DevelopmentConfig):
        TESTING = True
        WTF_CSRF_ENABLED = False
        DATA_DIR = str(tmp_path)
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'pacs.db'}"
    # PACS_ROOT is resolved from config.DATA_DIR at import; point uploads at tmp
    import mdc_erp.blueprints.pacs as pacs_mod
    pacs_mod.PACS_ROOT = str(tmp_path / 'uploads' / 'pacs')
    app = create_app(Cfg)
    init_db(app, demo=True)
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role='super_admin').first()
        u.must_change_pw = False
        db.session.commit()
        app._admin_id = u.id
    return app


def _login(app, client, role='super_admin'):
    with app.app_context():
        from mdc_erp.extensions import db
        from mdc_erp.models import User
        u = User.query.filter_by(role=role).first()
        if u:
            u.must_change_pw = False
            db.session.commit()
            uid = u.id
        else:
            uid = None
    if uid:
        with client.session_transaction() as s:
            s['uid'] = uid
    return uid


def _upload_study(tmp_path):
    d = tmp_path / 'dcm'
    d.mkdir(exist_ok=True)
    suid = generate_uid()
    s1 = generate_uid()
    _make_dicom(str(d / 'a.dcm'), series_uid=s1, series_no=1, inst_no=1, study_uid=suid)
    _make_dicom(str(d / 'b.dcm'), series_uid=s1, series_no=1, inst_no=2, study_uid=suid)
    _make_dicom(str(d / 'c.dcm'), frames=6, series_no=2, inst_no=1, study_uid=suid)
    return sorted(glob.glob(str(d / '*.dcm')))


def test_pacs_upload_ingest_and_view(pacs_app, tmp_path):
    app = pacs_app
    client = app.test_client()
    _login(app, client)

    files = _upload_study(tmp_path)
    # the app uses a custom per-session CSRF token: seed a known value
    with client.session_transaction() as s:
        s['_csrf'] = 'testtoken'
    r = client.post('/pacs/upload',
                    data={'_csrf': 'testtoken', 'patient_id': '',
                          'dicom': [(open(f, 'rb'), os.path.basename(f)) for f in files]},
                    content_type='multipart/form-data', follow_redirects=True)
    assert r.status_code == 200

    with app.app_context():
        from mdc_erp.models import ImgStudy, ImgSeries, ImgInstance
        st = ImgStudy.query.first()
        assert st is not None, 'study created'
        assert st.num_series == 2                      # two distinct series UIDs
        assert st.num_instances == 3
        assert st.modality == 'CT'
        multi = ImgInstance.query.filter_by(frames=6).first()
        assert multi is not None, 'multi-frame rendered to 6 frames'
        sid = st.id
        iid = ImgInstance.query.first().id

    # worklist, detail, viewer
    assert client.get('/m/pacs').status_code == 200
    assert client.get(f'/pacs/study/{sid}').status_code == 200
    v = client.get(f'/pacs/study/{sid}/viewer')
    assert v.status_code == 200 and b'vcanvas' in v.data

    # media: rendered frame, thumbnail, and full-study zip
    fr = client.get(f'/pacs/inst/{iid}/frame/0.png')
    assert fr.status_code == 200 and fr.headers['Content-Type'] == 'image/png'
    assert client.get(f'/pacs/inst/{iid}/thumb.png').status_code == 200
    z = client.get(f'/pacs/study/{sid}/download')
    assert z.status_code == 200 and 'zip' in z.headers['Content-Type']

    # reviewed toggle
    client.get(f'/pacs/study/{sid}/reviewed')
    with app.app_context():
        from mdc_erp.models import ImgStudy
        from mdc_erp.extensions import db
        assert db.session.get(ImgStudy, sid).status == 'Reviewed'


def test_pacs_rbac_denies_unprivileged_role(pacs_app):
    app = pacs_app
    client = app.test_client()
    # accountant is NOT in the pacs permission list
    if _login(app, client, role='accountant') is None:
        pytest.skip('no accountant role in seed')
    assert client.get('/pacs/upload').status_code == 403
