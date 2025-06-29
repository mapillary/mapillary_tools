from __future__ import annotations

import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import exceptions, types
from . import options
from .base import GeotagVideosFromGeneric
from .video_extractors.gpx import GPXVideoExtractor


LOG = logging.getLogger(__name__)


class GeotagVideosFromGPX(GeotagVideosFromGeneric):
    def __init__(
        self,
        source_path: options.SourcePathOption | None = None,
        num_processes: int | None = None,
    ):
        super().__init__(num_processes=num_processes)
        if source_path is None:
            source_path = options.SourcePathOption(pattern="%g.gpx")
        self.source_path = source_path

    @override
    def _generate_video_extractors(
        self, video_paths: T.Sequence[Path]
    ) -> T.Sequence[GPXVideoExtractor | types.ErrorMetadata]:
        results: list[GPXVideoExtractor | types.ErrorMetadata] = []
        for video_path in video_paths:
            source_path = self.source_path.resolve(video_path)
            if source_path.is_file():
                results.append(GPXVideoExtractor(video_path, source_path))
            else:
                results.append(
                    types.describe_error_metadata(
                        exceptions.MapillaryVideoGPSNotFoundError(
                            "GPX file not found for video"
                        ),
                        filename=video_path,
                        filetype=types.FileType.VIDEO,
                    )
                )
        return results
