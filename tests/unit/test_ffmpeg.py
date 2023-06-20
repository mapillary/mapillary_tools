import datetime
import os
import subprocess
from pathlib import Path

import pytest

from mapillary_tools import ffmpeg


def _ffmpeg_installed():
    ffmpeg_path = os.getenv("MAPILLARY_TOOLS_FFMPEG_PATH", "ffmpeg")
    ffprobe_path = os.getenv("MAPILLARY_TOOLS_FFPROBE_PATH", "ffprobe")
    try:
        subprocess.run(
            [ffmpeg_path, "-version"], stderr=subprocess.PIPE, stdout=subprocess.PIPE
        )
        # In Windows, ffmpeg is installed but ffprobe is not?
        subprocess.run(
            [ffprobe_path, "-version"], stderr=subprocess.PIPE, stdout=subprocess.PIPE
        )
    except FileNotFoundError:
        return False
    return True


IS_FFMPEG_INSTALLED = _ffmpeg_installed()


def test_ffmpeg_not_exists():
    if not IS_FFMPEG_INSTALLED:
        pytest.skip("ffmpeg not installed")

    ff = ffmpeg.FFMPEG()
    try:
        ff.extract_frames(Path("not_exist_a"), Path("not_exist_b"), sample_interval=2)
    except ffmpeg.FFmpegCalledProcessError as ex:
        assert "STDERR:" not in str(ex)
    else:
        assert False, "FFmpegCalledProcessError not raised"

    ff = ffmpeg.FFMPEG(stderr=subprocess.PIPE)
    try:
        ff.extract_frames(Path("not_exist_a"), Path("not_exist_b"), sample_interval=2)
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
