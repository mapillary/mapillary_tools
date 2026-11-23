# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import collections
import dataclasses
import datetime
import hashlib
import io
import logging
import multiprocessing
import os
import re
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

import gpxpy
import gpxpy.gpx
import gpxpy.gpxfield
import gpxpy.parser

from .. import exceptions, exiftool_read, geo, telemetry, utils

Track = T.List[geo.Point]
LOG = logging.getLogger(__name__)

# The tracks parsed from the last GPX files read in this process, or the error
# parsing them raised, by path and content: a GPX file that geotags several
# videos, or the samples of a video and then their images, is parsed once.
# Only a few are kept, so that one GPX file per video does not pile up
_PARSED_GPX: collections.OrderedDict[
    tuple[str, str],
    list[Track]
    | gpxpy.gpx.GPXException
    | UnicodeError
    | exceptions.MapillaryInvalidGPXError,
] = collections.OrderedDict()
_MAX_PARSED_GPX = 4

# GPX files are read in chunks of this size to tell whether they changed
_CHUNK_SIZE = 1024 * 1024

# The warnings given in this process about the track files read, so that each
# is given once however many times a file is read
_WARNED: set[tuple[T.Hashable, ...]] = set()

# What a time in a GPX file looks like, for the error of one that cannot be read
_GPX_TIME_EXAMPLE = "2026-08-12T06:32:05.000Z"


def parse_gpx(gpx_file: Path) -> list[Track]:
    """
    Parse the tracks of a GPX file, each a list of points with Unix times
    """
    # Copies, which the caller may change
    return [
        [dataclasses.replace(point) for point in track]
        for track in read_gpx_tracks(gpx_file)
    ]


def read_gpx_tracks(gpx_file: Path) -> list[Track]:
    """
    The tracks of a GPX file as parse_gpx() parses them, parsed once in a
    process for as long as the file does not change. They are shared with
    every other reader of the file, and must not be changed.

    Only track points with a time that gpxpy can read are kept. A file
    without any raises MapillaryInvalidGPXError, which says why; one with
    only some is warned of, once (see _check_track_points()).

    A worker of a pool keeps none: it parses the GPX file of one video only,
    as a file that geotags several videos is read before the pool (see
    GeotagVideosFromGPX), and would free them only when it exits.
    """
    path = str(gpx_file.resolve())
    with gpx_file.open("rb") as f:
        key = (path, _digest(f))
    parsed = _PARSED_GPX.get(key)
    if parsed is None:
        with gpx_file.open("rb") as f:
            reader = _DigestingReader(f)
            try:
                # Parsed from the file opened in text mode, which gpxpy reads
                # whole itself, so that no other copy of its content is kept
                # while it parses. As UTF-8, which GPX files almost always
                # are, on every platform rather than in the encoding of the
                # locale: a byte that is not UTF-8 only turns a letter of a
                # name into U+FFFD, as for NMEA
                parsed = _check_track_points(
                    gpx_file,
                    _parse_gpx_file(
                        io.TextIOWrapper(
                            io.BufferedReader(reader),
                            encoding="utf-8",
                            errors="replace",
                        )
                    ),
                )
            except (
                gpxpy.gpx.GPXException,
                UnicodeError,
                exceptions.MapillaryInvalidGPXError,
            ) as ex:
                parsed = ex
            # By the content parsed, which a file changed since it was looked
            # up by does not have
            key = (path, reader.hexdigest())
        if multiprocessing.parent_process() is None:
            _PARSED_GPX[key] = parsed
            while _MAX_PARSED_GPX < len(_PARSED_GPX):
                _PARSED_GPX.popitem(last=False)
    else:
        _PARSED_GPX.move_to_end(key)

    if isinstance(parsed, Exception):
        raise parsed.with_traceback(None)
    return parsed


