import dataclasses
import datetime
import random
import typing as T
import unittest

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


def test_interpolate_empty_list():
    try:
        geo.interpolate([], 1.5)
    except ValueError:
        pass
    else:
        assert False, "should raise ValueError"


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
    t = datetime.datetime.fromtimestamp(123, datetime.timezone.utc)
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
    assert 0 == geo.compute_bearing((1, 1), (1, 1))
    assert 0 == geo.compute_bearing((0, 0), (0, 0))
    assert 0 == geo.compute_bearing((0, 0), (1, 0))
    assert 90 == geo.compute_bearing((0, 0), (0, 1))
    assert 180 == geo.compute_bearing((0, 0), (-1, 0))
    assert 270 == geo.compute_bearing((0, 0), (0, -1))


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


class TestInterpolator(unittest.TestCase):
    """Test cases for the Interpolator class, focusing on tricky edge cases."""

    def setUp(self):
        """Set up test data for interpolation tests."""

        # Helper function to create a series of points
        def create_track(
            start_time,
            points_count,
            time_step,
            start_lat,
            start_lon,
            lat_step,
            lon_step,
            alt=None,
            angle=None,
        ):
            track = []
            for i in range(points_count):
                time = start_time + i * time_step
                lat = start_lat + i * lat_step
                lon = start_lon + i * lon_step
                alt_val = None if alt is None else alt + i * 10
                angle_val = None if angle is None else (angle + i * 5) % 360
                track.append(
                    Point(time=time, lat=lat, lon=lon, alt=alt_val, angle=angle_val)
                )
            return track

        # Regular track
        self.regular_track = create_track(
            start_time=1000.0,
            points_count=5,
            time_step=100.0,
            start_lat=10.0,
            start_lon=20.0,
            lat_step=0.1,
            lon_step=0.1,
            alt=100,
            angle=45,
        )

        # Track with very close timestamps (nearly identical)
        self.close_timestamps_track = [
            Point(time=2000.0, lat=30.0, lon=40.0, alt=200, angle=90),
            Point(time=2000.000001, lat=30.1, lon=40.1, alt=210, angle=95),
            Point(time=2000.000002, lat=30.2, lon=40.2, alt=220, angle=100),
        ]

        # Track with identical timestamps
        self.identical_timestamps_track = [
            Point(time=3000.0, lat=50.0, lon=60.0, alt=300, angle=180),
            Point(time=3000.0, lat=50.1, lon=60.1, alt=310, angle=185),
            Point(time=3100.0, lat=50.2, lon=60.2, alt=320, angle=190),
        ]

        # Track with large time gaps
        self.large_gaps_track = [
            Point(time=4000.0, lat=70.0, lon=80.0, alt=400, angle=270),
            Point(time=14000.0, lat=70.1, lon=80.1, alt=410, angle=275),
            Point(time=24000.0, lat=70.2, lon=80.2, alt=420, angle=280),
        ]

        # Track crossing the antimeridian (longitude wrapping around 180/-180)
        self.antimeridian_track = [
            Point(time=5000.0, lat=0.0, lon=179.9, alt=500, angle=0),
            Point(time=5100.0, lat=0.1, lon=-179.9, alt=510, angle=5),
            Point(time=5200.0, lat=0.2, lon=-179.8, alt=520, angle=10),
        ]

        # Track crossing the poles (extreme latitudes)
        self.polar_track = [
            Point(time=6000.0, lat=89.0, lon=0.0, alt=600, angle=0),
            Point(time=6100.0, lat=90.0, lon=0.0, alt=610, angle=0),
            Point(time=6200.0, lat=89.0, lon=180.0, alt=620, angle=180),
        ]

        # Multiple tracks with time gaps between them
        self.track_1 = create_track(
            start_time=7000.0,
            points_count=3,
            time_step=100.0,
            start_lat=10.0,
            start_lon=20.0,
            lat_step=0.1,
            lon_step=0.1,
        )

        self.track_2 = create_track(
            start_time=7500.0,
            points_count=3,
            time_step=100.0,
            start_lat=11.0,
            start_lon=21.0,
            lat_step=0.1,
            lon_step=0.1,
        )

        self.track_3 = create_track(
            start_time=8000.0,
            points_count=3,
            time_step=100.0,
            start_lat=12.0,
            start_lon=22.0,
            lat_step=0.1,
            lon_step=0.1,
        )

        # Track with None values for alt and angle
        self.none_values_track = [
            Point(time=9000.0, lat=80.0, lon=90.0, alt=None, angle=None),
            Point(time=9100.0, lat=80.1, lon=90.1, alt=None, angle=None),
            Point(time=9200.0, lat=80.2, lon=90.2, alt=None, angle=None),
        ]

        # Mixed track: some points with alt/angle, some without
        self.mixed_values_track = [
            Point(time=10000.0, lat=85.0, lon=95.0, alt=None, angle=45),
            Point(time=10100.0, lat=85.1, lon=95.1, alt=800, angle=None),
            Point(time=10200.0, lat=85.2, lon=95.2, alt=810, angle=50),
        ]

    def test_basic_interpolation(self):
        """Test basic interpolation within a track."""
        interpolator = geo.Interpolator([self.regular_track])

        # Interpolate in the middle of a segment
        point = interpolator.interpolate(1050.0)
        self.assertEqual(point.time, 1050.0)
        self.assertAlmostEqual(point.lat, 10.05)
        self.assertAlmostEqual(point.lon, 20.05)
        self.assertAlmostEqual(point.alt, 105)

        # Interpolate exactly at a point
        point = interpolator.interpolate(1100.0)
        self.assertEqual(point.time, 1100.0)
        self.assertAlmostEqual(point.lat, 10.1)
        self.assertAlmostEqual(point.lon, 20.1)
        self.assertAlmostEqual(point.alt, 110)

    def test_extrapolation_before_track(self):
        """Test extrapolation before the start of a track."""
        interpolator = geo.Interpolator([self.regular_track])

        # Extrapolate before first point
        point = interpolator.interpolate(900.0)
        self.assertEqual(point.time, 900.0)
        self.assertAlmostEqual(point.lat, 9.9)
        self.assertAlmostEqual(point.lon, 19.9)
        self.assertAlmostEqual(point.alt, 90)

    def test_extrapolation_after_track(self):
        """Test extrapolation after the end of a track."""
        interpolator = geo.Interpolator([self.regular_track])

        # Extrapolate after last point
        point = interpolator.interpolate(1500.0)
        self.assertEqual(point.time, 1500.0)
        self.assertAlmostEqual(point.lat, 10.5)
        self.assertAlmostEqual(point.lon, 20.5)
        self.assertAlmostEqual(point.alt, 150)

    def test_close_timestamps(self):
        """Test interpolation between points with very close timestamps."""
        interpolator = geo.Interpolator([self.close_timestamps_track])

        # Interpolate between very close timestamps
        point = interpolator.interpolate(2000.0000015)
        self.assertEqual(point.time, 2000.0000015)
        # Should be halfway between point 1 and 2
        self.assertAlmostEqual(point.lat, 30.15)
        self.assertAlmostEqual(point.lon, 40.15)
        self.assertAlmostEqual(point.alt, 215)

    def test_identical_timestamps(self):
        """Test interpolation with points having identical timestamps."""
        interpolator = geo.Interpolator([self.identical_timestamps_track])

        # Interpolate at time matching multiple points
        point = interpolator.interpolate(3000.0)
        self.assertEqual(point.time, 3000.0)
        # Should pick the first point with that time
        self.assertAlmostEqual(point.lat, 50.0)
        self.assertAlmostEqual(point.lon, 60.0)
        self.assertAlmostEqual(point.alt, 300)

        # Interpolate between identical and unique timestamps
        point = interpolator.interpolate(3050.0)
        self.assertEqual(point.time, 3050.0)
        # Should interpolate between the last point with identical timestamp and the next point
        self.assertAlmostEqual(point.lat, 50.15)
        self.assertAlmostEqual(point.lon, 60.15)
        self.assertAlmostEqual(point.alt, 315)

    def test_large_time_gaps(self):
        """Test interpolation across large time gaps."""
        interpolator = geo.Interpolator([self.large_gaps_track])

        # Interpolate in a large time gap
        point = interpolator.interpolate(9000.0)
        self.assertEqual(point.time, 9000.0)
        # Should interpolate linearly despite the large gap
        self.assertAlmostEqual(point.lat, 70.05)
        self.assertAlmostEqual(point.lon, 80.05)
        self.assertAlmostEqual(point.alt, 405)

    def test_antimeridian_crossing(self):
        """Test interpolation across the antimeridian (180/-180 longitude)."""
        interpolator = geo.Interpolator([self.antimeridian_track])

        # Interpolate across the antimeridian
        point = interpolator.interpolate(5050.0)
        self.assertEqual(point.time, 5050.0)
        self.assertAlmostEqual(point.lat, 0.05)
        # This is tricky - we need to check if the angle calculation is correct
        # The bearing should adjust correctly for the antimeridian crossing

    def test_polar_region(self):
        """Test interpolation near the poles."""
        interpolator = geo.Interpolator([self.polar_track])

        # Interpolate near the poles
        point = interpolator.interpolate(6150.0)
        self.assertEqual(point.time, 6150.0)
        self.assertAlmostEqual(point.lat, 89.5)
        # Near the poles, longitude values can change rapidly for small movements

    def test_multiple_tracks(self):
        """Test interpolation across multiple tracks."""
        interpolator = geo.Interpolator([self.track_1, self.track_2, self.track_3])

        # Interpolate within first track
        point = interpolator.interpolate(7050.0)
        self.assertEqual(point.time, 7050.0)
        self.assertAlmostEqual(point.lat, 10.05)
        self.assertAlmostEqual(point.lon, 20.05)

        # Interpolate in gap between tracks (should use the appropriate tracks)
        point = interpolator.interpolate(7400.0)
        self.assertEqual(point.time, 7400.0)
        # Should extrapolate from track_1

        # Interpolate within second track
        point = interpolator.interpolate(7550.0)
        self.assertEqual(point.time, 7550.0)
        self.assertAlmostEqual(point.lat, 11.05)
        self.assertAlmostEqual(point.lon, 21.05)

        # Interpolate in gap between tracks again
        point = interpolator.interpolate(7900.0)
        self.assertEqual(point.time, 7900.0)
        # Should extrapolate from track_2

        # Interpolate within third track
        point = interpolator.interpolate(8050.0)
        self.assertEqual(point.time, 8050.0)
        self.assertAlmostEqual(point.lat, 12.05)
        self.assertAlmostEqual(point.lon, 22.05)

        # Interpolate after all tracks
        point = interpolator.interpolate(8500.0)
        self.assertEqual(point.time, 8500.0)
        # Should extrapolate from track_3

    def test_sequence_of_calls(self):
        """Test a sequence of interpolation calls in different orders."""
        interpolator = geo.Interpolator([self.track_1, self.track_2, self.track_3])

        # Sequential calls with increasing time
        point1 = interpolator.interpolate(7100.0)
        point2 = interpolator.interpolate(7200.0)
        point3 = interpolator.interpolate(7600.0)
        point4 = interpolator.interpolate(8100.0)

        # All points should be correctly interpolated
        self.assertAlmostEqual(point1.lat, 10.1)
        self.assertAlmostEqual(point2.lat, 10.2)
        self.assertAlmostEqual(point3.lat, 11.1)
        self.assertAlmostEqual(point4.lat, 12.1)

    def test_non_monotonic_times(self):
        """Test that the interpolator raises on non-monotonic times."""
        interpolator = geo.Interpolator([self.regular_track])

        # First call should work
        interpolator.interpolate(1100.0)

        # Second call with earlier time should fail
        with self.assertRaises(ValueError):
            interpolator.interpolate(1050.0)

    def test_none_values(self):
        """Test interpolation with None values for alt and angle."""
        interpolator = geo.Interpolator([self.none_values_track])

        # Interpolate with None values
        point = interpolator.interpolate(9050.0)
        self.assertEqual(point.time, 9050.0)
        self.assertAlmostEqual(point.lat, 80.05)
        self.assertAlmostEqual(point.lon, 90.05)
        self.assertIsNone(point.alt)
        # Angle should be calculated even if the original points have None angles

    def test_mixed_none_values(self):
        """Test interpolation with mixed None and non-None values."""
        interpolator = geo.Interpolator([self.mixed_values_track])

        # Interpolate between None and non-None values
        point = interpolator.interpolate(10050.0)
        self.assertEqual(point.time, 10050.0)
        self.assertAlmostEqual(point.lat, 85.05)
        self.assertAlmostEqual(point.lon, 95.05)
        # Alt should be None because one of the endpoints has None
        self.assertIsNone(point.alt)

    def test_empty_tracks(self):
        """Test with empty track list (should raise)."""
        with self.assertRaises(ValueError):
            geo.Interpolator([])

    def test_single_point_track(self):
        """Test interpolation with a track containing only one point."""
        single_point_track = [
            Point(time=11000.0, lat=90.0, lon=100.0, alt=900, angle=0)
        ]
        interpolator = geo.Interpolator([single_point_track])

        # Interpolate before the point (should use the only point)
        point = interpolator.interpolate(10900.0)
        self.assertEqual(point.time, 10900.0)
        self.assertAlmostEqual(point.lat, 90.0)
        self.assertAlmostEqual(point.lon, 100.0)
        self.assertAlmostEqual(point.alt, 900)

        # Interpolate at the exact time
        point = interpolator.interpolate(11000.0)
        self.assertEqual(point.time, 11000.0)
        self.assertAlmostEqual(point.lat, 90.0)
        self.assertAlmostEqual(point.lon, 100.0)
        self.assertAlmostEqual(point.alt, 900)

        # Interpolate after the point (should use the only point)
        point = interpolator.interpolate(11100.0)
        self.assertEqual(point.time, 11100.0)
        self.assertAlmostEqual(point.lat, 90.0)
        self.assertAlmostEqual(point.lon, 100.0)
        self.assertAlmostEqual(point.alt, 900)

    def test_out_of_order_tracks(self):
        """Test with tracks provided in non-chronological order."""
        # Create tracks in the wrong order
        interpolator = geo.Interpolator([self.track_3, self.track_1, self.track_2])

        # Should interpolate correctly despite the initial order
        point = interpolator.interpolate(7050.0)
        self.assertEqual(point.time, 7050.0)
        self.assertAlmostEqual(point.lat, 10.05)
        self.assertAlmostEqual(point.lon, 20.05)

    def test_bisect_optimization(self):
        """Test that the bisect optimization works correctly."""
        # Create a long track to test bisect optimization
        long_track = []
        for i in range(1000):
            long_track.append(
                Point(
                    time=12000.0 + i,
                    lat=0.0 + i * 0.001,
                    lon=0.0 + i * 0.001,
                    alt=0.0 + i,
                    angle=0.0,
                )
            )

        interpolator = geo.Interpolator([long_track])

        # Interpolate at various points and ensure accuracy
        point1 = interpolator.interpolate(12100.5)
        self.assertAlmostEqual(point1.lat, 0.1005)

        point2 = interpolator.interpolate(12500.5)
        self.assertAlmostEqual(point2.lat, 0.5005)

        point3 = interpolator.interpolate(12900.5)
        self.assertAlmostEqual(point3.lat, 0.9005)

    def test_overlapping_tracks(self):
        """Test with overlapping tracks in time."""
        # Create overlapping tracks
        track_overlap_1 = [
            Point(time=13000.0, lat=10.0, lon=20.0, alt=100, angle=0),
            Point(time=13100.0, lat=10.1, lon=20.1, alt=110, angle=10),
            Point(time=13200.0, lat=10.2, lon=20.2, alt=120, angle=20),
        ]

        track_overlap_2 = [
            Point(time=13150.0, lat=11.0, lon=21.0, alt=150, angle=30),
            Point(time=13250.0, lat=11.1, lon=21.1, alt=160, angle=40),
            Point(time=13350.0, lat=11.2, lon=21.2, alt=170, angle=50),
        ]

        interpolator = geo.Interpolator([track_overlap_1, track_overlap_2])

        # Test point in first track before overlap
        point = interpolator.interpolate(13050.0)
        self.assertEqual(point.time, 13050.0)
        self.assertAlmostEqual(point.lat, 10.05)

        # Test point in overlap region (should use first track)
        point = interpolator.interpolate(13175.0)
        self.assertEqual(point.time, 13175.0)
        self.assertAlmostEqual(point.lat, 10.175)  # From track_overlap_1

        # Test point in second track after overlap
        point = interpolator.interpolate(13300.0)
        self.assertEqual(point.time, 13300.0)
        self.assertAlmostEqual(point.lat, 11.15)  # From track_overlap_2

    def test_extreme_value_tracks(self):
        """Test with extreme timestamp values."""
        # Create track with very large timestamps
        large_time_track = [
            Point(time=1e12, lat=1.0, lon=1.0, alt=100, angle=0),
            Point(time=1e12 + 100, lat=1.1, lon=1.1, alt=110, angle=10),
        ]

        # Create track with very small timestamps
        small_time_track = [
            Point(time=1e-12, lat=2.0, lon=2.0, alt=200, angle=20),
            Point(time=2e-12, lat=2.1, lon=2.1, alt=210, angle=30),
        ]

        # Test large timestamps
        interpolator = geo.Interpolator([large_time_track])
        point = interpolator.interpolate(1e12 + 50)
        self.assertEqual(point.time, 1e12 + 50)
        self.assertAlmostEqual(point.lat, 1.05)

        # Test small timestamps
        interpolator = geo.Interpolator([small_time_track])
        point = interpolator.interpolate(1.5e-12)
        self.assertEqual(point.time, 1.5e-12)
        self.assertAlmostEqual(point.lat, 2.05)

    def test_negative_timestamps(self):
        """Test with negative timestamp values."""
        negative_time_track = [
            Point(time=-1000.0, lat=3.0, lon=3.0, alt=300, angle=0),
            Point(time=-900.0, lat=3.1, lon=3.1, alt=310, angle=10),
            Point(time=-800.0, lat=3.2, lon=3.2, alt=320, angle=20),
        ]

        interpolator = geo.Interpolator([negative_time_track])

        # Interpolate at negative time
        point = interpolator.interpolate(-950.0)
        self.assertEqual(point.time, -950.0)
        self.assertAlmostEqual(point.lat, 3.05)
        self.assertAlmostEqual(point.lon, 3.05)
        self.assertAlmostEqual(point.alt, 305)
