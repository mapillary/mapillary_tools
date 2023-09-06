import subprocess
import typing as T
from pathlib import Path

from mapillary_tools import constants, geo
from mapillary_tools.video_data_extraction.cli_options import (
    CliOptions,
    CliParserOptions,
)
from mapillary_tools.video_data_extraction.extractors.base_parser import BaseParser
from mapillary_tools.video_data_extraction.extractors.exiftool_xml_parser import (
    ExiftoolXmlParser,
)


class ExiftoolRuntimeParser(BaseParser):
    """
    Wrapper around ExiftoolRdfParser that executes exiftool
    """

    exiftoolXmlParser: ExiftoolXmlParser

    default_source_pattern = "%f"
    must_rebase_times_to_zero = True
    parser_label = "exiftool_runtime"

    def __init__(
        self, video_path: Path, options: CliOptions, parser_options: CliParserOptions
    ):
        super().__init__(video_path, options, parser_options)

        args = (
            f"{constants.EXIFTOOL_PATH} -q -r -n -ee -api LargeFileSupport=1 -X {self.geotag_source_path}"
        ).split(" ")
        xml_content = subprocess.run(args, capture_output=True, text=True).stdout

        self.exiftoolXmlParser = ExiftoolXmlParser(
            video_path, options, parser_options, xml_content
        )

    def extract_points(self) -> T.Sequence[geo.Point]:
        return self.exiftoolXmlParser.extract_points() if self.exiftoolXmlParser else []

    def extract_make(self) -> T.Optional[str]:
        return self.exiftoolXmlParser.extract_make() if self.exiftoolXmlParser else None

    def extract_model(self) -> T.Optional[str]:
        return (
            self.exiftoolXmlParser.extract_model() if self.exiftoolXmlParser else None
        )
