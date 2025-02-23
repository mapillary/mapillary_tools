import functools
import typing as T

from ... import geo
from ...camm import camm_parser
from ...mp4 import simple_mp4_parser as sparser
from .base_parser import BaseParser


class CammParser(BaseParser):
    default_source_pattern = "%f"
    must_rebase_times_to_zero = False
    parser_label = "camm"

    @functools.cached_property
    def _camera_info(self) -> T.Tuple[str, str]:
        source_path = self.geotag_source_path
        if not source_path:
            return "", ""

        with source_path.open("rb") as fp:
            return camm_parser.extract_camera_make_and_model(fp)

    def extract_points(self) -> T.Sequence[geo.Point]:
        source_path = self.geotag_source_path
        if not source_path:
            return []
        with source_path.open("rb") as fp:
            try:
                return camm_parser.extract_points(fp) or []
            except sparser.ParsingError:
                return []

    def extract_make(self) -> T.Optional[str]:
        return self._camera_info[0] or None

    def extract_model(self) -> T.Optional[str]:
        return self._camera_info[1] or None