def describe_invalid_gpx(gpx_file: Path, ex: Exception) -> str:
    """
    The message of the error for the GPX file **gpx_file** that reading it
    failed with **ex**, which says why

    >>> describe_invalid_gpx(
    ...     Path("a/track.gpx"),
    ...     gpxpy.gpx.GPXXMLSyntaxException(
    ...         "Error parsing XML: not well-formed (invalid token): line 2, column 0",
    ...         None,
    ...     ),
    ... )
    'track.gpx is not a valid GPX file: Error parsing XML: not well-formed (invalid token): line 2, column 0. Replace it with a valid GPX file.'
    >>> describe_invalid_gpx(Path("track.gpx"), PermissionError(13, "Permission denied"))
    'track.gpx is not a valid GPX file: Permission denied. Replace it with a valid GPX file.'
    """
    if isinstance(ex, OSError):
        reason = ex.strerror or str(ex)
    else:
        reason = str(ex)
    because = f": {reason.rstrip('.')}" if reason else ""
    return (
        f"{gpx_file.name} is not a valid GPX file{because}. "
        "Replace it with a valid GPX file."
    )


def was_gpx_read(gpx_file: Path) -> bool:
    """
    Whether the tracks of a GPX file were parsed in this process and are kept
    """
    path = str(gpx_file.resolve())
    return any(key[0] == path for key in _PARSED_GPX)


def warn_once(
    path: Path, what: tuple[T.Hashable, ...], message: str, *args: object
) -> None:
    """
    Log a warning about the track file **path**, unless this process warned
    already of **what** about the file as it is now, whoever read it
    """
    try:
        stat = os.stat(path)
    except OSError:
        file_key: tuple[T.Hashable, ...] = (str(path),)
    else:
        file_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    key = (*file_key, *what)
    if key in _WARNED:
        return
    _WARNED.add(key)
    LOG.warning(message, *args)


def _digest(f: T.BinaryIO) -> str:
    """The SHA-256 digest of the rest of the binary file **f**, read in chunks"""
    digest = hashlib.sha256()
    for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
        digest.update(chunk)
    return digest.hexdigest()


class _DigestingReader(io.RawIOBase):
    """
    A binary file that computes the SHA-256 digest of the bytes read from it

    >>> reader = _DigestingReader(io.BytesIO(b"abc"))
    >>> io.BufferedReader(reader).read()
    b'abc'
    >>> reader.hexdigest() == hashlib.sha256(b"abc").hexdigest()
    True
    """

    def __init__(self, raw: T.BinaryIO) -> None:
        super().__init__()
        self._raw = raw
        self._digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: T.Any) -> int:
        data = self._raw.read(len(buffer))
        buffer[: len(data)] = data
        self._digest.update(data)
        return len(data)

    def readall(self) -> bytes:
        # At once, as a file opened in binary mode reads it, rather than in
        # chunks joined into a second copy
        data = self._raw.read()
        self._digest.update(data)
        return data

    def hexdigest(self) -> str:
        """The digest of the whole file: of the bytes read, and of the rest"""
        for chunk in iter(lambda: self._raw.read(_CHUNK_SIZE), b""):
            self._digest.update(chunk)
        return self._digest.hexdigest()


@dataclasses.dataclass
class _ParsedGPX:
    # A track for each track segment, of its points with a time
    tracks: list[Track]
    # The track points, with a time or without
    num_points: int
    # Whether the file has routes or waypoints, which are not read
    has_routes_or_waypoints: bool


def _parse_gpx_file(f: T.TextIO) -> _ParsedGPX:
    content = _TextFile(f.read())
    try:
        return _parse_gpx_fast(content.text)
    except gpxpy.gpx.GPXXMLSyntaxException:
        # Invalid XML, which gpxpy would fail to parse in the same way
        raise
    except Exception as ex:
        # What the fast reader does not read, gpxpy reads (or rejects) as before
        LOG.debug(f"Reading the GPX file with gpxpy: {ex!r}")
    return _parse_gpx_with_gpxpy(content)


class _TextFile:
    """
    A text file of a string, which it no longer keeps once read: gpxpy reads
    a whole file into a string itself, beside which a string of the content
    passed to it would stay alive while it parses

    >>> f = _TextFile("abc")
    >>> f.read(), f.read(), f.text
    ('abc', '', '')
    """

    def __init__(self, text: str) -> None:
        self.text = text

    def read(self) -> str:
        text, self.text = self.text, ""
        return text


