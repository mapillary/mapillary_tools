# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import os
from pathlib import Path

import pytest

from mapillary_tools import telemetry
from mapillary_tools.gpmf import gpmf_parser


# ---------------------------------------------------------------------------
# Test data file paths (used for integration-style tests)
# ---------------------------------------------------------------------------
GPS5_VIDEO = Path(
    "/tmp/mly_coverage_test/data/mly_test_data/GoPro MAX (works)/video 24 FPS/GS011498.360"
)
GPS9_VIDEO = Path(
    "/tmp/mly_coverage_test/data/mly_test_data/GoPro MAX 2 (works)/360 Video (including lower res)/GS015637.360"
)
HERO7_VIDEO = Path(
    "/tmp/mly_coverage_test/data/mly_test_data/GoPro Hero 7 (works)/GH010359.MP4"
)

_has_gps5_video = GPS5_VIDEO.exists()
_has_gps9_video = GPS9_VIDEO.exists()
_has_hero7_video = HERO7_VIDEO.exists()


# ---------------------------------------------------------------------------
# Helpers to construct realistic KLVDict structures
# ---------------------------------------------------------------------------
def _make_klv(
    key: bytes, type_char: bytes, data, structure_size: int = 0, repeat: int = 0
):
    """Build a minimal KLVDict-like dict with the fields the parser uses."""
    return {
        "key": key,
        "type": type_char,
        "structure_size": structure_size,
        "repeat": repeat,
        "data": data,
    }


# ---------------------------------------------------------------------------
# 1. _gps5_timestamp_to_epoch_time
# ---------------------------------------------------------------------------
class TestGps5TimestampToEpochTime:
    def test_known_timestamp(self):
        # GPSU from the GoPro MAX file: '230117115504.225' means 2023-01-17 11:55:04.225 UTC
        epoch = gpmf_parser._gps5_timestamp_to_epoch_time("230117115504.225")
        dt = datetime.datetime(
            2023, 1, 17, 11, 55, 4, 225000, tzinfo=datetime.timezone.utc
        )
        assert epoch == pytest.approx(dt.timestamp(), abs=0.001)

    def test_midnight_timestamp(self):
        epoch = gpmf_parser._gps5_timestamp_to_epoch_time("230101000000.000")
        dt = datetime.datetime(2023, 1, 1, 0, 0, 0, 0, tzinfo=datetime.timezone.utc)
        assert epoch == pytest.approx(dt.timestamp(), abs=0.001)

    def test_end_of_year(self):
        epoch = gpmf_parser._gps5_timestamp_to_epoch_time("231231235959.999")
        dt = datetime.datetime(
            2023, 12, 31, 23, 59, 59, 999000, tzinfo=datetime.timezone.utc
        )
        assert epoch == pytest.approx(dt.timestamp(), abs=0.001)


# ---------------------------------------------------------------------------
# 2. _gps9_timestamp_to_epoch_time
# ---------------------------------------------------------------------------
class TestGps9TimestampToEpochTime:
    def test_known_values_from_real_data(self):
        # days_since_2000=9463, secs_since_midnight=44896.0 -> 2025-11-28 12:28:16 UTC
        epoch = gpmf_parser._gps9_timestamp_to_epoch_time(9463, 44896.0)
        assert epoch == pytest.approx(1764332896.0, abs=1.0)

    def test_epoch_at_2000(self):
        # 0 days, 0 secs -> 2000-01-01T00:00:00 UTC
        epoch = gpmf_parser._gps9_timestamp_to_epoch_time(0, 0.0)
        dt_2000 = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
        assert epoch == pytest.approx(dt_2000.timestamp(), abs=0.001)

    def test_one_day_after_2000(self):
        epoch = gpmf_parser._gps9_timestamp_to_epoch_time(1, 0.0)
        dt = datetime.datetime(2000, 1, 2, tzinfo=datetime.timezone.utc)
        assert epoch == pytest.approx(dt.timestamp(), abs=0.001)

    def test_fractional_seconds(self):
        # 0 days, 3600.5 secs -> 2000-01-01T01:00:00.5 UTC
        epoch = gpmf_parser._gps9_timestamp_to_epoch_time(0, 3600.5)
        dt = datetime.datetime(
            2000, 1, 1, 1, 0, 0, 500000, tzinfo=datetime.timezone.utc
        )
        assert epoch == pytest.approx(dt.timestamp(), abs=0.001)


# ---------------------------------------------------------------------------
# 3. _get_gps_type
# ---------------------------------------------------------------------------
class TestGetGpsType:
    def test_flat_bytes_list(self):
        # TYPE data from real GPS9 stream: [b'lllllllSS']
        result = gpmf_parser._get_gps_type([b"lllllllSS"])
        assert result == b"lllllllSS"

    def test_nested_bytes(self):
        # e.g., [b'll', [b'SS', b'bb']]
        result = gpmf_parser._get_gps_type([b"ll", [b"SS", b"bb"]])
        assert result == b"llSSbb"

    def test_empty_input(self):
        result = gpmf_parser._get_gps_type([])
        assert result == b""

    def test_none_input(self):
        result = gpmf_parser._get_gps_type(None)
        assert result == b""

    def test_unexpected_type_raises(self):
        with pytest.raises(ValueError, match="Unexpected type"):
            gpmf_parser._get_gps_type([123])

    def test_deeply_nested(self):
        result = gpmf_parser._get_gps_type([[b"a", [b"b"]]])
        assert result == b"ab"


