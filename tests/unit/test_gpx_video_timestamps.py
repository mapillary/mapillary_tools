# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
The GPS timestamps of a video, which its GPS clock is fitted to, and the GPX
tracks placed by that clock: a straight line, from which the timestamps of a
camera that records in real time jitter by up to a second or more.
"""

from __future__ import annotations

import datetime
import typing as T
from pathlib import Path

import pytest
from mapillary_tools import geo, telemetry, types
from mapillary_tools.geotag.options import InterpolationOption, VideoSyncOption
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor, VideoClock

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


def _read(pairs: T.Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    return [
        (v, round(u - START.timestamp(), 3))
        for v, u in GPXVideoExtractor._read_timestamps(_points(pairs))
    ]


def _clock(pairs: T.Iterable[tuple[float, float]]) -> VideoClock:
    clock = GPXVideoExtractor._read_video_clock(_points(pairs))
    assert clock is not None
    return clock


class TestReadTimestamps:
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
        assert _read([(0, 0), (0.1, 3.9), (0.2, 4.9), (0.3, 5.9)]) == [
            (0.1, 3.9),
            (0.2, 4.9),
            (0.3, 5.9),
        ]

    def test_with_the_steps_of_a_clock_that_gains(self):
        """Further on, a step twice as fast as the clock is the clock's"""
        pairs = [(0, 0), (1, 1), (2, 2), (2.5, 3), (3.5, 4), (4, 5), (5, 6)]

        assert _read(pairs) == pairs

    def test_with_the_steps_of_a_short_timelapse(self):
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

        timestamps = _read(pairs)

        assert (2, 60) not in timestamps
        assert len(timestamps) == 5
        assert [u for _, u in timestamps] == sorted(u for _, u in timestamps)

    def test_without_a_placeholder_date(self):
        """GoPro stamps a date in 2015 until the GPS acquires the time"""
        days = 10 * 365 * 86400
        pairs = [(0, -days), (1, -days + 1), (2, 2), (3, 3)]

        assert _read(pairs) == [(2, 2), (3, 3)]

    def test_none_without_timestamps(self):
        points = _points([(0, 0)])
        points[0] = geo.Point(time=0, lat=37, lon=-122, alt=None, angle=None)

        assert GPXVideoExtractor._read_timestamps(points) == []


# A GoPro's timestamps of blocks of 1.001 seconds of video, which jitter by
# up to a second off the straight line through them
JITTER = [0.0, 0.6, -0.4, 0.9, 0.1, -0.5, 0.3, 1.0, -0.2, 0.0, 0.4, -0.6, 0.2]
GOPRO_PAIRS = [(1.001 * i, 1.001 * i + j) for i, j in enumerate(JITTER)]


