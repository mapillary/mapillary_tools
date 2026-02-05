# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import re
import typing as T

import pynmea2

from . import telemetry
from .mp4 import simple_mp4_parser as sparser


LOG = logging.getLogger(__name__)
NMEA_LINE_REGEX = re.compile(
    rb"""
    ^\s*
    \[(\d+)\] # Timestamp
    \s*
    (\$\w{5}.*) # NMEA message
    \s*
    (\[\d+\])? # Strange timestamp
    \s*$
    """,
    re.X,
)


@dataclasses.dataclass
class BlackVueInfo:
    # None and [] are equivalent here. Use None as default because:
    # ValueError: mutable default <class 'list'> for field gps is not allowed: use default_factory
    gps: list[telemetry.GPSPoint] | None = None
    make: str = "BlackVue"
    model: str = ""


def extract_blackvue_info(fp: T.BinaryIO) -> BlackVueInfo | None:
    try:
        gps_data = sparser.parse_mp4_data_first(fp, [b"free", b"gps "])
    except sparser.ParsingError:
        gps_data = None

    if gps_data is None:
        return None

    points = _parse_gps_box(gps_data)
    points.sort(key=lambda p: p.time)

    if points:
        # Convert the time field to relative time to the first point
        # epoch_time stays as the original time in seconds
        first_point_time = points[0].time
        for p in points:
            p.time = p.time - first_point_time

    # Camera model
    try:
        cprt_bytes = sparser.parse_mp4_data_first(fp, [b"free", b"cprt"])
    except sparser.ParsingError:
        cprt_bytes = None
        model = ""

    if cprt_bytes is None:
        model = ""
    else:
        model = _extract_camera_model_from_cprt(cprt_bytes)

    return BlackVueInfo(model=model, gps=points)


def extract_camera_model(fp: T.BinaryIO) -> str:
    try:
        cprt_bytes = sparser.parse_mp4_data_first(fp, [b"free", b"cprt"])
    except sparser.ParsingError:
        return ""

    if cprt_bytes is None:
        return ""

    return _extract_camera_model_from_cprt(cprt_bytes)


def _extract_camera_model_from_cprt(cprt_bytes: bytes) -> str:
    """
    >>> _extract_camera_model_from_cprt(b' {"model":"DR900X Plus","ver":0.918,"lang":"English","direct":1,"psn":"","temp":34,"GPS":1}')
    'DR900X Plus'
    >>> _extract_camera_model_from_cprt(b' Pittasoft Co., Ltd.;DR900S-1CH;1.008;English;1;D90SS1HAE00661;T69;')
    'DR900S-1CH'
    """
    cprt_bytes = cprt_bytes.strip().strip(b"\x00")

    try:
        cprt_str = cprt_bytes.decode("utf8")
    except UnicodeDecodeError:
        return ""

    try:
        cprt_json = json.loads(cprt_str)
    except json.JSONDecodeError:
        cprt_json = None

    if cprt_json is not None:
        return str(cprt_json.get("model", "")).strip()

    fields = cprt_str.split(";")
    if 2 <= len(fields):
        model = fields[1]
        if model:
            return model.strip()
        else:
            return ""
    else:
        return ""


def _compute_timezone_offset_from_rmc(
    epoch_sec: float, message: pynmea2.NMEASentence
) -> float | None:
    """
    Compute timezone offset from an RMC message which has full date+time.

    Returns the offset to add to camera epoch to get correct UTC time,
    or None if this message doesn't have the required datetime.
    """
    if (
        message.sentence_type != "RMC"
        or not hasattr(message, "datetime")
        or not message.datetime
    ):
        return None

    correct_epoch = message.datetime.replace(tzinfo=datetime.timezone.utc).timestamp()
    # Rounding needed to avoid floating point precision issues
    return round(correct_epoch - epoch_sec, 3)


def _compute_timezone_offset_from_time_only(
    epoch_sec: float, message: pynmea2.NMEASentence
) -> float | None:
    """
    Compute timezone offset from GGA/GLL which only have time (no date).

    Uses the date from camera epoch and replaces the time with NMEA time assuming camera date is correct.
    Handles day boundary when camera and GPS times differ by more than 12 hours.
    """
    if not hasattr(message, "timestamp") or not message.timestamp:
        return None

    camera_dt = datetime.datetime.fromtimestamp(epoch_sec, tz=datetime.timezone.utc)

    nmea_time = message.timestamp
    corrected_dt = camera_dt.replace(
        hour=nmea_time.hour,
        minute=nmea_time.minute,
        second=nmea_time.second,
        microsecond=getattr(nmea_time, "microsecond", 0),
    )
    # Handle day boundary e.g. camera time is 23:00, GPS time is 01:00 or vice versa
    camera_secs = camera_dt.hour * 3600 + camera_dt.minute * 60 + camera_dt.second
    nmea_secs = nmea_time.hour * 3600 + nmea_time.minute * 60 + nmea_time.second
    if camera_secs - nmea_secs > 12 * 3600:
        corrected_dt += datetime.timedelta(days=1)
    elif nmea_secs - camera_secs > 12 * 3600:
        corrected_dt -= datetime.timedelta(days=1)

    # Rounding needed to avoid floating point precision issues
    return round(corrected_dt.timestamp() - epoch_sec, 3)


