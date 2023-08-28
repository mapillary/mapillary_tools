import functools
import typing as T

from mapillary_tools import geo
from mapillary_tools.geotag import camm_parser, simple_mp4_parser
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser


class CammParser(BaseParser):
    default_source_pattern = "%f"
    must_rebase_times_to_zero = False
    parser_label = "camm"

    @functools.cached_property
    def __camera_info(self) -> T.Tuple[str, str]:
        with self.videoPath.open("rb") as fp:
            return camm_parser.extract_camera_make_and_model(fp)

    def extract_points(self) -> T.Sequence[geo.Point]:
        source_path = self.geotag_source_path
        if not source_path:
            return []
        with source_path.open("rb") as fp:
            try:
                return camm_parser.extract_points(fp) or []
            except simple_mp4_parser.ParsingError:
                return []

    def extract_make(self) -> T.Optional[str]:
        source_path = self.geotag_source_path
        if not source_path:
            return None
        with source_path.open("rb") as fp:
            return self.__camera_info[0] or None

    def extract_model(self) -> T.Optional[str]:
        source_path = self.geotag_source_path
        if not source_path:
            return None
        with source_path.open("rb") as fp:
            return self.__camera_info[1] or None
