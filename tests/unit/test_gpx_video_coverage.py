# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests for checking a GPX track, as placed on the timeline of a video, against
the video.

A GPX track that misses the video has no position for any moment of it, so
it fails with MapillaryOutsideGPXTrackError, a geotagging error that lets the
next geotag source take its turn, with a warning. A track that covers only part
of the video warns.
"""

from __future__ import annotations

import datetime
import io
import logging
import pickle
import shutil
import typing as T
from pathlib import Path

import pytest
from mapillary_tools import constants, exceptions, geo, telemetry, types, uploader
from mapillary_tools.camm import camm_builder
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import (
    InterpolationOption,
    SourceOption,
    SourcePathOption,
    SourceType,
    VideoSyncOption,
)
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor, SyncMode
from mapillary_tools.mp4 import construct_mp4_parser as cparser, simple_mp4_builder


# 2026-08-12T08:26:27Z, in GPS time and in Unix time
A_GPS_TIME = 1470558405.9798455
A_UNIX_TIME = 1786523187.9798455

# Seconds between the mp4 epoch (1904-01-01) and the Unix epoch
MP4_UNIX_DELTA = 2082844800

_DATA = Path(__file__).resolve().parent.parent.joinpath("data")
# No GPS of its own, and 5.76 seconds long
NO_GPS_VIDEO = _DATA.joinpath("videos", "sample-5s.mp4")
# Captured 2018-06-08T20:24:11Z at 45.5169, -122.5728
IMAGE = _DATA.joinpath("images", "DSC00001.JPG")

# A 10s video track starting at A_UNIX_TIME, in a 12s video
VIDEO_DURATION = 12.0


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


def _video_track(rate: float = 1.0) -> list[telemetry.CAMMGPSPoint]:
    """A GPS point every second of video, its clock running rate times faster"""
    return [
        _camm_point(time=float(t), epoch_time=A_UNIX_TIME + rate * t) for t in range(11)
    ]


# GPS without timestamps, so the GPX can only be assumed to start with the video
UNTIMED_TRACK = [
    geo.Point(time=float(t), lat=37.0, lon=14.0, alt=None, angle=None)
    for t in range(11)
]


def _write_camm_mp4(
    path: Path,
    points: T.Sequence[geo.Point],
    duration: float = VIDEO_DURATION,
    creation_time: float | None = A_UNIX_TIME + 600,
) -> Path:
    """
    Write points as a CAMM track into an empty mp4, the way the uploader does.

    duration is the duration of the video in seconds, or 0 for unknown.
    creation_time is the Unix time to put in mvhd, or None to leave it unset.
    """
    mp4_creation_time = (
        0 if creation_time is None else int(creation_time) + MP4_UNIX_DELTA
    )
    mvhd: cparser.BoxDict = {
        "type": b"mvhd",
        "data": {
            "creation_time": mp4_creation_time,
            "modification_time": mp4_creation_time,
            "timescale": 1000,
            "duration": int(duration * 1000),
        },
    }
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(
        [
            {"type": b"ftyp", "data": b"test"},
            {"type": b"moov", "data": [mvhd]},
        ]
    )
    metadata = types.VideoMetadata(
        Path(""), filetype=types.FileType.CAMM, points=list(points)
    )
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)
    target_fp = simple_mp4_builder.transform_mp4(
        io.BytesIO(src), camm_builder.camm_sample_generator2(camm_info)
    )
    path.write_bytes(target_fp.read())
    return path


def _write_gpx(path: Path, start: float, seconds: float, step: float = 1.0) -> Path:
    """A GPX track from start, a point every step seconds for seconds"""
    count = int(round(seconds / step))
    trkpts = "".join(
        f'<trkpt lat="37.0" lon="14.0"><time>{_isoformat(start + i * step)}</time></trkpt>'
        for i in range(count + 1)
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{trkpts}</trkseg></trk></gpx>"
    )
    return path


def _isoformat(unix_time: float) -> str:
    return (
        datetime.datetime.fromtimestamp(unix_time, datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


class TestVideoWithGPSClock:
    """The video's own GPS clock places the track, and says when it misses."""

    def _extract(
        self,
        tmp_path: Path,
        gpx_start: float,
        gpx_seconds: float,
        video_track: T.Sequence[geo.Point] | None = None,
        duration: float = VIDEO_DURATION,
        interpolation: InterpolationOption | None = None,
    ) -> types.VideoMetadata:
        video_path = _write_camm_mp4(
            tmp_path / "video.mp4",
            _video_track() if video_track is None else video_track,
            duration,
        )
        gpx_path = _write_gpx(tmp_path / "track.gpx", gpx_start, gpx_seconds)
        return GPXVideoExtractor(
            video_path, gpx_path, interpolation=interpolation
        ).extract()

    @pytest.mark.parametrize(
        "start, seconds",
        [
            # Starts 30s before the video and ends after it
            (A_UNIX_TIME - 30, 60),
            # Started a second into the video, and ends with it
            (A_UNIX_TIME + 1, 11),
            # A long recording that spans the video
            (A_UNIX_TIME - 3 * 24 * 3600, 6 * 24 * 3600),
        ],
    )
    def test_covering_gpx_is_silent(self, tmp_path, caplog, start, seconds):
        with caplog.at_level(logging.WARNING):
            self._extract(tmp_path, start, seconds)
        assert not _warnings(caplog)

    @pytest.mark.parametrize(
        "start, seconds, uncovered",
        [
            # Ends 5s into the video
            (A_UNIX_TIME - 30, 35, "7 seconds"),
            # Starts 5s into the video
            (A_UNIX_TIME + 5, 60, "5 seconds"),
            # Starts after the video's own GPS gives out, before the video ends
            (A_UNIX_TIME + 11, 20, "11 seconds"),
        ],
    )
    def test_partial_cover_warns(self, tmp_path, caplog, start, seconds, uncovered):
        with caplog.at_level(logging.WARNING):
            self._extract(tmp_path, start, seconds)
        [warning] = _warnings(caplog)
        assert "covers only part of" in warning
        assert f"{uncovered} of the video fall outside the track" in warning
        assert "video.mp4" in warning and "track.gpx" in warning

    @pytest.mark.parametrize(
        "start",
        [
            # Ended a minute before the video started
            A_UNIX_TIME - 70,
            # Starts after the video ends, though within a minute of it
            A_UNIX_TIME + 13,
            # Naive GPX timestamps read in a time zone 2h off
            A_UNIX_TIME + 2 * 3600,
            # A GPX file from another day
            A_UNIX_TIME - 3 * 24 * 3600,
        ],
    )
    def test_missing_the_video_raises(self, tmp_path, start):
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(tmp_path, start, 10)
        message = str(info.value)
        assert "video.mp4" in message and "track.gpx" in message
        assert "belongs to this video" in message
        assert "time zone" in message

    @pytest.mark.parametrize(
        "gap, reported",
        [
            # The GPX of the next clip, starting just after the video ends
            (0.089, "by 0.089 seconds."),
            (1, "by 1 second."),
            (70, "by 1.2 minutes."),
            (2 * 3600, "by 2.0 hours."),
            (3 * 24 * 3600, "by 3.0 days."),
        ],
    )
    def test_gap_is_reported_in_a_readable_unit(self, tmp_path, gap, reported):
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(tmp_path, A_UNIX_TIME + VIDEO_DURATION + gap, 10)
        assert reported in str(info.value)

    def test_error_vars_name_the_video_start_and_the_gpx(self, tmp_path):
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(tmp_path, A_UNIX_TIME + 2 * 3600, 10)
        assert info.value.image_time == "2026_08_12_08_26_27_979"
        assert info.value.gpx_start_time == "2026_08_12_10_26_27_979"
        assert info.value.gpx_end_time == "2026_08_12_10_26_37_979"

    @pytest.mark.parametrize(
        "start",
        [
            A_UNIX_TIME - 70,
            A_UNIX_TIME + 2 * 3600,
            # Starts after the video's own GPS gives out, which the video
            # itself may not
            A_UNIX_TIME + 60,
        ],
    )
    def test_without_duration_a_gap_warns(self, tmp_path, caplog, start):
        with caplog.at_level(logging.WARNING):
            self._extract(tmp_path, start, 10, duration=0)
        [warning] = _warnings(caplog)
        assert "misses" in warning

    @pytest.mark.parametrize(
        "start", [A_UNIX_TIME + 2 * 24 * 3600, A_UNIX_TIME - 3 * 24 * 3600]
    )
    def test_without_duration_a_gap_of_days_raises(self, tmp_path, start):
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError):
            self._extract(tmp_path, start, 10, duration=0)

    def test_epoch_mixup_raises(self, tmp_path):
        """Video timestamps left in GPS time sync ten years off."""
        video_track = [
            _camm_point(time=float(t), epoch_time=A_GPS_TIME + t) for t in range(11)
        ]
        video_path = _write_camm_mp4(
            tmp_path / "video.mp4", video_track, creation_time=None
        )
        gpx_path = _write_gpx(tmp_path / "track.gpx", A_UNIX_TIME, 10)
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            GPXVideoExtractor(video_path, gpx_path).extract()
        assert "by 3657.0 days." in str(info.value)

    def test_the_interpolation_offset_is_part_of_the_placement(self, tmp_path, caplog):
        """
        The frames are looked up 5s later along the track, so a track that
        covers the video exactly leaves its last 5s uncovered.
        """
        with caplog.at_level(logging.WARNING):
            self._extract(
                tmp_path,
                A_UNIX_TIME,
                VIDEO_DURATION,
                interpolation=InterpolationOption(offset_time=5),
            )
        [warning] = _warnings(caplog)
        assert "5 seconds of the video fall outside the track" in warning

    def test_error_survives_a_worker_process(self, tmp_path):
        """Videos are geotagged in a process pool, so the error gets pickled."""
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(tmp_path, A_UNIX_TIME + 2 * 3600, 10)

        unpickled = pickle.loads(pickle.dumps(info.value))

        assert str(unpickled) == str(info.value)
        assert vars(unpickled) == vars(info.value)


