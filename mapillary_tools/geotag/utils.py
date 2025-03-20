from __future__ import annotations
import datetime
import typing as T

import gpxpy
import gpxpy.gpx

from .. import geo


def is_video_stationary(max_distance_from_start: float) -> bool:
    radius_threshold = 10
    return max_distance_from_start < radius_threshold


def get_max_distance_from_start(latlons: T.Sequence[tuple[float, float]]) -> float:
    """
    Returns the radius of an entire GPS track. Used to calculate whether or not the entire sequence was just stationary video
    Takes a sequence of points as input
    """
    if not latlons:
        return 0
    start = latlons[0]
    return max(geo.gps_distance(start, latlon) for latlon in latlons)


def convert_points_to_gpx_segment(points: T.Sequence[geo.Point]):
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    for point in points:
        gpx_segment.points.append(
            gpxpy.gpx.GPXTrackPoint(
                point.lat,
                point.lon,
                elevation=point.alt,
                time=datetime.datetime.fromtimestamp(point.time, datetime.timezone.utc),
            )
        )
    return gpx_segment
