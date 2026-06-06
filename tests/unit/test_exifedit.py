# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import io
import os
import shutil
import unittest
from pathlib import Path

import piexif
import py.path
from mapillary_tools.exif_read import ExifRead
from mapillary_tools.exif_write import ExifEdit
from PIL import Image

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
# JPEGs whose EXIF piexif can load but cannot re-dump (a tag stored with the
# wrong type), used to exercise the ExifEdit._safe_dump recovery branches.
UNDUMPABLE_EXIF_FILE = data_dir.joinpath("corrupt_exif_wrong_type.jpg")
UNDUMPABLE_TRUSTED_EXIF_FILE = data_dir.joinpath("corrupt_exif_trusted_wrong_type.jpg")
# A JPEG whose EXIF carries a thumbnail above piexif's 64000-byte dump limit.
LARGE_THUMBNAIL_EXIF_FILE = data_dir.joinpath("corrupt_exif_large_thumbnail.jpg")


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

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_lat_lon(test_latitude, test_longitude)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)

    test_obj.assertEqual((test_longitude, test_latitude), exif_data.extract_lon_lat())


def add_altitude_general(test_obj, filename: Path):
    test_altitude = 15.5

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_altitude(test_altitude)
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

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_direction(test_direction, test_direction_ref)
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

        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)

        empty_exifedit.add_altitude(test_altitude)
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

        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)

        empty_exifedit.add_lat_lon(test_latitude, test_longitude)
        empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

        exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)

        assert (test_longitude, test_latitude) == exif_data.extract_lon_lat()

    def test_add_make_and_model(self):
        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)
        empty_exifedit.add_make("Canon")
        empty_exifedit.add_model("EOS 5D")
        empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

        exif_data = ExifRead(EMPTY_EXIF_FILE_TEST)
        self.assertEqual("Canon", exif_data.extract_make())
        self.assertEqual("EOS 5D", exif_data.extract_model())

    def test_add_make_empty_raises(self):
        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)
        with self.assertRaises(ValueError):
            empty_exifedit.add_make("")

    def test_add_model_empty_raises(self):
        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)
        with self.assertRaises(ValueError):
            empty_exifedit.add_model("")

    def test_add_orientation_invalid_raises(self):
        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)
        with self.assertRaises(ValueError):
            empty_exifedit.add_orientation(99)

    def test_write_bytes_without_filename_raises(self):
        with open(EMPTY_EXIF_FILE_TEST, "rb") as fp:
            edit = ExifEdit(fp.read())
        edit.add_orientation(1)
        # The source is raw bytes, so write() has no filename to fall back on.
        with self.assertRaises(ValueError):
            edit.write()

    def test_safe_dump_strips_untrusted_wrong_type_tag(self):
        """A non-trusted tag piexif loads but can't re-dump is stripped, then dump succeeds.

        The fixture stores Software (non-trusted) with a type piexif decodes as
        an int but refuses to dump as ASCII; _safe_dump drops it and retries.
        """
        edit = ExifEdit(UNDUMPABLE_EXIF_FILE)
        image_bytes = edit.dump_image_bytes()
        self.assertGreater(len(image_bytes), 0)
        # The offending Software tag is gone from the recovered output.
        recovered = piexif.load(image_bytes)
        self.assertNotIn(piexif.ImageIFD.Software, recovered["0th"])

    def test_safe_dump_reraises_trusted_wrong_type_tag(self):
        """A trusted tag with a wrong value type must not be silently dropped.

        The fixture stores ImageDescription (trusted) with the wrong type, so
        _safe_dump re-raises rather than stripping it.
        """
        edit = ExifEdit(UNDUMPABLE_TRUSTED_EXIF_FILE)
        with self.assertRaises(ValueError):
            edit.dump_image_bytes()

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

    def test_large_thumbnail_handling(self):
        """Test that images with thumbnails larger than 64kB are handled gracefully.

        The fixture carries a thumbnail above piexif's 64000-byte dump limit, so
        _safe_dump must drop the thumbnail and 1st IFD and retry. GPS data added
        through the public API must survive.
        """
        exif_edit = ExifEdit(LARGE_THUMBNAIL_EXIF_FILE)
        test_latitude = 50.5475894785
        test_longitude = 15.595866685
        exif_edit.add_lat_lon(test_latitude, test_longitude)

        # Given the thumbnail is too large, it and the 1st IFD should be removed.
        image_bytes = exif_edit.dump_image_bytes()

        # Verify the output is valid
        self.assertIsNotNone(image_bytes)
        self.assertGreater(len(image_bytes), 0)

        # Verify the resulting image is a valid JPEG
        result_image = Image.open(io.BytesIO(image_bytes))
        self.assertEqual(result_image.format, "JPEG")
        self.assertEqual(result_image.size, (100, 100))

        # Verify we can read the GPS data from the result
        output_exif = piexif.load(image_bytes)
        self.assertIn("GPS", output_exif)
        self.assertIn(piexif.GPSIFD.GPSLatitude, output_exif["GPS"])
        self.assertIn(piexif.GPSIFD.GPSLongitude, output_exif["GPS"])

        # CRITICAL: Verify the large thumbnail was actually removed
        # The fix should have deleted both "thumbnail" and "1st" to handle the error
        # piexif.load() may include "thumbnail": None after removal
        thumbnail_value = output_exif.get("thumbnail")
        self.assertTrue(
            thumbnail_value is None or thumbnail_value == b"",
            f"Large thumbnail should have been removed but got: {thumbnail_value[:100] if thumbnail_value else None}",
        )

        first_value = output_exif.get("1st")
        self.assertTrue(
            first_value is None or first_value == {} or len(first_value) == 0,
            f"1st metadata should have been removed but got: {first_value}",
        )


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
