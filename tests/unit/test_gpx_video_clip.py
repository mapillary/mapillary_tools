# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
A GPX track whose pace along a video a clock gives is clipped to the video,
with a point interpolated at either end, when it geotags the video. One that
is only assumed to start with a video without a GPS clock is not.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from mapillary_tools import types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import (
    SourceOption,
    SourcePathOption,
    SourceType,
    VideoSyncOption,
)
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor, SyncMode
from mapillary_tools.geotag.video_extractors.native import NativeVideoExtractor

_DATA = Path(__file__).resolve().parent.parent.joinpath("data")

# No GPS of its own, and 5.76 seconds long
NO_GPS_VIDEO = _DATA.joinpath("videos", "sample-5s.mp4")
NO_GPS_VIDEO_DURATION = 5.759

# GPS of its own, and 12.137125 seconds long
GPS_VIDEO = _DATA.joinpath("gopro_data", "max-360mode.mp4")
GPS_VIDEO_DURATION = 12.137125


def _gps_video_start() -> float:
    """The Unix time of the first frame of GPS_VIDEO, by its GPS clock"""
    points = NativeVideoExtractor(GPS_VIDEO).extract().points
    clock = GPXVideoExtractor._read_video_clock(points)
    assert clock is not None
    return clock.to_unix_time(0)


def _write_gpx(path: Path, start: float, seconds: int) -> Path:
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


def _times(metadata: types.VideoMetadata) -> list[float]:
    return [p.time for p in metadata.points]


class TestClockPlacedTrack:
    def _gpx(self, tmp_path: Path) -> Path:
        # From 12.5 seconds before the video to about 47 seconds after it
        return _write_gpx(tmp_path / "track.gpx", _gps_video_start() - 12.5, 60)

    def test_is_clipped_to_the_video(self, tmp_path):
        metadata = GPXVideoExtractor(
            GPS_VIDEO, self._gpx(tmp_path), clip_to_video=True
        ).extract()

        times = _times(metadata)
        assert times[0] == 0
        assert times[-1] == pytest.approx(GPS_VIDEO_DURATION)
        # The GPX points recorded during the video, from 0.5 to 11.5 seconds
        assert len(times) == 2 + 12
        assert all(0 <= t <= GPS_VIDEO_DURATION for t in times)

    def test_the_ends_are_interpolated(self, tmp_path):
        metadata = GPXVideoExtractor(
            GPS_VIDEO, self._gpx(tmp_path), clip_to_video=True
        ).extract()

        first, last = metadata.points[0], metadata.points[-1]
        assert first.get_unix_time() == pytest.approx(_gps_video_start())
        assert first.lat == pytest.approx(37.0 + 12.5 * 10 / 111_320, abs=1e-7)
        assert last.get_unix_time() == pytest.approx(
            _gps_video_start() + GPS_VIDEO_DURATION
        )

    def test_by_the_start_time_is_clipped_to_the_video(self, tmp_path):
        start = datetime.datetime(2025, 3, 14, 7, 0, 0, tzinfo=datetime.timezone.utc)
        gpx = _write_gpx(tmp_path / "track.gpx", start.timestamp(), 60)

        metadata = GPXVideoExtractor(
            NO_GPS_VIDEO,
            gpx,
            video_sync=VideoSyncOption(start_time=start.timestamp() + 30),
            clip_to_video=True,
        ).extract()

        times = _times(metadata)
        assert times[0] == 0
        assert times[-1] == pytest.approx(NO_GPS_VIDEO_DURATION, abs=1e-3)

    def test_started_with_the_video_is_clipped(self, tmp_path):
        """
        --interpolation_use_gpx_start_time places the track, and the GPS clock
        gives its pace
        """
        metadata = GPXVideoExtractor(
            GPS_VIDEO,
            self._gpx(tmp_path),
            sync_mode=SyncMode.REBASE,
            clip_to_video=True,
        ).extract()

        times = _times(metadata)
        assert times[:-1] == [float(t) for t in range(13)]
        assert times[-1] == pytest.approx(GPS_VIDEO_DURATION)

    def test_the_gpx_source_clips_it(self, tmp_path):
        [metadata] = factory.process(
            [GPS_VIDEO],
            [
                SourceOption(
                    SourceType.GPX,
                    num_processes=0,
                    source_path=SourcePathOption(source_path=self._gpx(tmp_path)),
                )
            ],
        )

        assert isinstance(metadata, types.VideoMetadata)
        assert _times(metadata)[0] == 0
        assert _times(metadata)[-1] == pytest.approx(GPS_VIDEO_DURATION)


class TestTrackAssumedToStartWithTheVideo:
    """
    Without a clock to say where the video ends along the track, a track that
    runs on past it may be that of a timelapse, at the pace of the GPS clock
    """

    def test_without_gps_is_not_clipped(self, tmp_path):
        start = datetime.datetime(2025, 3, 14, 7, 0, 0, tzinfo=datetime.timezone.utc)
        gpx = _write_gpx(tmp_path / "track.gpx", start.timestamp(), 60)

        metadata = GPXVideoExtractor(NO_GPS_VIDEO, gpx, clip_to_video=True).extract()

        assert _times(metadata) == [float(t) for t in range(61)]
