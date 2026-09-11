# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Regression tests for the epoch of CAMM GPS timestamps.

The CAMM box field is called ``time_gps_epoch``, but producers disagree about
what goes in it: Labpano cameras write GPS time (seconds since 1980-01-06),
while Insta360 and mapillary_tools itself write Unix time. Confusing the two
is a ~315,964,800s (10 year) error.

The invariant these tests protect: ``CAMMGPSPoint.epoch_time`` is *always*
Unix time in memory. The conversion happens exactly once, when the CAMM track
is parsed, and never again -- in particular not in the serializer, which must
keep writing Unix time so files stay readable by released versions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapillary_tools import geo, telemetry
from mapillary_tools.camm import camm_builder, camm_parser
from mapillary_tools.geotag.options import SourceOption, SourceType
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor
from mapillary_tools.mp4 import construct_mp4_parser as cparser


# Seconds between the two epochs, i.e. the size of the bug
GPS_UNIX_DELTA = 315964800

# 2026-08-12T08:26:27Z, taken from a PanoX V2 capture
A_GPS_TIME = 1470558405.9798455
A_UNIX_TIME = 1786523187.9798455


def _camm_point(time: float, epoch_time: float) -> telemetry.CAMMGPSPoint:
    return telemetry.CAMMGPSPoint(
        time=time,
        lat=37.8436443,
        lon=14.9886571,
        alt=1202.345,
        angle=None,
        epoch_time=epoch_time,
        gps_fix_type=3,
        horizontal_accuracy=0.0,
        vertical_accuracy=0.0,
        velocity_east=0.0,
        velocity_north=0.0,
        velocity_up=0.0,
        speed_accuracy=0.0,
    )


def _gps_point(time: float, epoch_time: float | None) -> telemetry.GPSPoint:
    return telemetry.GPSPoint(
        time=time,
        lat=37.8436443,
        lon=14.9886571,
        alt=1202.345,
        angle=None,
        epoch_time=epoch_time,
        fix=telemetry.GPSFix.FIX_3D,
        precision=None,
        ground_speed=None,
    )


class TestEpochConversion:
    def test_known_instant(self):
        assert telemetry.gps_epoch_to_unix(A_GPS_TIME) == A_UNIX_TIME

    def test_leap_seconds_accumulate(self):
        # No leap seconds had accumulated at the GPS epoch itself
        assert telemetry.gps_epoch_to_unix(0) == GPS_UNIX_DELTA
        # 18 by 2026, so the naive +315964800 conversion lands 18s too late
        assert (
            telemetry.gps_epoch_to_unix(A_GPS_TIME) == A_GPS_TIME + GPS_UNIX_DELTA - 18
        )


class TestParseBoundaryNormalization:
    """The one place an epoch conversion is allowed to happen."""

    def test_gps_epoch_producer_is_converted(self):
        points = [_camm_point(time=0.0, epoch_time=A_GPS_TIME)]
        camm_parser._normalize_gps_epochs(points, "Labpano")
        assert points[0].epoch_time == A_UNIX_TIME
        assert points[0].get_unix_time() == A_UNIX_TIME

    @pytest.mark.parametrize("make", ["Insta360", "GoPro", "", "Unknown"])
    def test_unix_producers_are_left_alone(self, make: str):
        """Converting these would push them ~10 years into the future."""
        points = [_camm_point(time=0.0, epoch_time=A_UNIX_TIME)]
        camm_parser._normalize_gps_epochs(points, make)
        assert points[0].epoch_time == A_UNIX_TIME

    def test_make_match_is_case_insensitive(self):
        for make in ["labpano", "LABPANO", " Labpano "]:
            points = [_camm_point(time=0.0, epoch_time=A_GPS_TIME)]
            camm_parser._normalize_gps_epochs(points, make)
            assert points[0].epoch_time == A_UNIX_TIME, make

    def test_invalid_timestamps_are_not_converted(self):
        """A zero timestamp must stay zero, not become 1980."""
        points = [_camm_point(time=0.0, epoch_time=0.0)]
        camm_parser._normalize_gps_epochs(points, "Labpano")
        assert points[0].epoch_time == 0.0
        assert points[0].get_unix_time() is None


