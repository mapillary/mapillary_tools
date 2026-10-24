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
    data = gpx_file.read_bytes()
    key = (str(gpx_file.resolve()), hashlib.sha256(data).hexdigest())
    parsed = _PARSED_GPX.get(key)
    if parsed is None:
        try:
            # Decoded as a file opened in text mode would be, and parsed
            # without the bytes, as a file is
            text = io.TextIOWrapper(io.BytesIO(data)).read()
            del data
            parsed = _parse_gpx_text(text)
        except (gpxpy.gpx.GPXException, UnicodeError) as ex:
            parsed = ex
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


def _parse_gpx_text(text: str) -> list[Track]:
    gpx = gpxpy.parse(text)

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
