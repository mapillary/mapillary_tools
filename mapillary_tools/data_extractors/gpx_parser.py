import functools
import os
import typing as T
from pathlib import Path

from mapillary_tools import exceptions, geo
from mapillary_tools.data_extractors.base_parser import BaseParser
from mapillary_tools.geotag import geotag_images_from_gpx_file


class GpxParser(BaseParser):
    @functools.cache
    def _get_geotag_source(self) -> Path:
        return next(self.videoPath.parent.glob("*gpx"))

    def extract_points(self) -> T.Sequence[geo.Point]:
        try:
            tracks = geotag_images_from_gpx_file.parse_gpx(self._get_geotag_source())
        except Exception as e:
            return []

        points: T.Sequence[geo.Point] = sum(tracks, [])
        return points

    def extract_make(self) -> T.Optional[str]:
        return None

    def extract_model(self) -> T.Optional[str]:
        return None

    @staticmethod
    def must_rebase_times_to_zero() -> bool:
        return True
