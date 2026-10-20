# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import time
import typing as T
from pathlib import Path
from unittest import mock

import py.path
import pytest
from mapillary_tools import (
    exceptions,
    exif_read,
    ffmpeg as ffmpeglib,
    geo,
    sample_video,
    telemetry,
)
from mapillary_tools.geotag.options import SourceType, VideoSyncOption
from mapillary_tools.mp4 import construct_mp4_parser as cparser, mp4_sample_parser
from mapillary_tools.serializer import description
from mapillary_tools.types import describe_error_metadata, FileType, VideoMetadata

_PWD = Path(os.path.dirname(os.path.abspath(__file__)))

# The creation time of the hello.mp4 probe fixture, which is where videos
# without their own GPS clock get their start time from
PROBE_START_TIME = datetime.datetime(
    2021, 8, 10, 14, 38, 6, tzinfo=datetime.timezone.utc
)


# ---------------------------------------------------------------------------
# Interval-based sampling tests (using MOCK_FFMPEG)
# ---------------------------------------------------------------------------


class MOCK_FFMPEG(ffmpeglib.FFMPEG):
    def extract_frames_by_interval(
        self,
        video_path: Path,
        sample_path: Path,
        video_sample_interval: float,
        stream_specifier: int | str = "v",
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
            sample = f"{frame_path_prefix}_{stream_specifier}_{idx + 1:06d}.jpg"
            shutil.copyfile(src, sample)

    def probe_format_and_streams(self, video_path: Path) -> ffmpeglib.ProbeOutput:
        with open(video_path) as fp:
            return json.load(fp)


@pytest.fixture
def setup_mock(monkeypatch):
    monkeypatch.setattr(ffmpeglib, "FFMPEG", MOCK_FFMPEG)


def _validate_interval(
    samples: T.Sequence[Path], video_start_time, seconds_per_sample: float = 2
):
    assert len(samples), "expect samples but got none"
    for idx, sample in enumerate(sorted(samples)):
        assert sample.name == f"hello_v_{idx + 1:06d}.jpg"
        exif = exif_read.ExifRead(sample)
        expected_dt = video_start_time + datetime.timedelta(
            seconds=seconds_per_sample * idx
        )
        assert exif.extract_capture_time() == expected_dt


def test_sample_video(tmpdir: py.path.local, setup_mock):
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")
    sample_video.sample_video(
        video_dir,
        Path(sample_dir),
        video_sample_distance=-1,
        video_sample_interval=2,
        rerun=True,
    )
    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], PROBE_START_TIME)


def test_sample_single_video(tmpdir: py.path.local, setup_mock):
    root = _PWD.joinpath("data/mock_sample_video")
    video_path = root.joinpath("videos", "hello.mp4")
    sample_dir = tmpdir.mkdir("sampled_video_frames")
    sample_video.sample_video(
        video_path,
        Path(sample_dir),
        video_sample_distance=-1,
        video_sample_interval=2,
        rerun=True,
    )
    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], PROBE_START_TIME)


def test_sample_video_with_start_time(tmpdir: py.path.local, setup_mock):
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")
    video_start_time_str = "2020_08_10_14_37_05_023"
    video_start_time = description.parse_capture_time(video_start_time_str)
    sample_video.sample_video(
        video_dir,
        Path(sample_dir),
        video_start_time=video_start_time_str,
        video_sample_distance=-1,
        video_sample_interval=2,
        rerun=True,
    )
    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], video_start_time)


def test_sample_video_from_gps_clock(tmpdir: py.path.local, setup_mock, monkeypatch):
    """A video's own GPS clock wins over the container's creation time."""
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")

    # A camera that stamps the creation time at the end of the recording, or in
    # local time, still has a correct absolute clock in its telemetry
    gps_start_time = datetime.datetime(
        2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
    )
    points = [
        telemetry.GPSPoint(
            time=float(i),
            lat=40.0 + i * 0.001,
            lon=-74.0,
            alt=None,
            angle=None,
            epoch_time=gps_start_time.timestamp() + i,
            fix=None,
            precision=None,
            ground_speed=None,
        )
        for i in range(3)
    ]
    monkeypatch.setattr(
        sample_video,
        "NativeVideoExtractor",
        lambda video_path: mock.Mock(
            extract=lambda: VideoMetadata(
                filename=video_path,
                filetype=FileType.BLACKVUE,
                points=T.cast(T.List[geo.Point], points),
            )
        ),
    )

    sample_video.sample_video(
        video_dir,
        Path(sample_dir),
        video_sample_distance=-1,
        video_sample_interval=2,
        rerun=True,
    )

    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], gps_start_time)


def test_sample_video_when_telemetry_fails(
    tmpdir: py.path.local, setup_mock, monkeypatch, caplog
):
    """A telemetry parser bug must not fail sampling, which did not need it."""
    root = _PWD.joinpath("data/mock_sample_video")
    video_dir = root.joinpath("videos")
    sample_dir = tmpdir.mkdir("sampled_video_frames")

    def raise_type_error():
        raise TypeError("'NoneType' object is not subscriptable")

    monkeypatch.setattr(
        sample_video,
        "NativeVideoExtractor",
        lambda video_path: mock.Mock(extract=raise_type_error),
    )

    with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
        sample_video.sample_video(
            video_dir,
            Path(sample_dir),
            video_sample_distance=-1,
            video_sample_interval=2,
            rerun=True,
        )

    samples = sample_dir.join("hello.mp4").listdir()
    _validate_interval([Path(s) for s in samples], PROBE_START_TIME)
    assert "Unable to read the telemetry of hello.mp4" in caplog.text


