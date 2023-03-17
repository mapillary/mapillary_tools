import dataclasses
import datetime
import random
import typing as T

from mapillary_tools import geo
from mapillary_tools.geo import Point


# lat, lon, bearing, alt
def approximate(a: Point, b: T.Tuple[float, float, float, float]):
    x: T.List[float] = [a.lat, a.lon, a.angle or 0, a.alt or 0]
    for i, j in zip(x, b):
        assert abs(i - j) <= 0.00001


def approximate_point(a: Point, b: Point):
    approximate(a, (b.lat, b.lon, b.angle or 0, b.alt or 0))


def test_interpolate_compare():
    points = [
        Point(time=1, lon=3, lat=2, alt=1, angle=None),
        Point(time=2, lon=2, lat=0, alt=None, angle=2),
    ]
    a = geo.interpolate(points, 1.5)
    approximate_point(
        a, Point(time=1.5, lat=1.0, lon=2.5, alt=None, angle=206.572033486577)
    )


def test_interpolate():
    points = [
        Point(lon=1, lat=1, time=1, alt=1, angle=None),
        Point(lon=2, lat=2, time=2, alt=2, angle=None),
    ]
    interpolator = geo.Interpolator([points])

    a = geo.interpolate(points, -1)
    assert a == interpolator.interpolate(-1)
    approximate(a, (-1.0, -1.0, 44.978182941465036, -1.0))

    a = geo.interpolate(points, 0.1)
    assert a == interpolator.interpolate(0.1)
    approximate(
        a,
        (
            0.09999999999999987,
            0.09999999999999987,
            44.978182941465036,
            0.09999999999999987,
        ),
    )

    a = geo.interpolate(points, 1)
    assert a == interpolator.interpolate(1)
    approximate(a, (1.0, 1.0, 44.978182941465036, 1.0))

    a = geo.interpolate(points, 1.2)
    assert a == interpolator.interpolate(1.2)
    approximate(
        a,
        (
            1.2000000000000002,
            1.2000000000000002,
            44.978182941465036,
            1.2000000000000002,
        ),
    )

    a = geo.interpolate(points, 2)
    assert a == interpolator.interpolate(2)
    approximate(a, (2.0, 2.0, 44.978182941465036, 2.0))

    a = geo.interpolate(points, 2)
    assert a == interpolator.interpolate(2)
    approximate(a, (2.0, 2.0, 44.978182941465036, 2.0))

    a = geo.interpolate(points, 2.3)
    assert a == interpolator.interpolate(2.3)
    approximate(a, (2.3, 2.3, 44.978182941465036, 2.3))

    a = geo.interpolate(points, 2.3)
    assert a == interpolator.interpolate(2.3)
    approximate(a, (2.3, 2.3, 44.978182941465036, 2.3))


def test_interpolate_single():
    points = [
        Point(lon=1, lat=1, time=1, alt=1, angle=None),
    ]
    interpolator = geo.Interpolator([points])

    a = geo.interpolate(points, -1)
    assert a == interpolator.interpolate(-1)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = geo.interpolate(points, 0.1)
    assert a == interpolator.interpolate(0.1)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = geo.interpolate(points, 1)
    assert a == interpolator.interpolate(1)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = geo.interpolate(points, 1.2)
    assert a == interpolator.interpolate(1.2)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = geo.interpolate(points, 2)
    assert a == interpolator.interpolate(2)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = geo.interpolate(points, 2.3)
    assert a == interpolator.interpolate(2.3)
    approximate(a, (1.0, 1.0, 0.0, 1.0))


def test_multiple_sequences():
    interpolator = geo.Interpolator(
        [
            [
                Point(lon=4, lat=4, time=1.5, alt=1, angle=None),
                Point(lon=5, lat=5, time=3, alt=2, angle=None),
            ],
            [
                Point(lon=1, lat=1, time=1, alt=1, angle=None),
                Point(lon=2, lat=2, time=2, alt=2, angle=None),
            ],
            [],
            [
                Point(lon=6, lat=6, time=9, alt=1, angle=None),
                Point(lon=7, lat=7, time=10, alt=2, angle=None),
            ],
        ]
    )
    a = interpolator.interpolate(-1)
    approximate_point(
        a, Point(time=-1, lat=-1.0, lon=-1.0, alt=-1.0, angle=44.978182941465036)
    )
    a = interpolator.interpolate(1)
    approximate_point(
        a, Point(time=1, lat=1.0, lon=1.0, alt=1.0, angle=44.978182941465036)
    )
    a = interpolator.interpolate(1)
    approximate_point(
        a, Point(time=1, lat=1.0, lon=1.0, alt=1.0, angle=44.978182941465036)
    )
    a = interpolator.interpolate(1.5)
    approximate_point(
        a, Point(time=1.5, lat=1.5, lon=1.5, alt=1.5, angle=44.978182941465036)
    )
    a = interpolator.interpolate(2)
    approximate_point(
        a, Point(time=2, lat=2.0, lon=2.0, alt=2.0, angle=44.978182941465036)
    )
    a = interpolator.interpolate(3)
    approximate_point(
        a, Point(time=3, lat=5.0, lon=5.0, alt=2.0, angle=44.87341066679062)
    )
    a = interpolator.interpolate(10)
    approximate_point(
        a,
        Point(time=10, lat=7.0, lon=7.0, alt=2.0, angle=44.759739722972995),
    )
    a = interpolator.interpolate(11)
    approximate_point(
        a, Point(time=11, lat=8.0, lon=8.0, alt=3.0, angle=44.759739722972995)
    )


