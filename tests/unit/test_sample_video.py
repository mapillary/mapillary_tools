import datetime
import os
import json
import shutil
from pathlib import Path

import py.path
import pytest

from mapillary_tools import sample_video, ffmpeg, exif_read, types, constants

_PWD = Path(os.path.dirname(os.path.abspath(__file__)))


class MOCK_FFMPEG(ffmpeg.FFMPEG):
    def extract_frames(
        self,
        video_path: Path,
        sample_path: Path,
        video_sample_interval: float,
    ):
        probe = self.probe_format_and_streams(video_path)
        video_streams = [
            s for s in probe.get("streams", []) if s.get("codec_type") == "video"
        ]
        duration = float(video_streams[0]["duration"])
        video_basename_no_ext, _ = os.path.splitext(os.path.basename(video_path))
        frame_path_prefix = os.path.join(sample_path, video_basename_no_ext)
        src = os.path.join(_PWD, "data/test_exif.jpg")
        for idx in range(0, int(duration / video_sample_interval)):
            sample = f"{frame_path_prefix}_{idx + 1:06d}.jpg"
            shutil.copyfile(src, sample)

    def probe_format_and_streams(self, video_path: Path) -> ffmpeg.ProbeOutput:
        with open(video_path) as fp:
            return json.load(fp)


@pytest.fixture
def setup_mock(monkeypatch):
    monkeypatch.setattr(ffmpeg, "FFMPEG", MOCK_FFMPEG)


def _validate(samples, video_start_time):
    assert len(samples), "expect samples but got none"
    for idx, sample in enumerate(sorted(samples)):
        assert sample.basename == f"hello_{idx + 1:06d}.jpg"
        exif = exif_read.ExifRead(str(sample))
        expected_dt = video_start_time + datetime.timedelta(
            seconds=constants.VIDEO_SAMPLE_INTERVAL * idx
        )
        assert exif.extract_capture_time() == expected_dt


def test_sample_video(tmpdir: py.path.local, setup_mock):
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")
    sample_video.sample_video(str(video_dir), str(sample_dir), rerun=True)
    samples = sample_dir.join("hello.mp4").listdir()
    video_start_time = types.map_capture_time_to_datetime("2021_08_10_14_37_05_023")
    _validate(samples, video_start_time)


def test_sample_single_video(tmpdir: py.path.local, setup_mock):
    root = _PWD.joinpath("data/mock_sample_video")
    video_path = root.joinpath("videos", "hello.mp4")
    sample_dir = tmpdir.mkdir("sampled_video_frames")
    sample_video.sample_video(str(video_path), str(sample_dir), rerun=True)
    samples = sample_dir.join("hello.mp4").listdir()
    video_start_time = types.map_capture_time_to_datetime("2021_08_10_14_37_05_023")
    _validate(samples, video_start_time)


def test_sample_video_with_start_time(tmpdir: py.path.local, setup_mock):
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")
    video_start_time_str = "2020_08_10_14_37_05_023"
    video_start_time = types.map_capture_time_to_datetime(video_start_time_str)
    sample_video.sample_video(
        str(video_dir),
        str(sample_dir),
        video_start_time=video_start_time_str,
        rerun=True,
    )
    samples = sample_dir.join("hello.mp4").listdir()
    _validate(samples, video_start_time)
