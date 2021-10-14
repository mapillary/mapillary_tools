import os
import typing as T

import gpxpy

from .geotag_from_gpx import GeotagFromGPX
from .. import types


class GeotagFromGPXFile(GeotagFromGPX):
    def __init__(
        self,
        image_dir: str,
        images: T.List[str],
        source_path: str,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
    ):
        if not os.path.isfile(source_path):
            raise RuntimeError(f"GPX file not found: {source_path}")
        points = get_lat_lon_time_from_gpx(source_path)
        super().__init__(
            image_dir,
            images,
            points,
            use_gpx_start_time=use_gpx_start_time,
            offset_time=offset_time,
        )


def get_lat_lon_time_from_gpx(gpx_file: str) -> T.List[types.GPXPoint]:
    with open(gpx_file, "r") as f:
        gpx = gpxpy.parse(f)

    points: T.List[types.GPXPoint] = []

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append(
                    types.GPXPoint(
                        point.time.replace(tzinfo=None),
                        lat=point.latitude,
                        lon=point.longitude,
                        alt=point.elevation,
                    )
                )

    for point in gpx.waypoints:
        points.append(
            types.GPXPoint(
                time=point.time.replace(tzinfo=None),
                lat=point.latitude,
                lon=point.longitude,
                alt=point.elevation,
            )
        )

    # sort by time just in case
    points.sort()

    return points
