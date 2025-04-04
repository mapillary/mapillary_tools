# pyre-ignore-all-errors[4]
from __future__ import annotations

import bisect
import dataclasses
import datetime
import itertools
import math
import sys
import typing as T

WGS84_a = 6378137.0
WGS84_a_SQ = WGS84_a**2
WGS84_b = 6356752.314245
WGS84_b_SQ = WGS84_b**2


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
    alt: float | None
    angle: float | None


PointLike = T.TypeVar("PointLike", bound=Point)


def gps_distance(latlon_1: tuple[float, float], latlon_2: tuple[float, float]) -> float:
    """
    Distance between two (lat,lon) pairs.

    >>> p1 = (42.1, -11.1)
    >>> p2 = (42.2, -11.3)
    >>> 19000 < gps_distance(p1, p2) < 20000
    True
    """
    x1, y1, z1 = _ecef_from_lla2(latlon_1[0], latlon_1[1])
    x2, y2, z2 = _ecef_from_lla2(latlon_2[0], latlon_2[1])

    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)


def compute_bearing(
    latlon_1: tuple[float, float],
    latlon_2: tuple[float, float],
) -> float:
    """
    Get the compass bearing from start to end.

    Formula from
    http://www.movable-type.co.uk/scripts/latlong.html
    """
    start_lat, start_lon = latlon_1
    end_lat, end_lon = latlon_2

    # Make sure everything is in radians
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
def pairwise(iterable: T.Iterable[_IT]) -> T.Iterable[tuple[_IT, _IT]]:
    """s -> (s0,s1), (s1,s2), (s2, s3), ..."""
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b)


def as_unix_time(dt: datetime.datetime | int | float) -> float:
    if isinstance(dt, (int, float)):
        return dt
    else:
        try:
            # if dt is naive, assume it's in local timezone
            return dt.timestamp()
        except ValueError:
            # Some datetimes can't be converted to timestamp
            # e.g. 0001-01-01 00:00:00 will throw ValueError: year 0 is out of range
            try:
                return dt.replace(year=1970).timestamp()
            except ValueError:
                return 0.0


if sys.version_info < (3, 10):

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
        return _interpolate_at_segment_idx(points, t, idx)
else:

    def interpolate(points: T.Sequence[Point], t: float, lo: int = 0) -> Point:
        """
        Interpolate or extrapolate the point at time t along the sequence of points (sorted by time).
        """
        if not points:
            raise ValueError("Expect non-empty points")

        # Make sure that points are sorted (disabled because the check costs O(N)):
        # for cur, nex in pairwise(points):
        #     assert cur.time <= nex.time, "Points not sorted"

        idx = bisect.bisect_left(points, t, lo=lo, key=lambda x: x.time)
        return _interpolate_at_segment_idx(points, t, idx)


