# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

from mapillary_tools import (
    constants,
    fingerprint,
    geo,
    history,
    types,
    upload,
    uploader,
    utils,
)
from mapillary_tools.commands import __main__ as commands
from mapillary_tools.serializer.description import DescriptionJSONSerializer

from .test_uploader import _write_empty_mp4

TEST_IMAGE_DIR = Path(__file__).parent.parent.joinpath("data", "images")


def _image(filename: Path, sequence_uuid: str, capture_time: float):
    return types.ImageMetadata(
        filename=filename,
        lat=1.0,
        lon=2.0,
        alt=None,
        angle=None,
        time=capture_time,
        MAPSequenceUUID=sequence_uuid,
    )


def _video(filename: Path) -> types.VideoMetadata:
    return types.VideoMetadata(
        filename=filename, filetype=types.FileType.CAMM, points=[]
    )


def _record_upload(*paths: Path, uploaded_at: float | None = 123.0) -> None:
    """Record the files as one uploaded video or image sequence, as upload does"""
    history.write_uploaded_files(
        [
            history.UploadedFile(
                path, path.stat().st_size, fingerprint.fingerprint_file(path)
            )
            for path in paths
        ],
        {"version": "test"},
        {"upload_end_time": uploaded_at},
    )


def _count_reads(monkeypatch) -> list[str]:
    """
    Record the name of each file read for its fingerprint, and of each file
    read in full for a checksum (prefixed with "md5:")
    """
    reads: list[str] = []
    fingerprint_file = fingerprint.fingerprint_file
    md5sum_fp = utils.md5sum_fp

    def _fingerprint_file(path):
        reads.append(path.name)
        return fingerprint_file(path)

    def _md5sum_fp(fp, *args, **kwargs):
        reads.append(f"md5:{os.path.basename(getattr(fp, 'name', ''))}")
        return md5sum_fp(fp, *args, **kwargs)

    monkeypatch.setattr(fingerprint, "fingerprint_file", _fingerprint_file)
    monkeypatch.setattr(utils, "md5sum_fp", _md5sum_fp)
    return reads


def _history_files(history_path: Path) -> dict[Path, bytes]:
    return {
        path: path.read_bytes() for path in history_path.rglob("*") if path.is_file()
    }


def _result(file_type, sequence_uuid, filenames, uploaded_filenames):
    return {
        "file_type": file_type,
        "sequence_uuid": sequence_uuid,
        "sequence_md5sum": "",
        "filenames": [str(filename) for filename in filenames],
        "already_uploaded_filenames": [
            str(filename) for filename in uploaded_filenames
        ],
        "already_uploaded": list(filenames) == list(uploaded_filenames),
    }


def test_check_upload_history_for_images_and_video(tmp_path, monkeypatch):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    first_image_path = tmp_path / "first.jpg"
    second_image_path = tmp_path / "second.jpg"
    video_path = tmp_path / "video.mp4"
    first_image_path.write_bytes(b"first image")
    second_image_path.write_bytes(b"second image")
    video_path.write_bytes(b"video")
    images = [first_image_path, second_image_path]

    metadatas = [
        _image(second_image_path, "sequence", 2.0),
        _image(first_image_path, "sequence", 1.0),
        _video(video_path),
    ]
    reads = _count_reads(monkeypatch)

    results = upload.check_upload_history(
        [*images, video_path], _metadatas_from_process=metadatas
    )

    assert results == [
        _result("image", "sequence", images, []),
        _result("camm", None, [video_path], []),
    ]
    # Nothing was uploaded: no file is read, no history is created
    assert reads == []
    assert not history_path.exists()

    _record_upload(*images)
    history_files = _history_files(history_path)
    reads.clear()

    results = upload.check_upload_history(
        [*images, video_path], _metadatas_from_process=metadatas
    )

    assert results == [
        _result("image", "sequence", images, images),
        _result("camm", None, [video_path], []),
    ]
    # Only the files of uploaded sizes are read, for their fingerprints
    assert sorted(reads) == ["first.jpg", "second.jpg"]
    # The upload history is only read
    assert _history_files(history_path) == history_files

    _record_upload(video_path, uploaded_at=456.0)
    results = upload.check_upload_history(
        [*images, video_path], _metadatas_from_process=metadatas
    )

    assert results == [
        _result("image", "sequence", images, images),
        _result("camm", None, [video_path], [video_path]),
    ]


