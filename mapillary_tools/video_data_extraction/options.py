import typing as T
from pathlib import Path


known_parser_options = ["source", "pattern", "exiftool_path"]


class ParserOptions(T.TypedDict):
    source: str
    pattern: T.NotRequired[str]
    exiftool_path: T.NotRequired[Path]


class Options(T.TypedDict):
    paths: T.Sequence[Path]
    recursive: bool
    geotag_sources_options: T.Sequence[ParserOptions]
    geotag_source_path: Path
    exiftool_path: Path
    num_processes: int
