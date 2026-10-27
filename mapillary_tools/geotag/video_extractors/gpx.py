# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import bisect
import dataclasses
import datetime
import enum
import logging
import math
import statistics
import sys
import typing as T
from pathlib import Path

import construct as C
import gpxpy

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import constants, exceptions, geo, telemetry, types, utils
from ...camm import camm_parser
from ...mp4 import construct_mp4_parser as cparser, simple_mp4_parser as sparser
from ...mp4.mp4_sample_parser import MovieBoxParser
from ...serializer.description import build_capture_time
from .. import options, utils as geotag_utils
from .base import BaseVideoExtractor
from .native import NativeVideoExtractor


LOG = logging.getLogger(__name__)

# No camera clock or time zone mistake puts a GPX track and the video it
# belongs to more than a day apart, while an epoch mix-up exceeds it by orders
# of magnitude.
_IMPLAUSIBLE_OFFSET_SECONDS = 24 * 3600

# A GPX track that lasts longer than this is not that of one recording, such as
# a GPS logger left running after the video, but a log of several trips
_MAX_RECORDING_SECONDS = 24 * 3600

# A GPS clock that runs this much faster than the video clock is a timelapse,
# and the steps between its timestamps show it too
_MIN_TIMELAPSE_RATE = 1.5

# No GPS fix can be timestamped before the GPS epoch, 1980-01-06. GPX files
# converted from camera logs can carry earlier times, such as
# 1969-12-31T15:59:59Z, on points that had no valid time
_GPS_EPOCH = datetime.datetime(1980, 1, 6, tzinfo=datetime.timezone.utc).timestamp()

# How far a GPX track may run past either end of a video, when it is assumed
# to start with the video, or fall short of them, without a warning. A logger
# that records once a second, started and stopped with the camera, can be a
# second off at each end.
_LOGGER_TOLERANCE_SECONDS = 2.0

# The first GPS timestamps of a recording can be stale: GoPro stamps its first
# block of points up to 3 seconds before the rest place the start of the video,
# and a PANOX V2 its first fix 7.6 seconds before. The step from a stale
# timestamp to the next runs this much faster than the median step of the rest.
# Further on, steps that fast are kept: a LabPano Pilot One gains on the video
# in steps of a second per half second, 2 minutes over a 14-minute video
_STALE_STEP_RATE = 1.5

# A GPS clock that runs within this fraction of the video's pace runs at it.
# Over 20 seconds or more, cameras that record in real time measure within
# 0.4% of 1x, or 1.6% for a GoPro MAX whose GPS glitches, while the clock of a
# LabPano runs 14% faster than its video
_MAX_CLOCK_RATE_ERROR = 0.05

# Nor can GPS timestamps measure a clock that departs from the video's pace by
# less than their own jitter over the video time they span: GoPro stamps blocks
# of points up to 1.7 seconds off the line through the rest, and clips a few
# seconds long measure up to 15% off 1x, if by no more than 0.3 seconds
_MAX_CLOCK_DRIFT_SECONDS = 2.0

# Nor, below the timelapse rate, do timestamps over less than this, of video
# or of GPS time, measure a pace off 1x: over 8 to 20 seconds of GoPro and
# PANOX V2 videos, a few timestamps seconds off the rest measure 0.24x to
# 1.33x, by least squares and by the median of slopes alike. The LabPano
# videos, whose clocks gain on them, span 3 minutes or more
_MIN_CLOCK_SPAN_SECONDS = 60.0

# The rate is the median of the slopes between pairs of timestamps, which a
# few timestamps off the rest, or a step of the clock, do not move: a clock
# that steps 18 seconds ahead two thirds into a 2-minute video pulls the
# least-squares slope to 1.2x. Over more timestamps than this, an evenly spaced
# selection of them measures it to within 0.01%
_MAX_RATE_TIMESTAMPS = 300


class SyncMode(enum.Enum):
    # Sync by video GPS timestamps if found, otherwise rebase
    SYNC = "sync"
    # Sync by video GPS timestamps, and throw if not found
    STRICT_SYNC = "strict_sync"
    # Rebase all GPX timestamps to start from 0
    REBASE = "rebase"


@dataclasses.dataclass(frozen=True)
class VideoClock:
    """
    Maps between the video time and the Unix time of the GPS clock in the video:
    a straight line, as a camera records its frames at a steady pace, whether
    in real time or as a timelapse. The GPS timestamps of the video jitter
    about it

    >>> clock = VideoClock(video_time=2.0, unix_time=1000.0)
    >>> clock.to_video_time(1030.0)
    32.0
    >>> timelapse = VideoClock(video_time=2.0, unix_time=1000.0, rate=15.0)
    >>> timelapse.to_video_time(1030.0)
    4.0
    >>> timelapse.to_unix_time(4.0)
    1030.0
    """

    video_time: float
    unix_time: float
    # GPS seconds per video second: 1 unless the video is a timelapse
    rate: float = 1.0

    def to_video_time(self, unix_time: float) -> float:
        return self.video_time + (unix_time - self.unix_time) / self.rate

    def to_unix_time(self, video_time: float) -> float:
        return self.unix_time + (video_time - self.video_time) * self.rate


