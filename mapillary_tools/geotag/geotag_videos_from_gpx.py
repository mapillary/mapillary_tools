from __future__ import annotations

import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from . import options
from .base import GeotagVideosFromGeneric
from .video_extractors.gpx import GPXVideoExtractor


LOG = logging.getLogger(__name__)


class GeotagVideosFromGPX(GeotagVideosFromGeneric):
    def __init__(
        self,
        option: options.SourcePathOption | None = None,
        num_processes: int | None = None,
    ):
        super().__init__(num_processes=num_processes)
        if option is None:
            option = options.SourcePathOption(pattern="%f.gpx")
        self.option = option

    @override
    def _generate_video_extractors(
        self, video_paths: T.Sequence[Path]
    ) -> T.Sequence[GPXVideoExtractor]:
        return [
            GPXVideoExtractor(video_path, self.option.resolve(video_path))
            for video_path in video_paths
        ]
