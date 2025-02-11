import typing as T
import xml.etree.ElementTree as ET

from pathlib import Path

from ... import geo
from ...exiftool_read import EXIFTOOL_NAMESPACES
from ...exiftool_read_video import ExifToolReadVideo
from ...geotag.geotag_videos_from_exiftool_video import _DESCRIPTION_TAG
from ..cli_options import CliOptions, CliParserOptions
from .base_parser import BaseParser


class ExiftoolXmlParser(BaseParser):
    default_source_pattern = "%g.xml"
    parser_label = "exiftool_xml"

    exifToolReadVideo: T.Optional[ExifToolReadVideo] = None

    def __init__(
        self,
        video_path: Path,
        options: CliOptions,
        parser_options: CliParserOptions,
        xml_content: T.Optional[str] = None,
    ) -> None:
        super().__init__(video_path, options, parser_options)

        if xml_content:
            etree = ET.fromstring(xml_content)
        else:
            xml_path = self.geotag_source_path
            if not xml_path:
                return
            etree = ET.parse(xml_path).getroot()

        element = next(etree.iterfind(_DESCRIPTION_TAG, namespaces=EXIFTOOL_NAMESPACES))
        self.exifToolReadVideo = ExifToolReadVideo(ET.ElementTree(element))

    def extract_points(self) -> T.Sequence[geo.Point]:
        gps_points = (
            self.exifToolReadVideo.extract_gps_track() if self.exifToolReadVideo else []
        )
        self._rebase_times(gps_points)
        return gps_points

    def extract_make(self) -> T.Optional[str]:
        return self.exifToolReadVideo.extract_make() if self.exifToolReadVideo else None

    def extract_model(self) -> T.Optional[str]:
        return (
            self.exifToolReadVideo.extract_model() if self.exifToolReadVideo else None
        )
