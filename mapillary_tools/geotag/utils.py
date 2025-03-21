from __future__ import annotations

import datetime
import typing as T

import gpxpy
import gpxpy.gpx

from .. import geo


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
