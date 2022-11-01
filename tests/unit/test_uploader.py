import json
import os
import tempfile
import typing as T
import zipfile
from pathlib import Path

import py.path
import pytest

from mapillary_tools import exif_read, uploader


def _validate_and_extract_zip(filename: str):
    ret = {}
    with zipfile.ZipFile(filename) as zipf:
        with tempfile.TemporaryDirectory() as tempdir:
            zipf.extractall(path=tempdir)
            for name in os.listdir(tempdir):
                with open(os.path.join(tempdir, name), "rb") as fp:
                    tags = exif_read.exifread.process_file(fp)
                    desc_tag = tags.get("Image ImageDescription")
                    assert desc_tag is not None, tags
                    desc = json.loads(str(desc_tag.values))
                    assert isinstance(desc.get("MAPLatitude"), (float, int)), desc
                    assert isinstance(desc.get("MAPLongitude"), (float, int)), desc
                    assert isinstance(desc.get("MAPCaptureTime"), str), desc
                    for key in desc.keys():
                        assert key.startswith("MAP"), key
                    ret[name] = desc
    return ret


def _validate_zip_dir(zip_dir: py.path.local):
    for zip_path in zip_dir.listdir():
        with zipfile.ZipFile(zip_path) as ziph:
            upload_md5sum = uploader._hash_zipfile(ziph)
        assert (
            str(os.path.basename(zip_path)) == f"mly_tools_{upload_md5sum}.zip"
        ), zip_path
        _validate_and_extract_zip(str(zip_path))


@pytest.fixture
def setup_upload(tmpdir: py.path.local):
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    os.environ["MAPILLARY__DISABLE_BLACKVUE_CHECK"] = "YES"
    yield upload_dir
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)
    del os.environ["MAPILLARY_UPLOAD_PATH"]
    del os.environ["MAPILLARY__DISABLE_BLACKVUE_CHECK"]


def test_upload_images(setup_upload: py.path.local):
    mly_uploader = uploader.Uploader(
        {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"}, dry_run=True
    )
    descs = [
        {
            "MAPLatitude": 58.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": "tests/unit/data/test_exif.jpg",
        },
        {
            "MAPLatitude": 59.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_25_41_140",
            "filename": "tests/unit/data/test_exif.jpg",
        },
    ]
    resp = mly_uploader.upload_images(T.cast(T.Any, descs))
    assert len(resp) == 1
    assert len(setup_upload.listdir()) == 1
    _validate_zip_dir(setup_upload)


def test_upload_images_multiple_sequences(setup_upload: py.path.local):
    descs = [
        {
            "MAPLatitude": 58.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": "tests/unit/data/test_exif.jpg",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 54.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": "tests/unit/data/test_exif.jpg",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 59.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_25_41_140",
            "filename": "tests/unit/data/fixed_exif.jpg",
            "MAPSequenceUUID": "sequence_2",
        },
    ]
    mly_uploader = uploader.Uploader(
        {
            "user_upload_token": "YOUR_USER_ACCESS_TOKEN",
            # will call the API for real
            # "MAPOrganizationKey": "3011753992432185",
        },
        dry_run=True,
    )
    resp = mly_uploader.upload_images(T.cast(T.Any, descs))
    assert len(resp) == 2
    assert len(setup_upload.listdir()) == 2
    _validate_zip_dir(setup_upload)


def test_upload_zip(tmpdir: py.path.local, setup_upload: py.path.local, emitter=None):
    same_basename = tmpdir.join("text_exif.jpg")
    py.path.local("tests/unit/data/test_exif.jpg").copy(tmpdir.join("text_exif.jpg"))
    descs = [
        {
            "MAPLatitude": 58.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": "tests/unit/data/test_exif.jpg",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 54.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(same_basename),
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 59.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_25_41_140",
            "filename": "tests/unit/data/test_exif.jpg",
            "MAPSequenceUUID": "sequence_2",
        },
    ]
    zip_dir = tmpdir.mkdir("zip_dir")
    uploader.zip_images(T.cast(T.Any, descs), Path(zip_dir))
    assert len(zip_dir.listdir()) == 2, list(zip_dir.listdir())
    _validate_zip_dir(zip_dir)

    mly_uploader = uploader.Uploader(
        {
            "user_upload_token": "YOUR_USER_ACCESS_TOKEN",
            # will call the API for real
            # "MAPOrganizationKey": 3011753992432185,
        },
        dry_run=True,
        emitter=emitter,
    )
    for zip_path in zip_dir.listdir():
        resp = mly_uploader.upload_zipfile(Path(zip_path))

    _validate_zip_dir(setup_upload)


def test_upload_blackvue(tmpdir: py.path.local, setup_upload: py.path.local):
    mly_uploader = uploader.Uploader(
        {
            "user_upload_token": "YOUR_USER_ACCESS_TOKEN",
            # will call the API for real
            # "MAPOrganizationKey": "3011753992432185",
        },
        dry_run=True,
    )
    blackvue_path = tmpdir.join("blackvue.mp4")
    with open(blackvue_path, "wb") as fp:
        fp.write(b"this is a fake video")
    with Path(blackvue_path).open("rb") as fp:
        resp = mly_uploader.upload_blackvue_fp(fp)
    assert resp == "0"
    for mp4_path in setup_upload.listdir():
        basename = os.path.basename(mp4_path)
        assert str(basename).startswith("mly_tools_")
        assert str(basename).endswith(".mp4")
        with open(mp4_path, "rb") as fp:
            assert fp.read() == b"this is a fake video"


def test_upload_zip_with_emitter(tmpdir: py.path.local, setup_upload: py.path.local):
    emitter = uploader.EventEmitter()

    stats = {}

    @emitter.on("upload_start")
    def _upload_start(payload):
        assert payload["entity_size"] > 0
        assert "offset" not in payload
        assert "test_started" not in payload
        payload["test_started"] = True

        assert payload["md5sum"] not in stats
        stats[payload["md5sum"]] = {**payload}

    @emitter.on("upload_fetch_offset")
    def _fetch_offset(payload):
        assert payload["offset"] >= 0
        assert payload["test_started"]
        payload["test_fetch_offset"] = True

        assert payload["md5sum"] in stats

    @emitter.on("upload_end")
    def _upload_end(payload):
        assert payload["offset"] > 0
        assert payload["test_started"]
        assert payload["test_fetch_offset"]

        assert payload["md5sum"] in stats

    test_upload_zip(tmpdir, setup_upload, emitter=emitter)

    assert len(stats) == 2