def _parse_gpx_with_gpxpy(xml_or_file: str | _TextFile) -> _ParsedGPX:
    # Read as gpxpy reads a file (or a string), whatever its annotations say
    gpx = gpxpy.parse(T.cast(T.Any, xml_or_file))

    tracks: list[Track] = []
    num_points = 0

    for track in gpx.tracks:
        for segment in track.segments:
            tracks.append([])
            for point in segment.points:
                num_points += 1
                # None too if gpxpy cannot read the time, which it says nothing of
                if point.time is not None:
                    tracks[-1].append(
                        track_point(
                            geo.as_unix_time(point.time),
                            lat=point.latitude,
                            lon=point.longitude,
                            alt=point.elevation,
                        )
                    )

    return _ParsedGPX(
        tracks=tracks,
        num_points=num_points,
        has_routes_or_waypoints=bool(gpx.routes or gpx.waypoints),
    )


# gpxpy.parse() decodes every field of every track point into an object, which
# takes seconds for a GPX file with hundreds of thousands of points. The fast
# reader below reads only time, lat, lon and ele from the track points, but
# checks their other fields as gpxpy does, and lets gpxpy read everything else,
# so that a file it reads gives the same result as _parse_gpx_with_gpxpy().
# Anything else (an invalid file, lxml installed, gpxpy fields it does not
# know) is read by _parse_gpx_with_gpxpy().
#
# Like gpxpy, drop the first default namespace declaration so that GPX elements
# have plain tags (see gpxpy.parser.GPXParser.parse). gpxpy also registers the
# declared namespace prefixes with ElementTree; that only affects how
# ElementTree serializes XML, which mapillary_tools does not do.
_GPXPY_DEFAULT_NAMESPACE = re.compile(r"""\sxmlns=(['"])[^'"]+\1""")

# The text is fed to the XML parser in pieces of this many characters, rather
# than copied whole without the namespace declaration
_FEED_SIZE = 1024 * 1024

# The usual GPX time format (UTC, at most microseconds), whose Unix time is
# computed directly; other formats go through gpxpy's time parser
_UTC_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z"
)
_UNIX_EPOCH_ORDINAL = datetime.date(1970, 1, 1).toordinal()

# How gpxpy checks the text of a track point child element (or a set of the
# values it allows)
_ELE = "ele"
_TIME = "time"
_FLOAT = "float"
_INT = "int"
_Check = T.Union[str, T.FrozenSet[str]]


class _IrregularGPXError(Exception):
    pass


def _track_point_checks(fields: T.Sequence[T.Any]) -> dict[str, _Check] | None:
    """
    Map the tags of track point child elements to how gpxpy converts or checks
    their text, or return None if gpxpy reads track points in a way the fast
    reader does not know.
    """
    checks: dict[str, _Check] = {}
    attributes: list[str] = []
    depth = 0
    for field in fields:
        if isinstance(field, str):
            # Container elements such as 'link:@link' ... '/link'
            depth += -1 if field.startswith("/") else 1
            continue
        if isinstance(field, gpxpy.gpxfield.GPXExtensionsField):
            # Copies the extension elements, never fails
            continue
        if type(field) is not gpxpy.gpxfield.GPXField:
            return None
        converter = field.type_converter
        if converter is None and not field.possible and not field.mandatory:
            # Plain text, never fails
            continue
        if depth:
            return None
        if field.attribute is not None:
            if not (field.mandatory and converter is gpxpy.gpxfield.FLOAT_TYPE):
                return None
            attributes.append(f"{field.name}={field.attribute}")
            continue
        tag = field.tag
        if tag is None or field.mandatory:
            return None
        if converter is None:
            if not field.possible:
                return None
            checks[tag] = frozenset(field.possible)
        elif field.possible:
            return None
        elif converter is gpxpy.gpxfield.FLOAT_TYPE:
            checks[tag] = _ELE if field.name == "elevation" else _FLOAT
        elif converter is gpxpy.gpxfield.INT_TYPE:
            checks[tag] = _INT
        elif converter is gpxpy.gpxfield.TIME_TYPE and field.name == "time":
            checks[tag] = _TIME
        else:
            return None

    if sorted(attributes) != ["latitude=lat", "longitude=lon"]:
        return None
    if checks.get("ele") != _ELE or checks.get("time") != _TIME:
        return None
    return checks


