import datetime
import typing as T
import gpxpy
import pynmea2

from .types import GPXPoint


"""
Methods for parsing gps data from various file format e.g. GPX, NMEA, SRT.
"""


def get_lat_lon_time_from_gpx(gpx_file: str) -> T.List[GPXPoint]:
    with open(gpx_file, "r") as f:
        gpx = gpxpy.parse(f)

    points: T.List[GPXPoint] = []

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append(
                    GPXPoint(
                        point.time,
                        lat=point.latitude,
                        lon=point.longitude,
                        alt=point.elevation,
                    )
                )

    for point in gpx.waypoints:
        points.append(
            GPXPoint(
                time=point.time,
                lat=point.latitude,
                lon=point.longitude,
                alt=point.elevation,
            )
        )

    # sort by time just in case
    points.sort()

    return points


def get_lat_lon_time_from_nmea(nmea_file: str) -> T.List[GPXPoint]:
    with open(nmea_file, "r") as f:
        lines = f.readlines()
        lines = [l.rstrip("\n\r") for l in lines]

    # Get initial date
    for l in lines:
        if "GPRMC" in l:
            data = pynmea2.parse(l)
            date = data.datetime.date()
            break

    # Parse GPS trace
    points = []
    for l in lines:
        if "GPRMC" in l:
            data = pynmea2.parse(l)
            date = data.datetime.date()

        if "$GPGGA" in l:
            data = pynmea2.parse(l)
            timestamp = datetime.datetime.combine(date, data.timestamp)
            lat, lon, alt = data.latitude, data.longitude, data.altitude
            points.append(GPXPoint(time=timestamp, lat=lat, lon=lon, alt=alt))

    points.sort()
    return points
