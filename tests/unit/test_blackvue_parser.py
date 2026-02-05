# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import io

import mapillary_tools.geo as geo
from mapillary_tools import blackvue_parser, telemetry
from mapillary_tools.mp4 import construct_mp4_parser as cparser


def test_parse_points():
    gps_data = b"""
[1623057130221]$GPGGA,201205.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6F

[1623057129253]$GPGGA,201204.00,3853.16945,N,07659.54371,W,2,10,0.99,10.2,M,-34.7,M,,0000*5C

[1623057129253]$GPGSA,A,3,19,02,06,12,17,09,05,20,04,25,,,1.83,0.99,1.54*0C

[1623057129253]$GPGSV,3,1,12,02,67,331,39,04,08,040,21,05,28,214,30,06,53,047,31*71

[1623057129253]$GPGSV,3,2,12,09,23,071,28,12,48,268,41,17,17,124,26,19,38,117,35*78

[1623057129253]$GPGSV,3,3,12,20,23,221,35,25,26,307,39,46,20,244,35,51,35,223,40*72

[1623057129255]$GPGLL,3853.16945,N,07659.54371,W,201204.00,A,D*70

[1623057129256]$GPRMC,201205.00,A,3853.16949,N,07659.54604,W,5.849,284.43,070621,,,D*76

[1623057129257]$GPVTG,284.43,T,,M,5.849,N,10.833,K,D*08[1623057130221]

[1623057130258]$GPGGA,201205.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6F

[1623057132256]$GPRMC,201208.00,A,3853.16949,N,07659.54604,W,5.849,284.43,070621,,,D*7B

# invalid line
[1623057130221]$GPGGA,**&^%$%$&(&(*(&&(^^*^*^^*&^&*))))

# invalid line
[1623057130221]$GPGGA,\x00\x00\x1c\xff

[1623057130221]$GPGSA,A,3,19,02,06,12,17,09,05,20,04,25,,,1.65,0.82,1.43*08
    """

    box = {"type": b"free", "data": [{"type": b"gps ", "data": gps_data}]}
    data = cparser.Box32ConstructBuilder({b"free": {}}).Box.build(box)
    info = blackvue_parser.extract_blackvue_info(io.BytesIO(data))
    assert info == blackvue_parser.BlackVueInfo(
        gps=[
            telemetry.GPSPoint(
                time=0.0,
                lat=38.88615816666667,
                lon=-76.992434,
                alt=None,
                angle=None,
                epoch_time=1623096725,
                fix=None,
                precision=None,
                ground_speed=None,
            ),
            telemetry.GPSPoint(
                time=3.0,
                lat=38.88615816666667,
                lon=-76.992434,
                alt=None,
                angle=None,
                epoch_time=1623096728,
                fix=None,
                precision=None,
                ground_speed=None,
            ),
        ],
        make="BlackVue",
        model="",
    )


def test_gpspoint_gga():
    gps_data = b"[1623057074211]$GPGGA,202530.25,5109.0262,N,11401.8407,W,5,40,0.5,1097.36,M,-17.00,M,18,TSTR*66"
    points = blackvue_parser._parse_gps_box(gps_data)

    assert len(points) == 1
    point = points[0]
    assert point.time == 1623097530.25
    assert point.lat == 51.150436666666664
    assert point.lon == -114.03067833333333
    assert point.epoch_time == 1623097530.25
    assert point.fix == telemetry.GPSFix.FIX_3D


def test_gpspoint_gll():
    gps_data = b"[1629874404069]$GNGLL,4404.14012,N,12118.85993,W,001037.00,A,A*67"
    points = blackvue_parser._parse_gps_box(gps_data)

    assert len(points) == 1
    point = points[0]
    assert point.time == 1629850237
    assert point.lat == 44.069002
    assert point.lon == -121.31433216666667
    assert point.epoch_time == 1629850237


def test_timezone_offset_from_rmc():
    """
    Test timezone correction when camera clock is in local time (GMT-3).

    Camera epoch: 1637762688000 ms = 2021-11-24 14:04:48 (local time)
    RMC GPS time: 11:04:48 on 2021-11-24 UTC (correct UTC from satellites)
    Expected offset: 3 hours = 10800 seconds
    Corrected epoch: 1637762688 - 10800 = 1637751888 = 2021-11-24 11:04:48 UTC
    """
    # Camera shows 14:04:48 local, GPS shows 11:04:48 UTC -> 3 hour offset (GMT+3)
    gps_data = b"[1637762688000]$GPRMC,110448.65,A,3853.16949,N,07659.54604,W,5.849,284.43,241121,,,D*7E"
    points = blackvue_parser._parse_gps_box(gps_data)

    assert len(points) == 1
    point = points[0]
    expected_epoch = 1637751888.65
    assert point.time == expected_epoch
    assert point.epoch_time == expected_epoch


