# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Syncing a GPX to the GPS clock of a video, timelapses included.

A timelapse compresses time: each second of video spans several seconds of
GPS time, so a GPX synced at 1x lands past the end of the video.
"""

from __future__ import annotations

import typing as T
from pathlib import Path

import pytest

from mapillary_tools import geo
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor, VideoClock
from mapillary_tools.gpmf import gpmf_parser
from mapillary_tools.telemetry import GPSFix, GPSPoint


# 2026-09-11T15:39:41Z
A_UNIX_TIME = 1789141181.0

# GoPro stamps this date until it acquires GPS time (2015-10-22T09:53:44Z)
PLACEHOLDER_UNIX_TIME = 1445507624.0


def _point(
    time: float, epoch_time: float, fix: GPSFix = GPSFix.FIX_3D, precision=150.0
) -> GPSPoint:
    return GPSPoint(
        time=time,
        lat=48.1737635,
        lon=11.5972871,
        alt=559.275,
        angle=None,
        epoch_time=epoch_time,
        fix=fix,
        precision=precision,
        ground_speed=0.749,
    )


def _clock_points(pairs: T.Iterable[tuple[float, float]]) -> list[geo.Point]:
    return [_point(time=v, epoch_time=u) for v, u in pairs]


def _read(pairs: T.Iterable[tuple[float, float]]) -> VideoClock:
    clock = GPXVideoExtractor._read_video_clock(_clock_points(pairs))
    assert clock is not None
    return clock


class TestVideoClock:
    def test_normal_video(self):
        clock = _read((i, A_UNIX_TIME + i) for i in range(10))
        assert clock == VideoClock(video_time=0, unix_time=A_UNIX_TIME)

    def test_first_timestamp_is_anchored_at_its_own_video_time(self):
        clock = _read((40 + i, A_UNIX_TIME + i) for i in range(10))
        assert clock.to_video_time(A_UNIX_TIME) == 40
        assert clock.to_video_time(A_UNIX_TIME + 5) == 45

    @pytest.mark.parametrize("rate", [2.0, 12.5, 30.0])
    def test_timelapse(self, rate):
        """1s of video spans `rate` seconds of GPS time."""
        clock = _read((i * 0.1, A_UNIX_TIME + i * 0.1 * rate) for i in range(20))
        assert clock.rate == pytest.approx(rate)
        assert clock.to_video_time(A_UNIX_TIME + rate) == pytest.approx(1.0)

    def test_small_rate_error_is_not_a_timelapse(self):
        """Block timestamps make short clips measure a little off 1x."""
        clock = _read((i, A_UNIX_TIME + i * 1.2) for i in range(6))
        assert clock.rate == 1.0

    def test_too_short_to_measure_a_rate(self):
        clock = _read((i * 0.1, A_UNIX_TIME + i * 1.5) for i in range(9))
        assert clock.rate == 1.0

    def test_block_timestamps_anchor_at_the_block_start(self):
        """
        GPS5 GoPros stamp a whole ~1s block of points with one timestamp. The
        blocks, not the points, measure the clock.
        """
        clock = _read(
            (b + i * 0.1, A_UNIX_TIME + b * 15) for b in range(4) for i in range(10)
        )
        assert clock.rate == pytest.approx(15)
        assert clock.to_video_time(A_UNIX_TIME + 30) == pytest.approx(2.0)

    @pytest.mark.parametrize(
        "pairs",
        [
            # The last timestamp is an hour off
            [(i, A_UNIX_TIME + i) for i in range(19)] + [(19, A_UNIX_TIME + 3619)],
            # One timestamp is two days off
            [(i, A_UNIX_TIME + i + (2 * 86400 if i == 5 else 0)) for i in range(11)],
            # The clock steps 20s ahead halfway through
            [(i, A_UNIX_TIME + i + (20 if 5 <= i else 0)) for i in range(10)],
            # A placeholder date until GPS time is acquired
            [(i, PLACEHOLDER_UNIX_TIME + i) for i in range(5)]
            + [(i, A_UNIX_TIME + i) for i in range(5, 15)],
        ],
    )
    def test_one_jump_does_not_make_a_timelapse(self, pairs):
        assert _read(pairs).rate == 1.0

    @pytest.mark.parametrize("rate", [1.0, 30.0])
    def test_a_first_timestamp_off_the_rest_does_not_anchor_the_clock(self, rate):
        """The first GPS block of a GoPro timelapse can be stamped 3s early."""
        pairs = [(0, A_UNIX_TIME - 3)] + [
            (i / rate, A_UNIX_TIME + i) for i in range(1, 60)
        ]
        clock = _read(pairs)
        assert clock.rate == pytest.approx(rate, rel=0.05)
        assert clock.to_unix_time(0) == pytest.approx(A_UNIX_TIME, abs=0.2)

    def test_a_placeholder_date_does_not_anchor_the_clock(self):
        """GoPro stamps a placeholder date until it acquires GPS time."""
        pairs = [(i, PLACEHOLDER_UNIX_TIME + i) for i in range(5)] + [
            (i, A_UNIX_TIME + i) for i in range(5, 15)
        ]
        assert _read(pairs).to_unix_time(0) == A_UNIX_TIME

    def test_no_timestamps(self):
        points = [
            geo.Point(time=i, lat=1, lon=1, alt=None, angle=None) for i in range(3)
        ]
        assert GPXVideoExtractor._read_video_clock(points) is None


def test_timelapse_gpx_lands_in_the_video(monkeypatch, tmp_path: Path):
    """
    The shape of the reported capture: 1.24s of 12.5x timelapse video, covering
    15.5s of GPS time, with GPS too noisy to publish. At 1x its GPX landed at
    2s..14s, past the end of the video.
    """
    points = [
        _point(
            time=i * 0.04,
            epoch_time=A_UNIX_TIME + i * 0.04 * 12.5,
            fix=GPSFix.NO_FIX,
            precision=2139.0,
        )
        for i in range(32)
    ]
    info = gpmf_parser.GoProInfo(gps=points, make="GoPro", model="MAX2")
    monkeypatch.setattr(gpmf_parser, "extract_gopro_info", lambda *a, **kw: info)
    video_path = tmp_path / "GS018205.360"
    video_path.write_bytes(b"not a real mp4")
    gpx_path = tmp_path / "GS018205.360.gpx"
    gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="test">
  <trk><trkseg>
<trkpt lat="48.170" lon="11.590"><time>2026-09-11T15:39:43Z</time></trkpt>
<trkpt lat="48.171" lon="11.591"><time>2026-09-11T15:39:55Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""
    )

    metadata = GPXVideoExtractor(video_path, gpx_path).extract()

    assert [p.time for p in metadata.points] == pytest.approx([0.16, 1.12])
