# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
How GPXVideoExtractor lines up a GPX track with the video it geotags, when
distance sampling hands it a VideoSyncOption, and when process, which does not,
geotags the video for upload.
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
from mapillary_tools.geotag.video_extractors.gpx import (
    GPXVideoExtractor,
    SyncMode,
    VideoClock,
)

_DATA = Path(__file__).resolve().parent.parent.joinpath("data")

# No GPS of its own, and 5.76 seconds long
NO_GPS_VIDEO = _DATA.joinpath("videos", "sample-5s.mp4")
# GPS of its own, recorded from 2019-11-18T23:44:42.59Z to 23:44:54.64Z
GPS_VIDEO = _DATA.joinpath("gopro_data", "max-360mode.mp4")
# Shortly before the GPS track of GPS_VIDEO starts
_GPS_VIDEO_START = datetime.datetime(
    2019, 11, 18, 23, 44, 40, tzinfo=datetime.timezone.utc
)

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


def _extract(
    video: Path,
    gpx: Path,
    video_sync: VideoSyncOption | None,
    interpolation: InterpolationOption | None = None,
):
    return GPXVideoExtractor(
        video, gpx, video_sync=video_sync, interpolation=interpolation
    ).extract()


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
        assert "--video_duration_ratio" in str(excinfo.value)

    def test_gpx_start_time_on_a_track_far_longer_than_the_video_is_refused(
        self, tmp_path
    ):
        """
        It was not recorded for the video alone, or the video is a timelapse,
        and nothing says how fast it runs through the track.
        """
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)

        with pytest.raises(exceptions.MapillaryGPXVideoStartUnknownError) as excinfo:
            GPXVideoExtractor(
                NO_GPS_VIDEO, gpx, SyncMode.REBASE, video_sync=VideoSyncOption()
            ).extract()

        message = str(excinfo.value)
        assert "--video_duration_ratio" in message
        # For a logger left running, ready to paste: the track starts at GPX_START
        assert (
            "started with the video and left running, specify --video_start_time "
            "2025_03_14_07_00_00_000, when the track starts"
        ) in message
        # Not for a track of more than this video, which the start of the track
        # would put on the wrong part of it
        assert "covers more than this video, specify the time the video started" in (
            message
        )

    def test_gpx_start_time_on_a_log_of_days_offers_no_start_time(self, tmp_path):
        """
        A track of several days is a log of several trips, and its start that
        of the first: placed there, the video would land on the wrong trip.
        """
        gpx = _write_gpx_tracks(
            tmp_path / "track.gpx",
            [
                ["2025-03-14T07:00:00Z", "2025-03-14T07:00:01Z"],
                ["2025-03-16T07:00:00Z", "2025-03-16T07:00:01Z"],
            ],
        )

        with pytest.raises(exceptions.MapillaryGPXVideoStartUnknownError) as excinfo:
            GPXVideoExtractor(
                NO_GPS_VIDEO, gpx, SyncMode.REBASE, video_sync=VideoSyncOption()
            ).extract()

        message = str(excinfo.value)
        assert "specify the time the video started as --video_start_time" in message
        assert "2025_03_14" not in message
        assert "left running" not in message
        assert "--video_duration_ratio" not in message

    def test_gpx_start_time_on_a_track_as_long_as_the_video_is_silent(
        self, tmp_path, caplog
    ):
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=6)

        with caplog.at_level(logging.WARNING):
            GPXVideoExtractor(
                NO_GPS_VIDEO, gpx, SyncMode.REBASE, video_sync=VideoSyncOption()
            ).extract()

        assert not caplog.text

    def test_the_duration_ratio_paces_a_track_placed_by_the_start_time(self, tmp_path):
        """
        One GPX can serve many videos, each placed by its start time, and a
        timelapse runs through it at its ratio.
        """
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=600)
        video_start = GPX_START + datetime.timedelta(seconds=300)

        metadata = _extract(
            NO_GPS_VIDEO,
            gpx,
            VideoSyncOption(start_time=video_start.timestamp(), duration_ratio=10),
        )

        assert metadata.points[300].time == pytest.approx(0)
        assert metadata.points[310].time == pytest.approx(1)
        # the absolute times, which the frames are stamped with, are untouched
        assert metadata.points[310].get_unix_time() == pytest.approx(
            video_start.timestamp() + 10
        )

    @pytest.mark.parametrize("sync_mode", [SyncMode.SYNC, SyncMode.REBASE])
    def test_the_duration_ratio_spreads_a_track_over_the_video(
        self, tmp_path, caplog, sync_mode
    ):
        """
        The 5.76s video spans 57.6s of GPS time at 10 seconds per second, so a
        track of 57s starts and ends with it.
        """
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=57)

        with caplog.at_level(logging.WARNING):
            metadata = GPXVideoExtractor(
                NO_GPS_VIDEO,
                gpx,
                sync_mode,
                video_sync=VideoSyncOption(duration_ratio=10),
            ).extract()

        assert metadata.points[0].time == 0
        assert metadata.points[-1].time == pytest.approx(5.7)
        assert not caplog.text

    def test_a_track_too_long_even_at_the_duration_ratio_is_refused(self, tmp_path):
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=600)

        with pytest.raises(exceptions.MapillaryGPXVideoStartUnknownError) as excinfo:
            _extract(NO_GPS_VIDEO, gpx, VideoSyncOption(duration_ratio=10))

        assert "which at --video_duration_ratio 10 span 57.6 seconds" in str(
            excinfo.value
        )

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

    @pytest.mark.parametrize("sync_mode", [SyncMode.SYNC, SyncMode.REBASE])
    def test_process_still_assumes_the_track_starts_with_the_video(
        self, tmp_path, caplog, sync_mode
    ):
        """process has no --video_start_time to offer as a way out."""
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=3600)

        with caplog.at_level(logging.WARNING):
            metadata = GPXVideoExtractor(NO_GPS_VIDEO, gpx, sync_mode).extract()

        assert metadata.points[0].time == 0
        assert "--video_duration_ratio" not in caplog.text

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
            start=_GPS_VIDEO_START,
        )
        far_off = GPX_START.timestamp()

        synced = _extract(GPS_VIDEO, gpx, video_sync=None)
        with_start_time = _extract(GPS_VIDEO, gpx, VideoSyncOption(start_time=far_off))

        assert [p.time for p in with_start_time.points] == [
            p.time for p in synced.points
        ]

    def test_the_video_gps_clock_wins_over_the_duration_ratio(self, tmp_path, caplog):
        """
        The ratio is for the videos without a GPS clock, which a batch of
        videos may mix with videos that have one.
        """
        gpx = _write_gpx(
            tmp_path / "track.gpx",
            seconds=30,
            start=_GPS_VIDEO_START,
        )

        synced = _extract(GPS_VIDEO, gpx, video_sync=None)
        with_ratio = _extract(GPS_VIDEO, gpx, VideoSyncOption(duration_ratio=10))

        assert [p.time for p in with_ratio.points] == [p.time for p in synced.points]
        assert "Ignoring --video_duration_ratio 10 for" in caplog.text


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
            VideoSyncOption(start_time=video_start.timestamp()),
            InterpolationOption(offset_time=2),
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
            start=_GPS_VIDEO_START,
        )

        synced = _extract(GPS_VIDEO, gpx, VideoSyncOption())
        shifted = _extract(
            GPS_VIDEO, gpx, VideoSyncOption(), InterpolationOption(offset_time=2)
        )

        assert [p.time for p in shifted.points] == pytest.approx(
            [p.time - 2 for p in synced.points]
        )

    def test_use_gpx_start_time_starts_the_track_with_the_video(self, tmp_path):
        """
        Whatever the start time says: the user has said that the two started
        together.
        """
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=6)

        metadata = _extract(
            NO_GPS_VIDEO,
            gpx,
            VideoSyncOption(
                start_time=(GPX_START + datetime.timedelta(seconds=30)).timestamp()
            ),
            InterpolationOption(use_gpx_start_time=True),
        )

        assert metadata.points[0].time == 0