def test_check_upload_history_tells_apart_files_of_the_same_size(tmp_path, monkeypatch):
    monkeypatch.setattr(
        constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(tmp_path / "history")
    )
    uploaded_path = tmp_path / "uploaded.mp4"
    uploaded_path.write_bytes(b"video A")
    _record_upload(uploaded_path)
    same_size_path = tmp_path / "same-size.mp4"
    same_size_path.write_bytes(b"video B")
    other_size_path = tmp_path / "other-size.mp4"
    other_size_path.write_bytes(b"another video")
    reads = _count_reads(monkeypatch)

    results = upload.check_upload_history(
        [same_size_path, other_size_path],
        _metadatas_from_process=[_video(same_size_path), _video(other_size_path)],
    )

    assert results == [
        _result("camm", None, [other_size_path], []),
        _result("camm", None, [same_size_path], []),
    ]
    assert reads == ["same-size.mp4"]


def test_check_upload_history_finds_renamed_files(tmp_path, monkeypatch):
    monkeypatch.setattr(
        constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(tmp_path / "history")
    )
    uploaded_path = tmp_path / "GX010001.MP4"
    uploaded_path.write_bytes(b"a video")
    _record_upload(uploaded_path)
    renamed_path = tmp_path / "renamed.mp4"
    uploaded_path.rename(renamed_path)

    results = upload.check_upload_history(
        [renamed_path], _metadatas_from_process=[_video(renamed_path)]
    )

    assert results == [_result("camm", None, [renamed_path], [renamed_path])]


def test_check_upload_history_matches_subset_of_uploaded_image_sequence(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(tmp_path / "history")
    )
    first_image_path = tmp_path / "first.jpg"
    second_image_path = tmp_path / "second.jpg"
    old_extra_path = tmp_path / "old-extra.jpg"
    first_image_path.write_bytes(b"first image")
    second_image_path.write_bytes(b"second image")
    old_extra_path.write_bytes(b"an image uploaded with them")
    # Uploaded in a larger sequence
    _record_upload(old_extra_path, first_image_path, second_image_path)

    results = upload.check_upload_history(
        [first_image_path, second_image_path],
        _metadatas_from_process=[
            _image(first_image_path, "current-sequence", 1.0),
            _image(second_image_path, "current-sequence", 2.0),
        ],
    )

    images = [first_image_path, second_image_path]
    assert results == [_result("image", "current-sequence", images, images)]


def test_check_upload_history_reports_mixed_uploaded_image_subset(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(tmp_path / "history")
    )
    first_image_path = tmp_path / "first.jpg"
    second_image_path = tmp_path / "second.jpg"
    first_image_path.write_bytes(b"first image")
    second_image_path.write_bytes(b"second image")
    _record_upload(first_image_path)

    results = upload.check_upload_history(
        [first_image_path, second_image_path],
        _metadatas_from_process=[
            _image(first_image_path, "current-sequence", 1.0),
            _image(second_image_path, "current-sequence", 2.0),
        ],
    )

    assert results == [
        _result(
            "image",
            "current-sequence",
            [first_image_path, second_image_path],
            [first_image_path],
        )
    ]


