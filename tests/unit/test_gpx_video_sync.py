# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
How GPXVideoExtractor lines up a GPX track with the video it geotags, when
distance sampling hands it a VideoSyncOption, and that process, which does
not, places a GPX as it always has.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

import pytest
from mapillary_tools import exceptions, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import (
    SourceOption,
    SourcePathOption,
    SourceType,
    VideoSyncOption,
)
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor

_DATA = Path(__file__).resolve().parent.parent.joinpath("data")

# No GPS of its own, and 5.76 seconds long
NO_GPS_VIDEO = _DATA.joinpath("videos", "sample-5s.mp4")
# GPS of its own, recorded from 2019-11-18T15:44:47Z
GPS_VIDEO = _DATA.joinpath("gopro_data", "max-360mode.mp4")

GPX_START = datetime.datetime(2025, 3, 14, 7, 0, 0, tzinfo=datetime.timezone.utc)


def _write_gpx(path: Path, seconds: int, start=GPX_START) -> Path:
    """A GPX track with a point every second, heading north at 10 m/s."""
    points = []
    for i in range(seconds + 1):
        time = (start + datetime.timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lat = 37.0 + i * 10 / 111_320
        points.append(
            f'<trkpt lat="{lat:.7f}" lon="-122.0"><ele>10</ele><time>{time}</time></trkpt>'
        )
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{''.join(points)}</trkseg></trk></gpx>\n"
    )
    return path


def _extract(video: Path, gpx: Path, video_sync: VideoSyncOption | None):
    return GPXVideoExtractor(video, gpx, video_sync=video_sync).extract()


class TestVideoWithoutGPS:
    def test_the_track_is_placed_by_the_video_start_time(self, tmp_path):
        """
        Not by assuming the track starts with the video: a GPX of a whole drive
        then put every clip on its first few minutes.
        """
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)
        video_start = GPX_START + datetime.timedelta(seconds=30)

        metadata = _extract(
            NO_GPS_VIDEO, gpx, VideoSyncOption(start_time=video_start.timestamp())
        )

        assert metadata.points[0].time == pytest.approx(-30)
        assert metadata.points[30].time == pytest.approx(0)
        # the absolute times, which the frames are stamped with, are untouched
        assert metadata.points[30].get_unix_time() == pytest.approx(
            video_start.timestamp()
        )

    def test_a_track_far_longer_than_the_video_is_refused(self, tmp_path):
        """The video could start anywhere along a track a minute long."""
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)

        with pytest.raises(exceptions.MapillaryGPXVideoStartUnknownError) as excinfo:
            _extract(NO_GPS_VIDEO, gpx, VideoSyncOption())

        assert "--video_start_time" in str(excinfo.value)

    def test_a_track_a_little_longer_than_the_video_warns(self, tmp_path, caplog):
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=9)

        with caplog.at_level(logging.WARNING):
            metadata = _extract(NO_GPS_VIDEO, gpx, VideoSyncOption())

        assert metadata.points[0].time == 0
        assert "--video_start_time" in caplog.text

    def test_a_track_as_long_as_the_video_starts_with_it_silently(
        self, tmp_path, caplog
    ):
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=6)

        with caplog.at_level(logging.WARNING):
            metadata = _extract(NO_GPS_VIDEO, gpx, VideoSyncOption())

        assert metadata.points[0].time == 0
        assert not caplog.text

    def test_process_still_assumes_the_track_starts_with_the_video(self, tmp_path):
        """process has no --video_start_time to offer as a way out."""
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=3600)

        metadata = _extract(NO_GPS_VIDEO, gpx, video_sync=None)

        assert metadata.points[0].time == 0

    def test_the_refusal_is_not_handed_on_to_the_next_source(self, tmp_path):
        """
        The video has no GPS, so a native source after the GPX can only fail,
        and its error would hide why the GPX was refused.
        """
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)
        video_sync = VideoSyncOption()

        [metadata] = factory.process(
            [NO_GPS_VIDEO],
            [
                SourceOption(
                    SourceType.GPX,
                    source_path=SourcePathOption(source_path=gpx),
                    video_sync=video_sync,
                ),
                SourceOption(SourceType.NATIVE, video_sync=video_sync),
            ],
        )

        assert isinstance(metadata, types.ErrorMetadata)
        assert isinstance(metadata.error, exceptions.MapillaryGPXVideoStartUnknownError)


class TestVideoWithGPS:
    def test_the_video_gps_wins_over_the_start_time(self, tmp_path):
        """
        Its own GPS clock syncs the track, as before; --video_start_time only
        places a GPX on a video that has nothing to sync it with.
        """
        gpx = _write_gpx(
            tmp_path / "track.gpx",
            seconds=30,
            start=datetime.datetime(
                2019, 11, 18, 15, 44, 40, tzinfo=datetime.timezone.utc
            ),
        )
        far_off = GPX_START.timestamp()

        synced = _extract(GPS_VIDEO, gpx, video_sync=None)
        with_start_time = _extract(GPS_VIDEO, gpx, VideoSyncOption(start_time=far_off))

        assert [p.time for p in with_start_time.points] == [
            p.time for p in synced.points
        ]


class TestInterpolationOptions:
    """
    The geotagging stage of video_process applies --interpolation_offset_time
    and --interpolation_use_gpx_start_time to the frames, so sampling applies
    them too, or it picks frames by positions the frames do not end up at.
    """

    def test_the_offset_shifts_the_track_and_its_times(self, tmp_path):
        """
        The frame at video time t is at track time start + t + offset, and is
        stamped start + t, which the geotagging stage adds the offset to.
        """
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)
        video_start = GPX_START + datetime.timedelta(seconds=30)

        metadata = _extract(
            NO_GPS_VIDEO,
            gpx,
            VideoSyncOption(start_time=video_start.timestamp(), offset_time=2),
        )

        # the point recorded at start + 2 is where the first frame is
        assert metadata.points[32].time == pytest.approx(0)
        assert metadata.points[32].get_unix_time() == pytest.approx(
            video_start.timestamp()
        )

    def test_the_offset_applies_to_a_track_synced_by_the_video_gps(self, tmp_path):
        gpx = _write_gpx(
            tmp_path / "track.gpx",
            seconds=30,
            start=datetime.datetime(
                2019, 11, 18, 15, 44, 40, tzinfo=datetime.timezone.utc
            ),
        )

        synced = _extract(GPS_VIDEO, gpx, VideoSyncOption())
        shifted = _extract(GPS_VIDEO, gpx, VideoSyncOption(offset_time=2))

        assert [p.time for p in shifted.points] == pytest.approx(
            [p.time - 2 for p in synced.points]
        )

    def test_use_gpx_start_time_starts_the_track_with_the_video(self, tmp_path):
        """
        Whatever the start time says, and however long the track: the user
        has said that the two started together.
        """
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)

        metadata = _extract(
            NO_GPS_VIDEO,
            gpx,
            VideoSyncOption(
                start_time=(GPX_START + datetime.timedelta(seconds=30)).timestamp(),
                use_gpx_start_time=True,
            ),
        )

        assert metadata.points[0].time == 0

    def test_process_applies_neither(self, tmp_path):
        """process passes no VideoSyncOption, and ignores both for videos."""
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=6)

        metadata = _extract(NO_GPS_VIDEO, gpx, video_sync=None)

        assert metadata.points[0].time == 0
        assert metadata.points[0].get_unix_time() == GPX_START.timestamp()