def test_timezone_offset_applied_to_all_points():
    """
    Test that the same timezone offset is applied to all GPS points.
    """
    # Two RMC messages with 1 second apart in camera time
    # Camera is 3 hours ahead (GMT+3), GPS shows correct UTC
    gps_data = b"""
[1637762688000]$GPRMC,110448.00,A,3853.16949,N,07659.54604,W,5.849,284.43,241121,,,D*7D

[1637762689000]$GPRMC,110449.00,A,3853.16950,N,07659.54605,W,5.850,284.44,241121,,,D*7A
    """
    points = blackvue_parser._parse_gps_box(gps_data)

    assert len(points) == 2
    # Both points should have 10800s subtracted
    assert points[0].time == 1637751888
    assert points[1].time == 1637751889
    # Time difference between points should be preserved
    assert points[1].time - points[0].time == 1.0


def test_timezone_offset_zero_when_clock_correct():
    """
    Test that no offset is applied when camera clock matches GPS time.
    """
    # Camera epoch matches GPS time
    # epoch 1623057125000 = 2021-06-07 09:12:05 UTC
    gps_data = b"[1623057125000]$GPRMC,091205.00,A,3853.16949,N,07659.54604,W,5.849,284.43,070621,,,D*7D"
    points = blackvue_parser._parse_gps_box(gps_data)

    assert len(points) == 1
    point = points[0]
    assert point.time == 1623057125.0
    assert point.epoch_time == 1623057125.0


def test_timezone_offset_fallback_gga():
    """
    Test timezone correction fallback using GGA when no RMC is available.

    Uses time-only correction with day boundary handling.
    """
    # Camera shows 14:04:48 local, GGA shows 11:04:48 UTC -> 3 hour offset
    # No RMC message, so fallback to GGA
    gps_data = b"[1637762688000]$GPGGA,110448.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*63"
    points = blackvue_parser._parse_gps_box(gps_data)

    assert len(points) == 1
    point = points[0]
    expected_epoch = 1637751888
    assert point.time == expected_epoch
    assert point.epoch_time == expected_epoch


def test_gga_day_boundary_nmea_next_day():
    """
    Test GGA day boundary: NMEA time is on the next day relative to camera.

    Scenario: Camera is in a negative timezone (e.g., GMT-2).
    Camera epoch: 1637794800 = 2021-11-24 23:00:00 (local time)
    GGA GPS time: 01:00:00 (correct UTC, next day = 2021-11-25 01:00:00)
    """
    gps_data = b"[1637794800000]$GPGGA,010000.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6A"
    points = blackvue_parser._parse_gps_box(gps_data)

    assert len(points) == 1
    expected_epoch = 1637802000
    assert points[0].time == expected_epoch


def test_gga_day_boundary_nmea_previous_day():
    """
    Test GGA day boundary: NMEA time is on the previous day relative to camera.

    Scenario: Camera is in a positive timezone (e.g., GMT+2).
    Camera epoch: 1637802000 = 2021-11-25 01:00:00 (local time)
    GGA GPS time: 23:00:00 (correct UTC, prev day = 2021-11-24 23:00:00)
    """
    gps_data = b"[1637802000000]$GPGGA,230000.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6A"
    points = blackvue_parser._parse_gps_box(gps_data)

    assert len(points) == 1
    expected_epoch = 1637794800
    assert points[0].time == expected_epoch


def test_gga_no_day_boundary_within_12_hours():
    """
    Test GGA with time difference within 12 hours - no day boundary adjustment.

    Camera is in GMT-3. Camera shows 14:00 local, actual UTC is 11:00 (same day).
    """
    # epoch 1637751600 = 2021-11-24 11:00:00 UTC
    # But camera clock shows 14:00 local, stored as epoch for 14:00 UTC = 1637762400
    gps_data = b"[1637762400000]$GPGGA,110000.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6B"
    points = blackvue_parser._parse_gps_box(gps_data)

    assert len(points) == 1
    # 3 hour offset between 11:00 and 14:00 -> no day adjustment
    expected_epoch = 1637762400.0 - 10800.0
    assert points[0].time == expected_epoch
