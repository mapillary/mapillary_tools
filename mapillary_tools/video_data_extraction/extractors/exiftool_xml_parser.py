import typing as T
import xml.etree.ElementTree as ET

from pathlib import Path

from mapillary_tools import geo
from mapillary_tools.exiftool_read import EXIFTOOL_NAMESPACES
from mapillary_tools.exiftool_read_video import ExifToolReadVideo
from mapillary_tools.geotag.geotag_videos_from_exiftool_video import _DESCRIPTION_TAG
from mapillary_tools.video_data_extraction.cli_options import (
    CliOptions,
    CliParserOptions,
)
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser


class ExiftoolXmlParser(BaseParser):
    default_source_pattern = "%g.xml"
    must_rebase_times_to_zero = True
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
        return (
            self.exifToolReadVideo.extract_gps_track() if self.exifToolReadVideo else []
        )

    def extract_make(self) -> T.Optional[str]:
        return self.exifToolReadVideo.extract_make() if self.exifToolReadVideo else None

    def extract_model(self) -> T.Optional[str]:
        return (
            self.exifToolReadVideo.extract_model() if self.exifToolReadVideo else None
        )
