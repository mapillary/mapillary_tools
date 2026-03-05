# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import statistics

import pytest

from mapillary_tools.geo import Point
from mapillary_tools.gpmf import gps_filter
from mapillary_tools.gpmf.gpmf_gps_filter import remove_noisy_points, remove_outliers
from mapillary_tools.telemetry import GPSFix, GPSPoint


def _make_point(time: float, lat: float, lon: float) -> Point:
    return Point(time=time, lat=lat, lon=lon, alt=None, angle=None)


def _make_gps_point(
    time: float,
    lat: float,
    lon: float,
    fix: GPSFix | None = GPSFix.FIX_3D,
    precision: float | None = 100,
    ground_speed: float | None = 5.0,
) -> GPSPoint:
    return GPSPoint(
        time=time,
        lat=lat,
        lon=lon,
        alt=None,
        angle=None,
        epoch_time=None,
        fix=fix,
        precision=precision,
        ground_speed=ground_speed,
    )


# --- Tests for gps_filter module ---


class TestCalculatePointSpeed:
    def test_same_point_zero_time(self):
        p = _make_point(0.0, 48.0, 11.0)
        speed = gps_filter.calculate_point_speed(p, p)
        assert speed == float("inf")

    def test_same_point_different_time(self):
        p1 = _make_point(0.0, 48.0, 11.0)
        p2 = _make_point(10.0, 48.0, 11.0)
        speed = gps_filter.calculate_point_speed(p1, p2)
        assert speed == 0.0

    def test_speed_calculation(self):
        p1 = _make_point(0.0, 0.0, 0.0)
        p2 = _make_point(10.0, 0.001, 0.0)  # ~111 meters
        speed = gps_filter.calculate_point_speed(p1, p2)
        assert 10 < speed < 12  # ~11.1 m/s


class TestSplitIf:
    def test_empty_list(self):
        assert gps_filter.split_if([], lambda a, b: True) == []

    def test_single_point(self):
        p = _make_point(0.0, 0.0, 0.0)
        result = gps_filter.split_if([p], lambda a, b: True)
        assert len(result) == 1
        assert result[0] == [p]

    def test_no_splits(self):
        points = [_make_point(float(i), 0.0, 0.0) for i in range(5)]
        result = gps_filter.split_if(points, lambda a, b: False)
        assert len(result) == 1
        assert len(result[0]) == 5

    def test_split_every_point(self):
        points = [_make_point(float(i), 0.0, 0.0) for i in range(5)]
        result = gps_filter.split_if(points, lambda a, b: True)
        assert len(result) == 5
        for seq in result:
            assert len(seq) == 1


class TestDistanceGt:
    def test_close_points_not_split(self):
        decider = gps_filter.distance_gt(100000)
        p1 = _make_point(0.0, 48.0, 11.0)
        p2 = _make_point(1.0, 48.001, 11.001)
        assert decider(p1, p2) is False

    def test_far_points_split(self):
        decider = gps_filter.distance_gt(100)
        p1 = _make_point(0.0, 0.0, 0.0)
        p2 = _make_point(1.0, 1.0, 1.0)
        assert decider(p1, p2) is True


class TestSpeedLe:
    def test_slow_speed_true(self):
        decider = gps_filter.speed_le(1000)
        p1 = _make_point(0.0, 48.0, 11.0)
        p2 = _make_point(10.0, 48.001, 11.001)
        assert decider(p1, p2) is True

    def test_fast_speed_false(self):
        decider = gps_filter.speed_le(0.001)
        p1 = _make_point(0.0, 0.0, 0.0)
        p2 = _make_point(1.0, 1.0, 1.0)
        assert decider(p1, p2) is False


class TestUpperWhiskerEdge:
    def test_raises_on_single_value(self):
        with pytest.raises(statistics.StatisticsError):
            gps_filter.upper_whisker([1])

    def test_even_length(self):
        # [1, 2, 3, 4] -> q1=1.5, q3=3.5, irq=2, upper=3.5+3=6.5
        assert gps_filter.upper_whisker([1, 2, 3, 4]) == 6.5

    def test_odd_length(self):
        # [1, 2, 3, 4, 5] -> q1=median([1,2])=1.5, q3=median([4,5])=4.5, irq=3, upper=4.5+4.5=9.0
        assert gps_filter.upper_whisker([1, 2, 3, 4, 5]) == 9.0


