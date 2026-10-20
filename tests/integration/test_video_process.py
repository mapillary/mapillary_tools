# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import functools
import json
import os
import re
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
    setup_config,
    setup_data,
    setup_upload,
    USERNAME,
)


run_video_process_for_descs = functools.partial(
    run_process_for_descs, command="video_process"
)

run_sample_video = functools.partial(run_command, command="sample_video")

# Not run_process_for_descs() for a run expected to fail: on Windows it would
# remove its description file while still holding it open, and the
# PermissionError would replace the CalledProcessError
run_video_process = functools.partial(run_command, command="video_process")


def test_sample_video_relpath():
    pytest_skip_if_not_ffmpeg_installed()

    # hero8.mp4's embedded GPS is filtered out entirely as noise, so it cannot
    # be sampled by distance. This test is about relative paths, not about that,
    # hence --skip_sample_errors.
    with tempfile.TemporaryDirectory() as dir:
        run_sample_video(
            [
                "--rerun",
                "--skip_sample_errors",
                "tests/data/gopro_data/hero8.mp4",
                str(dir),
            ]
        )

    with tempfile.TemporaryDirectory() as dir:
        run_sample_video(
            [
                "--rerun",
                "--skip_sample_errors",
                "--video_start_time",
                "2021_10_10_10_10_10_123",
                "tests/data",
                str(dir),
            ]
        )


def test_sample_video_by_distance_without_usable_gps(setup_data: py.path.local):
    """
    A video whose GPS cannot be read is not silently sampled into nothing.

    hero8.mp4 has 32 embedded GPS points and remove_noisy_points() drops all of
    them, so distance sampling has no positions to choose frames with. It used
    to log a warning, write no frames and still exit 0, which left the caller a
    success code and an empty import directory.
    """
    pytest_skip_if_not_ffmpeg_installed()

    video_path = setup_data.join("gopro_data").join("hero8.mp4")

    with tempfile.TemporaryDirectory() as dir:
        with pytest.raises(subprocess.CalledProcessError) as ex:
            run_sample_video(["--video_sample_distance=6", "--rerun", video_path, dir])
        assert 7 == ex.value.returncode, ex.value.stderr
        assert not list(Path(dir).iterdir())

    with tempfile.TemporaryDirectory() as dir:
        run_sample_video(
            [
                "--video_sample_distance=6",
                "--skip_sample_errors",
                "--rerun",
                video_path,
                dir,
            ]
        )


def test_video_process_by_distance_with_an_image_only_geotag_source(
    setup_data: py.path.local,
):
    """
    exif has nothing to read a video with; it geotags the frames. The video is
    sampled by its own GPS, as it was before --geotag_source reached sampling,
    instead of failing an assert.
    """
    pytest_skip_if_not_ffmpeg_installed()

    video_path = setup_data.join("gopro_data").join("max-360mode.mp4")

    with tempfile.TemporaryDirectory() as dir:
        descs = run_video_process_for_descs(
            [
                "--video_sample_distance=6",
                "--geotag_source=exif",
                str(video_path),
                dir,
            ]
        )

    assert descs
    assert all("error" not in desc for desc in descs), descs


def _with_creation_time(video: py.path.local, creation_time: str, dir: str) -> Path:
    """A copy of the video whose container records the creation time."""
    copy = Path(dir, video.basename)
    subprocess.run(
        [
            # as pytest_skip_if_not_ffmpeg_installed() finds it
            os.getenv("MAPILLARY_TOOLS_FFMPEG_PATH", "ffmpeg"),
            *["-loglevel", "error", "-y", "-i", str(video)],
            *["-c", "copy", "-metadata", f"creation_time={creation_time}"],
            str(copy),
        ],
        check=True,
    )
    return copy


