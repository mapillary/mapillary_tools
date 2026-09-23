# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest

from mapillary_tools import exceptions, novatek_parser, telemetry, types
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor
from mapillary_tools.geotag.video_extractors.native import NativeVideoExtractor


def _box(box_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I", 8 + len(data)) + box_type + data


def _build_video(blocks: list[bytes], duration: float | None = None) -> bytes:
    """
    Build a video with the blocks in mdat, indexed by moov/"gps " as Novatek does.
    By default the video is as long as the blocks, one per second.
    """
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")
    index = b""
    offset = len(ftyp) + 8
    for block in blocks:
        index += struct.pack(">II", offset, len(block))
        offset += len(block)
    if duration is None:
        duration = len(blocks)
    mvhd = struct.pack(">4xIIII", 0, 0, 1000, int(duration * 1000)).ljust(100, b"\x00")
    gps = struct.pack(">II", 0x101, len(blocks)) + index
    moov = _box(b"moov", _box(b"mvhd", mvhd) + _box(b"gps ", gps))
    return ftyp + _box(b"mdat", b"".join(blocks)) + moov


def _freegps_block(fields: dict[int, bytes], size: int = 0x100) -> bytes:
    block = bytearray(size)
    block[0:12] = struct.pack(">I", size) + b"freeGPS "
    for offset, data in fields.items():
        block[offset : offset + len(data)] = data
    return bytes(block)


def _type1_block(
    date_time: bytes = b"20180924224928",
    lat: bytes = b"N40464350",
    lon: bytes = b"W007040308",
    tail: bytes = b"00000007",
) -> bytes:
    # AZDome GS63H: text XOR encrypted from byte 18
    plain = (
        b"\x00\x00XKZD\xfe\xfe" + date_time + b"\x0c5567GP   \x00\x00\x00\x00\x00\x03"
    )
    plain += lat + lon + tail
    return _freegps_block(
        {
            12: b"\x05\x01\x00\x00\x01\x03",
            18: bytes(b ^ 0xAA for b in plain.ljust(0x100 - 18, b"\x00")),
        }
    )


def _type3_block(
    hms: tuple[int, int, int] = (5, 47, 3),
    ymd: tuple[int, int, int] = (19, 9, 27),
    lat: tuple[float, bytes] = (4922.143, b"N"),
    lon: tuple[float, bytes] = (12305.985, b"W"),
    track: float = 16.49,
) -> bytes:
    # Viofo A129: float32 values
    return _freegps_block(
        {
            16: struct.pack("<6I", *hms, *ymd),
            0x28: b"A" + lat[1] + lon[1] + b"\x00",
            0x2C: struct.pack("<4f", lat[0], lon[0], 26.3, track),
        }
    )


def _type15_block(
    hms: tuple[int, int, int] = (13, 22, 30),
    ymd: tuple[int, int, int] = (22, 12, 14),
    lat: tuple[float, bytes] = (4721.35197, b"N"),
    lon: tuple[float, bytes] = (830.80859, b"E"),
    track: float = 199.88,
) -> bytes:
    # Vantrue N4: float64 values
    return _freegps_block(
        {
            16: struct.pack("<3I", *hms),
            28: b"A",
            32: struct.pack("<d", lat[0]) + lat[1],
            48: struct.pack("<d", lon[0]) + lon[1],
            64: struct.pack("<2d3I", 22.519, track, *ymd),
        }
    )


# Written by the Vantrue N4 and Viofo A139 when there is no GPS fix
NO_FIX_BLOCK = _freegps_block({})


def _extract(blocks: list[bytes]) -> list[telemetry.GPSPoint] | None:
    return novatek_parser.extract_points(io.BytesIO(_build_video(blocks)))


# The expected positions and epoch times below are the same as extracted by
# ExifTool 13.40 from the same videos. The times are the positions of the blocks.
def _point(time, lat, lon, angle, epoch_time) -> telemetry.GPSPoint:
    return telemetry.GPSPoint(
        time=time,
        lat=lat,
        lon=lon,
        alt=None,
        angle=angle,
        epoch_time=epoch_time,
        fix=None,
        precision=None,
        ground_speed=None,
    )


def test_type15():
    # In the southern and western hemispheres
    next_block = _type15_block(
        hms=(13, 22, 31), lat=(4721.3524, b"S"), lon=(830.8082, b"W"), track=198.5
    )
    points = _extract(
        [
            # The camera has no fix yet when it starts recording
            NO_FIX_BLOCK,
            _type15_block(),
            next_block,
            # The camera repeats the last fix
            next_block,
            NO_FIX_BLOCK,
        ]
    )
    assert points == [
        _point(1.0, 47.3558661666667, 8.5134765, 199.88, 1671024150.0),
        _point(2.0, -47.3558733333333, -8.51347, 198.5, 1671024151.0),
    ]


def test_timelapse():
    # A block per second of video, 15 seconds apart in GPS time
    points = _extract(
        [
            _type15_block(hms=(13, 22, 30)),
            _type15_block(hms=(13, 22, 45)),
            _type15_block(hms=(13, 23, 0)),
        ]
    )
    assert points is not None
    assert [(p.time, p.epoch_time) for p in points] == [
        (0.0, 1671024150.0),
        (1.0, 1671024165.0),
        (2.0, 1671024180.0),
    ]


def test_skipped_blocks():
    # Skipped blocks still take their second of the video
    points = _extract(
        [
            # Too small for ExifTool
            _type15_block()[:81],
            # Not a freeGPS block
            b"\x00\x00\x01\x00free    " + _type15_block()[12:],
            _type15_block(),
        ]
    )
    assert points is not None
    assert [p.time for p in points] == [2.0]


def test_type3():
    points = _extract(
        [
            NO_FIX_BLOCK,
            _type3_block(),
            _type3_block(
                hms=(5, 47, 4),
                lat=(4922.155, b"N"),
                lon=(12305.995, b"W"),
                track=16.5,
            ),
        ]
    )
    assert points == [
        _point(
            1.0, 49.3690511067708, -123.099755859375, 16.4899997711182, 1569563223.0
        ),
        _point(2.0, 49.3692464192708, -123.099918619792, 16.5, 1569563224.0),
    ]


def test_type3_local_time():
    # ExifTool converts the time to UTC by the time zone of the machine it runs on
    assert _extract([_type3_block(ymd=(2019, 9, 27))]) is None


def test_type1():
    points = _extract(
        [
            _type1_block(),
            _type1_block(
                date_time=b"20180924224929", lat=b"N40464355", lon=b"W007040310"
            ),
        ]
    )
    assert points == [
        _point(0.0, 40.7739166666667, -7.06718, None, 1537829368.0),
        _point(1.0, 40.773925, -7.06718333333333, None, 1537829369.0),
    ]


def test_type1_date_without_gps():
    # AZDome stores the date without GPS, and ExifTool extracts it
    # when the accelerometer data is at the AZDome location
    block = _type1_block(
        lat=b" " * 9, lon=b" " * 10, tail=b"\x00" * (173 - 57) + b"+001-002+098"
    )
    assert _extract([block]) is None


def test_invalid_date_skipped():
    points = _extract(
        [
            _type15_block(hms=(13, 22, 30), ymd=(22, 2, 30)),
            _type15_block(hms=(13, 22, 31), ymd=(22, 13, 14)),
            _type15_block(hms=(13, 22, 32), ymd=(22, 12, 14)),
        ]
    )
    assert points is not None
    assert [(p.time, p.epoch_time) for p in points] == [(2.0, 1671024152.0)]


@pytest.mark.parametrize(
    "blocks",
    [
        [],
        [NO_FIX_BLOCK],
        # Unsupported layout (type 13)
        [_type15_block(), _freegps_block({16: b"ANE\x00"})],
        # Valid Nextbase records (type 20)
        [
            _type15_block(),
            _freegps_block({0x36: struct.pack(">HBBBBH", 2018, 10, 8, 6, 42, 465)}),
        ],
        # Mixed layouts
        [_type15_block(), _type3_block()],
        # Invalid numbers
        [_type15_block(lat=(float("nan"), b"N"))],
        # Truncated
        [_type15_block()[:84]],
    ],
)
def test_no_points(blocks: list[bytes]):
    assert _extract(blocks) is None


@pytest.mark.parametrize("duration", [1.0, 5.0, 0.0])
def test_unexpected_block_count(duration: float):
    # Not a block per second of video, so the block times are unknown
    video = _build_video([_type15_block()] * 3, duration=duration)
    assert novatek_parser.extract_points(io.BytesIO(video)) is None


def test_invalid_index():
    block = _type15_block()
    data = _build_video([block])
    # Point the index past the end of the file
    data = data[:-8] + struct.pack(">II", len(data) + 100, len(block))
    assert novatek_parser.extract_points(io.BytesIO(data)) is None
    assert novatek_parser.extract_points(io.BytesIO(b"")) is None
    assert novatek_parser.extract_points(io.BytesIO(b"\x00\x00\x00\x09moov")) is None


def test_native_video_extractor(tmp_path: Path):
    video_path = tmp_path / "novatek.mp4"
    video_path.write_bytes(_build_video([_type15_block()]))
    video_metadata = NativeVideoExtractor(video_path).extract()
    assert video_metadata.filetype == types.FileType.VIDEO
    assert video_metadata.make is None
    assert video_metadata.model is None
    assert video_metadata.points == [
        _point(0.0, 47.3558661666667, 8.5134765, 199.88, 1671024150.0)
    ]

    # Novatek is not one of the native file types
    with pytest.raises(exceptions.MapillaryVideoGPSNotFoundError):
        NativeVideoExtractor(video_path, filetypes={types.FileType.CAMM}).extract()

    video_path.write_bytes(_build_video([NO_FIX_BLOCK]))
    with pytest.raises(exceptions.MapillaryVideoGPSNotFoundError):
        NativeVideoExtractor(video_path).extract()


def test_gpx_sync(tmp_path: Path):
    video_path = tmp_path / "novatek.mp4"
    video_path.write_bytes(
        _build_video([_type15_block(), _type15_block(hms=(13, 22, 31))])
    )
    gpx_path = tmp_path / "track.gpx"
    gpx_path.write_text(
        '<gpx version="1.1" creator="test"><trk><trkseg>'
        '<trkpt lat="47.1" lon="8.1"><time>2022-12-14T13:22:20Z</time></trkpt>'
        '<trkpt lat="47.2" lon="8.2"><time>2022-12-14T13:22:30Z</time></trkpt>'
        '<trkpt lat="47.3" lon="8.3"><time>2022-12-14T13:22:40Z</time></trkpt>'
        "</trkseg></trk></gpx>"
    )
    # The GPX track is synced by the GPS time of the first fix
    video_metadata = GPXVideoExtractor(video_path, gpx_path).extract()
    assert [p.time for p in video_metadata.points] == [-10.0, 0.0, 10.0]
