import logging
import pathlib
import re
import typing as T

import pynmea2

from .. import geo
from . import simple_mp4_parser


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


# TODO: what it failed to parse free/cprt
def find_camera_model(path: pathlib.Path) -> str:
    with path.open("rb") as fp:
        cprt_data = simple_mp4_parser.parse_data_first(fp, [b"free", b"cprt"])
        if cprt_data is None:
            return ""
        fields = cprt_data.split(b";")
        if 2 <= len(fields):
            model: bytes = fields[1]
            if model:
                try:
                    return model.decode("utf8")
                except UnicodeDecodeError:
                    return ""
        else:
            return ""
    return ""


def extract_points(fp: T.BinaryIO) -> T.Optional[T.List[geo.Point]]:
    # TODO: what it failed to parse free/gps
    gps_data = simple_mp4_parser.parse_data_first(fp, [b"free", b"gps "])
    if gps_data is None:
        return None

    points = list(_parse_gps_box(gps_data))
    if not points:
        return points

    points.sort(key=lambda p: p.time)

    first_point_time = points[0].time
    for p in points:
        p.time = (p.time - first_point_time) / 1000

    return points


def parse_gps_points(path: pathlib.Path) -> T.List[geo.Point]:
    with path.open("rb") as fp:
        points = extract_points(fp)

    if points is None:
        return []

    return points
