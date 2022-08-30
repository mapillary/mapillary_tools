# pyre-ignore-all-errors[4]

import bisect
import dataclasses
import datetime
import itertools
import math
import typing as T

WGS84_a = 6378137.0
WGS84_b = 6356752.314245


def ecef_from_lla(lat: float, lon: float, alt: float) -> T.Tuple[float, float, float]:
    """
    Compute ECEF XYZ from latitude, longitude and altitude.

    All using the WGS94 model.
    Altitude is the distance to the WGS94 ellipsoid.
    Check results here http://www.oc.nps.edu/oc2902w/coord/llhxyz.htm

    """
    a2 = WGS84_a**2
    b2 = WGS84_b**2
    lat = math.radians(lat)
    lon = math.radians(lon)
    L = 1.0 / math.sqrt(a2 * math.cos(lat) ** 2 + b2 * math.sin(lat) ** 2)
    x = (a2 * L + alt) * math.cos(lat) * math.cos(lon)
    y = (a2 * L + alt) * math.cos(lat) * math.sin(lon)
    z = (b2 * L + alt) * math.sin(lat)
    return x, y, z


def gps_distance(
    latlon_1: T.Tuple[float, float], latlon_2: T.Tuple[float, float]
) -> float:
    """
    Distance between two (lat,lon) pairs.

    >>> p1 = (42.1, -11.1)
    >>> p2 = (42.2, -11.3)
    >>> 19000 < gps_distance(p1, p2) < 20000
    True
    """
    x1, y1, z1 = ecef_from_lla(latlon_1[0], latlon_1[1], 0.0)
    x2, y2, z2 = ecef_from_lla(latlon_2[0], latlon_2[1], 0.0)

    dis = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)

    return dis


def get_max_distance_from_start(latlons: T.List[T.Tuple[float, float]]) -> float:
    """
    Returns the radius of an entire GPS track. Used to calculate whether or not the entire sequence was just stationary video
    Takes a sequence of points as input
    """
    if not latlons:
        return 0
    start = latlons[0]
    return max(gps_distance(start, latlon) for latlon in latlons)


def compute_bearing(
    start_lat: float, start_lon: float, end_lat: float, end_lon: float
) -> float:
    """
    Get the compass bearing from start to end.

    Formula from
    http://www.movable-type.co.uk/scripts/latlong.html
    """
    # make sure everything is in radians
    start_lat = math.radians(start_lat)
    start_lon = math.radians(start_lon)
    end_lat = math.radians(end_lat)
    end_lon = math.radians(end_lon)

    dLong = end_lon - start_lon

    if abs(dLong) > math.pi:
        if dLong > 0.0:
            dLong = -(2.0 * math.pi - dLong)
        else:
            dLong = 2.0 * math.pi + dLong

    y = math.sin(dLong) * math.cos(end_lat)
    x = math.cos(start_lat) * math.sin(end_lat) - math.sin(start_lat) * math.cos(
        end_lat
    ) * math.cos(dLong)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    return bearing


def diff_bearing(b1: float, b2: float) -> float:
    """
    Compute difference between two bearings
    """
    d = abs(b2 - b1)
    d = 360 - d if d > 180 else d
    return d


_IT = T.TypeVar("_IT")


# http://stackoverflow.com/a/5434936
def pairwise(iterable: T.Iterable[_IT]) -> T.Iterable[T.Tuple[_IT, _IT]]:
    """s -> (s0,s1), (s1,s2), (s2, s3), ..."""
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b)


@dataclasses.dataclass(order=True)
class Point:
    # For reducing object sizes
    # dataclass(slots=True) not available until 3.10
    __slots__ = (
        "time",
        "lat",
        "lon",
        "alt",
        "angle",
    )
    time: float
    lat: float
    lon: float
    alt: T.Optional[float]
    angle: T.Optional[float]


def as_unix_time(dt: T.Union[datetime.datetime, int, float]) -> float:
    if isinstance(dt, (int, float)):
        return dt
    if dt.tzinfo is None:
        # assume UTC if no timezone is given
        aware_dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        aware_dt = dt
    return aware_dt.timestamp()


def interpolate(points: T.Sequence[Point], t: float) -> Point:
    """
    Interpolate or extrapolate the point at time t along the sequence of points (sorted by time).
    """
    if not points:
        raise ValueError("Expect non-empty points")

    # Make sure that points are sorted (disabled because the check costs O(N)):
    # for cur, nex in pairwise(points):
    #     assert cur.time <= nex.time, "Points not sorted"

    p = Point(time=t, lat=float("-inf"), lon=float("-inf"), alt=None, angle=None)
    idx = bisect.bisect_left(points, p)

    if 0 < idx < len(points):
        # interpolating within the range
        before = points[idx - 1]
        after = points[idx]
    elif idx <= 0:
        # extrapolating behind the range
        if 2 <= len(points):
            before, after = points[0], points[1]
        else:
            before, after = points[0], points[0]
    else:
        # extrapolating beyond the range
        assert len(points) <= idx
        if 2 <= len(points):
            before, after = points[-2], points[-1]
        else:
            before, after = points[-1], points[-1]

    if before.time == after.time:
        weight = 0.0
    else:
        weight = (t - before.time) / (after.time - before.time)
    lat = before.lat + (after.lat - before.lat) * weight
    lon = before.lon + (after.lon - before.lon) * weight
    angle = compute_bearing(before.lat, before.lon, after.lat, after.lon)
    alt: T.Optional[float]
    if before.alt is not None and after.alt is not None:
        alt = before.alt + (after.alt - before.alt) * weight
    else:
        alt = None
    return Point(time=t, lat=lat, lon=lon, alt=alt, angle=angle)
