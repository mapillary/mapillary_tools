# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
The GPS time of a video along it, through its GPS timestamps, and the GPX
tracks placed by it: GPX sync looks each GPX point up along it, as interval
samples are stamped by it.
"""

from __future__ import annotations

import datetime
import typing as T
from pathlib import Path

import pytest
from mapillary_tools import geo, telemetry, types
from mapillary_tools.geotag.options import InterpolationOption, VideoSyncOption
from mapillary_tools.geotag.video_extractors.gpx import (
    GPSTimeline,
    GPXVideoExtractor,
    VideoClock,
)

_DATA = Path(__file__).resolve().parent.parent.joinpath("data")

# 12.137125 seconds long, its own GPS replaced below
VIDEO = _DATA.joinpath("gopro_data", "max-360mode.mp4")

START = datetime.datetime(2025, 3, 14, 7, 0, 0, tzinfo=datetime.timezone.utc)


def _points(pairs: T.Iterable[tuple[float, float]]) -> list[geo.Point]:
    """Points at (video time, GPS seconds from START), heading north at 1 m/s"""
    return [
        telemetry.GPSPoint(
            time=video_time,
            lat=37.0 + seconds / 111_320,
            lon=-122.0,
            alt=None,
            angle=None,
            epoch_time=START.timestamp() + seconds,
            fix=None,
            precision=None,
            ground_speed=None,
        )
        for video_time, seconds in pairs
    ]


def _read(pairs: T.Iterable[tuple[float, float]], rate: float = 1.0):
    timeline = GPSTimeline.read(_points(pairs), rate)
    assert timeline is not None
    return [
        (v, round(u - START.timestamp(), 3))
        for v, u in zip(timeline.video_times, timeline.unix_times)
    ]


class TestRead:
    def test_through_the_timestamps(self):
        timeline = GPSTimeline.read(_points([(0, 0), (1, 1), (2, 3)]), rate=1.0)
        assert timeline is not None

        assert timeline.to_unix_time(1.5) == START.timestamp() + 2
        assert timeline.to_video_time(START.timestamp() + 2) == 1.5
        # beyond them, at the rate
        assert timeline.to_unix_time(3) == START.timestamp() + 4

    def test_the_first_point_of_a_block(self):
        """GoPro stamps a block of points with one timestamp"""
        assert _read([(0, 0), (0.5, 0), (1, 1), (1.5, 1), (2, 2)]) == [
            (0, 0),
            (1, 1),
            (2, 2),
        ]

    def test_without_a_stale_first_timestamp(self):
        """A PANOX V2 stamps its first fix 7.6 seconds before the rest"""
        assert _read([(0, -7.6), (0.4, 0.4), (1.4, 1.4), (2.4, 2.4)]) == [
            (0.4, 0.4),
            (1.4, 1.4),
            (2.4, 2.4),
        ]

    def test_without_stale_first_timestamps_of_a_timelapse(self):
        """Those of a timelapse run more than its rate behind the rest"""
        assert _read([(0, 0), (0.1, 3.9), (0.2, 4.9), (0.3, 5.9)], rate=10) == [
            (0.1, 3.9),
            (0.2, 4.9),
            (0.3, 5.9),
        ]

    def test_with_the_steps_of_a_clock_that_gains(self):
        """Further on, a step twice as fast as the clock is the clock's"""
        pairs = [(0, 0), (1, 1), (2, 2), (2.5, 3), (3.5, 4), (4, 5), (5, 6)]

        assert _read(pairs) == pairs

    def test_with_the_steps_of_a_short_timelapse(self):
        """Over less than a second of video, too short to measure, its rate is 1"""
        pairs = [(0, 0), (0.08, 1), (0.16, 2), (0.24, 3)]

        assert _read(pairs) == pairs

    def test_without_a_stale_first_timestamp_of_a_short_timelapse(self):
        assert _read([(0, -5), (0.08, 1), (0.16, 2), (0.24, 3)]) == [
            (0.08, 1),
            (0.16, 2),
            (0.24, 3),
        ]

    def test_without_timestamps_out_of_order(self):
        pairs = [(0, 0), (1, 1), (2, 60), (3, 3), (4, 4), (5, 3.5), (6, 6)]

        timeline = _read(pairs)

        assert (2, 60) not in timeline
        assert len(timeline) == 5
        assert [u for _, u in timeline] == sorted(u for _, u in timeline)

    def test_without_a_placeholder_date(self):
        """GoPro stamps a date in 2015 until the GPS acquires the time"""
        days = 10 * 365 * 86400
        pairs = [(0, -days), (1, -days + 1), (2, 2), (3, 3)]

        assert _read(pairs) == [(2, 2), (3, 3)]

    def test_none_without_timestamps(self):
        points = _points([(0, 0)])
        points[0] = geo.Point(time=0, lat=37, lon=-122, alt=None, angle=None)

        assert GPSTimeline.read(points, rate=1.0) is None

    def test_starting_at(self):
        timeline = GPSTimeline.read(_points([(0, 0), (1, 1), (2, 3)]), rate=1.0)
        assert timeline is not None

        started = timeline.starting_at(0.5, START.timestamp() + 100)

        assert started.to_unix_time(0.5) == pytest.approx(START.timestamp() + 100)
        # at its pace
        assert started.to_unix_time(2) == pytest.approx(START.timestamp() + 102.5)


