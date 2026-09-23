# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import dataclasses
import datetime
import enum
import logging
import sys
import typing as T
from pathlib import Path

import construct as C

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import exceptions, geo, types, utils
from ...mp4 import construct_mp4_parser as cparser, simple_mp4_parser as sparser
from ...serializer.description import build_capture_time
from ..utils import parse_gpx
from .base import BaseVideoExtractor
from .native import NativeVideoExtractor


LOG = logging.getLogger(__name__)

# When the duration of the video is unknown, a GPX track that misses the
# video's GPS by more than this cannot belong to it. No camera clock or time
# zone mistake comes close, while an epoch mix-up exceeds it by orders of
# magnitude.
_IMPLAUSIBLE_GAP_SECONDS = 24 * 3600

# How much of the video a GPX track may leave uncovered without a warning. A
# logger that records whole seconds once a second, started and stopped with
# the camera, can leave a second at each end.
_UNCOVERED_TOLERANCE_SECONDS = 2.0


class SyncMode(enum.Enum):
    # Sync by video GPS timestamps if found, otherwise rebase
    SYNC = "sync"
    # Sync by video GPS timestamps, and throw if not found
    STRICT_SYNC = "strict_sync"
    # Rebase all GPX timestamps to start from 0
    REBASE = "rebase"


