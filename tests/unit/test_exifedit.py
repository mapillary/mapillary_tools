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
        """Test that images with thumbnails larger than 64kB are handled gracefully."""
        # Create a test image with a large thumbnail (>64kB)
        test_image_path = data_dir.joinpath("tmp", "large_thumbnail.jpg")

        # Create a simple test image
        img = Image.new("RGB", (100, 100), color="red")
        img.save(test_image_path, "JPEG")

        # Create a large thumbnail (>64kB) by creating a high-quality large thumbnail
        # Use a larger size and add noise to make it incompressible
        large_thumbnail = Image.new("RGB", (2048, 2048))
        # Fill with random-like data to prevent compression
        pixels = large_thumbnail.load()
        for i in range(2048):
            for j in range(2048):
                pixels[i, j] = (
                    (i * 7 + j * 13) % 256,
                    (i * 11 + j * 17) % 256,
                    (i * 19 + j * 23) % 256,
                )

        thumbnail_bytes = io.BytesIO()
        large_thumbnail.save(thumbnail_bytes, "JPEG", quality=100)
        thumbnail_data = thumbnail_bytes.getvalue()

        # Verify thumbnail is larger than 64kB
        self.assertGreater(
            len(thumbnail_data),
            64 * 1024,
            f"Test thumbnail should be larger than 64kB but got {len(thumbnail_data)} bytes",
        )

        # Load the image and add GPS data first
        exif_edit = ExifEdit(test_image_path)
        test_latitude = 50.5475894785
        test_longitude = 15.595866685
        exif_edit.add_lat_lon(test_latitude, test_longitude)

        # Manually insert the large thumbnail into the internal EXIF structure
        # This simulates what would happen if an image came in with a large thumbnail
        exif_edit._ef["thumbnail"] = thumbnail_data
        exif_edit._ef["1st"] = {
            piexif.ImageIFD.Compression: 6,
            piexif.ImageIFD.XResolution: (72, 1),
            piexif.ImageIFD.YResolution: (72, 1),
            piexif.ImageIFD.ResolutionUnit: 2,
            piexif.ImageIFD.JPEGInterchangeFormat: 0,
            piexif.ImageIFD.JPEGInterchangeFormatLength: len(thumbnail_data),
        }

        # Given thumbnail is too large, max 64kB, thumbnail and 1st metadata should be removed.
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
