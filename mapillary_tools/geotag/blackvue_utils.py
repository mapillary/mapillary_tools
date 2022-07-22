import typing as T
import datetime
import re
import logging

import pynmea2

from .simple_mp4_parser import parse_boxes


LOG = logging.getLogger(__name__)


class _GPXPoint(T.NamedTuple):
    # Put it first for sorting
    time: datetime.datetime
    lat: float
    lon: float
    alt: T.Optional[float]


def _parse_gps_box(
    gps_data: bytes, use_nmea_stream_timestamp: bool
) -> T.List[_GPXPoint]:
    points = []
    date = None
    first_gps_date: T.Optional[datetime.date] = None
    first_gps_time: T.Optional[datetime.time] = None
    found_first_gps_date = False
    found_first_gps_time = False

    lines = gps_data

    # Parse GPS trace
    for line_bytes in lines.splitlines():
        line = line_bytes.decode("utf-8")
        m = line.lstrip("[]0123456789")
        # this utc millisecond timestamp seems to be the camera's
        # todo: unused?
        # match = re.search('\[([0-9]+)\]', l)
        # if match:
        #     utcdate = match.group(1)

        # By default, use camera timestamp. Only use GPS Timestamp if camera was not set up correctly and date/time is wrong
        if not use_nmea_stream_timestamp:
            if "$GPGGA" in m:
                match = re.search("\[([0-9]+)\]", line)
                if match:
                    epoch_in_local_time = match.group(1)

                camera_date = datetime.datetime.utcfromtimestamp(
                    int(epoch_in_local_time) / 1000.0
                )
                data = pynmea2.parse(m)
                if data.is_valid:
                    if not found_first_gps_time:
                        first_gps_time = data.timestamp
                        found_first_gps_time = True
                    lat, lon, alt = (
                        data.latitude,
                        data.longitude,
                        data.altitude,
                    )
                    points.append(
                        _GPXPoint(time=camera_date, lat=lat, lon=lon, alt=alt)
                    )

        if use_nmea_stream_timestamp or not found_first_gps_date:
            if "GPRMC" in m:
                try:
                    data = pynmea2.parse(m)
                    if data.is_valid:
                        date = data.datetime.date()
                        if not found_first_gps_date:
                            first_gps_date = date
                except pynmea2.ChecksumError:
                    # There are often Checksum errors in the GPS stream, better not to show errors to user
                    pass
                except Exception:
                    LOG.warning(
                        "Warning: Error in parsing gps trace to extract date information, nmea parsing failed"
                    )
        if use_nmea_stream_timestamp:
            if "$GPGGA" in m:
                try:
                    data = pynmea2.parse(m)
                    if data.is_valid:
                        if not date:
                            timestamp = data.timestamp
                        else:
                            timestamp = datetime.datetime.combine(date, data.timestamp)
                        points.append(
                            _GPXPoint(
                                time=timestamp,
                                lat=data.latitude,
                                lon=data.longitude,
                                alt=data.altitude,
                            )
                        )
                except Exception as e:
                    LOG.error(
                        "Error in parsing GPS trace to extract time and GPS information, nmea parsing failed",
                        exc_info=e,
                    )

    # If there are no points after parsing just return empty vector
    if not points:
        return []

    # After parsing all points, fix timedate issues
    if not use_nmea_stream_timestamp:
        # If we use the camera timestamp, we need to get the timezone offset, since Mapillary backend expects UTC timestamps
        first_gps_timestamp = datetime.datetime.combine(
            T.cast(datetime.date, first_gps_date),
            T.cast(datetime.time, first_gps_time),
        )
        delta_t = points[0].time - first_gps_timestamp
        if delta_t.days > 0:
            hours_diff_to_utc = round(delta_t.total_seconds() / 3600)
        else:
            hours_diff_to_utc = round(delta_t.total_seconds() / 3600) * -1
        utc_points = []
        for point in points:
            delay_compensation = datetime.timedelta(
                seconds=-1.8
            )  # Compensate for solution age when location gets timestamped by camera clock. Value is empirical from various cameras/recordings
            new_timestamp = (
                point.time
                + datetime.timedelta(hours=hours_diff_to_utc)
                + delay_compensation
            )
            utc_points.append(
                _GPXPoint(
                    time=T.cast(datetime.datetime, new_timestamp),
                    lat=point.lat,
                    lon=point.lon,
                    alt=point.alt,
                )
            )
        points = utc_points

    else:
        # add date to points that don't have it yet, because GPRMC message came later
        utc_points = []
        for point in points:
            if not isinstance(point.time, datetime.datetime):
                timestamp = datetime.datetime.combine(
                    T.cast(datetime.date, first_gps_date),
                    T.cast(datetime.time, point.time),
                )
            else:
                timestamp = point.time
            utc_points.append(
                _GPXPoint(
                    time=timestamp,
                    lat=point.lat,
                    lon=point.lon,
                    alt=point.alt,
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
) -> T.Optional[T.List[_GPXPoint]]:
    points = None
    for h, s in parse_boxes(stream, maxsize=maxsize, extend_eof=False):
        if h.type == b"gps ":
            gps_data = s.read(h.maxsize)
            if points is None:
                points = []
            points.extend(_parse_gps_box(gps_data, False))
    return points


def parse_gps_points(path: str) -> T.List[_GPXPoint]:
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
    from .. import utils, types
    from . import utils as geotag_utils

    def _convert(path: str):
        points = parse_gps_points(path)
        gpx = geotag_utils.convert_points_to_gpx(T.cast(T.List[types.GPXPoint], points))
        model = find_camera_model(path)
        gpx.description = f"Extracted from {model}"
        print(gpx.to_xml())

    for path in sys.argv[1:]:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _convert(p)
        else:
            _convert(path)
