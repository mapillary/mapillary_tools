# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Extract GPS from the "freeGPS " blocks written by Novatek based dashcams.

The moov/"gps " box indexes the "freeGPS " blocks stored in mdat. The block layout
varies by vendor. ExifTool (ProcessFreeGPS in QuickTimeStream.pl) tells the layouts
apart by probing them in a fixed order, and numbers them with its GPSType.

This parser probes the blocks in the same order and decodes only these layouts:
- Type 1: XOR encrypted text (AZDome GS63H)
- Type 3: float32 values (Viofo A129, Viofo A139, Anker Roav C1 Pro)
- Type 15: float64 values (Vantrue N4, Rove R2-4K Pro)

The decoded positions and GPS times match what the ExifTool fallback extracts from
the same video. If a video contains any block that can't be decoded that way,
extract_points returns None and the video is left to ExifTool.

Point times differ from ExifTool's on purpose. The camera writes one block per second
of video, right after the frames of that second, whether it has a fix or not (and in
timelapse too), so the position of the block in the index is its time in the video.
Counting from the first fix instead, as ExifTool's times do, would shift the track
whenever the camera gets its first fix after it starts recording.
"""

from __future__ import annotations

import datetime
import math
import re
import struct
import typing as T

from . import telemetry
from .mp4 import simple_mp4_parser as sparser


# ExifTool ignores smaller blocks
_MIN_BLOCK_SIZE = 82

# Enough to probe and decode every layout
_MAX_BLOCK_READ_SIZE = 0x1000

# The last, partial second of the video may have no block
_MAX_BLOCK_COUNT_DIFF = 1.5

_FREEGPS_SIGNATURE = b"freeGPS "

_TYPE1_KEY = b"\xaa\xaa\xf2\xe1\xf0\xee\x54\x54"
_TYPE1_GPS = re.compile(
    rb"^.{8}(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2}).(.{15})([NS])(\d{8})([EW])(\d{9})",
    re.S,
)
_TYPE1_DATE = re.compile(
    rb"^.{8}(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2}).(.{15})", re.S
)
_TYPE1_ACC = re.compile(rb"^.{65}([-+]\d{3}){3}", re.S)
_TYPE1_ACC_AZDOME = re.compile(rb"^.{173}([-+]\d{3}){3}", re.S)

_TYPE2 = re.compile(rb"^.{52}\d{14}", re.S)
_TYPE3 = re.compile(rb"^.{37}\x00\x00\x00A([NS])([EW])\x00", re.S)
_TYPE3_BASE64 = re.compile(rb"^[A-Za-z0-9+/]{8,20}={0,2}\x00*$")
_TYPE3_DECIMAL = re.compile(rb"^\d{1,5}\.\d+\x00*$")
_TYPE5 = re.compile(rb"^(.{16}|.{48}|.{80})LIGOGPSINFO\x00", re.S)
_TYPE6 = re.compile(rb"^.{60}A\x00{3}.{4}[NS]\x00{3}.{4}[EW]\x00{3}", re.S)
_TYPE7 = re.compile(rb"^.{60}4W`b]S<", re.S)
_TYPE8 = re.compile(
    rb"^.{64}[\x01-\x0c]\x00{3}[\x01-\x1f]\x00{3}A[NS][EW]\x00{5}", re.S
)
_TYPE9 = re.compile(rb"^.{12}\xac\x00\x00\x00.{116}", re.S)
_TYPE10 = re.compile(rb"^.{64}A[NS][EW]\x00", re.S)
_TYPE12 = re.compile(rb"^.{60}A\x00.{10}[NS]\x00.{14}[EW]\x00", re.S)
_TYPE13 = re.compile(rb"^.{16}A[NS][EW]\x00", re.S)
_TYPE14 = re.compile(rb"^.{20}[\x00-\x18][\x00-\x3b]{2}[\x00-\x09]A[NS][EW]", re.S)
_TYPE15 = re.compile(rb"^.{28}A.{11}([NS]).{15}([EW])", re.S)
_TYPE16 = re.compile(rb"^.{72}A[NS][EW]\x00", re.S)
_TYPE18 = re.compile(rb"^.{23}\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} [N|S]", re.S)
# No re.S here, as in ExifTool
_TYPE19 = re.compile(rb"^.{30}A.{20}VV")


class _UnsupportedBlockError(Exception):
    pass


def extract_points(fp: T.BinaryIO) -> list[telemetry.GPSPoint] | None:
    """
    Return the GPS points sorted by time, or None if the video has no "gps " box,
    no points, or anything this parser does not support.
    Point time is the time in the video, and epoch_time is the Unix time of the fix.
    """
    try:
        fp.seek(0)
        gps_box = sparser.parse_mp4_data_first(fp, [b"moov", b"gps "])
        fp.seek(0)
        mvhd = sparser.parse_mp4_data_first(fp, [b"moov", b"mvhd"])
    except sparser.ParsingError:
        return None

    if gps_box is None or mvhd is None:
        return None

    index = _parse_gps_box(gps_box)

    # Block times assume one block per second of video
    duration = _parse_duration(mvhd)
    if duration is None or _MAX_BLOCK_COUNT_DIFF < abs(len(index) - duration):
        return None

    gps_types: set[int] = set()
    points: list[telemetry.GPSPoint] = []

    for position, block in _read_blocks(fp, index):
        gps_type = _probe_block(block)
        gps_types.add(gps_type)

        if gps_type == 20:
            # ExifTool falls back to type 20 (Nextbase binary records) for anything unknown,
            # including blocks without a fix. It extracts nothing unless the first record is valid.
            if _has_valid_nextbase_record(block):
                return None
            continue

        decode = _DECODERS.get(gps_type)
        if decode is None:
            return None

        try:
            point = decode(block)
        except _UnsupportedBlockError:
            return None

        if point is None:
            continue

        point.time = float(position)

        # Without a new fix, the camera may repeat the last one
        if not points or _point_key(points[-1]) != _point_key(point):
            points.append(point)

    # ExifTool aggregates GPSTrack by position, so it misaligns the track values
    # if some blocks have them (types 3 and 15) and others don't (type 1)
    if len(gps_types & _DECODERS.keys()) > 1:
        return None

    if not points:
        return None

    return points


def _parse_gps_box(data: bytes) -> list[tuple[int, int]]:
    """
    Parse the "gps " box into a list of (offset, size) of the "freeGPS " blocks

    >>> _parse_gps_box(bytes.fromhex("00000101 00000002 00001000 00008000 00009000 00008000"))
    [(4096, 32768), (36864, 32768)]

    The count is limited by the box size, as in ExifTool
    >>> _parse_gps_box(bytes.fromhex("00000101 00000009 00001000 00008000 00009000"))
    [(4096, 32768)]
    >>> _parse_gps_box(bytes.fromhex("00000101 00000009"))
    []
    """
    if len(data) <= 8:
        return []
    (count,) = struct.unpack_from(">I", data, 4)
    count = min(count, (len(data) - 8) // 8)
    return [struct.unpack_from(">II", data, 8 + i * 8) for i in range(count)]


def _parse_duration(mvhd: bytes) -> float | None:
    """
    Return the duration in seconds from the "mvhd" box

    >>> _parse_duration(bytes.fromhex("00000000 00000000 00000000 000003e8 0000ea60"))
    60.0
    >>> _parse_duration(bytes.fromhex("01000000" + "00" * 16 + "000003e8 000000000000ea60"))
    60.0
    >>> _parse_duration(bytes.fromhex("00000000 00000000 00000000 00000000 0000ea60")) is None
    True
    """
    try:
        if mvhd[0] == 1:
            timescale, duration = struct.unpack_from(">IQ", mvhd, 20)
        else:
            timescale, duration = struct.unpack_from(">II", mvhd, 12)
    except (IndexError, struct.error):
        return None
    if not timescale:
        return None
    return duration / timescale


def _read_blocks(
    fp: T.BinaryIO, index: list[tuple[int, int]]
) -> T.Generator[tuple[int, bytes], None, None]:
    """
    Yield the valid blocks with their positions in the index
    """
    for position, (offset, size) in enumerate(index):
        fp.seek(offset, 0)
        # The layouts can be told apart by the first bytes and a few size thresholds,
        # all smaller than _MAX_BLOCK_READ_SIZE, so reading more doesn't change the result
        block = fp.read(min(size, _MAX_BLOCK_READ_SIZE))
        if block[4:12] != _FREEGPS_SIGNATURE:
            continue
        if len(block) < _MIN_BLOCK_SIZE:
            continue
        yield position, block


def _probe_block(block: bytes) -> int:
    """
    Return ExifTool's GPSType of the block, i.e. the first layout that matches it
    """
    if block[18:26] == _TYPE1_KEY:
        return 1
    if _TYPE2.match(block):
        return 2
    if _TYPE3.match(block):
        return 3 if _is_type3_binary(block) else 4
    matched = _TYPE5.match(block)
    if matched and len(block) >= len(matched.group(1)) + 0x84:
        return 5
    if _TYPE6.match(block):
        return 6
    if _TYPE7.match(block) and len(block) >= 140:
        return 7
    if _TYPE8.match(block):
        return 8
    if _TYPE9.match(block):
        return 9
    if _TYPE10.match(block):
        return 10
    if block[0x45:0x48] == b"ATC":
        return 11
    if _TYPE12.match(block) and len(block) >= 0x88:
        return 12
    if _TYPE13.match(block):
        return 13
    if _TYPE14.match(block):
        return 14
    if _TYPE15.match(block):
        return 15
    if _TYPE16.match(block):
        # Types 16 and 17
        return 16
    if _TYPE18.match(block):
        return 18
    if _TYPE19.match(block):
        return 19
    return 20


def _is_type3_binary(block: bytes) -> bool:
    """
    Type 3 stores lat/lon as floats, while type 4 (E-ACE B44) stores them
    as decimal or base64 encoded (and encrypted) strings in the same place
    """
    if len(block) < 0x78:
        return True
    lat, lon = block[0x2C : 0x2C + 20], block[0x40 : 0x40 + 20]
    is_base64 = all(_TYPE3_BASE64.match(s) for s in (lat, lon))
    is_decimal = all(_TYPE3_DECIMAL.match(s) for s in (lat, lon))
    return not is_base64 and not is_decimal


def _has_valid_nextbase_record(block: bytes) -> bool:
    """
    Check the first record in the same way as ExifTool
    """
    year, month, day, hour, minute, second = struct.unpack_from(">HBBBBH", block, 0x36)
    return (
        2000 <= year <= 2200
        and 1 <= month <= 12
        and 1 <= day <= 31
        and hour <= 59
        and minute <= 59
        and second <= 600
    )


def _decode_type1(block: bytes) -> telemetry.GPSPoint | None:
    n = min(len(block) - 18, 0x101)
    decrypted = bytes(b ^ 0xAA for b in block[18 : 18 + n])

    matched = _TYPE1_GPS.match(decrypted)
    if matched is None:
        # AZDome may store the date without GPS, which ExifTool extracts
        # when the accelerometer data is found at the AZDome location
        if (
            not _TYPE1_ACC.match(decrypted)
            and _TYPE1_ACC_AZDOME.match(decrypted)
            and _TYPE1_DATE.match(decrypted)
        ):
            raise _UnsupportedBlockError("Date without GPS")
        return None

    year, month, day, hour, minute, second = (
        int(g) for g in matched.group(1, 2, 3, 4, 5, 6)
    )
    return _build_point(
        (year, month, day, hour, minute, second),
        lat=int(matched.group(9)) / 1e4,
        lat_ref=matched.group(8),
        lon=int(matched.group(11)) / 1e4,
        lon_ref=matched.group(10),
        angle=None,
    )


def _decode_type3(block: bytes) -> telemetry.GPSPoint | None:
    matched = _TYPE3.match(block)
    assert matched is not None
    hour, minute, second, year, month, day = struct.unpack_from("<6I", block, 16)
    if year >= 2000:
        # ExifTool assumes it is local time (Kenwood) and converts it to UTC
        # using the time zone of the machine it runs on
        raise _UnsupportedBlockError("Local time")
    lat, lon, _speed, track = struct.unpack_from("<4f", block, 0x2C)
    return _build_point(
        (year, month, day, hour, minute, second),
        lat=lat,
        lat_ref=matched.group(1),
        lon=lon,
        lon_ref=matched.group(2),
        angle=track,
    )


def _decode_type15(block: bytes) -> telemetry.GPSPoint | None:
    matched = _TYPE15.match(block)
    assert matched is not None
    try:
        hour, minute, second = struct.unpack_from("<3I", block, 16)
        year, month, day = struct.unpack_from("<3I", block, 80)
        (lat,) = struct.unpack_from("<d", block, 32)
        (lon,) = struct.unpack_from("<d", block, 48)
        (track,) = struct.unpack_from("<d", block, 72)
    except struct.error as ex:
        raise _UnsupportedBlockError("Block too small") from ex
    return _build_point(
        (year, month, day, hour, minute, second),
        lat=abs(lat),
        lat_ref=matched.group(1),
        lon=abs(lon),
        lon_ref=matched.group(2),
        angle=track,
    )


_DECODERS: dict[int, T.Callable[[bytes], telemetry.GPSPoint | None]] = {
    1: _decode_type1,
    3: _decode_type3,
    15: _decode_type15,
}


def _build_point(
    date_time: tuple[int, int, int, int, int, int],
    lat: float,
    lat_ref: bytes,
    lon: float,
    lon_ref: bytes,
    angle: float | None,
) -> telemetry.GPSPoint | None:
    year, month, day, hour, minute, second = date_time

    # ExifTool drops the block
    if not 1 <= month <= 12:
        return None

    if year < 2000:
        year += 2000

    epoch_time = _epoch_time(year, month, day, hour, minute, second)
    if epoch_time is None:
        return None

    if not all(math.isfinite(v) for v in (lat, lon, 0.0 if angle is None else angle)):
        raise _UnsupportedBlockError("Invalid number")

    lat = _to_exiftool_number(_ddmm_to_degrees(lat) * (-1 if lat_ref == b"S" else 1))
    lon = _to_exiftool_number(_ddmm_to_degrees(lon) * (-1 if lon_ref == b"W" else 1))
    if angle is not None:
        angle = _to_exiftool_number(angle)

    return telemetry.GPSPoint(
        # Set by extract_points from the position of the block
        time=0.0,
        lat=lat,
        lon=lon,
        alt=None,
        angle=angle,
        epoch_time=epoch_time,
        fix=None,
        precision=None,
        ground_speed=None,
    )


def _epoch_time(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> float | None:
    """
    Convert the date and time to Unix time in the same way as parsing the GPSDateTime
    extracted by ExifTool: invalid dates are rejected, while the time overflows into the date

    >>> _epoch_time(2023, 1, 6, 15, 5, 58)
    1673017558.0
    >>> _epoch_time(2023, 1, 6, 23, 59, 60)
    1673049600.0
    >>> _epoch_time(2023, 2, 30, 1, 2, 3) is None
    True
    """
    try:
        dt = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    try:
        dt = dt + datetime.timedelta(hours=hour, minutes=minute, seconds=second)
    except OverflowError as ex:
        raise _UnsupportedBlockError("Invalid time") from ex
    return dt.timestamp()


def _ddmm_to_degrees(value: float) -> float:
    """
    Convert DDDMM.MMMM to degrees in the same way as ExifTool (ConvertLatLon)

    >>> _ddmm_to_degrees(4721.35197)
    47.355866166666665
    """
    degrees = int(value / 100)
    return degrees + (value - degrees * 100) / 60


def _to_exiftool_number(value: float) -> float:
    """
    ExifTool prints numbers with 15 significant digits (Perl's default),
    so round the same way to get identical points

    >>> _to_exiftool_number(0.1 + 0.2)
    0.3
    """
    return float(f"{value:.15g}")


def _point_key(point: telemetry.GPSPoint) -> tuple:
    # The fix, regardless of the block it is in. The ExifTool extractor tells
    # duplicate points the same way, as its point time is the fix time.
    return (point.lon, point.lat, point.epoch_time, point.angle)