class TestPointAccessors:
    def test_both_point_types_report_unix_time(self):
        assert _camm_point(0.0, A_UNIX_TIME).get_unix_time() == A_UNIX_TIME
        assert _gps_point(0.0, A_UNIX_TIME).get_unix_time() == A_UNIX_TIME

    def test_invalid_timestamps_are_ignored(self):
        assert _camm_point(time=0.0, epoch_time=0.0).get_unix_time() is None
        assert _gps_point(time=0.0, epoch_time=None).get_unix_time() is None
        assert _gps_point(time=0.0, epoch_time=0.0).get_unix_time() is None
        # A plain Point carries no absolute timestamp at all
        assert (
            geo.Point(time=1.0, lat=0, lon=0, alt=None, angle=None).get_unix_time()
            is None
        )


class TestGPXOffset:
    """A GPX recorded alongside the video must sync to ~0, not to ~10 years."""

    def test_camm_video_syncs_to_zero(self):
        gpx_points = [_camm_point(time=A_UNIX_TIME, epoch_time=A_UNIX_TIME)]
        video_points = [_camm_point(time=0.0, epoch_time=A_UNIX_TIME)]
        assert GPXVideoExtractor._gpx_offset(gpx_points, video_points) == 0.0

    def test_gopro_video_syncs_to_zero(self):
        gpx_points = [_camm_point(time=A_UNIX_TIME, epoch_time=A_UNIX_TIME)]
        video_points = [_gps_point(time=0.0, epoch_time=A_UNIX_TIME)]
        assert GPXVideoExtractor._gpx_offset(gpx_points, video_points) == 0.0

    def test_real_offset_is_preserved(self):
        gpx_points = [_camm_point(time=A_UNIX_TIME + 30, epoch_time=A_UNIX_TIME + 30)]
        video_points = [_camm_point(time=0.0, epoch_time=A_UNIX_TIME)]
        assert GPXVideoExtractor._gpx_offset(gpx_points, video_points) == 30.0

    def test_missing_video_timestamp_yields_no_offset(self):
        gpx_points = [_camm_point(time=A_UNIX_TIME, epoch_time=A_UNIX_TIME)]
        video_points = [_camm_point(time=0.0, epoch_time=0.0)]
        assert GPXVideoExtractor._gpx_offset(gpx_points, video_points) == 0.0


class TestEditListOverflow:
    """An oversized initial gap must not abort the upload."""

    def test_small_offset_stays_version_0(self):
        points = [geo.Point(time=1.5, lat=0, lon=0, alt=None, angle=None)]
        elst = camm_builder._create_edit_list_from_points([points], 1000, 1000)
        assert elst["data"]["version"] == 0
        assert elst["data"]["entries"][0]["segment_duration"] == 1500

    def test_oversized_offset_falls_back_to_version_1(self):
        # The exact shape of the reported crash: a whole GPS epoch of offset
        points = [geo.Point(time=GPS_UNIX_DELTA, lat=0, lon=0, alt=None, angle=None)]
        elst = camm_builder._create_edit_list_from_points([points], 1000, 1000)
        assert elst["data"]["version"] == 1
        assert elst["data"]["entries"][0]["segment_duration"] == GPS_UNIX_DELTA * 1000
        # Must serialize rather than raise construct.core.FormatFieldError
        assert cparser.EditBox.build(elst["data"])


class TestSourceOption:
    def test_explicit_source_path_is_not_dropped(self):
        opt = SourceOption.from_dict(
            {
                "source": "gpx",
                "pattern": "%g.gpx",
                "source_path": "/tmp/explicit.gpx",
            }
        )
        assert opt.source is SourceType.GPX
        assert opt.source_path is not None
        assert opt.source_path.source_path == Path("/tmp/explicit.gpx")
        # source_path wins over pattern when resolving
        assert opt.source_path.resolve(Path("/data/video.mp4")) == Path(
            "/tmp/explicit.gpx"
        )
