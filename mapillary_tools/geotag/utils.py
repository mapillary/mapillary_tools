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

from .. import exiftool_read, geo, telemetry, utils

Track = T.List[geo.Point]
LOG = logging.getLogger(__name__)

# The tracks parsed from the last GPX files read in this process, or the error
# parsing them raised, by path and content: a GPX file that geotags several
# videos, or the samples of a video and then their images, is parsed once.
# Only a few are kept, so that one GPX file per video does not pile up
_PARSED_GPX: collections.OrderedDict[
    tuple[str, str], list[Track] | gpxpy.gpx.GPXException | UnicodeError
] = collections.OrderedDict()
_MAX_PARSED_GPX = 4

# GPX files are read in chunks of this size to tell whether they changed
_CHUNK_SIZE = 1024 * 1024

# The warnings given in this process about the track files read, so that each
# is given once however many times a file is read
_WARNED: set[tuple[T.Hashable, ...]] = set()


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
                # while it parses
                parsed = _parse_gpx_file(io.TextIOWrapper(io.BufferedReader(reader)))
            except (gpxpy.gpx.GPXException, UnicodeError) as ex:
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


def _parse_gpx_file(f: T.TextIO) -> list[Track]:
    gpx = gpxpy.parse(f)

    tracks: list[Track] = []

    for track in gpx.tracks:
        for segment in track.segments:
            tracks.append([])
            for point in segment.points:
                if point.time is not None:
                    tracks[-1].append(
                        track_point(
                            geo.as_unix_time(point.time),
                            lat=point.latitude,
                            lon=point.longitude,
                            alt=point.elevation,
                        )
                    )

    return tracks


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
