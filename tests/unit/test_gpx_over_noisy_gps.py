# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Regression tests for geotagging a video whose own GPS is unusable.

A user-supplied GPX is the documented escape hatch for a video whose embedded
GPS is bad, so an unusable embedded track must never be what rejects the video.

Reported as "GPS is too noisy" persisting in the Desktop Uploader even after
attaching a valid GPX: a GoPro MAX2 .360 timelapse whose GPS reported a
dilution of precision over twice the limit, so the noise filter kept none of
its points.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapillary_tools import exceptions, types
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor, SyncMode
from mapillary_tools.geotag.video_extractors.native import NativeVideoExtractor
from mapillary_tools.gpmf import gpmf_gps_filter, gpmf_parser
from mapillary_tools.telemetry import GPSFix, GPSPoint


# 2026-09-11T15:39:41Z
A_UNIX_TIME = 1789141181.0


def _gpx_xml(*times: str) -> str:
    points = "\n".join(
        f'<trkpt lat="48.17{i}" lon="11.59{i}"><ele>506</ele><time>{t}</time></trkpt>'
        for i, t in enumerate(times)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="test">
  <trk><trkseg>
{points}
  </trkseg></trk>
</gpx>
"""


def _point(
    time: float, epoch_time: float, fix: GPSFix = GPSFix.NO_FIX, precision=2139.0
) -> GPSPoint:
    # The defaults make remove_noisy_points() drop the point. 2139 is the
    # highest DoP (x100) in the reported capture, against a limit of 1000
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


@pytest.fixture
def video_path(tmp_path: Path) -> Path:
    # Contents are irrelevant: the GPMF parser is stubbed out below. The file
    # only has to exist so the extractor can open it and stat its size.
    path = tmp_path / "GS018205.360"
    path.write_bytes(b"not a real mp4")
    return path


@pytest.fixture
def gpx_path(tmp_path: Path) -> Path:
    # 2s and 4s after the video's first GPS sample
    path = tmp_path / "GS018205.360.gpx"
    path.write_text(_gpx_xml("2026-09-11T15:39:43Z", "2026-09-11T15:39:45Z"))
    return path


def _stub_gopro(monkeypatch: pytest.MonkeyPatch, points: list[GPSPoint]):
    info = gpmf_parser.GoProInfo(gps=points, make="GoPro", model="MAX2")
    monkeypatch.setattr(gpmf_parser, "extract_gopro_info", lambda *a, **kw: info)
    return info


@pytest.fixture
def noisy_gopro(monkeypatch: pytest.MonkeyPatch):
    """Make every GoPro read return a track the noise filter rejects wholesale."""
    points = [_point(time=i * 0.1, epoch_time=A_UNIX_TIME + i * 0.1) for i in range(32)]
    assert not gpmf_gps_filter.remove_noisy_points(points), (
        "fixture must be noisy enough for the filter to drop every point"
    )
    return _stub_gopro(monkeypatch, points)


class TestNoiseGateStillApplies:
    """Nothing below may weaken the gate on tracks we actually publish."""

    def test_native_extraction_still_rejects_noise(self, video_path, noisy_gopro):
        with pytest.raises(exceptions.MapillaryGPSNoiseError):
            NativeVideoExtractor(video_path).extract()


class TestGPXOverridesNoisyGPS:
    def test_gpx_is_used_instead_of_failing(self, video_path, gpx_path, noisy_gopro):
        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert [(p.lat, p.lon) for p in metadata.points] == [
            (48.170, 11.590),
            (48.171, 11.591),
        ]


class TestEmptyGPSFallsBack:
    """Same escape hatch, but with no timestamps to sync against."""

    @pytest.fixture
    def empty_gopro(self, monkeypatch: pytest.MonkeyPatch):
        return _stub_gopro(monkeypatch, [])

    def test_gpx_is_rebased_from_zero(self, video_path, gpx_path, empty_gopro):
        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert [p.time for p in metadata.points] == [0.0, 2.0]
        assert metadata.filetype is types.FileType.VIDEO

    def test_strict_sync_still_refuses(self, video_path, gpx_path, empty_gopro):
        extractor = GPXVideoExtractor(
            video_path, gpx_path, sync_mode=SyncMode.STRICT_SYNC
        )
        with pytest.raises(exceptions.MapillaryGPXEmptyError):
            extractor.extract()


class TestUnusableGPSErrors:
    UNUSABLE = [
        exceptions.MapillaryVideoGPSNotFoundError,
        exceptions.MapillaryGPXEmptyError,
        exceptions.MapillaryGPSNoiseError,
    ]

    @pytest.mark.parametrize("error_class", UNUSABLE)
    def test_share_one_base_class(self, error_class):
        assert issubclass(error_class, exceptions.MapillaryVideoGPSUnusableError)

    @pytest.mark.parametrize("error_class", UNUSABLE)
    def test_still_description_errors(self, error_class):
        """Whatever catches them today keeps catching them."""
        assert issubclass(error_class, exceptions.MapillaryDescriptionError)
