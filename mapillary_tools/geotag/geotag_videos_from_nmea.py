# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import types
from .geotag_videos_from_gpx import GeotagVideosFromGPX
from .video_extractors.gpx import GPXVideoExtractor
from .video_extractors.nmea import NMEAVideoExtractor


class GeotagVideosFromNMEA(GeotagVideosFromGPX):
    """
    Geotag videos from NMEA files, which are placed on the videos as GPX
    files are
    """

    extractor_class = NMEAVideoExtractor
    default_pattern = "%g.nmea"

    @override
    def _generate_video_extractors(
        self, video_paths: T.Sequence[Path]
    ) -> T.Sequence[GPXVideoExtractor | types.ErrorMetadata]:
        extractors = super()._generate_video_extractors(video_paths)
        # Read each NMEA file here, once however many videos it geotags, and
        # warn about it once: the videos are geotagged in a pool of processes,
        # each of which would read it again
        for extractor in extractors:
            if isinstance(extractor, NMEAVideoExtractor):
                extractor.read_tracks()
        return extractors
