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
import humanize

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import exceptions, geo, telemetry, types, utils
from ...mp4 import construct_mp4_parser as cparser, simple_mp4_parser as sparser
from .. import options
from ..utils import parse_gpx
from .base import BaseVideoExtractor
from .native import NativeVideoExtractor


LOG = logging.getLogger(__name__)

# A GPX track and the video it is synced against should overlap in time. Warn
# above a day, which no legitimate pairing needs and an epoch mix-up exceeds by
# orders of magnitude.
_IMPLAUSIBLE_OFFSET_SECONDS = 24 * 3600

# No GPS fix can be timestamped before the GPS epoch, 1980-01-06. GPX files
# converted from camera logs can carry earlier times, such as
# 1969-12-31T15:59:59Z, on points that had no valid time
_GPS_EPOCH = datetime.datetime(1980, 1, 6, tzinfo=datetime.timezone.utc).timestamp()

# How much longer than a video a GPX track may last without a warning, when it
# is assumed to start with the video. A logger that records once a second,
# started and stopped with the camera, can run on for a second at each end.
_ASSUMED_START_TOLERANCE_SECONDS = 2.0


class SyncMode(enum.Enum):
    # Sync by video GPS timestamps if found, otherwise rebase
    SYNC = "sync"
    # Sync by video GPS timestamps, and throw if not found
    STRICT_SYNC = "strict_sync"
    # Rebase all GPX timestamps to start from 0
    REBASE = "rebase"


class GPXVideoExtractor(BaseVideoExtractor):
    def __init__(
        self,
        video_path: Path,
        gpx_path: Path,
        sync_mode: SyncMode = SyncMode.SYNC,
        video_sync: options.VideoSyncOption | None = None,
    ):
        self.video_path = video_path
        self.gpx_path = gpx_path
        self.sync_mode = sync_mode
        self.video_sync = video_sync
        if video_sync is not None and video_sync.use_gpx_start_time:
            self.sync_mode = SyncMode.REBASE

    @override
    def extract(self) -> types.VideoMetadata:
        gpx_tracks = parse_gpx(self.gpx_path)

        if 1 < len(gpx_tracks):
            LOG.warning(
                f"Found {len(gpx_tracks)} tracks in the GPX file {self.gpx_path}. Will merge points in all the tracks as a single track for interpolation"
            )

        all_points: list[geo.Point] = sum(gpx_tracks, [])
        gpx_points = [p for p in all_points if _GPS_EPOCH <= p.time]
        if len(gpx_points) < len(all_points):
            LOG.warning(
                "Ignoring %d of the %d points in the GPX file %s, which are timestamped before 1980",
                len(all_points) - len(gpx_points),
                len(all_points),
                self.gpx_path,
            )

        # The tracks need not be in time order, and interpolation needs the
        # merged points to be
        gpx_points.sort(key=lambda p: p.time)

        native_extractor = NativeVideoExtractor(self.video_path)

        try:
            native_video_metadata = native_extractor.extract()
        except exceptions.MapillaryVideoGPSNotFoundError as ex:
            if self.sync_mode is SyncMode.STRICT_SYNC:
                raise ex
            self._place_without_video_gps(gpx_points)
            self._apply_offset_time(gpx_points)
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
            if abs(offset) > _IMPLAUSIBLE_OFFSET_SECONDS:
                LOG.warning(
                    "Syncing %s against %s requires an offset of %.0f seconds (%.1f days). "
                    "The GPX file probably does not belong to this video",
                    self.video_path,
                    self.gpx_path,
                    offset,
                    offset / 86400,
                )
            self._rebase_times(gpx_points, offset=offset)

        self._apply_offset_time(gpx_points)

        return dataclasses.replace(native_video_metadata, points=gpx_points)

    def _place_without_video_gps(self, gpx_points: T.Sequence[geo.Point]) -> None:
        """
        Place the GPX track on the timeline of a video that has no GPS to sync
        it with: by the start time of the video, when sampling was given one,
        and otherwise by assuming that the track starts with the video.
        """
        if not gpx_points:
            return

        if self.sync_mode is SyncMode.SYNC and self.video_sync is not None:
            if self.video_sync.start_time is not None:
                self._rebase_times(
                    gpx_points, offset=gpx_points[0].time - self.video_sync.start_time
                )
                return
            self._check_assumed_start(gpx_points)

        self._rebase_times(gpx_points)

    def _apply_offset_time(self, gpx_points: T.Sequence[geo.Point]) -> None:
        """
        Shift the track back by --interpolation_offset_time, which the
        geotagging stage adds to the capture time of a frame to find its
        position along the GPX.

        The absolute times shift with the track, so that a frame is stamped
        with its capture time, and the geotagging stage, adding the offset back,
        finds the position the frame was picked by.
        """
        if self.video_sync is None or not self.video_sync.offset_time:
            return

        offset_time = self.video_sync.offset_time
        for p in gpx_points:
            p.time -= offset_time
            # parse_gpx() returns CAMMGPSPoint, with epoch_time 0 for no time
            if isinstance(p, telemetry.CAMMGPSPoint) and 0 < p.epoch_time:
                p.epoch_time -= offset_time

    def _check_assumed_start(self, gpx_points: T.Sequence[geo.Point]) -> None:
        """
        Check that the GPX track can have started with the video, as it is
        assumed to when nothing says when the video starts.

        A track that runs on for longer than the whole video was not recorded
        for the video alone, and the video could start anywhere along it: raise.
        One that runs on for less may have been started a little before the
        video, which puts every frame up to that much too early along it: warn.
        """
        video_duration = _video_duration(self.video_path)
        if video_duration is None:
            LOG.debug(
                "Unable to read the duration of %s to check the GPX track against",
                self.video_path,
            )
            return

        gpx_duration = max(p.time for p in gpx_points) - min(p.time for p in gpx_points)
        excess = gpx_duration - video_duration

        if video_duration < excess:
            raise exceptions.MapillaryGPXVideoStartUnknownError(
                f"The GPX track in {self.gpx_path} lasts {_format_duration(gpx_duration)} "
                f"and the video only {_format_duration(video_duration)}, so the video "
                "could start anywhere along the track. Specify --video_start_time, or "
                "--interpolation_use_gpx_start_time if the track was started with the video"
            )

        if _ASSUMED_START_TOLERANCE_SECONDS < excess:
            LOG.warning(
                "Assuming that the GPX track in %s starts with the video %s, although "
                "the track lasts %s longer. If it was started first, the frames are "
                "placed up to that much too early along it. Specify --video_start_time "
                "to place them exactly, or --interpolation_use_gpx_start_time if the "
                "track was started with the video",
                self.gpx_path,
                self.video_path,
                _format_duration(excess),
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

        # Both sides must be Unix time here. Video GPS timestamps are stored in
        # whatever epoch their container uses (CAMM records GPS time, GoPro
        # records Unix time), so go through get_unix_time() rather than reading
        # the raw attributes -- that also skips zero/invalid timestamps.
        video_unix_time = video_gps_points[0].get_unix_time()

        if video_unix_time is not None:
            offset = gpx_points[0].time - video_unix_time

        return offset


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


def _format_duration(seconds: float) -> str:
    """
    >>> _format_duration(5.76)
    '5 seconds'
    >>> _format_duration(43474)
    '12 hours'
    """
    return humanize.naturaldelta(datetime.timedelta(seconds=seconds))
