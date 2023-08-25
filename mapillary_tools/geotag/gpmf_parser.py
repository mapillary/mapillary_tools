import io
import pathlib
import typing as T

import construct as C

from .. import geo
from . import mp4_sample_parser as sample_parser, simple_mp4_parser as parser

"""
Parsing GPS from GPMF data format stored in GoPros. See the GPMF spec: https://github.com/gopro/gpmf-parser

A GPS GPMF sample has the following structure:
- DEVC: Each connected device starts with DEVC.
    - DVID: Auto generated unique-ID for managing a large number of connect devices
    - STRM: Metadata streams are each nested with STRM
         - GPS5: latitude, longitude, altitude (WGS 84), 2D ground speed, and 3D speed
         - GPSA: not documented in the spec
         - GPSF: Within the GPS stream: 0 - no lock, 2 or 3 - 2D or 3D Lock.
         - GPSP: GPS Precision - Dilution of Precision (DOP x100). Under 500 is good.
         - GPSU: UTC time and data from GPS. The time is read from from another clock so it is not in use.
         - SCAL: Scaling factor (divisor) for GPS5

NOTE:
- There might be multiple DEVC streams.
- Only GPS5 and SCAL are required. The others are optional.
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
    "data"
    / C.Switch(
        C.this.type,
        {
            # b	single byte signed integer	int8_t	-128 to 127
            b"b": C.Array(C.this.repeat, C.Array(C.this.structure_size, C.Int8sb)),
            # B	single byte unsigned integer	uint8_t	0 to 255
            b"B": C.Array(C.this.repeat, C.Array(C.this.structure_size, C.Int8ub)),
            # c	single byte 'c' style ASCII character string	char	Optionally NULL terminated - size/repeat sets the length
            b"c": C.Array(C.this.repeat, C.Bytes(C.this.structure_size)),
            # d	64-bit double precision (IEEE 754)	double
            b"d": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 8, C.Float64b)
            ),
            # f	32-bit float (IEEE 754)	float
            b"f": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 4, C.Float32b)
            ),
            # F	32-bit four character key -- FourCC	char fourcc[4]
            b"F": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 4, C.Bytes(4))
            ),
            # G	128-bit ID (like UUID)	uint8_t guid[16]
            b"G": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 16, C.Bytes(16))
            ),
            # j	64-bit signed unsigned number	int64_t
            b"j": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 8, C.Int64sb)
            ),
            # J	64-bit unsigned unsigned number	uint64_t
            b"J": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 8, C.Int64ub)
            ),
            # l	32-bit signed integer	int32_t
            b"l": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 4, C.Int32sb)
            ),
            # L	32-bit unsigned integer	uint32_t
            b"L": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 4, C.Int32ub)
            ),
            # q	32-bit Q Number Q15.16	uint32_t	16-bit integer (A) with 16-bit fixed point (B) for A.B value (range -32768.0 to 32767.99998)
            b"q": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 4, C.Int32ub)
            ),
            # Q	64-bit Q Number Q31.32	uint64_t	32-bit integer (A) with 32-bit fixed point (B) for A.B value.
            b"Q": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 8, C.Int64ub)
            ),
            # s	16-bit signed integer	int16_t	-32768 to 32768
            b"s": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 2, C.Int16sb)
            ),
            # S	16-bit unsigned integer	uint16_t	0 to 65536
            b"S": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 2, C.Int16ub)
            ),
            # U	UTC Date and Time string	char utcdate[16]	Date + UTC Time format yymmddhhmmss.sss - (years 20xx covered)
            b"U": C.Array(
                C.this.repeat, C.Array(C.this.structure_size // 16, C.Bytes(16))
            ),
            # ?	data structure is complex	TYPE	Structure is defined with a preceding TYPE
            # null	Nested metadata	uint32_t	The data within is GPMF structured KLV data
            b"\x00": C.FixedSized(
                (C.this.repeat * C.this.structure_size),
                C.LazyBound(lambda: GPMFSampleData),
            ),
        },
        C.Array(C.this.repeat, C.Bytes(C.this.structure_size)),
    ),
    C.IfThenElse(
        (C.this.repeat * C.this.structure_size) % 4 == 0,
        C.Padding(0),
        C.Padding(4 - (C.this.repeat * C.this.structure_size) % 4),
    ),
)


GPMFSampleData = C.GreedyRange(KLV)


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
def gps_from_stream(
    stream: T.Sequence[KLVDict],
) -> T.Generator[geo.PointWithFix, None, None]:
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
        gpsf_value = geo.GPSFix(gpsf[0][0])
    else:
        gpsf_value = None

    gpsp = indexed.get(b"GPSP")
    if gpsp is not None:
        gpsp_value = gpsp[0][0]
    else:
        gpsp_value = None

    for point in gps5:
        lat, lon, alt, ground_speed, _speed_3d = [
            v / s for v, s in zip(point, scal_values)
        ]
        yield geo.PointWithFix(
            # will figure out the actual timestamp later
            time=0,
            lat=lat,
            lon=lon,
            alt=alt,
            gps_fix=gpsf_value,
            gps_precision=gpsp_value,
            gps_ground_speed=ground_speed,
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


def _find_first_gps_stream(stream: T.Sequence[KLVDict]) -> T.List[geo.PointWithFix]:
    sample_points: T.List[geo.PointWithFix] = []

    for klv in stream:
        if klv["key"] == b"STRM":
            sample_points = list(gps_from_stream(klv["data"]))
            if sample_points:
                break

    return sample_points


def _extract_dvnm_from_samples(
    fp: T.BinaryIO, samples: T.Iterable[sample_parser.Sample]
) -> T.Dict[int, bytes]:
    dvnm_by_dvid: T.Dict[int, bytes] = {}

    for sample in samples:
        fp.seek(sample.offset, io.SEEK_SET)
        data = fp.read(sample.size)
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


def _extract_points_from_samples(
    fp: T.BinaryIO, samples: T.Iterable[sample_parser.Sample]
) -> T.List[geo.PointWithFix]:
    # To keep GPS points from different devices separated
    points_by_dvid: T.Dict[int, T.List[geo.PointWithFix]] = {}

    for sample in samples:
        fp.seek(sample.offset, io.SEEK_SET)
        data = fp.read(sample.size)
        gpmf_sample_data = T.cast(T.Dict, GPMFSampleData.parse(data))

        # iterate devices
        devices = (klv for klv in gpmf_sample_data if klv["key"] == b"DEVC")
        for device in devices:
            sample_points = _find_first_gps_stream(device["data"])
            if sample_points:
                # interpolate timestamps in between
                avg_timedelta = sample.timedelta / len(sample_points)
                for idx, point in enumerate(sample_points):
                    point.time = sample.time_offset + avg_timedelta * idx

                device_id = _find_first_device_id(device["data"])
                device_points = points_by_dvid.setdefault(device_id, [])
                device_points.extend(sample_points)

    values = list(points_by_dvid.values())
    return values[0] if values else []


def extract_points(fp: T.BinaryIO) -> T.Optional[T.List[geo.PointWithFix]]:
    """
    Return a list of points (could be empty) if it is a valid GoPro video,
    otherwise None
    """
    points = None
    for h, s in parser.parse_path(fp, [b"moov", b"trak"]):
        trak_start_offset = s.tell()
        descriptions = _extract_gpmd_descriptions_from_trak(s, h.maxsize)
        if descriptions:
            s.seek(trak_start_offset, io.SEEK_SET)
            gpmd_samples = _extract_gpmd_samples_from_trak(s, h.maxsize)
            points = list(_extract_points_from_samples(fp, gpmd_samples))
            # return the firstly found non-empty points
            if points:
                return points
    # points could be empty list or None here
    return points


def _extract_gpmd_descriptions_from_trak(
    s: T.BinaryIO,
    maxsize: int = -1,
):
    descriptions = sample_parser.parse_descriptions_from_trak(s, maxsize=maxsize)
    return [d for d in descriptions if d["format"] == b"gpmd"]


def _extract_gpmd_samples_from_trak(
    s: T.BinaryIO,
    maxsize: int = -1,
) -> T.Generator[sample_parser.Sample, None, None]:
    trak_start_offset = s.tell()
    gpmd_descriptions = _extract_gpmd_descriptions_from_trak(s, maxsize=maxsize)
    if gpmd_descriptions:
        s.seek(trak_start_offset, io.SEEK_SET)
        samples = sample_parser.parse_samples_from_trak(s, maxsize=maxsize)
        gpmd_samples = (
            sample for sample in samples if sample.description["format"] == b"gpmd"
        )
        yield from gpmd_samples


def extract_all_device_names(fp: T.BinaryIO) -> T.Dict[int, bytes]:
    for h, s in parser.parse_path(fp, [b"moov", b"trak"]):
        gpmd_samples = _extract_gpmd_samples_from_trak(s, h.maxsize)
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


def parse_gpx(path: pathlib.Path) -> T.List[geo.PointWithFix]:
    with path.open("rb") as fp:
        points = extract_points(fp)
    if points is None:
        return []
    return points


def iterate_gpmd_sample_data(fp: T.BinaryIO) -> T.Generator[T.Dict, None, None]:
    for h, s in parser.parse_path(fp, [b"moov", b"trak"]):
        gpmd_samples = _extract_gpmd_samples_from_trak(s, h.maxsize)
        for sample in gpmd_samples:
            fp.seek(sample.offset, io.SEEK_SET)
            data = fp.read(sample.size)
            yield T.cast(T.Dict, GPMFSampleData.parse(data))