class TestSampleTimelapseByInterval:
    """
    Interval samples of a timelapse are stamped with their capture times, which
    its GPS clock spaces 10 times as far apart as the frames
    """

    GPS_START_TIME = datetime.datetime(
        2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
    )

    @pytest.fixture
    def timelapse_telemetry(self, monkeypatch):
        # One point per second of video, recorded 10 seconds apart
        points = [
            telemetry.GPSPoint(
                time=float(i),
                lat=40.0 + i * 0.001,
                lon=-74.0,
                alt=None,
                angle=None,
                epoch_time=self.GPS_START_TIME.timestamp() + 10 * i,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for i in range(60)
        ]
        monkeypatch.setattr(
            sample_video,
            "NativeVideoExtractor",
            lambda video_path: mock.Mock(
                extract=lambda: VideoMetadata(
                    filename=video_path,
                    filetype=FileType.GOPRO,
                    points=T.cast(T.List[geo.Point], points),
                )
            ),
        )

    def _sample(self, tmpdir: py.path.local, **kwargs) -> list[Path]:
        root = _PWD.joinpath("data/mock_sample_video")
        sample_dir = tmpdir.mkdir("sampled_video_frames")
        sample_video.sample_video(
            root.joinpath("videos"),
            Path(sample_dir),
            video_sample_distance=-1,
            video_sample_interval=2,
            rerun=True,
            **kwargs,
        )
        return [Path(s) for s in sample_dir.join("hello.mp4").listdir()]

    def test_capture_times_follow_the_gps_clock(
        self, tmpdir, setup_mock, timelapse_telemetry, caplog
    ):
        _validate_interval(
            self._sample(tmpdir), self.GPS_START_TIME, seconds_per_sample=20
        )
        assert "--video_duration_ratio" not in caplog.text

    def test_from_the_given_start_time(self, tmpdir, setup_mock, timelapse_telemetry):
        video_start_time = "2020_08_10_14_37_05_023"
        _validate_interval(
            self._sample(tmpdir, video_start_time=video_start_time),
            description.parse_capture_time(video_start_time),
            seconds_per_sample=20,
        )

    def test_the_gps_clock_wins_over_the_duration_ratio(
        self, tmpdir, setup_mock, timelapse_telemetry, caplog
    ):
        """
        The ratio is for the videos without a GPS clock, which a batch of
        videos may mix with videos that have one
        """
        _validate_interval(
            self._sample(tmpdir, video_duration_ratio=5),
            self.GPS_START_TIME,
            seconds_per_sample=20,
        )
        assert (
            "Ignoring --video_duration_ratio 5 for hello.mp4, whose own GPS clock runs at 10x"
            in caplog.text
        )

    def test_the_duration_ratio_paces_a_video_without_a_gps_clock(
        self, tmpdir, setup_mock
    ):
        _validate_interval(
            self._sample(tmpdir, video_duration_ratio=5),
            PROBE_START_TIME,
            seconds_per_sample=10,
        )


class TestGPSClockStartTime:
    """Tests for _gps_clock_start_time."""

    @staticmethod
    def _gps_point(time: float, epoch_time: float | None) -> telemetry.GPSPoint:
        return telemetry.GPSPoint(
            time=time,
            lat=40.0,
            lon=-74.0,
            alt=None,
            angle=None,
            epoch_time=epoch_time,
            fix=None,
            precision=None,
            ground_speed=None,
        )

    def test_maps_first_timestamp_back_to_video_start(self) -> None:
        # The first point is 2.5s into the video, so the video started 2.5s
        # before that point was recorded
        points = [self._gps_point(2.5, 1628599086.0)]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 3, 500000, tzinfo=datetime.timezone.utc
        )

    def test_skips_points_without_a_timestamp(self) -> None:
        points = [self._gps_point(0.0, None), self._gps_point(1.0, 1628599086.0)]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 5, tzinfo=datetime.timezone.utc
        )

    def test_skips_unset_clock(self) -> None:
        # GoPro reports 2000-01-01 until it gets its first fix
        points = [
            self._gps_point(0.0, 946684800.0),
            self._gps_point(1.0, 1628599086.0),
        ]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 5, tzinfo=datetime.timezone.utc
        )

    def test_skips_future_timestamps(self) -> None:
        points = [
            self._gps_point(0.0, time.time() + 7 * 24 * 3600),
            self._gps_point(1.0, 1628599086.0),
        ]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 5, tzinfo=datetime.timezone.utc
        )

    def test_skips_non_finite_timestamps(self) -> None:
        points = [
            self._gps_point(float("nan"), 1628599086.0),
            self._gps_point(0.0, float("inf")),
            self._gps_point(0.0, 1e300),
            self._gps_point(1.0, 1628599086.0),
        ]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 5, tzinfo=datetime.timezone.utc
        )

    def test_only_implausible_timestamps(self) -> None:
        points = [self._gps_point(0.0, 946684800.0), self._gps_point(1.0, 1e300)]
        assert sample_video._gps_clock_start_time(points) is None

    def test_median_ignores_a_bad_timestamp(self) -> None:
        epoch_times = [1628599086.0 + i for i in range(5)]
        epoch_times[0] += 30
        points = [self._gps_point(float(i), t) for i, t in enumerate(epoch_times)]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 6, tzinfo=datetime.timezone.utc
        )

    def test_uses_the_start_of_a_timelapse(self) -> None:
        # Each second of this timelapse spans 10 seconds of GPS time, so the
        # offset between the two clocks grows by 9 seconds per point. Reading it
        # at the start of the track keeps the error to a couple of points
        # rather than half the track
        points = [self._gps_point(float(i), 1628599086.0 + 10 * i) for i in range(1000)]
        assert sample_video._gps_clock_start_time(points) == datetime.datetime(
            2021, 8, 10, 12, 38, 24, tzinfo=datetime.timezone.utc
        )

    def test_maps_a_timelapse_back_at_its_rate(self) -> None:
        points = [self._gps_point(float(i), 1628599086.0 + 10 * i) for i in range(1000)]
        assert sample_video._gps_clock_start_time(points, rate=10) == datetime.datetime(
            2021, 8, 10, 12, 38, 6, tzinfo=datetime.timezone.utc
        )

    def test_no_absolute_timestamps(self) -> None:
        assert sample_video._gps_clock_start_time(_make_gps_points(3)) is None

    def test_no_points(self) -> None:
        assert sample_video._gps_clock_start_time([]) is None


