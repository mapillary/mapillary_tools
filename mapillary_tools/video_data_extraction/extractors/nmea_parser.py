import typing as T

from ... import geo
from ...geotag import geotag_images_from_nmea_file
from .base_parser import BaseParser


class NmeaParser(BaseParser):
    default_source_pattern = "%g.nmea"
    must_rebase_times_to_zero = True
    parser_label = "nmea"

    def extract_points(self) -> T.Sequence[geo.Point]:
        source_path = self.geotag_source_path
        if not source_path:
            return []
        points = geotag_images_from_nmea_file.get_lat_lon_time_from_nmea(source_path)
        return points

    def extract_make(self) -> T.Optional[str]:
        return None

    def extract_model(self) -> T.Optional[str]:
        return None
