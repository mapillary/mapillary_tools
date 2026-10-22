# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
process warns of a GPX track that is assumed to start with a video, and runs on
for longer than the whole video, which sampling refuses: the video could start
anywhere along it.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

from mapillary_tools import types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import SourceOption, SourcePathOption, SourceType
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


def test_a_track_more_than_twice_as_long_as_the_video_warns(tmp_path, caplog):
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)

    with caplog.at_level(logging.WARNING):
        metadata = GPXVideoExtractor(NO_GPS_VIDEO, gpx).extract()

    [warning] = _warnings(caplog)
    assert "lasts 1.0 minutes and the video" in warning
    assert "could start anywhere along the track" in warning
    assert "video_process and --video_start_time" in warning
    # and the track is still assumed to start with the video
    assert metadata.points[0].time == 0


def test_a_track_up_to_twice_as_long_as_the_video_is_silent(tmp_path, caplog):
    # The video lasts 5.76 seconds
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=11)

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(NO_GPS_VIDEO, gpx).extract()

    assert not _warnings(caplog)


def test_the_gpx_source_of_process_warns(tmp_path, caplog):
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)

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
    assert "could start anywhere along the track" in warning


def test_a_track_said_to_start_with_the_video_is_silent(tmp_path, caplog):
    """--interpolation_use_gpx_start_time says that the two started together"""
    gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(NO_GPS_VIDEO, gpx, sync_mode=SyncMode.REBASE).extract()

    assert not _warnings(caplog)


def test_a_track_placed_by_the_gps_clock_is_silent(tmp_path, caplog):
    """The GPS clock of the video says where along the track it starts"""
    clock = GPXVideoExtractor._read_video_clock(
        NativeVideoExtractor(GPS_VIDEO).extract().points
    )
    assert clock is not None
    # From 30 seconds before the video to 90 seconds after it
    gpx = _write_gpx(
        tmp_path / "track.gpx", seconds=120, start=clock.to_unix_time(0) - 30
    )

    with caplog.at_level(logging.WARNING):
        GPXVideoExtractor(GPS_VIDEO, gpx).extract()

    assert not _warnings(caplog)
