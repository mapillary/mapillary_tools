import argparse
import datetime
import json
import sys
import typing as T

import gpxpy

from mapillary_tools import constants, geo
from mapillary_tools.geotag import gps_filter

from .gpmf_parser import _convert_points_to_gpx_track_segment


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max_dop",
        type=float,
        help='Filter points by its position dilution, see https://en.wikipedia.org/wiki/Dilution_of_precision_(navigation). Set it "inf" to disable it. [default: %(default)s]',
        default=constants.GOPRO_MAX_DOP100,
    )
    parser.add_argument(
        "--gps_fix",
        help="Filter points by GPS fix types (0=none, 2=2D, 3=3D). Multiple values are separate by commas, e.g. 2,3. Set 0,2,3 to disable it. [default: %(default)s]",
        default=",".join(map(str, constants.GOPRO_GPS_FIXES)),
    )
    parser.add_argument(
        "--gps_precision",
        type=float,
        help="Filter outlier points by GPS precision. Set 0 to disable it. [default: %(default)s]",
        default=constants.GOPRO_GPS_PRECISION,
    )
    return parser.parse_args()


def _gpx_track_segment_to_points(
    segment: gpxpy.gpx.GPXTrackSegment,
) -> T.List[geo.PointWithFix]:
    gps_fix_map = {
        "none": geo.GPSFix.NO_FIX,
        "2d": geo.GPSFix.FIX_2D,
        "3d": geo.GPSFix.FIX_3D,
    }
    points = []
    for p in segment.points:
        if p.comment:
            try:
                comment_json = json.loads(p.comment)
            except json.JSONDecodeError:
                comment_json = None
        else:
            comment_json = None

        if comment_json is not None:
            ground_speed = comment_json.get("ground_speed")
        else:
            ground_speed = None

        point = geo.PointWithFix(
            time=geo.as_unix_time(T.cast(datetime.datetime, p.time)),
            lat=p.latitude,
            lon=p.longitude,
            alt=p.elevation,
            angle=None,
            gps_fix=(
                gps_fix_map[p.type_of_gpx_fix]
                if p.type_of_gpx_fix is not None
                else None
            ),
            gps_precision=p.position_dilution,
            gps_ground_speed=ground_speed,
        )
        points.append(point)
    return points


def _filter_noise(
    points: T.Sequence[geo.PointWithFix],
    gps_fix: T.Set[int],
    max_dop: float,
) -> T.List[geo.PointWithFix]:
    return [
        p
        for p in points
        if (p.gps_fix is None or p.gps_fix.value in gps_fix)
        and (p.gps_precision is None or p.gps_precision <= max_dop)
    ]


def _filter_outliers(
    points: T.List[geo.PointWithFix],
    gps_precision: float,
) -> T.List[geo.PointWithFix]:
    if gps_precision == 0:
        return points

    distances = [
        geo.gps_distance((left.lat, left.lon), (right.lat, right.lon))
        for left, right in geo.pairwise(points)
    ]
    if len(distances) < 2:
        return points

    max_distance = gps_filter.upper_whisker(distances)
    max_distance = max(gps_precision + gps_precision, max_distance)

    subseqs = gps_filter.split_if(
        T.cast(T.List[geo.Point], points),
        gps_filter.distance_gt(max_distance),
    )

    ground_speeds = [
        point.gps_ground_speed for point in points if point.gps_ground_speed is not None
    ]
    if len(ground_speeds) < 2:
        return points

    max_speed = gps_filter.upper_whisker(ground_speeds)
    merged = gps_filter.dbscan(subseqs, gps_filter.speed_le(max_speed))

    return T.cast(
        T.List[geo.PointWithFix],
        gps_filter.find_majority(merged.values()),
    )


def main():
    parsed_args = _parse_args()
    gps_fix = set(int(x) for x in parsed_args.gps_fix.split(","))

    gpx = gpxpy.parse(sys.stdin)
    for track in gpx.tracks:
        new_segs = []
        for seg in track.segments:
            points = _gpx_track_segment_to_points(seg)
            points = _filter_noise(points, gps_fix, parsed_args.max_dop)
            points = _filter_outliers(points, parsed_args.gps_precision)
            new_seg = _convert_points_to_gpx_track_segment(points)
            new_segs.append(new_seg)
        track.segments = new_segs
    print(gpx.to_xml())


if __name__ == "__main__":
    main()
