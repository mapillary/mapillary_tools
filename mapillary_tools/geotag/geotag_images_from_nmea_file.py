# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import datetime
import logging
import re
from pathlib import Path

import pynmea2

from .. import exceptions, geo
from .geotag_images_from_gpx import GeotagImagesFromGPX


LOG = logging.getLogger(__name__)

# An RMC or a GGA sentence, from any talker: GP (GPS), GN (several systems),
# GL (GLONASS), GA (Galileo), ...
_SENTENCE_RE = re.compile(r"\$[A-Z]{2}(RMC|GGA),")


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
    """
    Read the fixes of an NMEA file: the time and position of each GGA
    sentence, on the date of the RMC sentence of the same fix. Receivers
    write the GGA sentence of a fix before or after its RMC sentence, so a
    GGA sentence takes the date that puts it nearest the fix before it or the
    RMC sentence after it, whichever it is nearer: the first fix after
    midnight falls on the next day, also when the RMC sentence with that date
    follows it.

    Receivers log sentences without a fix, such as before they acquire one:
    RMC sentences that are void or have no date or time, and GGA sentences
    without a time or a fix, which give their position as 0, 0. They are
    skipped. A file without the date of any fix gives no points.

    A receiver may log a fix from several talkers, such as $GPGGA and $GNGGA,
    for the same time: only the first is read, so that no two points share a
    time.
    """
    # NMEA sentences are ASCII. Decode them as UTF-8 on every platform, so
    # that a file that is not text fails to read, not only where UTF-8 is the
    # default encoding
    with nmea_file.open("r", encoding="utf-8") as f:
        lines = f.readlines()
        lines = [line.rstrip("\n\r") for line in lines]

    messages = [pynmea2.parse(line) for line in lines if _SENTENCE_RE.search(line)]

    # The RMC sentences with a date, and the GGA sentences with a fix
    fixes = [
        m
        for m in messages
        if (isinstance(m, pynmea2.RMC) and _fix_date(m) is not None)
        or (isinstance(m, pynmea2.GGA) and _has_fix(m))
    ]
    if not any(isinstance(m, pynmea2.RMC) for m in fixes):
        if fixes:
            LOG.warning(
                "Ignoring the %d fixes in the NMEA file %s, as no RMC sentence gives their date",
                len(fixes),
                nmea_file,
            )
        return []

    # The datetime of the next RMC sentence after each fix
    next_rmc: list[datetime.datetime | None] = []
    upcoming: datetime.datetime | None = None
    for message in reversed(fixes):
        next_rmc.append(upcoming)
        if isinstance(message, pynmea2.RMC):
            upcoming = _rmc_datetime(message)
    next_rmc.reverse()

    # Parse GPS trace
    points = []
    times: set[float] = set()
    last: datetime.datetime | None = None
    for message, after in zip(fixes, next_rmc):
        if isinstance(message, pynmea2.RMC):
            last = _rmc_datetime(message)
            continue

        last = _gga_datetime(message.timestamp, last, after)
        time = geo.as_unix_time(last)
        if time in times:
            continue
        times.add(time)
        lat, lon, alt = message.latitude, message.longitude, message.altitude
        points.append(geo.Point(time=time, lat=lat, lon=lon, alt=alt, angle=None))

    points.sort()
    return points


def _rmc_datetime(message: pynmea2.RMC) -> datetime.datetime:
    return datetime.datetime.combine(message.datestamp, message.timestamp)


def _gga_datetime(
    time: datetime.time,
    before: datetime.datetime | None,
    after: datetime.datetime | None,
) -> datetime.datetime:
    """
    The datetime of a GGA sentence at **time** of day, after the fix **before**
    it and before the RMC sentence **after** it: on the date, or the day before
    or after it, that puts it nearest the one of them it is nearer

    >>> before = datetime.datetime(2022, 12, 21, 23, 59, 59)
    >>> after = datetime.datetime(2022, 12, 22, 0, 0, 0)
    >>> _gga_datetime(datetime.time(0, 0, 0), before, after)
    datetime.datetime(2022, 12, 22, 0, 0)
    >>> _gga_datetime(datetime.time(0, 0, 0), before, None)
    datetime.datetime(2022, 12, 22, 0, 0)
    >>> _gga_datetime(datetime.time(23, 59, 59), None, after)
    datetime.datetime(2022, 12, 21, 23, 59, 59)

    The first fix of a log of another day, appended to the file:

    >>> after = datetime.datetime(2022, 12, 24, 9, 0, 0)
    >>> _gga_datetime(datetime.time(9, 0, 0), before, after)
    datetime.datetime(2022, 12, 24, 9, 0)
    """
    candidates = [
        (datetime.datetime.combine(near.date() + datetime.timedelta(days), time), near)
        for near in (before, after)
        if near is not None
        for days in (-1, 0, 1)
    ]
    return min(candidates, key=lambda candidate: abs(candidate[0] - candidate[1]))[0]


def _fix_date(message: pynmea2.RMC) -> datetime.date | None:
    """The date of an RMC sentence, or None if it is void or has no date or time"""
    if message.status != "A" or message.timestamp is None:
        return None
    return message.datestamp


def _has_fix(message: pynmea2.GGA) -> bool:
    """Whether a GGA sentence has a time and a fix (quality 0 is none)"""
    return message.timestamp is not None and bool(message.gps_qual)