# --- Tests for gpmf_gps_filter module ---


class TestRemoveNoisyPoints:
    def test_empty_sequence(self):
        result = remove_noisy_points([])
        assert list(result) == []

    def test_all_good_points(self):
        points = [
            _make_gps_point(
                float(i), 48.0 + i * 0.0001, 11.0, fix=GPSFix.FIX_3D, precision=100
            )
            for i in range(10)
        ]
        result = remove_noisy_points(points)
        assert len(result) == len(points)

    def test_filters_bad_fix(self):
        good_0 = _make_gps_point(0.0, 48.0, 11.0, fix=GPSFix.FIX_3D)
        bad_1 = _make_gps_point(1.0, 48.001, 11.001, fix=GPSFix.NO_FIX)
        good_2 = _make_gps_point(2.0, 48.002, 11.002, fix=GPSFix.FIX_3D)
        result = list(remove_noisy_points([good_0, bad_1, good_2]))
        # NO_FIX point should be removed; FIX_3D points kept
        assert bad_1 not in result
        assert good_0 in result
        assert good_2 in result

    def test_filters_high_precision(self):
        good_0 = _make_gps_point(0.0, 48.0, 11.0, precision=100)
        bad_1 = _make_gps_point(1.0, 48.001, 11.001, precision=9999)  # Very high DOP
        good_2 = _make_gps_point(2.0, 48.002, 11.002, precision=100)
        result = list(remove_noisy_points([good_0, bad_1, good_2]))
        # High DOP point should be removed; low DOP points kept
        assert bad_1 not in result
        assert good_0 in result
        assert good_2 in result

    def test_none_fix_kept(self):
        """Points without GPS fix info should be kept."""
        points = [
            _make_gps_point(0.0, 48.0, 11.0, fix=None),
            _make_gps_point(1.0, 48.001, 11.001, fix=None),
        ]
        result = remove_noisy_points(points)
        assert len(result) == 2

    def test_none_precision_kept(self):
        """Points without precision info should be kept."""
        points = [
            _make_gps_point(0.0, 48.0, 11.0, precision=None),
            _make_gps_point(1.0, 48.001, 11.001, precision=None),
        ]
        result = remove_noisy_points(points)
        assert len(result) == 2


class TestRemoveOutliers:
    def test_short_sequence_unchanged(self):
        points = [
            _make_gps_point(0.0, 48.0, 11.0),
        ]
        result = remove_outliers(points)
        assert len(result) == 1

    def test_no_ground_speed_returns_original(self):
        points = [
            _make_gps_point(0.0, 48.0, 11.0, ground_speed=None),
            _make_gps_point(1.0, 48.001, 11.001, ground_speed=None),
            _make_gps_point(2.0, 48.002, 11.002, ground_speed=None),
        ]
        result = remove_outliers(points)
        assert len(result) == len(points)

    def test_consistent_sequence_kept(self):
        points = [
            _make_gps_point(
                float(i), 48.0 + i * 0.0001, 11.0 + i * 0.0001, ground_speed=5.0
            )
            for i in range(10)
        ]
        result = remove_outliers(points)
        assert len(result) == len(points)

    def test_outlier_removed(self):
        """A point far away from a consistent cluster should be dropped."""
        # 9 points in a tight cluster, then 1 point far away
        cluster = [
            _make_gps_point(
                float(i), 48.0 + i * 0.00001, 11.0 + i * 0.00001, ground_speed=1.0
            )
            for i in range(9)
        ]
        outlier = _make_gps_point(9.0, 10.0, 10.0, ground_speed=1.0)
        result = remove_outliers(cluster + [outlier])
        # The outlier is far from the cluster and should be removed
        assert len(result) < len(cluster) + 1
        # The cluster points should survive
        assert len(result) >= len(cluster)