def _increasing_subsequence(
    pairs: T.Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    The longest subsequence of the (video time, Unix time) pairs whose Unix
    times increase

    >>> _increasing_subsequence([(0, 10), (1, 50), (2, 12), (3, 13), (4, 11)])
    [(0, 10), (2, 12), (3, 13)]
    >>> _increasing_subsequence([])
    []
    """
    # tails[k]: the index of the pair that ends the increasing subsequence of
    # length k + 1 with the smallest Unix time found so far
    tails: list[int] = []
    tail_unix_times: list[float] = []
    previous: list[int] = []
    for idx, (_, unix_time) in enumerate(pairs):
        k = bisect.bisect_left(tail_unix_times, unix_time)
        previous.append(tails[k - 1] if k else -1)
        if k == len(tails):
            tails.append(idx)
            tail_unix_times.append(unix_time)
        else:
            tails[k] = idx
            tail_unix_times[k] = unix_time

    subsequence: list[tuple[float, float]] = []
    idx = tails[-1] if tails else -1
    while 0 <= idx:
        subsequence.append(pairs[idx])
        idx = previous[idx]
    subsequence.reverse()
    return subsequence


class GPXVideoExtractor(BaseVideoExtractor):
    # The format of the track file, as messages name it
    file_format = "GPX"

    # The tracks of the track file, or the error reading it, once read_tracks()
    # has read them
    _tracks: list[list[geo.Point]] | exceptions.MapillaryInvalidGPXError | None = None

    def __init__(
        self,
        video_path: Path,
        gpx_path: Path,
        sync_mode: SyncMode = SyncMode.SYNC,
        video_sync: options.VideoSyncOption | None = None,
        interpolation: options.InterpolationOption | None = None,
        clip_to_video: bool = False,
    ):
        self.video_path = video_path
        self.gpx_path = gpx_path
        self.sync_mode = sync_mode
        self.video_sync = video_sync
        self.interpolation = interpolation
        # Clip the track to the video when a clock gives its pace along the
        # video (see _clip_to_video)
        self.clip_to_video = clip_to_video
        if interpolation is not None and interpolation.use_gpx_start_time:
            self.sync_mode = SyncMode.REBASE

    @override
    def extract(self) -> types.VideoMetadata:
        gpx_points = self._read_gpx_points()
        # The first and last Unix time of the track, before it is placed on
        # the timeline of the video
        gpx_unix_times = (
            (gpx_points[0].time, gpx_points[-1].time) if gpx_points else None
        )

        try:
            native_video_metadata, noisy = self._extract_native_video_metadata()
        except exceptions.MapillaryVideoGPSUnusableError as ex:
            # The GPX replaces the video's own GPS, so GPS that is missing,
            # empty or too noisy must not reject the video
            if self.sync_mode is SyncMode.STRICT_SYNC:
                raise ex
            start_clock = self._place_without_video_gps(gpx_points)
            rate = self._duration_ratio()
            self._apply_offset_time(gpx_points, rate=rate)
            self._check_coverage(gpx_points, gpx_unix_times, [], start_clock, rate)
            if self.clip_to_video:
                gpx_points = self._clip_to_video(gpx_points, start_clock, rate)
            return types.VideoMetadata(
                filename=self.video_path,
                filesize=utils.get_file_size(self.video_path),
                filetype=types.FileType.VIDEO,
                points=gpx_points,
            )

        video_clock = self._read_video_clock(native_video_metadata.points)
        clock = self._sync_clock(video_clock, gpx_points, noisy)
        if video_clock is not None and clock is None:
            LOG.warning(
                "The GPS clock of %s, whose GPS was rejected as noise, is %.1f days away from %s. "
                "Syncing the %s from the start of the video instead",
                self.video_path,
                abs(gpx_points[0].time - video_clock.to_unix_time(0)) / 86400,
                self.gpx_path,
                self.file_format,
            )
        if clock is not None and gpx_points and self.sync_mode is SyncMode.REBASE:
            # Distance sampling reads the frames by their composition times:
            # start the track at that of the first frame
            clock = dataclasses.replace(clock, video_time=self._gpx_start_video_time())

        if clock is None:
            # Its GPS has no clock to sync with, as if it had no GPS
            clock = self._place_without_video_gps(gpx_points)
            self._apply_offset_time(gpx_points, rate=self._duration_ratio())
        else:
            if self._duration_ratio() != 1.0:
                LOG.warning(
                    "Ignoring --video_duration_ratio %g for %s, whose own GPS clock runs at %.3gx",
                    self._duration_ratio(),
                    self.video_path,
                    clock.rate,
                )
            if self.video_sync is not None and self.video_sync.start_time is not None:
                LOG.warning(
                    "Ignoring --video_start_time %s for %s, which has a GPS clock of its own",
                    build_capture_time(self.video_sync.start_time),
                    self.video_path,
                )
            if clock.rate != 1.0:
                LOG.info(
                    "The GPS clock in %s runs %.3g times faster than the video. Syncing %s accordingly",
                    self.video_path,
                    clock.rate,
                    self.gpx_path,
                )
            # In GPS seconds, before the clock places the track
            self._apply_offset_time(gpx_points)
            for p in gpx_points:
                p.time = clock.to_video_time(p.time)

        rate = self._duration_ratio() if clock is None else clock.rate
        # Started with the video, the track is checked against it as one that
        # no clock placed: the clock gave it only its pace
        self._check_coverage(
            gpx_points,
            gpx_unix_times,
            native_video_metadata.points,
            None if self.sync_mode is SyncMode.REBASE else clock,
            rate,
        )
        if self.clip_to_video:
            gpx_points = self._clip_to_video(gpx_points, clock, rate)

        return dataclasses.replace(native_video_metadata, points=gpx_points)

    def read_tracks(self) -> None:
        """
        Read the tracks of the track file now, for extract() to place, rather
        than when it runs, which can be in another process: a file that
        geotags several videos is then read, and warned about, once
        """
        try:
            self._tracks = self._read_tracks()
        except exceptions.MapillaryInvalidGPXError as ex:
            self._tracks = ex
        except Exception:
            # Left for extract() to raise again, and to be reported for the
            # video as any unexpected error is
            pass
        else:
            self._warn_of_tracks(self._tracks)

    def _read_gpx_points(self) -> list[geo.Point]:
        """
        Read the points of the GPX file, merged into one track in time order
        """
        warned = self._tracks is not None
        gpx_tracks = self._parse_tracks()
        if not warned:
            self._warn_of_tracks(gpx_tracks)

        # Copies, which are moved to the video: the tracks may be shared with
        # other readers of the file
        gpx_points = [
            dataclasses.replace(p)
            for track in gpx_tracks
            for p in track
            if _GPS_EPOCH <= p.time
        ]

        # The tracks need not be in time order, and interpolation needs the
        # merged points to be
        gpx_points.sort(key=lambda p: p.time)
        return gpx_points

    def _warn_of_tracks(self, gpx_tracks: list[list[geo.Point]]) -> None:
        """
        Warn of what reading the points of the tracks leaves out or merges,
        once for each file
        """
        if 1 < len(gpx_tracks):
            geotag_utils.warn_once(
                self.gpx_path,
                ("tracks", len(gpx_tracks)),
                "Found %d tracks in the %s file %s. Will merge points in all the tracks as a single track for interpolation",
                len(gpx_tracks),
                self.file_format,
                self.gpx_path,
            )

        num_points = sum(len(track) for track in gpx_tracks)
        num_kept = sum(1 for track in gpx_tracks for p in track if _GPS_EPOCH <= p.time)
        if num_kept < num_points:
            geotag_utils.warn_once(
                self.gpx_path,
                ("before 1980", num_points - num_kept, num_points),
                "Ignoring %d of the %d points in the %s file %s, which are timestamped before 1980",
                num_points - num_kept,
                num_points,
                self.file_format,
                self.gpx_path,
            )

    def _parse_tracks(self) -> list[list[geo.Point]]:
        """
        The tracks of the track file, each a list of points with Unix times,
        as read_tracks() read them, or read now. They may be shared with other
        readers of the file, and must not be changed
        """
        if self._tracks is None:
            return self._read_tracks()
        if isinstance(self._tracks, exceptions.MapillaryInvalidGPXError):
            raise self._tracks
        return self._tracks

    def _read_tracks(self) -> list[list[geo.Point]]:
        """
        Read the tracks of the GPX file, parsed once in a process (see
        read_gpx_tracks())
        """
        try:
            return geotag_utils.read_gpx_tracks(self.gpx_path)
        except (OSError, UnicodeError, gpxpy.gpx.GPXException) as ex:
            raise exceptions.MapillaryInvalidGPXError(
                geotag_utils.describe_invalid_gpx(self.gpx_path, ex)
            ) from ex

    def _clip_to_video(
        self, gpx_points: list[geo.Point], clock: VideoClock | None, rate: float
    ) -> list[geo.Point]:
        """
        Clip a GPX track to the video, from video time 0 to where the video
        ends along it, which is known when a **clock** gives its pace along
        the video: the GPS clock of the video, which places the track too
        unless --interpolation_use_gpx_start_time starts it with the video, or
        the --video_start_time of sampling. Its points outside the video are
        the positions of none of its frames, and a GPX of a longer trip can
        run on for long after it.

        A track placed at the start of a video without a GPS clock, assumed to
        start with it or by --interpolation_use_gpx_start_time, is clipped
        only at video time 0, which --interpolation_offset_time may move it
        past, so that the first frames keep a position. Its end is left as it
        is: it may be that of a timelapse, which runs on past the end of the
        video at the pace of the GPS clock rather than that of the video.

        A gap of more than constants.MAX_GPX_GAP_SECONDS that video time 0, or
        the end of the video at **rate** GPS seconds per second, falls in says
        nothing of where the video was: the fixes on its far side are left
        out, with no point interpolated across it, as if the track started
        (or ended) there. One inside the video fails it (see _check_coverage).
        """
        video_duration = _video_duration(self.video_path)
        gpx_points = _leave_out_far_side_of_gaps(
            gpx_points, constants.MAX_GPX_GAP_SECONDS, video_duration, rate
        )
        if clock is None:
            return _clip_track(gpx_points, None)
        return _clip_track(gpx_points, video_duration)

    def _place_without_video_gps(
        self, gpx_points: T.Sequence[geo.Point]
    ) -> VideoClock | None:
        """
        Place the GPX track on the timeline of a video that has no GPS clock to
        sync it with: by the start time of the video, when sampling was given
        one, and otherwise by assuming that the track starts with the video. It
        runs at --video_duration_ratio GPS seconds per second of video.

        Return the clock of the video the track was placed by: the start time,
        or None if the track was assumed to start with the video.
        """
        if not gpx_points:
            return None

        ratio = self._duration_ratio()

        if self.sync_mode is SyncMode.SYNC and self.video_sync is not None:
            if self.video_sync.start_time is not None:
                self._rebase_times(
                    gpx_points,
                    offset=(gpx_points[0].time - self.video_sync.start_time) / ratio,
                    rate=ratio,
                )
                return VideoClock(
                    video_time=0.0, unix_time=self.video_sync.start_time, rate=ratio
                )
            self._check_assumed_start(gpx_points, ratio)
        elif self.sync_mode is SyncMode.REBASE and self.video_sync is not None:
            self._check_given_start(gpx_points, ratio)
            self._rebase_times(
                gpx_points, offset=self._gpx_start_video_time(), rate=ratio
            )
            return None
        elif self.sync_mode is SyncMode.SYNC:
            self._warn_of_a_long_track(gpx_points)

        self._rebase_times(gpx_points, rate=ratio)
        return None

    def _gpx_start_video_time(self) -> float:
        """
        The video time that --interpolation_use_gpx_start_time starts the GPX
        track at. The geotagging stage of video_process puts the start of the
        track at the first sample, which is the first frame, so distance
        sampling starts the track at the first frame too: by its composition
        time, which distance sampling reads the frames by, and which is not 0
        in a video with B-frames. In process, the track starts at 0 as before,
        and so it does in interval sampling, which ffmpeg cuts from time 0.
        """
        if self.video_sync is None:
            return 0.0
        return _first_frame_time(self.video_path)

    def _duration_ratio(self) -> float:
        """
        GPS seconds per second of a video without a GPS clock of its own to
        tell, from --video_duration_ratio: more than 1 for a timelapse
        """
        if self.video_sync is None:
            return 1.0
        return self.video_sync.duration_ratio

    def _apply_offset_time(
        self, gpx_points: T.Sequence[geo.Point], rate: float = 1.0
    ) -> None:
        """
        Shift the track back by --interpolation_offset_time, which is added to
        the capture time of a frame to find its position along the GPX. The
        offset is in GPS seconds, of which a timelapse packs **rate** into each
        second of video.

        The absolute times stay those of the GPX, just as an image geotagged
        with the offset takes the time of its position along the GPX. When
        sampling, they shift with the track, so that a frame is stamped with
        its capture time, and the geotagging stage, adding the offset back,
        finds the position the frame was picked by.
        """
        if self.interpolation is None or not self.interpolation.offset_time:
            return

        offset_time = self.interpolation.offset_time
        for p in gpx_points:
            p.time -= offset_time / rate
            # parse_gpx() returns CAMMGPSPoint, with epoch_time 0 for no time
            if (
                self.video_sync is not None
                and isinstance(p, telemetry.CAMMGPSPoint)
                and 0 < p.epoch_time
            ):
                p.epoch_time -= offset_time

    def _check_coverage(
        self,
        gpx_points: T.Sequence[geo.Point],
        gpx_unix_times: tuple[float, float] | None,
        video_gps_points: T.Sequence[geo.Point],
        clock: VideoClock | None,
        rate: float,
    ) -> None:
        """
        Check the GPX track, as placed on the timeline of the video, against
        the video, from video time 0 to its mvhd duration. Each second of video
        spans **rate** GPS seconds.

        A track that misses the video has no position for any moment of it, so
        it raises when its placement says so: the clock it was placed by, or
        --interpolation_offset_time. A track that covers only part of the video
        warns, and one that covers all of it is silent. The video can fall
        between the ends of the track and still miss it, or part of it, in a
        gap of more than constants.MAX_GPX_GAP_SECONDS between two of its
        points. In process, which uploads the track with the video, a gap
        inside the video raises too: sampling leaves out the frames in it,
        while the track would be interpolated across it.

        Without the duration of the video, the video is known only up to its
        last GPS point, and a track that starts after it may still overlap the
        video. Then a gap only warns, unless it is too large for any clock or
        time zone mistake to explain. A track placed at the start of the video,
        whether assumed to start with it or by --interpolation_use_gpx_start_time,
        can miss it only once --interpolation_offset_time moves it.
        """
        if not gpx_points or gpx_unix_times is None:
            return

        video_duration = _video_duration(self.video_path)
        video_end = max((p.time for p in video_gps_points), default=0.0)
        if video_duration is not None:
            video_end = max(video_end, video_duration)
        if video_end <= 0:
            return

        gpx_first = min(p.time for p in gpx_points)
        gpx_last = max(p.time for p in gpx_points)
        # The gaps of the track, and its parts between them, in video seconds
        gap_points = track_gaps(
            sorted(gpx_points, key=lambda p: p.time),
            constants.MAX_GPX_GAP_SECONDS,
            rate,
        )
        gaps = [(before.time, after.time) for before, after in gap_points]
        parts = list(
            zip(
                [gpx_first, *(end for _, end in gaps)],
                [*(start for start, _ in gaps), gpx_last],
            )
        )
        offset_time = (
            0.0 if self.interpolation is None else self.interpolation.offset_time
        )

        # Where the start of the video is looked up along the track, in its
        # Unix time: the offset is added to the time of every frame, as it is
        # to the capture time of an image
        lookup_start = (
            gpx_unix_times[0] if clock is None else clock.to_unix_time(0)
        ) + offset_time

        gpx_track = f"The {self.file_format} track in {self.gpx_path} ({_isoformat(gpx_unix_times[0])} to {_isoformat(gpx_unix_times[1])})"
        if clock is None:
            video = f"the video {self.video_path}"
        else:
            video = f"the video {self.video_path} ({_isoformat(clock.to_unix_time(0))} to {_isoformat(clock.to_unix_time(video_end))})"
        # Without it, the times of the video read as if the track missed it
        # by more or less than it does
        offset_clause = ""
        if offset_time:
            offset_clause = (
                f", as --interpolation_offset_time {offset_time:g} looks the video up along it "
                f"({_isoformat(lookup_start)} to {_isoformat(lookup_start + video_end * rate)})"
            )

        # In GPS seconds, which is where clock and time zone mistakes are made
        gap = min(max(first - video_end, -last) for first, last in parts) * rate
        if clock is None:
            # Placed at the start of the video, only the offset moved it off
            advice = "Check --interpolation_offset_time"
        elif offset_time:
            advice = (
                f"Check --interpolation_offset_time, that the {self.file_format} file belongs to "
                f"this video, then the camera clock and the time zone of the {self.file_format} "
                "timestamps"
            )
        else:
            advice = (
                f"Check that the {self.file_format} file belongs to this video, then the camera "
                f"clock and the time zone of the {self.file_format} timestamps"
            )

        if gap <= 0 and self.clip_to_video:
            # process uploads the track with the video, and its frames would be
            # placed along it across a gap that the video spans, which says
            # nothing of where the video was. Sampling leaves out the frames
            # in it (see _clip_to_video for the gaps at its ends)
            for before, after in gap_points:
                if before.time <= 0 and video_end <= after.time:
                    # The track touches the video at an instant at one end only
                    where = f"which {video} falls in{offset_clause}"
                    if clock is not None or offset_time:
                        where_advice = advice
                    elif self.sync_mode is SyncMode.REBASE:
                        # Said to start with the video
                        where_advice = f"Trim the {self.file_format} to the video"
                    else:
                        # Assumed to start with the video
                        where_advice = (
                            f"Trim the {self.file_format} to the video, or sample the video "
                            "with video_process and --video_start_time"
                        )
                elif 0 <= before.time and after.time <= video_end:
                    where = (
                        f"inside {video}{offset_clause}, which says nothing of where "
                        "the video was in it"
                    )
                    where_advice = (
                        "Sample the video with video_process and --video_geotag_source "
                        f"{self.file_format.lower()}, which leaves out the frames in the gap"
                    )
                else:
                    continue
                # At the Unix times the points were recorded at
                track_gap = describe_gap(
                    before,
                    after,
                    lookup_start + before.time * rate,
                    lookup_start + after.time * rate,
                )
                raise exceptions.MapillaryOutsideGPXTrackError(
                    f"{gpx_track} has {track_gap}, {where}. {where_advice}",
                    image_time=build_capture_time(lookup_start),
                    gpx_start_time=build_capture_time(gpx_unix_times[0]),
                    gpx_end_time=build_capture_time(gpx_unix_times[1]),
                )

        if gap <= 0:
            # In video seconds
            uncovered = (
                max(gpx_first, 0.0)
                + max(video_end - gpx_last, 0.0)
                + sum(
                    max(min(end, video_end) - max(start, 0.0), 0.0)
                    for start, end in gaps
                )
            )
            if _LOGGER_TOLERANCE_SECONDS < uncovered * rate:
                LOG.warning(
                    f"{gpx_track} covers only part of {video}{offset_clause}: "
                    f"{_format_duration(uncovered)} of the video fall outside the track"
                )
            return

        # Between the ends of the track, the video falls in one of its gaps
        surrounding_gap = next(
            (
                (before, after)
                for before, after in gap_points
                if before.time < 0 and video_end < after.time
            ),
            None,
        )
        if surrounding_gap is None:
            message = (
                f"{gpx_track} misses {video} by {_format_duration(gap)}{offset_clause}. "
                f"{advice}"
            )
        else:
            before, after = surrounding_gap
            # At the Unix times the points were recorded at
            track_gap = describe_gap(
                before,
                after,
                lookup_start + before.time * rate,
                lookup_start + after.time * rate,
            )
            message = (
                f"{gpx_track} has {track_gap}, which {video} falls in{offset_clause}. "
                f"{advice}"
            )

        if (clock is not None or offset_time) and (
            video_duration is not None or _IMPLAUSIBLE_OFFSET_SECONDS < gap
        ):
            raise exceptions.MapillaryOutsideGPXTrackError(
                message,
                image_time=build_capture_time(lookup_start),
                gpx_start_time=build_capture_time(gpx_unix_times[0]),
                gpx_end_time=build_capture_time(gpx_unix_times[1]),
            )

        LOG.warning(message)

    def _check_assumed_start(
        self, gpx_points: T.Sequence[geo.Point], ratio: float
    ) -> None:
        """
        Check that the GPX track can have started with the video, as it is
        assumed to when nothing says when the video starts. The video spans
        **ratio** GPS seconds per second.

        A track that runs on for longer than the whole video was not recorded
        for the video alone, and the video could start anywhere along it: raise.
        One that runs on for less may have been started a little before the
        video, which puts every frame up to that much too early along it: warn.
        """
        durations = self._durations(gpx_points, ratio)
        if durations is None:
            return

        video_span, gpx_duration = durations
        excess = gpx_duration - video_span

        if video_span < excess:
            message = (
                f"The {self.file_format} track in {self.gpx_path} lasts {_format_duration(gpx_duration)} "
                f"and {self._describe_video_span(video_span, ratio)}, so the video "
                "could start anywhere along the track. "
            )
            # Not --interpolation_use_gpx_start_time, which starts the track
            # with the video too, and refuses it for the same reason
            if gpx_duration < _MAX_RECORDING_SECONDS:
                message += (
                    "If the video is a timelapse, specify --video_duration_ratio. If "
                    "the GPS logger was started with the video and left running, "
                    "specify --video_start_time "
                    f"{build_capture_time(min(p.time for p in gpx_points))}, when the "
                    "track starts. If the track covers more than this video, specify "
                    "the time the video started as --video_start_time instead"
                )
            else:
                message += (
                    "A track that long covers more than this video: specify the time "
                    "the video started as --video_start_time"
                )
            raise exceptions.MapillaryGPXVideoStartUnknownError(message)

        if _LOGGER_TOLERANCE_SECONDS < excess:
            LOG.warning(
                "Assuming that the %s track in %s starts with the video %s, although "
                "the track lasts %s longer. If it was started first, the frames are "
                "placed up to that much too early along it. Specify --video_start_time "
                "to place them exactly, or --interpolation_use_gpx_start_time if the "
                "track was started with the video",
                self.file_format,
                self.gpx_path,
                self.video_path,
                _format_duration(excess),
            )

    def _check_given_start(
        self, gpx_points: T.Sequence[geo.Point], ratio: float
    ) -> None:
        """
        Check a GPX track that --interpolation_use_gpx_start_time says started
        with the video, which spans **ratio** GPS seconds per second. A track
        that runs on for longer than the whole video was not recorded for it
        alone, or belongs to a timelapse, whose rate nothing gives: raise.
        """
        durations = self._durations(gpx_points, ratio)
        if durations is None:
            return

        video_span, gpx_duration = durations
        if gpx_duration - video_span <= video_span:
            return

        message = (
            f"The {self.file_format} track in {self.gpx_path} lasts {_format_duration(gpx_duration)} "
            f"and {self._describe_video_span(video_span, ratio)}, so it runs on long "
            "after the video ends. "
        )
        if gpx_duration < _MAX_RECORDING_SECONDS:
            # The start of the track is the start of the video only if the
            # track is that of the one recording
            message += (
                "If the video is a timelapse, specify --video_duration_ratio. If the "
                "GPS logger was started with the video and left running, specify "
                f"--video_start_time {build_capture_time(min(p.time for p in gpx_points))}, "
                "when the track starts, instead of --interpolation_use_gpx_start_time. "
                "If the track covers more than this video, specify the time the video "
                "started as --video_start_time instead"
            )
        else:
            message += (
                "A track that long covers more than this video: specify the time the "
                "video started as --video_start_time instead of "
                "--interpolation_use_gpx_start_time"
            )
        raise exceptions.MapillaryGPXVideoStartUnknownError(message)

    def _describe_video_span(self, video_span: float, ratio: float) -> str:
        """
        >>> extractor = GPXVideoExtractor(Path("a.mp4"), Path("a.gpx"))
        >>> extractor._describe_video_span(5, 1)
        'the video only 5 seconds'
        >>> extractor._describe_video_span(120, 60)
        'the video only 2 seconds, which at --video_duration_ratio 60 span 2.0 minutes'
        """
        description = f"the video only {_format_duration(video_span / ratio)}"
        if ratio != 1.0:
            description += (
                f", which at --video_duration_ratio {ratio:g} span "
                f"{_format_duration(video_span)}"
            )
        return description

    def _durations(
        self, gpx_points: T.Sequence[geo.Point], ratio: float
    ) -> tuple[float, float] | None:
        """
        The GPS seconds that the video spans at **ratio** GPS seconds per
        second, and the duration of the GPX track, or None if the duration of
        the video cannot be read
        """
        video_duration = _video_duration(self.video_path)
        if video_duration is None:
            LOG.debug(
                "Unable to read the duration of %s to check the GPX track against",
                self.video_path,
            )
            return None

        gpx_duration = max(p.time for p in gpx_points) - min(p.time for p in gpx_points)
        return video_duration * ratio, gpx_duration

    def _sync_clock(
        self,
        clock: VideoClock | None,
        gpx_points: T.Sequence[geo.Point],
        noisy: bool,
    ) -> VideoClock | None:
        """
        The clock to place the GPX track by along the video, from the GPS
        clock of the video (None if it has none), whose GPS was rejected as
        noise if **noisy**. Return None if the track is to be placed as for a
        video without a GPS clock. --interpolation_use_gpx_start_time starts
        the track at video time 0.
        """
        if clock is None or not gpx_points:
            return clock

        if self.sync_mode is SyncMode.REBASE:
            # The GPX is placed to start with the video, and runs on at the rate
            # of the video's GPS clock, which in a timelapse packs several GPS
            # seconds into each second of video
            return VideoClock(
                video_time=0.0, unix_time=gpx_points[0].time, rate=clock.rate
            )

        # GPS rejected as noise may not have GPS time yet: GoPro stamps a
        # placeholder date until it acquires it. That GPS is what the GPX
        # replaces, so do not let a placeholder clock place the GPX days away
        # from the video. A clock that agrees with the creation time of the
        # video is no placeholder: it places the GPX as for any video with GPS,
        # and a GPX days away from it misses the video
        offset = gpx_points[0].time - clock.to_unix_time(0)
        if (
            abs(offset) > _IMPLAUSIBLE_OFFSET_SECONDS
            and noisy
            and self.sync_mode is SyncMode.SYNC
            and not self._clock_matches_creation_time(clock)
        ):
            return None

        return clock

    def _clock_matches_creation_time(self, clock: VideoClock) -> bool:
        """
        Whether the GPS clock of the video starts within a day of the mvhd
        creation time of the video, or False if that cannot be read.

        A day absorbs any time zone the creation time is written in (GoPro
        writes local time), and whether it marks the start or the end of the
        recording. Some cameras write a creation time that means nothing (a
        GoPro HERO10 recorded in 2022 reports 2016-01-01), so a clock that does
        not match it may still be real.
        """
        creation_time = _video_creation_time(self.video_path)
        if creation_time is None:
            return False
        gap = abs(clock.to_unix_time(0) - creation_time)
        return gap <= _IMPLAUSIBLE_OFFSET_SECONDS

    def _warn_of_a_long_track(self, gpx_points: T.Sequence[geo.Point]) -> None:
        """
        Warn, in process, of a GPX track assumed to start with the video that
        runs on for longer than the whole video, which sampling refuses (see
        _check_assumed_start): the video could start anywhere along it. Only
        warn, since the track of a timelapse without a GPS clock of its own
        runs on past the end of the video too.

        With --interpolation_offset_time, it is the offset that places the
        video along the track, and one way to place it right.
        """
        track = describe_long_track(
            f"The {self.file_format} track in {self.gpx_path}",
            gpx_points,
            self.video_path,
        )
        if track is None:
            return

        gpx_start = min(p.time for p in gpx_points)
        offset_time = (
            0.0 if self.interpolation is None else self.interpolation.offset_time
        )
        if offset_time:
            LOG.warning(
                f"{track}, and --interpolation_offset_time {offset_time:g} places its "
                f"start at {_isoformat(gpx_start + offset_time)} along it. Unless the "
                "video is a timelapse of the track from there, check that the offset "
                f"is where the video starts along the track, trim the {self.file_format} to the "
                "video, or sample the video with video_process and --video_start_time"
            )
        else:
            LOG.warning(
                f"{track}, and is assumed to start with it. Unless the video is a "
                f"timelapse of the whole track, trim the {self.file_format} to the video, or sample "
                "the video with video_process and --video_start_time"
            )

    def _extract_native_video_metadata(self) -> tuple[types.VideoMetadata, bool]:
        """
        Extract the video metadata, and whether its GPS was rejected as noise
        """
        try:
            return NativeVideoExtractor(self.video_path).extract(), False
        except exceptions.MapillaryGPSNoiseError:
            # The GPX replaces the video's own GPS, which is then only needed
            # for make/model and a clock to sync against. Noisy points are
            # never published
            metadata = NativeVideoExtractor(
                self.video_path, filter_noisy_points=False
            ).extract()
            return metadata, True

    @classmethod
    def _rebase_times(
        cls, points: T.Sequence[geo.Point], offset: float = 0.0, rate: float = 1.0
    ) -> None:
        """
        Rebase point times to start from **offset**, at **rate** of their
        seconds per second
        """
        if points:
            first_timestamp = points[0].time
            for p in points:
                p.time = (p.time - first_timestamp) / rate + offset

    @classmethod
    def _read_video_clock(
        cls, video_gps_points: T.Sequence[geo.Point]
    ) -> VideoClock | None:
        """
        Read the GPS clock from the video GPS points, or None if they have no
        timestamps: the straight line that their timestamps fit, at 1x unless
        they measure a pace off it. The fit assumes that the clock runs at a
        steady pace, as the camera records its frames: a step of the clock, or
        a GPS dropout that it does not recover from, leaves the timestamps off
        any line

        >>> GPXVideoExtractor._read_video_clock([]) is None
        True
        >>> point = geo.Point(time=5, lat=1, lon=1, alt=None, angle=None)
        >>> GPXVideoExtractor._read_video_clock([point]) is None
        True
        """
        pairs = cls._read_timestamps(video_gps_points)
        if not pairs:
            return None

        rate = cls._estimate_clock_rate(pairs)
        if rate is None or abs(rate - 1.0) <= max(
            _MAX_CLOCK_RATE_ERROR,
            _MAX_CLOCK_DRIFT_SECONDS / (pairs[-1][0] - pairs[0][0]),
        ):
            # See _MAX_CLOCK_RATE_ERROR and _MAX_CLOCK_DRIFT_SECONDS
            rate = 1.0
        elif _MIN_TIMELAPSE_RATE < rate:
            # A timelapse must show in the steps between neighbouring pairs
            # too: in their median, which is too coarse to measure the rate, but
            # not to tell a timelapse from a normal video. Not in one step, nor
            # in one of two: where a GPS stamps a fix seconds late, a few
            # seconds of a video that records in real time can hold only 3
            # timestamps, which measure 3.5x or 4x
            steps = cls._step_rates(pairs)
            if (
                len(steps) < 2
                or (min(steps) if len(steps) == 2 else statistics.median(steps))
                <= _MIN_TIMELAPSE_RATE
            ):
                rate = 1.0
        elif (
            min(pairs[-1][0] - pairs[0][0], pairs[-1][1] - pairs[0][1])
            < _MIN_CLOCK_SPAN_SECONDS
        ):
            # See _MIN_CLOCK_SPAN_SECONDS
            rate = 1.0

        # Anchored at its own video time, which is not 0 when the video's GPS
        # starts late (e.g. GoPro drops noisy fixes at the start of a recording),
        # and at the median of all its timestamps mapped back to that time, not
        # at the first alone: GPS clocks jitter by a second or so against the
        # video, and a PANOX V2 stamps some fixes seconds late
        video_time = pairs[0][0]
        unix_time = statistics.median(u - (v - video_time) * rate for v, u in pairs)

        return VideoClock(video_time=video_time, unix_time=unix_time, rate=rate)

    @classmethod
    def _read_timestamps(
        cls, video_gps_points: T.Sequence[geo.Point]
    ) -> list[tuple[float, float]]:
        """
        Read the (video time, Unix time) pairs of the GPS timestamps of the
        points, leaving out those that the others show to be wrong: those out
        of order, those before a jump of days (from a placeholder date to the
        GPS time), and stale first ones

        >>> points = [
        ...     telemetry.GPSPoint(time=v, lat=1, lon=1, alt=None, angle=None, epoch_time=u, fix=None, precision=None, ground_speed=None)
        ...     for v, u in [(0, 992.4), (0.4, 1000.4), (1.4, 1001.4), (1.8, 1001.4), (2.4, 1002.4)]
        ... ]
        >>> GPXVideoExtractor._read_timestamps(points)
        [(0.4, 1000.4), (1.4, 1001.4), (2.4, 1002.4)]
        """
        pairs: list[tuple[float, float]] = []
        for p in video_gps_points:
            # Video GPS timestamps are stored in whatever epoch their container
            # uses (CAMM records GPS time, GoPro records Unix time), so go
            # through get_unix_time(), which also skips zero/invalid timestamps
            unix_time = p.get_unix_time()
            if unix_time is None:
                continue
            if pairs and unix_time == pairs[-1][1]:
                # GoPro GPS5 stamps a whole block (~1s) of points with one
                # timestamp. Keep the first point of the block
                continue
            if pairs and p.time <= pairs[-1][0]:
                # Two timestamps at one video time
                continue
            pairs.append((p.time, unix_time))

        # A timestamp out of order with the others is wrong
        pairs = _increasing_subsequence(pairs)

        pace = cls._median_step_rate(pairs)
        if pace is None:
            return pairs

        # GoPro stamps a placeholder date until the GPS acquires the time
        start = 0
        for idx in range(1, len(pairs)):
            (v0, u0), (v1, u1) = pairs[idx - 1], pairs[idx]
            if _IMPLAUSIBLE_OFFSET_SECONDS < (u1 - u0) - (v1 - v0) * pace:
                start = idx

        # Stale first timestamps (see _STALE_STEP_RATE). Judged by the steps of
        # the rest: the rate is fitted to the timestamps that are left
        pace = cls._median_step_rate(pairs[start + 1 :])
        while pace is not None and start + 1 < len(pairs):
            (v0, u0), (v1, u1) = pairs[start], pairs[start + 1]
            if (u1 - u0) <= (v1 - v0) * pace * _STALE_STEP_RATE:
                break
            start += 1

        return pairs[start:]

    @classmethod
    def _estimate_clock_rate(
        cls, pairs: T.Sequence[tuple[float, float]]
    ) -> float | None:
        """
        The slope of the Unix time over the video time: the median of the slopes
        between pairs of the pairs (the Theil-Sen estimator), of an evenly
        spaced selection of them if there are many (see _MAX_RATE_TIMESTAMPS).
        None without two pairs at different video times

        >>> GPXVideoExtractor._estimate_clock_rate([(0, 100), (1, 115), (2, 130)])
        15.0
        >>> GPXVideoExtractor._estimate_clock_rate([(0, 100)]) is None
        True

        One timestamp far off the rest does not move it:

        >>> GPXVideoExtractor._estimate_clock_rate([(i, 100 + i) for i in range(9)] + [(9, 130)])
        1.0
        """
        if len(pairs) > _MAX_RATE_TIMESTAMPS:
            last = len(pairs) - 1
            pairs = [
                pairs[round(idx * last / (_MAX_RATE_TIMESTAMPS - 1))]
                for idx in range(_MAX_RATE_TIMESTAMPS)
            ]

        slopes = [
            (u2 - u1) / (v2 - v1)
            for idx, (v1, u1) in enumerate(pairs)
            for v2, u2 in pairs[idx + 1 :]
            if v1 < v2
        ]
        return statistics.median(slopes) if slopes else None

    @classmethod
    def _median_step_rate(cls, pairs: T.Sequence[tuple[float, float]]) -> float | None:
        """
        Median rate of the GPS clock between neighbouring pairs, or None if
        there are none

        >>> pairs = [(0, 100), (1, 101), (2, 102), (3, 140), (4, 141)]
        >>> GPXVideoExtractor._median_step_rate(pairs)
        1.0
        """
        steps = cls._step_rates(pairs)
        return statistics.median(steps) if steps else None

    @classmethod
    def _step_rates(cls, pairs: T.Sequence[tuple[float, float]]) -> list[float]:
        """
        The rates of the GPS clock between neighbouring pairs

        >>> GPXVideoExtractor._step_rates([(0, 100), (1, 101), (1.5, 104)])
        [1.0, 6.0]
        """
        return [
            (u2 - u1) / (v2 - v1)
            for (v1, u1), (v2, u2) in zip(pairs, pairs[1:])
            if v1 < v2
        ]


def track_gaps(
    points: T.Sequence[geo.Point], max_gap: float, rate: float = 1.0
) -> list[tuple[geo.Point, geo.Point]]:
    """
    The gaps of a track, sorted by time, between consecutive points more than
    **max_gap** GPS seconds apart (see gps_seconds_apart()), as the points
    either side

    >>> track = [geo.Point(time=t, lat=0, lon=0, alt=None, angle=None) for t in (0, 1, 5000, 5001, 9000)]
    >>> [(before.time, after.time) for before, after in track_gaps(track, 3600)]
    [(1, 5000), (5001, 9000)]
    >>> [(before.time, after.time) for before, after in track_gaps(track, 4000)]
    [(1, 5000)]
    >>> track_gaps(track[:2], 3600)
    []

    A gap of exactly **max_gap** is none, also along a video whose clock runs
    at another rate than 1:

    >>> placed = [geo.Point(time=t / 1.1426, lat=0, lon=0, alt=None, angle=None) for t in (0, 3600)]
    >>> track_gaps(placed, 3600, rate=1.1426)
    []
    """
    return [
        (left, right)
        for left, right in geo.pairwise(points)
        if max_gap < gps_seconds_apart(left, right, rate)
    ]


def gps_seconds_apart(left: geo.Point, right: geo.Point, rate: float = 1.0) -> float:
    """
    The GPS seconds between two points of a track: those between the GPS
    times they keep, where both keep one, and otherwise between their times
    at **rate** GPS seconds per second of their time, as a track placed along
    a timelapse packs several GPS seconds into each second of video. Rounded to
    the millisecond, which no GPS time is recorded more finely than, so that
    neither a division by the rate nor a fractional timestamp makes a gap of
    exactly the limit more than it

    >>> p = lambda t: geo.Point(time=t, lat=0, lon=0, alt=None, angle=None)
    >>> gps_seconds_apart(p(1.0), p(3.5), rate=2.0)
    5.0
    >>> gps_seconds_apart(p(0), p(3600 / 1.1426), rate=1.1426)
    3600.0
    """
    left_time, right_time = left.get_unix_time(), right.get_unix_time()
    if left_time is None or right_time is None:
        seconds = (right.time - left.time) * rate
    else:
        seconds = right_time - left_time
    return round(seconds, 3)


def describe_gap(
    before: geo.Point, after: geo.Point, before_time: float, after_time: float
) -> str:
    """
    Describe a gap of a track between the points **before** and **after**,
    which were recorded at the Unix times **before_time** and **after_time**

    >>> p = lambda lat, lon: geo.Point(time=0, lat=lat, lon=lon, alt=None, angle=None)
    >>> describe_gap(p(55.174859, 61.256901), p(55.172986, 61.256636), 1739074271, 1739124451)
    'a gap of 13.9 hours, from 2025-02-09T04:11:11+00:00 at (55.174859, 61.256901) to 2025-02-09T18:07:31+00:00 at (55.172986, 61.256636)'
    """
    return (
        f"a gap of {_format_duration(after_time - before_time)}, "
        f"from {_isoformat(before_time)} at ({round(before.lat, 7)}, {round(before.lon, 7)}) "
        f"to {_isoformat(after_time)} at ({round(after.lat, 7)}, {round(after.lon, 7)})"
    )


def describe_long_track(
    track_name: str, points: T.Sequence[geo.Point], video_path: Path
) -> str | None:
    """
    Describe a track, named **track_name**, that lasts more than twice as long
    as the video it is assumed to start with, which could then start anywhere
    along it; or None if it does not, or if the duration of the video cannot
    be read
    """
    video_duration = _video_duration(video_path)
    if video_duration is None or not points:
        return None

    track_duration = max(p.time for p in points) - min(p.time for p in points)
    if track_duration <= 2 * video_duration:
        return None

    return (
        f"{track_name} lasts {_format_duration(track_duration)} "
        f"and the video {video_path} only {_format_duration(video_duration)}, "
        "so the video could start anywhere along the track"
    )


def _leave_out_far_side_of_gaps(
    points: T.Sequence[geo.Point],
    max_gap: float,
    end: float | None,
    rate: float = 1.0,
) -> list[geo.Point]:
    """
    Leave out of a track, sorted by time, the points on the far side of a gap
    of more than **max_gap** GPS seconds (see gps_seconds_apart()) that time 0,
    or **end** (None if unknown), falls in

    >>> track = [geo.Point(time=t, lat=t, lon=0, alt=None, angle=None) for t in (-9000, 99, 200, 9000)]
    >>> [p.time for p in _leave_out_far_side_of_gaps(track, 3600, 300)]
    [99, 200]
    >>> [p.time for p in _leave_out_far_side_of_gaps(track, 3600, None)]
    [99, 200, 9000]
    >>> [p.time for p in _leave_out_far_side_of_gaps(track, 10000, 300)]
    [-9000, 99, 200, 9000]
    """
    start, stop = 0, len(points)
    for idx, (before, after) in enumerate(geo.pairwise(points)):
        if gps_seconds_apart(before, after, rate) <= max_gap:
            continue
        if before.time < 0 < after.time:
            start = idx + 1
        if end is not None and before.time < end < after.time:
            stop = idx + 1
    return list(points[start:stop])


def _clip_track(
    points: T.Sequence[geo.Point], duration: float | None
) -> list[geo.Point]:
    """
    Clip a track, sorted by time, to the video, from time 0 to duration (None
    if unknown), with a point interpolated at either end that the track runs
    past, so that the frames up to that end keep their position

    >>> track = [geo.Point(time=t, lat=t, lon=0, alt=None, angle=None) for t in (-2, 2, 6, 10)]
    >>> [(p.time, p.lat) for p in _clip_track(track, 8.0)]
    [(0.0, 0.0), (2, 2), (6, 6), (8.0, 8.0)]
    >>> [p.time for p in _clip_track(track, None)]
    [0.0, 2, 6, 10]
    >>> [p.time for p in _clip_track(track, 10.0)]
    [0.0, 2, 6, 10]
    >>> _clip_track(track[:1], 8.0)
    []
    """
    if not points:
        return []

    end = math.inf if duration is None else duration
    clipped = [p for p in points if 0 <= p.time <= end]
    if points[0].time < 0 < points[-1].time and (not clipped or 0 < clipped[0].time):
        clipped.insert(0, geo.interpolate(points, 0.0))
    if points[0].time < end < points[-1].time and clipped[-1].time < end:
        clipped.append(geo.interpolate(points, end))
    return clipped


def _video_duration(video_path: Path) -> float | None:
    """
    The duration of the video in seconds, from its mvhd box, or None if it
    cannot be read.
    """
    try:
        with video_path.open("rb") as fp:
            data = sparser.parse_box_data_first(fp, [b"moov", b"mvhd"])
        if data is None:
            return None
        mvhd = cparser.MovieHeaderBox.parse(data)
    except (OSError, sparser.ParsingError, C.ConstructError) as ex:
        LOG.debug("Failed to read the duration of %s: %s", video_path, ex)
        return None

    # All 1s means the duration is unknown
    if not mvhd.timescale or mvhd.duration in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
        return None

    return mvhd.duration / mvhd.timescale


def _first_frame_time(video_path: Path) -> float:
    """
    The composition time of the first frame of the video stream with the
    highest resolution, which distance sampling samples by, or 0 if it cannot
    be read
    """
    try:
        moov = MovieBoxParser.parse_file(video_path)
        video_tracks = [
            track for track in moov.extract_tracks() if track.is_video_track()
        ]
        if not video_tracks:
            return 0.0
        # As ffprobe picks the stream to sample: the first of the largest
        track = max(
            video_tracks,
            key=lambda track: (
                track.extract_tkhd_boxdata()["width"]
                * track.extract_tkhd_boxdata()["height"]
            ),
        )
        return min(
            (sample.exact_composition_time for sample in track.extract_samples()),
            default=0.0,
        )
    except (
        OSError,
        sparser.ParsingError,
        cparser.BoxNotFoundError,
        C.ConstructError,
    ) as ex:
        LOG.debug("Failed to read the first frame time of %s: %s", video_path, ex)
        return 0.0


def _video_creation_time(video_path: Path) -> float | None:
    """
    The creation time of the video as Unix time, from its mvhd box, or None if
    it is unset or cannot be read.
    """
    try:
        moov = MovieBoxParser.parse_file(video_path)
    except (OSError, sparser.ParsingError, C.ConstructError) as ex:
        LOG.debug("Failed to read the creation time of %s: %s", video_path, ex)
        return None
    return camm_parser._extract_creation_time(moov)


def _format_duration(seconds: float) -> str:
    """
    Format a duration in the largest unit it fills, rounded rather than
    truncated, since timestamps often fall a hair short of a whole unit

    >>> _format_duration(0.089)
    '0.089 seconds'
    >>> _format_duration(1)
    '1 second'
    >>> _format_duration(4.9991)
    '5 seconds'
    >>> _format_duration(90)
    '1.5 minutes'
    >>> _format_duration(7199.999)
    '2.0 hours'
    >>> _format_duration(43474)
    '12.1 hours'
    >>> _format_duration(3 * 86400 - 0.001)
    '3.0 days'
    """
    for unit, size in (("days", 86400), ("hours", 3600), ("minutes", 60)):
        if seconds >= size:
            return f"{seconds / size:.1f} {unit}"
    # Significant digits, so that a gap under a second does not read as 0
    text = f"{seconds:.3g}"
    return f"{text} second" if text == "1" else f"{text} seconds"


def _isoformat(unix_time: float) -> str:
    return datetime.datetime.fromtimestamp(
        unix_time, tz=datetime.timezone.utc
    ).isoformat()
