import datetime
import os
import unittest
from pathlib import Path

import py.path

import pytest

from mapillary_tools.exif_read import ExifRead, parse_datetimestr
from mapillary_tools.exif_write import ExifEdit
from PIL import ExifTags, Image

"""Initialize all the neccessary data"""

this_file = os.path.abspath(__file__)
this_file_dir = os.path.dirname(this_file)
data_dir = os.path.join(this_file_dir, "data")

TEST_EXIF_FILE = Path(os.path.join(data_dir, "test_exif.jpg"))

# more info on the standard exif tags
# https://sno.phy.queensu.ca/~phil/exiftool/TagNames/EXIF.html
EXIF_PRIMARY_TAGS_DICT = {y: x for x, y in ExifTags.TAGS.items()}
EXIF_GPS_TAGS_DICT = {y: x for x, y in ExifTags.GPSTAGS.items()}


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


def load_exif_PIL(filename=TEST_EXIF_FILE):
    test_image = Image.open(filename)
    return test_image.getexif()


def read_orientation_general(test_obj, filename: Path):
    exif_data_PIL = load_exif_PIL()
    orientation_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT["Orientation"]]

    exif_data_ExifRead = ExifRead(filename)
    orientation_ExifRead = exif_data_ExifRead.extract_orientation()

    test_obj.assertEqual(orientation_PIL, orientation_ExifRead)


def read_date_time_original_general(test_obj, filename: Path):
    exif_data_ExifRead = ExifRead(filename)
    capture_time_ExifRead = exif_data_ExifRead.extract_capture_time()
    assert capture_time_ExifRead is not None
    capture_time = capture_time_ExifRead.strftime("%Y:%m:%d %H:%M:%S.%f")[:-3]
    test_obj.assertEqual("2011:07:15 09:14:39.000", capture_time)


def read_lat_lon_general(test_obj, filename: Path):
    exif_data_PIL = load_exif_PIL()
    latitude_PIL = exif_data_PIL.get_ifd(EXIF_PRIMARY_TAGS_DICT["GPSInfo"])[
        EXIF_GPS_TAGS_DICT["GPSLatitude"]
    ]
    longitude_PIL = exif_data_PIL.get_ifd(EXIF_PRIMARY_TAGS_DICT["GPSInfo"])[
        EXIF_GPS_TAGS_DICT["GPSLongitude"]
    ]
    latitudeRef_PIL = exif_data_PIL.get_ifd(EXIF_PRIMARY_TAGS_DICT["GPSInfo"])[
        EXIF_GPS_TAGS_DICT["GPSLatitudeRef"]
    ]
    longitudeRef_PIL = exif_data_PIL.get_ifd(EXIF_PRIMARY_TAGS_DICT["GPSInfo"])[
        EXIF_GPS_TAGS_DICT["GPSLongitudeRef"]
    ]

    latitude_PIL = gps_to_decimal(latitude_PIL, latitudeRef_PIL)
    longitude_PIL = gps_to_decimal(longitude_PIL, longitudeRef_PIL)

    exif_data_ExifRead = ExifRead(filename)
    lonlat = exif_data_ExifRead.extract_lon_lat()
    assert lonlat
    longitude_ExifRead, latitude_ExifRead = lonlat

    test_obj.assertEqual(
        (latitude_PIL, longitude_PIL), (latitude_ExifRead, longitude_ExifRead)
    )


def read_camera_make_model_general(test_obj, filename: Path):
    exif_data_PIL = load_exif_PIL()
    make_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT["Make"]]
    model_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT["Model"]]

    exif_data_ExifRead = ExifRead(filename)
    make_ExifRead = exif_data_ExifRead.extract_make()
    model_ExifRead = exif_data_ExifRead.extract_model()

    test_obj.assertEqual((make_PIL, model_PIL), (make_ExifRead, model_ExifRead))


def read_altitude_general(test_obj, filename: Path):
    exif_data_PIL = load_exif_PIL()
    altitude_PIL = exif_data_PIL.get_ifd(EXIF_PRIMARY_TAGS_DICT["GPSInfo"])[
        EXIF_GPS_TAGS_DICT["GPSAltitude"]
    ]
    altitude_value_PIL = altitude_PIL.numerator / altitude_PIL.denominator

    exif_data_ExifRead = ExifRead(filename)
    altitude_ExifRead = exif_data_ExifRead.extract_altitude()

    test_obj.assertEqual(altitude_value_PIL, altitude_ExifRead)


