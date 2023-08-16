import abc
import typing as T
from pathlib import Path

from mapillary_tools import exceptions, geo
from mapillary_tools.data_extractors.base_parser import BaseParser
from mapillary_tools.geotag import geotag_images_from_nmea_file


class NmeaParser(BaseParser):
    def extract_points(self) -> T.Sequence[geo.Point]:
        points = geotag_images_from_nmea_file.get_lat_lon_time_from_nmea(self.videoPath)
        return points

    def extract_make(self) -> T.Optional[str]:
        return None

    def extract_model(self) -> T.Optional[str]:
        return None

    @staticmethod
    def must_rebase_times_to_zero() -> bool:
        return True
