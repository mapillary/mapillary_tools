# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import sys

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

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
    def _read_here(self, extractor: GPXVideoExtractor, num_videos: int) -> bool:
        # Every NMEA file, which is read once in a process however many videos
        # it geotags, and warned about once
        return True
