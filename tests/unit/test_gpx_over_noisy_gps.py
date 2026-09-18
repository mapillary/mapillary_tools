# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Regression tests for geotagging a video whose own GPS is unusable.

A user-supplied GPX is the documented escape hatch for a video whose embedded
GPS is bad, so an unusable embedded track must never be what rejects the video.
The GPX replaces that track entirely; the video is then only a source of
make/model and of a clock to sync the GPX against.

Reported as "GPS is too noisy" persisting in the Desktop Uploader even after
attaching a valid GPX (a GoPro MAX2 .360 recorded with no GPS fix, where every
point is dropped by the noise filter).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapillary_tools import exceptions, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor, SyncMode
from mapillary_tools.geotag.video_extractors.native import NativeVideoExtractor
from mapillary_tools.gpmf import gpmf_gps_filter, gpmf_parser
from mapillary_tools.telemetry import GPSFix, GPSPoint


# Shape of the reported capture: no GPS fix and a DoP two orders of magnitude
# over the limit, so remove_noisy_points() drops every point
A_UNIX_TIME = 1789141181.0

GPX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="test">
  <trk><trkseg>
    <trkpt lat="48.1731513" lon="11.5973752">
      <ele>506.6</ele><time>2026-09-11T15:39:43Z</time>
    </trkpt>
    <trkpt lat="48.1731692" lon="11.5973021">
      <ele>506.8</ele><time>2026-09-11T15:39:45Z</time>
    </trkpt>
  </trkseg></trk>
</gpx>
"""


def _noisy_point(time: float, epoch_time: float) -> GPSPoint:
    return GPSPoint(
        time=time,
        lat=48.1737635,
        lon=11.5972871,
        alt=559.275,
        angle=None,
        epoch_time=epoch_time,
        fix=GPSFix.NO_FIX,
        precision=2139.0,
        ground_speed=0.749,
    )


@pytest.fixture
def video_path(tmp_path: Path) -> Path:
    # Contents are irrelevant: the GPMF parser is stubbed out below. The file
    # only has to exist so the extractor can open it and stat its size.
    path = tmp_path / "GS018205.360"
    path.write_bytes(b"not a real mp4")
    return path


@pytest.fixture
def gpx_path(tmp_path: Path) -> Path:
    path = tmp_path / "GS018205.360.gpx"
    path.write_text(GPX_XML)
    return path


@pytest.fixture
def noisy_gopro(monkeypatch: pytest.MonkeyPatch):
    """Make every GoPro read return a track the noise filter rejects wholesale."""
    points = [
        _noisy_point(time=i * 0.04, epoch_time=A_UNIX_TIME + i * 0.1) for i in range(32)
    ]
    assert not gpmf_gps_filter.remove_noisy_points(points), (
        "fixture must be noisy enough for the filter to drop every point"
    )

    info = gpmf_parser.GoProInfo(gps=points, make="GoPro", model="MAX2")
    monkeypatch.setattr(gpmf_parser, "extract_gopro_info", lambda *a, **kw: info)
    return info


class TestNoiseGateStillApplies:
    """Nothing below may weaken the gate on tracks we actually publish."""

    def test_native_extraction_still_rejects_noise(self, video_path, noisy_gopro):
        with pytest.raises(exceptions.MapillaryGPSNoiseError):
            NativeVideoExtractor(video_path).extract()

    def test_noise_filter_is_opt_out_only(self, video_path, noisy_gopro):
        metadata = NativeVideoExtractor(video_path, filter_noisy_points=False).extract()
        assert len(metadata.points) == 32


class TestGPXOverridesNoisyGPS:
    def test_gpx_is_used_instead_of_failing(self, video_path, gpx_path, noisy_gopro):
        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert [(p.lat, p.lon) for p in metadata.points] == [
            (48.1731513, 11.5973752),
            (48.1731692, 11.5973021),
        ]

    def test_camera_identity_survives(self, video_path, gpx_path, noisy_gopro):
        """Falling back to a bare VIDEO would drop make/model from the upload."""
        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert metadata.filetype is types.FileType.GOPRO
        assert (metadata.make, metadata.model) == ("GoPro", "MAX2")

    def test_noisy_points_still_provide_the_sync_clock(
        self, video_path, gpx_path, noisy_gopro
    ):
        """
        The GPX starts 2s after the video's first GPS sample, so it must land at
        t=2.0 rather than being rebased to t=0.
        """
        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert metadata.points[0].time == pytest.approx(2.0)
        assert metadata.points[1].time == pytest.approx(4.0)


class TestEmptyGPSFallsBack:
    """Same escape hatch, but with no timestamps to sync against."""

    @pytest.fixture
    def empty_gopro(self, monkeypatch: pytest.MonkeyPatch):
        info = gpmf_parser.GoProInfo(gps=[], make="GoPro", model="MAX2")
        monkeypatch.setattr(gpmf_parser, "extract_gopro_info", lambda *a, **kw: info)
        return info

    def test_gpx_is_rebased_from_zero(self, video_path, gpx_path, empty_gopro):
        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert [p.time for p in metadata.points] == [0.0, 2.0]

    def test_strict_sync_still_refuses(self, video_path, gpx_path, empty_gopro):
        extractor = GPXVideoExtractor(
            video_path, gpx_path, sync_mode=SyncMode.STRICT_SYNC
        )
        with pytest.raises(exceptions.MapillaryGPXEmptyError):
            extractor.extract()


class TestChainedSourcesFallThrough:
    """'--geotag_source native --geotag_source gpx' must reach the gpx stage."""

    @pytest.mark.parametrize(
        "error",
        [
            exceptions.MapillaryGPSNoiseError("GPS is too noisy"),
            exceptions.MapillaryGPXEmptyError("Empty GPS data found"),
            exceptions.MapillaryVideoGPSNotFoundError("No GPS data found"),
        ],
    )
    def test_unusable_gps_is_reprocessable(self, error):
        metadata = types.describe_error_metadata(
            error, filename=Path("/tmp/x.360"), filetype=types.FileType.VIDEO
        )
        assert factory._is_reprocessable(metadata)

    def test_unrelated_errors_are_not_reprocessable(self):
        metadata = types.describe_error_metadata(
            exceptions.MapillaryStationaryVideoError("Stationary"),
            filename=Path("/tmp/x.360"),
            filetype=types.FileType.VIDEO,
        )
        assert not factory._is_reprocessable(metadata)
