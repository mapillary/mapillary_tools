# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import json
import sys
import zipfile
from pathlib import Path

from mapillary_tools import constants, history, types, upload
from mapillary_tools.commands import __main__ as commands
from mapillary_tools.serializer.description import DescriptionJSONSerializer


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

    results = json.loads(capsys.readouterr().out)
    assert len(results) == 1
    assert results[0]["sequence_uuid"] == "sequence"
    assert results[0]["filenames"] == [str(image_path)]
    assert results[0]["already_uploaded_filenames"] == []
    assert results[0]["already_uploaded"] is False