# ---------------------------------------------------------------------------
# 4. _gps5_from_stream - unit tests using constructed KLVDict data
# ---------------------------------------------------------------------------
class TestGps5FromStream:
    def _make_gps5_stream(
        self,
        gps5_data=None,
        scal_data=None,
        gpsf_data=None,
        gpsu_data=None,
        gpsp_data=None,
    ):
        """Build a GPS5 STRM stream with realistic structure."""
        stream = []
        if gpsf_data is not None:
            stream.append(_make_klv(b"GPSF", b"L", gpsf_data))
        if gpsu_data is not None:
            stream.append(_make_klv(b"GPSU", b"U", gpsu_data))
        if gpsp_data is not None:
            stream.append(_make_klv(b"GPSP", b"S", gpsp_data))
        if scal_data is not None:
            stream.append(_make_klv(b"SCAL", b"l", scal_data))
        if gps5_data is not None:
            stream.append(_make_klv(b"GPS5", b"l", gps5_data))
        return stream

    def test_basic_gps5_parsing(self):
        """Parse two GPS5 points from the GoPro MAX real data."""
        # Real values from the GoPro MAX file
        stream = self._make_gps5_stream(
            gps5_data=[
                [473598318, 85227055, 414870, 891, 119],
                [473598322, 85227045, 414950, 1064, 95],
            ],
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
            gpsf_data=[[3]],
            gpsu_data=[[b"230117115504.225"]],
            gpsp_data=[[219]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert len(points) == 2

        p0 = points[0]
        assert p0.lat == pytest.approx(47.3598318, abs=1e-7)
        assert p0.lon == pytest.approx(8.5227055, abs=1e-7)
        assert p0.alt == pytest.approx(414.87, abs=0.01)
        assert p0.ground_speed == pytest.approx(0.891, abs=0.001)
        assert p0.fix == telemetry.GPSFix.FIX_3D
        assert p0.precision == 219
        assert p0.epoch_time is not None
        assert p0.time == 0  # time is always 0 from _gps5_from_stream
        assert p0.angle is None

        p1 = points[1]
        assert p1.lat == pytest.approx(47.3598322, abs=1e-7)
        assert p1.lon == pytest.approx(8.5227045, abs=1e-7)

    def test_no_gps5_key(self):
        """Stream without GPS5 key yields nothing."""
        stream = self._make_gps5_stream(
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert points == []

    def test_no_scal_key(self):
        """Stream without SCAL key yields nothing."""
        stream = self._make_gps5_stream(
            gps5_data=[[473598318, 85227055, 414870, 891, 119]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert points == []

    def test_zero_scale_value(self):
        """Zero in SCAL causes early return (avoids division by zero)."""
        stream = self._make_gps5_stream(
            gps5_data=[[473598318, 85227055, 414870, 891, 119]],
            scal_data=[[10000000], [0], [1000], [1000], [100]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert points == []

    def test_no_gpsf(self):
        """Missing GPSF -> fix is None."""
        stream = self._make_gps5_stream(
            gps5_data=[[473598318, 85227055, 414870, 891, 119]],
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert len(points) == 1
        assert points[0].fix is None

    def test_gpsf_no_lock(self):
        """GPSF=0 means no lock."""
        stream = self._make_gps5_stream(
            gps5_data=[[473598318, 85227055, 414870, 891, 119]],
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
            gpsf_data=[[0]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert len(points) == 1
        assert points[0].fix == telemetry.GPSFix.NO_FIX

    def test_gpsf_2d_lock(self):
        """GPSF=2 means 2D lock."""
        stream = self._make_gps5_stream(
            gps5_data=[[473598318, 85227055, 414870, 891, 119]],
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
            gpsf_data=[[2]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert points[0].fix == telemetry.GPSFix.FIX_2D

    def test_no_gpsu(self):
        """Missing GPSU -> epoch_time is None."""
        stream = self._make_gps5_stream(
            gps5_data=[[473598318, 85227055, 414870, 891, 119]],
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert len(points) == 1
        assert points[0].epoch_time is None

    def test_invalid_gpsu(self):
        """Invalid GPSU string -> epoch_time is None (exception caught)."""
        stream = self._make_gps5_stream(
            gps5_data=[[473598318, 85227055, 414870, 891, 119]],
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
            gpsu_data=[[b"invalid_gpsu_str"]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert len(points) == 1
        assert points[0].epoch_time is None

    def test_no_gpsp(self):
        """Missing GPSP -> precision is None."""
        stream = self._make_gps5_stream(
            gps5_data=[[473598318, 85227055, 414870, 891, 119]],
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert len(points) == 1
        assert points[0].precision is None

    def test_epoch_time_same_for_all_points_in_sample(self):
        """All points in the same GPS5 sample share the same epoch_time."""
        stream = self._make_gps5_stream(
            gps5_data=[
                [473598318, 85227055, 414870, 891, 119],
                [473598322, 85227045, 414950, 1064, 95],
                [473598323, 85227036, 415033, 1139, 111],
            ],
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
            gpsu_data=[[b"230117115504.225"]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert len(points) == 3
        # All should have the same epoch_time
        assert points[0].epoch_time == points[1].epoch_time == points[2].epoch_time

    def test_negative_coordinates(self):
        """Negative GPS coordinates (southern/western hemisphere)."""
        # Hero 7 data: lat=34.3985866, lon=-119.6986334 (negative raw lon)
        stream = self._make_gps5_stream(
            gps5_data=[[343985866, -1196986334, -34141, 313, 50]],
            scal_data=[[10000000], [10000000], [1000], [1000], [100]],
            gpsf_data=[[3]],
        )
        points = list(gpmf_parser._gps5_from_stream(stream))
        assert len(points) == 1
        assert points[0].lat == pytest.approx(34.3985866, abs=1e-7)
        assert points[0].lon == pytest.approx(-119.6986334, abs=1e-7)
        assert points[0].alt == pytest.approx(-34.141, abs=0.001)


# ---------------------------------------------------------------------------
# 5. _gps9_from_stream - unit tests
# ---------------------------------------------------------------------------
class TestGps9FromStream:
    def _make_gps9_stream(
        self,
        gps9_data=None,
        scal_data=None,
        type_data=None,
    ):
        """Build a GPS9 STRM stream with realistic structure."""
        stream = []
        if type_data is not None:
            stream.append(_make_klv(b"TYPE", b"c", type_data))
        if scal_data is not None:
            stream.append(_make_klv(b"SCAL", b"l", scal_data))
        if gps9_data is not None:
            stream.append(_make_klv(b"GPS9", b"?", gps9_data))
        return stream

    def _build_gps9_sample_bytes(
        self, lat, lon, alt, speed2d, speed3d, days, secs_ms, dop, fix
    ):
        """Encode raw GPS9 values as bytes using the 'lllllllSS' format."""
        import struct

        return struct.pack(
            ">iiiiiiiHH",
            lat,
            lon,
            alt,
            speed2d,
            speed3d,
            days,
            secs_ms,
            dop,
            fix,
        )

    def test_basic_gps9_parsing(self):
        """Parse a GPS9 point from GoPro MAX2 real data."""
        # Real bytes from the file
        sample_bytes = bytes.fromhex(
            "1e71d2c703b6242500014dce000001270000002a000024f702ad0f0000b90003"
        )

        stream = self._make_gps9_stream(
            gps9_data=[sample_bytes],
            scal_data=[
                [10000000],
                [10000000],
                [1000],
                [1000],
                [100],
                [1],
                [1000],
                [100],
                [1],
            ],
            type_data=[b"lllllllSS"],
        )
        points = list(gpmf_parser._gps9_from_stream(stream))
        assert len(points) == 1

        p = points[0]
        assert p.lat == pytest.approx(51.0776007, abs=1e-6)
        assert p.lon == pytest.approx(6.2268453, abs=1e-6)
        assert p.alt == pytest.approx(85.454, abs=0.01)
        assert p.ground_speed == pytest.approx(0.295, abs=0.001)
        assert p.fix == telemetry.GPSFix.FIX_3D
        assert p.precision == pytest.approx(185.0, abs=0.1)
        assert p.epoch_time == pytest.approx(1764332896.0, abs=1.0)
        assert p.time == 0
        assert p.angle is None

    def test_no_gps9_key(self):
        stream = self._make_gps9_stream(
            scal_data=[
                [10000000],
                [10000000],
                [1000],
                [1000],
                [100],
                [1],
                [1000],
                [100],
                [1],
            ],
            type_data=[b"lllllllSS"],
        )
        points = list(gpmf_parser._gps9_from_stream(stream))
        assert points == []

    def test_no_scal_key(self):
        sample_bytes = self._build_gps9_sample_bytes(
            510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3
        )
        stream = self._make_gps9_stream(
            gps9_data=[sample_bytes],
            type_data=[b"lllllllSS"],
        )
        points = list(gpmf_parser._gps9_from_stream(stream))
        assert points == []

    def test_no_type_key(self):
        sample_bytes = self._build_gps9_sample_bytes(
            510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3
        )
        stream = self._make_gps9_stream(
            gps9_data=[sample_bytes],
            scal_data=[
                [10000000],
                [10000000],
                [1000],
                [1000],
                [100],
                [1],
                [1000],
                [100],
                [1],
            ],
        )
        points = list(gpmf_parser._gps9_from_stream(stream))
        assert points == []

    def test_zero_scale_value(self):
        sample_bytes = self._build_gps9_sample_bytes(
            510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3
        )
        stream = self._make_gps9_stream(
            gps9_data=[sample_bytes],
            scal_data=[[10000000], [0], [1000], [1000], [100], [1], [1000], [100], [1]],
            type_data=[b"lllllllSS"],
        )
        points = list(gpmf_parser._gps9_from_stream(stream))
        assert points == []

    def test_wrong_type_length_raises(self):
        sample_bytes = self._build_gps9_sample_bytes(
            510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3
        )
        stream = self._make_gps9_stream(
            gps9_data=[sample_bytes],
            scal_data=[
                [10000000],
                [10000000],
                [1000],
                [1000],
                [100],
                [1],
                [1000],
                [100],
                [1],
            ],
            type_data=[b"llll"],  # only 4 types instead of 9
        )
        with pytest.raises(ValueError, match="expect 9 types"):
            list(gpmf_parser._gps9_from_stream(stream))

    def test_multiple_gps9_samples(self):
        """Multiple GPS9 samples in one stream."""
        s1 = self._build_gps9_sample_bytes(
            510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3
        )
        s2 = self._build_gps9_sample_bytes(
            510776005, 62268463, 85505, 300, 45, 9463, 44897000, 190, 3
        )
        stream = self._make_gps9_stream(
            gps9_data=[s1, s2],
            scal_data=[
                [10000000],
                [10000000],
                [1000],
                [1000],
                [100],
                [1],
                [1000],
                [100],
                [1],
            ],
            type_data=[b"lllllllSS"],
        )
        points = list(gpmf_parser._gps9_from_stream(stream))
        assert len(points) == 2
        # Each point should have its own epoch_time
        assert points[0].epoch_time != points[1].epoch_time
        assert points[1].epoch_time == pytest.approx(
            gpmf_parser._gps9_timestamp_to_epoch_time(9463, 44897.0), abs=0.01
        )


# ---------------------------------------------------------------------------
# 6. _find_first_device_id
# ---------------------------------------------------------------------------
class TestFindFirstDeviceId:
    def test_dvid_present(self):
        stream = [
            _make_klv(b"DVID", b"L", [[1]]),
            _make_klv(b"DVNM", b"c", [b"GoPro Max"]),
        ]
        assert gpmf_parser._find_first_device_id(stream) == 1

    def test_dvid_large_value(self):
        stream = [
            _make_klv(b"DVID", b"L", [[4294967295]]),
        ]
        assert gpmf_parser._find_first_device_id(stream) == 4294967295

    def test_no_dvid_returns_default(self):
        stream = [
            _make_klv(b"DVNM", b"c", [b"GoPro Max"]),
        ]
        device_id = gpmf_parser._find_first_device_id(stream)
        assert device_id == 2**32

    def test_empty_stream(self):
        device_id = gpmf_parser._find_first_device_id([])
        assert device_id == 2**32

    def test_dvid_first_wins(self):
        """If multiple DVID entries exist, the first one is used."""
        stream = [
            _make_klv(b"DVID", b"L", [[5]]),
            _make_klv(b"DVID", b"L", [[10]]),
        ]
        assert gpmf_parser._find_first_device_id(stream) == 5


# ---------------------------------------------------------------------------
# 7. _find_first_gps_stream - prefers GPS9 over GPS5
# ---------------------------------------------------------------------------
class TestFindFirstGpsStream:
    def test_gps5_stream_found(self):
        gps5_strm = _make_klv(
            b"STRM",
            b"\x00",
            [
                _make_klv(
                    b"SCAL", b"l", [[10000000], [10000000], [1000], [1000], [100]]
                ),
                _make_klv(b"GPS5", b"l", [[473598318, 85227055, 414870, 891, 119]]),
                _make_klv(b"GPSF", b"L", [[3]]),
            ],
        )
        points = gpmf_parser._find_first_gps_stream([gps5_strm])
        assert len(points) == 1
        assert points[0].lat == pytest.approx(47.3598318, abs=1e-7)

    def test_empty_stream(self):
        points = gpmf_parser._find_first_gps_stream([])
        assert points == []

    def test_no_strm_key(self):
        non_strm = _make_klv(b"DVNM", b"c", [b"GoPro Max"])
        points = gpmf_parser._find_first_gps_stream([non_strm])
        assert points == []

    def test_gps9_preferred_over_gps5(self):
        """GPS9 is tried first within each STRM; GPS5 is fallback."""
        import struct

        sample_bytes = struct.pack(
            ">iiiiiiiHH",
            510776007,
            62268453,
            85454,
            295,
            42,
            9463,
            44896000,
            185,
            3,
        )
        gps9_strm = _make_klv(
            b"STRM",
            b"\x00",
            [
                _make_klv(b"TYPE", b"c", [b"lllllllSS"]),
                _make_klv(
                    b"SCAL",
                    b"l",
                    [
                        [10000000],
                        [10000000],
                        [1000],
                        [1000],
                        [100],
                        [1],
                        [1000],
                        [100],
                        [1],
                    ],
                ),
                _make_klv(b"GPS9", b"?", [sample_bytes]),
            ],
        )
        points = gpmf_parser._find_first_gps_stream([gps9_strm])
        assert len(points) == 1
        assert points[0].lat == pytest.approx(51.0776007, abs=1e-6)

    def test_gps5_fallback_when_gps9_missing(self):
        """Falls back to GPS5 if GPS9 is not found in stream."""
        gps5_strm = _make_klv(
            b"STRM",
            b"\x00",
            [
                _make_klv(
                    b"SCAL", b"l", [[10000000], [10000000], [1000], [1000], [100]]
                ),
                _make_klv(b"GPS5", b"l", [[343985866, -1196986334, -34141, 313, 50]]),
                _make_klv(b"GPSF", b"L", [[3]]),
            ],
        )
        points = gpmf_parser._find_first_gps_stream([gps5_strm])
        assert len(points) == 1
        assert points[0].lat == pytest.approx(34.3985866, abs=1e-7)
        assert points[0].lon == pytest.approx(-119.6986334, abs=1e-7)


# ---------------------------------------------------------------------------
# 8. _extract_camera_model_from_devices
# ---------------------------------------------------------------------------
class TestExtractCameraModelFromDevices:
    def test_empty_device_names(self):
        assert gpmf_parser._extract_camera_model_from_devices({}) == ""

    def test_single_device(self):
        result = gpmf_parser._extract_camera_model_from_devices({1: b"GoPro Max"})
        assert result == "GoPro Max"

    def test_hero_priority(self):
        """Device with 'hero' in the name gets higher priority."""
        result = gpmf_parser._extract_camera_model_from_devices(
            {
                1: b"GoPro Max",
                2: b"Hero7 Black",
            }
        )
        assert result == "Hero7 Black"

    def test_gopro_priority_over_other(self):
        """Device with 'gopro' gets priority if no 'hero' device."""
        result = gpmf_parser._extract_camera_model_from_devices(
            {
                1: b"SomeOtherCam",
                2: b"GoPro Fusion",
            }
        )
        assert result == "GoPro Fusion"

    def test_first_alphabetically_if_no_hero_or_gopro(self):
        result = gpmf_parser._extract_camera_model_from_devices(
            {
                1: b"ZCam",
                2: b"ACam",
            }
        )
        assert result == "ACam"

    def test_whitespace_stripped(self):
        result = gpmf_parser._extract_camera_model_from_devices(
            {
                1: b"  GoPro Max  ",
            }
        )
        assert result == "GoPro Max"

    def test_unicode_decode_error_skipped(self):
        """Devices with invalid UTF-8 names are skipped."""
        result = gpmf_parser._extract_camera_model_from_devices(
            {
                1: b"\xff\xfe",
                2: b"GoPro Max",
            }
        )
        assert result == "GoPro Max"

    def test_all_invalid_unicode(self):
        """All devices with invalid UTF-8 returns empty string."""
        result = gpmf_parser._extract_camera_model_from_devices(
            {
                1: b"\xff\xfe",
                2: b"\x80\x81",
            }
        )
        assert result == ""

    def test_hero_case_insensitive(self):
        result = gpmf_parser._extract_camera_model_from_devices(
            {
                1: b"MAX2",
                2: b"HERO12 Black",
            }
        )
        assert result == "HERO12 Black"

    def test_gopro_case_insensitive(self):
        result = gpmf_parser._extract_camera_model_from_devices(
            {
                1: b"SomeCam",
                2: b"GOPRO MAX",
            }
        )
        assert result == "GOPRO MAX"

    def test_real_max_model(self):
        """GoPro Max has 'GoPro Max' device name (contains 'gopro', not 'hero')."""
        result = gpmf_parser._extract_camera_model_from_devices({1: b"GoPro Max"})
        assert result == "GoPro Max"

    def test_real_max2_model(self):
        """MAX2 has no 'hero' or 'gopro' in the name."""
        result = gpmf_parser._extract_camera_model_from_devices({1: b"MAX2"})
        assert result == "MAX2"


# ---------------------------------------------------------------------------
# 9. _backfill_gps_timestamps
# ---------------------------------------------------------------------------
class TestBackfillGpsTimestamps:
    def _make_point(self, time, epoch_time=None):
        return telemetry.GPSPoint(
            time=time,
            lat=47.36,
            lon=8.52,
            alt=400.0,
            epoch_time=epoch_time,
            fix=telemetry.GPSFix.FIX_3D,
            precision=200,
            ground_speed=1.0,
            angle=None,
        )

    def test_all_have_epoch_time(self):
        """No backfilling needed when all points have epoch_time."""
        pts = [
            self._make_point(0.0, 1000.0),
            self._make_point(1.0, 1001.0),
            self._make_point(2.0, 1002.0),
        ]
        gpmf_parser._backfill_gps_timestamps(pts)
        assert pts[0].epoch_time == 1000.0
        assert pts[1].epoch_time == 1001.0
        assert pts[2].epoch_time == 1002.0

    def test_backfill_forward(self):
        """Points after the first with epoch_time get backfilled."""
        pts = [
            self._make_point(0.0, 1000.0),
            self._make_point(1.0, None),
            self._make_point(2.0, None),
        ]
        gpmf_parser._backfill_gps_timestamps(pts)
        assert pts[0].epoch_time == 1000.0
        assert pts[1].epoch_time == pytest.approx(1001.0)
        assert pts[2].epoch_time == pytest.approx(1002.0)

    def test_backfill_backward_with_reversed(self):
        """Backfill backward by calling with reversed()."""
        pts = [
            self._make_point(0.0, None),
            self._make_point(1.0, None),
            self._make_point(2.0, 1002.0),
        ]
        gpmf_parser._backfill_gps_timestamps(reversed(pts))
        assert pts[0].epoch_time == pytest.approx(1000.0)
        assert pts[1].epoch_time == pytest.approx(1001.0)
        assert pts[2].epoch_time == 1002.0

    def test_no_points_with_epoch_time(self):
        """No crash when no points have epoch_time."""
        pts = [
            self._make_point(0.0, None),
            self._make_point(1.0, None),
        ]
        gpmf_parser._backfill_gps_timestamps(pts)
        assert pts[0].epoch_time is None
        assert pts[1].epoch_time is None

    def test_empty_list(self):
        """No crash on empty list."""
        gpmf_parser._backfill_gps_timestamps([])

    def test_single_point_with_epoch(self):
        pts = [self._make_point(0.0, 1000.0)]
        gpmf_parser._backfill_gps_timestamps(pts)
        assert pts[0].epoch_time == 1000.0

    def test_single_point_without_epoch(self):
        pts = [self._make_point(0.0, None)]
        gpmf_parser._backfill_gps_timestamps(pts)
        assert pts[0].epoch_time is None

    def test_middle_point_has_epoch(self):
        """Only points after the first with epoch_time get filled (forward pass)."""
        pts = [
            self._make_point(0.0, None),
            self._make_point(1.0, 1001.0),
            self._make_point(2.0, None),
        ]
        gpmf_parser._backfill_gps_timestamps(pts)
        # Forward pass: only point after 1001 gets filled
        assert pts[0].epoch_time is None
        assert pts[1].epoch_time == 1001.0
        assert pts[2].epoch_time == pytest.approx(1002.0)

    def test_preserves_existing_epoch_times(self):
        """Points that already have epoch_time are not overwritten."""
        pts = [
            self._make_point(0.0, 1000.0),
            self._make_point(1.0, None),
            self._make_point(2.0, 1005.0),  # intentionally different
        ]
        gpmf_parser._backfill_gps_timestamps(pts)
        assert pts[2].epoch_time == 1005.0  # preserved, not overwritten


# ---------------------------------------------------------------------------
# 10. _build_matrix, _apply_matrix, _is_matrix_calibration
# ---------------------------------------------------------------------------
class TestMatrixOperations:
    def test_is_matrix_calibration_identity_like(self):
        """A matrix with only 0, 1, -1 values is NOT calibration."""
        assert gpmf_parser._is_matrix_calibration([1, 0, 0, 0, -1, 0, 0, 0, 1]) is False

    def test_is_matrix_calibration_actual(self):
        """A matrix with non-trivial values IS calibration."""
        assert (
            gpmf_parser._is_matrix_calibration([1.5, 0, 0, 0, -1, 0, 0, 0, 1]) is True
        )

    def test_is_matrix_calibration_all_zeros(self):
        assert gpmf_parser._is_matrix_calibration([0, 0, 0, 0, 0, 0, 0, 0, 0]) is False

    def test_build_matrix_identity(self):
        """ORIN='XYZ' ORIO='XYZ' should produce identity."""
        matrix = gpmf_parser._build_matrix(b"XYZ", b"XYZ")
        assert matrix == [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

    def test_build_matrix_swap_axes(self):
        """ORIN='YxZ' ORIO='ZXY' swaps and negates axes."""
        matrix = gpmf_parser._build_matrix(b"YxZ", b"ZXY")
        # Y -> ZXY: Y matches at index 2 -> [0, 0, 1]
        # x (lowercase) -> negate X -> [0, -1, 0]
        # Z -> ZXY: Z matches at index 0 -> [1, 0, 0]
        assert matrix == [0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 1.0, 0.0, 0.0]

    def test_build_matrix_negate_all(self):
        """ORIN='xyz' ORIO='XYZ' should produce -1 on diagonal."""
        matrix = gpmf_parser._build_matrix(b"xyz", b"XYZ")
        assert matrix == [-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0]

    def test_apply_matrix_identity(self):
        identity = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        values = [10.0, 20.0, 30.0]
        result = list(gpmf_parser._apply_matrix(identity, values))
        assert result == [10.0, 20.0, 30.0]

    def test_apply_matrix_negate_y(self):
        matrix = [1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0]
        values = [10.0, 20.0, 30.0]
        result = list(gpmf_parser._apply_matrix(matrix, values))
        assert result == [10.0, -20.0, 30.0]

    def test_apply_matrix_swap(self):
        matrix = [0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 1.0, 0.0, 0.0]
        values = [10.0, 20.0, 30.0]
        result = list(gpmf_parser._apply_matrix(matrix, values))
        assert result == [30.0, -20.0, 10.0]

    def test_apply_matrix_wrong_size_asserts(self):
        matrix = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]  # 6 elements, not 9
        with pytest.raises(AssertionError, match="square matrix"):
            list(gpmf_parser._apply_matrix(matrix, [10.0, 20.0, 30.0]))

    def test_apply_matrix_2d(self):
        """2x2 matrix multiplication."""
        matrix = [0.0, 1.0, 1.0, 0.0]  # swap
        values = [3.0, 7.0]
        result = list(gpmf_parser._apply_matrix(matrix, values))
        assert result == [7.0, 3.0]


# ---------------------------------------------------------------------------
# 11. _scale_and_calibrate
# ---------------------------------------------------------------------------
class TestScaleAndCalibrate:
    def test_basic_scaling(self):
        stream = [
            _make_klv(b"SCAL", b"s", [[100], [200], [300]]),
            _make_klv(b"ACCL", b"s", [[1000, 2000, 3000], [500, 600, 900]]),
        ]
        results = list(gpmf_parser._scale_and_calibrate(stream, b"ACCL"))
        assert len(results) == 2
        assert results[0] == pytest.approx((10.0, 10.0, 10.0))
        assert results[1] == pytest.approx((5.0, 3.0, 3.0))

    def test_single_scale_repeated(self):
        """Single SCAL value is repeated for all elements."""
        stream = [
            _make_klv(b"SCAL", b"s", [[100]]),
            _make_klv(b"GYRO", b"s", [[200, 400, 600]]),
        ]
        results = list(gpmf_parser._scale_and_calibrate(stream, b"GYRO"))
        assert len(results) == 1
        assert results[0] == pytest.approx((2.0, 4.0, 6.0))

    def test_missing_key_returns_empty(self):
        stream = [
            _make_klv(b"SCAL", b"s", [[100]]),
            _make_klv(b"ACCL", b"s", [[200, 300, 400]]),
        ]
        results = list(gpmf_parser._scale_and_calibrate(stream, b"GYRO"))
        assert results == []

    def test_with_orin_orio_matrix(self):
        """Matrix from ORIN/ORIO applied to scaled values."""
        stream = [
            _make_klv(b"SCAL", b"s", [[100], [100], [100]]),
            _make_klv(b"ACCL", b"s", [[1000, 2000, 3000]]),
            _make_klv(b"ORIN", b"c", [b"Y", b"x", b"Z"]),
            _make_klv(b"ORIO", b"c", [b"Z", b"X", b"Y"]),
        ]
        results = list(gpmf_parser._scale_and_calibrate(stream, b"ACCL"))
        assert len(results) == 1
        # ORIN=YxZ, ORIO=ZXY -> matrix=[0,0,1, 0,-1,0, 1,0,0]
        # scaled = [10, 20, 30]
        # matrix * scaled = [30, -20, 10]
        assert results[0] == pytest.approx((30.0, -20.0, 10.0))

    def test_zero_scal_replaced_with_one(self):
        """Zero SCAL values should be replaced with 1 to avoid division by zero."""
        stream = [
            _make_klv(b"SCAL", b"s", [[0], [100], [0]]),
            _make_klv(b"ACCL", b"s", [[500, 1000, 300]]),
        ]
        results = list(gpmf_parser._scale_and_calibrate(stream, b"ACCL"))
        assert len(results) == 1
        # 0 replaced with 1, so: 500/1=500, 1000/100=10, 300/1=300
        assert results[0] == pytest.approx((500.0, 10.0, 300.0))


# ---------------------------------------------------------------------------
# 12. KLV parsing basics (existing test expanded)
# ---------------------------------------------------------------------------
class TestKLVParsing:
    def test_simple_klv(self):
        x = gpmf_parser.KLV.parse(b"DEMO\x02\x01\x00\x01\xff\x00\x00\x00")
        assert x["key"] == b"DEMO"

    def test_gpmf_sample_data(self):
        x = gpmf_parser.GPMFSampleData.parse(
            b"DEM1\x01\x01\x00\x01\xff\x00\x00\x00DEM2\x03\x00\x00\x01"
        )
        assert len(x) == 2
        assert x[0]["key"] == b"DEM1"
        assert x[1]["key"] == b"DEM2"


# ---------------------------------------------------------------------------
# 13. GoProInfo dataclass defaults
# ---------------------------------------------------------------------------
class TestGoProInfo:
    def test_defaults(self):
        info = gpmf_parser.GoProInfo()
        assert info.gps is None
        assert info.accl is None
        assert info.gyro is None
        assert info.magn is None
        assert info.make == "GoPro"
        assert info.model == ""


# ============================================================================
# INTEGRATION TESTS (require real test data files)
# ============================================================================


# ---------------------------------------------------------------------------
# 14. extract_gopro_info with GPS5 file (GoPro MAX)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _has_gps5_video, reason="GPS5 test data not available")
class TestExtractGoProInfoGPS5:
    def test_basic_extraction(self):
        with open(GPS5_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        assert info is not None
        assert info.make == "GoPro"
        assert info.model == "GoPro Max"

    def test_gps_count(self):
        with open(GPS5_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        assert info.gps is not None
        assert len(info.gps) == 1737

    def test_first_gps_point(self):
        with open(GPS5_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        p = info.gps[0]
        assert p.lat == pytest.approx(47.3598318, abs=1e-6)
        assert p.lon == pytest.approx(8.5227055, abs=1e-6)
        assert p.alt == pytest.approx(414.87, abs=0.1)
        assert p.fix == telemetry.GPSFix.FIX_3D
        assert p.precision == 219
        assert p.ground_speed == pytest.approx(0.891, abs=0.01)

    def test_epoch_time_backfilled(self):
        """All GPS points should have epoch_time after backfilling."""
        with open(GPS5_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        for p in info.gps:
            assert p.epoch_time is not None

    def test_telemetry_not_extracted_by_default(self):
        """By default (telemetry_only=False), ACCL/GYRO/MAGN are None."""
        with open(GPS5_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        assert info.accl is None
        assert info.gyro is None
        assert info.magn is None


# ---------------------------------------------------------------------------
# 15. extract_gopro_info with GPS9 file (GoPro MAX 2)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _has_gps9_video, reason="GPS9 test data not available")
class TestExtractGoProInfoGPS9:
    def test_basic_extraction(self):
        with open(GPS9_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        assert info is not None
        assert info.make == "GoPro"
        assert info.model == "MAX2"

    def test_gps_count(self):
        with open(GPS9_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        assert info.gps is not None
        assert len(info.gps) == 267

    def test_first_gps_point(self):
        with open(GPS9_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        p = info.gps[0]
        assert p.lat == pytest.approx(51.0776007, abs=1e-5)
        assert p.lon == pytest.approx(6.2268453, abs=1e-5)
        assert p.alt == pytest.approx(85.454, abs=0.1)
        assert p.fix == telemetry.GPSFix.FIX_3D
        assert p.precision == pytest.approx(185.0, abs=1.0)

    def test_epoch_time_backfilled(self):
        with open(GPS9_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        for p in info.gps:
            assert p.epoch_time is not None


# ---------------------------------------------------------------------------
# 16. extract_gopro_info with telemetry_only mode
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _has_hero7_video, reason="Hero7 test data not available")
class TestExtractGoProInfoTelemetryOnly:
    def test_telemetry_only_no_gps(self):
        """In telemetry_only mode, GPS is None."""
        with open(HERO7_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f, telemetry_only=True)
        assert info is not None
        assert info.gps is None

    def test_telemetry_only_no_model(self):
        """In telemetry_only mode, model is not extracted."""
        with open(HERO7_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f, telemetry_only=True)
        assert info.model == ""

    def test_telemetry_only_has_accl(self):
        with open(HERO7_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f, telemetry_only=True)
        assert info.accl is not None
        assert len(info.accl) == 103806

    def test_telemetry_only_has_gyro(self):
        with open(HERO7_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f, telemetry_only=True)
        assert info.gyro is not None
        assert len(info.gyro) == 103806

    def test_telemetry_only_first_accl_values(self):
        with open(HERO7_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f, telemetry_only=True)
        a = info.accl[0]
        assert a.x == pytest.approx(1.672, abs=0.01)
        assert a.y == pytest.approx(5.175, abs=0.01)
        assert a.z == pytest.approx(11.022, abs=0.01)

    def test_telemetry_only_first_gyro_values(self):
        with open(HERO7_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f, telemetry_only=True)
        g = info.gyro[0]
        assert g.x == pytest.approx(0.121, abs=0.01)
        assert g.y == pytest.approx(0.896, abs=0.01)
        assert g.z == pytest.approx(0.165, abs=0.01)


# ---------------------------------------------------------------------------
# 17. extract_gopro_info normal mode with Hero 7
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _has_hero7_video, reason="Hero7 test data not available")
class TestExtractGoProInfoHero7:
    def test_model_is_hero7(self):
        with open(HERO7_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        assert info is not None
        assert info.model == "Hero7 Black"

    def test_gps_count(self):
        with open(HERO7_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        assert info.gps is not None
        assert len(info.gps) == 2435

    def test_first_gps_point(self):
        with open(HERO7_VIDEO, "rb") as f:
            info = gpmf_parser.extract_gopro_info(f)
        p = info.gps[0]
        assert p.lat == pytest.approx(34.3985866, abs=1e-5)
        assert p.lon == pytest.approx(-119.6986334, abs=1e-5)
        assert p.alt == pytest.approx(-34.141, abs=0.1)
        assert p.fix == telemetry.GPSFix.FIX_3D
        assert p.ground_speed == pytest.approx(0.313, abs=0.01)


# ---------------------------------------------------------------------------
# 18. _flatten helper
# ---------------------------------------------------------------------------
class TestFlatten:
    def test_basic(self):
        assert gpmf_parser._flatten([[1, 2], [3, 4]]) == [1, 2, 3, 4]

    def test_single_row(self):
        assert gpmf_parser._flatten([[5, 6, 7]]) == [5, 6, 7]

    def test_empty(self):
        assert gpmf_parser._flatten([]) == []
