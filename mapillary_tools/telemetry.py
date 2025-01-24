import dataclasses
import typing as T
from enum import Enum, unique

from .geo import Point


@unique
class GPSFix(Enum):
    NO_FIX = 0
    FIX_2D = 2
    FIX_3D = 3


@dataclasses.dataclass
class GPSPoint(Point):
    epoch_time: T.Optional[float]
    fix: T.Optional[GPSFix]
    precision: T.Optional[float]
    ground_speed: T.Optional[float]


@dataclasses.dataclass(order=True)
class TelemetryMeasurement:
    """Base class for all telemetry measurements.

    All telemetry measurements must have a timestamp in seconds.
    This is an abstract base class - do not instantiate directly.
    Instead use the concrete subclasses: AccelerationData, GyroscopeData, etc.
    """

    time: float


@dataclasses.dataclass(order=True)
class GyroscopeData(TelemetryMeasurement):
    """Gyroscope signal in radians/seconds around XYZ axes of the camera."""

    x: float
    y: float
    z: float


@dataclasses.dataclass(order=True)
class AccelerationData(TelemetryMeasurement):
    """Accelerometer reading in meters/second^2 along XYZ axes of the camera."""

    x: float
    y: float
    z: float


@dataclasses.dataclass(order=True)
class MagnetometerData(TelemetryMeasurement):
    """Ambient magnetic field."""

    x: float
    y: float
    z: float
