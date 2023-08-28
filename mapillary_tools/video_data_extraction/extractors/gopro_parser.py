import typing as T

from mapillary_tools import geo
from mapillary_tools.geotag import gpmf_parser, simple_mp4_parser
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser


class GoProParser(BaseParser):
    default_source_pattern = "%f"
    must_rebase_times_to_zero = False
    parser_label = "gopro"

    pointsFound: bool = False

    def extract_points(self) -> T.Sequence[geo.Point]:
        source_path = self.geotag_source_path
        if not source_path:
            return []
        with source_path.open("rb") as fp:
            try:
                points = gpmf_parser.extract_points(fp) or []
                self.pointsFound = len(points) > 0
                return points
            except simple_mp4_parser.ParsingError:
                return []

    def extract_make(self) -> T.Optional[str]:
        # If no points were found, assume this is not a GoPro
        return "GoPro" if self.pointsFound else None

    def extract_model(self) -> T.Optional[str]:
        source_path = self.geotag_source_path
        if not source_path:
            return None
        with source_path.open("rb") as fp:
            return gpmf_parser.extract_camera_model(fp) or None