class GPXVideoExtractor(BaseVideoExtractor):
    def __init__(
        self, video_path: Path, gpx_path: Path, sync_mode: SyncMode = SyncMode.SYNC
    ):
        self.video_path = video_path
        self.gpx_path = gpx_path
        self.sync_mode = sync_mode

    @override
    def extract(self) -> types.VideoMetadata:
        gpx_tracks = parse_gpx(self.gpx_path)

        if 1 < len(gpx_tracks):
            LOG.warning(
                f"Found {len(gpx_tracks)} tracks in the GPX file {self.gpx_path}. Will merge points in all the tracks as a single track for interpolation"
            )

        gpx_points: T.Sequence[geo.Point] = sum(gpx_tracks, [])

        native_extractor = NativeVideoExtractor(self.video_path)

        try:
            native_video_metadata = native_extractor.extract()
        except exceptions.MapillaryVideoGPSNotFoundError as ex:
            if self.sync_mode is SyncMode.STRICT_SYNC:
                raise ex
            self._rebase_times(gpx_points)
            return types.VideoMetadata(
                filename=self.video_path,
                filesize=utils.get_file_size(self.video_path),
                filetype=types.FileType.VIDEO,
                points=gpx_points,
            )

        if self.sync_mode is SyncMode.REBASE:
            self._rebase_times(gpx_points)
        else:
            offset = self._gpx_offset(gpx_points, native_video_metadata.points)
            if gpx_points and native_video_metadata.points:
                self._check_time_gap(
                    gpx_points,
                    native_video_metadata.points,
                    offset,
                    self._video_duration(),
                )
            self._rebase_times(gpx_points, offset=offset)

        return dataclasses.replace(native_video_metadata, points=gpx_points)

    def _video_duration(self) -> float | None:
        """
        The duration of the video in seconds, from its mvhd box, or None if it
        cannot be read.
        """
        try:
            with self.video_path.open("rb") as fp:
                data = sparser.parse_box_data_first(fp, [b"moov", b"mvhd"])
            if data is None:
                return None
            mvhd = cparser.MovieHeaderBox.parse(data)
        except (OSError, sparser.ParsingError, C.ConstructError) as ex:
            LOG.debug("Failed to read the duration of %s: %s", self.video_path, ex)
            return None

        # All 1s means the duration is unknown
        if not mvhd.timescale or mvhd.duration in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            return None

        return mvhd.duration / mvhd.timescale

    def _check_time_gap(
        self,
        gpx_points: T.Sequence[geo.Point],
        video_gps_points: T.Sequence[geo.Point],
        offset: float,
        video_duration: float | None,
    ) -> None:
        """
        Check the GPX track, once synced by offset, against the video in time.

        A GPX track that misses the video raises: it has no position for any
        moment of the video. A track that covers only part of the video warns,
        and one that covers all of it is silent.

        When the video's GPS has no timestamps, the offset is 0 and the track
        starts at video time 0, so only the end of the video can go uncovered.

        Without the duration of the video, the video is known only up to its
        last GPS point, and a GPX that starts after it may still overlap the
        video. Then a gap only warns, unless it is too large for any clock or
        time zone mistake to explain.
        """
        # The Unix time of video time 0, in the convention _rebase_times() uses
        video_start_time = gpx_points[0].time - offset
        # From video time 0, since the frames start there even when the video's
        # own GPS starts later
        video_end_time = video_start_time + max(p.time for p in video_gps_points)
        if video_duration is not None:
            video_end_time = max(video_end_time, video_start_time + video_duration)
        gpx_first = min(p.time for p in gpx_points)
        gpx_last = max(p.time for p in gpx_points)

        gpx_track = f"The GPX track in {self.gpx_path} ({_isoformat(gpx_first)} to {_isoformat(gpx_last)})"
        video = f"the video {self.video_path} ({_isoformat(video_start_time)} to {_isoformat(video_end_time)})"

        gap = max(gpx_first - video_end_time, video_start_time - gpx_last)
        if gap <= 0:
            uncovered = max(gpx_first - video_start_time, 0) + max(
                video_end_time - gpx_last, 0
            )
            if uncovered > _UNCOVERED_TOLERANCE_SECONDS:
                LOG.warning(
                    f"{gpx_track} covers only part of {video}: "
                    f"{_format_duration(uncovered)} of the video fall outside the track"
                )
            return

        message = (
            f"{gpx_track} misses {video} by {_format_duration(gap)}. Check that "
            "the GPX file belongs to this video, then the camera clock and the "
            "time zone of the GPX timestamps"
        )

        if video_duration is not None or gap > _IMPLAUSIBLE_GAP_SECONDS:
            raise exceptions.MapillaryOutsideGPXTrackError(
                message,
                image_time=build_capture_time(video_start_time),
                gpx_start_time=build_capture_time(gpx_first),
                gpx_end_time=build_capture_time(gpx_last),
            )

        LOG.warning(message)

    @classmethod
    def _rebase_times(cls, points: T.Sequence[geo.Point], offset: float = 0.0) -> None:
        """
        Rebase point times to start from **offset**
        """
        if points:
            first_timestamp = points[0].time
            for p in points:
                p.time = (p.time - first_timestamp) + offset

    @classmethod
    def _gpx_offset(
        cls, gpx_points: T.Sequence[geo.Point], video_gps_points: T.Sequence[geo.Point]
    ) -> float:
        """
        Calculate the offset that needs to be applied to the GPX points to sync with the video GPS points.

        >>> gpx_points = [geo.Point(time=5, lat=1, lon=1, alt=None, angle=None)]
        >>> GPXVideoExtractor._gpx_offset(gpx_points, gpx_points)
        0.0
        >>> GPXVideoExtractor._gpx_offset(gpx_points, [])
        0.0
        >>> GPXVideoExtractor._gpx_offset([], gpx_points)
        0.0
        """
        offset: float = 0.0

        if not gpx_points or not video_gps_points:
            return offset

        # Both sides must be Unix time here. get_unix_time() skips
        # zero/invalid timestamps, and points that carry none at all, like
        # CAMM type 5 points, which a track can start with.
        anchor = next(
            (p for p in video_gps_points if p.get_unix_time() is not None), None
        )

        if anchor is not None:
            anchor_unix_time = T.cast(float, anchor.get_unix_time())
            # The Unix time of video time 0
            video_unix_time = anchor_unix_time - anchor.time
            offset = gpx_points[0].time - video_unix_time

        return offset


def _isoformat(unix_time: float) -> str:
    return datetime.datetime.fromtimestamp(
        unix_time, tz=datetime.timezone.utc
    ).isoformat()


def _format_duration(seconds: float) -> str:
    """
    >>> _format_duration(0.089)
    '0.089 seconds'
    >>> _format_duration(1)
    '1 second'
    >>> _format_duration(13)
    '13 seconds'
    >>> _format_duration(90)
    '1.5 minutes'
    >>> _format_duration(2 * 3600)
    '2.0 hours'
    >>> _format_duration(3 * 86400)
    '3.0 days'
    """
    for unit, size in (("days", 86400), ("hours", 3600), ("minutes", 60)):
        if seconds >= size:
            return f"{seconds / size:.1f} {unit}"
    # Significant digits, so that a gap under a second does not read as 0
    text = f"{seconds:.3g}"
    return f"{text} second" if text == "1" else f"{text} seconds"