def test_video_process_by_distance_places_a_gpx_by_the_video_start_time(
    setup_data: py.path.local,
):
    """
    The video has no GPS of its own. The GPX was placed as if it started with
    the video, so the frames were picked from, and stamped with, its first
    seconds, whatever --video_start_time said.
    """
    pytest_skip_if_not_ffmpeg_installed()

    video_path = setup_data.join("videos").join("sample-5s.mp4")
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")

    with tempfile.TemporaryDirectory() as dir:
        descs = run_video_process_for_descs(
            [
                "--video_sample_distance=3",
                *["--video_start_time", "2025_03_14_07_00_30_000"],
                "--geotag_source=gpx",
                *["--geotag_source_path", str(gpx_file)],
                str(video_path),
                dir,
            ]
        )

    assert descs
    assert all("error" not in desc for desc in descs), descs
    capture_times = sorted(desc["MAPCaptureTime"] for desc in descs)
    assert "2025_03_14_07_00_30_000" <= capture_times[0], capture_times
    assert capture_times[-1] < "2025_03_14_07_00_36_000", capture_times


def test_video_process_by_distance_refuses_to_guess_where_the_video_starts(
    setup_data: py.path.local,
):
    """
    Without --video_start_time, a GPX far longer than the video could start
    anywhere along it, so assuming that it starts with the video is a guess.
    """
    pytest_skip_if_not_ffmpeg_installed()

    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")

    with tempfile.TemporaryDirectory() as dir:
        video_path = _with_creation_time(
            setup_data.join("videos").join("sample-5s.mp4"), "2025-03-14T07:00:36Z", dir
        )
        with pytest.raises(subprocess.CalledProcessError) as ex:
            run_video_process(
                [
                    "--video_sample_distance=3",
                    "--geotag_source=gpx",
                    *["--geotag_source_path", str(gpx_file)],
                    str(video_path),
                    str(Path(dir, "samples")),
                ],
                capture_output=True,
                text=True,
            )

    assert 7 == ex.value.returncode, ex.value.stderr
    assert "specify --video_start_time" in ex.value.stderr.lower(), ex.value.stderr


def test_video_process_by_distance_with_a_gpx_that_misses_the_video(
    setup_data: py.path.local,
):
    """
    The track ends two hours before the video starts: the command fails, saying
    so, instead of passing with no frames.
    """
    pytest_skip_if_not_ffmpeg_installed()

    video_path = setup_data.join("videos").join("sample-5s.mp4")
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")

    with tempfile.TemporaryDirectory() as dir:
        with pytest.raises(subprocess.CalledProcessError) as ex:
            run_video_process(
                [
                    "--video_sample_distance=3",
                    *["--video_start_time", "2025_03_14_09_00_00_000"],
                    "--geotag_source=gpx",
                    *["--geotag_source_path", str(gpx_file)],
                    str(video_path),
                    str(Path(dir, "samples")),
                ],
                capture_output=True,
                text=True,
            )
        # sampling creates the sample directory up front, but writes no frames
        assert not list(Path(dir, "samples").rglob("*.jpg"))

    assert 7 == ex.value.returncode, ex.value.stderr
    assert "MapillaryOutsideGPXTrackError" in ex.value.stderr
    assert "misses the video" in ex.value.stderr


def test_video_process_by_distance_applies_the_interpolation_offset(
    setup_data: py.path.local,
):
    """
    The geotagging stage adds --interpolation_offset_time to each frame's time.
    Sampling ignored it, so it picked the last frames by positions within the
    GPX that the offset then pushed past its end, and they were rejected.
    """
    pytest_skip_if_not_ffmpeg_installed()

    video_path = setup_data.join("videos").join("sample-5s.mp4")
    # the track ends at 07:01:33.624
    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")

    with tempfile.TemporaryDirectory() as dir:
        descs = run_video_process_for_descs(
            [
                "--video_sample_distance=3",
                *["--video_start_time", "2025_03_14_07_01_28_000"],
                *["--interpolation_offset_time", "2"],
                "--geotag_source=gpx",
                *["--geotag_source_path", str(gpx_file)],
                str(video_path),
                dir,
            ]
        )

    assert descs
    assert all("error" not in desc for desc in descs), descs
    capture_times = sorted(desc["MAPCaptureTime"] for desc in descs)
    assert "2025_03_14_07_01_30_000" <= capture_times[0], capture_times
    assert capture_times[-1] <= "2025_03_14_07_01_33_624", capture_times


