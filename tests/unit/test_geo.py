import dataclasses
import datetime
import typing as T

from mapillary_tools.geo import interpolate, Point, as_unix_time


# lat, lon, bearing, alt
def approximate(a: Point, b: T.Tuple[float, float, float, float]):
    x = a.lat, a.lon, a.angle, a.alt
    for i, j in zip(x, b):
        assert abs(i - j) <= 0.00001


def test_interpolate():
    points = [
        Point(lon=1, lat=1, time=1, alt=1, angle=None),
        Point(lon=2, lat=2, time=2, alt=2, angle=None),
    ]
    a = interpolate(points, -1)
    approximate(a, (-1.0, -1.0, 44.978182941465036, -1.0))

    a = interpolate(points, 0.1)
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
    approximate(a, (1.0, 1.0, 44.978182941465036, 1.0))

    a = interpolate(points, 1.2)
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
    approximate(a, (2.0, 2.0, 44.978182941465036, 2.0))

    a = interpolate(points, 2.3)
    approximate(a, (2.3, 2.3, 44.978182941465036, 2.3))


def test_interpolate_single():
    points = [
        Point(lon=1, lat=1, time=1, alt=1, angle=None),
    ]
    a = interpolate(points, -1)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 0.1)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 1)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 1.2)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 2)
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate(points, 2.3)
    approximate(a, (1.0, 1.0, 0.0, 1.0))


def test_point_sorting():
    @dataclasses.dataclass
    class _Point(Point):
        p: float

    t1 = _Point(lon=1, lat=1, time=1, alt=1, angle=None, p=123)
    t2 = _Point(lon=9, lat=1, time=1, alt=1, angle=123, p=1)
    t3 = _Point(lon=1, lat=1, time=2, alt=1, angle=None, p=100)
    s = sorted([t1, t2, t3])
    assert s[0].time <= s[-1].time
    assert s == sorted([t3, t2, t1])


def test_timestamp():
    t = datetime.datetime.utcfromtimestamp(123)
    assert as_unix_time(t) == 123
