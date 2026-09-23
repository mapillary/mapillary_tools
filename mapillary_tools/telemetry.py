# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

# pyre-ignore-all-errors[16]
from __future__ import annotations

import bisect
import calendar
import dataclasses
from enum import Enum, unique

from .geo import Point


# Seconds between the Unix epoch (1970-01-01) and the GPS epoch (1980-01-06).
GPS_EPOCH_UNIX_OFFSET = 315964800

# UTC dates on which a leap second took effect since the GPS epoch. GPS time is
# a continuous scale that does not count leap seconds, so converting it to UTC
# requires subtracting however many have accumulated. There has been no leap
# second since 2017-01-01 (GPS - UTC = 18s); append here if one is announced.
_LEAP_SECOND_UTC_DATES: tuple[tuple[int, int, int], ...] = (
    (1981, 7, 1),
    (1982, 7, 1),
    (1983, 7, 1),
    (1985, 7, 1),
    (1988, 1, 1),
    (1990, 1, 1),
    (1991, 1, 1),
    (1992, 7, 1),
    (1993, 7, 1),
    (1994, 7, 1),
    (1996, 1, 1),
    (1997, 7, 1),
    (1999, 1, 1),
    (2006, 1, 1),
    (2009, 1, 1),
    (2012, 7, 1),
    (2015, 7, 1),
    (2017, 1, 1),
)

_LEAP_SECOND_UNIX_TIMES: tuple[int, ...] = tuple(
    calendar.timegm((year, month, day, 0, 0, 0))
    for year, month, day in _LEAP_SECOND_UTC_DATES
)


def _gps_utc_offset_at(unix_time: float) -> int:
    """
    Number of leap seconds GPS time is ahead of UTC at the given Unix time.

    >>> _gps_utc_offset_at(0)  # before the GPS epoch
    0
    >>> _gps_utc_offset_at(1786523187)  # 2026
    18
    """
    return bisect.bisect_right(_LEAP_SECOND_UNIX_TIMES, unix_time)


def gps_epoch_to_unix(gps_epoch_time: float) -> float:
    """
    Convert seconds since the GPS epoch (GPS time) to Unix time (UTC).

    Only called at the parse boundary, for producers known to record GPS time.

    >>> gps_epoch_to_unix(1470558405.9798455)
    1786523187.9798455
    """
    # The leap-second lookup is done on the uncorrected value. That is only
    # ambiguous for instants within ~18s of a leap-second boundary.
    approx_unix_time = gps_epoch_time + GPS_EPOCH_UNIX_OFFSET
    return approx_unix_time - _gps_utc_offset_at(approx_unix_time)


@unique
class GPSFix(Enum):
    NO_FIX = 0
    FIX_2D = 2
    FIX_3D = 3


@dataclasses.dataclass(order=True)
class TimestampedMeasurement:
    """Base class for all telemetry measurements.

    All telemetry measurements must have a timestamp in seconds.
    This is an abstract base class - do not instantiate directly.
    Instead use the concrete subclasses: AccelerationData, GyroscopeData, etc.
    """

    time: float


@dataclasses.dataclass
class GPSPoint(TimestampedMeasurement, Point):
    # Unix time (UTC), NOT seconds since the GPS epoch
    epoch_time: float | None
    fix: GPSFix | None
    precision: float | None
    ground_speed: float | None

    def get_unix_time(self) -> float | None:
        """Return the Unix time if valid, otherwise None."""
        if self.epoch_time is not None and self.epoch_time > 0:
            return self.epoch_time
        return None

    def interpolate_with(self, other: Point, t: float) -> Point:
        """Create a new interpolated GPSPoint using this and other point at time t."""
        base = super().interpolate_with(other, t)
        if not isinstance(other, GPSPoint):
            return base

        # Interpolate GPSPoint-specific fields
        weight = self._calculate_weight_for_interpolation(other, t)
        epoch_time: float | None
        if (
            self.epoch_time is not None
            and other.epoch_time is not None
            and self.epoch_time > 0
            and other.epoch_time > 0
        ):
            epoch_time = self.epoch_time + (other.epoch_time - self.epoch_time) * weight
        else:
            epoch_time = None

        precision: float | None
        if self.precision is not None and other.precision is not None:
            precision = self.precision + (other.precision - self.precision) * weight
        else:
            precision = None

        ground_speed: float | None
        if self.ground_speed is not None and other.ground_speed is not None:
            ground_speed = (
                self.ground_speed + (other.ground_speed - self.ground_speed) * weight
            )
        else:
            ground_speed = None

        return GPSPoint(
            time=base.time,
            lat=base.lat,
            lon=base.lon,
            alt=base.alt,
            angle=base.angle,
            epoch_time=epoch_time,
            fix=self.fix,  # Use start point's fix value
            precision=precision,
            ground_speed=ground_speed,
        )


