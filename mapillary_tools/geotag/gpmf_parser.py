import dataclasses
import io
import pathlib
import typing as T

import construct as C

from .. import geo
from .simple_mp4_parser import parse_path, parse_samples_from_trak, Sample

"""
Parsing GPS from GPMF data format stored in GoPros. See the GPMF spec: https://github.com/gopro/gpmf-parser

From my observation, A GPS record in GPMF has the following structure:
- DEVC: Each connected device starts with DEVC.
    - DVID: Auto generated unique-ID for managing a large number of connect devices
    - STRM: Metadata streams are each nested with STRM
         - GPS5: latitude, longitude, altitude (WGS 84), 2D ground speed, and 3D speed
         - GPSA: not sure what it is -- not documented in the GPMF spec
         - GPSF: Within the GPS stream: 0 - no lock, 2 or 3 - 2D or 3D Lock.
         - GPSP: GPS Precision - Dilution of Precision (DOP x100). Under 500 is good.
         - GPSU: UTC time and data from GPS. The time is read from from another clock so it is not in use.
         - SCAL: Scaling factor (divisor) for GPS5


NOTE:
- There might be multiple DEVC streams. Check all of them and found the streams containing GPS5 KLVs.
- Only GPS5 and SCAL are required. The others are optional.
- GPSU is not in use. We use the video clock to make sure frames and GPS are in sync.
- We should skip records with GPSF==0 or GPSP >= 500
"""


GPMF: C.GreedyRange


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
                (C.this.repeat * C.this.structure_size), C.LazyBound(lambda: GPMF)
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


GPMF = C.GreedyRange(KLV)


@dataclasses.dataclass
class Point(geo.Point):
    gps_fix: int
    gps_precision: float


def gps_from_stream(stream: T.Sequence[T.Any]) -> T.Generator[Point, None, None]:
    indexed = {}
    for klv in stream:
        indexed[klv["key"]] = klv["data"]

    gps5 = indexed.get(b"GPS5")
    if gps5 is None:
        return

    scal = indexed.get(b"SCAL")
    if scal is None:
        return

    gpsf = indexed.get(b"GPSF")
    if gpsf is not None:
        gpsf_value = gpsf[0][0]
    else:
        gpsf_value = None

    gpsp = indexed.get(b"GPSP")
    if gpsp is not None:
        gpsp_value = gpsp[0][0]
    else:
        gpsp_value = None

    for point in gps5:
        try:
            lat, lon, alt, _ground_speed, _speed_3d = [
                v / s[0] for v, s in zip(point, scal)
            ]
        except ZeroDivisionError:
            return None

        yield Point(
            # will figure out the timestamp later
            time=0,
            lat=lat,
            lon=lon,
            alt=alt,
            gps_fix=gpsf_value,
            gps_precision=gpsp_value,
            angle=None,
        )


def _extract_points(fp: T.BinaryIO, samples: T.Iterable[Sample]):
    # There might be multiple GPS devices
    # This table is to make sure GPS points are not mixed
    # (i.e. points from device 1 and device 2 are added to the same track)
    dvid_points: T.Dict[int, T.List[Point]] = {}

    # The default value is for grouping points for those streams without DVID found,
    # it does not matter what value it is, however, to be safe, make sure it is larger than
    # DVID's type 32-bit unsigned integer (uint32_t)
    DEFAULT_DEVICE_ID = 2**32

    for sample in samples:
        fp.seek(sample.offset, io.SEEK_SET)
        data = fp.read(sample.size)
        klvs = GPMF.parse(data)

        # iterate devices
        devices = (klv for klv in klvs if klv["key"] == b"DEVC")
        for device in devices:
            device_id = DEFAULT_DEVICE_ID
            sample_points = []

            # iterate KLVs in the device
            for klv in device["data"]:
                if klv["key"] == b"DVID":
                    device_id = klv["data"][0][0]
                elif klv["key"] == b"STRM":
                    sample_points = list(gps_from_stream(klv["data"]))

                # return points in the first stream with GPS data found in the device
                if sample_points:
                    # calculate and update the timestamp based on current sample time offset
                    avg_timedelta_in_gps5 = sample.timedelta / len(sample_points)
                    for idx, point in enumerate(sample_points):
                        point.time = sample.time_offset + avg_timedelta_in_gps5 * idx
                    dvid_points.setdefault(device_id, []).extend(sample_points)
                    break

    if dvid_points:
        return list(dvid_points.values())[0]
    else:
        return []


def parse_gpx(path: pathlib.Path) -> T.List[Point]:
    with open(path, "rb") as fp:
        for h, s in parse_path(fp, [b"moov", b"trak"]):
            gpmd_samples = (
                sample
                for sample in parse_samples_from_trak(s, maxsize=h.maxsize)
                if sample.description.format == b"gpmd"
            )
            points = list(_extract_points(fp, gpmd_samples))
            if points:
                return points
    return []
