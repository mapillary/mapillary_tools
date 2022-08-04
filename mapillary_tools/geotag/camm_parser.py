import io
import typing as T
from enum import Enum

import construct as C

from . import geo
from .simple_mp4_parser import parse_path, parse_samples_from_trak, Sample


# Camera Motion Metadata Spec https://developers.google.com/streetview/publish/camm-spec
class CAMMType(Enum):
    ANGLE_AXIS = 0
    EXPOSURE_TIME = 1
    GYRO = 2
    ACCELERATION = 3
    POSITION = 4
    MIN_GPS = 5
    GPS = 6
    MAGNETIC_FIELD = 7


# All fields are little-endian
Float = C.Float32l
Double = C.Float64l

_SWITCH: T.Dict[int, C.Struct] = {
    # angle_axis
    CAMMType.ANGLE_AXIS.value: Float[3],
    CAMMType.EXPOSURE_TIME.value: C.Struct(
        "pixel_exposure_time" / C.Int32sl,
        "rolling_shutter_skew_time" / C.Int32sl,
    ),
    # gyro
    CAMMType.GYRO.value: Float[3],
    # acceleration
    CAMMType.ACCELERATION.value: Float[3],
    # position
    CAMMType.POSITION.value: Float[3],
    # lat, lon, alt
    CAMMType.MIN_GPS.value: Double[3],
    CAMMType.GPS.value: C.Struct(
        "time_gps_epoch" / Double,
        "gps_fix_type" / C.Int32sl,
        "latitude" / Double,
        "longitude" / Double,
        "altitude" / Float,
        "horizontal_accuracy" / Float,
        "vertical_accuracy" / Float,
        "velocity_east" / Float,
        "velocity_north" / Float,
        "velocity_up" / Float,
        "speed_accuracy" / Float,
    ),
    # magnetic_field
    CAMMType.MAGNETIC_FIELD.value: Float[3],
}

CAMMSampleData = C.Struct(
    C.Padding(2),
    "type" / C.Int16ul,
    "data"
    / C.Switch(
        C.this.type,
        _SWITCH,
    ),
)


def _extract_delta_points(fp: T.BinaryIO, samples: T.Iterable[Sample]):
    for sample in samples:
        fp.seek(sample.offset, io.SEEK_SET)
        data = fp.read(sample.size)
        box = CAMMSampleData.parse(data)
        if box.type == CAMMType.MIN_GPS.value:
            yield geo.Point(
                time=sample.delta,
                lat=box.data[0],
                lon=box.data[1],
                alt=box.data[2],
                angle=None,
            )
        elif box.type == CAMMType.GPS.value:
            # Not using box.data.time_gps_epoch as the point timestamp
            # because it is from another clock
            yield geo.Point(
                time=sample.delta,
                lat=box.data.latitude,
                lon=box.data.longitude,
                alt=box.data.altitude,
                angle=None,
            )


def parse_gpx(path: str) -> T.List[geo.Point]:
    with open(path, "rb") as fp:
        for h, s in parse_path(fp, [b"moov", b"trak"]):
            camm_samples = (
                sample
                for sample in parse_samples_from_trak(s, maxsize=h.maxsize)
                if sample.description.format == b"camm"
            )
            points = list(_extract_delta_points(fp, camm_samples))
            if points:
                return points
    return []
