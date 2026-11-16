# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import json
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest
from mapillary_tools import constants, geo, history, types, upload
from mapillary_tools.commands import __main__ as commands
from mapillary_tools.serializer.description import DescriptionJSONSerializer

from .test_uploader import (
    _count_checksum_reads,
    _rewrite_keeping_size_and_mtime,
    _write_empty_mp4,
)


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


def test_check_upload_history_for_images_and_video(tmp_path, monkeypatch):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    first_image_path = tmp_path / "first.jpg"
    second_image_path = tmp_path / "second.jpg"
    video_path = tmp_path / "video.mp4"
    first_image_path.write_bytes(b"first image")
    second_image_path.write_bytes(b"second image")
    video_path.write_bytes(b"video")

    metadatas = [
        _image(second_image_path, "sequence", 2.0),
        _image(first_image_path, "sequence", 1.0),
        types.VideoMetadata(
            filename=video_path,
            filetype=types.FileType.CAMM,
            points=[],
        ),
    ]

    results = upload.check_upload_history(
        [first_image_path, second_image_path, video_path],
        _metadatas_from_process=metadatas,
    )

    first_md5 = hashlib.md5(first_image_path.read_bytes()).hexdigest()
    second_md5 = hashlib.md5(second_image_path.read_bytes()).hexdigest()
    expected_sequence_md5 = hashlib.md5(f"{first_md5}{second_md5}".encode()).hexdigest()
    expected_video_md5 = hashlib.md5(video_path.read_bytes()).hexdigest()

    assert results == [
        {
            "file_type": "image",
            "sequence_uuid": "sequence",
            "sequence_md5sum": expected_sequence_md5,
            "filenames": [str(first_image_path), str(second_image_path)],
            "already_uploaded_filenames": [],
            "already_uploaded": False,
        },
        {
            "file_type": "camm",
            "sequence_uuid": None,
            "sequence_md5sum": expected_video_md5,
            "filenames": [str(video_path)],
            "already_uploaded_filenames": [],
            "already_uploaded": False,
        },
    ]

    history.write_history(
        expected_sequence_md5,
        {"version": "test"},
        {"upload_end_time": 123.0},
    )
    history_record_path = history.history_desc_path(expected_sequence_md5)
    history_record = history_record_path.read_bytes()

    results = upload.check_upload_history(
        [first_image_path, second_image_path, video_path],
        _metadatas_from_process=metadatas,
    )

    assert results[0]["already_uploaded"] is True
    assert results[0]["already_uploaded_filenames"] == [
        str(first_image_path),
        str(second_image_path),
    ]
    assert results[1]["already_uploaded"] is False
    assert results[1]["already_uploaded_filenames"] == []
    assert history_record_path.read_bytes() == history_record

    history.write_history(
        expected_video_md5,
        {"version": "test"},
        {"upload_end_time": 456.0},
    )
    results = upload.check_upload_history(
        [first_image_path, second_image_path, video_path],
        _metadatas_from_process=metadatas,
    )

    assert results[0]["already_uploaded"] is True
    assert results[1]["already_uploaded"] is True
    assert results[1]["already_uploaded_filenames"] == [str(video_path)]


def test_check_upload_history_for_zip(tmp_path, monkeypatch):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    zip_path = tmp_path / "sequence.zip"
    sequence_md5sum = "1" * 32
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.comment = json.dumps({"sequence_md5sum": sequence_md5sum}).encode()

    results = upload.check_upload_history(
        [zip_path],
        _metadatas_from_process=[],
    )
    assert results == [
        {
            "file_type": "zip",
            "sequence_uuid": None,
            "sequence_md5sum": sequence_md5sum,
            "filenames": [str(zip_path)],
            "already_uploaded_filenames": [],
            "already_uploaded": False,
        }
    ]

    history.write_history(
        sequence_md5sum,
        {"version": "test"},
        {"upload_end_time": 123.0},
    )
    history_record_path = history.history_desc_path(sequence_md5sum)
    history_record = history_record_path.read_bytes()

    results = upload.check_upload_history(
        [zip_path],
        _metadatas_from_process=[],
    )
    assert results[0]["already_uploaded_filenames"] == [str(zip_path)]
    assert results[0]["already_uploaded"] is True
    assert history_record_path.read_bytes() == history_record


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


