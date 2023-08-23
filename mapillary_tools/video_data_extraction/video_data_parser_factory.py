import typing as T
from pathlib import Path

from mapillary_tools.video_data_extraction.cli_options import CliOptions

from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser

from mapillary_tools.video_data_extraction.extractors.blackvue_parser import (
    BlackVueParser,
)
from mapillary_tools.video_data_extraction.extractors.camm_parser import CammParser
from mapillary_tools.video_data_extraction.extractors.exiftool_runtime_parser import (
    ExiftoolRuntimeParser,
)
from mapillary_tools.video_data_extraction.extractors.exiftool_xml_parser import (
    ExiftoolXmlParser,
)
from mapillary_tools.video_data_extraction.extractors.generic_video_parser import (
    GenericVideoParser,
)
from mapillary_tools.video_data_extraction.extractors.gopro_parser import GoProParser
from mapillary_tools.video_data_extraction.extractors.gpx_parser import GpxParser
from mapillary_tools.video_data_extraction.extractors.nmea_parser import NmeaParser


known_parsers = {
    "gpx": GpxParser,
    "nmea": NmeaParser,
    "exiftool_xml": ExiftoolXmlParser,
    "exiftool_runtime": ExiftoolRuntimeParser,
    "camm": CammParser,
    "blackvue": BlackVueParser,
    "gopro": GoProParser,
    "video": GenericVideoParser,
}


def make_parsers(file: Path, options: CliOptions) -> T.Sequence[BaseParser]:
    src_options = options["geotag_sources_options"]
    parsers = [
        known_parsers[s["source"]](file, options, s)
        for s in src_options
        if s["source"] in known_parsers
    ]

    return parsers
