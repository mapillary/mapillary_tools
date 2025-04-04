# pyre-ignore-all-errors[5, 11, 16, 21, 24, 58]
from __future__ import annotations

import abc
import dataclasses
import io
import logging
import typing as T
from enum import Enum

import construct as C
from typing_extensions import TypeIs

from .. import geo, telemetry
from ..mp4.mp4_sample_parser import MovieBoxParser, Sample, TrackBoxParser


LOG = logging.getLogger(__name__)
# All fields are little-endian
_Float = C.Float32l
_Double = C.Float64l


TelemetryMeasurement = T.Union[
    geo.Point,
    telemetry.TimestampedMeasurement,
]


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


TTelemetry = T.TypeVar("TTelemetry", bound=TelemetryMeasurement)


@dataclasses.dataclass
class CAMMInfo:
    # None indicates the data has been extracted,
    # while [] indicates extracetd but no data point found
    mini_gps: list[geo.Point] | None = None
    gps: list[telemetry.CAMMGPSPoint] | None = None
    accl: list[telemetry.AccelerationData] | None = None
    gyro: list[telemetry.GyroscopeData] | None = None
    magn: list[telemetry.MagnetometerData] | None = None
    make: str = ""
    model: str = ""


def extract_camm_info(fp: T.BinaryIO, telemetry_only: bool = False) -> CAMMInfo | None:
    moov = MovieBoxParser.parse_stream(fp)

    make, model = "", ""
    if not telemetry_only:
        udta_boxdata = moov.extract_udta_boxdata()
        if udta_boxdata is not None:
            make, model = _extract_camera_make_and_model_from_utda_boxdata(udta_boxdata)

    gps_only_construct = _construct_with_selected_camm_types(
        [CAMMType.MIN_GPS, CAMMType.GPS]
    )
    # Optimization: skip parsing sample data smaller than 16 bytes
    # because we are only interested in MIN_GPS and GPS which are larger than 16 bytes
    MIN_GPS_SAMPLE_SIZE = 17

    for track in moov.extract_tracks():
        if _contains_camm_description(track):
            if telemetry_only:
                maybe_measurements = (
                    _parse_telemetry_from_sample(fp, sample)
                    for sample in track.extract_samples()
                    if _is_camm_description(sample.description)
                )
                measurements = _filter_telemetry_by_track_elst(
                    moov, track, (m for m in maybe_measurements if m is not None)
                )

                accl: list[telemetry.AccelerationData] = []
                gyro: list[telemetry.GyroscopeData] = []
                magn: list[telemetry.MagnetometerData] = []

                for measurement in measurements:
                    if isinstance(measurement, telemetry.AccelerationData):
                        accl.append(measurement)
                    elif isinstance(measurement, telemetry.GyroscopeData):
                        gyro.append(measurement)
                    elif isinstance(measurement, telemetry.MagnetometerData):
                        magn.append(measurement)

                return CAMMInfo(accl=accl, gyro=gyro, magn=magn)
            else:
                maybe_measurements = (
                    _parse_telemetry_from_sample(fp, sample, gps_only_construct)
                    for sample in track.extract_samples()
                    if _is_camm_description(sample.description)
                    and sample.raw_sample.size >= MIN_GPS_SAMPLE_SIZE
                )
                measurements = _filter_telemetry_by_track_elst(
                    moov, track, (m for m in maybe_measurements if m is not None)
                )

                mini_gps: list[geo.Point] = []
                gps: list[telemetry.CAMMGPSPoint] = []

                for measurement in measurements:
                    if isinstance(measurement, geo.Point):
                        mini_gps.append(measurement)
                    elif isinstance(measurement, telemetry.CAMMGPSPoint):
                        gps.append(measurement)

                return CAMMInfo(mini_gps=mini_gps, gps=gps, make=make, model=model)

    return None


def extract_camera_make_and_model(fp: T.BinaryIO) -> tuple[str, str]:
    moov = MovieBoxParser.parse_stream(fp)
    udta_boxdata = moov.extract_udta_boxdata()
    if udta_boxdata is None:
        return "", ""
    return _extract_camera_make_and_model_from_utda_boxdata(udta_boxdata)