def test_check_upload_history_matches_subset_of_uploaded_image_sequence(
    tmp_path, monkeypatch
):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    first_image_path = tmp_path / "first.jpg"
    second_image_path = tmp_path / "second.jpg"
    first_image_path.write_bytes(b"first image")
    second_image_path.write_bytes(b"second image")
    current_sequence = [
        _image(first_image_path, "current-sequence", 1.0),
        _image(second_image_path, "current-sequence", 2.0),
    ]
    types.update_sequence_md5sum(current_sequence)

    old_extra = _image(tmp_path / "old-extra.jpg", "old-sequence", 0.0)
    old_extra.md5sum = hashlib.md5(b"old extra").hexdigest()
    uploaded_sequence = [old_extra, *current_sequence]
    history.write_history(
        "1" * 32,
        {"version": "test"},
        {"upload_end_time": 123.0},
        uploaded_sequence,
    )

    results = upload.check_upload_history(
        [first_image_path, second_image_path],
        _metadatas_from_process=current_sequence,
    )

    assert len(results) == 1
    assert results[0]["sequence_md5sum"] != "1" * 32
    assert results[0]["already_uploaded_filenames"] == [
        str(first_image_path),
        str(second_image_path),
    ]
    assert results[0]["already_uploaded"] is True


def test_check_upload_history_reports_mixed_uploaded_image_subset(
    tmp_path, monkeypatch
):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    first_image_path = tmp_path / "first.jpg"
    second_image_path = tmp_path / "second.jpg"
    first_image_path.write_bytes(b"first image")
    second_image_path.write_bytes(b"second image")
    current_sequence = [
        _image(first_image_path, "current-sequence", 1.0),
        _image(second_image_path, "current-sequence", 2.0),
    ]
    types.update_sequence_md5sum(current_sequence)

    # The matching video checksum must not be mistaken for an uploaded image.
    matching_video = types.VideoMetadata(
        filename=tmp_path / "old-video.mp4",
        filetype=types.FileType.CAMM,
        points=[],
        md5sum=current_sequence[1].md5sum,
    )
    history.write_history(
        "2" * 32,
        {"version": "test"},
        {"upload_end_time": 123.0},
        [current_sequence[0], matching_video],
    )

    results = upload.check_upload_history(
        [first_image_path, second_image_path],
        _metadatas_from_process=current_sequence,
    )

    assert results[0]["already_uploaded_filenames"] == [str(first_image_path)]
    assert results[0]["already_uploaded"] is False


