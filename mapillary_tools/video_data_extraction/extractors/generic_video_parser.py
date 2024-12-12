import typing as T
from pathlib import Path

from ... import geo
from ..cli_options import CliOptions, CliParserOptions
from .base_parser import BaseParser
from .blackvue_parser import BlackVueParser
from .camm_parser import CammParser
from .gopro_parser import GoProParser


class GenericVideoParser(BaseParser):
    """
    Wrapper around the three native video parsers. It will try to execute them
    in the order camm-gopro-blackvue, like the previous implementation
    """

    parsers: T.Sequence[BaseParser] = []

    default_source_pattern = "%f"
    must_rebase_times_to_zero = False
    parser_label = "video"

    def __init__(
        self, video_path: Path, options: CliOptions, parser_options: CliParserOptions
    ) -> None:
        super().__init__(video_path, options, parser_options)
        camm_parser = CammParser(video_path, options, parser_options)
        gopro_parser = GoProParser(video_path, options, parser_options)
        blackvue_parser = BlackVueParser(video_path, options, parser_options)
        self.parsers = [camm_parser, gopro_parser, blackvue_parser]

    def extract_points(self) -> T.Sequence[geo.Point]:
        for parser in self.parsers:
            points = parser.extract_points()
            if points:
                return points
        return []

    def extract_make(self) -> T.Optional[str]:
        for parser in self.parsers:
            make = parser.extract_make()
            if make:
                return make
        return None

    def extract_model(self) -> T.Optional[str]:
        for parser in self.parsers:
            model = parser.extract_model()
            if model:
                return model
        return None
