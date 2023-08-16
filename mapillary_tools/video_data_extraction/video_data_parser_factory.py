import typing as T
from pathlib import Path

from mapillary_tools.data_extractors.base_parser import BaseParser

from mapillary_tools.data_extractors.blackvue_parser import BlackVueParser
from mapillary_tools.data_extractors.camm_parser import CammParser
from mapillary_tools.data_extractors.exiftool_rdf_parser import ExiftoolRdfParser
from mapillary_tools.data_extractors.exiftool_runtime_parser import (
    ExiftoolRuntimeParser,
)
from mapillary_tools.data_extractors.gopro_parser import GoProParser
from mapillary_tools.data_extractors.gpx_parser import GpxParser
from mapillary_tools.data_extractors.nmea_parser import NmeaParser
from mapillary_tools.video_data_extraction.options import Options


known_parsers = {
    "gpx": GpxParser,
    "nmea": NmeaParser,
    "exiftool_rdf": ExiftoolRdfParser,
    "exiftool_runtime": ExiftoolRuntimeParser,
    "camm": CammParser,
    "blackvue": BlackVueParser,
    "gopro": GoProParser,
}


def make_parsers(file: Path, options: Options) -> T.Sequence[BaseParser]:
    geotag_sources = options["geotag_sources_options"]
    parsers = [
        known_parsers[s](file, options) for s in geotag_sources.keys() if s in known_parsers
    ]

    return parsers
