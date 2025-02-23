# pyre-ignore-all-errors[5, 11, 16, 21, 24, 58]

import dataclasses
import io
import logging
import pathlib
import typing as T
from enum import Enum

import construct as C

from .. import geo, telemetry
from ..mp4 import simple_mp4_parser as sparser
from ..mp4.mp4_sample_parser import MovieBoxParser, Sample, TrackBoxParser


LOG = logging.getLogger(__name__)


TelemetryMeasurement = T.Union[
    geo.Point,
    telemetry.AccelerationData,
    telemetry.GyroscopeData,
    telemetry.MagnetometerData,
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


def _parse_telemetry_from_sample(
    fp: T.BinaryIO, sample: Sample
) -> T.Optional[TelemetryMeasurement]:
    fp.seek(sample.raw_sample.offset, io.SEEK_SET)
    data = fp.read(sample.raw_sample.size)
    box = CAMMSampleData.parse(data)
    if box.type == CAMMType.MIN_GPS.value:
        return geo.Point(
            time=sample.exact_time,
            lat=box.data[0],
            lon=box.data[1],
            alt=box.data[2],
            angle=None,
        )
    elif box.type == CAMMType.GPS.value:
        # Not using box.data.time_gps_epoch as the point timestamp
        # because it is from another clock
        return geo.Point(
            time=sample.exact_time,
            lat=box.data.latitude,
            lon=box.data.longitude,
            alt=box.data.altitude,
            angle=None,
        )
    elif box.type == CAMMType.ACCELERATION.value:
        return telemetry.AccelerationData(
            time=sample.exact_time,
            x=box.data[0],
            y=box.data[1],
            z=box.data[2],
        )
    elif box.type == CAMMType.GYRO.value:
        return telemetry.GyroscopeData(
            time=sample.exact_time,
            x=box.data[0],
            y=box.data[1],
            z=box.data[2],
        )
    elif box.type == CAMMType.MAGNETIC_FIELD.value:
        return telemetry.MagnetometerData(
            time=sample.exact_time,
            x=box.data[0],
            y=box.data[1],
            z=box.data[2],
        )
    return None


def _filter_telemetry_by_elst_segments(
    measurements: T.Iterable[TelemetryMeasurement],
    elst: T.Sequence[T.Tuple[float, float]],
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
    entry: T.Dict, movie_timescale: int, media_timescale: int
) -> T.Tuple[float, float]:
    assert movie_timescale > 0, "expected positive movie_timescale"
    assert media_timescale > 0, "expected positive media_timescale"
    media_time, duration = entry["media_time"], entry["segment_duration"]
    if media_time != -1:
        media_time = media_time / media_timescale
    duration = duration / movie_timescale
    return (media_time, duration)


def _is_camm_description(description: T.Dict) -> bool:
    return description["format"] == b"camm"


def _contains_camm_description(track: TrackBoxParser) -> bool:
    descriptions = track.extract_sample_descriptions()
    return any(_is_camm_description(d) for d in descriptions)


def _filter_telemetry_by_track_elst(
    moov: MovieBoxParser,
    track: TrackBoxParser,
    measurements: T.Iterable[TelemetryMeasurement],
) -> T.List[TelemetryMeasurement]:
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


def extract_points(fp: T.BinaryIO) -> T.Optional[T.List[geo.Point]]:
    """
    Return a list of points (could be empty) if it is a valid CAMM video,
    otherwise None
    """

    moov = MovieBoxParser.parse_stream(fp)

    for track in moov.extract_tracks():
        if _contains_camm_description(track):
            maybe_measurements = (
                _parse_telemetry_from_sample(fp, sample)
                for sample in track.extract_samples()
                if _is_camm_description(sample.description)
            )
            points = [m for m in maybe_measurements if isinstance(m, geo.Point)]

            return T.cast(
                T.List[geo.Point], _filter_telemetry_by_track_elst(moov, track, points)
            )

    return None


def extract_telemetry_data(fp: T.BinaryIO) -> T.Optional[T.List[TelemetryMeasurement]]:
    moov = MovieBoxParser.parse_stream(fp)

    for track in moov.extract_tracks():
        if _contains_camm_description(track):
            maybe_measurements = (
                _parse_telemetry_from_sample(fp, sample)
                for sample in track.extract_samples()
                if _is_camm_description(sample.description)
            )
            measurements = [m for m in maybe_measurements if m is not None]

            measurements = _filter_telemetry_by_track_elst(moov, track, measurements)

            return measurements

    return None


def parse_gpx(path: pathlib.Path) -> T.List[geo.Point]:
    with path.open("rb") as fp:
        points = extract_points(fp)
    if points is None:
        return []
    return points


MakeOrModel = C.Struct(
    "size" / C.Int16ub,
    C.Padding(2),
    "data" / C.FixedSized(C.this.size, C.GreedyBytes),
)


def _decode_quietly(data: bytes, h: sparser.Header) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        LOG.warning("Failed to decode %s: %s", h, data[:512])
        return ""


def _parse_quietly(data: bytes, h: sparser.Header) -> bytes:
    try:
        parsed = MakeOrModel.parse(data)
    except C.ConstructError:
        LOG.warning("Failed to parse %s: %s", h, data[:512])
        return b""
    return parsed["data"]


def extract_camera_make_and_model(fp: T.BinaryIO) -> T.Tuple[str, str]:
    header_and_stream = sparser.parse_path(
        fp,
        [
            b"moov",
            b"udta",
            [
                # Insta360 Titan
                b"\xa9mak",
                b"\xa9mod",
                # RICHO THETA V
                b"@mod",
                b"@mak",
                # RICHO THETA V
                b"manu",
                b"modl",
            ],
        ],
    )

    make: T.Optional[str] = None
    model: T.Optional[str] = None

    try:
        for h, s in header_and_stream:
            data = s.read(h.maxsize)
            if h.type == b"\xa9mak":
                make_data = _parse_quietly(data, h)
                make_data = make_data.rstrip(b"\x00")
                make = _decode_quietly(make_data, h)
            elif h.type == b"\xa9mod":
                model_data = _parse_quietly(data, h)
                model_data = model_data.rstrip(b"\x00")
                model = _decode_quietly(model_data, h)
            elif h.type in [b"@mak", b"manu"]:
                make = _decode_quietly(data, h)
            elif h.type in [b"@mod", b"modl"]:
                model = _decode_quietly(data, h)
            # quit when both found
            if make and model:
                break
    except sparser.ParsingError:
        pass

    if make:
        make = make.strip()
    if model:
        model = model.strip()
    return make or "", model or ""
