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
from mapillary_tools.mp4 import construct_mp4_parser as cparser, mp4_sample_parser
from mapillary_tools.serializer import description
from mapillary_tools.types import FileType, VideoMetadata

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


def _validate_interval(samples: T.Sequence[Path], video_start_time):
    assert len(samples), "expect samples but got none"
    for idx, sample in enumerate(sorted(samples)):
        assert sample.name == f"hello_v_{idx + 1:06d}.jpg"
        exif = exif_read.ExifRead(sample)
        expected_dt = video_start_time + datetime.timedelta(seconds=2 * idx)
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
    assert "Unable to read the start time of hello.mp4 from its telemetry" in (
        caplog.text
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

        mock_geotag_instance = mock.MagicMock()
        mock_geotag_instance.to_description.return_value = [video_metadata]
        patches["geotag_cls"] = mock.patch(
            "mapillary_tools.sample_video.geotag_videos_from_video.GeotagVideosFromVideo",
            return_value=mock_geotag_instance,
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
