import typing as T

from mapillary_tools import geo
from mapillary_tools.geotag import geotag_images_from_gpx_file
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser


class GpxParser(BaseParser):
    default_source_pattern = "%g.gpx"
    must_rebase_times_to_zero = True
    parser_label = "gpx"

    def extract_points(self) -> T.Sequence[geo.Point]:
        path = self.geotag_source_path
        if not path:
            return []
        try:
            tracks = geotag_images_from_gpx_file.parse_gpx(path)
        except Exception as e:
            return []

        points: T.Sequence[geo.Point] = sum(tracks, [])
        return points

    def extract_make(self) -> T.Optional[str]:
        return None

    def extract_model(self) -> T.Optional[str]:
        return None