def test_check_upload_history_skips_invalid_records_and_preserves_file_order(
    tmp_path, monkeypatch, caplog
):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    image_paths = [tmp_path / f"image-{index}.jpg" for index in range(3)]
    for index, image_path in enumerate(image_paths):
        image_path.write_bytes(f"image {index}".encode() * (index + 1))
    root = history_path / history.UPLOADED_FILES_DIR
    invalid_records = {
        root / "00" / "invalid-json.json": b"{",
        root / "01" / "not-utf8.json": b"\xff",
        root / "02" / "invalid-record.json": b"[]",
        root / "03" / "invalid-files.json": json.dumps(
            {"files": [None, {"filesize": 7, "fingerprint": "not one"}]}
        ).encode(),
    }
    for record_path, contents in invalid_records.items():
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_bytes(contents)
    # Recorded in another order
    _record_upload(image_paths[2], image_paths[0])
    history_files = _history_files(history_path)

    with caplog.at_level("WARNING"):
        results = upload.check_upload_history(
            image_paths,
            _metadatas_from_process=[
                _image(image_path, "current-sequence", float(index))
                for index, image_path in enumerate(image_paths)
            ],
        )

    assert results == [
        _result(
            "image",
            "current-sequence",
            image_paths,
            [image_paths[0], image_paths[2]],
        )
    ]
    for record_path in invalid_records:
        assert record_path.name in caplog.text
    assert _history_files(history_path) == history_files


def _write_checksum_record(history_path: Path, md5sum: str, record: dict) -> None:
    """Write an upload history record as earlier versions did, by checksum"""
    path = history_path / md5sum[:2] / f"{md5sum[2:]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))


def test_check_upload_history_does_not_use_records_by_checksum(tmp_path, monkeypatch):
    """
    Files recorded by checksum, before uploads were recorded by fingerprint,
    are not found: they would be uploaded again
    """
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    zip_path = tmp_path / "sequence.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.comment = json.dumps({"sequence_md5sum": "1" * 32}).encode()
    image_md5sum = hashlib.md5(b"image").hexdigest()
    _write_checksum_record(
        history_path,
        hashlib.md5(image_md5sum.encode()).hexdigest(),
        {
            "summary": {"upload_end_time": 1.0},
            "descs": [
                {
                    "filename": str(image_path),
                    "filetype": "image",
                    "md5sum": image_md5sum,
                    "filesize": 5,
                }
            ],
        },
    )
    _write_checksum_record(
        history_path, hashlib.md5(b"video").hexdigest(), {"summary": {}}
    )
    _write_checksum_record(history_path, "1" * 32, {"summary": {}})
    reads = _count_reads(monkeypatch)

    results = upload.check_upload_history(
        [image_path, video_path, zip_path],
        _metadatas_from_process=[
            _image(image_path, "sequence", 1.0),
            _video(video_path),
        ],
    )

    assert results == [
        _result("image", "sequence", [image_path], []),
        _result("camm", None, [video_path], []),
        _result("zip", None, [zip_path], []),
    ]
    assert reads == []


def test_check_upload_history_without_history(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", "")
    monkeypatch.chdir(tmp_path)
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    reads = _count_reads(monkeypatch)

    results = upload.check_upload_history(
        [video_path], _metadatas_from_process=[_video(video_path)]
    )

    assert results == [_result("camm", None, [video_path], [])]
    assert reads == []
    assert [path.name for path in tmp_path.iterdir()] == ["video.mp4"]


def test_check_upload_history_for_zip(tmp_path, monkeypatch):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    zip_path = tmp_path / "sequence.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.comment = json.dumps({"sequence_md5sum": "1" * 32}).encode()

    results = upload.check_upload_history([zip_path], _metadatas_from_process=[])
    assert results == [_result("zip", None, [zip_path], [])]

    _record_upload(zip_path)
    history_files = _history_files(history_path)

    results = upload.check_upload_history([zip_path], _metadatas_from_process=[])
    assert results == [_result("zip", None, [zip_path], [zip_path])]
    assert _history_files(history_path) == history_files


def test_check_upload_history_skips_the_apple_double_file_of_a_zip(
    tmp_path, monkeypatch, caplog
):
    """
    The AppleDouble file (._NAME) that macOS writes beside a zip file, named
    like a zip file but none, was read as one and stopped the run
    """
    monkeypatch.setattr(
        constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(tmp_path / "history")
    )
    zip_path = tmp_path / "sequence.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.comment = json.dumps({"sequence_md5sum": "1" * 32}).encode()
    apple_double = tmp_path / "._sequence.zip"
    apple_double.write_bytes(b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X")

    with caplog.at_level("WARNING"):
        results = upload.check_upload_history(
            [apple_double, zip_path], _metadatas_from_process=[]
        )

    assert [result["filenames"] for result in results] == [[str(zip_path)]]
    assert (
        f"Skipping {apple_double}, which is not a supported image or video"
        in caplog.text
    )


def test_check_upload_history_command_outputs_json_without_authentication(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(tmp_path / "history")
    )

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    metadata = _image(image_path, "sequence", 1.0)
    desc_path = tmp_path / "description.json"
    desc_path.write_bytes(DescriptionJSONSerializer.serialize([metadata]))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mapillary_tools",
            "check_upload_history",
            str(image_path),
            "--desc_path",
            str(desc_path),
        ],
    )
    commands.main()

    results = json.loads(capsys.readouterr().out)
    assert len(results) == 1
    assert results[0]["sequence_uuid"] == "sequence"
    assert results[0]["filenames"] == [str(image_path)]
    assert results[0]["already_uploaded_filenames"] == []
    assert results[0]["already_uploaded"] is False


