# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import datetime
import json
import os
import shutil
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
)
from mapillary_tools.mp4 import mp4_sample_parser
from mapillary_tools.serializer import description
from mapillary_tools.types import FileType, VideoMetadata

_PWD = Path(os.path.dirname(os.path.abspath(__file__)))


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
    video_start_time = description.parse_capture_time("2021_08_10_14_37_05_023")
    _validate_interval([Path(s) for s in samples], video_start_time)


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
    video_start_time = description.parse_capture_time("2021_08_10_14_37_05_023")
    _validate_interval([Path(s) for s in samples], video_start_time)


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


# ---------------------------------------------------------------------------
# Helpers for distance-based sampling tests
# ---------------------------------------------------------------------------

MOCK_PROBE_JSON = _PWD / "data" / "mock_sample_video" / "videos" / "hello.mp4"
TEST_EXIF_JPG = _PWD / "data" / "test_exif.jpg"

# Start time derived from the hello.mp4 probe fixture:
# creation_time "2021-08-10T14:38:06.000000Z" - duration "60.977000"
PROBE_START_TIME = datetime.datetime(
    2021, 8, 10, 14, 36, 55, 23000, tzinfo=datetime.timezone.utc
)


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
    ) -> dict[str, T.Any]:
        """Set up all the mocks needed for _sample_single_video_by_distance."""
        probe_output = _load_probe_output()
        gps_points = _make_gps_points(num_gps_points, time_step=1.0)

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