class TestCreationTimeToStartTime:
    """Tests for _creation_time_to_start_time."""

    # A 60-second video, so the start is a minute before this if the camera
    # stamped the end
    CREATION_TIME = datetime.datetime(
        2023, 3, 7, 1, 36, 34, tzinfo=datetime.timezone.utc
    )
    START_TIME_IF_END_STAMPED = datetime.datetime(
        2023, 3, 7, 1, 35, 34, tzinfo=datetime.timezone.utc
    )

    @staticmethod
    def _probe(
        creation_time: str | None = "2023-03-07T01:36:34.000000Z",
        duration: str | None = "60.0",
        format_tags: dict[str, str] | None = None,
    ) -> ffmpeglib.Probe:
        stream: dict[str, T.Any] = {
            "index": 0,
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "tags": {},
        }
        if creation_time is not None:
            stream["tags"]["creation_time"] = creation_time
        if duration is not None:
            stream["duration"] = duration
        return ffmpeglib.Probe(
            T.cast(
                ffmpeglib.ProbeOutput,
                {"streams": [stream], "format": {"tags": format_tags or {}}},
            )
        )

    @staticmethod
    def _video(tmp_path: Path, name: str, data: bytes = b"") -> Path:
        video_path = tmp_path / name
        video_path.write_bytes(data)
        return video_path

    def test_assumes_start_without_evidence(self, tmp_path: Path, caplog) -> None:
        video_path = self._video(tmp_path, "clip.mp4")
        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            start_time = sample_video._creation_time_to_start_time(
                video_path, self._probe()
            )
        assert start_time == self.CREATION_TIME
        # Tells the user how to override it if the camera stamps the end
        assert "--video_start_time 2023_03_07_01_35_34_000" in caplog.text

    def test_known_end_stamping_camera(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "R0020627.MP4")
        probe = self._probe(format_tags={"make": "RICOH", "model": "RICOH THETA X"})
        assert (
            sample_video._creation_time_to_start_time(video_path, probe)
            == self.START_TIME_IF_END_STAMPED
        )

    def test_other_models_of_the_same_make(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "R0010001.MP4")
        probe = self._probe(format_tags={"make": "RICOH", "model": "RICOH THETA Z1"})
        assert (
            sample_video._creation_time_to_start_time(video_path, probe)
            == self.CREATION_TIME
        )

    def test_blackvue_without_gps_fix(self, tmp_path: Path) -> None:
        # BlackVue stamps the end. Without a fix there is no GPS clock to read
        # the start from, but its GPS box is still there to identify it
        box = {
            "type": b"free",
            "data": [
                {"type": b"gps ", "data": b"[1678152934000]$GPRMC,,V,,,,,,,,,,N*53"}
            ],
        }
        data = cparser.Box32ConstructBuilder({b"free": {}}).Box.build(box)
        video_path = self._video(tmp_path, "clip.mp4", data)
        assert (
            sample_video._creation_time_to_start_time(video_path, self._probe())
            == self.START_TIME_IF_END_STAMPED
        )

    def test_file_name_matches_end(self, tmp_path: Path) -> None:
        # Viofo names files by the start in local time (UTC+9 here), and stamps
        # the creation time at the end. The two clocks can be seconds apart
        for name in ["2023_0307_103534_0001F.MP4", "2023_0307_103544_0001F.MP4"]:
            video_path = self._video(tmp_path, name)
            assert (
                sample_video._creation_time_to_start_time(video_path, self._probe())
                == self.START_TIME_IF_END_STAMPED
            )

    def test_file_name_matches_end_with_naive_creation_time(
        self, tmp_path: Path
    ) -> None:
        video_path = self._video(tmp_path, "2023_0307_103534_0001F.MP4")
        probe = self._probe(creation_time="2023-03-07 01:36:34")
        assert sample_video._creation_time_to_start_time(
            video_path, probe
        ) == datetime.datetime(2023, 3, 7, 1, 35, 34)

    def test_file_name_matches_start(self, tmp_path: Path) -> None:
        # Insta360 names files a few seconds after it stamps the creation time
        for name in ["VID_20230307_103634_00_001.mp4", "VID_20230307_103644.mp4"]:
            video_path = self._video(tmp_path, name)
            assert (
                sample_video._creation_time_to_start_time(video_path, self._probe())
                == self.CREATION_TIME
            )

    def test_file_name_matches_both(self, tmp_path: Path, caplog) -> None:
        # A 15-minute video starts and ends at times that are both a whole
        # time zone away from the file name
        video_path = self._video(tmp_path, "20230307_103634.mp4")
        with caplog.at_level(logging.WARNING, logger=sample_video.LOG.name):
            start_time = sample_video._creation_time_to_start_time(
                video_path, self._probe(duration="900.0")
            )
        assert start_time == self.CREATION_TIME
        assert "--video_start_time" in caplog.text

    def test_file_name_matches_neither(self, tmp_path: Path) -> None:
        for name in ["20230307_104004.mp4", "20230309_103634.mp4"]:
            video_path = self._video(tmp_path, name)
            assert (
                sample_video._creation_time_to_start_time(video_path, self._probe())
                == self.CREATION_TIME
            )

    def test_file_name_with_invalid_date(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "20231399_103534.mp4")
        assert (
            sample_video._creation_time_to_start_time(video_path, self._probe())
            == self.CREATION_TIME
        )

    def test_no_creation_time(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "clip.mp4")
        probe = self._probe(creation_time=None)
        assert sample_video._creation_time_to_start_time(video_path, probe) is None

    def test_no_duration(self, tmp_path: Path) -> None:
        video_path = self._video(tmp_path, "2023_0307_103534_0001F.MP4")
        probe = self._probe(duration=None)
        assert (
            sample_video._creation_time_to_start_time(video_path, probe)
            == self.CREATION_TIME
        )


# ---------------------------------------------------------------------------
# Helpers for distance-based sampling tests
# ---------------------------------------------------------------------------

MOCK_PROBE_JSON = _PWD / "data" / "mock_sample_video" / "videos" / "hello.mp4"
TEST_EXIF_JPG = _PWD / "data" / "test_exif.jpg"


def _load_probe_output() -> ffmpeglib.ProbeOutput:
    with open(MOCK_PROBE_JSON) as fp:
        return T.cast(ffmpeglib.ProbeOutput, json.load(fp))


def _make_gps_points(
    n: int = 10,
    start_lat: float = 40.0,
    start_lon: float = -74.0,
    lat_step: float = 0.001,
    lon_step: float = 0.001,
    time_step: float = 1.0,
) -> list[geo.Point]:
    """Create a synthetic GPS track with n points."""
    return [
        geo.Point(
            time=i * time_step,
            lat=start_lat + i * lat_step,
            lon=start_lon + i * lon_step,
            alt=10.0,
            angle=45.0,
        )
        for i in range(n)
    ]


def _make_sample(
    composition_time: float,
    timedelta: float = 0.033,
) -> mp4_sample_parser.Sample:
    """Create a synthetic mp4 Sample at the given composition time."""
    raw = mp4_sample_parser.RawSample(
        description_idx=1,
        offset=0,
        size=1000,
        timedelta=int(timedelta * 1000),
        composition_offset=0,
        is_sync=True,
    )
    return mp4_sample_parser.Sample(
        raw_sample=raw,
        exact_time=composition_time,
        exact_composition_time=composition_time,
        exact_timedelta=timedelta,
        description={},
    )


def _create_fake_frames(
    sample_dir: Path,
    video_stem: str,
    stream_specifier: str,
    num_frames: int,
) -> list[Path]:
    """Create fake JPEG frame files in sample_dir mimicking ffmpeg output."""
    os.makedirs(sample_dir, exist_ok=True)
    paths: list[Path] = []
    for i in range(1, num_frames + 1):
        name = f"{video_stem}_{stream_specifier}_{i:06d}.jpg"
        frame_path = sample_dir / name
        shutil.copy(str(TEST_EXIF_JPG), str(frame_path))
        paths.append(frame_path)
    return paths