class Interpolator:
    """
    Interpolator for interpolating a sequence of timestamps incrementally.
    """

    tracks: T.Sequence[T.Sequence[Point]]
    track_idx: int
    # interpolation starts from the lower bound point index in the current track
    lo: int
    prev_time: float | None

    def __init__(self, tracks: T.Sequence[T.Sequence[Point]]):
        # Remove empty tracks
        self.tracks = [track for track in tracks if track]

        if not self.tracks:
            raise ValueError("Expect at least one non-empty track")

        for track in self.tracks:
            for left, right in pairwise(track):
                if not (left.time <= right.time):
                    raise ValueError(
                        "Expect points to be sorted by time, but got {left.time} then {right.time}"
                    )

        self.tracks.sort(key=lambda track: track[0].time)
        self.track_idx = 0
        self.lo = 0
        self.prev_time = None

    @staticmethod
    def _lsearch_left(
        track: T.Sequence[Point], t: float, lo: int = 0, hi: int | None = None
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
        # assert track[lo - 1].time < t <= track[lo].time
        return lo

    def interpolate(self, t: float) -> Point:
        if self.prev_time is not None:
            if not (self.prev_time <= t):
                raise ValueError(
                    f"Require times to be monotonically increasing, but got {self.prev_time} then {t}"
                )

        interpolated: Point | None = None

        while self.track_idx < len(self.tracks):
            track = self.tracks[self.track_idx]
            assert track, "expect non-empty track"

            if t < track[0].time:
                interpolated = _interpolate_at_segment_idx(track, t, 0)
                break

            elif track[0].time <= t <= track[-1].time:
                # Similar to bisect.bisect_left(points, p, lo=lo) but faster in this case
                idx = Interpolator._lsearch_left(track, t, lo=self.lo)
                # Time t must be between (track[idx - 1], track[idx]], so set the lower bound to idx - 1
                # Because the next t can still be interpolated anywhere between (track[idx - 1], track[idx]]
                self.lo = max(idx - 1, 0)
                interpolated = _interpolate_at_segment_idx(track, t, idx)
                break

            self.track_idx += 1
            self.lo = 0

        if interpolated is None:
            interpolated = _interpolate_at_segment_idx(
                self.tracks[-1], t, len(self.tracks[-1])
            )

        self.prev_time = t

        return interpolated


_T = T.TypeVar("_T")


def sample_points_by_distance(
    samples: T.Iterable[_T],
    min_distance: float,
    point_func: T.Callable[[_T], Point],
) -> T.Generator[_T, None, None]:
    prevp: Point | None = None
    for sample in samples:
        if prevp is None:
            yield sample
            prevp = point_func(sample)
        else:
            p = point_func(sample)
            if min_distance < gps_distance((prevp.lat, prevp.lon), (p.lat, p.lon)):
                yield sample
                prevp = p


def interpolate_directions_if_none(sequence: T.Sequence[PointLike]) -> None:
    for cur, nex in pairwise(sequence):
        if cur.angle is None:
            cur.angle = compute_bearing((cur.lat, cur.lon), (nex.lat, nex.lon))

    if len(sequence) == 1:
        if sequence[-1].angle is None:
            sequence[-1].angle = 0
    elif 2 <= len(sequence):
        if sequence[-1].angle is None:
            prev_angle = sequence[-2].angle
            assert prev_angle is not None, (
                "expect the last second point to have an interpolated angle"
            )
            sequence[-1].angle = prev_angle


def _ecef_from_lla2(lat: float, lon: float) -> tuple[float, float, float]:
    """
    Compute ECEF XYZ from latitude and longitude.

    All using the WGS94 model.
    Altitude is the distance to the WGS94 ellipsoid.
    Check results here http://www.oc.nps.edu/oc2902w/coord/llhxyz.htm

    """
    lat = math.radians(lat)
    lon = math.radians(lon)
    cos_lat = math.cos(lat)
    sin_lat = math.sin(lat)
    L = 1.0 / math.sqrt(WGS84_a_SQ * cos_lat**2 + WGS84_b_SQ * sin_lat**2)
    K = WGS84_a_SQ * L * cos_lat
    x = K * math.cos(lon)
    y = K * math.sin(lon)
    z = WGS84_b_SQ * L * sin_lat
    return x, y, z


def _interpolate_segment(start: Point, end: Point, t: float) -> Point:
    try:
        weight = (t - start.time) / (end.time - start.time)
    except ZeroDivisionError:
        weight = 0.0

    lat = start.lat + (end.lat - start.lat) * weight
    lon = start.lon + (end.lon - start.lon) * weight
    angle = compute_bearing((start.lat, start.lon), (end.lat, end.lon))
    alt: float | None
    if start.alt is not None and end.alt is not None:
        alt = start.alt + (end.alt - start.alt) * weight
    else:
        alt = None

    return Point(time=t, lat=lat, lon=lon, alt=alt, angle=angle)


def _interpolate_at_segment_idx(points: T.Sequence[Point], t: float, idx: int) -> Point:
    """
    Interpolate time t along the segment between idx - 1 and idx.
    If idx is out of range, extrapolate it to the nearest segment (first or last).
    """

    if len(points) == 1:
        start, end = points[0], points[0]
    elif 2 <= len(points):
        if 0 < idx < len(points):
            # Normal interpolation within the range
            start, end = points[idx - 1], points[idx]
        elif idx <= 0:
            # Extrapolating before the first point
            start, end = points[0], points[1]
        else:
            # Extrapolating after the last point
            assert len(points) <= idx
            start, end = points[-2], points[-1]
    else:
        assert False, "expect non-empty points"

    return _interpolate_segment(start, end, t)
