import typing as T
from pathlib import Path


class Options(T.TypedDict):
    paths: T.Sequence[Path]
    recursive: bool
    geotag_sources: T.Sequence[str]
    geotag_source_path: Path
    exiftool_path: Path
    num_processes: int
