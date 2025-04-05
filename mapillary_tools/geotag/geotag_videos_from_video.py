from __future__ import annotations

import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ..types import FileType
from .base import GeotagVideosFromGeneric
from .video_extractors.native import NativeVideoExtractor


class GeotagVideosFromVideo(GeotagVideosFromGeneric):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        filetypes: set[FileType] | None = None,
        num_processes: int | None = None,
    ):
        super().__init__(video_paths, num_processes=num_processes)
        self.filetypes = filetypes

    @override
    def _generate_video_extractors(self) -> T.Sequence[NativeVideoExtractor]:
        return [
            NativeVideoExtractor(path, filetypes=self.filetypes)
            for path in self.video_paths
        ]