def _gpx(path: Path, seconds: T.Iterable[float]) -> Path:
    """A GPX track with a point at each of the GPS seconds from START"""
    trkpts = "".join(
        f'<trkpt lat="{37.0 + s / 111_320:.9f}" lon="-122.0"><time>'
        f"{(START + datetime.timedelta(seconds=s)).isoformat()}</time></trkpt>"
        for s in seconds
    )
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{trkpts}</trkseg></trk></gpx>\n"
    )
    return path


class TestGPXPlacement:
    """GPX sync places each GPX point at the video time of its GPS time"""

    # Over the 12 seconds of the video, the clock gains 2 seconds
    PAIRS = [
        (0, 0),
        (1, 1),
        (2, 2),
        (3, 3),
        (3.5, 4),
        (4.5, 5),
        (5.5, 6),
        (6.5, 7),
        (7, 8),
        (8, 9),
        (9, 10),
        (10, 11),
        (11, 12),
        (12, 13),
    ]

    @pytest.fixture
    def video_gps(self, monkeypatch):
        self.mock_video_gps(monkeypatch, self.PAIRS)

    @staticmethod
    def mock_video_gps(
        monkeypatch, pairs: T.Sequence[tuple[float, float]], noisy: bool = False
    ):
        monkeypatch.setattr(
            GPXVideoExtractor,
            "_extract_native_video_metadata",
            lambda self: (
                types.VideoMetadata(
                    filename=VIDEO, filetype=types.FileType.GOPRO, points=_points(pairs)
                ),
                noisy,
            ),
        )

    def _extract(self, tmp_path: Path, **kwargs) -> dict[float, float]:
        """GPS seconds from START of each GPX point, to its video time"""
        gpx = _gpx(tmp_path / "track.gpx", [s for _, s in self.PAIRS])
        metadata = GPXVideoExtractor(VIDEO, gpx, **kwargs).extract()
        return {
            round(T.cast(float, p.get_unix_time()) - START.timestamp(), 3): p.time
            for p in metadata.points
        }

    def test_at_the_video_time_of_its_gps_time(self, tmp_path, video_gps):
        """
        A straight clock, anchored at the median of the timestamps, put the
        points up to a second off
        """
        placed = self._extract(tmp_path, video_sync=VideoSyncOption())

        for video_time, seconds in self.PAIRS:
            assert placed[seconds] == pytest.approx(video_time)

    def test_in_process_too(self, tmp_path, video_gps):
        placed = self._extract(tmp_path)

        for video_time, seconds in self.PAIRS:
            assert placed[seconds] == pytest.approx(video_time)

    def test_without_a_stale_first_timestamp(self, tmp_path, monkeypatch):
        self.mock_video_gps(monkeypatch, [(0, -5), *self.PAIRS[1:]])

        placed = self._extract(tmp_path, video_sync=VideoSyncOption())

        # From the second timestamp back at the clock's rate
        assert placed[0] == pytest.approx(0)
        assert placed[1] == pytest.approx(1)

    def test_the_offset_in_gps_seconds(self, tmp_path, video_gps):
        """
        The video is looked up 1 GPS second further along the track, whose
        points keep their times in process
        """
        placed = self._extract(
            tmp_path, interpolation=InterpolationOption(offset_time=1)
        )

        for (video_time, _), (_, seconds) in zip(self.PAIRS, self.PAIRS[1:]):
            assert placed[seconds] == pytest.approx(video_time)

    def test_started_with_the_video_at_the_pace_of_the_timestamps(
        self, tmp_path, monkeypatch
    ):
        # The timestamps of the video 100 seconds before the GPX
        self.mock_video_gps(monkeypatch, [(v, s - 100) for v, s in self.PAIRS])

        placed = self._extract(
            tmp_path,
            video_sync=VideoSyncOption(),
            interpolation=InterpolationOption(use_gpx_start_time=True),
        )

        for video_time, seconds in self.PAIRS:
            assert placed[seconds] == pytest.approx(video_time)

    def test_gps_rejected_as_noise_by_its_clock(self, tmp_path, monkeypatch):
        """Which gives GPX sync only its clock"""
        self.mock_video_gps(monkeypatch, self.PAIRS, noisy=True)
        clock = GPXVideoExtractor._read_video_clock(_points(self.PAIRS))
        assert isinstance(clock, VideoClock)

        placed = self._extract(tmp_path, video_sync=VideoSyncOption())

        for _, seconds in self.PAIRS:
            assert placed[seconds] == pytest.approx(
                clock.to_video_time(START.timestamp() + seconds)
            )
