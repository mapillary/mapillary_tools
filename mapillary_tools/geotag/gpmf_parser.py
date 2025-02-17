import dataclasses
import datetime
import io
import itertools
import pathlib
import typing as T

import construct as C

from .. import telemetry
from ..mp4.mp4_sample_parser import MovieBoxParser, Sample, TrackBoxParser
from ..telemetry import GPSFix, GPSPoint

"""
Parsing GPS from GPMF data format stored in GoPros. See the GPMF spec: https://github.com/gopro/gpmf-parser

A GPS GPMF sample has the following structure:
- DEVC: Each connected device starts with DEVC.
    - DVID: Auto generated unique-ID for managing a large number of connect devices
    - STRM: Metadata streams are each nested with STRM
         - GPS5: latitude, longitude, altitude (WGS 84), 2D ground speed, and 3D speed
         - GPS9: lat, long, alt, 2D speed, 3D speed, days since 2000, secs since midnight (ms precision), DOP, fix (0, 2D or 3D)
         - GPSA: not documented in the spec
         - GPSF: Within the GPS stream: 0 - no lock, 2 or 3 - 2D or 3D Lock.
         - GPSP: GPS Precision - Dilution of Precision (DOP x100). Under 500 is good.
         - GPSU: UTC time and data from GPS. The time is read from from another clock so it is not in use.
         - SCAL: Scaling factor (divisor) for GPS5 and GPS9

NOTE:
- There might be multiple DEVC streams.
- Only GPS5, GPS9, and SCAL are required. The others are optional.
- GPSU is not in use. We use the video clock to make sure frames and GPS are in sync.
- We should skip samples with GPSF==0 or GPSP > 500
"""


class KLVDict(T.TypedDict):
    key: bytes
    type: bytes
    structure_size: int
    repeat: int
    data: T.List[T.Any]


GPMFSampleData: C.GreedyRange


# type char: (construct type, size in bytes)
_type_mapping = {
    # b	single byte signed integer	int8_t	-128 to 127
    b"b": (C.Int8sb, 1),
    # B	single byte unsigned integer	uint8_t	0 to 255
    b"B": (C.Int8ub, 1),
    # c	single byte 'c' style ASCII character string	char	Optionally NULL terminated - size/repeat sets the length
    b"c": (C.Bytes(1), 1),
    # d	64-bit double precision (IEEE 754)	double
    b"d": (C.Float64b, 8),
    # f	32-bit float (IEEE 754)	float
    b"f": (C.Float32b, 4),
    # F	32-bit four character key -- FourCC	char fourcc[4]
    b"F": (C.Bytes(4), 4),
    # G	128-bit ID (like UUID)	uint8_t guid[16]
    b"G": (C.Bytes(16), 16),
    # j	64-bit signed long number	int64_t
    b"j": (C.Int64sb, 8),
    # J	64-bit unsigned long number	uint64_t
    b"J": (C.Int64ub, 8),
    # l	32-bit signed integer	int32_t
    b"l": (C.Int32sb, 4),
    # L	32-bit unsigned integer	uint32_t
    b"L": (C.Int32ub, 4),
    # q	32-bit Q Number Q15.16	uint32_t	16-bit integer (A) with 16-bit fixed point (B) for A.B value (range -32768.0 to 32767.99998)
    b"q": (C.Int32ub, 4),
    # Q	64-bit Q Number Q31.32	uint64_t	32-bit integer (A) with 32-bit fixed point (B) for A.B value.
    b"Q": (C.Int64ub, 8),
    # s	16-bit signed integer	int16_t	-32768 to 32768
    b"s": (C.Int16sb, 2),
    # S	16-bit unsigned integer	uint16_t	0 to 65536
    b"S": (C.Int16ub, 2),
    # U	UTC Date and Time string	char utcdate[16]	Date + UTC Time format yymmddhhmmss.sss - (years 20xx covered)
    b"U": (C.Bytes(16), 16),
}


