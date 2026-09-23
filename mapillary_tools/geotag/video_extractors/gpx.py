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

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import exceptions, geo, types, utils
from ...serializer.description import build_capture_time
from ..utils import parse_gpx
from .base import BaseVideoExtractor
from .native import NativeVideoExtractor


LOG = logging.getLogger(__name__)


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
            if offset:
                self._check_overlap(gpx_points, native_video_metadata.points, offset)
            self._rebase_times(gpx_points, offset=offset)

        return dataclasses.replace(native_video_metadata, points=gpx_points)

    @classmethod
    def _check_overlap(
        cls,
        gpx_points: T.Sequence[geo.Point],
        video_gps_points: T.Sequence[geo.Point],
        offset: float,
    ) -> None:
        """
        Raise if the GPX track, once synced by offset, does not overlap the
        video in time.

        Nothing downstream can use such a sync: every point would fall outside
        the video, and at upload the edit list would carry the whole offset.
        That used to overflow and abort the upload. Now that the edit list
        widens instead, this is what keeps an epoch mix-up or a GPX file from
        another day from failing silently.
        """
        # The Unix time of video time 0, in the convention _rebase_times() uses
        video_start_time = gpx_points[0].time - offset
        video_first = video_start_time + min(p.time for p in video_gps_points)
        video_last = video_start_time + max(p.time for p in video_gps_points)
        gpx_first = min(p.time for p in gpx_points)
        gpx_last = max(p.time for p in gpx_points)

        if gpx_last < video_first or video_last < gpx_first:
            raise exceptions.MapillaryOutsideGPXTrackError(
                f"The video GPS track ({_isoformat(video_first)} to {_isoformat(video_last)}) "
                f"does not overlap the GPX track ({_isoformat(gpx_first)} to {_isoformat(gpx_last)}) in time",
                image_time=build_capture_time(video_first),
                gpx_start_time=build_capture_time(gpx_first),
                gpx_end_time=build_capture_time(gpx_last),
            )

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
            # The Unix time the first video point would have
            video_unix_time = anchor_unix_time - (
                anchor.time - video_gps_points[0].time
            )
            offset = gpx_points[0].time - video_unix_time

        return offset


def _isoformat(unix_time: float) -> str:
    return datetime.datetime.fromtimestamp(
        unix_time, tz=datetime.timezone.utc
    ).isoformat()
