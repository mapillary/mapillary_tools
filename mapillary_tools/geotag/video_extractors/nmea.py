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

    # The tracks of the NMEA file, or the error reading it, once read_tracks()
    # has read them
    _tracks: list[list[geo.Point]] | exceptions.MapillaryInvalidGPXError | None = None

    def read_tracks(self) -> None:
        """
        Read the tracks of the NMEA file now, for extract() to place, rather
        than when it runs, which can be in another process
        """
        try:
            self._tracks = self._read_tracks()
        except exceptions.MapillaryInvalidGPXError as ex:
            self._tracks = ex
        except Exception:
            # Left for extract() to raise again, and to be reported for the
            # video as any unexpected error is
            pass

    @override
    def _parse_tracks(self) -> list[list[geo.Point]]:
        if self._tracks is None:
            return self._read_tracks()
        if isinstance(self._tracks, exceptions.MapillaryInvalidGPXError):
            raise self._tracks
        return self._tracks

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