_klv_data_switch = C.Switch(
    C.this.type,
    {
        **{
            type_char: C.Array(
                C.this.repeat, C.Array(C.this.structure_size // size, ctype)
            )
            for type_char, (ctype, size) in _type_mapping.items()
        },
        # c	single byte 'c' style ASCII character string	char	Optionally NULL terminated - size/repeat sets the length
        b"c": C.Array(
            C.this.repeat, C.Bytes(C.this.structure_size)
        ),  # overwrite the one in _type_mapping to make sure it returns bytes instead of a list of bytes
        # null      Nested metadata uint32_t        The data within is GPMF structured KLV data
        b"\x00": C.FixedSized(
            (C.this.repeat * C.this.structure_size),
            C.LazyBound(lambda: GPMFSampleData),
        ),
    },
    C.Array(C.this.repeat, C.Bytes(C.this.structure_size)),
)


KLV = C.Struct(
    # FourCC
    "key" / C.Bytes(4),
    # using a ASCII character to describe the data stored. A character 'f' would describe float data, 'd' for double precision, etc.
    # All types are reserved, and are not end user definable.
    "type" / C.Bytes(1),
    # 8-bits is used for a sample size, each sample is limited to 255 bytes or less.
    "structure_size" / C.Int8ub,
    # 16-bits is used to indicate the number of samples in a GPMF payload,
    # this is the Repeat field. Struct Size and the Repeat allow for up to
    # 16.7MB of data in a single KLV GPMF payload.
    "repeat" / C.Int16ub,
    "data" / _klv_data_switch,
    C.IfThenElse(
        (C.this.repeat * C.this.structure_size) % 4 == 0,
        C.Padding(0),
        C.Padding(4 - (C.this.repeat * C.this.structure_size) % 4),
    ),
)


GPMFSampleData = C.GreedyRange(KLV)


@dataclasses.dataclass
class TelemetryData:
    gps: T.List[GPSPoint]
    accl: T.List[telemetry.AccelerationData]
    gyro: T.List[telemetry.GyroscopeData]
    magn: T.List[telemetry.MagnetometerData]


def _gps5_timestamp_to_epoch_time(dtstr: str):
    # yymmddhhmmss.sss
    dt = datetime.datetime.strptime(dtstr, "%y%m%d%H%M%S.%f").replace(
        tzinfo=datetime.timezone.utc
    )
    return dt.timestamp()


# A GPS5 stream example:
#     key = b'STRM' type = b'\x00' structure_size =  1 repeat = 400
#     data = ListContainer:
#         Container:
#             key = b'STMP' type = b'J' structure_size =  8 repeat = 1
#             data = [[60315]]
#         Container:
#             key = b'TSMP' type = b'L' structure_size =  4 repeat = 1
#             data = [[10]]
#         Container:
#             key = b'STNM' type = b'c' structure_size = 43 repeat = 1
#             data = [b'GPS (Lat., Long., Alt., 2D speed, 3D speed)']
#         Container:
#             key = b'GPSF' type = b'L' structure_size =  4 repeat = 1
#             data = [[3]]
#         Container:
#             key = b'GPSU' type = b'U' structure_size = 16 repeat = 1
#             data = [[b'220731002523.200']]
#         Container:
#             key = b'GPSP' type = b'S' structure_size =  2 repeat = 1
#             data = [[342]]
#         Container:
#             key = b'UNIT' type = b'c' structure_size =  3 repeat = 5
#             data = [b'deg', b'deg', b'm\x00\x00', b'm/s', b'm/s']
#         Container:
#             key = b'SCAL' type = b'l' structure_size =  4 repeat = 5
#             data = [[10000000], [10000000], [1000], [1000], [100]]
#         Container:
#             key = b'GPSA' type = b'F' structure_size =  4 repeat = 1
#             data = [[b'MSLV']]
#         Container:
#             key = b'GPS5' type = b'l' structure_size = 20 repeat = 2
#             data = [
#                 [378081666, -1224280064, 9621, 1492, 138],
#                 [378081662, -1224280049, 9592, 1476, 150],
#             ]
def gps5_from_stream(
    stream: T.Sequence[KLVDict],
) -> T.Generator[GPSPoint, None, None]:
    indexed: T.Dict[bytes, T.List[T.List[T.Any]]] = {
        klv["key"]: klv["data"] for klv in stream
    }

    gps5 = indexed.get(b"GPS5")
    if gps5 is None:
        return

    scal = indexed.get(b"SCAL")
    if scal is None:
        return
    scal_values = [s[0] for s in scal]
    if any(s == 0 for s in scal_values):
        return

    gpsf = indexed.get(b"GPSF")
    if gpsf is not None:
        gpsf_value = GPSFix(gpsf[0][0])
    else:
        gpsf_value = None

    gpsu = indexed.get(b"GPSU")
    if gpsu is not None:
        try:
            yymmdd = gpsu[0][0].decode("utf-8")
            epoch_time = _gps5_timestamp_to_epoch_time(yymmdd)
        except Exception:
            epoch_time = None
    else:
        epoch_time = None

    gpsp = indexed.get(b"GPSP")
    if gpsp is not None:
        gpsp_value = gpsp[0][0]
    else:
        gpsp_value = None

    for point in gps5:
        lat, lon, alt, ground_speed, _speed_3d = [
            v / s for v, s in zip(point, scal_values)
        ]
        yield GPSPoint(
            # will figure out the actual timestamp later
            time=0,
            lat=lat,
            lon=lon,
            alt=alt,
            epoch_time=epoch_time,
            fix=gpsf_value,
            precision=gpsp_value,
            ground_speed=ground_speed,
            angle=None,
        )


_EPOCH_TIME_IN_2000 = datetime.datetime(
    2000, 1, 1, tzinfo=datetime.timezone.utc
).timestamp()


def _gps9_timestamp_to_epoch_time(
    days_since_2000: int, secs_since_midnight: float
) -> float:
    epoch_time = _EPOCH_TIME_IN_2000 + days_since_2000 * 24 * 60 * 60
    epoch_time += secs_since_midnight
    return epoch_time


def _get_gps_type(input) -> bytes:
    final = b""
    for val in input or []:
        if isinstance(val, bytes):
            final += val
        elif isinstance(val, list):
            final += _get_gps_type(val)
        else:
            raise ValueError(f"Unexpected type {type(val)} in {input}")

    return final


def gps9_from_stream(
    stream: T.Sequence[KLVDict],
) -> T.Generator[GPSPoint, None, None]:
    NUM_VALUES = 9

    indexed: T.Dict[bytes, T.List[T.List[T.Any]]] = {
        klv["key"]: klv["data"] for klv in stream
    }

    gps9 = indexed.get(b"GPS9")
    if gps9 is None:
        return

    scal = indexed.get(b"SCAL")
    if scal is None:
        return
    scal_values = [s[0] for s in scal]
    if any(s == 0 for s in scal_values):
        return

    gps_value_types = _get_gps_type(indexed.get(b"TYPE"))
    if not gps_value_types:
        return

    if len(gps_value_types) != NUM_VALUES:
        raise ValueError(
            f"Error parsing the complex type {gps_value_types!r}: expect {NUM_VALUES} types but got {len(gps_value_types)}"
        )

    try:
        sample_parser = C.Sequence(
            *[
                # Changed in version 3.11: Added default argument values for length and byteorder
                _type_mapping[t.to_bytes(length=1, byteorder="big")][0]
                for t in gps_value_types
            ]
        )
    except Exception as ex:
        raise ValueError(f"Error parsing the complex type {gps_value_types!r}: {ex}")

    for sample_data_bytes in gps9:
        sample_data = sample_parser.parse(sample_data_bytes)

        (
            lat,
            lon,
            alt,
            speed_2d,
            _speed_3d,
            days_since_2000,
            secs_since_midnight,
            dop,
            gps_fix,
        ) = [v / s for v, s in zip(sample_data, scal_values)]

        epoch_time = _gps9_timestamp_to_epoch_time(days_since_2000, secs_since_midnight)

        yield GPSPoint(
            # will figure out the actual timestamp later
            time=0,
            lat=lat,
            lon=lon,
            alt=alt,
            epoch_time=epoch_time,
            fix=GPSFix(gps_fix),
            precision=dop * 100,
            ground_speed=speed_2d,
            angle=None,
        )


def _find_first_device_id(stream: T.Sequence[KLVDict]) -> int:
    device_id = None

    for klv in stream:
        if klv["key"] == b"DVID":
            device_id = klv["data"][0][0]
            break

    if device_id is None:
        # The default value is for grouping points for those streams without DVID found,
        # make sure it is larger than DVID's type 32-bit unsigned integer (uint32_t)
        device_id = 2**32

    return device_id


def _find_first_gps_stream(stream: T.Sequence[KLVDict]) -> T.List[GPSPoint]:
    sample_points: T.List[GPSPoint] = []

    for klv in stream:
        if klv["key"] == b"STRM":
            sample_points = list(gps9_from_stream(klv["data"]))
            if sample_points:
                break

            sample_points = list(gps5_from_stream(klv["data"]))
            if sample_points:
                break

    return sample_points


# a sensor matrix with only [1,0,0, 0,-1,0, 0,0,1], is just a form of non-calibrated sensor orientation
def _is_matrix_calibration(matrix: T.Sequence[float]) -> bool:
    for v in matrix:
        if v not in [0, -1, 1]:
            return True
    return False


def _build_matrix(
    orin: T.Union[bytes, T.Sequence[int]], orio: T.Union[bytes, T.Sequence[int]]
) -> T.Sequence[float]:
    matrix = []

    # list(b'aA') == [97, 65]
    lower_a, upper_A = 97, 65

    for out_char in orin:
        for in_char in orio:
            if in_char == out_char:
                matrix.append(1.0)
            elif (in_char - lower_a) == (out_char - upper_A):
                matrix.append(-1.0)
            elif (in_char - upper_A) == (out_char - lower_a):
                matrix.append(-1.0)
            else:
                matrix.append(0.0)

    return matrix


def _apply_matrix(
    matrix: T.Sequence[float], values: T.Sequence[float]
) -> T.Generator[float, None, None]:
    size = len(values)
    assert len(matrix) == size * size, (
        f"expecting a square matrix of size {size} x {size} but got {len(matrix)}"
    )

    for y in range(size):
        row_start = y * size
        yield sum(matrix[row_start + x] * values[x] for x in range(size))


def _flatten(nested: T.Sequence[T.Sequence[float]]) -> T.List[float]:
    output: T.List[float] = []
    for row in nested:
        output.extend(row)
    return output


def _get_matrix(klv: T.Dict[bytes, KLVDict]) -> T.Optional[T.Sequence[float]]:
    mtrx = klv.get(b"MTRX")
    if mtrx is not None:
        matrix: T.Sequence[float] = _flatten(mtrx["data"])
        if _is_matrix_calibration(matrix):
            return matrix

    orin = klv.get(b"ORIN")
    orio = klv.get(b"ORIO")

    if orin is not None and orio is not None:
        matrix = _build_matrix(b"".join(orin["data"]), b"".join(orio["data"]))
        return matrix

    return None


def _scale_and_calibrate(
    stream: T.Sequence[KLVDict], key: bytes
) -> T.Generator[T.Sequence[float], None, None]:
    indexed: T.Dict[bytes, KLVDict] = {klv["key"]: klv for klv in stream}

    klv = indexed.get(key)
    if klv is None:
        return

    scal_klv = indexed.get(b"SCAL")

    if scal_klv is not None:
        # replace 0s with 1s to avoid division by zero
        scals = [s or 1 for s in _flatten(scal_klv["data"])]

    if not scals:
        scals = [1]

    if len(scals) == 1:
        # infinite repeat
        scales: T.Iterable[float] = itertools.repeat(scals[0])
    else:
        scales = scals

    matrix = _get_matrix(indexed)

    for values in klv["data"]:
        if matrix is None:
            yield tuple(v / s for v, s in zip(values, scales))
        else:
            yield tuple(v / s for v, s in zip(_apply_matrix(matrix, values), scales))


def _find_first_telemetry_stream(stream: T.Sequence[KLVDict], key: bytes):
    values: T.List[T.Sequence[float]] = []

    for klv in stream:
        if klv["key"] == b"STRM":
            values = list(_scale_and_calibrate(klv["data"], key))
            if values:
                break

    return values


def _extract_dvnm_from_samples(
    fp: T.BinaryIO, samples: T.Iterable[Sample]
) -> T.Dict[int, bytes]:
    dvnm_by_dvid: T.Dict[int, bytes] = {}

    for sample in samples:
        fp.seek(sample.raw_sample.offset, io.SEEK_SET)
        data = fp.read(sample.raw_sample.size)
        gpmf_sample_data = T.cast(T.Dict, GPMFSampleData.parse(data))

        # iterate devices
        devices = (klv for klv in gpmf_sample_data if klv["key"] == b"DEVC")
        for device in devices:
            device_id = _find_first_device_id(device["data"])
            for klv in device["data"]:
                if klv["key"] == b"DVNM" and klv["data"]:
                    # klv["data"] could be [b"H", b"e", b"r", b"o", b"8", b" ", b"B", b"l", b"a", b"c", b"k"]
                    # or [b"Hero8 Black"]
                    dvnm_by_dvid[device_id] = b"".join(klv["data"])

    return dvnm_by_dvid


def _backfill_gps_timestamps(gps_points: T.Iterable[GPSPoint]) -> None:
    it = iter(gps_points)

    # find the first point with epoch time
    last = None
    for point in it:
        if point.epoch_time is not None:
            last = point
            break

    # if no point with epoch time found, return
    if last is None:
        return

    # backfill points without epoch time
    for point in it:
        assert last.epoch_time is not None
        if point.epoch_time is None:
            point.epoch_time = last.epoch_time + (point.time - last.time)
        last = point


def _extract_points_from_samples(
    fp: T.BinaryIO, samples: T.Iterable[Sample]
) -> TelemetryData:
    # To keep GPS points from different devices separated
    points_by_dvid: T.Dict[int, T.List[GPSPoint]] = {}
    accls_by_dvid: T.Dict[int, T.List[telemetry.AccelerationData]] = {}
    gyros_by_dvid: T.Dict[int, T.List[telemetry.GyroscopeData]] = {}
    magns_by_dvid: T.Dict[int, T.List[telemetry.MagnetometerData]] = {}

    for sample in samples:
        fp.seek(sample.raw_sample.offset, io.SEEK_SET)
        data = fp.read(sample.raw_sample.size)
        gpmf_sample_data = T.cast(T.Dict, GPMFSampleData.parse(data))

        # iterate devices
        devices = (klv for klv in gpmf_sample_data if klv["key"] == b"DEVC")
        for device in devices:
            device_id = _find_first_device_id(device["data"])

            sample_points = _find_first_gps_stream(device["data"])
            if sample_points:
                # interpolate timestamps in between
                avg_timedelta = sample.exact_timedelta / len(sample_points)
                for idx, point in enumerate(sample_points):
                    point.time = sample.exact_time + avg_timedelta * idx

                device_points = points_by_dvid.setdefault(device_id, [])
                device_points.extend(sample_points)

            sample_accls = _find_first_telemetry_stream(device["data"], b"ACCL")
            if sample_accls:
                # interpolate timestamps in between
                avg_delta = sample.exact_timedelta / len(sample_accls)
                accls_by_dvid.setdefault(device_id, []).extend(
                    telemetry.AccelerationData(
                        time=sample.exact_time + avg_delta * idx,
                        x=x,
                        y=y,
                        z=z,
                    )
                    for idx, (z, x, y, *_) in enumerate(sample_accls)
                )

            sample_gyros = _find_first_telemetry_stream(device["data"], b"GYRO")
            if sample_gyros:
                # interpolate timestamps in between
                avg_delta = sample.exact_timedelta / len(sample_gyros)
                gyros_by_dvid.setdefault(device_id, []).extend(
                    telemetry.GyroscopeData(
                        time=sample.exact_time + avg_delta * idx,
                        x=x,
                        y=y,
                        z=z,
                    )
                    for idx, (z, x, y, *_) in enumerate(sample_gyros)
                )

            sample_magns = _find_first_telemetry_stream(device["data"], b"MAGN")
            if sample_magns:
                # interpolate timestamps in between
                avg_delta = sample.exact_timedelta / len(sample_magns)
                magns_by_dvid.setdefault(device_id, []).extend(
                    telemetry.MagnetometerData(
                        time=sample.exact_time + avg_delta * idx,
                        x=x,
                        y=y,
                        z=z,
                    )
                    for idx, (z, x, y, *_) in enumerate(sample_magns)
                )

    gps_points = list(points_by_dvid.values())[0] if points_by_dvid else []

    # backfill forward from the first point with epoch time
    _backfill_gps_timestamps(gps_points)

    # backfill backward from the first point with epoch time in reversed order
    _backfill_gps_timestamps(reversed(gps_points))

    return TelemetryData(
        gps=gps_points,
        accl=list(accls_by_dvid.values())[0] if accls_by_dvid else [],
        gyro=list(gyros_by_dvid.values())[0] if gyros_by_dvid else [],
        magn=list(magns_by_dvid.values())[0] if magns_by_dvid else [],
    )


def _is_gpmd_description(description: T.Dict) -> bool:
    return description["format"] == b"gpmd"


def _contains_gpmd_description(track: TrackBoxParser) -> bool:
    descriptions = track.extract_sample_descriptions()
    return any(_is_gpmd_description(d) for d in descriptions)


def _filter_gpmd_samples(track: TrackBoxParser) -> T.Generator[Sample, None, None]:
    for sample in track.extract_samples():
        if _is_gpmd_description(sample.description):
            yield sample


def extract_points(fp: T.BinaryIO) -> T.List[GPSPoint]:
    """
    Return a list of points (could be empty) if it is a valid GoPro video,
    otherwise None
    """
    moov = MovieBoxParser.parse_stream(fp)
    for track in moov.extract_tracks():
        if _contains_gpmd_description(track):
            gpmd_samples = _filter_gpmd_samples(track)
            telemetry = _extract_points_from_samples(fp, gpmd_samples)
            # return the firstly found non-empty points
            if telemetry.gps:
                return telemetry.gps

    # points could be empty list or None here
    return []


def extract_telemetry_data(fp: T.BinaryIO) -> T.Optional[TelemetryData]:
    """
    Return the telemetry data from the first found GoPro GPMF track
    """
    moov = MovieBoxParser.parse_stream(fp)

    for track in moov.extract_tracks():
        if _contains_gpmd_description(track):
            gpmd_samples = _filter_gpmd_samples(track)
            telemetry = _extract_points_from_samples(fp, gpmd_samples)
            # return the firstly found non-empty points
            if telemetry.gps:
                return telemetry

    # points could be empty list or None here
    return None


def extract_all_device_names(fp: T.BinaryIO) -> T.Dict[int, bytes]:
    moov = MovieBoxParser.parse_stream(fp)
    for track in moov.extract_tracks():
        if _contains_gpmd_description(track):
            gpmd_samples = _filter_gpmd_samples(track)
            device_names = _extract_dvnm_from_samples(fp, gpmd_samples)
            if device_names:
                return device_names
    return {}


def extract_camera_model(fp: T.BinaryIO) -> str:
    device_names = extract_all_device_names(fp)

    if not device_names:
        return ""

    unicode_names: T.List[str] = []
    for name in device_names.values():
        try:
            unicode_names.append(name.decode("utf-8"))
        except UnicodeDecodeError:
            pass

    if not unicode_names:
        return ""

    unicode_names.sort()

    # device containing "hero" higher priority
    for unicode_name in unicode_names:
        if "hero" in unicode_name.lower():
            return unicode_name.strip()

    # device containing "gopro" higher priority
    for unicode_name in unicode_names:
        if "gopro" in unicode_name.lower():
            return unicode_name.strip()

    return unicode_names[0].strip()


def parse_gpx(path: pathlib.Path) -> T.List[GPSPoint]:
    with path.open("rb") as fp:
        points = extract_points(fp)
    if points is None:
        return []
    return points