class TestTimelapse:
    """The check is made on the placement the GPS clock gives the track."""

    # 11 seconds of video spanning 165 seconds of GPS time
    RATE = 15.0

    def _extract(self, tmp_path, gpx_start: float, gpx_seconds: float, **kwargs):
        video_path = _write_camm_mp4(
            tmp_path / "timelapse.mp4", _video_track(self.RATE), duration=11.0
        )
        gpx_path = _write_gpx(tmp_path / "track.gpx", gpx_start, gpx_seconds)
        return GPXVideoExtractor(video_path, gpx_path, **kwargs).extract()

    def test_gpx_of_the_whole_recording_is_silent(self, tmp_path, caplog):
        """At 1x, the track would run on 154 seconds past the video's end."""
        with caplog.at_level(logging.WARNING):
            metadata = self._extract(tmp_path, A_UNIX_TIME, 11 * self.RATE)
        assert not _warnings(caplog)
        assert metadata.points[-1].time == pytest.approx(11.0, abs=1e-3)

    def test_gpx_of_half_the_recording_warns(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            # The first 6 of the video's 11 seconds
            self._extract(tmp_path, A_UNIX_TIME, 6 * self.RATE)
        [warning] = _warnings(caplog)
        assert "5 seconds of the video fall outside the track" in warning

    def test_gap_is_reported_in_gps_time(self, tmp_path):
        """The GPX starts an hour after the recording ended."""
        recording_end = A_UNIX_TIME + 11 * self.RATE
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(tmp_path, recording_end + 3600, 60)
        assert "by 1.0 hours." in str(info.value)

    def test_gpx_start_time_keeps_the_rate(self, tmp_path, caplog):
        """
        --interpolation_use_gpx_start_time starts the track with the video,
        whatever the clock says, and the clock still sets its pace
        """
        with caplog.at_level(logging.WARNING):
            metadata = self._extract(
                tmp_path, A_UNIX_TIME + 3600, 11 * self.RATE, sync_mode=SyncMode.REBASE
            )
        assert not _warnings(caplog)
        assert metadata.points[0].time == 0
        assert metadata.points[-1].time == pytest.approx(11.0, abs=1e-3)


class TestVideoWithoutGPSClock:
    """
    Placed by --video_start_time, the track can be found to miss the video.
    Assumed to start with the video, it can only fall short of its end.
    """

    def _extract(
        self, tmp_path, video_path: Path, gpx_start: float, gpx_seconds: float, **sync
    ):
        gpx_path = _write_gpx(tmp_path / "track.gpx", gpx_start, gpx_seconds)
        return GPXVideoExtractor(
            video_path, gpx_path, video_sync=VideoSyncOption(**sync)
        ).extract()

    def test_start_time_two_hours_off_raises(self, tmp_path):
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(
                tmp_path, NO_GPS_VIDEO, A_UNIX_TIME, 30, start_time=A_UNIX_TIME + 7200
            )
        assert "by 2.0 hours." in str(info.value)

    def test_start_time_within_the_track_is_silent(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            self._extract(
                tmp_path, NO_GPS_VIDEO, A_UNIX_TIME, 30, start_time=A_UNIX_TIME + 10
            )
        assert not _warnings(caplog)

    @pytest.mark.parametrize(
        "video_track", [[], UNTIMED_TRACK], ids=["no GPS", "GPS without timestamps"]
    )
    def test_assumed_start_warns_of_a_short_track(self, tmp_path, caplog, video_track):
        video_path = _write_camm_mp4(tmp_path / "video.mp4", video_track)
        with caplog.at_level(logging.WARNING):
            # Covers the first 6 of the video's 12 seconds
            self._extract(tmp_path, video_path, A_UNIX_TIME, 6)
        [warning] = _warnings(caplog)
        assert "6 seconds of the video fall outside the track" in warning

    def test_assumed_start_is_silent_on_a_covering_track(self, tmp_path, caplog):
        video_path = _write_camm_mp4(tmp_path / "video.mp4", UNTIMED_TRACK)
        with caplog.at_level(logging.WARNING):
            self._extract(tmp_path, video_path, A_UNIX_TIME, VIDEO_DURATION)
        assert not _warnings(caplog)


class TestInterpolationOffset:
    """
    --interpolation_offset_time moves the track along the video, and can move
    it off, however the track was placed: a track placed at the start of the
    video then misses it as surely as one placed by a clock.
    """

    def _extract(
        self,
        tmp_path,
        video_track: T.Sequence[geo.Point],
        offset_time: float,
        use_gpx_start_time: bool = False,
    ) -> types.VideoMetadata:
        video_path = _write_camm_mp4(tmp_path / "video.mp4", video_track)
        gpx_path = _write_gpx(tmp_path / "track.gpx", A_UNIX_TIME, VIDEO_DURATION)
        return GPXVideoExtractor(
            video_path,
            gpx_path,
            interpolation=InterpolationOption(
                offset_time=offset_time, use_gpx_start_time=use_gpx_start_time
            ),
        ).extract()

    @pytest.mark.parametrize(
        "video_track, use_gpx_start_time",
        [([], False), (UNTIMED_TRACK, False), (_video_track(), True)],
        ids=["no GPS", "GPS without timestamps", "use_gpx_start_time"],
    )
    # Before the start of the video, and after its end
    @pytest.mark.parametrize("offset_time", [100, -100])
    def test_a_track_placed_at_the_start_moved_off_raises(
        self, tmp_path, video_track, use_gpx_start_time, offset_time
    ):
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(tmp_path, video_track, offset_time, use_gpx_start_time)
        message = str(info.value)
        assert (
            f"by 1.5 minutes, as --interpolation_offset_time {offset_time} " in message
        )
        # Nothing but the offset can have moved it off
        assert message.endswith(". Check --interpolation_offset_time")

    def test_the_error_gives_the_times_the_video_is_looked_up_at(self, tmp_path):
        """
        Its own times overlap the track, and would contradict the gap. The
        offset is added to them, as it is to the capture time of an image.
        """
        # The clock of the video puts the track at video times -20 to -8
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(tmp_path, _video_track(), offset_time=20)
        message = str(info.value)
        assert (
            "by 8 seconds, as --interpolation_offset_time 20 looks the video up "
            "along it (2026-08-12T08:26:47.979846+00:00 to 2026-08-12T08:26:59.979846+00:00)"
        ) in message
        assert "Check --interpolation_offset_time, that the GPX file belongs" in message
        assert info.value.image_time == "2026_08_12_08_26_47_979"

    def test_moved_partly_off_it_warns(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            self._extract(tmp_path, [], offset_time=6)
        [warning] = _warnings(caplog)
        assert "as --interpolation_offset_time 6 looks the video up" in warning
        assert "6 seconds of the video fall outside the track" in warning


class TestFallThrough:
    """
    A GPX that misses a file lets the next geotag source take its turn, with a
    warning when that source geotags the file, so the GPX does not go unnoticed.
    """

    def test_video_is_geotagged_by_the_next_source_with_a_warning(
        self, tmp_path, caplog
    ):
        video_path = _write_camm_mp4(tmp_path / "video.mp4", _video_track())
        gpx_path = _write_gpx(tmp_path / "track.gpx", A_UNIX_TIME + 2 * 3600, 10)
        options = [
            SourceOption(
                SourceType.GPX,
                num_processes=0,
                source_path=SourcePathOption(source_path=gpx_path),
            ),
            SourceOption(SourceType.NATIVE, num_processes=0),
        ]

        with caplog.at_level(logging.WARNING):
            [metadata] = factory.process([video_path], options)

        assert isinstance(metadata, types.VideoMetadata)
        assert [p.time for p in metadata.points] == [float(t) for t in range(11)]
        [warning] = _warnings(caplog)
        assert "misses the video" in warning and "by 2.0 hours" in warning
        assert warning.endswith("Geotagged it from the native source instead")

    def _process_images(
        self, tmp_path: Path, sources: list[SourceType], count: int = 1
    ) -> list[types.MetadataOrError]:
        image_paths = []
        for i in range(count):
            image_path = tmp_path / f"image{i}.jpg"
            shutil.copyfile(IMAGE, image_path)
            image_paths.append(image_path)
        # A track recorded years after the images
        gpx_path = _write_gpx(tmp_path / "walk.gpx", A_UNIX_TIME, 10)
        options = [
            SourceOption(
                source,
                num_processes=0,
                source_path=SourcePathOption(source_path=gpx_path),
            )
            if source is SourceType.GPX
            else SourceOption(source, num_processes=0)
            for source in sources
        ]
        return factory.process(image_paths, options)

    def test_images_are_geotagged_by_the_next_source_with_one_warning(
        self, tmp_path, caplog
    ):
        with caplog.at_level(logging.WARNING):
            metadatas = self._process_images(
                tmp_path, [SourceType.GPX, SourceType.EXIF], count=3
            )

        assert all(isinstance(m, types.ImageMetadata) for m in metadatas)
        assert {(round(m.lat, 4), round(m.lon, 4)) for m in metadatas} == {
            (45.5169, -122.5728)
        }
        [warning] = _warnings(caplog)
        assert warning == (
            f"3 images fall outside the GPX track in {tmp_path / 'walk.gpx'}. "
            "Geotagged them from the exif source instead"
        )

    def test_gpx_as_the_only_source_fails_the_image(self, tmp_path):
        [metadata] = self._process_images(tmp_path, [SourceType.GPX])

        assert isinstance(metadata, types.ErrorMetadata)
        assert isinstance(metadata.error, exceptions.MapillaryOutsideGPXTrackError)


def _write_gpx_parts(path: Path, parts: T.Sequence[tuple[float, float]]) -> Path:
    """A GPX track of several parts, each (start, seconds) with a point a second"""
    trkpts = "".join(
        f'<trkpt lat="37.0" lon="14.0"><time>{_isoformat(start + i)}</time></trkpt>'
        for start, seconds in parts
        for i in range(int(seconds) + 1)
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{trkpts}</trkseg></trk></gpx>"
    )
    return path


class TestGapsInTheTrack:
    """
    A GPX track can hold several trips, with the GPS logger switched off in
    between. Nothing can be interpolated across a gap of more than an hour
    between two of its points, which is outside the track like the time before
    or after it.
    """

    def _extract(
        self,
        tmp_path: Path,
        parts: T.Sequence[tuple[float, float]],
        video_track: T.Sequence[geo.Point] | None = None,
        duration: float = VIDEO_DURATION,
        **kwargs,
    ) -> types.VideoMetadata:
        video_path = _write_camm_mp4(
            tmp_path / "video.mp4",
            _video_track() if video_track is None else video_track,
            duration,
        )
        gpx_path = _write_gpx_parts(tmp_path / "track.gpx", parts)
        return GPXVideoExtractor(video_path, gpx_path, **kwargs).extract()

    def test_a_video_in_a_gap_misses_the_track(self, tmp_path):
        """Trips ended 3 hours before the video and started 2 hours after it"""
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(
                tmp_path,
                [
                    (A_UNIX_TIME - 3 * 3600 - 60, 60),
                    (A_UNIX_TIME + VIDEO_DURATION + 2 * 3600, 60),
                ],
            )
        message = str(info.value)
        # The gap, and the last point before it and the first after it
        assert (
            "has a gap of 5.0 hours, from 2026-08-12T05:26:27.979846+00:00 at (37.0, 14.0) "
            "to 2026-08-12T10:26:39.979846+00:00 at (37.0, 14.0), which the video"
        ) in message
        assert "falls in. Check that the GPX file belongs to this video" in message
        assert info.value.image_time == "2026_08_12_08_26_27_979"

    def test_a_gap_of_less_than_an_hour_is_interpolated(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            self._extract(
                tmp_path, [(A_UNIX_TIME - 1800, 60), (A_UNIX_TIME + 1500, 60)]
            )
        assert not _warnings(caplog)

    def test_a_gap_in_part_of_the_video_warns(self, tmp_path, caplog):
        """The first trip ends 5 seconds into the video"""
        with caplog.at_level(logging.WARNING):
            self._extract(tmp_path, [(A_UNIX_TIME - 60, 65), (A_UNIX_TIME + 7200, 60)])
        [warning] = _warnings(caplog)
        assert "7 seconds of the video fall outside the track" in warning

    def test_the_gap_of_a_timelapse_is_in_gps_time(self, tmp_path):
        """
        2 hours of GPS time are 8 minutes of a timelapse at 15x, a gap in GPS
        time, where trips are recorded
        """
        rate = 15.0
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(
                tmp_path,
                [(A_UNIX_TIME - 3600 - 60, 60), (A_UNIX_TIME + 11 * rate + 3600, 60)],
                video_track=_video_track(rate),
                duration=11.0,
            )
        assert "has a gap of 2.0 hours" in str(info.value)

    def test_a_start_time_in_a_gap_misses_the_track(self, tmp_path):
        gpx_path = _write_gpx_parts(
            tmp_path / "track.gpx",
            [(A_UNIX_TIME - 7200, 60), (A_UNIX_TIME + 7200, 60)],
        )
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            GPXVideoExtractor(
                NO_GPS_VIDEO,
                gpx_path,
                video_sync=VideoSyncOption(start_time=A_UNIX_TIME),
            ).extract()
        assert "has a gap of 4.0 hours" in str(info.value)

    def test_the_limit_can_be_raised(self, tmp_path, caplog, monkeypatch):
        """By MAPILLARY_TOOLS_MAX_GPX_GAP_SECONDS"""
        monkeypatch.setattr(constants, "MAX_GPX_GAP_SECONDS", 6 * 3600)
        with caplog.at_level(logging.WARNING):
            self._extract(
                tmp_path,
                [
                    (A_UNIX_TIME - 3 * 3600 - 60, 60),
                    (A_UNIX_TIME + VIDEO_DURATION + 2 * 3600, 60),
                ],
            )
        assert not _warnings(caplog)

    def _process_image(
        self, tmp_path: Path, parts: T.Sequence[tuple[float, float]]
    ) -> types.MetadataOrError:
        image_path = tmp_path / "image.jpg"
        shutil.copyfile(IMAGE, image_path)
        gpx_path = _write_gpx_parts(tmp_path / "walk.gpx", parts)
        [metadata] = factory.process(
            [image_path],
            [
                SourceOption(
                    SourceType.GPX,
                    num_processes=0,
                    source_path=SourcePathOption(source_path=gpx_path),
                )
            ],
        )
        return metadata

    # The capture time of IMAGE
    IMAGE_TIME = datetime.datetime(
        2018, 6, 8, 20, 24, 11, tzinfo=datetime.timezone.utc
    ).timestamp()

    def test_an_image_in_a_gap_is_outside_the_track(self, tmp_path):
        metadata = self._process_image(
            tmp_path, [(self.IMAGE_TIME - 3600, 60), (self.IMAGE_TIME + 600, 60)]
        )
        assert isinstance(metadata, types.ErrorMetadata)
        assert isinstance(metadata.error, exceptions.MapillaryOutsideGPXTrackError)
        # The gap, and the last point before it and the first after it
        assert str(metadata.error) == (
            "The GPX track has a gap of 1.1 hours, from 2018-06-08T19:25:11+00:00 at (37.0, 14.0) "
            "to 2018-06-08T20:34:11+00:00 at (37.0, 14.0), which the image time "
            "2018-06-08T20:24:11+00:00 falls in"
        )
        assert vars(metadata.error) == {
            "image_time": "2018_06_08_20_24_11_000",
            "gpx_start_time": "2018_06_08_19_24_11_000",
            "gpx_end_time": "2018_06_08_20_35_11_000",
        }

    def test_the_image_limit_can_be_raised(self, tmp_path, monkeypatch):
        """By MAPILLARY_TOOLS_MAX_GPX_GAP_SECONDS"""
        monkeypatch.setattr(constants, "MAX_GPX_GAP_SECONDS", 2 * 3600)
        metadata = self._process_image(
            tmp_path, [(self.IMAGE_TIME - 3600, 60), (self.IMAGE_TIME + 600, 60)]
        )
        assert isinstance(metadata, types.ImageMetadata)

    def test_an_image_in_a_gap_of_less_than_an_hour_is_interpolated(self, tmp_path):
        metadata = self._process_image(
            tmp_path, [(self.IMAGE_TIME - 1800, 60), (self.IMAGE_TIME + 600, 60)]
        )
        assert isinstance(metadata, types.ImageMetadata)

    def test_an_image_on_a_point_by_a_gap_is_on_the_track(self, tmp_path):
        """The last point before the gap is the image's own position"""
        metadata = self._process_image(
            tmp_path, [(self.IMAGE_TIME - 60, 60), (self.IMAGE_TIME + 7200, 60)]
        )
        assert isinstance(metadata, types.ImageMetadata)


class TestGapsInTheTrackUploadedWithTheVideo:
    """
    process uploads the track with the video, and the frames are placed along
    it. Nothing can be interpolated across a gap of more than an hour: a video
    that starts or ends in one takes the track from the far side of it no
    further, and one with a gap inside fails, as sampling leaves out the frames
    in the gap.
    """

    def _extract(
        self, tmp_path: Path, parts: T.Sequence[tuple[float, float]], **kwargs
    ) -> types.VideoMetadata:
        video_path = _write_camm_mp4(tmp_path / "video.mp4", _video_track())
        gpx_path = _write_gpx_parts(tmp_path / "track.gpx", parts)
        return GPXVideoExtractor(
            video_path, gpx_path, clip_to_video=True, **kwargs
        ).extract()

    def test_a_start_in_a_gap_starts_the_track_past_it(self, tmp_path, caplog):
        """The trip before ended 2 hours before the video, and the next one starts 5 seconds into it"""
        with caplog.at_level(logging.WARNING):
            metadata = self._extract(
                tmp_path, [(A_UNIX_TIME - 7260, 60), (A_UNIX_TIME + 5, 60)]
            )
        times = [p.time for p in metadata.points]
        # No point at video time 0, interpolated across the gap
        assert times[0] == pytest.approx(5.0)
        assert times[-1] == pytest.approx(VIDEO_DURATION)
        [warning] = _warnings(caplog)
        assert "5 seconds of the video fall outside the track" in warning

    def test_an_end_in_a_gap_ends_the_track_before_it(self, tmp_path, caplog):
        """The trip ends 6 seconds into the video, and the next one starts 2 hours later"""
        with caplog.at_level(logging.WARNING):
            metadata = self._extract(
                tmp_path, [(A_UNIX_TIME - 60, 66), (A_UNIX_TIME + 7200, 60)]
            )
        times = [p.time for p in metadata.points]
        assert times[0] == 0
        # No point at the end of the video, interpolated across the gap
        assert times[-1] == pytest.approx(6.0)
        [warning] = _warnings(caplog)
        assert "6 seconds of the video fall outside the track" in warning

    def test_a_gap_inside_the_video_fails_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr(constants, "MAX_GPX_GAP_SECONDS", 3)
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(tmp_path, [(A_UNIX_TIME - 10, 13), (A_UNIX_TIME + 7, 30)])
        message = str(info.value)
        assert (
            "has a gap of 4 seconds, from 2026-08-12T08:26:30.979846+00:00 at (37.0, 14.0) "
            "to 2026-08-12T08:26:34.979846+00:00 at (37.0, 14.0), inside the video"
        ) in message
        assert message.endswith(
            "Sample the video with video_process and --video_geotag_source gpx, which leaves out the frames in the gap"
        )
        assert info.value.image_time == "2026_08_12_08_26_27_979"

    def test_sampling_leaves_the_gap_inside_the_video_to_the_frames(
        self, tmp_path, monkeypatch, caplog
    ):
        monkeypatch.setattr(constants, "MAX_GPX_GAP_SECONDS", 3)
        video_path = _write_camm_mp4(tmp_path / "video.mp4", _video_track())
        gpx_path = _write_gpx_parts(
            tmp_path / "track.gpx", [(A_UNIX_TIME - 10, 13), (A_UNIX_TIME + 7, 30)]
        )
        with caplog.at_level(logging.WARNING):
            metadata = GPXVideoExtractor(
                video_path, gpx_path, video_sync=VideoSyncOption()
            ).extract()
        assert metadata.points
        [warning] = _warnings(caplog)
        assert "covers only part of the video" in warning

    def test_a_gap_of_less_than_an_hour_is_interpolated(self, tmp_path):
        metadata = self._extract(
            tmp_path, [(A_UNIX_TIME - 1860, 60), (A_UNIX_TIME + 5, 60)]
        )
        first = metadata.points[0]
        assert first.time == 0
        assert first.get_unix_time() == pytest.approx(A_UNIX_TIME)

    def test_the_limit_can_be_raised(self, tmp_path, monkeypatch):
        """By MAPILLARY_TOOLS_MAX_GPX_GAP_SECONDS"""
        monkeypatch.setattr(constants, "MAX_GPX_GAP_SECONDS", 3 * 3600)
        metadata = self._extract(
            tmp_path, [(A_UNIX_TIME - 7260, 60), (A_UNIX_TIME + 5, 60)]
        )
        assert metadata.points[0].time == 0

    def test_started_with_the_video_ends_before_a_gap(self, tmp_path):
        """--interpolation_use_gpx_start_time places the track, the clock gives its pace"""
        metadata = self._extract(
            tmp_path,
            [(A_UNIX_TIME, 6), (A_UNIX_TIME + 7200, 60)],
            sync_mode=SyncMode.REBASE,
        )
        times = [p.time for p in metadata.points]
        assert times == [float(t) for t in range(7)]

    def test_a_start_moved_into_a_gap_by_the_offset(self, tmp_path):
        """
        Without a GPS clock the track is assumed to start with the video, and
        --interpolation_offset_time moves the start of the video into the gap
        """
        video_path = _write_camm_mp4(tmp_path / "video.mp4", UNTIMED_TRACK)
        gpx_path = _write_gpx_parts(
            tmp_path / "track.gpx", [(A_UNIX_TIME, 10), (A_UNIX_TIME + 7200, 60)]
        )
        metadata = GPXVideoExtractor(
            video_path,
            gpx_path,
            interpolation=InterpolationOption(offset_time=7195),
            clip_to_video=True,
        ).extract()
        times = [p.time for p in metadata.points]
        assert times[0] == pytest.approx(5.0)
        assert times[-1] == pytest.approx(65.0)

    def test_a_video_started_at_a_lone_fix_falls_in_the_gap_after_it(self, tmp_path):
        """
        --interpolation_use_gpx_start_time starts the video at the first point
        of the track, the only one before a gap of 2 hours: the track touches
        the video at that instant alone
        """
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            self._extract(
                tmp_path,
                [(A_UNIX_TIME, 0), (A_UNIX_TIME + 7200, 60)],
                sync_mode=SyncMode.REBASE,
            )
        message = str(info.value)
        assert (
            "has a gap of 2.0 hours, from 2026-08-12T08:26:27.979846+00:00" in message
        )
        assert message.endswith("falls in. Trim the GPX to the video")

    def test_a_video_assumed_to_start_at_a_lone_fix_falls_in_the_gap_after_it(
        self, tmp_path
    ):
        video_path = _write_camm_mp4(tmp_path / "video.mp4", UNTIMED_TRACK)
        gpx_path = _write_gpx_parts(
            tmp_path / "track.gpx", [(A_UNIX_TIME, 0), (A_UNIX_TIME + 7200, 60)]
        )
        with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
            GPXVideoExtractor(video_path, gpx_path, clip_to_video=True).extract()
        assert str(info.value).endswith(
            "falls in. Trim the GPX to the video, or sample the video with "
            "video_process and --video_start_time"
        )
