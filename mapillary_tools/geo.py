# pyre-ignore-all-errors[4]

import bisect
import dataclasses
import datetime
import itertools
import math
import typing as T

WGS84_a = 6378137.0
WGS84_b = 6356752.314245


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


def group_every(
    iterable: T.Iterable[_IT], n: int
) -> T.Generator[T.Generator[_IT, None, None], None, None]:
    """
    Return a generator that divides the iterable into groups by N.
    """

    if not (0 < n):
        raise ValueError("expect 0 < n but got {0}".format(n))

    for _, group in itertools.groupby(enumerate(iterable), key=lambda t: t[0] // n):
        yield (item for _, item in group)


def as_unix_time(dt: T.Union[datetime.datetime, int, float]) -> float:
    if isinstance(dt, (int, float)):
        return dt
    if dt.tzinfo is None:
        # assume UTC if no timezone is given
        aware_dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        aware_dt = dt
    return aware_dt.timestamp()


def _interpolate_segment(start: Point, end: Point, t: float) -> Point:
    if start.time == end.time:
        weight = 0.0
    else:
        weight = (t - start.time) / (end.time - start.time)

    lat = start.lat + (end.lat - start.lat) * weight
    lon = start.lon + (end.lon - start.lon) * weight
    angle = compute_bearing(start.lat, start.lon, end.lat, end.lon)
    alt: T.Optional[float]
    if start.alt is not None and end.alt is not None:
        alt = start.alt + (end.alt - start.alt) * weight
    else:
        alt = None

    return Point(time=t, lat=lat, lon=lon, alt=alt, angle=angle)


def _interpolate_at_index(points: T.Sequence[Point], t: float, idx: int):
    assert points, "expect non-empty points"

    # find the segment (start point, end point)
    if len(points) == 1:
        start, end = points[0], points[0]
    else:
        if 0 < idx < len(points):
            # interpolating within the range
            start, end = points[idx - 1], points[idx]
        elif idx <= 0:
            # extrapolating behind the range
            start, end = points[0], points[1]
        else:
            # extrapolating beyond the range
            assert len(points) <= idx
            start, end = points[-2], points[-1]

    return _interpolate_segment(start, end, t)


def interpolate(points: T.Sequence[Point], t: float, lo: int = 0) -> Point:
    """
    Interpolate or extrapolate the point at time t along the sequence of points (sorted by time).
    """
    if not points:
        raise ValueError("Expect non-empty points")

    # Make sure that points are sorted (disabled because the check costs O(N)):
    # for cur, nex in pairwise(points):
    #     assert cur.time <= nex.time, "Points not sorted"

    p = Point(time=t, lat=float("-inf"), lon=float("-inf"), alt=None, angle=None)
    idx = bisect.bisect_left(points, p, lo=lo)
    return _interpolate_at_index(points, t, idx)


class Interpolator:
    """
    Interpolator for interpolating a sequence of timestamps incrementally.
    """

    tracks: T.Sequence[T.Sequence[Point]]
    track_idx: int
    # lower bound index in the current track to interpolate timestamps
    lo: int
    prev_time: T.Optional[float]

    def __init__(self, tracks: T.Sequence[T.Sequence[Point]]):
        self.tracks = [track for track in tracks if track]
        if not self.tracks:
            raise ValueError("Expect non-empty tracks")
        self.tracks.sort(key=lambda track: track[0].time)
        self.track_idx = 0
        self.lo = 0
        self.prev_time = None

    @staticmethod
    def _lsearch_left(
        track: T.Sequence[Point], t: float, lo: int = 0, hi: T.Optional[int] = None
    ) -> int:
        """
        similar to bisect.bisect_left, but faster in the incremental search case
        """
        assert 0 <= lo, "expect non-negative lower bound"
        if hi is None:
            hi = len(track)
        while lo < hi:
            # assert track[lo - 1].time < t
            if t <= track[lo].time:
                break
            # assert track[lo].time < t
            lo += 1
        # assert track[lo - 1] < t <= track[lo]
        return lo

    def interpolate(self, t: float) -> Point:
        if self.prev_time is not None:
            assert self.prev_time <= t, "requires time to be monotonically increasing"

        while self.track_idx < len(self.tracks):
            track = self.tracks[self.track_idx]
            if t < track[0].time:
                return _interpolate_at_index(track, t, 0)
            elif track[0].time <= t <= track[-1].time:
                # similar to bisect.bisect_left(points, p, lo=lo) but faster in this case
                idx = Interpolator._lsearch_left(track, t, lo=self.lo)
                # set the lower bound to idx - 1
                # because the next timestamp can still be interpolated in [idx - 1, idx]
                self.lo = max(idx - 1, 0)
                return _interpolate_at_index(track, t, idx)
            self.track_idx += 1
            self.lo = 0

        interpolated = _interpolate_at_index(self.tracks[-1], t, len(self.tracks[-1]))

        self.prev_time = t

        return interpolated


_PointLike = T.TypeVar("_PointLike")


def sample_points_by_distance(
    samples: T.Iterable[_PointLike],
    min_distance: float,
    point_func: T.Callable[[_PointLike], Point],
) -> T.Generator[_PointLike, None, None]:
    prevp: T.Optional[Point] = None
    for sample in samples:
        if prevp is None:
            yield sample
            prevp = point_func(sample)
        else:
            p = point_func(sample)
            if min_distance < gps_distance((prevp.lat, prevp.lon), (p.lat, p.lon)):
                yield sample
                prevp = p