def read_direction_general(test_obj, filename: Path):
    exif_data_PIL = load_exif_PIL()
    direction_PIL = exif_data_PIL.get_ifd(EXIF_PRIMARY_TAGS_DICT["GPSInfo"])[
        EXIF_GPS_TAGS_DICT["GPSImgDirection"]
    ]
    direction_value_PIL = direction_PIL.numerator / direction_PIL.denominator

    exif_data_ExifRead = ExifRead(filename)
    direction_ExifRead = exif_data_ExifRead.extract_direction()

    test_obj.assertEqual(direction_value_PIL, direction_ExifRead)


class ExifReadTests(unittest.TestCase):
    """tests for main functions."""

    def test_read_orientation(self):
        read_orientation_general(self, TEST_EXIF_FILE)

    def test_read_date_time_original(self):
        read_date_time_original_general(self, TEST_EXIF_FILE)

    def test_read_lat_lon(self):
        read_lat_lon_general(self, TEST_EXIF_FILE)

    def test_read_camera_make_model(self):
        read_camera_make_model_general(self, TEST_EXIF_FILE)

    def test_read_altitude(self):
        read_altitude_general(self, TEST_EXIF_FILE)

    def test_read_direction(self):
        read_direction_general(self, TEST_EXIF_FILE)


def test_parse():
    dt = parse_datetimestr("2019:02:01 12:13:14")
    assert dt
    assert dt.tzinfo is None
    assert dt.timetuple() == (2019, 2, 1, 12, 13, 14, 4, 32, -1)

    dt = parse_datetimestr("2019:03:03 23:00:00.123", "456", "+12:12:11")
    assert str(dt) == "2019-03-03 23:00:00.456000+12:12:11"

    dt = parse_datetimestr("2019:01:01 22:00:00.123", "1456", "+12:34")
    assert str(dt) == "2019-01-01 22:00:00.145600+12:34"

    dt = parse_datetimestr("2019:01:01 22:00:00.123", "0456", "+12:34")
    assert str(dt) == "2019-01-01 22:00:00.045600+12:34"

    dt = parse_datetimestr("2019:01:01 01:00:00.123456789", None, "-10:34")
    assert str(dt) == "2019-01-01 01:00:00.123457-10:34"

    dt = parse_datetimestr("2019:01:01 01:00:00.123456789", None, "-24:00")
    assert str(dt) == "2019-01-01 01:00:00.123457+00:00"

    dt = parse_datetimestr("2019:01:01 01:00:00.123456789", None, "24:00")
    assert str(dt) == "2019-01-01 01:00:00.123457+00:00"

    dt = parse_datetimestr("2019:01:01 01:00:00.123456789", None, "24:23")
    assert str(dt) == "2019-01-01 01:00:00.123457+00:23"

    dt = parse_datetimestr("2019:01:01 24:00:00.123456789", None, "24:23")
    assert str(dt) == "2019-01-02 00:00:00.123457+00:23"

    dt = parse_datetimestr("2019:01:01 24:88:00.123456789", None, "-24:23")
    assert str(dt) == "2019-01-02 01:28:00.123457-00:23"


# test ExifWrite write a timestamp and ExifRead read it back
def test_read_and_write(setup_data: py.path.local):
    image_path = Path(setup_data, "test_exif.jpg")
    dts = [
        datetime.datetime.now(),
        datetime.datetime.utcnow(),
        datetime.datetime.fromtimestamp(0),
        datetime.datetime.utcfromtimestamp(0),
        datetime.datetime.utcfromtimestamp(0),
        datetime.datetime.utcfromtimestamp(0.0000001),
        datetime.datetime.utcfromtimestamp(0.123456),
        datetime.datetime.utcfromtimestamp(0.0123),
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
        assert dt.astimezone(datetime.timezone.utc) == actual

    for dt in dts:
        edit = ExifEdit(image_path)
        edit.add_gps_datetime(dt)
        edit.write()
        read = ExifRead(image_path)
        actual = read.extract_gps_datetime()
        assert dt.astimezone(datetime.timezone.utc) == actual
