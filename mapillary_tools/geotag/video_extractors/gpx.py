from __future__ import annotations

import dataclasses
import datetime
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import geo, telemetry, types
from ..utils import parse_gpx
from .base import BaseVideoExtractor
from .native import NativeVideoExtractor


LOG = logging.getLogger(__name__)


class GPXVideoExtractor(BaseVideoExtractor):
    def __init__(self, video_path: Path, gpx_path: Path):
        self.video_path = video_path
        self.gpx_path = gpx_path

    @override
    def extract(self) -> types.VideoMetadataOrError:
        try:
            gpx_tracks = parse_gpx(self.gpx_path)
        except Exception as ex:
            raise RuntimeError(
                f"Error parsing GPX {self.gpx_path}: {ex.__class__.__name__}: {ex}"
            )

        if 1 < len(gpx_tracks):
            LOG.warning(
                "Found %s tracks in the GPX file %s. Will merge points in all the tracks as a single track for interpolation",
                len(gpx_tracks),
                self.gpx_path,
            )

        gpx_points: T.Sequence[geo.Point] = sum(gpx_tracks, [])

        native_extractor = NativeVideoExtractor(self.video_path)

        video_metadata_or_error = native_extractor.extract()

        if isinstance(video_metadata_or_error, types.ErrorMetadata):
            self._rebase_times(gpx_points)
            return types.VideoMetadata(
                filename=video_metadata_or_error.filename,
                filetype=video_metadata_or_error.filetype or types.FileType.VIDEO,
                points=gpx_points,
            )

        video_metadata = video_metadata_or_error

        offset = self._synx_gpx_by_first_gps_timestamp(
            gpx_points, video_metadata.points
        )

        self._rebase_times(gpx_points, offset=offset)

        return dataclasses.replace(video_metadata_or_error, points=gpx_points)

    @staticmethod
    def _rebase_times(points: T.Sequence[geo.Point], offset: float = 0.0):
        """
        Make point times start from 0
        """
        if points:
            first_timestamp = points[0].time
            for p in points:
                p.time = (p.time - first_timestamp) + offset
        return points

    def _synx_gpx_by_first_gps_timestamp(
        self, gpx_points: T.Sequence[geo.Point], video_gps_points: T.Sequence[geo.Point]
    ) -> float:
        offset: float = 0.0

        if not gpx_points:
            return offset

        first_gpx_dt = datetime.datetime.fromtimestamp(
            gpx_points[0].time, tz=datetime.timezone.utc
        )
        LOG.info("First GPX timestamp: %s", first_gpx_dt)

        if not video_gps_points:
            LOG.warning(
                "Skip GPX synchronization because no GPS found in video %s",
                self.video_path,
            )
            return offset

        first_gps_point = video_gps_points[0]
        if isinstance(first_gps_point, telemetry.GPSPoint):
            if first_gps_point.epoch_time is not None:
                first_gps_dt = datetime.datetime.fromtimestamp(
                    first_gps_point.epoch_time, tz=datetime.timezone.utc
                )
                LOG.info("First GPS timestamp: %s", first_gps_dt)
                offset = gpx_points[0].time - first_gps_point.epoch_time
                if offset:
                    LOG.warning(
                        "Found offset between GPX %s and video GPS timestamps %s: %s seconds",
                        first_gpx_dt,
                        first_gps_dt,
                        offset,
                    )
                else:
                    LOG.info(
                        "GPX and GPS are perfectly synchronized (all starts from %s)",
                        first_gpx_dt,
                    )
            else:
                LOG.warning(
                    "Skip GPX synchronization because no GPS epoch time found in video %s",
                    self.video_path,
                )

        return offset
