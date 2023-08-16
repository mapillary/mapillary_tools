import abc
import functools
import typing as T
from pathlib import Path

from mapillary_tools import exceptions, geo
from mapillary_tools.data_extractors.base_parser import BaseParser
from mapillary_tools.geotag import (
    blackvue_parser,
    camm_parser,
    geotag_images_from_nmea_file,
    gpmf_parser,
    simple_mp4_parser,
)


class GoProParser(BaseParser):
    def extract_points(self) -> T.Sequence[geo.Point]:
        with self.videoPath.open("rb") as fp:
            try:
                return gpmf_parser.extract_points(fp) or []
            except simple_mp4_parser.ParsingError:
                return []

    def extract_make(self) -> T.Optional[str]:
        return "GoPro"

    def extract_model(self) -> T.Optional[str]:
        with self.videoPath.open("rb") as fp:
            return gpmf_parser.extract_camera_model(fp)

    @staticmethod
    def must_rebase_times_to_zero() -> bool:
        return False
