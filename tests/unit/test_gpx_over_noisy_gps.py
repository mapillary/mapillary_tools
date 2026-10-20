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

import typing as T
from pathlib import Path

import pytest

from mapillary_tools import exceptions, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import SourceOption, SourceType
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor, SyncMode
from mapillary_tools.geotag.video_extractors.native import NativeVideoExtractor
from mapillary_tools.gpmf import gpmf_gps_filter, gpmf_parser
from mapillary_tools.process_geotag_properties import DEFAULT_GEOTAG_SOURCE_OPTIONS
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

    def test_noise_filter_is_opt_out_only(self, video_path, noisy_gopro):
        metadata = NativeVideoExtractor(video_path, filter_noisy_points=False).extract()
        assert len(metadata.points) == 32


class TestGPXOverridesNoisyGPS:
    def test_gpx_is_used_instead_of_failing(self, video_path, gpx_path, noisy_gopro):
        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert [(p.lat, p.lon) for p in metadata.points] == [
            (48.170, 11.590),
            (48.171, 11.591),
        ]

    def test_camera_identity_survives(self, video_path, gpx_path, noisy_gopro):
        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert metadata.filetype is types.FileType.GOPRO
        assert (metadata.make, metadata.model) == ("GoPro", "MAX2")

    def test_noisy_points_still_provide_the_sync_clock(
        self, video_path, gpx_path, noisy_gopro
    ):
        """
        The GPX starts 2s after the video's first GPS sample, so it must land at
        t=2.0 rather than being synced from the start of the video.
        """
        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert [p.time for p in metadata.points] == pytest.approx([2.0, 4.0])

    def test_good_fixes_are_preferred_as_the_clock(
        self, monkeypatch, video_path, gpx_path
    ):
        """The unfiltered clock is only a fallback for GPS rejected as noise."""
        # The points without a fix read 1s late, and start the video
        points = [_point(time=i, epoch_time=A_UNIX_TIME + i + 1) for i in range(3)]
        points += [
            _point(time=i, epoch_time=A_UNIX_TIME + i, fix=GPSFix.FIX_3D, precision=150)
            for i in range(3, 8)
        ]
        _stub_gopro(monkeypatch, points)

        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert [p.time for p in metadata.points] == pytest.approx([2.0, 4.0])

    def test_noisy_clock_days_away_is_ignored(self, monkeypatch, video_path, gpx_path):
        """
        Until it acquires GPS time, a GoPro stamps a placeholder date, which a
        GPS rejected as noise may never have got past. Syncing by it would put
        the GPX years away from the video.
        """
        # 2015-10-22T09:53:44Z
        placeholder = 1445507624.0
        points = [
            _point(time=i * 0.1, epoch_time=placeholder + i * 0.1) for i in range(32)
        ]
        _stub_gopro(monkeypatch, points)

        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert [p.time for p in metadata.points] == [0.0, 2.0]
        assert (metadata.make, metadata.model) == ("GoPro", "MAX2")

    def test_good_clock_days_away_is_still_used(
        self, monkeypatch, video_path, gpx_path
    ):
        """Only a clock rejected with its noisy track is second-guessed."""
        day = 24 * 3600.0
        points = [
            _point(
                time=i,
                epoch_time=A_UNIX_TIME - 2 * day + i,
                fix=GPSFix.FIX_3D,
                precision=150,
            )
            for i in range(10)
        ]
        _stub_gopro(monkeypatch, points)

        metadata = GPXVideoExtractor(video_path, gpx_path).extract()

        assert metadata.points[0].time == pytest.approx(2 * day + 2.0)


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


def _run_chain(
    monkeypatch: pytest.MonkeyPatch,
    sources: T.Sequence[SourceType],
    outcomes: dict[SourceType, Exception | None],
) -> tuple[list[types.MetadataOrError], list[SourceType]]:
    """
    Run factory.process() on one video, with every source that geotags videos
    replaced by a stub reporting outcomes[source]: an error, or None for
    success. Returns the results and the sources that were asked to geotag it.
    """
    called: list[SourceType] = []

    class StubGeotag:
        def __init__(self, source: SourceType):
            self.source = source

        def to_description(self, paths):
            called.append(self.source)
            outcome = outcomes[self.source]
            if outcome is None:
                return [
                    types.VideoMetadata(
                        filename=path,
                        filetype=types.FileType.VIDEO,
                        points=[],
                        make=self.source.value,
                    )
                    for path in paths
                ]
            return [
                types.describe_error_metadata(
                    outcome, filename=path, filetype=types.FileType.VIDEO
                )
                for path in paths
            ]

    def build_video_geotag(option: SourceOption):
        # As the real builder: these sources do not geotag videos
        if option.source in [SourceType.NMEA, SourceType.EXIF]:
            return None
        return StubGeotag(option.source)

    monkeypatch.setattr(factory, "_build_video_geotag", build_video_geotag)
    results = factory.process(
        [Path("/tmp/GS018205.360")], [SourceOption(source) for source in sources]
    )
    return results, called


NOISE = exceptions.MapillaryGPSNoiseError("GPS is too noisy")
EMPTY = exceptions.MapillaryGPXEmptyError("Empty GPS data found")
NOT_FOUND = exceptions.MapillaryVideoGPSNotFoundError("No GPS data found")
GPX_NOT_FOUND = exceptions.MapillaryVideoGPSNotFoundError(
    "GPX file not found for video"
)

DEFAULT_CHAIN = [SourceType(source) for source in DEFAULT_GEOTAG_SOURCE_OPTIONS]


def _only_result(results: list[types.MetadataOrError]) -> types.MetadataOrError:
    assert len(results) == 1, results
    return results[0]


