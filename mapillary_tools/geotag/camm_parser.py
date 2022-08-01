import datetime
import io
import typing as T

import construct as C

from ..geo import TimeDeltaPoint
from .simple_mp4_parser import Sample, parse_path, parse_samples_from_trak

Float = C.Float32l
Double = C.Float64l


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
            yield TimeDeltaPoint(
                delta=sample.delta,
                lat=box.data[0],
                lon=box.data[1],
                alt=box.data[2],
                angle=None,
            )
        elif box.type == 6:
            # Not using box.data.time_gps_epoch as the point timestamp
            # because it is from another clock
            yield TimeDeltaPoint(
                delta=sample.delta,
                lat=box.data.latitude,
                lon=box.data.longitude,
                alt=box.data.altitude,
                angle=None,
            )


def parse_gpx(path: str) -> T.List[TimeDeltaPoint]:
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


if __name__ == "__main__":
    import sys, os
    from .. import utils, types
    from . import utils as geotag_utils

    def _convert(path: str):
        delta_points = parse_gpx(path)
        points = [
            types.GPXPoint(
                time=datetime.datetime.utcfromtimestamp(p.delta),
                lat=p.lat,
                lon=p.lon,
                alt=p.alt,
            )
            for p in delta_points
        ]
        gpx = geotag_utils.convert_points_to_gpx(points)
        print(gpx.to_xml())

    for path in sys.argv[1:]:
        if os.path.isdir(path):
            for p in utils.get_video_file_list(path, abs_path=True):
                _convert(p)
        else:
            _convert(path)
