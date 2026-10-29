# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
import subprocess
from pathlib import Path

import py.path
import pytest

from .fixtures import run_command, setup_data


def _run_process_with_report(import_paths: list[Path], output_dir: Path, *args: str):
    desc_path = output_dir / "description.json"
    report_path = output_dir / "process-report.json"
    run_command(
        [
            *args,
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
        "warnings": [],
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
    # Skipped with a warning, not failed, but still reported
    assert descs == []
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


def test_process_skips_named_sidecars_of_a_camera_folder(tmpdir: py.path.local):
    """
    Named along with the images, as by selecting all the files of a camera
    folder, the thumbnails, proxies and other files beside them failed the run
    """
    root = Path(str(tmpdir))
    folder = root / "100GOPRO"
    folder.mkdir()
    sidecars = [
        folder / "GH010001.THM",
        folder / "GL010001.LRV",
        folder / "GH010001.gpx",
        folder / "GH010001.xml",
        folder / ".DS_Store",
        # The AppleDouble file of an image, which has its extension
        folder / "._GOPR0001.JPG",
    ]
    for sidecar in sidecars:
        sidecar.write_bytes(b"\x00\x05\x16\x07 not an image")
    original = folder / "VID_00_001.insv"
    original.write_bytes(b"not stitched")

    descs, report = _run_process_with_report(sidecars, root)
    assert descs == []
    assert report["processed_file_count"] == 0
    assert sorted(skipped["filename"] for skipped in report["skipped_files"]) == sorted(
        str(sidecar.resolve()) for sidecar in sidecars
    )

    desc_path = root / "description.json"
    run_command(
        ["--desc_path", str(desc_path), *(str(sidecar) for sidecar in sidecars)],
        command="process",
    )
    assert json.loads(desc_path.read_text(encoding="utf-8")) == []

    # Any other unsupported file named with them still fails the run
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_command(
            [
                "--desc_path",
                str(desc_path),
                *(str(sidecar) for sidecar in sidecars),
                str(original),
            ],
            command="process",
        )
    assert exc_info.value.returncode == 6
    assert [
        (desc["filename"], desc["error"]["type"])
        for desc in json.loads(desc_path.read_text(encoding="utf-8"))
    ] == [(str(original.resolve()), "MapillaryUnsupportedFileError")]


def test_process_skips_named_companion_files_of_other_cameras_and_systems(
    tmpdir: py.path.local,
):
    """
    Named along with the images, DJI proxies, Apple photo edits, GPS tracks,
    XMP metadata and the files that Windows writes into folders failed the run
    """
    root = Path(str(tmpdir))
    folder = root / "DCIM"
    folder.mkdir()
    companions = [
        folder / "DJI_0001.LRF",
        folder / "IMG_0001.AAE",
        folder / "IMG_0001.XMP",
        folder / "track.kml",
        folder / "track.KMZ",
        folder / "ride.fit",
        folder / "Thumbs.db",
        folder / "desktop.ini",
    ]
    for companion in companions:
        companion.write_bytes(b"not an image")

    descs, report = _run_process_with_report(companions, root)
    assert descs == []
    assert report["processed_file_count"] == 0
    assert sorted(skipped["filename"] for skipped in report["skipped_files"]) == sorted(
        str(companion.resolve()) for companion in companions
    )

    desc_path = root / "description.json"
    run_command(
        ["--desc_path", str(desc_path), *(str(companion) for companion in companions)],
        command="process",
    )
    assert json.loads(desc_path.read_text(encoding="utf-8")) == []


def test_process_report_warns_to_align_a_gpx_with_the_video(
    setup_data: py.path.local,
):
    """
    A video without a GPS clock is assumed to start with its GPX track, which
    lasts far longer: the report names the video with what to align
    """
    video_path = Path(str(setup_data.join("videos", "sample-5s.mp4")))
    # 93.6 seconds of track for 5.76 seconds of video
    gpx_path = setup_data.join("gpx", "sf_30km_h.gpx")
    output_dir = Path(str(setup_data.join("..")))

    descs, report = _run_process_with_report(
        [video_path],
        output_dir,
        *["--geotag_source", "gpx", "--geotag_source_path", str(gpx_path)],
    )

    [desc] = descs
    assert "error" not in desc
    [warning] = report["warnings"]
    assert warning["filename"] == str(video_path.resolve())
    assert warning["type"] == "MapillaryGPXAlignmentWarning"
    assert (
        "Please align the video start time with the GPX track" in (warning["message"])
    )
    assert "If the video is a timelapse" in warning["message"]
    assert warning["vars"] == {
        "video_duration": pytest.approx(5.76, abs=0.01),
        "gpx_duration": pytest.approx(93.624),
        "gpx_start_time": "2025_03_14_07_00_00_000",
        "gpx_end_time": "2025_03_14_07_01_33_624",
        "gpx_longer": True,
    }


def test_process_report_has_no_warnings_for_a_video_without_any(
    setup_data: py.path.local,
):
    video_path = Path(str(setup_data.join("videos", "sample-5s.mp4")))
    output_dir = Path(str(setup_data.join("..")))

    _, report = _run_process_with_report([video_path], output_dir)

    assert report["warnings"] == []
