import datetime
import typing as T

import gpxpy
import gpxpy.gpx

from .. import geo


def is_video_stationary(max_distance_from_start: float) -> bool:
    radius_threshold = 10
    return max_distance_from_start < radius_threshold


def convert_points_to_gpx_segment(points: T.Sequence[geo.Point]):
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    for point in points:
        gpx_segment.points.append(
            gpxpy.gpx.GPXTrackPoint(
                point.lat,
                point.lon,
                elevation=point.alt,
                time=datetime.datetime.utcfromtimestamp(point.time),
            )
        )
    return gpx_segment
