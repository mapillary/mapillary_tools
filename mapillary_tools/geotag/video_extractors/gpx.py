from __future__ import annotations

import dataclasses
import enum
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import exceptions, geo, telemetry, types, utils
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
            self._rebase_times(gpx_points, offset=offset)

        return dataclasses.replace(native_video_metadata, points=gpx_points)

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

        gps_epoch_time: float | None = None
        gps_point = video_gps_points[0]
        if isinstance(gps_point, telemetry.GPSPoint):
            if gps_point.epoch_time is not None:
                gps_epoch_time = gps_point.epoch_time
        elif isinstance(gps_point, telemetry.CAMMGPSPoint):
            if gps_point.time_gps_epoch is not None:
                gps_epoch_time = gps_point.time_gps_epoch

        if gps_epoch_time is not None:
            offset = gpx_points[0].time - gps_epoch_time

        return offset