def test_multiple_sequences_random():
    track = [
        Point(lon=4, lat=4, time=1.5, alt=1, angle=None),
        Point(lon=5, lat=5, time=3, alt=2, angle=None),
        Point(lon=5, lat=5, time=4.3, alt=8, angle=None),
        Point(lon=5, lat=8, time=4.3, alt=2, angle=None),
        Point(lon=5, lat=8, time=7.3, alt=1, angle=None),
        Point(lon=5, lat=8, time=9.3, alt=3, angle=None),
    ]
    interpolator = geo.Interpolator(
        [
            track,
        ]
    )
    ts = [random.random() * 11 for _ in range(1000)]
    ts.sort()
    assert [geo.interpolate(track, t) for t in ts] == [
        interpolator.interpolate(t) for t in ts
    ]


def test_point_sorting():
    @dataclasses.dataclass
    class _Point(Point):
        p: float

    t1 = _Point(lon=1, lat=1, time=1, alt=1, angle=None, p=123)
    t2 = _Point(lon=1, lat=1, time=1, alt=1, angle=2, p=123)
    t3 = _Point(lon=9, lat=1, time=1, alt=1, angle=123, p=1)
    t4 = _Point(lon=1, lat=1, time=2, alt=1, angle=None, p=100)
    # not a very useful tests
    # just be careful with comparing points: angle could be None
    s = sorted([t1, t2, t3, t4], key=lambda x: x.time)
    assert s[0].time <= s[-1].time


def test_timestamp():
    t = datetime.datetime.utcfromtimestamp(123)
    t = t.replace(tzinfo=datetime.timezone.utc)
    assert geo.as_unix_time(t) == 123


def test_sample_points_by_distance():
    x = list(
        geo.sample_points_by_distance(
            [
                Point(time=1, lat=1, lon=1, alt=1, angle=None),
                Point(time=1, lat=1, lon=1, alt=1, angle=None),
                Point(time=1, lat=1.1, lon=1.1, alt=1, angle=None),
                Point(time=1, lat=1.1, lon=1.1, alt=1, angle=None),
                Point(time=1, lat=2, lon=2, alt=1, angle=None),
                Point(time=1, lat=2, lon=2, alt=1, angle=None),
            ],
            100000,
            lambda x: x,
        )
    )
    assert [
        Point(time=1, lat=1, lon=1, alt=1, angle=None),
        Point(time=1, lat=2, lon=2, alt=1, angle=None),
    ] == x

    x = list(
        geo.sample_points_by_distance(
            [
                Point(time=1, lat=1, lon=1, alt=1, angle=None),
            ],
            100000,
            lambda x: x,
        )
    )
    assert [
        Point(time=1, lat=1, lon=1, alt=1, angle=None),
    ] == x

    x = list(
        geo.sample_points_by_distance(
            [],
            100000,
            lambda x: x,
        )
    )
    assert [] == x


def test_distance():
    p1 = (42.1, -11.1)
    p2 = (42.2, -11.3)
    assert 19916.286 == round(geo.gps_distance(p1, p2), 3)

    assert 9004939.288 == round(geo.gps_distance((0, 0), (90, 180)), 3)
    assert 9004939.288 == round(geo.gps_distance((0, 0), (90, 0)), 3)
    assert 9004939.288 == round(geo.gps_distance((0, 0), (90, 2)), 3)

    assert round(geo.gps_distance((0, -180), (0, 180)), 5) == 0
    assert round(geo.gps_distance((0, 180), (0, -180)), 5) == 0


def test_compute_bearing():
    assert 0 == geo.compute_bearing(0, 0, 0, 0)
    assert 0 == geo.compute_bearing(0, 0, 1, 0)
    assert 90 == geo.compute_bearing(0, 0, 0, 1)
    assert 180 == geo.compute_bearing(0, 0, -1, 0)
    assert 270 == geo.compute_bearing(0, 0, 0, -1)


def test_interpolate_directions_if_none():
    points = [
        Point(time=1, lat=0, lon=0, alt=1, angle=None),
        Point(time=1, lat=0, lon=1, alt=1, angle=1),
        Point(time=1, lat=1, lon=1, alt=1, angle=2),
        Point(time=1, lat=1, lon=0, alt=1, angle=None),
        Point(time=1, lat=0, lon=0, alt=1, angle=None),
    ]
    geo.interpolate_directions_if_none(points)
    assert [90, 1, 2, 180, 180] == [p.angle for p in points]
