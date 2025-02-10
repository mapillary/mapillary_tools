import typing as T

from ... import geo
from ...geotag import gpmf_parser
from ...mp4 import simple_mp4_parser as sparser
from .base_parser import BaseParser


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
            except sparser.ParsingError:
                return []

    def extract_make(self) -> T.Optional[str]:
        model = self.extract_model()
        if model:
            return "GoPro"

        # make sure self.pointsFound is updated
        _ = self.extract_points()
        # If no points were found, assume this is not a GoPro
        return "GoPro" if self.pointsFound else None

    def extract_model(self) -> T.Optional[str]:
        source_path = self.geotag_source_path
        if not source_path:
            return None
        with source_path.open("rb") as fp:
            return gpmf_parser.extract_camera_model(fp) or None