class TestChainedSources:
    """How a video moves through a chain of geotag sources."""

    @pytest.mark.parametrize("rejection", [NOISE, EMPTY])
    def test_gpx_rescues_rejected_gps(self, monkeypatch, rejection):
        results, _ = _run_chain(
            monkeypatch,
            [SourceType.NATIVE, SourceType.GPX],
            {SourceType.NATIVE: rejection, SourceType.GPX: None},
        )
        result = _only_result(results)
        assert isinstance(result, types.VideoMetadata)
        assert result.make == "gpx"

    @pytest.mark.parametrize("rejection", [NOISE, EMPTY])
    def test_default_chain_keeps_the_verdict(self, monkeypatch, rejection):
        """
        exiftool must not get a second opinion on the track that native just
        rejected. The exact chain `process` runs with no flags.
        """
        assert DEFAULT_CHAIN == [SourceType.NATIVE, SourceType.EXIFTOOL_RUNTIME]
        results, called = _run_chain(
            monkeypatch,
            DEFAULT_CHAIN,
            {SourceType.NATIVE: rejection, SourceType.EXIFTOOL_RUNTIME: None},
        )
        result = _only_result(results)
        assert isinstance(result, types.ErrorMetadata)
        assert result.error is rejection
        assert called == [SourceType.NATIVE]

    @pytest.mark.parametrize("rejection", [NOISE, EMPTY])
    def test_embedded_reader_cannot_win_before_gpx(self, monkeypatch, rejection):
        """
        A GPX later in the chain must not let exiftool in first: it could
        publish the embedded track instead of the GPX.
        """
        results, called = _run_chain(
            monkeypatch,
            [SourceType.NATIVE, SourceType.EXIFTOOL_RUNTIME, SourceType.GPX],
            {
                SourceType.NATIVE: rejection,
                SourceType.EXIFTOOL_RUNTIME: None,
                SourceType.GPX: None,
            },
        )
        result = _only_result(results)
        assert isinstance(result, types.VideoMetadata)
        assert result.make == "gpx"
        assert called == [SourceType.NATIVE, SourceType.GPX]

    @pytest.mark.parametrize(
        "sources",
        [
            [SourceType.NATIVE, SourceType.NMEA],
            [SourceType.NATIVE, SourceType.NMEA, SourceType.EXIFTOOL_RUNTIME],
        ],
    )
    def test_source_that_skips_videos_does_not_drop_them(self, monkeypatch, sources):
        """NMEA cannot geotag videos: the video must keep its error, not vanish."""
        results, _ = _run_chain(
            monkeypatch,
            sources,
            {SourceType.NATIVE: NOISE, SourceType.EXIFTOOL_RUNTIME: None},
        )
        result = _only_result(results)
        assert isinstance(result, types.ErrorMetadata)
        assert result.error is NOISE

    def test_not_found_is_not_dropped_by_image_only_source(self, monkeypatch):
        results, _ = _run_chain(
            monkeypatch,
            [SourceType.NATIVE, SourceType.EXIF],
            {SourceType.NATIVE: NOT_FOUND},
        )
        result = _only_result(results)
        assert isinstance(result, types.ErrorMetadata)
        assert result.error is NOT_FOUND

    def test_missing_gpx_does_not_hide_why_gps_was_rejected(self, monkeypatch):
        results, _ = _run_chain(
            monkeypatch,
            [SourceType.NATIVE, SourceType.GPX],
            {SourceType.NATIVE: NOISE, SourceType.GPX: GPX_NOT_FOUND},
        )
        result = _only_result(results)
        assert isinstance(result, types.ErrorMetadata)
        assert result.error is NOISE

    def test_gpx_that_fails_replaces_the_rejection(self, monkeypatch):
        """Only a fallback that finds nothing is outranked by the rejection."""
        mismatch = exceptions.MapillaryGeoTaggingError("GPX does not match")
        results, _ = _run_chain(
            monkeypatch,
            [SourceType.NATIVE, SourceType.GPX],
            {SourceType.NATIVE: NOISE, SourceType.GPX: mismatch},
        )
        result = _only_result(results)
        assert isinstance(result, types.ErrorMetadata)
        assert result.error is mismatch

    def test_not_found_still_falls_through_to_exiftool(self, monkeypatch):
        """Finding nothing is a verdict on the reader, so retrying is fair."""
        results, called = _run_chain(
            monkeypatch,
            DEFAULT_CHAIN,
            {SourceType.NATIVE: NOT_FOUND, SourceType.EXIFTOOL_RUNTIME: None},
        )
        result = _only_result(results)
        assert isinstance(result, types.VideoMetadata)
        assert called == DEFAULT_CHAIN

    def test_last_error_is_reported(self, monkeypatch):
        exiftool_missing = exceptions.MapillaryExiftoolNotFoundError("no exiftool")
        results, _ = _run_chain(
            monkeypatch,
            DEFAULT_CHAIN,
            {
                SourceType.NATIVE: NOT_FOUND,
                SourceType.EXIFTOOL_RUNTIME: exiftool_missing,
            },
        )
        result = _only_result(results)
        assert isinstance(result, types.ErrorMetadata)
        assert result.error is exiftool_missing

    def test_unrelated_errors_are_final(self, monkeypatch):
        stationary = exceptions.MapillaryStationaryVideoError("Stationary")
        results, called = _run_chain(
            monkeypatch,
            [SourceType.NATIVE, SourceType.GPX],
            {SourceType.NATIVE: stationary, SourceType.GPX: None},
        )
        result = _only_result(results)
        assert isinstance(result, types.ErrorMetadata)
        assert result.error is stationary
        assert called == [SourceType.NATIVE]