class TestProcessInterpolationOptions:
    """
    process applies --interpolation_offset_time and
    --interpolation_use_gpx_start_time to the track it geotags a video with, as
    it does when it geotags images from a GPX. It ignored them for videos.
    """

    # 3.613 seconds before the GPS clock of GPS_VIDEO starts
    START = datetime.datetime(2019, 11, 18, 23, 44, 40, tzinfo=datetime.timezone.utc)

    def test_use_gpx_start_time_starts_the_track_with_a_video_with_gps(self, tmp_path):
        """Instead of syncing it by the GPS clock of the video."""
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=20, start=self.START)

        synced = _extract(GPS_VIDEO, gpx, None, InterpolationOption())
        started = _extract(
            GPS_VIDEO, gpx, None, InterpolationOption(use_gpx_start_time=True)
        )

        assert synced.points[0].time == pytest.approx(-3.613)
        assert started.points[0].time == 0

    def test_the_offset_shifts_the_track_but_not_its_times(self, tmp_path):
        """
        The frame at video time t is at the position the GPX recorded at
        t + offset, and takes that time, as an image does.
        """
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=20, start=self.START)

        synced = _extract(GPS_VIDEO, gpx, None, InterpolationOption())
        shifted = _extract(GPS_VIDEO, gpx, None, InterpolationOption(offset_time=2))

        assert [p.time for p in shifted.points] == pytest.approx(
            [p.time - 2 for p in synced.points]
        )
        assert [p.get_unix_time() for p in shifted.points] == [
            p.get_unix_time() for p in synced.points
        ]

    def test_both_on_a_video_without_gps(self, tmp_path):
        """As the README describes for a GPX started 2.5 seconds before the video."""
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=6)

        metadata = _extract(
            NO_GPS_VIDEO,
            gpx,
            None,
            InterpolationOption(use_gpx_start_time=True, offset_time=2.5),
        )

        assert metadata.points[0].time == pytest.approx(-2.5)
        assert metadata.points[0].get_unix_time() == GPX_START.timestamp()

    def test_without_them_the_track_is_placed_as_before(self, tmp_path):
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=3600)

        metadata = _extract(NO_GPS_VIDEO, gpx, None, InterpolationOption())

        assert metadata.points[0].time == 0
        assert metadata.points[0].get_unix_time() == GPX_START.timestamp()

    def test_the_factory_hands_them_to_the_gpx_source(self, tmp_path):
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=6)

        [metadata] = factory.process(
            [NO_GPS_VIDEO],
            [
                SourceOption(
                    SourceType.GPX,
                    source_path=SourcePathOption(source_path=gpx),
                    interpolation=InterpolationOption(offset_time=2),
                )
            ],
        )

        assert isinstance(metadata, types.VideoMetadata)
        assert metadata.points[0].time == pytest.approx(-2)


