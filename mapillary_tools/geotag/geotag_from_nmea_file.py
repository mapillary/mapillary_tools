import datetime
import typing as T

import pynmea2

from .. import geo

from .geotag_from_gpx import GeotagFromGPX


class GeotagFromNMEAFile(GeotagFromGPX):
    def __init__(
        self,
        image_dir: str,
        images: T.Sequence[str],
        source_path: str,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
    ):
        points = get_lat_lon_time_from_nmea(source_path)
        super().__init__(
            image_dir,
            images,
            points,
            use_gpx_start_time=use_gpx_start_time,
            offset_time=offset_time,
        )


def get_lat_lon_time_from_nmea(nmea_file: str) -> T.List[geo.Point]:
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
            dt = datetime.datetime.combine(date, data.timestamp)
            lat, lon, alt = data.latitude, data.longitude, data.altitude
            points.append(
                geo.Point(
                    time=geo.as_unix_time(dt), lat=lat, lon=lon, alt=alt, angle=None
                )
            )

    points.sort()
    return points
