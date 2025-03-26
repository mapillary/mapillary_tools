from __future__ import annotations

import dataclasses

import json
import logging
import re
import typing as T

import pynmea2

from . import geo
from .mp4 import simple_mp4_parser as sparser


LOG = logging.getLogger(__name__)
# An example: [1623057074211]$GPVTG,,T,,M,0.078,N,0.144,K,D*28[1623057075215]
NMEA_LINE_REGEX = re.compile(
    rb"""
    ^\s*
    \[(\d+)\] # timestamp
    \s*
    (\$\w{5}.*) # nmea line
    \s*
    (\[\d+\])? # strange timestamp
    \s*$
    """,
    re.X,
)


@dataclasses.dataclass
class BlackVueInfo:
    # None and [] are equivalent here. Use None as default because:
    # ValueError: mutable default <class 'list'> for field gps is not allowed: use default_factory
    gps: list[geo.Point] | None = None
    make: str = "BlackVue"
    model: str = ""


def extract_blackvue_info(fp: T.BinaryIO) -> BlackVueInfo | None:
    try:
        gps_data = sparser.parse_mp4_data_first(fp, [b"free", b"gps "])
    except sparser.ParsingError:
        gps_data = None

    if gps_data is None:
        return None

    points = list(_parse_gps_box(gps_data))
    points.sort(key=lambda p: p.time)

    if points:
        first_point_time = points[0].time
        for p in points:
            p.time = (p.time - first_point_time) / 1000

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
    # examples: b' {"model":"DR900X Plus","ver":0.918,"lang":"English","direct":1,"psn":"","temp":34,"GPS":1}\x00'
    #           b' Pittasoft Co., Ltd.;DR900S-1CH;1.008;English;1;D90SS1HAE00661;T69;\x00'
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


def _parse_gps_box(gps_data: bytes) -> T.Generator[geo.Point, None, None]:
    for line_bytes in gps_data.splitlines():
        match = NMEA_LINE_REGEX.match(line_bytes)
        if match is None:
            continue
        nmea_line_bytes = match.group(2)
        if nmea_line_bytes.startswith(b"$GPGGA"):
            try:
                nmea_line = nmea_line_bytes.decode("utf8")
            except UnicodeDecodeError:
                continue
            try:
                nmea = pynmea2.parse(nmea_line)
            except pynmea2.nmea.ParseError:
                continue
            if not nmea.is_valid:
                continue
            epoch_ms = int(match.group(1))
            yield geo.Point(
                time=epoch_ms,
                lat=nmea.latitude,
                lon=nmea.longitude,
                alt=nmea.altitude,
                angle=None,
            )
