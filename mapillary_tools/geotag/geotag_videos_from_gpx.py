from __future__ import annotations

import logging
import typing as T
from pathlib import Path

from . import options
from .base import GeotagVideosFromGeneric
from .video_extractors.gpx import GPXVideoExtractor


LOG = logging.getLogger(__name__)


class GeotagVideosFromGPX(GeotagVideosFromGeneric):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        option: options.SourcePathOption | None = None,
        num_processes: int | None = None,
    ):
        super().__init__(video_paths, num_processes=num_processes)
        if option is None:
            option = options.SourcePathOption(pattern="%f.gpx")
        self.option = option

    def _generate_image_extractors(self) -> T.Sequence[GPXVideoExtractor]:
        return [
            GPXVideoExtractor(video_path, self.option.resolve(video_path))
            for video_path in self.video_paths
        ]