def _write_gpx_tracks(path: Path, tracks: list[list[str]]) -> Path:
    """A GPX file with one track per list of times, heading north at 10 m/s."""
    trks = []
    for i, times in enumerate(tracks):
        points = "".join(
            f'<trkpt lat="{37.0 + (i * 100 + j) * 10 / 111_320:.7f}" lon="-122.0">'
            f"<ele>10</ele><time>{time}</time></trkpt>"
            for j, time in enumerate(times)
        )
        trks.append(f"<trk><trkseg>{points}</trkseg></trk>")
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"{''.join(trks)}</gpx>\n"
    )
    return path


class TestUntidyGPX:
    """
    GPX files converted from camera logs can list their tracks out of order,
    and carry whole tracks timestamped 1969-12-31T15:59:59Z. Merged as they
    were, the points were out of time order, and sampling crashed in the
    interpolator.
    """

    JUNK = "1969-12-31T15:59:59Z"
    LATER = ["2025-03-14T07:00:10Z", "2025-03-14T07:00:11Z"]
    EARLIER = ["2025-03-14T07:00:00Z", "2025-03-14T07:00:01Z"]

    def _gpx(self, tmp_path):
        return _write_gpx_tracks(
            tmp_path / "track.gpx", [self.LATER, [self.JUNK] * 3, self.EARLIER]
        )

    @pytest.mark.parametrize(
        "video_sync",
        [
            pytest.param(None, id="process"),
            pytest.param(
                VideoSyncOption(start_time=GPX_START.timestamp()), id="sampling"
            ),
        ],
    )
    def test_points_before_1980_are_dropped_and_the_rest_sorted(
        self, tmp_path, video_sync
    ):
        metadata = _extract(NO_GPS_VIDEO, self._gpx(tmp_path), video_sync)

        unix_times = [p.get_unix_time() for p in metadata.points]
        assert unix_times == sorted(unix_times)
        assert len(unix_times) == 4
        assert unix_times[0] == GPX_START.timestamp()

    def test_use_gpx_start_time_starts_at_the_earliest_point(self, tmp_path):
        """Not at the first point in the file, nor at a junk one."""
        metadata = _extract(
            NO_GPS_VIDEO,
            self._gpx(tmp_path),
            VideoSyncOption(),
            InterpolationOption(use_gpx_start_time=True),
        )

        assert metadata.points[0].time == 0
        assert metadata.points[0].get_unix_time() == GPX_START.timestamp()


class TestVideoGPSWithoutAClock:
    """
    A video whose GPS has no usable clock, such as GPS rejected as noise with a
    placeholder date, has nothing to sync a GPX with, as if it had no GPS.
    """

    def test_the_track_is_placed_by_the_video_start_time(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            GPXVideoExtractor,
            "_read_video_clock",
            classmethod(lambda cls, points: None),
        )
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=60)
        video_start = GPX_START + datetime.timedelta(seconds=30)

        metadata = _extract(
            GPS_VIDEO, gpx, VideoSyncOption(start_time=video_start.timestamp())
        )

        assert metadata.points[30].time == pytest.approx(0)


class TestTimelapseOffset:
    def test_the_offset_is_in_gps_seconds(self, tmp_path, monkeypatch):
        """
        A timelapse packs rate GPS seconds into each video second, so an offset
        of 2 GPS seconds moves the track by 2 / rate seconds of video.
        """
        start = datetime.datetime(
            2019, 11, 18, 15, 44, 40, tzinfo=datetime.timezone.utc
        )
        monkeypatch.setattr(
            GPXVideoExtractor,
            "_read_video_clock",
            classmethod(
                lambda cls, points: VideoClock(
                    video_time=0.0, unix_time=start.timestamp(), rate=10.0
                )
            ),
        )
        gpx = _write_gpx(tmp_path / "track.gpx", seconds=30, start=start)

        synced = _extract(GPS_VIDEO, gpx, VideoSyncOption())
        shifted = _extract(
            GPS_VIDEO, gpx, VideoSyncOption(), InterpolationOption(offset_time=2)
        )

        assert [p.time for p in shifted.points] == pytest.approx(
            [p.time - 0.2 for p in synced.points]
        )
        # and the frames are stamped 2 GPS seconds back, for the geotagging
        # stage to add them again
        assert [p.get_unix_time() for p in shifted.points] == pytest.approx(
            [p.get_unix_time() - 2 for p in synced.points]
        )
