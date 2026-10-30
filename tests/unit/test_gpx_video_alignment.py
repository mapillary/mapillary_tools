# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
A GPX track placed on a video without a GPS clock is assumed to start with the
video, and taken to be right. When the two lengths differ by more than a
minute (and a longer track also lasts more than 1.5 times as long), the video
start time needs aligning with the track, which process and sampling warn of.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

import pytest
from mapillary_tools import exceptions, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import (
    InterpolationOption,
    SourceOption,
    SourcePathOption,
    SourceType,
    VideoSyncOption,
)
from mapillary_tools.geotag.video_extractors import gpx as gpx_module
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor, SyncMode
from mapillary_tools.geotag.video_extractors.native import NativeVideoExtractor

_DATA = Path(__file__).resolve().parent.parent.joinpath("data")

# No GPS of its own, and 5.76 seconds long
NO_GPS_VIDEO = _DATA.joinpath("videos", "sample-5s.mp4")
# GPS of its own, and 12.14 seconds long
GPS_VIDEO = _DATA.joinpath("gopro_data", "max-360mode.mp4")

GPX_START = datetime.datetime(2025, 3, 14, 7, 0, 0, tzinfo=datetime.timezone.utc)


def _write_gpx(path: Path, seconds: int, start: float = GPX_START.timestamp()) -> Path:
    """A GPX track with a point every second from start, heading north at 10 m/s."""
    points = "".join(
        f'<trkpt lat="{37.0 + i * 10 / 111_320:.7f}" lon="-122.0"><time>'
        f"{datetime.datetime.fromtimestamp(start + i, datetime.timezone.utc).isoformat()}"
        "</time></trkpt>"
        for i in range(seconds + 1)
    )
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{points}</trkseg></trk></gpx>\n"
    )
    return path


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def _video_lasting(monkeypatch, seconds: float) -> None:
    """Make the video read as lasting **seconds**"""
    monkeypatch.setattr(gpx_module, "_video_duration", lambda video_path: seconds)


def test_a_track_more_than_a_minute_longer_warns_in_process(tmp_path, caplog):
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=120)
    extractor = GPXVideoExtractor(NO_GPS_VIDEO, gpx)

    with caplog.at_level(logging.WARNING):
        metadata = extractor.extract()

    [message] = _warnings(caplog)
    assert "lasts 2.0 minutes and the video" in message
    assert "so the track is assumed to start with the video" in message
    assert "Please align the video start time with the GPX track" in message
    assert "trim the GPX to the video, or sample the video with video_process" in (
        message
    )
    assert "If the video is a timelapse, its GPX track is expected to last longer" in (
        message
    )
    # and the track is still assumed to start with the video
    assert metadata.points[0].time == 0

    [warning] = extractor.warnings
    assert isinstance(warning, exceptions.MapillaryGPXAlignmentWarning)
    assert str(warning) == message
    # returned with the metadata, for the process report
    assert metadata.warnings == [warning]
    assert warning.video_duration == pytest.approx(5.76, abs=0.01)
    assert warning.gpx_duration == 120
    assert warning.gpx_start_time == "2025_03_14_07_00_00_000"
    assert warning.gpx_end_time == "2025_03_14_07_02_00_000"
    assert warning.gpx_longer


def test_sampling_warns_with_its_own_options(tmp_path, caplog):
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=120)

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(NO_GPS_VIDEO, gpx, video_sync=VideoSyncOption()).extract()

    [message] = _warnings(caplog)
    assert "specify the time the video started as --video_start_time" in message
    assert "If the video is a timelapse, specify --video_duration_ratio" in message


def test_a_track_up_to_a_minute_longer_is_silent(tmp_path, caplog):
    # The video lasts 5.76 seconds
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=65)
    extractor = GPXVideoExtractor(NO_GPS_VIDEO, gpx)

    with caplog.at_level(logging.WARNING):
        extractor.extract()

    assert not _warnings(caplog)
    assert not extractor.warnings


