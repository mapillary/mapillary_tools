import abc
import functools
import typing as T
from pathlib import Path

from mapillary_tools import exceptions, geo
from mapillary_tools.data_extractors.base_parser import BaseParser
from mapillary_tools.geotag import (
    camm_parser,
    geotag_images_from_nmea_file,
    gpmf_parser,
    simple_mp4_parser,
)


class CammParser(BaseParser):
    @functools.cache
    def _get_camera_info(self) -> T.Tuple[str, str]:
        with self.videoPath.open("rb") as fp:
            return camm_parser.extract_camera_make_and_model(fp)

    def extract_points(self) -> T.Sequence[geo.Point]:
        with self.videoPath.open("rb") as fp:
            try:
                return camm_parser.extract_points(fp) or []
            except simple_mp4_parser.ParsingError:
                return []

    def extract_make(self) -> T.Optional[str]:
        with self.videoPath.open("rb") as fp:
            return self._get_camera_info()[0]

    def extract_model(self) -> T.Optional[str]:
        with self.videoPath.open("rb") as fp:
            return self._get_camera_info()[1]

    @staticmethod
    def must_rebase_times_to_zero() -> bool:
        return False
