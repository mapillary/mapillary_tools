import typing as T

from mapillary_tools import geo
from mapillary_tools.geotag import blackvue_parser, simple_mp4_parser
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser


class BlackVueParser(BaseParser):
    default_source_pattern = "%f"
    must_rebase_times_to_zero = False
    parser_label = "blackvue"

    pointsFound: bool = False

    def extract_points(self) -> T.Sequence[geo.Point]:
        source_path = self.geotag_source_path
        if not source_path:
            return []
        with source_path.open("rb") as fp:
            try:
                points = blackvue_parser.extract_points(fp) or []
                self.pointsFound = len(points) > 0
                return points
            except simple_mp4_parser.ParsingError:
                return []

    def extract_make(self) -> T.Optional[str]:
        # If no points were found, assume this is not a BlackVue
        return "Blackvue" if self.pointsFound else None

    def extract_model(self) -> T.Optional[str]:
        with self.videoPath.open("rb") as fp:
            return blackvue_parser.extract_camera_model(fp) or None