# ---------------------------------------------------------------------------
# Distance-based sampling: _within_track_time_range_buffered
# ---------------------------------------------------------------------------


class TestWithinTrackTimeRangeBuffered:
    """Tests for _within_track_time_range_buffered."""

    def test_within_range(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 2.0) is True

    def test_at_start_boundary(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 0.0) is True

    def test_at_end_boundary(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 4.0) is True

    def test_within_1ms_buffer_before_start(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, -0.0005) is True

    def test_within_1ms_buffer_after_end(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 4.0005) is True

    def test_outside_buffer_before_start(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, -0.002) is False

    def test_outside_buffer_after_end(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, 4.002) is False

    def test_exactly_at_1ms_boundary(self) -> None:
        points = _make_gps_points(5, time_step=1.0)
        assert sample_video._within_track_time_range_buffered(points, -0.001) is True
        assert sample_video._within_track_time_range_buffered(points, 4.001) is True


# ---------------------------------------------------------------------------
# Distance-based sampling: _sample_video_stream_by_distance
# ---------------------------------------------------------------------------


class TestSampleVideoStreamByDistance:
    """Tests for _sample_video_stream_by_distance."""

    def test_selects_frames_by_distance(self) -> None:
        """Frames spaced farther than sample_distance should be selected."""
        points = _make_gps_points(10, lat_step=0.001, time_step=1.0)
        samples = [_make_sample(float(i)) for i in range(10)]

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter(samples)

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=50.0
        )

        # Each point is ~111m apart in lat, so all 10 should be selected
        assert len(result) == 10
        assert all(idx in result for idx in range(10))

    def test_filters_close_frames(self) -> None:
        """Frames closer than sample_distance should be filtered out."""
        # ~15m apart (0.0001 degree in each axis)
        points = _make_gps_points(10, lat_step=0.0001, lon_step=0.0001, time_step=1.0)
        samples = [_make_sample(float(i)) for i in range(10)]

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter(samples)

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=50.0
        )

        assert len(result) < 10
        assert 0 in result  # first frame is always selected

    def test_zero_distance_selects_all(self) -> None:
        """With sample_distance=0, all frames in range should be selected."""
        points = _make_gps_points(5, time_step=1.0)
        samples = [_make_sample(float(i)) for i in range(5)]

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter(samples)

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=0.0
        )

        assert len(result) == 5

    def test_frames_outside_track_range_excluded(self) -> None:
        """Frames outside the GPS track time range should not be selected."""
        # GPS track covers t=2..6
        points = [
            geo.Point(time=p.time + 2.0, lat=p.lat, lon=p.lon, alt=p.alt, angle=p.angle)
            for p in _make_gps_points(5, time_step=1.0)
        ]

        # Samples at t=0..9 — only t=2..6 should be interpolated
        samples = [_make_sample(float(i)) for i in range(10)]

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter(samples)

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=0.0
        )

        for idx in result:
            sample_time = samples[idx].exact_composition_time
            assert 1.999 <= sample_time <= 6.001

    def test_empty_samples(self) -> None:
        """Empty video track should produce no selected frames."""
        points = _make_gps_points(5, time_step=1.0)

        mock_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_parser.extract_samples.return_value = iter([])

        result = sample_video._sample_video_stream_by_distance(
            points, mock_parser, sample_distance=3.0
        )

        assert len(result) == 0


# ---------------------------------------------------------------------------
# A failed distance sample must not look like a successful one
# ---------------------------------------------------------------------------


