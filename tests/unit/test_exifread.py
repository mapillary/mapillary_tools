import datetime
import os

import typing as T
from pathlib import Path

import py.path

import pytest
from mapillary_tools import geo

from mapillary_tools.exif_read import (
    _parse_coord,
    ExifRead,
    parse_datetimestr_with_subsec_and_offset,
)
from mapillary_tools.exif_write import ExifEdit

"""Initialize all the neccessary data"""

this_file = os.path.abspath(__file__)
this_file_dir = os.path.dirname(this_file)
data_dir = os.path.join(this_file_dir, "data")

TEST_EXIF_FILE = Path(os.path.join(data_dir, "test_exif.jpg"))


@pytest.fixture
def setup_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(data_dir)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


def gps_to_decimal(value, ref):
    sign = 1 if ref in "NE" else -1
    degrees, minutes, seconds = value
    return sign * (float(degrees) + float(minutes) / 60 + float(seconds) / 3600)


def test_read_orientation_general():
    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    orientation_ExifRead = exif_data_ExifRead.extract_orientation()
    assert 2 == orientation_ExifRead


def test_read_date_time_original_general():
    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    capture_time_ExifRead = exif_data_ExifRead.extract_capture_time()
    # exiftool -time:all tests/unit/data/test_exif.jpg
    # Date/Time Original              : 2018:06:26 17:46:33.847
    # Create Date                     : 2011:07:15 11:14:39
    # Sub Sec Time                    : 000005
    # GPS Time Stamp                  : 09:14:39
    # GPS Date Stamp                  : 2011:07:15
    # GPS Date/Time                   : 2011:07:15 09:14:39Z
    assert (
        datetime.datetime.fromisoformat("2011-07-15T09:14:39+00:00")
        == capture_time_ExifRead
    )
    # note it is not: datetime.datetime.fromisoformat("2018-06-26T17:46:33.000005") == capture_time_ExifRead
    # because "Sub Sec Time" is not subsec for "Date/Time Original"


def test_read_lat_lon_general():
    latitude_PIL, latitudeRef_PIL = (35.0, 54.0, 45.06), "N"
    longitude_PIL, longitudeRef_PIL = (14.0, 29.0, 55.7), "E"

    latitude_PIL = gps_to_decimal(latitude_PIL, latitudeRef_PIL)
    longitude_PIL = gps_to_decimal(longitude_PIL, longitudeRef_PIL)

    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    lonlat = exif_data_ExifRead.extract_lon_lat()
    assert lonlat
    longitude_ExifRead, latitude_ExifRead = lonlat

    assert (latitude_PIL, longitude_PIL) == (latitude_ExifRead, longitude_ExifRead)


def test_read_camera_make_model_general():
    make_PIL = "HTC"
    model_PIL = "Legend"

    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    make_ExifRead = exif_data_ExifRead.extract_make()
    model_ExifRead = exif_data_ExifRead.extract_model()

    assert (make_PIL, model_PIL) == (make_ExifRead, model_ExifRead)


def test_read_altitude_general():
    numerator = 69
    denominator = 1

    altitude_value_PIL = numerator / denominator

    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    altitude_ExifRead = exif_data_ExifRead.extract_altitude()

    assert altitude_value_PIL == altitude_ExifRead


def test_read_direction_general():
    numerator = 100
    denominator = 100
    direction_value_PIL = numerator / denominator

    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    direction_ExifRead = exif_data_ExifRead.extract_direction()

    assert direction_value_PIL == direction_ExifRead


