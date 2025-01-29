import typing as T
from pathlib import Path


known_parser_options = ["source", "pattern", "exiftool_path"]


class CliParserOptions(T.TypedDict, total=False):
    source: str
    pattern: T.Optional[str]
    exiftool_path: T.Optional[Path]


class CliOptions(T.TypedDict, total=False):
    paths: T.Sequence[Path]
    recursive: bool
    geotag_sources_options: T.Sequence[CliParserOptions]
    geotag_source_path: Path
    exiftool_path: Path
    num_processes: int
    device_make: T.Optional[str]
    device_model: T.Optional[str]
