import shutil
import subprocess
import typing as T
from pathlib import Path

from ... import constants, exceptions, geo
from ..cli_options import CliOptions, CliParserOptions
from .base_parser import BaseParser
from .exiftool_xml_parser import ExiftoolXmlParser


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
        exiftool_path = shutil.which(constants.EXIFTOOL_PATH)

        if not exiftool_path:
            raise exceptions.MapillaryExiftoolNotFoundError(
                "Cannot execute exiftool. Please install it from https://exiftool.org/ or you package manager, or set the environment variable MAPILLARY_TOOLS_EXIFTOOL_PATH"
            )
        if not self.geotag_source_path:
            return

        # To handle non-latin1 filenames under Windows, we pass the path
        # via stdin. See https://exiftool.org/faq.html#Q18
        stdin = str(self.geotag_source_path)
        args = [
            exiftool_path,
            "-q",
            "-r",
            "-n",
            "-ee",
            "-api",
            "LargeFileSupport=1",
            "-X",
            "-charset",
            "filename=utf8",
            "-@",
            "-",
        ]

        process = subprocess.run(
            args, capture_output=True, text=True, input=stdin, encoding="utf-8"
        )

        self.exiftoolXmlParser = ExiftoolXmlParser(
            video_path, options, parser_options, process.stdout
        )

    def extract_points(self) -> T.Sequence[geo.Point]:
        return self.exiftoolXmlParser.extract_points() if self.exiftoolXmlParser else []

    def extract_make(self) -> T.Optional[str]:
        return self.exiftoolXmlParser.extract_make() if self.exiftoolXmlParser else None

    def extract_model(self) -> T.Optional[str]:
        return (
            self.exiftoolXmlParser.extract_model() if self.exiftoolXmlParser else None
        )
