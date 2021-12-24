import typing as T
import gpxpy

from .. import types


def is_video_stationary(max_distance_from_start: float) -> bool:
    radius_threshold = 10
    return max_distance_from_start < radius_threshold


def convert_points_to_gpx(points: T.List[types.GPXPoint]) -> gpxpy.gpx.GPX:
    gpx = gpxpy.gpx.GPX()
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(gpx_track)
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)
    for point in points:
        gpx_segment.points.append(
            gpxpy.gpx.GPXTrackPoint(point.lat, point.lon, elevation=point.alt)
        )
    return gpx