def test_a_track_more_than_a_minute_shorter_warns(tmp_path, caplog, monkeypatch):
    _video_lasting(monkeypatch, 600)
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=120)
    extractor = GPXVideoExtractor(NO_GPS_VIDEO, gpx)

    with caplog.at_level(logging.WARNING):
        extractor.extract()

    [message] = _warnings(caplog)
    assert "lasts 2.0 minutes and the video" in message
    assert "10.0 minutes" in message
    assert "Please align the video start time with the GPX track" in message
    # A shorter track is no timelapse's
    assert "timelapse" not in message
    [warning] = extractor.warnings
    assert not warning.gpx_longer


def test_a_track_up_to_a_minute_shorter_is_silent(tmp_path, caplog, monkeypatch):
    _video_lasting(monkeypatch, 600)
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=541)

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(NO_GPS_VIDEO, gpx).extract()

    assert not _warnings(caplog)


@pytest.mark.parametrize("seconds, warns", [(899, False), (901, True)])
def test_a_longer_track_warns_only_past_one_and_a_half_times_the_video(
    tmp_path, caplog, monkeypatch, seconds, warns
):
    """Longer by more than a minute either way, but only one is longer than 1.5x"""
    _video_lasting(monkeypatch, 600)
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=seconds)

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(NO_GPS_VIDEO, gpx).extract()

    assert bool(_warnings(caplog)) is warns


def test_the_duration_ratio_spans_the_video_in_sampling(tmp_path, caplog):
    """At 30 GPS seconds per second, the 5.76 seconds of video span 173 seconds"""
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=180)

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(
            NO_GPS_VIDEO, gpx, video_sync=VideoSyncOption(duration_ratio=30)
        ).extract()

    assert not _warnings(caplog)


def test_a_track_looked_up_at_an_offset_is_silent(tmp_path, caplog):
    """The offset places the video along the track: it is aligned"""
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=600)

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(
            NO_GPS_VIDEO, gpx, interpolation=InterpolationOption(offset_time=30)
        ).extract()

    assert not _warnings(caplog)


def test_the_gpx_source_of_process_warns(tmp_path, caplog):
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=120)

    with caplog.at_level(logging.WARNING):
        [metadata] = factory.process(
            [NO_GPS_VIDEO],
            [
                SourceOption(
                    SourceType.GPX,
                    num_processes=0,
                    source_path=SourcePathOption(source_path=gpx),
                )
            ],
        )

    assert isinstance(metadata, types.VideoMetadata)
    [warning] = _warnings(caplog)
    assert "Please align the video start time with the GPX track" in warning
    [returned] = metadata.warnings
    assert str(returned) == warning


def test_a_track_said_to_start_with_the_video_is_silent(tmp_path, caplog):
    """--interpolation_use_gpx_start_time says that the two started together"""
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=600)

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(NO_GPS_VIDEO, gpx, sync_mode=SyncMode.REBASE).extract()

    assert not _warnings(caplog)


def test_a_track_placed_by_the_gps_clock_is_silent(tmp_path, caplog):
    """The GPS clock of the video says where along the track it starts"""
    clock = GPXVideoExtractor._read_video_clock(
        NativeVideoExtractor(GPS_VIDEO).extract().points
    )
    assert clock is not None
    # From 5 minutes before the video to 10 minutes after it
    gpx = _write_gpx(
        tmp_path / "track.gpx", seconds=900, start=clock.to_unix_time(0) - 300
    )

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(GPS_VIDEO, gpx).extract()

    assert not _warnings(caplog)


def test_a_video_whose_gps_has_no_clock_returns_the_warning(
    tmp_path, caplog, monkeypatch
):
    """Its GPS has no clock to place the track by, as if it had no GPS"""
    monkeypatch.setattr(
        GPXVideoExtractor, "_read_video_clock", classmethod(lambda cls, points: None)
    )
    # The video lasts 12.14 seconds
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=120)
    extractor = GPXVideoExtractor(GPS_VIDEO, gpx)

    with caplog.at_level(logging.WARNING):
        metadata = extractor.extract()

    [message] = _warnings(caplog)
    assert "Please align the video start time with the GPX track" in message
    assert metadata.warnings == extractor.warnings
    assert len(metadata.warnings) == 1
