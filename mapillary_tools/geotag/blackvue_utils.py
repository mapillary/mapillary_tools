import typing as T
import datetime
import re
import logging

import pynmea2

from .. import geo
from .simple_mp4_parser import parse_boxes


LOG = logging.getLogger(__name__)


def _parse_gps_box(gps_data: bytes) -> T.List[geo.Point]:
    points = []
    first_gps_date: T.Optional[datetime.date] = None
    first_gps_time: T.Optional[datetime.time] = None
    found_first_gps_date = False
    found_first_gps_time = False

    lines = gps_data

    # Parse GPS trace
    for line_bytes in lines.splitlines():
        line = line_bytes.decode("utf-8")
        m = line.lstrip("[]0123456789")

        # By default, use camera timestamp. Only use GPS Timestamp if camera was not set up correctly and date/time is wrong
        if "$GPGGA" in m:
            match = re.search("\[([0-9]+)\]", line)
            if match:
                epoch_in_local_time = int(match.group(1)) / 1000.0

            data = pynmea2.parse(m)
            if data.is_valid:
                if not found_first_gps_time:
                    first_gps_time = data.timestamp
                    found_first_gps_time = True
                points.append(
                    geo.Point(
                        time=epoch_in_local_time,
                        lat=data.latitude,
                        lon=data.longitude,
                        alt=data.altitude,
                        angle=None,
                    )
                )

        if not found_first_gps_date:
            if "GPRMC" in m:
                try:
                    data = pynmea2.parse(m)
                    if data.is_valid:
                        date = data.datetime.date()
                        if not found_first_gps_date:
                            first_gps_date = date
                            found_first_gps_date = True
                except pynmea2.ChecksumError:
                    # There are often Checksum errors in the GPS stream, better not to show errors to user
                    pass
                except Exception:
                    LOG.warning(
                        "Warning: Error in parsing gps trace to extract date information, nmea parsing failed"
                    )

    # If there are no points after parsing just return empty vector
    if not points:
        return []

    if first_gps_date is not None and first_gps_time is not None:
        # After parsing all points, fix timedate issues
        # If we use the camera timestamp, we need to get the timezone offset, since Mapillary backend expects UTC timestamps
        first_gps_timestamp = geo.as_unix_time(
            datetime.datetime.combine(
                T.cast(datetime.date, first_gps_date),
                T.cast(datetime.time, first_gps_time),
            )
        )
        delta_t = points[0].time - first_gps_timestamp
        if delta_t > 0:
            hours_diff_to_utc = round(delta_t / 3600)
        else:
            hours_diff_to_utc = round(delta_t / 3600) * -1
    else:
        hours_diff_to_utc = 0

    utc_points = []
    for point in points:
        # Compensate for solution age when location gets timestamped by camera clock. Value is empirical from various cameras/recordings
        delay_compensation = -1.8
        new_timestamp = point.time + hours_diff_to_utc * 3600 + delay_compensation
        utc_points.append(
            geo.Point(
                time=new_timestamp,
                lat=point.lat,
                lon=point.lon,
                alt=point.alt,
                angle=None,
            )
        )

    points = utc_points

    return points


def find_camera_model(path: str) -> str:
    with open(path, "rb") as fp:
        for header, stream in parse_boxes(fp, extend_eof=True):
            if header.type == b"free":
                return _parse_camera_model_from_free_box(stream, maxsize=header.maxsize)
    return ""


def _parse_camera_model_from_free_box(stream: T.BinaryIO, maxsize: int) -> str:
    for h, s in parse_boxes(stream, maxsize=maxsize, extend_eof=False):
        if h.type == b"cprt":
            cprt = s.read(h.maxsize)
            # An example cprt: b' Pittasoft Co., Ltd.;DR900S-1CH;'
            fields = cprt.split(b";")
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


def _parse_gps_from_free_box(
    stream: T.BinaryIO, maxsize: int
) -> T.Optional[T.List[geo.Point]]:
    points = None
    for h, s in parse_boxes(stream, maxsize=maxsize, extend_eof=False):
        if h.type == b"gps ":
            gps_data = s.read(h.maxsize)
            if points is None:
                points = []
            points.extend(_parse_gps_box(gps_data))
    return points


def parse_gps_points(path: str) -> T.List[geo.Point]:
    points = None

    with open(path, "rb") as fp:
        for header, stream in parse_boxes(fp, extend_eof=True):
            if header.type == b"free":
                points = _parse_gps_from_free_box(stream, maxsize=header.maxsize)
                if points is not None:
                    break

    if points is None:
        points = []

    points.sort()

    return points


if __name__ == "__main__":
    import sys, os
    from .. import utils, types, geo
    from . import utils as geotag_utils

    def _convert(path: str):
        points = parse_gps_points(path)
        gpx = geotag_utils.convert_points_to_gpx(points)
        model = find_camera_model(path)
        gpx.description = f"Extracted from {model}"
        print(gpx.to_xml())

    for path in sys.argv[1:]:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _convert(p)
        else:
            _convert(path)
