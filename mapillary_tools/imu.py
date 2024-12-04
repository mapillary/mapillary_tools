import typing as T


# Gyroscope signal in radians/seconds around XYZ axes of the camera. Rotation is positive in the counterclockwise direction.
class GyroscopeData(T.NamedTuple):
    time: float
    x: float
    y: float
    z: float


# Accelerometer reading in meters/second^2 along XYZ axes of the camera.
class AccelerationData(T.NamedTuple):
    time: float
    x: float
    y: float
    z: float


# Ambient magnetic field.
class MagnetometerData(T.NamedTuple):
    time: float
    x: float
    y: float
    z: float