class CAMMSampleEntry(abc.ABC, T.Generic[TTelemetry]):
    serialized_camm_type: CAMMType

    telemetry_cls_type: T.Type[TTelemetry]

    construct: C.Struct

    @classmethod
    def serializable(cls, data: T.Any, throw: bool = False) -> TypeIs[TTelemetry]:
        # Use "is" for exact type match, instead of isinstance
        if type(data) is cls.telemetry_cls_type:
            return True

        if throw:
            raise TypeError(
                f"{cls} can not serialize {type(data)}: expect {cls.telemetry_cls_type}"
            )

        return False

    @classmethod
    @abc.abstractmethod
    def serialize(cls, data: TTelemetry) -> bytes:
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def deserialize(cls, sample: Sample, data: T.Any) -> TTelemetry:
        raise NotImplementedError


class MinGPSSampleEntry(CAMMSampleEntry):
    serialized_camm_type = CAMMType.MIN_GPS

    telemetry_cls_type = geo.Point

    construct = _Double[3]  # type: ignore

    @classmethod
    def deserialize(cls, sample: Sample, data: T.Any) -> geo.Point:
        return geo.Point(
            time=sample.exact_time,
            lat=data[0],
            lon=data[1],
            alt=data[2],
            angle=None,
        )

    @classmethod
    def serialize(cls, data: geo.Point) -> bytes:
        cls.serializable(data, throw=True)

        return CAMMSampleData.build(
            {
                "type": cls.serialized_camm_type.value,
                "data": [
                    data.lat,
                    data.lon,
                    -1.0 if data.alt is None else data.alt,
                ],
            }
        )


class GPSSampleEntry(CAMMSampleEntry):
    serialized_camm_type: CAMMType = CAMMType.GPS

    telemetry_cls_type = telemetry.CAMMGPSPoint

    construct = C.Struct(
        "time_gps_epoch" / _Double,  # type: ignore
        "gps_fix_type" / C.Int32sl,  # type: ignore
        "latitude" / _Double,  # type: ignore
        "longitude" / _Double,  # type: ignore
        "altitude" / _Float,  # type: ignore
        "horizontal_accuracy" / _Float,  # type: ignore
        "vertical_accuracy" / _Float,  # type: ignore
        "velocity_east" / _Float,  # type: ignore
        "velocity_north" / _Float,  # type: ignore
        "velocity_up" / _Float,  # type: ignore
        "speed_accuracy" / _Float,  # type: ignore
    )

    @classmethod
    def deserialize(cls, sample: Sample, data: T.Any) -> telemetry.CAMMGPSPoint:
        return telemetry.CAMMGPSPoint(
            time=sample.exact_time,
            lat=data.latitude,
            lon=data.longitude,
            alt=data.altitude,
            angle=None,
            time_gps_epoch=data.time_gps_epoch,
            gps_fix_type=data.gps_fix_type,
            horizontal_accuracy=data.horizontal_accuracy,
            vertical_accuracy=data.vertical_accuracy,
            velocity_east=data.velocity_east,
            velocity_north=data.velocity_north,
            velocity_up=data.velocity_up,
            speed_accuracy=data.speed_accuracy,
        )

    @classmethod
    def serialize(cls, data: telemetry.CAMMGPSPoint) -> bytes:
        cls.serializable(data, throw=True)

        return CAMMSampleData.build(
            {
                "type": cls.serialized_camm_type.value,
                "data": {
                    "time_gps_epoch": data.time_gps_epoch,
                    "gps_fix_type": data.gps_fix_type,
                    "latitude": data.lat,
                    "longitude": data.lon,
                    "altitude": -1.0 if data.alt is None else data.alt,
                    "horizontal_accuracy": data.horizontal_accuracy,
                    "vertical_accuracy": data.vertical_accuracy,
                    "velocity_east": data.velocity_east,
                    "velocity_north": data.velocity_north,
                    "velocity_up": data.velocity_up,
                    "speed_accuracy": data.speed_accuracy,
                },
            }
        )


class GoProGPSSampleEntry(CAMMSampleEntry):
    serialized_camm_type: CAMMType = CAMMType.MIN_GPS

    telemetry_cls_type = telemetry.GPSPoint

    construct = _Double[3]  # type: ignore

    @classmethod
    def deserialize(cls, sample: Sample, data: T.Any) -> telemetry.GPSPoint:
        raise NotImplementedError("Deserializing GoPro GPS Point is not supported")

    @classmethod
    def serialize(cls, data: telemetry.GPSPoint) -> bytes:
        cls.serializable(data, throw=True)

        return CAMMSampleData.build(
            {
                "type": cls.serialized_camm_type.value,
                "data": [
                    data.lat,
                    data.lon,
                    -1.0 if data.alt is None else data.alt,
                ],
            }
        )