def test_check_upload_history_skips_malformed_records_and_preserves_file_order(
    tmp_path, monkeypatch
):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    image_paths = [tmp_path / f"image-{index}.jpg" for index in range(3)]
    for index, image_path in enumerate(image_paths):
        image_path.write_bytes(f"image {index}".encode())
    current_sequence = [
        _image(image_path, "current-sequence", float(index))
        for index, image_path in enumerate(image_paths)
    ]
    types.update_sequence_md5sum(current_sequence)

    malformed_records = {
        history_path / "00" / "invalid-json.json": b"{",
        history_path / "01" / "invalid-record.json": b"[]",
        history_path / "02" / "invalid-descriptions.json": json.dumps(
            {
                "descs": [
                    None,
                    {"filetype": "image", "md5sum": 123},
                    {"filetype": "image", "md5sum": "not-an-md5"},
                ]
            }
        ).encode(),
    }
    for record_path, contents in malformed_records.items():
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_bytes(contents)

    valid_record_path = history_path / "03" / "valid.json"
    valid_record_path.parent.mkdir(parents=True)
    valid_record_path.write_text(
        json.dumps(
            {
                "descs": [
                    {
                        "filetype": "image",
                        "md5sum": current_sequence[2].md5sum.upper(),
                    },
                    {
                        "filetype": "video",
                        "md5sum": current_sequence[1].md5sum,
                    },
                    {
                        "filetype": "image",
                        "md5sum": current_sequence[0].md5sum.upper(),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    history_snapshot = {
        path: path.read_bytes() for path in history_path.glob("*/*.json")
    }

    results = upload.check_upload_history(
        image_paths,
        _metadatas_from_process=current_sequence,
    )

    assert len(results) == 1
    assert results[0]["already_uploaded_filenames"] == [
        str(image_paths[0]),
        str(image_paths[2]),
    ]
    assert results[0]["already_uploaded"] is False
    assert {
        path: path.read_bytes() for path in history_path.glob("*/*.json")
    } == history_snapshot


def test_check_upload_history_treats_corrupt_record_as_not_uploaded(
    tmp_path, monkeypatch
):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    metadata = _image(image_path, "sequence", 1.0)
    sequence_md5sum = types.update_sequence_md5sum([metadata])
    history_record_path = history.history_desc_path(sequence_md5sum)
    history_record_path.parent.mkdir(parents=True)
    history_record_path.write_bytes(b"\xff")

    results = upload.check_upload_history(
        [image_path],
        _metadatas_from_process=[metadata],
    )

    assert results[0]["already_uploaded"] is False
    assert results[0]["already_uploaded_filenames"] == []


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

    captured = capsys.readouterr()
    # Only the results go to stdout, on one line: the progress goes to stderr
    assert captured.out.endswith("\n")
    assert captured.out.count("\n") == 1
    assert "Checksumming IMAGE" in captured.err
    results = json.loads(captured.out)
    assert len(results) == 1
    assert results[0]["sequence_uuid"] == "sequence"
    assert results[0]["filenames"] == [str(image_path)]
    assert results[0]["already_uploaded_filenames"] == []
    assert results[0]["already_uploaded"] is False

    # Checksums taken from the cache: same output
    commands.main()
    assert capsys.readouterr().out == captured.out


def _history_files(history_path: Path) -> dict[Path, bytes]:
    """The files of the upload history but the checksum cache"""
    return {
        path: path.read_bytes()
        for path in history_path.rglob("*")
        if path.is_file() and not path.name.startswith("checksum_cache")
    }


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _sequence_md5(*paths: Path) -> str:
    return hashlib.md5("".join(_md5(path) for path in paths).encode()).hexdigest()


def test_check_upload_history_caches_checksums(tmp_path, monkeypatch):
    """
    A second check reads no file to compute its checksum, and returns the
    same results, for uploaded, partly uploaded and new sequences and videos
    """
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))

    paths: dict[str, Path] = {}
    for name in [
        "uploaded-1.jpg",
        "uploaded-2.jpg",
        "partly-1.jpg",
        "partly-2.jpg",
        "new-1.jpg",
        "uploaded.mp4",
        "new.mp4",
    ]:
        paths[name] = tmp_path / name
        paths[name].write_bytes(f"contents of {name}".encode())
    zip_path = tmp_path / "sequence.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.comment = json.dumps({"sequence_md5sum": "3" * 32}).encode()

    def _metadatas() -> list[types.Metadata]:
        return [
            _image(paths["uploaded-2.jpg"], "uploaded", 2.0),
            _image(paths["uploaded-1.jpg"], "uploaded", 1.0),
            _image(paths["partly-1.jpg"], "partly", 1.0),
            _image(paths["partly-2.jpg"], "partly", 2.0),
            _image(paths["new-1.jpg"], "new", 1.0),
            types.VideoMetadata(
                filename=paths["uploaded.mp4"],
                filetype=types.FileType.CAMM,
                points=[],
            ),
            types.VideoMetadata(
                filename=paths["new.mp4"], filetype=types.FileType.GOPRO, points=[]
            ),
        ]

    uploaded_sequence_md5 = _sequence_md5(
        paths["uploaded-1.jpg"], paths["uploaded-2.jpg"]
    )
    history.write_history(uploaded_sequence_md5, {}, {"upload_end_time": 1.0})
    history.write_history(_md5(paths["uploaded.mp4"]), {}, {"upload_end_time": 2.0})
    history.write_history("3" * 32, {}, {"upload_end_time": 3.0})
    # Only the first image of "partly" was uploaded, in another sequence
    partly_uploaded = _image(paths["partly-1.jpg"], "other", 1.0)
    partly_uploaded.md5sum = _md5(paths["partly-1.jpg"])
    history.write_history("4" * 32, {}, {"upload_end_time": 4.0}, [partly_uploaded])

    def _result(file_type, sequence_uuid, md5sum, names, uploaded_names):
        return {
            "file_type": file_type,
            "sequence_uuid": sequence_uuid,
            "sequence_md5sum": md5sum,
            "filenames": [str(paths[name]) for name in names],
            "already_uploaded_filenames": [str(paths[name]) for name in uploaded_names],
            "already_uploaded": names == uploaded_names,
        }

    expected = [
        _result(
            "image",
            "uploaded",
            uploaded_sequence_md5,
            ["uploaded-1.jpg", "uploaded-2.jpg"],
            ["uploaded-1.jpg", "uploaded-2.jpg"],
        ),
        _result(
            "image",
            "partly",
            _sequence_md5(paths["partly-1.jpg"], paths["partly-2.jpg"]),
            ["partly-1.jpg", "partly-2.jpg"],
            ["partly-1.jpg"],
        ),
        _result("image", "new", _sequence_md5(paths["new-1.jpg"]), ["new-1.jpg"], []),
        _result("gopro", None, _md5(paths["new.mp4"]), ["new.mp4"], []),
        _result(
            "camm",
            None,
            _md5(paths["uploaded.mp4"]),
            ["uploaded.mp4"],
            ["uploaded.mp4"],
        ),
        {
            "file_type": "zip",
            "sequence_uuid": None,
            "sequence_md5sum": "3" * 32,
            "filenames": [str(zip_path)],
            "already_uploaded_filenames": [str(zip_path)],
            "already_uploaded": True,
        },
    ]
    history_files = _history_files(history_path)
    reads = _count_checksum_reads(monkeypatch)

    results = upload.check_upload_history(
        [tmp_path], _metadatas_from_process=_metadatas()
    )
    assert results == expected
    assert sorted(reads) == sorted(paths)
    assert (history_path / "checksum_cache").is_file()

    reads.clear()
    results = upload.check_upload_history(
        [tmp_path], _metadatas_from_process=_metadatas()
    )
    assert results == expected
    assert reads == []

    # Only the checksum cache is written
    assert _history_files(history_path) == history_files


def test_upload_after_check_upload_history_reads_no_checksums(
    tmp_path, monkeypatch, caplog
):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))
    monkeypatch.setattr(constants, "MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN", True)
    monkeypatch.setenv(
        "MAPILLARY_TOOLS_UPLOAD_CACHE_DIR", str(tmp_path / "upload_cache")
    )

    import_path = tmp_path / "import"
    import_path.mkdir()
    image_data = Path("tests/unit/data/test_exif.jpg").read_bytes()
    image_paths = [import_path / "first.jpg", import_path / "second.jpg"]
    image_paths[0].write_bytes(image_data)
    # A different image: change a byte of the image data
    second_image_data = bytearray(image_data)
    second_image_data[-10] = 0x01 if second_image_data[-10] != 0x01 else 0x02
    image_paths[1].write_bytes(bytes(second_image_data))
    video_path = import_path / "video.mp4"
    _write_empty_mp4(video_path, 60000)
    input_names = {path.name for path in [*image_paths, video_path]}

    def _metadatas() -> list[types.Metadata]:
        return [
            *(
                types.ImageMetadata(
                    filename=path,
                    lat=58.5927694,
                    lon=16.1840944 + idx * 0.0001,
                    alt=None,
                    angle=None,
                    time=1613222681.14 + idx,
                    MAPSequenceUUID="sequence",
                    filesize=path.stat().st_size,
                )
                for idx, path in enumerate(image_paths)
            ),
            types.VideoMetadata(
                filename=video_path,
                filetype=types.FileType.VIDEO,
                points=[
                    geo.Point(time=0.0, lat=1, lon=1, alt=None, angle=None),
                    geo.Point(time=1.0, lat=1.0001, lon=1, alt=None, angle=None),
                ],
            ),
        ]

    reads = _count_checksum_reads(monkeypatch)
    results = upload.check_upload_history(
        import_path, _metadatas_from_process=_metadatas()
    )
    assert [result["already_uploaded"] for result in results] == [False, False]
    assert sorted(reads) == sorted(input_names)

    reads.clear()
    upload.upload(
        import_path,
        {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
        num_upload_workers=1,
        _metadatas_from_process=_metadatas(),
        dry_run=True,
    )
    # Only the uploaded streams were read for checksums, not the files
    assert not set(reads) & input_names
    assert "UploadedAlready" not in caplog.text
    assert history.read_history_record(results[0]["sequence_md5sum"]) is not None
    assert history.read_history_record(results[1]["sequence_md5sum"]) is not None

    reads.clear()
    results_after_upload = upload.check_upload_history(
        import_path, _metadatas_from_process=_metadatas()
    )
    assert reads == []
    assert results_after_upload == [
        {
            **result,
            "already_uploaded_filenames": result["filenames"],
            "already_uploaded": True,
        }
        for result in results
    ]


def test_check_upload_history_rereads_replaced_files(tmp_path, monkeypatch):
    """
    A file uploaded, then replaced by another of the same size and
    modification time, is not taken as uploaded
    """
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")

    def _metadatas() -> list[types.Metadata]:
        return [
            _image(image_path, "sequence", 1.0),
            types.VideoMetadata(
                filename=video_path, filetype=types.FileType.CAMM, points=[]
            ),
        ]

    history.write_history(_sequence_md5(image_path), {}, {"upload_end_time": 1.0})
    history.write_history(_md5(video_path), {}, {"upload_end_time": 2.0})
    results = upload.check_upload_history(
        [tmp_path], _metadatas_from_process=_metadatas()
    )
    assert [result["already_uploaded"] for result in results] == [True, True]

    for path, data in [(image_path, b"IMAGE"), (video_path, b"VIDEO")]:
        stat = path.stat()
        replacement_path = tmp_path / f"replacement-{path.name}"
        replacement_path.write_bytes(data)
        os.utime(replacement_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        os.replace(replacement_path, path)

    reads = _count_checksum_reads(monkeypatch)
    results = upload.check_upload_history(
        [tmp_path], _metadatas_from_process=_metadatas()
    )
    assert sorted(reads) == ["image.jpg", "video.mp4"]
    assert results[0]["sequence_md5sum"] == _sequence_md5(image_path)
    assert results[1]["sequence_md5sum"] == _md5(video_path)
    assert [result["already_uploaded"] for result in results] == [False, False]
    assert [result["already_uploaded_filenames"] for result in results] == [[], []]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="On Windows, os.stat has no change time: an edit in place that keeps the size and modification time keeps the file ID and creation time",
)
def test_check_upload_history_rereads_files_edited_in_place(tmp_path, monkeypatch):
    """
    A file uploaded, then edited keeping its size and modification time (as
    exiftool -P can), is not taken as uploaded
    """
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))
    image_paths = [tmp_path / "first.jpg", tmp_path / "second.jpg"]
    image_paths[0].write_bytes(b"first image")
    image_paths[1].write_bytes(b"second image")
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")

    def _metadatas() -> list[types.Metadata]:
        return [
            _image(image_paths[0], "sequence", 1.0),
            _image(image_paths[1], "sequence", 2.0),
            types.VideoMetadata(
                filename=video_path, filetype=types.FileType.CAMM, points=[]
            ),
        ]

    uploaded_image = _image(image_paths[1], "sequence", 2.0)
    uploaded_image.md5sum = _md5(image_paths[1])
    history.write_history(
        _sequence_md5(*image_paths), {}, {"upload_end_time": 1.0}, [uploaded_image]
    )
    history.write_history(_md5(video_path), {}, {"upload_end_time": 2.0})
    results = upload.check_upload_history(
        [tmp_path], _metadatas_from_process=_metadatas()
    )
    assert [result["already_uploaded"] for result in results] == [True, True]

    _rewrite_keeping_size_and_mtime(image_paths[1], b"SECOND IMAGE")
    _rewrite_keeping_size_and_mtime(video_path, b"VIDEO")

    reads = _count_checksum_reads(monkeypatch)
    results = upload.check_upload_history(
        [tmp_path], _metadatas_from_process=_metadatas()
    )
    assert sorted(reads) == ["second.jpg", "video.mp4"]
    assert results[0]["sequence_md5sum"] == _sequence_md5(*image_paths)
    assert results[0]["already_uploaded_filenames"] == []
    assert results[0]["already_uploaded"] is False
    assert results[1]["sequence_md5sum"] == _md5(video_path)
    assert results[1]["already_uploaded"] is False


