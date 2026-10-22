# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import datetime
from pathlib import Path

import pynmea2

from .. import exceptions, geo
from .geotag_images_from_gpx import GeotagImagesFromGPX


class GeotagImagesFromNMEAFile(GeotagImagesFromGPX):
    def __init__(
        self,
        source_path: Path,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
        num_processes: int | None = None,
    ):
        track_error: Exception | None = None
        try:
            points = _read_nmea_points(source_path)
        except exceptions.MapillaryInvalidGPXError as ex:
            points, track_error = [], ex

        super().__init__(
            points,
            use_gpx_start_time=use_gpx_start_time,
            offset_time=offset_time,
            num_processes=num_processes,
        )
        self.track_error = track_error


def _read_nmea_points(source_path: Path) -> list[geo.Point]:
    """
    Read the points of an NMEA file, raising as _read_gpx_points() does for a
    GPX file
    """
    if not source_path.is_file():
        raise exceptions.MapillaryInvalidGPXError(f"NMEA file not found: {source_path}")

    try:
        points = get_lat_lon_time_from_nmea(source_path)
    # OSError: unreadable; ValueError: not text (UnicodeError) or a malformed
    # sentence (pynmea2.ParseError); TypeError: a sentence without its time or
    # date; UnboundLocalError: GGA sentences but no RMC sentence to give their
    # date
    except (OSError, ValueError, TypeError, UnboundLocalError) as ex:
        raise exceptions.MapillaryInvalidGPXError(
            f"{source_path.name} is not a valid NMEA file. "
            "Replace it with a valid NMEA file."
        ) from ex

    if not points:
        raise exceptions.MapillaryInvalidGPXError(
            f"No timestamped points found in the NMEA file {source_path}"
        )

    return points


def get_lat_lon_time_from_nmea(nmea_file: Path) -> list[geo.Point]:
    # NMEA sentences are ASCII. Decode them as UTF-8 on every platform, so
    # that a file that is not text fails to read, not only where UTF-8 is the
    # default encoding
    with nmea_file.open("r", encoding="utf-8") as f:
        lines = f.readlines()
        lines = [line.rstrip("\n\r") for line in lines]

    # Get initial date
    for line in lines:
        if "GPRMC" in line:
            data = pynmea2.parse(line)
            date = data.datetime.date()
            break

    # Parse GPS trace
    points = []
    for line in lines:
        if "GPRMC" in line:
            data = pynmea2.parse(line)
            date = data.datetime.date()

        if "$GPGGA" in line:
            data = pynmea2.parse(line)
            dt = datetime.datetime.combine(date, data.timestamp)
            lat, lon, alt = data.latitude, data.longitude, data.altitude
            points.append(
                geo.Point(
                    time=geo.as_unix_time(dt), lat=lat, lon=lon, alt=alt, angle=None
                )
            )

    points.sort()
    return points
