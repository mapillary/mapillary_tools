import datetime
import os
import shutil
import unittest
from pathlib import Path

import py.path

from mapillary_tools.exif_read import ExifRead
from mapillary_tools.exif_write import ExifEdit

this_file = Path(__file__)
this_file_dir = this_file.parent
data_dir = this_file_dir.joinpath("data")

EMPTY_EXIF_FILE = data_dir.joinpath("empty_exif.jpg")
EMPTY_EXIF_FILE_TEST = data_dir.joinpath(data_dir, "tmp", "empty_exif.jpg")
NON_EXISTING_FILE = data_dir.joinpath("tmp", "non_existing_file.jpg")
CORRUPT_EXIF_FILE = data_dir.joinpath("corrupt_exif.jpg")
CORRUPT_EXIF_FILE_2 = data_dir.joinpath("corrupt_exif_2.jpg")
FIXED_EXIF_FILE = data_dir.joinpath("fixed_exif.jpg")
FIXED_EXIF_FILE_2 = data_dir.joinpath("fixed_exif_2.jpg")


def add_image_description_general(_test_obj, filename):
    test_dictionary = {
        "key_numeric": 1,
        "key_string": "one",
        "key_list": [1, 2],
        "key_dict": {"key_dict1": 1, "key_dict2": 2},
    }

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_image_description(test_dictionary)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    _exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)


def add_orientation_general(test_obj, filename: Path):
    test_orientation = 2

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_orientation(test_orientation)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)
    orientation = exif_data.extract_orientation()
    test_obj.assertEqual(test_orientation, orientation)


def add_date_time_original_general(test_obj, filename: Path):
    test_datetime = datetime.datetime(2016, 8, 31, 8, 29, 26, 249000)

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_date_time_original(test_datetime)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)
    dt = exif_data.extract_exif_datetime()

    test_obj.assertEqual(test_datetime, dt)


def add_lat_lon_general(test_obj, filename):
    test_latitude = 50.5475894785
    test_longitude = 15.595866685
    precision = 1e7

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_lat_lon(test_latitude, test_longitude, precision)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)

    test_obj.assertEqual((test_longitude, test_latitude), exif_data.extract_lon_lat())


def add_altitude_general(test_obj, filename: Path):
    test_altitude = 15.5
    test_altitude_precision = 100

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_altitude(test_altitude, test_altitude_precision)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)
    test_obj.assertEqual(test_altitude, exif_data.extract_altitude())


def add_repeatedly_time_original_general(test_obj, filename):
    test_datetime = datetime.datetime(2016, 8, 31, 8, 29, 26, 249000)

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_date_time_original(test_datetime)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    test_datetime = datetime.datetime(2016, 9, 30, 8, 29, 26, 249000)

    not_empty_exifedit = ExifEdit(filename)

    not_empty_exifedit.add_date_time_original(test_datetime)
    not_empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)
    test_obj.assertEqual(
        test_datetime,
        exif_data.extract_exif_datetime(),
    )


def add_direction_general(test_obj, filename):
    test_direction = 1
    test_direction_ref = "T"
    test_direction_precision = 100

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_direction(
        test_direction, test_direction_ref, test_direction_precision
    )
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)
    test_obj.assertEqual(
        test_direction,
        exif_data.extract_orientation(),
    )


