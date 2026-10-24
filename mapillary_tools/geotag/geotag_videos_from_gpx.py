# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import collections
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import exceptions, types
from . import options, utils
from .base import GeotagVideosFromGeneric
from .video_extractors.gpx import GPXVideoExtractor


LOG = logging.getLogger(__name__)


class GeotagVideosFromGPX(GeotagVideosFromGeneric):
    # Reads the track file of each video, and where to find it by default
    extractor_class: type[GPXVideoExtractor] = GPXVideoExtractor
    default_pattern = "%g.gpx"

    def __init__(
        self,
        source_path: options.SourcePathOption | None = None,
        num_processes: int | None = None,
        video_sync: options.VideoSyncOption | None = None,
        interpolation: options.InterpolationOption | None = None,
    ):
        super().__init__(num_processes=num_processes)
        if source_path is None:
            source_path = options.SourcePathOption(pattern=self.default_pattern)
        self.source_path = source_path
        self.video_sync = video_sync
        self.interpolation = interpolation

    @override
    def _generate_video_extractors(
        self, video_paths: T.Sequence[Path]
    ) -> T.Sequence[GPXVideoExtractor | types.ErrorMetadata]:
        results: list[GPXVideoExtractor | types.ErrorMetadata] = []
        for video_path in video_paths:
            source_path = self.source_path.resolve(video_path)
            if source_path.is_file():
                results.append(
                    self.extractor_class(
                        video_path,
                        source_path,
                        video_sync=self.video_sync,
                        interpolation=self.interpolation,
                        # The track that process uploads with the video.
                        # Sampling reads its track only within the video
                        clip_to_video=self.video_sync is None,
                    )
                )
            else:
                results.append(
                    types.describe_error_metadata(
                        exceptions.MapillaryVideoGPSNotFoundError(
                            f"{self.extractor_class.file_format} file not found for video"
                        ),
                        filename=video_path,
                        filetype=types.FileType.VIDEO,
                    )
                )

        # The videos are geotagged in a pool of processes, each of which would
        # read the track file of its videos. Read here, once, and warn about
        # once, a file that geotags several of them, or that this process read
        # already (see _read_here())
        extractors = [
            result for result in results if isinstance(result, GPXVideoExtractor)
        ]
        num_videos = collections.Counter(
            extractor.gpx_path.resolve() for extractor in extractors
        )
        for extractor in extractors:
            if self._read_here(extractor, num_videos[extractor.gpx_path.resolve()]):
                extractor.read_tracks()

        return results

    def _read_here(self, extractor: GPXVideoExtractor, num_videos: int) -> bool:
        """
        Whether to read the track file of **extractor**, which geotags
        **num_videos** videos, in this process rather than in the pool: if it
        geotags several, or was parsed in this process already. A file of
        each video is left to the pool, which parses them side by side
        """
        return 1 < num_videos or utils.was_gpx_read(extractor.gpx_path)
