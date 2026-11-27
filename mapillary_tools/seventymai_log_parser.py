# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Read the GPS of a 70mai dashcam clip from the GPS log that the camera writes beside
its clips (GPSData000001.txt): the clips themselves have no GPS that can be read.

The log is text: a line "$V02" each time the camera starts logging, then a row per
fix, for many clips and hours:

    1717236900,A,47.376900,8.541700,9000,1250,-81,9,40,NO20240601-121500-000123F.MP4,0,0,0

The columns are the Unix time (UTC), the fix status (A: valid), the latitude and the
longitude in degrees, the course in centidegrees, the speed in cm/s, three unknown
values, the clip being recorded, and three unknown values. Rows that are not valid
fixes have no position, or a placeholder time (0, -28801, the start of 2021), or
null island. Some cameras write such rows, naming the clip, until they have a fix.
Others write none, or name no clip in them ("0").

The rows carry the GPS time of the fixes, not their time in the video. A camera
that has a fix when a clip starts, as in the middle of a recording, writes the first
row of the clip within about a second of its start, and the last within a few
seconds of its end: it writes a row every 1 to 1.5 seconds, and repeats a stale fix
while its GPS stalls, for up to 5 seconds. So the first fix of the clip is taken as
its start. A camera that is switched on records before it has a fix: its first fix
comes seconds, at times minutes, into the clip. Then the last fix of the clip is
taken as its end instead, if the camera wrote rows without a fix that name the clip
before its first fix, or if the clip is the first that the camera logged after it
started logging ("$V02") and its fixes span much less than the clip. Any other clip
whose fixes span much less ended early, as the camera stopped recording it: the
next line of the log is "$V02".
"""

from __future__ import annotations

import functools
import logging
import math
import os
import typing as T
from pathlib import Path

import construct as C

from . import telemetry
from .mp4 import construct_mp4_parser as cparser, simple_mp4_parser as sparser

LOG = logging.getLogger(__name__)

# GPSData000001.txt, GPSData000002.txt, ... compared case-insensitively
_LOG_NAME_PREFIX = "gpsdata"
_LOG_NAME_SUFFIX = ".txt"

_NUM_COLUMNS = 13
_CLIP_COLUMN = 9

# The fixes of the first clip that the camera logged after it started logging
# span all of it but for a stall of its GPS, up to 6 seconds in the logs seen,
# if it had a fix from the start of the clip. If its first fix came late, as
# when the camera was switched on, they span at least 9 seconds less
_MAX_MISSING_SECONDS = 8.0

# Where the first run of the rows of a clip is in a log: right after "$V02" (or
# after rows that name no clip), at the top of the log, or after rows of another
# clip
_AFTER_HEADER = "header"
_AT_TOP = "top"
_AFTER_CLIP = "clip"

# The fixes may span a few seconds more than the clip, as the camera may repeat
# the last fix of the previous clip as the first of the next. More than this,
# they are not of the clip as it is (e.g. a timelapse)
_MAX_EXCESS_SECONDS = 5.0


class _Row(T.NamedTuple):
    # (Unix time, latitude, longitude), or None if the row is not a valid fix
    fix: tuple[int, float, float] | None


def extract_points(video_path: Path) -> list[telemetry.GPSPoint] | None:
    """
    Return the GPS points of the clip from the logs in its folder, sorted by time,
    or None if there are no logs, no valid fixes of the clip in them, or they do
    not fit the clip. Point time is the time in the video, and epoch_time is the
    Unix time of the fix.
    """
    folder = video_path.parent
    try:
        log_paths = _find_log_paths(folder, folder.stat().st_mtime_ns)
    except OSError as ex:
        LOG.debug("Unable to list %s for GPS logs: %s", folder, ex)
        return None

    if not log_paths:
        return None

    # The rows of the clip in the order the camera wrote them, which may be
    # continued in the next log, and whether they are the first rows that the
    # camera wrote after it started logging
    rows: list[_Row] = []
    first_logged: bool | None = None
    for log_idx, log_path in enumerate(log_paths):
        try:
            clip_rows, begins = _read_clip_rows(log_path, video_path.stem.casefold())
        except OSError as ex:
            LOG.warning("Unable to read the GPS log %s: %s", log_path, ex)
            continue
        if first_logged is None and begins is not None:
            # The top of a later log continues the previous log
            first_logged = begins == _AFTER_HEADER or (
                begins == _AT_TOP and log_idx == 0
            )
        rows.extend(clip_rows)

    fix_indices = [idx for idx, row in enumerate(rows) if row.fix is not None]
    if not fix_indices:
        LOG.debug("No fixes of %s in the GPS logs %s", video_path.name, log_paths)
        return None

    duration = _read_duration(video_path)
    if duration is None:
        return None

    # The positions by time, without the stale fixes that the camera repeats
    fixes: dict[int, tuple[float, float]] = {}
    for idx in fix_indices:
        fix = rows[idx].fix
        assert fix is not None
        fixes.setdefault(fix[0], (fix[1], fix[2]))
    times = sorted(fixes)

    span = times[-1] - times[0]
    if duration + _MAX_EXCESS_SECONDS < span:
        LOG.warning(
            "Ignoring the GPS log of %s: its fixes span %d seconds, more than the %.1f seconds of the video",
            video_path.name,
            span,
            duration,
        )
        return None

    no_fix_at_start = 0 < fix_indices[0]
    no_fix_at_end = fix_indices[-1] < len(rows) - 1
    if no_fix_at_start and no_fix_at_end:
        LOG.warning(
            "Ignoring the GPS log of %s: the camera had no fix at the start nor at the end of the clip, so its fixes cannot be placed in the video",
            video_path.name,
        )
        return None

    if no_fix_at_start or (
        first_logged and not no_fix_at_end and _MAX_MISSING_SECONDS < duration - span
    ):
        # The camera got its first fix after it started recording the clip
        start_time = float(times[-1]) - duration
    else:
        start_time = float(times[0])

    return [
        telemetry.GPSPoint(
            time=t - start_time,
            lat=fixes[t][0],
            lon=fixes[t][1],
            alt=None,
            angle=None,
            epoch_time=float(t),
            fix=None,
            precision=None,
            ground_speed=None,
        )
        for t in times
        # Leave out the fixes that span more than the clip: the CAMM track of
        # the upload starts at time 0
        if start_time <= t
    ]


@functools.lru_cache(maxsize=64)
def _find_log_paths(folder: Path, mtime_ns: int) -> list[Path]:
    """
    The GPS logs in the folder (GPSData000001.txt, ...), in the order of their
    names. The modification time of the folder is part of the cache key
    """
    with os.scandir(folder) as entries:
        names = [
            entry.name
            for entry in entries
            if entry.name.casefold().startswith(_LOG_NAME_PREFIX)
            and entry.name.casefold().endswith(_LOG_NAME_SUFFIX)
            and entry.is_file()
        ]
    return [folder / name for name in sorted(names, key=str.casefold)]


def _read_clip_rows(log_path: Path, key: str) -> tuple[list[_Row], str | None]:
    """
    The rows of the clip in the log, and where their first run is in it (see
    _AFTER_HEADER), or None if the log has no rows of the clip
    """
    stat = log_path.stat()
    index = _index_log(log_path, stat.st_size, stat.st_mtime_ns)
    runs = index.get(key)
    if not runs:
        return [], None

    rows: list[_Row] = []
    with log_path.open("rb") as fp:
        for start, end, _ in runs:
            fp.seek(start)
            for line in fp.read(end - start).splitlines():
                row = _parse_row(line)
                if row is not None:
                    rows.append(row)
    return rows, runs[0][2]


@functools.lru_cache(maxsize=16)
def _index_log(
    log_path: Path, size: int, mtime_ns: int
) -> dict[str, list[tuple[int, int, str]]]:
    """
    Index the log by clip: the byte ranges of the runs of lines that name each
    clip, and where each run is (see _AFTER_HEADER). A log may be tens of MB and
    is read by every clip it covers, so it is read once. The size and the
    modification time of the log are part of the cache key
    """
    index: dict[str, list[tuple[int, int, str]]] = {}

    with log_path.open("rb") as fp:
        offset = 0
        run_name: bytes | None = None
        run_start = 0
        run_where = position = _AT_TOP
        for line in fp:
            fields = line.split(b",", _CLIP_COLUMN + 1)
            name = fields[_CLIP_COLUMN] if _CLIP_COLUMN < len(fields) - 1 else None
            if name != run_name:
                key = None if run_name is None else _clip_key(run_name)
                if key is not None:
                    index.setdefault(key, []).append((run_start, offset, run_where))
                    position = _AFTER_CLIP
                run_name = name
                run_start = offset
                run_where = position
            if line.startswith(b"$"):
                position = _AFTER_HEADER
            offset += len(line)
        key = None if run_name is None else _clip_key(run_name)
        if key is not None:
            index.setdefault(key, []).append((run_start, offset, run_where))

    return index


def _clip_key(name: bytes) -> str | None:
    """
    The clip that a row names, as the stem of its file name, or None if the row
    names none. Some cameras leave characters of a longer name after the extension

    >>> _clip_key(b"NO20240601-121500-000123F.MP44")
    'no20240601-121500-000123f'
    >>> _clip_key(b"NO20240601-121500-000123F.mp4")
    'no20240601-121500-000123f'
    >>> _clip_key(b"0") is None
    True
    """
    text = name.strip().decode("latin-1")
    if "." not in text:
        return None
    stem = text.rsplit(".", 1)[0]
    if not stem:
        return None
    return stem.casefold()


def _parse_row(line: bytes) -> _Row | None:
    """
    Parse a row of the log, or return None if it is malformed

    >>> _parse_row(b"1717236900,A,47.376900,8.541700,9000,1250,-81,9,40,NO20240601-121500-000123F.MP4,0,0,0")
    _Row(fix=(1717236900, 47.3769, 8.5417))
    >>> _parse_row(b"1609430400,V,0.000000,0.000000,0,0,0.00,0.00,0.00,NO20240601-121500-000123F.mp4,0,0,0")
    _Row(fix=None)
    >>> _parse_row(b"-28801,A,47.376900,8.541700,9000,1250,100,1,-18,NO20240601-121500-000123F.MP4,0,0,0")
    _Row(fix=None)
    >>> _parse_row(b"1717236900,A,47.376900,8.5417") is None
    True
    """
    fields = line.strip().split(b",")
    if len(fields) != _NUM_COLUMNS:
        return None

    try:
        unix_time = int(fields[0])
        lat = float(fields[2])
        lon = float(fields[3])
    except ValueError:
        return None

    if (
        fields[1].strip().upper() != b"A"
        or unix_time <= 0
        or not (math.isfinite(lat) and math.isfinite(lon))
        or not (-90 <= lat <= 90 and -180 <= lon <= 180)
        or (lat == 0 and lon == 0)
    ):
        return _Row(fix=None)

    return _Row(fix=(unix_time, lat, lon))


def _read_duration(video_path: Path) -> float | None:
    try:
        with video_path.open("rb") as fp:
            data = sparser.parse_mp4_data_first(fp, [b"moov", b"mvhd"])
        if data is None:
            return None
        mvhd = cparser.MovieHeaderBox.parse(data)
    except (OSError, sparser.ParsingError, C.ConstructError) as ex:
        LOG.debug("Unable to read the duration of %s: %s", video_path, ex)
        return None

    if not mvhd.timescale or mvhd.duration <= 0:
        return None
    return mvhd.duration / mvhd.timescale
