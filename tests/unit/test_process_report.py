# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
from pathlib import Path

from mapillary_tools import process_report


def _touch(path: Path, content: bytes = b"test") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_build_process_report_for_directory(tmp_path: Path):
    _touch(tmp_path / "capture.JPG")
    _touch(tmp_path / "clip.MP4")
    unsupported_paths = [
        _touch(tmp_path / "document.PDF"),
        _touch(tmp_path / "map.WEBP"),
        _touch(tmp_path / "nested" / "地图.HEIC"),
    ]

    # Folder discovery deliberately ignores hidden/system files and common
    # capture metadata or GPS sidecars.
    for path in [
        tmp_path / ".DS_Store",
        tmp_path / ".hidden.webp",
        tmp_path / "Thumbs.db",
        tmp_path / "track.GPX",
        tmp_path / "metadata.JSON",
        tmp_path / "metadata.XML",
        tmp_path / "video.LRV",
        tmp_path / "archive.ZIP",
        tmp_path / ".hidden" / "secret.webp",
        tmp_path / "__MACOSX" / "resource.webp",
    ]:
        _touch(path)

    report = process_report.build_process_report(tmp_path)

    assert report == {
        "schema_version": 1,
        "discovered_file_count": 5,
        "processed_file_count": 2,
        "skipped_file_count": 3,
        "skipped_files": [
            {
                "filename": str(path.resolve()),
                "category": "unsupported",
                "reason_code": "unsupported_format",
                "details": {"extension": path.suffix.lower()},
            }
            for path in sorted(unsupported_paths, key=lambda path: str(path.resolve()))
        ],
    }


def test_explicit_files_are_reported_even_when_folder_discovery_ignores_them(
    tmp_path: Path,
):
    track_path = _touch(tmp_path / "track.GPX")
    system_path = _touch(tmp_path / "Thumbs.db")
    hidden_path = _touch(tmp_path / ".unsupported")
    supported_path = _touch(tmp_path / "capture.JPEG")

    report = process_report.build_process_report(
        [tmp_path, track_path, system_path, hidden_path, supported_path]
    )

    assert report["discovered_file_count"] == 4
    assert report["processed_file_count"] == 1
    assert report["skipped_file_count"] == 3
    assert [item["filename"] for item in report["skipped_files"]] == sorted(
        [
            str(track_path.resolve()),
            str(system_path.resolve()),
            str(hidden_path.resolve()),
        ]
    )
    assert [item["details"]["extension"] for item in report["skipped_files"]] == [
        Path(filename).suffix.lower()
        for filename in sorted(
            [
                str(track_path.resolve()),
                str(system_path.resolve()),
                str(hidden_path.resolve()),
            ]
        )
    ]


def test_skip_subfolders_and_deterministic_utf8_output(tmp_path: Path):
    unsupported_path = _touch(tmp_path / "é.Unsupported")
    _touch(tmp_path / "nested" / "nested.webp")

    report = process_report.build_process_report(tmp_path, skip_subfolders=True)
    first_path = tmp_path / "report-first.json"
    second_path = tmp_path / "report-second.json"
    process_report.write_process_report(first_path, report)
    process_report.write_process_report(second_path, report)

    assert report["discovered_file_count"] == 1
    assert report["processed_file_count"] == 0
    assert report["skipped_file_count"] == 1
    assert report["skipped_files"][0]["filename"] == str(unsupported_path.resolve())
    assert report["skipped_files"][0]["details"] == {"extension": ".unsupported"}
    assert first_path.read_bytes() == second_path.read_bytes()
    assert "é" in first_path.read_text(encoding="utf-8")
    assert json.loads(first_path.read_text(encoding="utf-8")) == report


def test_empty_process_report(tmp_path: Path):
    assert process_report.build_process_report(tmp_path) == {
        "schema_version": 1,
        "discovered_file_count": 0,
        "processed_file_count": 0,
        "skipped_file_count": 0,
        "skipped_files": [],
    }
