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
