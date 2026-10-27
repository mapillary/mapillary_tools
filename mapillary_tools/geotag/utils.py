# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import collections
import dataclasses
import hashlib
import io
import logging
import multiprocessing
import os
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

import gpxpy
import gpxpy.gpxfield

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
    gpx = gpxpy.parse(f)

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