class AccelerationSampleEntry(CAMMSampleEntry):
    serialized_camm_type: CAMMType = CAMMType.ACCELERATION

    telemetry_cls_type = telemetry.AccelerationData

    construct: C.Struct = _Float[3]  # type: ignore

    @classmethod
    def deserialize(cls, sample: Sample, data: T.Any) -> telemetry.AccelerationData:
        return telemetry.AccelerationData(
            time=sample.exact_time,
            x=data[0],
            y=data[1],
            z=data[2],
        )

    @classmethod
    def serialize(cls, data: telemetry.AccelerationData) -> bytes:
        cls.serializable(data, throw=True)

        return CAMMSampleData.build(
            {
                "type": cls.serialized_camm_type.value,
                "data": [data.x, data.y, data.z],
            }
        )


class GyroscopeSampleEntry(CAMMSampleEntry):
    serialized_camm_type: CAMMType = CAMMType.GYRO

    telemetry_cls_type = telemetry.GyroscopeData

    construct: C.Struct = _Float[3]  # type: ignore

    @classmethod
    def deserialize(cls, sample: Sample, data: T.Any) -> telemetry.GyroscopeData:
        return telemetry.GyroscopeData(
            time=sample.exact_time,
            x=data[0],
            y=data[1],
            z=data[2],
        )

    @classmethod
    def serialize(cls, data: telemetry.GyroscopeData) -> bytes:
        cls.serializable(data)

        return CAMMSampleData.build(
            {
                "type": cls.serialized_camm_type.value,
                "data": [data.x, data.y, data.z],
            }
        )


class MagnetometerSampleEntry(CAMMSampleEntry):
    serialized_camm_type: CAMMType = CAMMType.MAGNETIC_FIELD

    telemetry_cls_type = telemetry.MagnetometerData

    construct: C.Struct = _Float[3]  # type: ignore

    @classmethod
    def deserialize(cls, sample: Sample, data: T.Any) -> telemetry.MagnetometerData:
        return telemetry.MagnetometerData(
            time=sample.exact_time,
            x=data[0],
            y=data[1],
            z=data[2],
        )

    @classmethod
    def serialize(cls, data: telemetry.MagnetometerData) -> bytes:
        cls.serializable(data)

        return CAMMSampleData.build(
            {
                "type": cls.serialized_camm_type.value,
                "data": [data.x, data.y, data.z],
            }
        )


SAMPLE_ENTRY_CLS_BY_CAMM_TYPE = {
    sample_entry_cls.serialized_camm_type: sample_entry_cls
    for sample_entry_cls in CAMMSampleEntry.__subclasses__()
    if sample_entry_cls not in [GoProGPSSampleEntry]
}
assert len(SAMPLE_ENTRY_CLS_BY_CAMM_TYPE) == 5, SAMPLE_ENTRY_CLS_BY_CAMM_TYPE.keys()


_SWITCH: dict[int, C.Struct] = {
    # Angle_axis
    CAMMType.ANGLE_AXIS.value: _Float[3],  # type: ignore
    # Exposure time
    CAMMType.EXPOSURE_TIME.value: C.Struct(
        "pixel_exposure_time" / C.Int32sl,  # type: ignore
        "rolling_shutter_skew_time" / C.Int32sl,  # type: ignore
    ),
    # Position
    CAMMType.POSITION.value: _Float[3],  # type: ignore
    # Serializable types
    **{t.value: cls.construct for t, cls in SAMPLE_ENTRY_CLS_BY_CAMM_TYPE.items()},
}


def _construct_with_selected_camm_types(
    selected_camm_types: T.Container[CAMMType] | None = None,
) -> C.Struct:
    if selected_camm_types is None:
        switch = _SWITCH
    else:
        switch = {
            k: v for k, v in _SWITCH.items() if CAMMType(k) in selected_camm_types
        }

    return C.Struct(
        C.Padding(2),
        "type" / C.Int16ul,
        "data" / C.Switch(C.this.type, switch),
    )


CAMMSampleData = _construct_with_selected_camm_types()


def _parse_telemetry_from_sample(
    fp: T.BinaryIO,
    sample: Sample,
    construct: C.Struct | None = None,
) -> TelemetryMeasurement | None:
    if construct is None:
        construct = CAMMSampleData

    fp.seek(sample.raw_sample.offset, io.SEEK_SET)
    data = fp.read(sample.raw_sample.size)

    box = construct.parse(data)

    # boxdata=None when the construct is unable to parse the data
    # (CAMM type not in the switch)
    if box.data is None:
        return None

    camm_type = CAMMType(box.type)  # type: ignore
    SampleKlass = SAMPLE_ENTRY_CLS_BY_CAMM_TYPE.get(camm_type)
    if SampleKlass is None:
        return None

    return SampleKlass.deserialize(sample, box.data)


