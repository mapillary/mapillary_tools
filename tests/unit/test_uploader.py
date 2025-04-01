import json
import os
import typing as T
import zipfile
from pathlib import Path

import py.path

import pytest

from mapillary_tools import types, upload_api_v4, uploader

from ..integration.fixtures import setup_upload, validate_and_extract_zip


IMPORT_PATH = "tests/unit/data"


@pytest.fixture
def setup_unittest_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(IMPORT_PATH)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


def _validate_zip_dir(zip_dir: py.path.local):
    descs = []
    for zip_path in zip_dir.listdir():
        with zipfile.ZipFile(zip_path) as ziph:
            filename = ziph.testzip()
            assert filename is None, f"Corrupted zip {zip_path}: {filename}"

            upload_md5sum = json.loads(ziph.comment).get("upload_md5sum")
        assert str(os.path.basename(zip_path)) == f"mly_tools_{upload_md5sum}.zip", (
            zip_path
        )
        descs.extend(validate_and_extract_zip(str(zip_path)))
    return descs


def test_upload_images(setup_unittest_data: py.path.local, setup_upload: py.path.local):
    mly_uploader = uploader.Uploader(
        {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"}, dry_run=True
    )
    test_exif = setup_unittest_data.join("test_exif.jpg")
    descs: T.List[types.DescriptionOrError] = [
        {
            "MAPLatitude": 58.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif),
            "md5sum": None,
            "filetype": "image",
        },
        {
            "MAPLatitude": 59.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_25_41_140",
            "filename": str(test_exif),
            "md5sum": "hello",
            "filetype": "image",
        },
    ]
    results = list(
        uploader.ZipImageSequence.prepare_images_and_upload(
            [types.from_desc(T.cast(T.Any, desc)) for desc in descs],
            mly_uploader,
        )
    )
    assert len(results) == 1
    assert len(setup_upload.listdir()) == 1
    actual_descs = _validate_zip_dir(setup_upload)
    assert 1 == len(actual_descs), "should return 1 desc because of the unique filename"


def test_upload_images_multiple_sequences(
    setup_unittest_data: py.path.local, setup_upload: py.path.local
):
    test_exif = setup_unittest_data.join("test_exif.jpg")
    fixed_exif = setup_unittest_data.join("fixed_exif.jpg")
    descs: T.List[types.DescriptionOrError] = [
        {
            "MAPLatitude": 58.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif),
            "md5sum": None,
            "filetype": "image",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 54.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif),
            "md5sum": None,
            "filetype": "image",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 59.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_25_41_140",
            "filename": str(fixed_exif),
            "md5sum": None,
            "filetype": "image",
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
    results = list(
        uploader.ZipImageSequence.prepare_images_and_upload(
            [types.from_desc(T.cast(T.Any, desc)) for desc in descs],
            mly_uploader,
        )
    )
    assert len(results) == 2
    assert len(setup_upload.listdir()) == 2
    actual_descs = _validate_zip_dir(setup_upload)
    assert 2 == len(actual_descs)


def test_upload_zip(
    setup_unittest_data: py.path.local,
    setup_upload: py.path.local,
    emitter=None,
):
    test_exif = setup_unittest_data.join("test_exif.jpg")
    setup_unittest_data.join("another_directory").mkdir()
    test_exif2 = setup_unittest_data.join("another_directory").join("test_exif.jpg")
    test_exif.copy(test_exif2)

    descs: T.List[types.DescriptionOrError] = [
        {
            "MAPLatitude": 58.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif),
            "md5sum": "1",
            "filetype": "image",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 54.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_24_41_140",
            "filename": str(test_exif2),
            "md5sum": "2",
            "filetype": "image",
            "MAPSequenceUUID": "sequence_1",
        },
        {
            "MAPLatitude": 59.5927694,
            "MAPLongitude": 16.1840944,
            "MAPCaptureTime": "2021_02_13_13_25_41_140",
            "filename": str(test_exif),
            "md5sum": "3",
            "filetype": "image",
            "MAPSequenceUUID": "sequence_2",
        },
    ]
    zip_dir = setup_unittest_data.mkdir("zip_dir")
    sequence = [types.from_desc(T.cast(T.Any, desc)) for desc in descs]
    uploader.ZipImageSequence.zip_images(sequence, Path(zip_dir))
    assert len(zip_dir.listdir()) == 2, list(zip_dir.listdir())
    descs = _validate_zip_dir(zip_dir)
    assert 3 == len(descs)

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
        cluster = uploader.ZipImageSequence.prepare_zipfile_and_upload(
            Path(zip_path), mly_uploader
        )
        assert cluster == "0"
    descs = _validate_zip_dir(setup_upload)
    assert 3 == len(descs)


def test_upload_blackvue(
    tmpdir: py.path.local,
    setup_upload: py.path.local,
):
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
        resp = mly_uploader.upload_stream(
            fp,
            upload_api_v4.ClusterFileType.BLACKVUE,
            "this_is_a_blackvue.mp4",
        )
    assert resp == "0"
    for mp4_path in setup_upload.listdir():
        assert os.path.basename(mp4_path) == "this_is_a_blackvue.mp4"
        with open(mp4_path, "rb") as fp:
            assert fp.read() == b"this is a fake video"


def test_upload_zip_with_emitter(
    setup_unittest_data: py.path.local,
    tmpdir: py.path.local,
    setup_upload: py.path.local,
):
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

    test_upload_zip(setup_unittest_data, setup_upload, emitter=emitter)

    assert len(stats) == 2
