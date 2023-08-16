import functools
import os
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

from mapillary_tools import exceptions, geo
from mapillary_tools.data_extractors.base_parser import BaseParser
from mapillary_tools.exiftool_read import EXIFTOOL_NAMESPACES
from mapillary_tools.exiftool_read_video import ExifToolReadVideo
from mapillary_tools.geotag import geotag_images_from_gpx_file
from mapillary_tools.geotag.geotag_videos_from_exiftool_video import _DESCRIPTION_TAG


class ExiftoolRdfParser(BaseParser):
    def _devise_rdf_file(self):
        video_dir = self.videoPath.parent
        video_filename = self.videoPath.name
        video_basename = os.path.splitext(video_filename)[0]
        format = (
            self.options["geotag_sources_options"]
            .get("exiftool_rdf", {})
            .get("format", "%f.%e")
        )
        replaced = (
            format.replace("%f", video_basename)
            .replace("%e", ".xml")
        )
        return Path.joinpath(video_dir, replaced)

    @functools.cache
    def _get_reader(self) -> ExifToolReadVideo:
        rdf_file = self._devise_rdf_file()
        etree = ET.parse(rdf_file)
        element = next(etree.iterfind(_DESCRIPTION_TAG, namespaces=EXIFTOOL_NAMESPACES))
        return ExifToolReadVideo(ET.ElementTree(element))

    def extract_points(self) -> T.Sequence[geo.Point]:
        return self._get_reader().extract_gps_track()

    def extract_make(self) -> T.Optional[str]:
        return self._get_reader().extract_make()

    def extract_model(self) -> T.Optional[str]:
        return self._get_reader().extract_model()

    @staticmethod
    def must_rebase_times_to_zero() -> bool:
        return True