def test_check_upload_history_without_history_creates_no_checksum_cache(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", "")
    monkeypatch.chdir(tmp_path)
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    metadatas = [
        _image(image_path, "sequence", 1.0),
        types.VideoMetadata(
            filename=video_path, filetype=types.FileType.CAMM, points=[]
        ),
    ]

    results = upload.check_upload_history([tmp_path], _metadatas_from_process=metadatas)

    assert results == [
        {
            "file_type": "image",
            "sequence_uuid": "sequence",
            "sequence_md5sum": _sequence_md5(image_path),
            "filenames": [str(image_path)],
            "already_uploaded_filenames": [],
            "already_uploaded": False,
        },
        {
            "file_type": "camm",
            "sequence_uuid": None,
            "sequence_md5sum": _md5(video_path),
            "filenames": [str(video_path)],
            "already_uploaded_filenames": [],
            "already_uploaded": False,
        },
    ]
    assert sorted(path.name for path in tmp_path.rglob("*")) == [
        "image.jpg",
        "video.mp4",
    ]


@pytest.mark.parametrize("failure", ["directory", "not_a_database", "write_error"])
def test_check_upload_history_with_unusable_checksum_cache(
    tmp_path, monkeypatch, caplog, failure
):
    history_path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))
    checksum_cache_path = history_path / "checksum_cache"
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image")
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    history.write_history(_md5(video_path), {}, {"upload_end_time": 1.0})

    if failure == "directory":
        checksum_cache_path.mkdir(parents=True)
        warning = "Not caching checksums in"
    elif failure == "not_a_database":
        checksum_cache_path.write_bytes(b"not a database" * 100)
        warning = "Not caching checksums in"
    else:

        def _set_many(*args, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(history.PersistentCache, "set_many", _set_many)
        warning = "Failed to cache checksums: disk I/O error"

    def _metadatas() -> list[types.Metadata]:
        return [
            _image(image_path, "sequence", 1.0),
            types.VideoMetadata(
                filename=video_path, filetype=types.FileType.CAMM, points=[]
            ),
        ]

    for _ in range(2):
        caplog.clear()
        with caplog.at_level("WARNING"):
            results = upload.check_upload_history(
                [tmp_path], _metadatas_from_process=_metadatas()
            )
        assert warning in caplog.text
        assert [result["sequence_md5sum"] for result in results] == [
            _sequence_md5(image_path),
            _md5(video_path),
        ]
        assert [result["already_uploaded"] for result in results] == [False, True]
