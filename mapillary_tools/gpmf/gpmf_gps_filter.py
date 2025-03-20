import logging
import typing as T

from .. import constants, geo
from ..telemetry import GPSPoint
from . import gps_filter

"""
This module was originally used for GoPro GPS data (GPMF) filtering,
but it now can be used for any GPS data with fixes, precisions, and ground speeds.
"""

LOG = logging.getLogger(__name__)


def remove_outliers(
    sequence: T.Sequence[GPSPoint],
) -> T.Sequence[GPSPoint]:
    distances = [
        geo.gps_distance((left.lat, left.lon), (right.lat, right.lon))
        for left, right in geo.pairwise(sequence)
    ]
    if len(distances) < 2:
        return sequence

    max_distance = gps_filter.upper_whisker(distances)
    LOG.debug("max distance: %f", max_distance)
    max_distance = max(
        # distance between two points hence double
        constants.GOPRO_GPS_PRECISION + constants.GOPRO_GPS_PRECISION,
        max_distance,
    )
    sequences = gps_filter.split_if(
        T.cast(T.List[geo.Point], sequence),
        gps_filter.distance_gt(max_distance),
    )
    LOG.debug(
        "Split to %d sequences with max distance %f", len(sequences), max_distance
    )

    ground_speeds = [p.ground_speed for p in sequence if p.ground_speed is not None]
    if len(ground_speeds) < 2:
        return sequence

    max_speed = gps_filter.upper_whisker(ground_speeds)
    merged = gps_filter.dbscan(sequences, gps_filter.speed_le(max_speed))
    LOG.debug(
        "Found %d sequences after merging with max speed %f", len(merged), max_speed
    )

    return T.cast(
        T.List[GPSPoint],
        gps_filter.find_majority(merged.values()),
    )


def remove_noisy_points(
    sequence: T.Sequence[GPSPoint],
) -> T.Sequence[GPSPoint]:
    num_points = len(sequence)
    sequence = [
        p
        for p in sequence
        # include points **without** GPS fix
        if p.fix is None or p.fix.value in constants.GOPRO_GPS_FIXES
    ]
    if len(sequence) < num_points:
        LOG.debug(
            "Removed %d points with the GPS fix not in %s",
            num_points - len(sequence),
            constants.GOPRO_GPS_FIXES,
        )

    num_points = len(sequence)
    sequence = [
        p
        for p in sequence
        # include points **without** precision
        if p.precision is None or p.precision <= constants.GOPRO_MAX_DOP100
    ]
    if len(sequence) < num_points:
        LOG.debug(
            "Removed %d points with DoP value higher than %d",
            num_points - len(sequence),
            constants.GOPRO_MAX_DOP100,
        )

    num_points = len(sequence)
    sequence = remove_outliers(sequence)
    if len(sequence) < num_points:
        LOG.debug(
            "Removed %d outlier points",
            num_points - len(sequence),
        )

    return sequence