def _setup_dry_run_upload(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    history_path = tmp_path / "history"
    upload_path = tmp_path / "uploads"
    upload_path.mkdir()
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))
    monkeypatch.setattr(constants, "MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN", True)
    monkeypatch.setenv("MAPILLARY_UPLOAD_ENDPOINT", str(upload_path))
    monkeypatch.setenv(
        "MAPILLARY_TOOLS_UPLOAD_CACHE_DIR", str(tmp_path / "upload_cache")
    )
    return history_path, upload_path


def _uploaded_files(upload_path: Path) -> list[str]:
    return sorted(path.name for path in upload_path.iterdir() if path.is_file())


def test_upload_records_images_and_skips_them_the_next_time(
    tmp_path, monkeypatch, caplog
):
    history_path, upload_path = _setup_dry_run_upload(tmp_path, monkeypatch)
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_paths = []
    for name in ["DSC00001.JPG", "DSC00497.JPG"]:
        shutil.copy(TEST_IMAGE_DIR.joinpath(name), image_dir)
        image_paths.append(image_dir.joinpath(name))

    def _metadatas() -> list[types.Metadata]:
        return [
            types.ImageMetadata(
                filename=image_path,
                lat=58.5927694 + idx * 0.0001,
                lon=16.1840944,
                alt=None,
                angle=None,
                time=1613222681.0 + idx,
                MAPSequenceUUID="sequence",
                filesize=image_path.stat().st_size,
            )
            for idx, image_path in enumerate(image_paths)
        ]

    reads = _count_reads(monkeypatch)
    upload.upload(
        image_dir,
        {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
        num_upload_workers=1,
        _metadatas_from_process=_metadatas(),
        dry_run=True,
    )

    assert _uploaded_files(upload_path)
    # No image is read in full for a checksum, only for its fingerprint
    # when recorded
    assert not [read for read in reads if read.startswith("md5:DSC")]
    [record_path] = history_path.glob(f"{history.UPLOADED_FILES_DIR}/*/*.json")
    record = json.loads(record_path.read_text())
    assert [
        (entry["filename"], entry["filesize"], entry["fingerprint"])
        for entry in record["files"]
    ] == [
        (
            os.path.abspath(image_path),
            image_path.stat().st_size,
            fingerprint.fingerprint_file(image_path),
        )
        for image_path in image_paths
    ]
    assert isinstance(record["summary"]["upload_end_time"], float)

    # check_upload_history agrees with upload
    [result] = upload.check_upload_history(
        image_dir, _metadatas_from_process=_metadatas()
    )
    assert result["already_uploaded"] is True

    for name in _uploaded_files(upload_path):
        upload_path.joinpath(name).unlink()
    caplog.clear()
    upload.upload(
        image_dir,
        {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
        num_upload_workers=1,
        _metadatas_from_process=_metadatas(),
        dry_run=True,
    )

    assert _uploaded_files(upload_path) == []
    assert (
        "UploadedAlready: Skipping sequence_sequence, already uploaded" in caplog.text
    )


def test_upload_skips_an_uploaded_video_without_reading_it_for_the_session_key(
    tmp_path, monkeypatch, caplog
):
    _, upload_path = _setup_dry_run_upload(tmp_path, monkeypatch)
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video_path = video_dir / "video.mp4"
    _write_empty_mp4(video_path, 60000)

    def _metadatas() -> list[types.Metadata]:
        return [
            types.VideoMetadata(
                video_path,
                types.FileType.VIDEO,
                points=[
                    geo.Point(time=0.0, lat=1, lon=1, alt=None, angle=None),
                    geo.Point(time=1.0, lat=1.0001, lon=1, alt=None, angle=None),
                ],
            )
        ]

    session_keys: list[str | None] = []
    gen_session_key = uploader.Uploader._gen_session_key

    def _gen_session_key(self, fp, progress):
        session_keys.append(progress.get("import_path"))
        return gen_session_key(self, fp, progress)

    monkeypatch.setattr(uploader.Uploader, "_gen_session_key", _gen_session_key)
    reads = _count_reads(monkeypatch)

    def _upload(reupload: bool = False):
        upload.upload(
            video_dir,
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            num_upload_workers=1,
            _metadatas_from_process=_metadatas(),
            reupload=reupload,
            dry_run=True,
        )

    _upload()
    assert session_keys == [str(video_path)]
    # The video is read in full once, for the session key: not for a checksum
    assert [read for read in reads if read.startswith("md5:")] == ["md5:"]
    assert _uploaded_files(upload_path)

    for name in _uploaded_files(upload_path):
        upload_path.joinpath(name).unlink()
    caplog.clear()
    _upload()

    assert session_keys == [str(video_path)]
    assert _uploaded_files(upload_path) == []
    assert "UploadedAlready: Skipping video.mp4, already uploaded" in caplog.text

    caplog.clear()
    _upload(reupload=True)

    assert session_keys == [str(video_path), str(video_path)]
    assert _uploaded_files(upload_path)
    assert "Reuploading video.mp4, despite being uploaded" in caplog.text


def test_upload_records_a_zip_file_and_skips_it_the_next_time(
    tmp_path, monkeypatch, caplog
):
    history_path, upload_path = _setup_dry_run_upload(tmp_path, monkeypatch)
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    shutil.copy(TEST_IMAGE_DIR.joinpath("DSC00001.JPG"), image_dir)
    image_path = image_dir.joinpath("DSC00001.JPG")
    zip_dir = tmp_path / "zips"
    uploader.ZipUploader.zip_images(
        [
            types.ImageMetadata(
                filename=image_path,
                lat=58.5927694,
                lon=16.1840944,
                alt=None,
                angle=None,
                time=1613222681.0,
                MAPSequenceUUID="sequence",
                filesize=image_path.stat().st_size,
            )
        ],
        zip_dir,
    )
    [zip_path] = zip_dir.glob("*.zip")

    def _upload():
        upload.upload(
            zip_dir,
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            num_upload_workers=1,
            _metadatas_from_process=[],
            dry_run=True,
        )

    _upload()
    assert _uploaded_files(upload_path)
    [record_path] = history_path.glob(f"{history.UPLOADED_FILES_DIR}/*/*.json")
    assert [
        entry["filename"] for entry in json.loads(record_path.read_text())["files"]
    ] == [os.path.abspath(zip_path)]
    assert upload.check_upload_history(zip_dir, _metadatas_from_process=[]) == [
        _result("zip", None, [zip_path], [zip_path])
    ]

    for name in _uploaded_files(upload_path):
        upload_path.joinpath(name).unlink()
    caplog.clear()
    _upload()

    assert _uploaded_files(upload_path) == []
    assert f"UploadedAlready: Skipping {zip_path.name}, already uploaded" in caplog.text
