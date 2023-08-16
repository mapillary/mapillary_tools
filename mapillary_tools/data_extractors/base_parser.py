import abc
import typing as T
from pathlib import Path

from mapillary_tools import geo
from mapillary_tools.video_data_extraction.options import Options


class BaseParser:
    videoPath: Path
    geotagSourcePath: T.Optional[Path]
    options: Options

    def __init__(self, video_path: Path, options: Options) -> None:
        self.videoPath = video_path
        self.geotagSourcePath = None
        self.options = options

    @abc.abstractmethod
    def extract_points(self) -> T.Sequence[geo.Point]:
        raise NotImplementedError

    @abc.abstractmethod
    def extract_make(self) -> T.Optional[str]:
        return None

    @abc.abstractmethod
    def extract_model(self) -> T.Optional[str]:
        return None

    def cleanup(self) -> None:
        pass

    @staticmethod
    @abc.abstractstaticmethod
    def must_rebase_times_to_zero() -> bool:
        raise NotImplementedError