@dataclasses.dataclass
class CAMMGPSPoint(TimestampedMeasurement, Point):
    # Unix time (UTC), same meaning as GPSPoint.epoch_time.
    #
    # The corresponding CAMM box field is named time_gps_epoch, but what
    # producers actually store there varies: Labpano cameras record GPS time,
    # while Insta360 and mapillary_tools itself record Unix time. Whatever the
    # producer wrote is normalized to Unix time once, when the CAMM track is
    # parsed (see camm_parser.extract_camm_info), so that everything
    # downstream can rely on a single meaning.
    epoch_time: float
    gps_fix_type: int
    horizontal_accuracy: float
    vertical_accuracy: float
    velocity_east: float
    velocity_north: float
    velocity_up: float
    speed_accuracy: float

    def get_unix_time(self) -> float | None:
        """Return the Unix time if valid, otherwise None."""
        if self.epoch_time > 0:
            return self.epoch_time
        return None

    def interpolate_with(self, other: Point, t: float) -> Point:
        """Create a new interpolated CAMMGPSPoint using this and other point at time t."""
        base = super().interpolate_with(other, t)
        if not isinstance(other, CAMMGPSPoint):
            return base

        # Interpolate all CAMM-specific fields
        weight = self._calculate_weight_for_interpolation(other, t)
        epoch_time = self.epoch_time + (other.epoch_time - self.epoch_time) * weight
        horizontal_accuracy = (
            self.horizontal_accuracy
            + (other.horizontal_accuracy - self.horizontal_accuracy) * weight
        )
        vertical_accuracy = (
            self.vertical_accuracy
            + (other.vertical_accuracy - self.vertical_accuracy) * weight
        )
        velocity_east = (
            self.velocity_east + (other.velocity_east - self.velocity_east) * weight
        )
        velocity_north = (
            self.velocity_north + (other.velocity_north - self.velocity_north) * weight
        )
        velocity_up = self.velocity_up + (other.velocity_up - self.velocity_up) * weight
        speed_accuracy = (
            self.speed_accuracy + (other.speed_accuracy - self.speed_accuracy) * weight
        )

        return CAMMGPSPoint(
            time=base.time,
            lat=base.lat,
            lon=base.lon,
            alt=base.alt,
            angle=base.angle,
            epoch_time=epoch_time,
            gps_fix_type=self.gps_fix_type,  # Use start point's fix type
            horizontal_accuracy=horizontal_accuracy,
            vertical_accuracy=vertical_accuracy,
            velocity_east=velocity_east,
            velocity_north=velocity_north,
            velocity_up=velocity_up,
            speed_accuracy=speed_accuracy,
        )


@dataclasses.dataclass(order=True)
class GyroscopeData(TimestampedMeasurement):
    """Gyroscope signal in radians/seconds around XYZ axes of the camera."""

    x: float
    y: float
    z: float


@dataclasses.dataclass(order=True)
class AccelerationData(TimestampedMeasurement):
    """Accelerometer reading in meters/second^2 along XYZ axes of the camera."""

    x: float
    y: float
    z: float


@dataclasses.dataclass(order=True)
class MagnetometerData(TimestampedMeasurement):
    """Ambient magnetic field."""

    x: float
    y: float
    z: float