class TestDistanceSamplingFailsLoudly:
    """
    Distance sampling used to warn and return when it could not read the GPS,
    which left the caller a success exit code, no sample directory and nothing
    to upload -- `video_process` went on to geotag zero files and printed an
    empty summary. Reported for a GoPro whose embedded GPS is all noise, where
    an attached GPX made no difference.
    """

    VIDEO = _PWD.joinpath("data/mock_sample_video/videos/hello.mp4")

    @pytest.fixture
    def unreadable_gps(self, monkeypatch):
        """Every GPS read fails the way a fully filtered noisy track does."""
        error = exceptions.MapillaryGPSNoiseError("GPS is too noisy")
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options: [
                describe_error_metadata(
                    error, filename=paths[0], filetype=FileType.GOPRO
                )
            ],
        )
        return error

    def _sample(self, tmpdir: py.path.local, **kwargs):
        return sample_video.sample_video(
            self.VIDEO, Path(tmpdir), video_sample_distance=2, rerun=True, **kwargs
        )

    def test_it_raises_instead_of_returning(
        self, tmpdir, setup_mock, unreadable_gps, caplog
    ):
        with pytest.raises(exceptions.MapillaryVideoSampleError):
            self._sample(tmpdir)

        # the underlying reason has to reach the user, and is logged per video
        assert "GPS is too noisy" in caplog.text

    def test_it_names_the_flag_that_suppresses_it(
        self, tmpdir, setup_mock, unreadable_gps
    ):
        """
        --skip_process_errors governs the later geotagging stage and does not
        cover sampling, so the message has to name --skip_sample_errors or
        users reach for the wrong flag.
        """
        with pytest.raises(exceptions.MapillaryVideoError) as excinfo:
            self._sample(tmpdir)

        assert "--skip_sample_errors" in str(excinfo.value)

    def test_the_exit_code_is_a_clean_one(self, tmpdir, setup_mock, unreadable_gps):
        """Not a MapillaryUserError means a traceback instead of an exit code."""
        with pytest.raises(exceptions.MapillaryUserError) as excinfo:
            self._sample(tmpdir)

        assert excinfo.value.exit_code == 7

    def test_nothing_is_left_behind(self, tmpdir, setup_mock, unreadable_gps):
        with pytest.raises(exceptions.MapillaryVideoError):
            self._sample(tmpdir)

        assert not Path(tmpdir).joinpath(self.VIDEO.name).exists()

    def test_skip_sample_errors_still_tolerates_it(
        self, tmpdir, setup_mock, unreadable_gps
    ):
        """The opt-out that several existing callers rely on."""
        self._sample(tmpdir, skip_sample_errors=True)

    def test_the_summary_counts_it_by_its_own_type(
        self, tmpdir, setup_mock, unreadable_gps, caplog
    ):
        with pytest.raises(exceptions.MapillaryVideoSampleError):
            self._sample(tmpdir)

        assert "1 MapillaryGPSNoiseError" in caplog.text

    def test_an_empty_track_is_also_an_error(self, tmpdir, setup_mock, monkeypatch):
        """Previously an assert, so it vanished under `python -O`."""
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options: [
                VideoMetadata(
                    filename=paths[0], filesize=0, filetype=FileType.GOPRO, points=[]
                )
            ],
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            self._sample(tmpdir)

    def test_a_missing_video_stream_is_also_an_error(
        self, tmpdir, setup_mock, monkeypatch
    ):
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options: [
                VideoMetadata(
                    filename=paths[0],
                    filesize=0,
                    filetype=FileType.GOPRO,
                    points=_make_gps_points(3, time_step=1.0),
                )
            ],
        )
        monkeypatch.setattr(
            ffmpeglib.Probe, "probe_video_with_max_resolution", lambda _self: None
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            self._sample(tmpdir)


# ---------------------------------------------------------------------------
# sample_video() parameter validation & rerun
# ---------------------------------------------------------------------------


class TestSampleVideoNegativeDistance:
    """Test sample_video() with invalid parameters."""

    def test_negative_distance_raises(self, tmp_path: Path) -> None:
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        (video_dir / "test.mp4").touch()

        with pytest.raises(exceptions.MapillaryBadParameterError):
            sample_video.sample_video(
                video_import_path=video_dir,
                import_path=tmp_path / "output",
                video_sample_distance=1.0,
                video_sample_interval=1.0,
            )


class TestSampleVideoRerun:
    """Test rerun behavior of sample_video."""

    def test_skip_existing_samples_without_rerun(self, tmp_path: Path) -> None:
        """Existing sample directories should be skipped without --rerun."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        (video_dir / "test.mp4").touch()

        output_dir = tmp_path / "output"
        sample_dir = output_dir / "test.mp4"
        sample_dir.mkdir(parents=True)
        (sample_dir / "frame_000001.jpg").touch()

        with mock.patch.object(
            sample_video, "_sample_single_video_by_distance"
        ) as mock_sample:
            sample_video.sample_video(
                video_import_path=video_dir,
                import_path=output_dir,
                rerun=False,
            )
            mock_sample.assert_not_called()

    def test_rerun_removes_existing_and_resamples(self, tmp_path: Path) -> None:
        """With --rerun, existing sample directories should be removed."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        (video_dir / "test.mp4").touch()

        output_dir = tmp_path / "output"
        sample_dir = output_dir / "test.mp4"
        sample_dir.mkdir(parents=True)
        marker = sample_dir / "old_frame.jpg"
        marker.touch()

        with mock.patch.object(
            sample_video, "_sample_single_video_by_distance"
        ) as mock_sample:
            sample_video.sample_video(
                video_import_path=video_dir,
                import_path=output_dir,
                rerun=True,
            )
            assert not marker.exists()
            mock_sample.assert_called_once()


# ---------------------------------------------------------------------------
# Distance-based sampling: integration tests with mocked ffmpeg and geotag
# ---------------------------------------------------------------------------


class TestSampleVideoDistanceIntegration:
    """Integration-style tests for the distance-based sampling path."""

    def _setup_mocks(
        self,
        tmp_path: Path,
        video_path: Path,
        num_gps_points: int = 10,
        gps_points: T.Sequence[geo.Point] | None = None,
    ) -> dict[str, T.Any]:
        """Set up all the mocks needed for _sample_single_video_by_distance."""
        probe_output = _load_probe_output()
        if gps_points is None:
            gps_points = _make_gps_points(num_gps_points, time_step=1.0)
        num_gps_points = len(gps_points)

        video_metadata = VideoMetadata(
            filename=video_path,
            filetype=FileType.CAMM,
            points=gps_points,
            make="TestMake",
            model="TestModel",
        )

        video_samples = [_make_sample(float(i)) for i in range(num_gps_points)]

        mock_track_parser = mock.MagicMock(spec=mp4_sample_parser.TrackBoxParser)
        mock_track_parser.extract_samples.return_value = iter(video_samples)

        mock_moov_parser = mock.MagicMock(spec=mp4_sample_parser.MovieBoxParser)
        mock_moov_parser.extract_track_at.return_value = mock_track_parser

        patches = {}

        # Mock FFMPEG: instance methods are mocked, classmethods delegate to real
        def fake_extract_frames(
            video_path: Path,
            sample_dir: Path,
            frame_indices: set[int],
            stream_specifier: str = "v",
        ) -> None:
            _create_fake_frames(
                sample_dir,
                video_path.stem,
                stream_specifier,
                len(frame_indices),
            )

        mock_ffmpeg_instance = mock.MagicMock(spec=ffmpeglib.FFMPEG)
        mock_ffmpeg_instance.probe_format_and_streams.return_value = probe_output
        mock_ffmpeg_instance.extract_specified_frames.side_effect = fake_extract_frames

        mock_ffmpeg_class = mock.MagicMock()
        mock_ffmpeg_class.return_value = mock_ffmpeg_instance
        mock_ffmpeg_class.sort_selected_samples = ffmpeglib.FFMPEG.sort_selected_samples
        mock_ffmpeg_class.iterate_samples = ffmpeglib.FFMPEG.iterate_samples
        mock_ffmpeg_class._extract_stream_frame_idx = (
            ffmpeglib.FFMPEG._extract_stream_frame_idx
        )
        mock_ffmpeg_class._validate_stream_specifier = (
            ffmpeglib.FFMPEG._validate_stream_specifier
        )
        mock_ffmpeg_class.FRAME_EXT = ffmpeglib.FFMPEG.FRAME_EXT

        patches["ffmpeg_cls"] = mock.patch(
            "mapillary_tools.sample_video.ffmpeglib.FFMPEG",
            mock_ffmpeg_class,
        )

        patches["geotag_cls"] = mock.patch(
            "mapillary_tools.sample_video.factory.process",
            return_value=[video_metadata],
        )

        patches["moov_parse"] = mock.patch.object(
            mp4_sample_parser.MovieBoxParser,
            "parse_file",
            return_value=mock_moov_parser,
        )

        return {
            "patches": patches,
            "gps_points": gps_points,
            "video_metadata": video_metadata,
        }

    def test_single_video_file(self, tmp_path: Path) -> None:
        """sample_video with a single video file produces sample frames."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        mocks = self._setup_mocks(tmp_path, video_file)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        sample_dir = output_dir / "test.mp4"
        assert sample_dir.is_dir()

        frames = list(sample_dir.glob("*.jpg"))
        assert len(frames) > 0

        exif = exif_read.ExifRead(frames[0])
        assert exif.extract_lon_lat() is not None
        assert exif.extract_capture_time() is not None

    def test_video_directory(self, tmp_path: Path) -> None:
        """sample_video with a directory processes all videos."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        (video_dir / "clip1.mp4").touch()
        (video_dir / "clip2.mp4").touch()
        output_dir = tmp_path / "output"

        with mock.patch.object(
            sample_video, "_sample_single_video_by_distance"
        ) as mock_sample:
            sample_video.sample_video(
                video_import_path=video_dir,
                import_path=output_dir,
                video_sample_distance=3.0,
            )
            assert mock_sample.call_count == 2

    def test_custom_start_time(self, tmp_path: Path) -> None:
        """sample_video with video_start_time override uses the given time."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        mocks = self._setup_mocks(tmp_path, video_file)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
                video_start_time="2023_06_15_12_00_00_000",
            )

        sample_dir = output_dir / "test.mp4"
        frames = list(sample_dir.glob("*.jpg"))
        assert len(frames) > 0

        exif = exif_read.ExifRead(frames[0])
        capture_time = exif.extract_capture_time()
        assert capture_time is not None
        assert capture_time.year == 2023
        assert capture_time.month == 6
        assert capture_time.day == 15

    def test_exif_lat_lon_written(self, tmp_path: Path) -> None:
        """Verify GPS coordinates are written into EXIF of sampled frames."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        mocks = self._setup_mocks(tmp_path, video_file)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        sample_dir = output_dir / "test.mp4"
        frames = sorted(sample_dir.glob("*.jpg"))
        assert len(frames) > 0

        exif = exif_read.ExifRead(frames[0])
        lon_lat = exif.extract_lon_lat()
        assert lon_lat is not None
        lon, lat = lon_lat
        # First GPS point is at (40.0, -74.0)
        assert abs(lat - 40.0) < 0.01
        assert abs(lon - (-74.0)) < 0.01

    def test_no_frame_within_the_track(self, tmp_path: Path) -> None:
        """
        A track that covers none of the video selects no frames, which is a
        failed sample, not an empty sample directory and a success
        """
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        sample_dir = tmp_path / "output" / "test.mp4"

        mocks = self._setup_mocks(tmp_path, video_file)
        # The frames are at 0s to 9s
        for point in mocks["gps_points"]:
            point.time += 100

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            with pytest.raises(
                exceptions.MapillaryVideoError,
                # how humanize words the time varies between its versions
                match="none of its frames falls within its GPS track, which starts .+ after the video starts",
            ):
                sample_video._sample_single_video_by_distance(
                    video_file, sample_dir, sample_distance=0.0
                )

        assert not sample_dir.exists()

    def test_timestamps_from_creation_time(self, tmp_path: Path) -> None:
        """Without a GPS clock, frames are timestamped from the creation time."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        mocks = self._setup_mocks(tmp_path, video_file)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        frames = sorted((output_dir / "test.mp4").glob("*.jpg"))
        assert len(frames) == 10
        for idx, frame in enumerate(frames):
            assert exif_read.ExifRead(frame).extract_capture_time() == (
                PROBE_START_TIME + datetime.timedelta(seconds=idx)
            )

    def test_timestamps_from_gps_clock(self, tmp_path: Path) -> None:
        """Frames at points with their own timestamp do not need the creation time."""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        video_file = video_dir / "test.mp4"
        video_file.touch()
        output_dir = tmp_path / "output"

        gps_start_time = datetime.datetime(
            2021, 8, 10, 6, 38, 6, tzinfo=datetime.timezone.utc
        )
        gps_points = [
            telemetry.GPSPoint(
                time=p.time,
                lat=p.lat,
                lon=p.lon,
                alt=p.alt,
                angle=p.angle,
                epoch_time=gps_start_time.timestamp() + p.time,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for p in _make_gps_points(10, time_step=1.0)
        ]
        mocks = self._setup_mocks(tmp_path, video_file, gps_points=gps_points)

        with (
            mocks["patches"]["ffmpeg_cls"],
            mocks["patches"]["geotag_cls"],
            mocks["patches"]["moov_parse"],
            mock.patch.object(
                sample_video,
                "_creation_time_to_start_time",
                side_effect=AssertionError("creation time should not be read"),
            ),
        ):
            sample_video.sample_video(
                video_import_path=video_file,
                import_path=output_dir,
                video_sample_distance=0.0,
            )

        frames = sorted((output_dir / "test.mp4").glob("*.jpg"))
        assert len(frames) == 10
        for idx, frame in enumerate(frames):
            assert exif_read.ExifRead(frame).extract_capture_time() == (
                gps_start_time + datetime.timedelta(seconds=idx)
            )


class TestFailuresAreReportedTogether:
    """
    A video that fails to sample does not stop the others. They are sampled,
    the failures are summarized by type, and one error naming
    --skip_sample_errors is raised at the end, as the process command does
    with --skip_process_errors. Raising on the first failure left the samples
    of the videos before it unprocessed, and which videos those were depended
    on the order the filesystem listed them in.
    """

    VIDEO = _PWD.joinpath("data/mock_sample_video/videos/hello.mp4")

    @pytest.fixture
    def video_dir(self, tmp_path: Path, monkeypatch) -> Path:
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        videos = [video_dir / name for name in ["c.mp4", "a.mp4", "b.mp4"]]
        for video in videos:
            video.touch()
        # Listed out of order, as a filesystem may list them
        monkeypatch.setattr(
            sample_video.utils, "find_videos", lambda *args, **kwargs: videos
        )
        return video_dir

    @pytest.fixture
    def attempted(self, monkeypatch) -> list[str]:
        """
        Sample a video by creating its sample directory, unless it is named
        a.mp4 (no GPS) or b.mp4 (unreadable)
        """
        attempted: list[str] = []

        def fake_sample(video_path: Path, sample_dir: Path, **kwargs) -> None:
            attempted.append(video_path.name)
            if video_path.name == "a.mp4":
                raise exceptions.MapillaryVideoGPSNotFoundError("No GPS data found")
            if video_path.name == "b.mp4":
                raise exceptions.MapillaryVideoError("Unreadable")
            sample_dir.mkdir(parents=True)

        monkeypatch.setattr(
            sample_video, "_sample_single_video_by_distance", fake_sample
        )
        return attempted

    def test_every_video_is_sampled_in_order(
        self, tmp_path: Path, video_dir: Path, attempted: list[str]
    ):
        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(video_dir, tmp_path / "output")

        assert attempted == ["a.mp4", "b.mp4", "c.mp4"]
        assert (tmp_path / "output" / "c.mp4").is_dir()

    def test_one_error_names_the_flag(
        self, tmp_path: Path, video_dir: Path, attempted: list[str]
    ):
        """
        --skip_process_errors governs the later geotagging stage and does not
        cover sampling, so the message has to name --skip_sample_errors or
        users reach for the wrong flag.
        """
        with pytest.raises(exceptions.MapillaryVideoSampleError) as excinfo:
            sample_video.sample_video(video_dir, tmp_path / "output")

        assert str(excinfo.value) == (
            "Failed to sample 2 videos. To skip these errors, specify --skip_sample_errors"
        )

    def test_the_summary_counts_failures_by_type(
        self, tmp_path: Path, video_dir: Path, attempted: list[str], caplog
    ):
        caplog.set_level(logging.INFO)
        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(video_dir, tmp_path / "output")

        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert f"Failed to sample {video_dir / 'a.mp4'}: No GPS data found" in errors
        assert f"Failed to sample {video_dir / 'b.mp4'}: Unreadable" in errors
        assert "\t1 MapillaryVideoGPSNotFoundError" in errors
        assert "\t1 MapillaryVideoError" in errors
        assert "3 videos found" in caplog.text
        assert "\t1 sampled" in caplog.text

    def test_skip_sample_errors_downgrades_them_to_warnings(
        self, tmp_path: Path, video_dir: Path, attempted: list[str], caplog
    ):
        sample_video.sample_video(
            video_dir, tmp_path / "output", skip_sample_errors=True
        )

        assert attempted == ["a.mp4", "b.mp4", "c.mp4"]
        assert not [r for r in caplog.records if r.levelname == "ERROR"]
        assert "\t1 MapillaryVideoGPSNotFoundError" in caplog.text

    def test_the_import_path_exists_even_if_nothing_samples(
        self, tmp_path: Path, attempted: list[str]
    ):
        """
        video_process runs the process command on the import path next, which
        fails on a missing one: skipping every video used to end in "Import
        file or directory not found"
        """
        video = tmp_path / "a.mp4"
        video.touch()

        sample_video.sample_video(video, tmp_path / "output", skip_sample_errors=True)

        assert (tmp_path / "output").is_dir()
        assert not list((tmp_path / "output").iterdir())

    def test_unreadable_start_time_by_interval(
        self, tmpdir, setup_mock, monkeypatch, caplog
    ):
        monkeypatch.setattr(
            sample_video, "_extract_video_start_time", lambda *args: None
        )

        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(
                self.VIDEO,
                Path(tmpdir),
                rerun=True,
                video_sample_distance=-1,
                video_sample_interval=2,
            )

        assert "Unable to extract video start time" in caplog.text

    def test_unreadable_start_time_by_distance(
        self, tmpdir, setup_mock, monkeypatch, caplog
    ):
        """
        Distance sampling looks the start time up only for the frames at
        points without an absolute time, and fails if it cannot be found
        """
        # plain points: no GPS clock to take the start time from
        points = _make_gps_points(4, time_step=1.0)
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options: [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.VIDEO,
                    points=points,
                )
            ],
        )
        monkeypatch.setattr(
            ffmpeglib.Probe,
            "probe_video_with_max_resolution",
            lambda _self: {"index": 0},
        )
        monkeypatch.setattr(
            mp4_sample_parser.MovieBoxParser, "parse_file", mock.MagicMock()
        )
        monkeypatch.setattr(
            sample_video,
            "_sample_video_stream_by_distance",
            lambda *args: {0: (mock.MagicMock(), points[0])},
        )
        monkeypatch.setattr(
            sample_video, "_creation_time_to_start_time", lambda *args: None
        )

        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(
                self.VIDEO, Path(tmpdir), rerun=True, video_sample_distance=2
            )

        assert "Unable to extract video start time" in caplog.text

    def test_a_missing_ffmpeg_is_still_fatal(self, tmpdir, setup_mock, monkeypatch):
        """
        FFmpegNotFoundError fails every video alike, so it is raised at once,
        --skip_sample_errors or not, and its message must not offer the flag
        """

        def boom(*args, **kwargs):
            raise ffmpeglib.FFmpegNotFoundError("ffmpeg not found")

        monkeypatch.setattr(MOCK_FFMPEG, "extract_frames_by_interval", boom)

        with pytest.raises(exceptions.MapillaryFFmpegNotFoundError) as excinfo:
            sample_video.sample_video(
                self.VIDEO,
                Path(tmpdir),
                video_sample_distance=-1,
                video_sample_interval=2,
                rerun=True,
                skip_sample_errors=True,
            )

        assert "--skip_sample_errors" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Distance sampling honours --geotag_source
# ---------------------------------------------------------------------------


class TestGeotagSourceReachesDistanceSampling:
    """
    Distance sampling read the video's own telemetry directly, bypassing the
    geotag factory, so --geotag_source was ignored: a GPX attached to rescue a
    camera whose embedded GPS is unusable never got a chance to supply the
    positions the sampler picks frames with.
    """

    def test_no_sources_requested_means_native_only(self):
        """
        Not DEFAULT_GEOTAG_SOURCE_OPTIONS: that chain continues on to
        exiftool_runtime, whose parser cannot see every field the noise filter
        rejects on, so it would accept tracks the native parser refuses.
        """
        options = sample_video._parse_geotag_options(
            None, None, None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.NATIVE]

    def test_requested_source_is_passed_through(self):
        options = sample_video._parse_geotag_options(
            ["gpx"], Path("/data/track.gpx"), None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.GPX]
        assert options[0].source_path is not None
        assert options[0].source_path.source_path == Path("/data/track.gpx")

    def test_video_geotag_source_is_honoured_too(self):
        options = sample_video._parse_geotag_options(
            None, Path("/data/track.gpx"), ["gpx"], Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.GPX]

    @pytest.mark.parametrize("source", ["exiftool_xml", "gpx"])
    def test_without_a_path_sources_get_the_video_import_path(self, source):
        """
        As when the frames are geotagged. That is how exiftool_xml finds the
        XML files in the video directory; a GPX gets no sidecar lookup.
        """
        options = sample_video._parse_geotag_options(
            [source], None, None, Path("/data/videos")
        )

        assert options[0].source_path is not None
        assert options[0].source_path.source_path == Path("/data/videos")

    def test_chained_sources_are_preserved(self):
        options = sample_video._parse_geotag_options(
            ["native", "gpx"], Path("/data/track.gpx"), None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [
            SourceType.NATIVE,
            SourceType.GPX,
        ]

    def test_the_sampler_asks_the_factory_for_them(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """The options reach factory.process() rather than being dropped."""
        seen: list = []
        points = _make_gps_points(4, time_step=1.0)

        def fake_process(paths, options):
            seen.append(list(options))
            return [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.GOPRO,
                    points=points,
                )
            ]

        monkeypatch.setattr(sample_video.factory, "process", fake_process)
        # stop after the metadata is read; the rest needs real ffmpeg
        monkeypatch.setattr(
            ffmpeglib.Probe, "probe_video_with_max_resolution", lambda _self: None
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            sample_video.sample_video(
                _PWD.joinpath("data/mock_sample_video/videos/hello.mp4"),
                Path(tmpdir),
                video_sample_distance=2,
                rerun=True,
                geotag_source=["gpx"],
                geotag_source_path=Path("/data/track.gpx"),
            )

        assert len(seen) == 1
        assert [option.source for option in seen[0]] == [SourceType.GPX]


class TestSourcesThatCannotReadVideos:
    """
    exif, nmea and the legacy gopro/blackvue/camm sources have no video
    extractor, so process() returned no metadata for the video and the sampler
    failed an assert, for a video it used to sample by its own GPS.
    """

    @pytest.mark.parametrize("source", ["exif", "nmea", "gopro", "blackvue", "camm"])
    def test_sampling_falls_back_to_the_video_gps(self, source):
        options = sample_video._parse_geotag_options(
            [source], Path("/data/track"), None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.NATIVE]

    def test_they_are_dropped_from_a_chain(self):
        options = sample_video._parse_geotag_options(
            ["exif", "gpx"], Path("/data/track.gpx"), None, Path("/data/v.mp4")
        )

        assert [option.source for option in options] == [SourceType.GPX]

    def test_a_source_limited_to_images_is_dropped(self):
        options = sample_video._parse_geotag_options(
            ['{"source": "gpx", "filetypes": ["image"]}'],
            Path("/data/track.gpx"),
            None,
            Path("/data/v.mp4"),
        )

        assert [option.source for option in options] == [SourceType.NATIVE]


class TestVideoStartTimeReachesTheGPX:
    """
    A GPX on a video without GPS was assumed to start with the video, and
    --video_start_time was ignored, so every clip of a drive sampled the first
    minutes of its GPX, and was stamped with their times.
    """

    def test_every_option_carries_it(self):
        video_sync = VideoSyncOption(start_time=1_700_000_000.0)

        for sources in [None, ["gpx"], ["exif"]]:
            options = sample_video._parse_geotag_options(
                sources, Path("/data/track.gpx"), None, Path("/data/v.mp4"), video_sync
            )
            assert all(option.video_sync is video_sync for option in options)

    def test_sample_video_passes_it_on(self, tmpdir, setup_mock, monkeypatch):
        seen: list = []

        def fake_process(paths, options):
            seen.extend(options)
            return [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.VIDEO,
                    points=_make_gps_points(4, time_step=1.0),
                )
            ]

        monkeypatch.setattr(sample_video.factory, "process", fake_process)
        # stop after the metadata is read; the rest needs real ffmpeg
        monkeypatch.setattr(
            ffmpeglib.Probe, "probe_video_with_max_resolution", lambda _self: None
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            sample_video.sample_video(
                _PWD.joinpath("data/mock_sample_video/videos/hello.mp4"),
                Path(tmpdir),
                video_sample_distance=2,
                rerun=True,
                video_start_time="2025_03_14_07_00_30_000",
                geotag_source=["gpx"],
                geotag_source_path=Path("/data/track.gpx"),
            )

        expected = datetime.datetime(
            2025, 3, 14, 7, 0, 30, tzinfo=datetime.timezone.utc
        ).timestamp()
        assert seen[0].video_sync == VideoSyncOption(start_time=expected)

    def test_sample_video_passes_the_interpolation_options_on(
        self, tmpdir, setup_mock, monkeypatch
    ):
        """video_process registers them for its geotagging stage."""
        seen: list = []

        def fake_process(paths, options):
            seen.extend(options)
            return [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.VIDEO,
                    points=_make_gps_points(4, time_step=1.0),
                )
            ]

        monkeypatch.setattr(sample_video.factory, "process", fake_process)
        monkeypatch.setattr(
            ffmpeglib.Probe, "probe_video_with_max_resolution", lambda _self: None
        )

        with pytest.raises(exceptions.MapillaryVideoError):
            sample_video.sample_video(
                _PWD.joinpath("data/mock_sample_video/videos/hello.mp4"),
                Path(tmpdir),
                video_sample_distance=2,
                rerun=True,
                geotag_source=["gpx"],
                geotag_source_path=Path("/data/track.gpx"),
                interpolation_offset_time=2.5,
                interpolation_use_gpx_start_time=True,
            )

        assert seen[0].video_sync == VideoSyncOption(
            offset_time=2.5, use_gpx_start_time=True
        )

    def test_without_it_the_start_time_is_left_unknown(self):
        """
        A video without a GPS clock would get its start time from its creation
        time, which cameras stamp at the start or the end of the recording.
        """
        options = sample_video._parse_geotag_options(
            ["gpx"], Path("/data/track.gpx"), None, Path("/data/v.mp4"), None
        )

        assert options[0].video_sync is None


class TestTrackThatMissesTheVideo:
    def test_it_fails_instead_of_writing_an_empty_sample_directory(
        self, tmpdir, setup_mock, monkeypatch, caplog
    ):
        """
        A GPX placed by a wrong --video_start_time selects no frames. The
        video counts as failed, and the log says why.
        """
        points = _make_gps_points(4, time_step=1.0)
        for point in points:
            point.time -= 7200
        monkeypatch.setattr(
            sample_video.factory,
            "process",
            lambda paths, options: [
                VideoMetadata(
                    filename=paths[0],
                    filesize=1,
                    filetype=FileType.VIDEO,
                    points=points,
                )
            ],
        )
        monkeypatch.setattr(
            ffmpeglib.Probe,
            "probe_video_with_max_resolution",
            lambda _self: {"index": 0},
        )
        monkeypatch.setattr(
            mp4_sample_parser.MovieBoxParser, "parse_file", mock.MagicMock()
        )
        monkeypatch.setattr(
            sample_video, "_sample_video_stream_by_distance", lambda *args: {}
        )

        with pytest.raises(exceptions.MapillaryVideoSampleError):
            sample_video.sample_video(
                _PWD.joinpath("data/mock_sample_video/videos/hello.mp4"),
                Path(tmpdir),
                video_sample_distance=2,
                rerun=True,
            )

        assert "none of its frames falls within its GPS track" in caplog.text
        assert "before the video starts" in caplog.text
        assert not Path(tmpdir).joinpath("hello.mp4").exists()
