import functools
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

from mapillary_tools import geo
from mapillary_tools.exiftool_read import EXIFTOOL_NAMESPACES
from mapillary_tools.exiftool_read_video import ExifToolReadVideo
from mapillary_tools.geotag.geotag_videos_from_exiftool_video import _DESCRIPTION_TAG
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser
from mapillary_tools.video_data_extraction.options import Options, ParserOptions


class ExiftoolXmlParser(BaseParser):
    default_source_pattern = "%g.xml"
    must_rebase_times_to_zero = True
    parser_label = "exiftool_xml"

    forcedRdfSource: T.Optional[Path]

    def __init__(
        self,
        video_path: Path,
        options: Options,
        parser_options: ParserOptions,
        forced_rdf_source: T.Optional[Path] = None,
    ) -> None:
        super().__init__(video_path, options, parser_options)
        self.forcedRdfSource = forced_rdf_source

    @functools.cache
    def _get_reader(self) -> T.Optional[ExifToolReadVideo]:
        xml_path = self.forcedRdfSource or self.get_geotag_source_path()
        if not xml_path:
            return None
        etree = ET.parse(xml_path)
        element = next(etree.iterfind(_DESCRIPTION_TAG, namespaces=EXIFTOOL_NAMESPACES))
        return ExifToolReadVideo(ET.ElementTree(element))

    def extract_points(self) -> T.Sequence[geo.Point]:
        reader = self._get_reader()
        return reader.extract_gps_track() if reader else []

    def extract_make(self) -> T.Optional[str]:
        reader = self._get_reader()
        return reader.extract_make() if reader else None

    def extract_model(self) -> T.Optional[str]:
        reader = self._get_reader()
        return reader.extract_model() if reader else None