def _filter_telemetry_by_elst_segments(
    measurements: T.Iterable[TelemetryMeasurement],
    elst: T.Sequence[tuple[float, float]],
) -> T.Generator[TelemetryMeasurement, None, None]:
    empty_elst = [entry for entry in elst if entry[0] == -1]
    if empty_elst:
        offset = empty_elst[-1][1]
    else:
        offset = 0

    elst = [entry for entry in elst if entry[0] != -1]

    if not elst:
        for m in measurements:
            yield dataclasses.replace(m, time=m.time + offset)
        return

    elst.sort(key=lambda entry: entry[0])
    elst_idx = 0
    for m in measurements:
        if len(elst) <= elst_idx:
            break
        media_time, duration = elst[elst_idx]
        if m.time < media_time:
            pass
        elif m.time <= media_time + duration:
            yield dataclasses.replace(m, time=m.time + offset)
        else:
            elst_idx += 1


def elst_entry_to_seconds(
    entry: dict, movie_timescale: int, media_timescale: int
) -> tuple[float, float]:
    assert movie_timescale > 0, "expected positive movie_timescale"
    assert media_timescale > 0, "expected positive media_timescale"
    media_time, duration = entry["media_time"], entry["segment_duration"]
    if media_time != -1:
        media_time = media_time / media_timescale
    duration = duration / movie_timescale
    return (media_time, duration)


def _is_camm_description(description: dict) -> bool:
    return description["format"] == b"camm"


def _contains_camm_description(track: TrackBoxParser) -> bool:
    descriptions = track.extract_sample_descriptions()
    return any(_is_camm_description(d) for d in descriptions)


def _filter_telemetry_by_track_elst(
    moov: MovieBoxParser,
    track: TrackBoxParser,
    measurements: T.Iterable[TelemetryMeasurement],
) -> list[TelemetryMeasurement]:
    elst_boxdata = track.extract_elst_boxdata()

    if elst_boxdata is not None:
        elst_entries = elst_boxdata["entries"]
        if elst_entries:
            # media_timescale
            mdhd_boxdata = track.extract_mdhd_boxdata()
            media_timescale = mdhd_boxdata["timescale"]

            # movie_timescale
            mvhd_boxdata = moov.extract_mvhd_boxdata()
            movie_timescale = mvhd_boxdata["timescale"]

            segments = [
                elst_entry_to_seconds(
                    entry,
                    movie_timescale=movie_timescale,
                    media_timescale=media_timescale,
                )
                for entry in elst_entries
            ]

            return list(_filter_telemetry_by_elst_segments(measurements, segments))

    return list(measurements)


_MakeOrModel = C.Struct(
    "size" / C.Int16ub,
    C.Padding(2),
    "data" / C.FixedSized(C.this.size, C.GreedyBytes),
)


def _decode_quietly(data: bytes, type: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        LOG.warning("Failed to decode %s: %s", type, data[:512])
        return ""


def _parse_quietly(data: bytes, type: bytes) -> bytes:
    try:
        parsed = _MakeOrModel.parse(data)
    except C.ConstructError:
        LOG.warning("Failed to parse %s: %s", type, data[:512])
        return b""

    if parsed is None:
        return b""

    return parsed["data"]


def _extract_camera_make_and_model_from_utda_boxdata(
    utda_boxdata: dict,
) -> tuple[str, str]:
    make: str = ""
    model: str = ""

    for box in utda_boxdata:
        # Insta360 Titan
        if box.type == b"\xa9mak":
            if not make:
                make_data = _parse_quietly(box.data, box.type)
                make_data = make_data.rstrip(b"\x00")
                make = _decode_quietly(make_data, box.type)

        # Insta360 Titan
        elif box.type == b"\xa9mod":
            if not model:
                model_data = _parse_quietly(box.data, box.type)
                model_data = model_data.rstrip(b"\x00")
                model = _decode_quietly(model_data, box.type)

        # RICHO THETA V
        elif box.type in [b"@mak", b"manu"]:
            if not make:
                make = _decode_quietly(box.data, box.type)

        # RICHO THETA V
        elif box.type in [b"@mod", b"modl"]:
            if not model:
                model = _decode_quietly(box.data, box.type)

        # quit when both found
        if make and model:
            break

    if make:
        make = make.strip()

    if model:
        model = model.strip()

    return make, model
