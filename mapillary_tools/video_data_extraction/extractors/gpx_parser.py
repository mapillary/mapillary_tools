import datetime
import logging
import typing as T

from ... import geo, telemetry
from ...geotag import geotag_images_from_gpx_file
from .base_parser import BaseParser
from .generic_video_parser import GenericVideoParser


LOG = logging.getLogger(__name__)


class GpxParser(BaseParser):
    default_source_pattern = "%g.gpx"
    parser_label = "gpx"

    def extract_points(self) -> T.Sequence[geo.Point]:
        path = self.geotag_source_path
        if not path:
            return []

        gpx_tracks = geotag_images_from_gpx_file.parse_gpx(path)
        if 1 < len(gpx_tracks):
            LOG.warning(
                "Found %s tracks in the GPX file %s. Will merge points in all the tracks as a single track for interpolation",
                len(gpx_tracks),
                self.videoPath,
            )

        gpx_points: T.Sequence[geo.Point] = sum(gpx_tracks, [])
        if not gpx_points:
            return gpx_points

        first_gpx_dt = datetime.datetime.fromtimestamp(
            gpx_points[0].time, tz=datetime.timezone.utc
        )
        LOG.info("First GPX timestamp: %s", first_gpx_dt)

        # Extract first GPS timestamp (if found) for synchronization
        offset: float = 0.0
        parser = GenericVideoParser(self.videoPath, self.options, self.parserOptions)
        gps_points = parser.extract_points()
        if gps_points:
            first_gps_point = gps_points[0]
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

        self._rebase_times(gpx_points, offset=offset)

        return gpx_points

    def extract_make(self) -> T.Optional[str]:
        parser = GenericVideoParser(self.videoPath, self.options, self.parserOptions)
        return parser.extract_make()

    def extract_model(self) -> T.Optional[str]:
        parser = GenericVideoParser(self.videoPath, self.options, self.parserOptions)
        return parser.extract_model()
