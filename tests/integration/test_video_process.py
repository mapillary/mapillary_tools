# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import functools
import subprocess
import tempfile
from pathlib import Path

import exifread
import py.path
import pytest

from .fixtures import (
    assert_contains_image_descs,
    pytest_skip_if_not_ffmpeg_installed,
    run_command,
    run_process_for_descs,
    setup_data,
)


run_video_process_for_descs = functools.partial(
    run_process_for_descs, command="video_process"
)

run_sample_video = functools.partial(run_command, command="sample_video")


def test_sample_video_relpath():
    pytest_skip_if_not_ffmpeg_installed()

    with tempfile.TemporaryDirectory() as dir:
        run_sample_video(["--rerun", "tests/data/gopro_data/hero8.mp4", str(dir)])

    with tempfile.TemporaryDirectory() as dir:
        run_sample_video(
            [
                "--rerun",
                "--video_start_time",
                "2021_10_10_10_10_10_123",
                "tests/data",
                str(dir),
            ]
        )


def test_sample_video_without_video_time(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    video_dir = setup_data.join("videos")
    root_sample_dir = video_dir.join("mapillary_sampled_video_frames")

    for input_path in [video_dir, video_dir.join("sample-5s.mp4")]:
        with pytest.raises(subprocess.CalledProcessError) as ex:
            run_sample_video(
                [
                    "--video_sample_interval=2",
                    "--video_sample_distance=-1",
                    "--rerun",
                    input_path,
                ]
            )
        assert 7 == ex.value.returncode, ex.value.stderr

        if root_sample_dir.exists():
            assert len(root_sample_dir.listdir()) == 0

        run_sample_video(
            [
                "--video_sample_interval=2",
                "--video_sample_distance=-1",
                "--skip_sample_errors",
                "--rerun",
                input_path,
            ]
        )
        if root_sample_dir.exists():
            assert len(root_sample_dir.listdir()) == 0


def test_sample_video_specify_video_start_time(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    video_dir = setup_data.join("videos")
    root_sample_dir = video_dir.join("mapillary_sampled_video_frames")

    for input_path in [video_dir, video_dir.join("sample-5s.mp4")]:
        run_sample_video(
            [
                "--video_sample_interval=2",
                "--video_sample_distance=-1",
                "--video_start_time=2021_10_10_10_10_10_123",
                "--rerun",
                input_path,
            ]
        )
        samples = root_sample_dir.join("sample-5s.mp4").listdir()
        samples.sort()
        times = []
        for s in samples:
            with s.open("rb") as fp:
                tags = exifread.process_file(fp)
                times.append(tags["EXIF DateTimeOriginal"].values)
        assert (
            "2021:10:10 10:10:10",
            "2021:10:10 10:10:12",
            "2021:10:10 10:10:14",
        ) == tuple(times)


def test_video_process(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    video_dir = setup_data.join("videos")
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")
    gpx_start_time = "2025_03_14_07_00_00_000"
    gpx_end_time = "2025_03_14_07_01_33_624"
    video_start_time = "2025_03_14_07_00_00_000"

    descs = run_video_process_for_descs(
        [
            "--video_sample_interval=2",
            "--video_sample_distance=-1",
            *["--video_start_time", video_start_time],
            "--geotag_source=gpx",
            *["--geotag_source_path", str(gpx_file)],
            str(video_dir),
            str(video_dir.join("my_samples")),
        ]
    )
    assert 3 == len(descs)
    assert 0 == len([d for d in descs if "error" in d])


def test_video_process_sample_with_multiple_distances(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    video_dir = setup_data.join("gopro_data")
    for distance in [0, 2.4, 100]:
        descs = run_video_process_for_descs(
            [
                "--video_sample_distance",
                str(distance),
                "--rerun",
                str(video_dir),
                str(video_dir.join("my_samples")),
            ]
        )
        if distance == 100:
            assert 1 == len(descs)
        else:
            assert len(descs) > 1


def test_video_process_sample_with_distance(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    video_dir = setup_data.join("gopro_data")
    sample_dir = Path(setup_data, "gopro_data", "my_samples")

    for options in [
        ["--video_sample_distance=6"],
        ["--video_sample_distance=6", "--video_sample_interval=-2"],
    ]:
        descs = run_video_process_for_descs(
            [
                *options,
                str(video_dir),
                str(video_dir.join("my_samples")),
            ]
        )
        assert_contains_image_descs(
            descs,
            [
                {
                    "filename": str(
                        Path(
                            sample_dir,
                            "max-360mode.mp4",
                            "max-360mode_0_000001.jpg",
                        )
                    ),
                    "filetype": "image",
                    "MAPLatitude": 33.1266719,
                    "MAPLongitude": -117.3273063,
                    "MAPCaptureTime": "2019_11_18_15_44_47_862",
                    "MAPAltitude": -22.18,
                    "MAPCompassHeading": {
                        "TrueHeading": 313.68,
                        "MagneticHeading": 313.68,
                    },
                    "MAPSequenceUUID": "0",
                    "MAPDeviceMake": "GoPro",
                    "MAPDeviceModel": "GoPro Max",
                    "MAPOrientation": 1,
                },
                {
                    "filename": str(
                        Path(
                            sample_dir,
                            "max-360mode.mp4",
                            "max-360mode_0_000002.jpg",
                        )
                    ),
                    "filetype": "image",
                    "MAPLatitude": 33.1267206,
                    "MAPLongitude": -117.3273345,
                    "MAPCaptureTime": "2019_11_18_15_44_53_159",
                    "MAPAltitude": -21.91,
                    "MAPCompassHeading": {
                        "TrueHeading": 330.82,
                        "MagneticHeading": 330.82,
                    },
                    "MAPSequenceUUID": "0",
                    "MAPDeviceMake": "GoPro",
                    "MAPDeviceModel": "GoPro Max",
                    "MAPOrientation": 1,
                },
                {
                    "filename": str(
                        Path(
                            sample_dir,
                            "max-360mode.mp4",
                            "max-360mode_0_000003.jpg",
                        )
                    ),
                    "filetype": "image",
                    "MAPLatitude": 33.1267702,
                    "MAPLongitude": -117.3273612,
                    "MAPCaptureTime": "2019_11_18_15_44_58_289",
                    "MAPAltitude": -22.58,
                    "MAPCompassHeading": {
                        "TrueHeading": 10.54,
                        "MagneticHeading": 10.54,
                    },
                    "MAPSequenceUUID": "0",
                    "MAPDeviceMake": "GoPro",
                    "MAPDeviceModel": "GoPro Max",
                    "MAPOrientation": 1,
                },
            ],
        )


def test_video_process_multiple_videos(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    sub_folder = setup_data.join("video_sub_folder").mkdir()
    video_path = setup_data.join("videos").join("sample-5s.mp4")
    video_path.copy(sub_folder)
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")
    gpx_start_time = "2025_03_14_07_00_00_000"
    gpx_end_time = "2025_03_14_07_01_33_624"
    descs = run_video_process_for_descs(
        [
            "--video_sample_interval=2",
            "--video_sample_distance=-1",
            *["--video_start_time", gpx_start_time],
            "--geotag_source=gpx",
            "--geotag_source_path",
            str(gpx_file),
            str(sub_folder),
            str(setup_data.join("my_samples")),
        ]
    )
    for d in descs:
        assert Path(d["filename"]).is_file(), d["filename"]
        assert "sample-5s.mp4" in d["filename"]
    assert 3 == len(descs)
    assert 0 == len([d for d in descs if "error" in d])
