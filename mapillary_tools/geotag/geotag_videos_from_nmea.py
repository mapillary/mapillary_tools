# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from .geotag_videos_from_gpx import GeotagVideosFromGPX
from .video_extractors.nmea import NMEAVideoExtractor


class GeotagVideosFromNMEA(GeotagVideosFromGPX):
    """
    Geotag videos from NMEA files, which are placed on the videos as GPX
    files are
    """

    extractor_class = NMEAVideoExtractor
    default_pattern = "%g.nmea"
