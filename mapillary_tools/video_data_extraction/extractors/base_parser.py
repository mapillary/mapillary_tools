import abc
import functools
import logging
import os
import typing as T
from pathlib import Path

from ... import geo
from ..cli_options import CliOptions, CliParserOptions

LOG = logging.getLogger(__name__)


class BaseParser(metaclass=abc.ABCMeta):
    videoPath: Path
    options: CliOptions
    parserOptions: CliParserOptions

    def __init__(
        self, video_path: Path, options: CliOptions, parser_options: CliParserOptions
    ) -> None:
        self.videoPath = video_path
        self.options = options
        self.parserOptions = parser_options

    @property
    @abc.abstractmethod
    def default_source_pattern(self) -> str:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def parser_label(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_points(self) -> T.Sequence[geo.Point]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_make(self) -> T.Optional[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_model(self) -> T.Optional[str]:
        raise NotImplementedError

    @functools.cached_property
    def geotag_source_path(self) -> T.Optional[Path]:
        video_dir = self.videoPath.parent.resolve()
        video_filename = self.videoPath.name
        video_basename, video_ext = os.path.splitext(video_filename)
        pattern = self.parserOptions.get("pattern") or self.default_source_pattern

        replaced = Path(
            pattern.replace("%f", video_filename)
            .replace("%g", video_basename)
            .replace("%e", video_ext)
        )
        abs_path = (
            replaced if replaced.is_absolute() else Path.joinpath(video_dir, replaced)
        ).resolve()

        return abs_path if abs_path.is_file() else None

    @staticmethod
    def _rebase_times(points: T.Sequence[geo.Point], offset: float = 0.0):
        """
        Make point times start from 0
        """
        if points:
            first_timestamp = points[0].time
            for p in points:
                p.time = (p.time - first_timestamp) + offset
        return points