class TestStraightClock:
    def test_a_camera_that_records_in_real_time(self):
        """Not through its timestamps, which stamp 1 second as 0.1 to 2 seconds"""
        clock = _clock(GOPRO_PAIRS)

        assert clock.rate == 1.0
        # Anchored at the median of its timestamps
        assert clock.to_unix_time(0) == pytest.approx(START.timestamp() + 0.1)

    def test_a_clock_that_gains_on_the_video(self):
        """
        A LabPano gains a second on the video every 7 seconds, in steps of a
        second per half second, and its timestamps fit 8/7 GPS seconds per
        second of video within 0.3 seconds
        """
        pairs = [(round(s * 7 / 8 * 2) / 2, s) for s in range(200)]

        clock = _clock(pairs)

        assert clock.rate == pytest.approx(8 / 7, abs=0.001)
        for v, u in pairs:
            assert clock.to_unix_time(v) - START.timestamp() == pytest.approx(
                u, abs=0.3
            )

    def test_a_rate_within_a_few_percent_is_1(self):
        """
        A GoPro MAX whose GPS glitches measures 1.6% off 1x over 3 minutes.
        It records in real time
        """
        clock = _clock((i, i * 0.984) for i in range(190))

        assert clock.rate == 1.0

    def test_a_rate_measured_over_a_short_clip_is_1(self):
        """
        Over a few seconds, a second of jitter measures a rate 15% off 1x, a
        drift of half a second
        """
        clock = _clock([(0, 0), (1, 1.4), (2, 2.1), (3, 3.45)])

        assert clock.rate == 1.0

    def test_a_short_timelapse(self):
        """
        Its rate, 12.4x over less than a second of video, drifts by 11
        seconds from 1x
        """
        clock = _clock((seconds / 12.4, seconds) for seconds in range(13))

        assert clock.rate == pytest.approx(12.4)

    def test_a_stale_first_timestamp_off_the_line(self):
        clock = _clock([(0, -5), *GOPRO_PAIRS[1:]])

        assert clock.rate == 1.0
        assert clock.to_unix_time(0) == pytest.approx(START.timestamp() + 0.1)

    def test_a_timestamp_far_off_makes_no_timelapse(self):
        """It pulls the least-squares slope past the timelapse rate"""
        pairs = [(i, i) for i in range(9)] + [(9, 30)]

        assert _clock(pairs).rate == 1.0


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
    """
    GPX sync places each GPX point at the video time of its GPS time by the
    straight clock of the video, not through the timestamps of the video,
    whose jitter is not that of the GPX
    """

    # The GPX records a point every second
    GPX_SECONDS = [float(s) for s in range(13)]

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
        gpx = _gpx(tmp_path / "track.gpx", self.GPX_SECONDS)
        metadata = GPXVideoExtractor(VIDEO, gpx, **kwargs).extract()
        return {
            round(T.cast(float, p.get_unix_time()) - START.timestamp(), 3): p.time
            for p in metadata.points
        }

    @pytest.mark.parametrize("video_sync", [VideoSyncOption(), None])
    def test_by_the_straight_clock(self, tmp_path, monkeypatch, video_sync):
        """In distance sampling and in process"""
        self.mock_video_gps(monkeypatch, GOPRO_PAIRS)

        placed = self._extract(tmp_path, video_sync=video_sync)

        # A second of video per second of the GPX, from the median of the
        # timestamps of the video, 0.1 seconds after START
        for seconds in self.GPX_SECONDS:
            assert placed[seconds] == pytest.approx(seconds - 0.1)

    def test_at_the_pace_of_a_clock_that_gains(self, tmp_path, monkeypatch):
        # Over 30 seconds, as 12 are too few to tell 8/7 from 1x (by 1.7 s)
        self.mock_video_gps(monkeypatch, [(i, i * 8 / 7) for i in range(30)])
        self.GPX_SECONDS = [float(s) for s in range(15)]

        placed = self._extract(tmp_path, video_sync=VideoSyncOption())

        for seconds in self.GPX_SECONDS:
            assert placed[seconds] == pytest.approx(seconds * 7 / 8)

    def test_the_offset_in_gps_seconds(self, tmp_path, monkeypatch):
        """
        The video is looked up 1 GPS second further along the track, whose
        points keep their times in process
        """
        self.mock_video_gps(monkeypatch, GOPRO_PAIRS)

        placed = self._extract(
            tmp_path, interpolation=InterpolationOption(offset_time=1)
        )

        for seconds in self.GPX_SECONDS:
            assert placed[seconds] == pytest.approx(seconds - 0.1 - 1)

    def test_started_with_the_video_at_the_pace_of_the_clock(
        self, tmp_path, monkeypatch
    ):
        # The timestamps of the video 100 seconds before the GPX, 8/7 times as
        # fast as the video
        self.mock_video_gps(monkeypatch, [(i, i * 8 / 7 - 100) for i in range(30)])

        placed = self._extract(
            tmp_path,
            video_sync=VideoSyncOption(),
            interpolation=InterpolationOption(use_gpx_start_time=True),
        )

        for seconds in self.GPX_SECONDS:
            assert placed[seconds] == pytest.approx(seconds * 7 / 8)

    def test_gps_rejected_as_noise_by_its_clock(self, tmp_path, monkeypatch):
        self.mock_video_gps(monkeypatch, GOPRO_PAIRS, noisy=True)

        placed = self._extract(tmp_path, video_sync=VideoSyncOption())

        for seconds in self.GPX_SECONDS:
            assert placed[seconds] == pytest.approx(seconds - 0.1)