def test_parse():
    dt = parse_datetimestr_with_subsec_and_offset("2019:02:01 12:13:14")
    assert dt
    assert dt.tzinfo is None
    assert dt.timetuple() == (2019, 2, 1, 12, 13, 14, 4, 32, -1)

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:03:03 23:00:00.123", "456", "+12:12:11"
    )
    assert str(dt) == "2019-03-03 23:00:00.456000+12:12:11"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 22:00:00.123", "1456", "+12:34"
    )
    assert str(dt) == "2019-01-01 22:00:00.145600+12:34"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 22:00:00.123", "0456", "+12:34"
    )
    assert str(dt) == "2019-01-01 22:00:00.045600+12:34"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 01:00:00.123456789", None, "-10:34"
    )
    assert str(dt) == "2019-01-01 01:00:00.123457-10:34"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 01:00:00.123456789", None, "-24:00"
    )
    assert str(dt) == "2019-01-01 01:00:00.123457+00:00"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 01:00:00.123456789", None, "24:00"
    )
    assert str(dt) == "2019-01-01 01:00:00.123457+00:00"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 01:00:00.123456789", None, "24:23"
    )
    assert str(dt) == "2019-01-01 01:00:00.123457+00:23"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 24:00:00.123456789", None, "24:23"
    )
    assert str(dt) == "2019-01-02 00:00:00.123457+00:23"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 24:88:00.123456789", None, "-24:23"
    )
    assert str(dt) == "2019-01-02 01:28:00.123457-00:23"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.123456Z",
    )
    assert str(dt) == "2019-01-01 12:22:00.123456+00:00", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.123456+11:00",
    )
    assert str(dt) == "2019-01-01 12:22:00.123456+11:00", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.456789+11:00", "123", "+01:00"
    )
    assert str(dt) == "2019-01-01 12:22:00.123000+01:00", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.123456",
    )
    assert str(dt) == "2019-01-01 12:22:00.123456", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.123",
    )
    assert str(dt) == "2019-01-01 12:22:00.123000", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2021:10:10 17:29:54.124+02:00",
    )
    assert str(dt) == "2021-10-10 17:29:54.124000+02:00", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2021:10:10 17:29:54.124-02:00",
    )
    assert str(dt) == "2021-10-10 17:29:54.124000-02:00", dt


@pytest.mark.parametrize(
    "raw_coord,raw_ref,expected",
    [
        (None, "", None),
        ("foo", "N", None),
        ("0.0", "foo", None),
        ("0.0", "N", 0),
        ("1.5", "N", 1.5),
        ("1.5", "S", -1.5),
        ("-1.5", "N", -1.5),
        ("-1.5", "S", 1.5),
        ("-1.5", "S", 1.5),
        ("33,18.32N", "N", 33.30533),
        ("33,18.32N", "S", 33.30533),
        ("33,18.32S", "", -33.30533),
        ("44,24.54E", "", 44.40900),
        ("44,24.54W", "", -44.40900),
    ],
)
def test_parse_coordinates(
    raw_coord: T.Optional[str], raw_ref: str, expected: T.Optional[float]
):
    assert _parse_coord(raw_coord, raw_ref) == pytest.approx(expected)


# test ExifWrite write a timestamp and ExifRead read it back
def test_read_and_write(setup_data: py.path.local):
    image_path = Path(setup_data, "test_exif.jpg")
    dts = [
        datetime.datetime.now(),
        datetime.datetime.now(datetime.timezone.utc),
        # 86400 is total seconds of one day (24 * 3600)
        # to avoid "OSError: [Errno 22] Invalid argument" in WINDOWS https://bugs.python.org/issue36759
        datetime.datetime.fromtimestamp(86400),
        datetime.datetime.fromtimestamp(86400, tz=datetime.timezone.utc),
        datetime.datetime.fromtimestamp(86400.0000001, tz=datetime.timezone.utc),
        datetime.datetime.fromtimestamp(86400.123456, tz=datetime.timezone.utc),
        datetime.datetime.fromtimestamp(86400.0123, tz=datetime.timezone.utc),
    ]
    dts = dts[:] + [dt.astimezone() for dt in dts]
    dts = dts[:] + [dt.astimezone(datetime.timezone.utc) for dt in dts]

    for dt in dts:
        edit = ExifEdit(image_path)
        edit.add_gps_datetime(dt)
        edit.add_date_time_original(dt)
        edit.write()
        read = ExifRead(image_path)
        actual = read.extract_capture_time()
        assert actual
        assert geo.as_unix_time(dt) == geo.as_unix_time(actual), (dt, actual)

    for dt in dts:
        edit = ExifEdit(image_path)
        edit.add_gps_datetime(dt)
        edit.write()
        read = ExifRead(image_path)
        actual = read.extract_gps_datetime()
        assert actual
        assert geo.as_unix_time(dt) == geo.as_unix_time(actual)