_TRACK_POINT_CHECKS_10 = _track_point_checks(gpxpy.gpx.GPXTrackPoint.gpx_10_fields)
_TRACK_POINT_CHECKS_11 = _track_point_checks(gpxpy.gpx.GPXTrackPoint.gpx_11_fields)


def _parse_gpx_fast(text: str) -> _ParsedGPX:
    if gpxpy.parser.library() != "STDLIB":
        raise _IrregularGPXError("gpxpy parses with lxml")

    try:
        root = _parse_xml_as_gpxpy(text)
    except ET.ParseError as ex:
        # What gpxpy raises when it parses the same text, without parsing it again
        raise gpxpy.gpx.GPXXMLSyntaxException(f"Error parsing XML: {ex}", ex) from ex

    version = root.get("version")
    checks = _TRACK_POINT_CHECKS_11 if version == "1.1" else _TRACK_POINT_CHECKS_10
    if checks is None:
        raise _IrregularGPXError("Unexpected gpxpy track point fields")

    # Take the track points out of the tree, where gpxpy looks for them
    segments: list[list[ET.Element]] = []
    for trk in root:
        if trk.tag == "trk":
            for trkseg in trk:
                if trkseg.tag == "trkseg":
                    segments.append([e for e in trkseg if e.tag == "trkpt"])
                    trkseg[:] = [e for e in trkseg if e.tag != "trkpt"]

    # Let gpxpy read (and check) everything else, as gpxpy.parse() does (which
    # passes it an element and a version that may be None, whatever its
    # annotations say)
    gpx = gpxpy.gpxfield.gpx_fields_from_xml(
        gpxpy.gpx.GPX(), T.cast(T.Any, root), T.cast(T.Any, version)
    )

    seconds_by_minute: dict[str, int | None] = {}
    return _ParsedGPX(
        tracks=[
            _read_track_points(trkpts, checks, seconds_by_minute) for trkpts in segments
        ],
        num_points=sum(len(trkpts) for trkpts in segments),
        has_routes_or_waypoints=bool(gpx.routes or gpx.waypoints),
    )


def _parse_xml_as_gpxpy(text: str) -> ET.Element:
    """
    The XML element of the text without its first default namespace
    declaration, as gpxpy parses it
    """
    match = _GPXPY_DEFAULT_NAMESPACE.search(text)
    if match is None:
        spans = [(0, len(text))]
    else:
        spans = [(0, match.start()), (match.end(), len(text))]

    # As ET.XML() parses a string
    parser = ET.XMLParser(target=ET.TreeBuilder())
    for start, end in spans:
        for piece_start in range(start, end, _FEED_SIZE):
            parser.feed(text[piece_start : min(piece_start + _FEED_SIZE, end)])
    return parser.close()


def _read_track_points(
    trkpts: list[ET.Element],
    checks: dict[str, _Check],
    seconds_by_minute: dict[str, int | None],
) -> Track:
    track: Track = []

    for trkpt in trkpts:
        lat_text, lon_text = trkpt.get("lat"), trkpt.get("lon")
        if lat_text is None or lon_text is None:
            raise _IrregularGPXError("Track point without lat or lon")
        # Converted like gpxpy.gpxfield.FLOAT_TYPE does
        lat, lon = float(lat_text.strip()), float(lon_text.strip())

        ele: float | None = None
        time_text: str | None = None
        # gpxpy reads the first child element with each tag
        seen: set[str] = set()
        for child in trkpt:
            tag = child.tag
            check = checks.get(tag)
            if check is None or tag in seen:
                continue
            seen.add(tag)
            child_text = child.text
            if child_text is None:
                continue
            if check is _ELE:
                ele = float(child_text.strip())
            elif check is _TIME:
                time_text = child_text
            elif check is _FLOAT:
                float(child_text.strip())
            elif check is _INT:
                int(child_text.strip())
            elif child_text not in check:
                raise _IrregularGPXError(f"Invalid <{tag}> value {child_text!r}")

        if time_text is not None:
            unix_time = _unix_time_from_gpx_time(time_text, seconds_by_minute)
            if unix_time is not None:
                track.append(track_point(unix_time, lat=lat, lon=lon, alt=ele))

    return track


