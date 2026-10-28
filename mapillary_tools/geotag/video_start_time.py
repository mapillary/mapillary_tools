# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
The time at which a video started recording, by the creation time in its
metadata. That comes from the camera's own clock, which can be off, and marks
the start or the end of the recording depending on the camera, so it is read
only for a video without GPS timestamps of its own.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import re
from pathlib import Path

import construct as C

from .. import blackvue_parser
from ..camm import camm_parser
from ..mp4 import simple_mp4_parser as sparser
from ..mp4.mp4_sample_parser import MovieBoxParser
from ..serializer.description import build_capture_time

LOG = logging.getLogger(__name__)

# Cameras known to stamp the creation time at the end of the recording, as
# lowercase (make, model) from the container tags. BlackVue is not listed
# because it does not write those tags: blackvue_parser.is_blackvue detects it
_END_STAMPING_CAMERAS = {
    ("ricoh", "ricoh theta x"),
    ("labpano", "panox v2"),
}

# A date and time in a file name, for example 20230512_101530 (BlackVue,
# Insta360) or 2023_0512_101530 (Viofo), in the camera's local time
_FILENAME_TIME_RE = re.compile(
    r"(?<!\d)(20\d\d)[-_]?(\d\d)[-_]?(\d\d)[-_T]?(\d\d)[-_]?(\d\d)[-_]?(\d\d)(?!\d)"
)

# UTC offsets range from -12 to +14 hours in multiples of 15 minutes
_MAX_UTC_OFFSET_SECONDS = 14 * 3600
_UTC_OFFSET_GRANULARITY_SECONDS = 15 * 60

# Cameras do not name the file at exactly the moment they stamp the creation
# time: Insta360's are about 10 seconds apart
_FILENAME_TIME_TOLERANCE_SECONDS = 15


def _parse_filename_time(video_path: Path) -> datetime.datetime | None:
    for match in _FILENAME_TIME_RE.finditer(video_path.stem):
        year, month, day, hour, minute, second = (int(g) for g in match.groups())
        try:
            return datetime.datetime(
                year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc
            )
        except ValueError:
            continue

    return None


def _as_utc(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _is_same_time_in_another_time_zone(
    a: datetime.datetime, b: datetime.datetime
) -> bool:
    """
    Tell whether two times could be the same moment, one of them possibly in
    local time labelled as UTC
    """
    delta = abs((_as_utc(a) - _as_utc(b)).total_seconds())
    if _MAX_UTC_OFFSET_SECONDS + _FILENAME_TIME_TOLERANCE_SECONDS < delta:
        return False
    remainder = delta % _UTC_OFFSET_GRANULARITY_SECONDS
    return (
        min(remainder, _UTC_OFFSET_GRANULARITY_SECONDS - remainder)
        <= _FILENAME_TIME_TOLERANCE_SECONDS
    )


def _is_end_stamping_camera(
    video_path: Path, make: str | None, model: str | None
) -> bool:
    if make is not None and model is not None:
        if (make.strip().lower(), model.strip().lower()) in _END_STAMPING_CAMERAS:
            return True

    try:
        with video_path.open("rb") as fp:
            return blackvue_parser.is_blackvue(fp)
    except Exception as ex:
        LOG.debug("Unable to tell whether %s is a BlackVue video: %s", video_path, ex)
        return False


@dataclasses.dataclass(frozen=True)
class StartTime:
    # When the video started, by its creation time
    start_time: datetime.datetime
    # When it started if the camera stamped the creation time at the other end
    # of the recording, where nothing said which end the creation time marks
    # and start_time assumes the start; else None
    if_end_stamped: datetime.datetime | None = None


def creation_time_to_start_time(
    video_path: Path,
    creation_time: datetime.datetime,
    duration: float | None,
    make: str | None = None,
    model: str | None = None,
) -> StartTime:
    """
    Determine the wall clock time at which a video started recording from the
    creation time in its metadata, the video lasting **duration** seconds.

    Cameras disagree on what the creation time marks. Many stamp the end of the
    recording: BlackVue, Viofo, Vantrue and most other dashcams, the Ricoh Theta
    X and the Labpano PanoX V2. Others stamp the start: Sony, Insta360 and the
    dashcam in the bug report that motivated reading this at all. Nothing in the
    metadata says which, so look for evidence: a camera known to stamp the end,
    or a time in the file name that matches only one of the two. Without any,
    assume the start, and give the alternative for the caller to warn about.
    """
    if duration is None:
        LOG.warning(
            "Unable to read the duration of %s, so assuming its creation time %s marks the start of the recording",
            video_path.name,
            creation_time,
        )
        return StartTime(creation_time)

    start_time_if_end_stamped = creation_time - datetime.timedelta(seconds=duration)

    if _is_end_stamping_camera(video_path, make, model):
        return StartTime(start_time_if_end_stamped)

    filename_time = _parse_filename_time(video_path)
    if filename_time is not None:
        matches_start = _is_same_time_in_another_time_zone(filename_time, creation_time)
        matches_end = _is_same_time_in_another_time_zone(
            filename_time, start_time_if_end_stamped
        )
        if matches_end and not matches_start:
            return StartTime(start_time_if_end_stamped)
        if matches_start and not matches_end:
            return StartTime(creation_time)

    return StartTime(creation_time, if_end_stamped=start_time_if_end_stamped)


def describe_end_stamped_alternative(
    video_path: Path, start_time: StartTime, how_to_specify: str
) -> str | None:
    """
    The warning that the creation time was assumed to mark the start of the
    recording, which **how_to_specify** says how to correct, or None if
    evidence said which end it marks
    """
    if start_time.if_end_stamped is None:
        return None
    seconds = (start_time.start_time - start_time.if_end_stamped).total_seconds()
    return (
        f"Assuming the creation time {start_time.start_time} of {video_path.name} marks "
        "the start of the recording. If the camera stamps the end instead, as most "
        f"dashcams do, the recording started {seconds:.1f} seconds earlier: "
        f"{how_to_specify} {build_capture_time(start_time.if_end_stamped)} to use that"
    )


def read_creation_time(video_path: Path) -> datetime.datetime | None:
    """
    The creation time of the video, from its mvhd box, or None if it is unset
    or cannot be read. Read without ffprobe, which process does not need.
    """
    try:
        moov = MovieBoxParser.parse_file(video_path)
    except (OSError, sparser.ParsingError, C.ConstructError) as ex:
        LOG.debug("Failed to read the creation time of %s: %s", video_path, ex)
        return None
    unix_time = camm_parser._extract_creation_time(moov)
    if unix_time is None:
        return None
    return datetime.datetime.fromtimestamp(unix_time, tz=datetime.timezone.utc)
