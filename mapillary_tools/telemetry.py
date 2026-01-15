from __future__ import annotations

import dataclasses
from enum import Enum, unique

from .geo import Point


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
    epoch_time: float | None
    fix: GPSFix | None
    precision: float | None
    ground_speed: float | None

    def get_gps_epoch_time(self) -> float | None:
        """Return the GPS epoch time if valid, otherwise None."""
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
    time_gps_epoch: float
    gps_fix_type: int
    horizontal_accuracy: float
    vertical_accuracy: float
    velocity_east: float
    velocity_north: float
    velocity_up: float
    speed_accuracy: float

    def get_gps_epoch_time(self) -> float | None:
        """Return the GPS epoch time if valid, otherwise None."""
        if self.time_gps_epoch > 0:
            return self.time_gps_epoch
        return None

    def interpolate_with(self, other: Point, t: float) -> Point:
        """Create a new interpolated CAMMGPSPoint using this and other point at time t."""
        base = super().interpolate_with(other, t)
        if not isinstance(other, CAMMGPSPoint):
            return base

        # Interpolate all CAMM-specific fields
        weight = self._calculate_weight_for_interpolation(other, t)
        time_gps_epoch = (
            self.time_gps_epoch + (other.time_gps_epoch - self.time_gps_epoch) * weight
        )
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
            time_gps_epoch=time_gps_epoch,
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
