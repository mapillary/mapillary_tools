import os
import subprocess
from pathlib import Path

import pytest

from mapillary_tools import ffmpeg


def ffmpeg_installed():
    ffmpeg_path = os.getenv("MAPILLARY_TOOLS_FFMPEG_PATH", "ffmpeg")
    ffprobe_path = os.getenv("MAPILLARY_TOOLS_FFPROBE_PATH", "ffprobe")
    try:
        subprocess.run([ffmpeg_path, "-version"])
        # In Windows, ffmpeg is installed but ffprobe is not?
        subprocess.run([ffprobe_path, "-version"])
    except FileNotFoundError:
        return False
    return True


is_ffmpeg_installed = ffmpeg_installed()


def test_ffmpeg_not_exists():
    if not is_ffmpeg_installed:
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
    if not is_ffmpeg_installed:
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