def _parse_nmea_lines(
    gps_data: bytes,
) -> T.Iterator[tuple[int, pynmea2.NMEASentence]]:
    """Parse NMEA lines from GPS data, yielding (epoch_ms, message) tuples."""
    for line_bytes in gps_data.splitlines():
        match = NMEA_LINE_REGEX.match(line_bytes)
        if match is None:
            continue
        nmea_line_bytes = match.group(2)

        if not nmea_line_bytes:
            continue

        try:
            nmea_line = nmea_line_bytes.decode("utf8")
        except UnicodeDecodeError:
            continue

        if not nmea_line:
            continue

        try:
            message = pynmea2.parse(nmea_line)
        except pynmea2.nmea.ParseError:
            continue

        epoch_ms = int(match.group(1))
        yield epoch_ms, message


def _parse_gps_box(gps_data: bytes) -> list[telemetry.GPSPoint]:
    """
    >>> list(_parse_gps_box(b"[1623057074211]$GPGGA,202530.00,5109.0262,N,11401.8407,W,5,40,0.5,1097.36,M,-17.00,M,18,TSTR*61"))
    [GPSPoint(time=1623097530.0, lat=51.150436666666664, lon=-114.03067833333333, alt=1097.36, angle=None, epoch_time=1623097530.0, fix=<GPSFix.FIX_3D: 3>, precision=None, ground_speed=None)]

    >>> list(_parse_gps_box(b"[1629874404069]$GNGGA,175322.00,3244.53126,N,11710.97811,W,1,12,0.84,17.4,M,-34.0,M,,*45"))
    [GPSPoint(time=1629914002.0, lat=32.742187666666666, lon=-117.1829685, alt=17.4, angle=None, epoch_time=1629914002.0, fix=<GPSFix.FIX_3D: 3>, precision=None, ground_speed=None)]

    >>> list(_parse_gps_box(b"[1629874404069]$GNGLL,4404.14012,N,12118.85993,W,001037.00,A,A*67"))
    [GPSPoint(time=1629850237.0, lat=44.069002, lon=-121.31433216666667, alt=None, angle=None, epoch_time=1629850237.0, fix=None, precision=None, ground_speed=None)]

    >>> list(_parse_gps_box(b"[1629874404069]$GNRMC,001031.00,A,4404.13993,N,12118.86023,W,0.146,,100117,,,A*7B"))
    [GPSPoint(time=1484007031.0, lat=44.06899883333333, lon=-121.31433716666666, alt=None, angle=None, epoch_time=1484007031.0, fix=None, precision=None, ground_speed=None)]

    >>> list(_parse_gps_box(b"[1623057074211]$GPVTG,,T,,M,0.078,N,0.144,K,D*28[1623057075215]"))
    []
    """
    timezone_offset: float | None = None
    parsed_lines: list[tuple[float, pynmea2.NMEASentence]] = []
    first_valid_gga_gll: tuple[float, pynmea2.NMEASentence] | None = None

    # First pass: collect parsed_lines and compute timezone offset from the first valid RMC message
    for epoch_ms, message in _parse_nmea_lines(gps_data):
        # Rounding needed to avoid floating point precision issues
        epoch_sec = round(epoch_ms / 1000, 3)
        parsed_lines.append((epoch_sec, message))
        if timezone_offset is None and message.sentence_type == "RMC":
            if hasattr(message, "is_valid") and message.is_valid:
                timezone_offset = _compute_timezone_offset_from_rmc(epoch_sec, message)
                if timezone_offset is not None:
                    LOG.debug(
                        "Computed timezone offset %.1fs from RMC (%s %s)",
                        timezone_offset,
                        message.datestamp,
                        message.timestamp,
                    )
        # Track first valid GGA/GLL for fallback
        if first_valid_gga_gll is None and message.sentence_type in ["GGA", "GLL"]:
            if hasattr(message, "is_valid") and message.is_valid:
                first_valid_gga_gll = (epoch_sec, message)

    # Fallback: if no RMC found, try GGA/GLL (less reliable - no date info)
    if timezone_offset is None and first_valid_gga_gll is not None:
        epoch_sec, message = first_valid_gga_gll
        timezone_offset = _compute_timezone_offset_from_time_only(epoch_sec, message)
        if timezone_offset is not None:
            LOG.debug(
                "Computed timezone offset %.1fs from %s (fallback, no date info)",
                timezone_offset,
                message.sentence_type,
            )

    # If no offset could be determined, use 0 (camera clock assumed correct)
    if timezone_offset is None:
        timezone_offset = 0.0

    points_by_sentence_type: dict[str, list[telemetry.GPSPoint]] = {}

    # Second pass: apply offset to all GPS points
    for epoch_sec, message in parsed_lines:
        corrected_epoch = round(epoch_sec + timezone_offset, 3)

        # https://tavotech.com/gps-nmea-sentence-structure/
        if message.sentence_type in ["GGA"]:
            if not message.is_valid:
                continue
            point = telemetry.GPSPoint(
                time=corrected_epoch,
                lat=message.latitude,
                lon=message.longitude,
                alt=message.altitude,
                angle=None,
                epoch_time=corrected_epoch,
                fix=telemetry.GPSFix.FIX_3D if message.gps_qual >= 1 else None,
                precision=None,
                ground_speed=None,
            )
            points_by_sentence_type.setdefault(message.sentence_type, []).append(point)

        elif message.sentence_type in ["RMC", "GLL"]:
            if not message.is_valid:
                continue
            point = telemetry.GPSPoint(
                time=corrected_epoch,
                lat=message.latitude,
                lon=message.longitude,
                alt=None,
                angle=None,
                epoch_time=corrected_epoch,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            points_by_sentence_type.setdefault(message.sentence_type, []).append(point)

    # This is the extraction order in exiftool
    if "RMC" in points_by_sentence_type:
        return points_by_sentence_type["RMC"]

    if "GGA" in points_by_sentence_type:
        return points_by_sentence_type["GGA"]

    if "GLL" in points_by_sentence_type:
        return points_by_sentence_type["GLL"]

    return []
