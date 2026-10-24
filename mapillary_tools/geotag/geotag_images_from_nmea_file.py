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

# The checksum that ends a sentence: *HH
_CHECKSUM_RE = re.compile(r"\*[0-9A-Fa-f]{2}\s*$")

# The time of a sentence (hhmmss, and a fraction of a second), and the date of
# an RMC sentence (ddmmyy). pynmea2 reads a field cut short as another time or
# date: an RMC sentence cut inside its date "2212" as 2012-02-02
_TIME_RE = re.compile(r"\d{6}(\.\d+)?")
_DATE_RE = re.compile(r"\d{6}")


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
    # OSError: unreadable; ValueError: not text (UnicodeError), or malformed
    # sentences and no fix; TypeError: a sentence without its time or date;
    # UnboundLocalError: GGA sentences but no RMC sentence to give their date
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

    A malformed sentence, such as one whose checksum does not match, or one
    cut short, is skipped with a warning. A file of which no fix can be read
    and that has malformed sentences raises ValueError, as one that is not
    text does.
    """
    # NMEA sentences are ASCII. Decode them as UTF-8 on every platform, so
    # that a file that is not text fails to read, not only where UTF-8 is the
    # default encoding
    with nmea_file.open("r", encoding="utf-8") as f:
        lines = f.readlines()
        lines = [line.rstrip("\n\r") for line in lines]

    # (line number, line) of each RMC and GGA sentence
    sentences = [
        (number, line)
        for number, line in enumerate(lines, start=1)
        if _SENTENCE_RE.search(line)
    ]
    # Receivers end each sentence with its checksum, or none of them. One
    # without, where the others have theirs, was cut short, such as the last
    # one of a log when the recording stopped
    checksummed = any(_CHECKSUM_RE.search(line) for _, line in sentences)

    messages = []
    # (line number, line, error) of each malformed sentence
    malformed: list[tuple[int, str, ValueError]] = []
    for number, line in sentences:
        try:
            messages.append(_parse_sentence(line, checksummed=checksummed))
        except ValueError as ex:
            malformed.append((number, line, ex))

    points = _read_fixes(messages, nmea_file)

    if malformed:
        number, line, error = malformed[0]
        if not points:
            raise error
        LOG.warning(
            "Skipping %d of the %d RMC and GGA sentences of the NMEA file %s, which are malformed, the first on line %d (%s): %s",
            len(malformed),
            len(malformed) + len(messages),
            nmea_file,
            number,
            error,
            line,
        )

    return points


def _read_fixes(
    messages: list[pynmea2.NMEASentence], nmea_file: Path
) -> list[geo.Point]:
    """
    The points of the fixes of the NMEA sentences read from **nmea_file**, as
    get_lat_lon_time_from_nmea() describes
    """
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


def _parse_sentence(line: str, checksummed: bool = False) -> pynmea2.NMEASentence:
    """
    Parse an NMEA sentence, raising ValueError if it is malformed: if it does
    not parse or its checksum does not match, if it has no checksum but should
    (**checksummed**), if its time or the date of an RMC sentence is not
    hhmmss[.ss] or ddmmyy, or if a field that a fix is read from does not
    parse, which pynmea2 leaves a string

    >>> _parse_sentence("$GPGGA,0246,3735.30670,N,12220.25810,W,1,08,1.0,0.0,M,0.0,M,,*64")
    Traceback (most recent call last):
    ...
    ValueError: malformed timestamp: '0246'
    >>> _parse_sentence("$GPGGA,024636.00,3735.30670,N,12220.25810,W,1,08,1.0,0.0,M,0.0,M,,*00")
    Traceback (most recent call last):
    ...
    ValueError: checksum does not match: 00 != 4F
    >>> _parse_sentence("$GPRMC,024636.00,A,3735.30670,N,12220.25810,W,0.0,0.0,2212", checksummed=True)
    Traceback (most recent call last):
    ...
    ValueError: no checksum
    >>> _parse_sentence("$GPRMC,024636.00,A,3735.30670,N,12220.25810,W,0.0,0.0,2212")
    Traceback (most recent call last):
    ...
    ValueError: malformed datestamp: '2212'
    """
    if checksummed and not _CHECKSUM_RE.search(line):
        raise ValueError("no checksum")

    try:
        message = pynmea2.parse(line)
    except pynmea2.ParseError as ex:
        # Its argument is (reason, sentence)
        raise ValueError(ex.args[0][0]) from ex

    formats = {"timestamp": _TIME_RE}
    if isinstance(message, pynmea2.RMC):
        formats["datestamp"] = _DATE_RE
    for name, pattern in formats.items():
        value = _raw_field(message, name)
        # An empty field is no time or date, as before a fix
        if value and not pattern.fullmatch(value):
            raise ValueError(f"malformed {name}: {value!r}")

    fields: dict[str, type] = {}
    if isinstance(message, pynmea2.RMC):
        fields = {"timestamp": datetime.time, "datestamp": datetime.date}
    elif isinstance(message, pynmea2.GGA):
        fields = {"timestamp": datetime.time, "gps_qual": int, "altitude": float}
    for name, expected_type in fields.items():
        value = getattr(message, name)
        if value is not None and not isinstance(value, expected_type):
            raise ValueError(f"malformed {name}: {value!r}")

    if isinstance(message, pynmea2.GGA) and _has_fix(message):
        # pynmea2 computes the position from its fields when it is read,
        # raising ValueError if they are malformed
        _position = (message.latitude, message.longitude)

    return message


def _raw_field(message: pynmea2.NMEASentence, name: str) -> str:
    """The text of the field **name** of a sentence, empty if it is cut off"""
    idx = message.name_to_idx[name]
    return message.data[idx] if idx < len(message.data) else ""


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
