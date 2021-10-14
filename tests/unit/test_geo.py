import datetime

from mapillary_tools.geo import interpolate_lat_lon, Point


def approximate(a, b):
    for i, j in zip(a, b):
        assert abs(i - j) <= 0.00001


def test_interpolate():
    points = [
        Point(lon=1, lat=1, time=datetime.datetime.utcfromtimestamp(1), alt=1),
        Point(lon=2, lat=2, time=datetime.datetime.utcfromtimestamp(2), alt=2),
    ]
    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(-1))
    approximate(a, (-1.0, -1.0, 44.978182941465036, -1.0))

    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(0.1))
    approximate(
        a,
        (
            0.09999999999999987,
            0.09999999999999987,
            44.978182941465036,
            0.09999999999999987,
        ),
    )

    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(1))
    approximate(a, (1.0, 1.0, 44.978182941465036, 1.0))

    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(1.2))
    approximate(
        a,
        (
            1.2000000000000002,
            1.2000000000000002,
            44.978182941465036,
            1.2000000000000002,
        ),
    )

    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(2))
    approximate(a, (2.0, 2.0, 44.978182941465036, 2.0))

    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(2.3))
    approximate(a, (2.3, 2.3, 44.978182941465036, 2.3))


def test_interpolate_single():
    points = [
        Point(lon=1, lat=1, time=datetime.datetime.utcfromtimestamp(1), alt=1),
    ]
    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(-1))
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(0.1))
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(1))
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(1.2))
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(2))
    approximate(a, (1.0, 1.0, 0.0, 1.0))
    a = interpolate_lat_lon(points, datetime.datetime.utcfromtimestamp(2.3))
    approximate(a, (1.0, 1.0, 0.0, 1.0))
