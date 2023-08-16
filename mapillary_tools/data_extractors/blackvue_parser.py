import abc
import functools
import typing as T
from pathlib import Path

from mapillary_tools import exceptions, geo
from mapillary_tools.data_extractors.base_parser import BaseParser
from mapillary_tools.geotag import blackvue_parser, simple_mp4_parser


class BlackVueParser(BaseParser):
    def extract_points(self) -> T.Sequence[geo.Point]:
        with self.videoPath.open("rb") as fp:
            try:
                return blackvue_parser.extract_points(fp) or []
            except simple_mp4_parser.ParsingError:
                return []

    def extract_make(self) -> T.Optional[str]:
        return "BlackVue"

    def extract_model(self) -> T.Optional[str]:
        with self.videoPath.open("rb") as fp:
            return blackvue_parser.extract_camera_model(fp)

    @staticmethod
    def must_rebase_times_to_zero() -> bool:
        return False