def _gpx_until(gpx_file: py.path.local, until: str, path: Path) -> Path:
    """Copy the GPX file without its points recorded after **until**"""
    text = gpx_file.read_text("utf-8")
    trkpts = re.findall(r"<trkpt\b.*?</trkpt>", text, flags=re.DOTALL)
    for trkpt in trkpts:
        [time] = re.findall(r"<time>(.*?)</time>", trkpt)
        if until < time:
            text = text.replace(trkpt, "")
    path.write_text(text, "utf-8")
    return path


def test_video_process_by_distance_with_the_gpx_start_time(
    setup_data: py.path.local,
):
    """
    As the README describes for a GPX started 2.5 seconds before the video:
    the frames start 2.5 seconds into the track.
    """
    pytest_skip_if_not_ffmpeg_installed()

    with tempfile.TemporaryDirectory() as dir:
        # Stopped about when the 5.76s video ended
        gpx_file = _gpx_until(
            setup_data.join("gpx").join("sf_30km_h.gpx"),
            "2025-03-14T07:00:10",
            Path(dir, "track.gpx"),
        )
        video_path = _with_creation_time(
            setup_data.join("videos").join("sample-5s.mp4"), "2025-03-14T07:00:36Z", dir
        )
        descs = run_video_process_for_descs(
            [
                "--video_sample_distance=3",
                "--interpolation_use_gpx_start_time",
                *["--interpolation_offset_time", "2.5"],
                "--geotag_source=gpx",
                *["--geotag_source_path", str(gpx_file)],
                str(video_path),
                str(Path(dir, "samples")),
            ]
        )

    assert descs
    assert all("error" not in desc for desc in descs), descs
    capture_times = sorted(desc["MAPCaptureTime"] for desc in descs)
    assert capture_times[0] == "2025_03_14_07_00_02_500", capture_times
    assert capture_times[-1] < "2025_03_14_07_00_09_000", capture_times


def test_video_process_with_the_gpx_start_time_refuses_a_far_longer_gpx(
    setup_data: py.path.local,
):
    """
    A GPX running on for 1.5 minutes after a 5.76s video was not recorded for
    it alone, or the video is a timelapse: the error says what to specify.
    """
    pytest_skip_if_not_ffmpeg_installed()

    gpx_file = setup_data.join("gpx").join("sf_30km_h.gpx")

    with tempfile.TemporaryDirectory() as dir:
        video_path = _with_creation_time(
            setup_data.join("videos").join("sample-5s.mp4"), "2025-03-14T07:00:36Z", dir
        )
        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            run_video_process(
                [
                    "--video_sample_distance=3",
                    "--interpolation_use_gpx_start_time",
                    "--geotag_source=gpx",
                    *["--geotag_source_path", str(gpx_file)],
                    str(video_path),
                    str(Path(dir, "samples")),
                ],
                capture_output=True,
                text=True,
            )

    assert "--video_duration_ratio" in excinfo.value.stderr
    assert "--video_start_time" in excinfo.value.stderr


def test_video_process_by_distance_with_an_untidy_gpx(setup_data: py.path.local):
    """
    GPX files converted from camera logs can list their tracks out of order and
    carry tracks timestamped 1969. Merged as they were, the points were out of
    time order, and sampling crashed with a traceback.
    """
    pytest_skip_if_not_ffmpeg_installed()

    def track(times):
        return "".join(
            f'<trkpt lat="{37.0 + i * 0.0001:.7f}" lon="-122.0"><time>{time}</time></trkpt>'
            for i, time in times
        )

    later = [(i, f"2025-03-14T07:00:{s:02d}Z") for i, s in enumerate(range(10, 20), 10)]
    earlier = [(i, f"2025-03-14T07:00:{s:02d}Z") for i, s in enumerate(range(0, 10))]
    junk = [(0, "1969-12-31T15:59:59Z")] * 3

    video_path = setup_data.join("videos").join("sample-5s.mp4")

    with tempfile.TemporaryDirectory() as dir:
        gpx_file = Path(dir, "untidy.gpx")
        gpx_file.write_text(
            '<?xml version="1.0"?>\n'
            '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
            + "".join(
                f"<trk><trkseg>{track(t)}</trkseg></trk>"
                for t in [later, junk, earlier]
            )
            + "</gpx>\n"
        )
        descs = run_video_process_for_descs(
            [
                "--video_sample_distance=3",
                *["--video_start_time", "2025_03_14_07_00_00_000"],
                "--geotag_source=gpx",
                *["--geotag_source_path", str(gpx_file)],
                str(video_path),
                str(Path(dir, "samples")),
            ]
        )

    assert descs
    assert all("error" not in desc for desc in descs), descs
    capture_times = sorted(desc["MAPCaptureTime"] for desc in descs)
    assert "2025_03_14_07_00_00_000" <= capture_times[0], capture_times
    assert capture_times[-1] < "2025_03_14_07_00_06_000", capture_times


