# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
import subprocess
from pathlib import Path

import py.path
import pytest

from .fixtures import run_command


def _run_process_with_report(import_paths: list[Path], output_dir: Path):
    desc_path = output_dir / "description.json"
    report_path = output_dir / "process-report.json"
    run_command(
        [
            "--skip_process_errors",
            "--desc_path",
            str(desc_path),
            "--process_report_path",
            str(report_path),
            *(str(path) for path in import_paths),
        ],
        command="process",
    )
    return (
        json.loads(desc_path.read_text(encoding="utf-8")),
        json.loads(report_path.read_text(encoding="utf-8")),
    )


def test_process_report_counts_recognized_errors_and_explicit_unsupported(
    tmpdir: py.path.local,
):
    root = Path(str(tmpdir))
    broken_image = root / "broken.JPG"
    unsupported = root / "unsupported.WEBP"
    broken_image.write_bytes(b"not an image")
    unsupported.write_bytes(b"not supported")

    descs, report = _run_process_with_report([broken_image, unsupported], root)

    descs_by_filename = {desc["filename"]: desc for desc in descs}
    assert set(descs_by_filename) == {
        str(broken_image.resolve()),
        str(unsupported.resolve()),
    }
    assert "error" in descs_by_filename[str(broken_image.resolve())]
    assert descs_by_filename[str(unsupported.resolve())]["error"] == {
        "type": "MapillaryUnsupportedFileError",
        "message": "Not a supported image or video",
    }
    assert report == {
        "schema_version": 1,
        "discovered_file_count": 2,
        "processed_file_count": 1,
        "skipped_file_count": 1,
        "skipped_files": [
            {
                "filename": str(unsupported.resolve()),
                "category": "unsupported",
                "reason_code": "unsupported_format",
                "details": {"extension": ".webp"},
            }
        ],
    }


def test_process_report_filters_folder_sidecars_but_reports_explicit_sidecars(
    tmpdir: py.path.local,
):
    root = Path(str(tmpdir))
    broken_image = root / "broken.jpg"
    unsupported = root / "unsupported.webp"
    sidecar = root / "track.GPX"
    broken_image.write_bytes(b"not an image")
    unsupported.write_bytes(b"not supported")
    sidecar.write_text("metadata", encoding="utf-8")
    (root / "Thumbs.db").write_bytes(b"system")
    (root / ".hidden.webp").write_bytes(b"hidden")
    macosx = root / "__MACOSX"
    macosx.mkdir()
    (macosx / "resource.webp").write_bytes(b"system")

    _, folder_report = _run_process_with_report([root], root)
    assert folder_report["discovered_file_count"] == 2
    assert folder_report["processed_file_count"] == 1
    assert folder_report["skipped_file_count"] == 1
    assert folder_report["skipped_files"][0]["filename"] == str(unsupported.resolve())

    explicit_output = root / "explicit"
    explicit_output.mkdir()
    descs, explicit_report = _run_process_with_report([sidecar], explicit_output)
    assert [desc["error"]["type"] for desc in descs] == [
        "MapillaryUnsupportedFileError"
    ]
    assert explicit_report["discovered_file_count"] == 1
    assert explicit_report["processed_file_count"] == 0
    assert explicit_report["skipped_file_count"] == 1
    assert explicit_report["skipped_files"][0]["filename"] == str(sidecar.resolve())
    assert explicit_report["skipped_files"][0]["details"] == {"extension": ".gpx"}


def test_process_without_report_fails_an_explicit_unsupported_file(
    tmpdir: py.path.local,
):
    root = Path(str(tmpdir))
    unsupported = root / "unsupported.webp"
    desc_path = root / "description.json"
    unsupported.write_bytes(b"not supported")

    run_command(
        [
            "--skip_process_errors",
            "--desc_path",
            str(desc_path),
            str(unsupported),
        ],
        command="process",
    )

    assert json.loads(desc_path.read_text(encoding="utf-8")) == [
        {
            "error": {
                "type": "MapillaryUnsupportedFileError",
                "message": "Not a supported image or video",
            },
            "filename": str(unsupported.resolve()),
        }
    ]
    assert not (root / "process-report.json").exists()


def test_process_fails_an_explicit_unsupported_file(tmpdir: py.path.local):
    """It was left out with only a warning, and the run succeeded"""
    root = Path(str(tmpdir))
    unsupported = root / "unsupported.webp"
    unsupported_in_folder = root / "folder" / "unsupported.webp"
    desc_path = root / "description.json"
    unsupported.write_bytes(b"not supported")
    unsupported_in_folder.parent.mkdir()
    unsupported_in_folder.write_bytes(b"not supported")

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_command(
            [
                "--desc_path",
                str(desc_path),
                str(unsupported),
                str(unsupported_in_folder.parent),
            ],
            command="process",
        )

    assert exc_info.value.returncode == 6
    # Only the file named explicitly: those found in a folder are left alone
    assert [
        (desc["filename"], desc["error"]["type"])
        for desc in json.loads(desc_path.read_text(encoding="utf-8"))
    ] == [(str(unsupported.resolve()), "MapillaryUnsupportedFileError")]
