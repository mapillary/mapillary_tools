import logging
import typing as T

from .. import constants, geo
from . import gpmf_parser, gps_filter

LOG = logging.getLogger(__name__)


def filter_out_outliers(
    points: T.Sequence[gpmf_parser.PointWithFix],
) -> T.Sequence[gpmf_parser.PointWithFix]:
    distances = [
        geo.gps_distance((left.lat, left.lon), (right.lat, right.lon))
        for left, right in geo.pairwise(points)
    ]
    if len(distances) < 2:
        return points

    max_distance = gps_filter.upper_whisker(distances)
    LOG.debug("max distance: %f", max_distance)
    max_distance = max(
        # distance between two points hence double
        constants.GOPRO_GPS_PRECISION + constants.GOPRO_GPS_PRECISION,
        max_distance,
    )
    sequences = gps_filter.split_if(
        T.cast(T.List[geo.Point], points),
        gps_filter.distance_gt(max_distance),
    )
    LOG.debug(
        "Split to %d sequences with max distance %f", len(sequences), max_distance
    )

    ground_speeds = [
        point.gps_ground_speed for point in points if point.gps_ground_speed is not None
    ]
    if len(ground_speeds) < 2:
        return points

    max_speed = gps_filter.upper_whisker(ground_speeds)
    merged = gps_filter.dbscan(sequences, gps_filter.speed_le(max_speed))
    LOG.debug(
        "Found %d sequences after merging with max speed %f", len(merged), max_speed
    )

    return T.cast(
        T.List[gpmf_parser.PointWithFix],
        gps_filter.find_majority(merged.values()),
    )


def filter_noisy_points(
    points: T.Sequence[gpmf_parser.PointWithFix],
) -> T.Sequence[gpmf_parser.PointWithFix]:
    num_points = len(points)
    points = [
        p
        for p in points
        if p.gps_fix is not None and p.gps_fix.value in constants.GOPRO_GPS_FIXES
    ]
    if len(points) < num_points:
        LOG.debug(
            "Removed %d points with the GPS fix not in %s",
            num_points - len(points),
            constants.GOPRO_GPS_FIXES,
        )

    num_points = len(points)
    points = [
        p
        for p in points
        if p.gps_precision is not None and p.gps_precision <= constants.GOPRO_MAX_DOP100
    ]
    if len(points) < num_points:
        LOG.debug(
            "Removed %d points with DoP value higher than %d",
            num_points - len(points),
            constants.GOPRO_MAX_DOP100,
        )

    num_points = len(points)
    points = filter_out_outliers(points)
    if len(points) < num_points:
        LOG.debug(
            "Removed %d outlier points",
            num_points - len(points),
        )

    return points