class ExifEditTests(unittest.TestCase):
    """tests for main functions."""

    def setUp(self):
        if not os.path.exists(os.path.join(data_dir, "tmp")):
            os.makedirs(os.path.join(data_dir, "tmp"))
        shutil.copy2(EMPTY_EXIF_FILE, EMPTY_EXIF_FILE_TEST)

    def tearDown(self):
        shutil.rmtree(os.path.join(data_dir, "tmp"))

    def test_add_image_description(self):
        add_image_description_general(self, EMPTY_EXIF_FILE_TEST)

    def test_add_orientation(self):
        add_orientation_general(self, EMPTY_EXIF_FILE_TEST)

    def test_add_date_time_original(self):
        add_date_time_original_general(self, EMPTY_EXIF_FILE_TEST)

    def test_add_lat_lon(self):
        add_lat_lon_general(self, EMPTY_EXIF_FILE_TEST)

    def test_add_altitude(self):
        add_altitude_general(self, EMPTY_EXIF_FILE_TEST)

    def test_add_direction(self):
        add_direction_general(self, EMPTY_EXIF_FILE_TEST)

    def test_write_to_non_existing_file(self):
        test_datetime = datetime.datetime(2016, 8, 31, 8, 29, 26, 249000)

        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)

        empty_exifedit.add_date_time_original(test_datetime)
        empty_exifedit.write(NON_EXISTING_FILE)

        exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)
        self.assertIsNone(
            exif_data.extract_exif_datetime(),
        )

    def test_add_repeatedly_time_original(self):
        add_repeatedly_time_original_general(self, EMPTY_EXIF_FILE_TEST)

    def test_add_time_original_to_existing_exif(self):
        test_altitude = 15.5
        test_altitude_precision = 100

        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)

        empty_exifedit.add_altitude(test_altitude, test_altitude_precision)
        empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

        test_datetime = datetime.datetime(2016, 9, 30, 8, 29, 26, 249000)

        not_empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)

        not_empty_exifedit.add_date_time_original(test_datetime)
        not_empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

        exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)

        self.assertEqual(
            test_altitude,
            exif_data.extract_altitude(),
        )

    def test_add_negative_lat_lon(self):
        test_latitude = -50.5
        test_longitude = -15.5
        precision = 1e7

        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)

        empty_exifedit.add_lat_lon(test_latitude, test_longitude, precision)
        empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

        exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)

        assert (test_longitude, test_latitude) == exif_data.extract_lon_lat()

    # REPEAT CERTAIN TESTS AND ADD ADDITIONAL TESTS FOR THE CORRUPT EXIF
    def test_load_and_dump_corrupt_exif(self):
        corrupt_exifedit = ExifEdit(CORRUPT_EXIF_FILE)
        corrupt_exifedit.dump_image_bytes()

    def test_load_and_dump_corrupt_exif_2(self):
        corrupt_exifedit = ExifEdit(CORRUPT_EXIF_FILE_2)
        corrupt_exifedit.dump_image_bytes()

    def test_add_image_description_corrupt_exif(self):
        add_image_description_general(self, CORRUPT_EXIF_FILE)

    def test_add_image_description_corrupt_exif_2(self):
        add_image_description_general(self, CORRUPT_EXIF_FILE_2)

    def test_add_orientation_corrupt_exif(self):
        add_orientation_general(self, CORRUPT_EXIF_FILE)

    def test_add_orientation_corrupt_exif_2(self):
        add_orientation_general(self, CORRUPT_EXIF_FILE_2)

    def test_add_date_time_original_corrupt_exif(self):
        add_date_time_original_general(self, CORRUPT_EXIF_FILE)

    def test_add_date_time_original_corrupt_exif_2(self):
        add_date_time_original_general(self, CORRUPT_EXIF_FILE_2)

    def test_add_lat_lon_corrupt_exif(self):
        add_lat_lon_general(self, CORRUPT_EXIF_FILE)

    def test_add_lat_lon_corrupt_exif_2(self):
        add_lat_lon_general(self, CORRUPT_EXIF_FILE_2)

    def test_add_altitude_corrupt_exif(self):
        add_altitude_general(self, CORRUPT_EXIF_FILE)

    def test_add_altitude_corrupt_exif_2(self):
        add_altitude_general(self, CORRUPT_EXIF_FILE_2)

    def test_add_direction_corrupt_exif(self):
        add_direction_general(self, CORRUPT_EXIF_FILE)

    def test_add_direction_corrupt_exif_2(self):
        add_direction_general(self, CORRUPT_EXIF_FILE_2)

    def test_add_repeatedly_time_original_corrupt_exif(self):
        add_repeatedly_time_original_general(self, CORRUPT_EXIF_FILE)

    def test_add_repeatedly_time_original_corrupt_exif_2(self):
        add_repeatedly_time_original_general(self, CORRUPT_EXIF_FILE_2)


def test_exif_write(tmpdir: py.path.local):
    image_dir = tmpdir.mkdir("images")
    image_path = image_dir.join("img.jpg")

    for filename in [
        EMPTY_EXIF_FILE,
        CORRUPT_EXIF_FILE,
        CORRUPT_EXIF_FILE_2,
        FIXED_EXIF_FILE,
        FIXED_EXIF_FILE_2,
    ]:
        p = py.path.local(filename)
        p.copy(image_path)

        with open(image_path, "rb") as fp:
            orig = fp.read()

        with open(image_path, "rb") as fp:
            edit = ExifEdit(fp.read())
        edit.add_orientation(1)
        image_bytes = edit.dump_image_bytes()

        with open(image_path, "rb") as fp:
            content = fp.read()
        assert image_bytes != content
        assert content == orig

        exif = ExifEdit(Path(image_path))
        exif.add_orientation(1)
        exif.write()

        with open(image_path, "rb") as fp:
            content = fp.read()
        assert image_bytes == content
