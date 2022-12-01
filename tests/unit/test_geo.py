import dataclasses
import datetime
import typing as T

from mapillary_tools.geo import as_unix_time, interpolate, Interpolator, Point


# lat, lon, bearing, alt
def approximate(a: Point, b: T.Tuple[float, float, float, float]):
    x: T.List[float] = [a.lat, a.lon, a.angle or 0, a.alt or 0]
    for i, j in zip(x, b):
        assert abs(i - j) <= 0.00001


def approximate_point(a: Point, b: Point):
    approximate(a, (b.lat, b.lon, b.angle or 0, b.alt or 0))


def test_interpolate():
    points = [
        Point(lon=1, lat=1, time=1, alt=1, angle=None),
        Point(lon=2, lat=2, time=2, alt=2, angle=None),
    ]
    interpolator = Interpolator([points])

    a = interpolate(points, -1)
    assert a == interpolator.interpolate(-1)
    approximate(a, (-1.0, -1.0, 44.978182941465036, -1.0))

    a = interpolate(points, 0.1)
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

    a = interpolate(points, 1)
    assert a == interpolator.interpolate(1)
    approximate(a, (1.0, 1.0, 44.978182941465036, 1.0))

    a = interpolate(points, 1.2)
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

    a = interpolate(points, 2)
    assert a == interpolator.interpolate(2)
    approximate(a, (2.0, 2.0, 44.978182941465036, 2.0))

    a = interpolate(points, 2)
    assert a == interpolator.interpolate(2)
    approximate(a, (2.0, 2.0, 44.978182941465036, 2.0))

    a = interpolate(points, 2.3)
    assert a == interpolator.interpolate(2.3)
    approximate(a, (2.3, 2.3, 44.978182941465036, 2.3))

    a = interpolate(points, 2.3)
    assert a == interpolator.interpolate(2.3)
    approximate(a, (2.3, 2.3, 44.978182941465036, 2.3))


def test_interpolate_single():
    points = [
        Point(lon=1, lat=1, time=1, alt=1, angle=None),
    ]
    interpolator = Interpolator([points])

    a = interpolate(points, -1)
    assert a == interpolator.interpolate(-1)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 0.1)
    assert a == interpolator.interpolate(0.1)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 1)
    assert a == interpolator.interpolate(1)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 1.2)
    assert a == interpolator.interpolate(1.2)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 2)
    assert a == interpolator.interpolate(2)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 2.3)
    assert a == interpolator.interpolate(2.3)
    approximate(a, (1.0, 1.0, 0.0, 1.0))


def test_multiple_sequences():
    interpolator = Interpolator(
        [
            [
                Point(lon=1, lat=1, time=1, alt=1, angle=None),
                Point(lon=2, lat=2, time=2, alt=2, angle=None),
            ],
            [],
            [
                Point(lon=4, lat=4, time=1.5, alt=1, angle=None),
                Point(lon=5, lat=5, time=3, alt=2, angle=None),
            ],
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
    a = interpolator.interpolate(11)
    approximate_point(
        a, Point(time=11, lat=8.0, lon=8.0, alt=3.0, angle=44.759739722972995)
    )


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
    assert as_unix_time(t) == 123
