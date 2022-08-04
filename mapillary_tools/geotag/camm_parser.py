import io
import typing as T

import construct as C

from . import geo
from .simple_mp4_parser import Sample, parse_path, parse_samples_from_trak

# All fields are little-endian
Float = C.Float32l
Double = C.Float64l


# Camera Motion Metadata Spec https://developers.google.com/streetview/publish/camm-spec
CAMMSampleData = C.Struct(
    C.Padding(2),
    "type" / C.Int16ul,
    "data"
    / C.Switch(
        C.this.type,
        {
            # angle_axis
            0: Float[3],
            1: C.Struct(
                "pixel_exposure_time" / C.Int32sl,
                "rolling_shutter_skew_time" / C.Int32sl,
            ),
            # gyro
            2: Float[3],
            # acceleration
            3: Float[3],
            # position
            4: Float[3],
            # lat, lon, alt
            5: Double[3],
            6: C.Struct(
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
            7: Float[3],
        },
    ),
)


def _extract_delta_points(fp: T.BinaryIO, samples: T.Iterable[Sample]):
    for sample in samples:
        fp.seek(sample.offset, io.SEEK_SET)
        data = fp.read(sample.size)
        box = CAMMSampleData.parse(data)
        if box.type == 5:
            yield geo.TimeDeltaPoint(
                time=sample.delta,
                lat=box.data[0],
                lon=box.data[1],
                alt=box.data[2],
                angle=None,
            )
        elif box.type == 6:
            # Not using box.data.time_gps_epoch as the point timestamp
            # because it is from another clock
            yield geo.TimeDeltaPoint(
                time=sample.delta,
                lat=box.data.latitude,
                lon=box.data.longitude,
                alt=box.data.altitude,
                angle=None,
            )


def parse_gpx(path: str) -> T.List[geo.TimeDeltaPoint]:
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