def _unix_time_from_gpx_time(
    text: str, seconds_by_minute: dict[str, int | None]
) -> float | None:
    """
    Return geo.as_unix_time() of the time gpxpy reads from the text, or None
    if gpxpy reads no time.
    """
    if _UTC_TIME.fullmatch(text) is not None:
        # YYYY-MM-DDTHH:MM:SS[.ffffff]Z
        minute_text = text[:16]
        if minute_text in seconds_by_minute:
            minute_seconds = seconds_by_minute[minute_text]
        else:
            minute_seconds = seconds_by_minute[minute_text] = _unix_seconds_of_minute(
                minute_text
            )
        second = int(text[17:19])
        if minute_seconds is not None and second < 60:
            fraction = text[20:-1]
            microseconds = int(fraction.ljust(6, "0")) if fraction else 0
            # The same correctly rounded division as datetime.timestamp()
            return ((minute_seconds + second) * 1_000_000 + microseconds) / 1_000_000

    time = gpxpy.gpxfield.TIME_TYPE.from_string(text)
    if time is None:
        return None
    return geo.as_unix_time(time)


def _unix_seconds_of_minute(minute_text: str) -> int | None:
    # YYYY-MM-DDTHH:MM
    hour, minute = int(minute_text[11:13]), int(minute_text[14:16])
    if hour >= 24 or minute >= 60:
        return None
    try:
        date = datetime.date(
            int(minute_text[:4]), int(minute_text[5:7]), int(minute_text[8:10])
        )
    except ValueError:
        return None
    days = date.toordinal() - _UNIX_EPOCH_ORDINAL
    return days * 86400 + hour * 3600 + minute * 60


def _check_track_points(gpx_file: Path, parsed: _ParsedGPX) -> list[Track]:
    """
    The tracks of the parsed GPX file **gpx_file**, of its track points with
    a time: one without cannot be placed on a video, or matched with an
    image. Raise MapillaryInvalidGPXError, which says why, if it has none,
    and warn once of the points left out whose time cannot be read.

    A point without a <time>, which GPX allows, is left out without a word:
    ExifTool writes one only on the points of a GoPro video that have a GPS
    time. A point whose time gpxpy cannot read is left out as gpxpy leaves
    it, without a time: no time is guessed from the text, as of
    06:32:05.123.456Z, whose second fraction could mean anything.
    """
    if not parsed.num_points:
        not_read = (
            "; routes and waypoints are not read"
            if parsed.has_routes_or_waypoints
            else ""
        )
        raise exceptions.MapillaryInvalidGPXError(
            f"{gpx_file.name} has no track points{not_read}"
        )

    num_timeless = parsed.num_points - sum(len(track) for track in parsed.tracks)
    if not num_timeless:
        return parsed.tracks

    unreadable: _UnreadableTimes | None
    try:
        unreadable = _read_unreadable_times(gpx_file)
    except Exception:
        # Why is not known, which must not fail the file otherwise
        unreadable = None

    if num_timeless == parsed.num_points:
        if unreadable is None:
            why = ""
        elif unreadable.first is None:
            why = ": its track points have no <time>"
        else:
            why = f": {unreadable.first!r} is not a GPX time, which looks like {_GPX_TIME_EXAMPLE}"
        raise exceptions.MapillaryInvalidGPXError(
            f"{gpx_file.name} has no track point with a time that can be read{why}"
        )

    if unreadable is None:
        warn_once(
            gpx_file,
            ("unreadable times", num_timeless, parsed.num_points),
            "Ignoring %d of the %d points in the GPX file %s, whose times cannot be read",
            num_timeless,
            parsed.num_points,
            gpx_file,
        )
    elif unreadable.first is not None:
        warn_once(
            gpx_file,
            ("unreadable times", unreadable.count, parsed.num_points),
            "Ignoring %d of the %d points in the GPX file %s, whose times cannot be read (e.g. %r)",
            unreadable.count,
            parsed.num_points,
            gpx_file,
            unreadable.first,
        )
    return parsed.tracks


