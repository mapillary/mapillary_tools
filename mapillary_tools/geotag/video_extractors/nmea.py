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

from ... import exceptions, geo
from ..geotag_images_from_nmea_file import get_lat_lon_time_from_nmea
from ..utils import track_point
from .gpx import GPXVideoExtractor


class NMEAVideoExtractor(GPXVideoExtractor):
    """
    Geotag a video from the track in an NMEA file, placed on the video as a
    GPX track is
    """

    file_format = "NMEA"

    @override
    def _read_tracks(self) -> list[list[geo.Point]]:
        try:
            points = get_lat_lon_time_from_nmea(self.gpx_path)
        # OSError: unreadable; ValueError: not text, or
        # malformed sentences and no fix
        except (OSError, ValueError) as ex:
            raise exceptions.MapillaryInvalidGPXError(
                f"{self.gpx_path.name} is not a valid NMEA file. "
                "Replace it with a valid NMEA file."
            ) from ex

        return [[track_point(p.time, p.lat, p.lon, p.alt) for p in points]]
