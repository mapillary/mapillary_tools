import copy
import functools
import subprocess
import tempfile
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

from mapillary_tools import geo
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser
from mapillary_tools.video_data_extraction.extractors.exiftool_xml_parser import (
    ExiftoolXmlParser,
)
from mapillary_tools.video_data_extraction.options import Options, ParserOptions


class ExiftoolRuntimeParser(BaseParser):
    """
    Wrapper around ExiftoolRdfParser that executes exiftool
    """

    default_source_pattern = "%f"
    must_rebase_times_to_zero = True
    parser_label = "exiftool_runtime"
    tempFilePath: T.Optional[Path] = None

    @functools.cache
    def _get_exiftool_xml_parser(self) -> ExiftoolXmlParser:
        exiftool_xml = tempfile.NamedTemporaryFile(delete=False)
        exiftool_xml_path = Path(exiftool_xml.name)
        source_path = self.get_geotag_source_path()
        args = (
            f"{self.parserOptions.get('exiftool_path', 'exiftool')} -q -w! {exiftool_xml.name}%0f -r -n -ee -api LargeFileSupport=1 -X {source_path}"
        ).split(" ")
        subprocess.run(args)

        options = copy.deepcopy(self.options)
        options["geotag_source_path"] = exiftool_xml_path
        self.tempFilePath = exiftool_xml_path

        return ExiftoolXmlParser(
            exiftool_xml_path, options, self.parserOptions, exiftool_xml_path
        )
        # TODO: if ExiftoolXmlParser expects different parser options from ExiftoolRuntimeParser, we should build them properly

    def extract_points(self) -> T.Sequence[geo.Point]:
        return self._get_exiftool_xml_parser().extract_points()

    def extract_make(self) -> T.Optional[str]:
        return self._get_exiftool_xml_parser().extract_make()

    def extract_model(self) -> T.Optional[str]:
        return self._get_exiftool_xml_parser().extract_model()

    def cleanup(self) -> None:
        if self.tempFilePath:
            self.tempFilePath.unlink(missing_ok=True)
