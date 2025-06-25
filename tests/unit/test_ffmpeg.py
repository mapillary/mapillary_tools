import datetime
import subprocess
from pathlib import Path

import py.path

import pytest

from mapillary_tools import ffmpeg

from ..integration.fixtures import IS_FFMPEG_INSTALLED, setup_data


def test_ffmpeg_run_ok():
    ff = ffmpeg.FFMPEG()
    ff.run_ffmpeg_non_interactive(["-version"])


@pytest.mark.xfail(
    reason="ffmpeg run_ffmpeg_non_interactive should raise FFmpegCalledProcessError",
    raises=ffmpeg.FFmpegCalledProcessError,
)
def test_ffmpeg_run_raise():
    ff = ffmpeg.FFMPEG()
    ff.run_ffmpeg_non_interactive(["foo"])


def test_ffmpeg_extract_frames_ok(setup_data: py.path.local):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("ffmpeg not installed")

    ff = ffmpeg.FFMPEG()

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))

    sample_dir = Path(setup_data.join("videos/samples"))
    sample_dir.mkdir()

    ff.extract_frames_by_interval(
        video_path, sample_dir, stream_idx=None, sample_interval=1
    )

    results = list(ff.sort_selected_samples(sample_dir, video_path, [None]))
    assert len(results) == 6
    for idx, (file_idx, frame_paths) in enumerate(results):
        assert idx + 1 == file_idx
        assert 1 == len(frame_paths)
        assert frame_paths[0] is not None
        assert frame_paths[0].exists()

    results = list(ff.sort_selected_samples(sample_dir, video_path, [0]))
    assert len(results) == 6
    for idx, (file_idx, frame_paths) in enumerate(results):
        assert idx + 1 == file_idx
        assert 1 == len(frame_paths)
        assert frame_paths[0] is None


def test_ffmpeg_extract_specified_frames_ok(setup_data: py.path.local):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("ffmpeg not installed")

    ff = ffmpeg.FFMPEG()

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))

    sample_dir = Path(setup_data.join("videos/samples"))
    sample_dir.mkdir()

    ff.extract_specified_frames(video_path, sample_dir, frame_indices={2, 9})

    results = list(ff.sort_selected_samples(sample_dir, video_path, [None]))
    assert len(results) == 2

    for idx, (file_idx, frame_paths) in enumerate(results):
        assert idx + 1 == file_idx
        assert frame_paths[0] is not None
        assert frame_paths[0].exists()


def test_probe_format_and_streams_ok(setup_data: py.path.local):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("ffmpeg not installed")

    video_path = Path(setup_data.join("videos/sample-5s.mp4"))

    ff = ffmpeg.FFMPEG()
    probe_output = ff.probe_format_and_streams(video_path)
    probe = ffmpeg.Probe(probe_output)

    start_time = probe.probe_video_start_time()
    assert start_time is None
    max_stream = probe.probe_video_with_max_resolution()
    assert max_stream is not None
    assert max_stream["index"] == 0
    assert max_stream["codec_type"] == "video"


def test_probe_format_and_streams_gopro_ok(setup_data: py.path.local):
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("ffmpeg not installed")

    video_path = Path(setup_data.join("gopro_data/hero8.mp4"))

    ff = ffmpeg.FFMPEG()
    probe_output = ff.probe_format_and_streams(video_path)
    probe = ffmpeg.Probe(probe_output)

    start_time = probe.probe_video_start_time()
    assert start_time is not None
    assert datetime.datetime.isoformat(start_time) == "2019-11-18T15:41:12.354033+00:00"
    max_stream = probe.probe_video_with_max_resolution()
    assert max_stream is not None
    assert max_stream["index"] == 0
    assert max_stream["codec_type"] == "video"


def test_ffmpeg_not_exists():
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("ffmpeg not installed")

    ff = ffmpeg.FFMPEG()
    try:
        ff.extract_frames_by_interval(
            Path("not_exist_a"), Path("not_exist_b"), sample_interval=2
        )
    except ffmpeg.FFmpegCalledProcessError as ex:
        assert "STDERR:" not in str(ex)
    else:
        assert False, "FFmpegCalledProcessError not raised"

    ff = ffmpeg.FFMPEG(stderr=subprocess.PIPE)
    try:
        ff.extract_frames_by_interval(
            Path("not_exist_a"), Path("not_exist_b"), sample_interval=2
        )
    except ffmpeg.FFmpegCalledProcessError as ex:
        assert "STDERR:" in str(ex)
    else:
        assert False, "FFmpegCalledProcessError not raised"


def test_ffprobe_not_exists():
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("ffmpeg not installed")

    ff = ffmpeg.FFMPEG()
    try:
        x = ff.probe_format_and_streams(Path("not_exist_a"))
    except ffmpeg.FFmpegCalledProcessError as ex:
        # exc from linux
        assert "STDERR:" not in str(ex)
    except RuntimeError as ex:
        # exc from macos
        assert "Empty JSON ffprobe output with STDERR: None" == str(ex)
    else:
        assert False, "RuntimeError not raised"

    ff = ffmpeg.FFMPEG(stderr=subprocess.PIPE)
    try:
        x = ff.probe_format_and_streams(Path("not_exist_a"))
    except ffmpeg.FFmpegCalledProcessError as ex:
        # exc from linux
        assert "STDERR:" in str(ex)
    except RuntimeError as ex:
        # exc from macos
        assert (
            "Empty JSON ffprobe output with STDERR: b'not_exist_a: No such file or directory"
            in str(ex)
        )
    else:
        assert False, "RuntimeError not raised"


def test_probe():
    def test_creation_time(expected, probe_creation_time, probe_duration):
        probe = ffmpeg.Probe(
            {
                "streams": [
                    {
                        "index": 0,
                        "codec_type": "video",
                        "codec_tag_string": "avc1",
                        "width": 2880,
                        "height": 1620,
                        "coded_width": 2880,
                        "coded_height": 1620,
                        "duration": probe_duration,
                        "tags": {
                            "creation_time": probe_creation_time,
                            "language": "und",
                            "handler_name": "Core Media Video",
                            "vendor_id": "[0][0][0][0]",
                            "encoder": "H.264",
                        },
                    }
                ]
            }
        )
        creation_time = probe.probe_video_start_time()
        assert expected == creation_time

    test_creation_time(
        datetime.datetime(2023, 3, 7, 1, 35, 29, 190123, tzinfo=datetime.timezone.utc),
        "2023-03-07T01:35:34.123456Z",
        "4.933333",
    )
    test_creation_time(
        datetime.datetime(2023, 3, 7, 1, 35, 29, 66667, tzinfo=datetime.timezone.utc),
        "2023-03-07T01:35:34.000000Z",
        "4.933333",
    )
    test_creation_time(
        datetime.datetime(2023, 3, 7, 1, 35, 29, 66667),
        "2023-03-07 01:35:34",
        "4.933333",
    )
