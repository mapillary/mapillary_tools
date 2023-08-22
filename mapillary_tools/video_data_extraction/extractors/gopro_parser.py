import typing as T

from mapillary_tools import geo
from mapillary_tools.geotag import gpmf_parser, simple_mp4_parser
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser


class GoProParser(BaseParser):
    default_source_pattern = "%f"
    must_rebase_times_to_zero = False
    parser_label = "gopro"

    def extract_points(self) -> T.Sequence[geo.Point]:
        source_path = self.geotag_source_path
        if not source_path:
            return []
        with source_path.open("rb") as fp:
            try:
                return gpmf_parser.extract_points(fp) or []
            except simple_mp4_parser.ParsingError:
                return []

    def extract_make(self) -> T.Optional[str]:
        return "GoPro"

    def extract_model(self) -> T.Optional[str]:
        source_path = self.geotag_source_path
        if not source_path:
            return None
        with source_path.open("rb") as fp:
            return gpmf_parser.extract_camera_model(fp)
