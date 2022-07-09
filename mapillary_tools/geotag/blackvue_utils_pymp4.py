import typing as T
import datetime
import os
import io
import re
import pynmea2
import logging

try:
    from pymp4.parser import Box
except ImportError:
    Box = None

try:
    import construct
except ImportError:
    construct = None


from .. import types
from ..exceptions import (
    MapillaryInvalidBlackVueVideoError,
)
from . import utils as geotag_utils

LOG = logging.getLogger(__name__)


def find_camera_model(video_path: str) -> str:
    assert Box is not None, "Package pymp4 is required"

    with open(video_path, "rb") as fd:
        fd.seek(0, io.SEEK_END)
        eof = fd.tell()
        fd.seek(0)
        while fd.tell() < eof:
            try:
                box = Box.parse_stream(fd)
            except Exception as ex:
                return ""
            if box.type.decode("utf-8") == "free":
                bs = box.data[29:39]
                try:
                    return bs.decode("utf8")
                except UnicodeDecodeError:
                    return ""
        return ""


def _parse_gps_box(gps_data: bytes, use_nmea_stream_timestamp: bool):
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
                    points.append((camera_date, lat, lon, alt))

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
                        lat, lon, alt = (
                            data.latitude,
                            data.longitude,
                            data.altitude,
                        )
                        if not date:
                            timestamp = data.timestamp
                        else:
                            timestamp = datetime.datetime.combine(date, data.timestamp)
                        points.append((timestamp, lat, lon, alt))

                except Exception as e:
                    LOG.error(
                        f"Error in parsing GPS trace to extract time and GPS information, nmea parsing failed",
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
        delta_t = points[0][0] - first_gps_timestamp
        if delta_t.days > 0:
            hours_diff_to_utc = round(delta_t.total_seconds() / 3600)
        else:
            hours_diff_to_utc = round(delta_t.total_seconds() / 3600) * -1
        utc_points = []
        for idx, point in enumerate(points):
            delay_compensation = datetime.timedelta(
                seconds=-1.8
            )  # Compensate for solution age when location gets timestamped by camera clock. Value is empirical from various cameras/recordings
            new_timestamp = (
                points[idx][0]
                + datetime.timedelta(hours=hours_diff_to_utc)
                + delay_compensation
            )
            lat = points[idx][1]
            lon = points[idx][2]
            alt = points[idx][3]
            utc_points.append((new_timestamp, lat, lon, alt))
        points = utc_points

    else:
        # add date to points that don't have it yet, because GPRMC message came later
        utc_points = []
        for idx, point in enumerate(points):
            if not isinstance(points[idx][0], datetime.datetime):
                timestamp = datetime.datetime.combine(
                    T.cast(datetime.date, first_gps_date),
                    T.cast(datetime.time, points[idx][0]),
                )
            else:
                timestamp = points[idx][0]
            lat = points[idx][1]
            lon = points[idx][2]
            alt = points[idx][3]
            utc_points.append((timestamp, lat, lon, alt))
        points = utc_points

    return points


def _parse_free_box(box_data: bytes, use_nmea_stream_timestamp: bool):
    assert Box is not None, "Package pymp4 is required"

    points = []
    offset = 0
    while offset < len(box_data):
        newb = Box.parse(box_data[offset:])
        if newb.type.decode("utf-8") == "gps":
            points.extend(_parse_gps_box(newb.data, use_nmea_stream_timestamp))
        offset += newb.end

    points.sort()

    return points


def get_points_from_bv(
    path: str, use_nmea_stream_timestamp: bool = False
) -> T.List[types.GPXPoint]:
    assert Box is not None, "Package pymp4 is required"
    assert construct is not None, "Package construct is required"

    points = []
    with open(path, "rb") as fd:
        fd.seek(0, io.SEEK_END)
        eof = fd.tell()
        fd.seek(0)

        while fd.tell() < eof:
            try:
                box = Box.parse_stream(fd)
            except (construct.core.RangeError, construct.core.ConstError) as ex:
                raise MapillaryInvalidBlackVueVideoError(
                    f"Unable to parse the BlackVue video ({ex.__class__.__name__}: {ex}): {path}"
                ) from ex
            except IOError as ex:
                raise MapillaryInvalidBlackVueVideoError(
                    f"Unable to parse the BlackVue video ({ex.__class__.__name__}: {ex}): {path}"
                ) from ex

            if box.type.decode("utf-8") == "free":
                points = _parse_free_box(box.data, use_nmea_stream_timestamp)
                break

        return [types.GPXPoint(time=p[0], lat=p[1], lon=p[2], alt=p[3]) for p in points]


if __name__ == "__main__":
    import sys
    from .. import utils

    def _convert(path: str):
        points = get_points_from_bv(path)
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