@dataclasses.dataclass
class _UnreadableTimes:
    # The text of the first, or None if there are none
    first: str | None
    count: int


def _read_unreadable_times(gpx_file: Path) -> _UnreadableTimes:
    """
    The <time> of the track points in the GPX file **gpx_file** that gpxpy
    cannot read. gpxpy reads no time for such a point, as for a point without
    a <time>, and keeps no trace of the text, so the file is read again, as
    XML decoded as gpxpy reads it (see read_gpx_tracks()). That raises if the
    file changed since, or if gpxpy read it with another XML parser (lxml).

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     gpx = Path(tmp) / "track.gpx"
    ...     _ = gpx.write_text(
    ...         '<gpx xmlns="http://www.topografix.com/GPX/1/1">'
    ...         "<metadata><time>bad</time></metadata><trk><trkseg>"
    ...         '<trkpt lat="1" lon="2"><time>2026-08-12T06:32:05Z</time></trkpt>'
    ...         '<trkpt lat="1" lon="2"></trkpt>'
    ...         '<trkpt lat="1" lon="2"><time> 2026-08-12T06:32:06Z</time></trkpt>'
    ...         '<trkpt lat="1" lon="2"><time>2026-08-12</time></trkpt>'
    ...         "</trkseg></trk></gpx>"
    ...     )
    ...     _read_unreadable_times(gpx)
    _UnreadableTimes(first=' 2026-08-12T06:32:06Z', count=2)
    """
    unreadable = _UnreadableTimes(first=None, count=0)
    # The local names of the elements that the element read is in
    parents: list[str] = []
    with gpx_file.open("r", encoding="utf-8", errors="replace") as f:
        # Fed text, as gpxpy is, the parser ignores the encoding the file
        # declares
        for event, element in ET.iterparse(f, events=("start", "end")):
            name = element.tag.rpartition("}")[2]
            if event == "start":
                parents.append(name)
                continue
            parents.pop()
            if name == "time" and parents[-1:] == ["trkpt"]:
                text = element.text or ""
                if not _is_gpx_time(text):
                    unreadable.count += 1
                    if unreadable.first is None:
                        unreadable.first = text
            elif name == "trkpt":
                # Read, so that a long track is not kept whole
                element.clear()
    return unreadable


def _is_gpx_time(text: str) -> bool:
    """
    Whether gpxpy can read the time **text** of a GPX file

    >>> _is_gpx_time("2026-08-12T06:32:05.000Z")
    True
    >>> _is_gpx_time("2026-08-12T06:32:05.000.000Z")
    False
    >>> _is_gpx_time("")
    False
    """
    try:
        return gpxpy.gpxfield.parse_time(text) is not None
    # gpxpy reads a time that raises anything as none
    except Exception:
        return False


def track_point(
    unix_time: float, lat: float, lon: float, alt: float | None
) -> telemetry.CAMMGPSPoint:
    """
    A point of a track read from a file beside a video (GPX or NMEA), at its
    Unix time, as it is written to the CAMM track uploaded with the video
    """
    return telemetry.CAMMGPSPoint(
        time=unix_time,
        lat=lat,
        lon=lon,
        alt=alt,
        angle=None,
        epoch_time=unix_time,
        gps_fix_type=3 if alt is not None else 2,
        horizontal_accuracy=0.0,
        vertical_accuracy=0.0,
        velocity_east=0.0,
        velocity_north=0.0,
        velocity_up=0.0,
        speed_accuracy=0.0,
    )


def index_rdf_description_by_path(xml_paths: T.Sequence[Path]) -> dict[str, ET.Element]:
    rdf_by_path: dict[str, ET.Element] = {}

    for xml_path in utils.find_xml_files(xml_paths):
        try:
            etree = ET.parse(xml_path)
        except Exception as ex:
            LOG.warning(
                f"Failed to parse {xml_path}: {ex}",
                exc_info=LOG.isEnabledFor(logging.DEBUG),
            )
            continue

        rdf_by_path.update(
            exiftool_read.index_rdf_description_by_path_from_xml_element(
                etree.getroot()
            )
        )

    return rdf_by_path