def test_video_process_processes_the_videos_that_sampled(setup_data: py.path.local):
    """
    hero8.mp4's GPS is all noise, so it cannot be sampled by distance. That
    fails the command, but only after max-360mode.mp4 beside it is sampled and
    its samples processed, rather than leaving them behind unprocessed.
    """
    pytest_skip_if_not_ffmpeg_installed()

    video_dir = setup_data.join("gopro_data")
    desc_path = Path(setup_data, "descs.json")

    with pytest.raises(subprocess.CalledProcessError) as ex:
        run_command(
            [
                "--video_sample_distance=6",
                *["--desc_path", str(desc_path)],
                str(video_dir),
                str(video_dir.join("my_samples")),
            ],
            "video_process",
            capture_output=True,
            text=True,
        )
    assert 7 == ex.value.returncode, ex.value.stderr
    assert "Failed to sample 1 videos" in ex.value.stderr
    assert "--skip_sample_errors" in ex.value.stderr

    descs = json.loads(desc_path.read_text())
    assert descs
    for desc in descs:
        assert "error" not in desc, desc
        assert Path(desc["filename"]).parent.name == "max-360mode.mp4"


def test_video_process_skips_the_only_video(setup_data: py.path.local):
    """
    Skipping every video leaves nothing to process, which is not an error:
    it used to fail with "Import file or directory not found"
    """
    pytest_skip_if_not_ffmpeg_installed()

    descs = run_video_process_for_descs(
        [
            "--video_sample_distance=6",
            "--skip_sample_errors",
            str(setup_data.join("gopro_data").join("hero8.mp4")),
        ]
    )
    assert [] == descs


def test_video_process_and_upload_uploads_nothing_if_a_video_fails(
    setup_data: py.path.local, setup_config, setup_upload
):
    """
    hero8.mp4 cannot be sampled by distance. The command fails without
    uploading max-360mode.mp4 beside it either, and says so, because the last
    thing it logs before failing is that its sample images are ready.
    """
    pytest_skip_if_not_ffmpeg_installed()

    video_dir = setup_data.join("gopro_data")
    upload_args = ["--dry_run", *["--user_name", USERNAME], "--video_sample_distance=6"]

    with pytest.raises(subprocess.CalledProcessError) as ex:
        run_command(
            [*upload_args, str(video_dir), str(setup_data.join("samples"))],
            command="video_process_and_upload",
            capture_output=True,
            text=True,
        )
    assert 7 == ex.value.returncode, ex.value.stderr
    assert "Nothing was uploaded" in ex.value.stderr
    assert "--skip_sample_errors" in ex.value.stderr
    assert not setup_upload.listdir()

    run_command(
        [
            *upload_args,
            "--skip_sample_errors",
            str(video_dir),
            str(setup_data.join("samples_skipped")),
        ],
        command="video_process_and_upload",
    )
    assert setup_upload.listdir()


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
    assert 6 == len(descs)
    assert 0 == len([d for d in descs if "error" in d])


def test_video_process_sample_with_multiple_distances(setup_data: py.path.local):
    pytest_skip_if_not_ffmpeg_installed()

    video_dir = setup_data.join("gopro_data")
    for distance in [0, 2.4, 100]:
        descs = run_video_process_for_descs(
            [
                "--video_sample_distance",
                str(distance),
                # gopro_data also holds hero8.mp4, whose GPS is all noise and so
                # cannot be distance-sampled; this test is about max-360mode.mp4
                "--skip_sample_errors",
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
                # see test_video_process_sample_with_multiple_distances
                "--skip_sample_errors",
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
