import os
import unittest
from PIL import Image, ExifTags
from mapillary_tools.exif_write import ExifEdit
from mapillary_tools.geo import decimal_to_dms
import datetime
import shutil

"""Initialize all the neccessary data"""

this_file = os.path.abspath(__file__)
this_file_dir = os.path.dirname(this_file)
data_dir = os.path.join(this_file_dir, "data")

EMPTY_EXIF_FILE = os.path.join(data_dir, "empty_exif.jpg")
EMPTY_EXIF_FILE_TEST = os.path.join(data_dir, "tmp", "empty_exif.jpg")
NON_EXISTING_FILE = os.path.join(data_dir, "tmp", "non_existing_file.jpg")
CORRUPT_EXIF_FILE = os.path.join(data_dir, "corrupt_exif.jpg")
CORRUPT_EXIF_FILE_2 = os.path.join(data_dir, "corrupt_exif_2.jpg")
FIXED_EXIF_FILE = os.path.join(data_dir, "fixed_exif.jpg")
FIXED_EXIF_FILE_2 = os.path.join(data_dir, "fixed_exif_2.jpg")

# more info on the standard exif tags
# https://sno.phy.queensu.ca/~phil/exiftool/TagNames/EXIF.html
EXIF_PRIMARY_TAGS_DICT = {y: x for x, y in ExifTags.TAGS.iteritems()}
EXIF_GPS_TAGS_DICT = {y: x for x, y in ExifTags.GPSTAGS.iteritems()}


def load_exif(filename=EMPTY_EXIF_FILE_TEST):

    test_image = Image.open(filename)

    exif_data = test_image._getexif()

    return exif_data


def add_image_description_general(test_obj, filename):

    test_dictionary = {"key_numeric": 1,
                       "key_string": "one",
                       "key_list": [1, 2],
                       "key_dict": {"key_dict1": 1, "key_dict2": 2}
                       }

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_image_description(test_dictionary)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = load_exif()
    test_obj.assertEqual(str(test_dictionary), str(
        exif_data[EXIF_PRIMARY_TAGS_DICT['ImageDescription']]).replace('"', '\''))


def add_orientation_general(test_obj, filename):

    test_orientation = 2

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_orientation(test_orientation)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = load_exif()
    test_obj.assertEqual(
        test_orientation, exif_data[EXIF_PRIMARY_TAGS_DICT['Orientation']])


def add_date_time_original_general(test_obj, filename):

    test_datetime = datetime.datetime(2016, 8, 31, 8, 29, 26, 249000)

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_date_time_original(test_datetime)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = load_exif()
    test_obj.assertEqual(test_datetime.strftime('%Y:%m:%d %H:%M:%S.%f')[
                         :-3], exif_data[EXIF_PRIMARY_TAGS_DICT['DateTimeOriginal']])


def add_lat_lon_general(test_obj, filename):

    test_latitude = 50.5475894785
    test_longitude = 15.595866685
    precision = 1e7

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_lat_lon(test_latitude, test_longitude, precision)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = load_exif()
    test_obj.assertEqual((decimal_to_dms(abs(test_latitude), precision), decimal_to_dms(abs(test_longitude), precision), "N", "E"),
                         (exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']][EXIF_GPS_TAGS_DICT['GPSLatitude']],
                          exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                    ][EXIF_GPS_TAGS_DICT['GPSLongitude']],
                          exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                    ][EXIF_GPS_TAGS_DICT['GPSLatitudeRef']],
                          exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']][EXIF_GPS_TAGS_DICT['GPSLongitudeRef']]))


def add_camera_make_model_general(test_obj, filename):

    test_make = "test_make"
    test_model = "test_model"

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_camera_make_model(test_make, test_model)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = load_exif()
    test_obj.assertEqual((test_make, test_model), (
        exif_data[EXIF_PRIMARY_TAGS_DICT['Make']], exif_data[EXIF_PRIMARY_TAGS_DICT['Model']]))


def add_dop_general(test_obj, filename):

    test_dop = 10.5
    test_dop_precision = 100

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_dop(test_dop, test_dop_precision)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = load_exif()
    test_obj.assertEqual((test_dop * test_dop_precision, test_dop_precision),
                         exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']][EXIF_GPS_TAGS_DICT['GPSDOP']])


def add_altitude_general(test_obj, filename):

    test_altitude = 15.5
    test_altitude_precision = 100

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_altitude(test_altitude, test_altitude_precision)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = load_exif()
    test_obj.assertEqual((test_altitude * test_altitude_precision, test_altitude_precision),
                         exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']][EXIF_GPS_TAGS_DICT['GPSAltitude']])


def add_repeatedly_time_original_general(test_obj, filename):

    test_datetime = datetime.datetime(2016, 8, 31, 8, 29, 26, 249000)

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_date_time_original(test_datetime)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    test_datetime = datetime.datetime(2016, 9, 30, 8, 29, 26, 249000)

    not_empty_exifedit = ExifEdit(filename)

    not_empty_exifedit.add_date_time_original(test_datetime)
    not_empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = load_exif()
    test_obj.assertEqual(test_datetime.strftime('%Y:%m:%d %H:%M:%S.%f')[
                         :-3], exif_data[EXIF_PRIMARY_TAGS_DICT['DateTimeOriginal']])


def add_direction_general(test_obj, filename):

    test_direction = 1
    test_direction_ref = "T"
    test_direction_precision = 100

    empty_exifedit = ExifEdit(filename)

    empty_exifedit.add_direction(
        test_direction, test_direction_ref, test_direction_precision)
    empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

    exif_data = load_exif()
    test_obj.assertEqual((test_direction * test_direction_precision, test_direction_precision),
                         exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']][EXIF_GPS_TAGS_DICT['GPSImgDirection']])


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

    def test_add_camera_make_model(self):

        add_camera_make_model_general(self, EMPTY_EXIF_FILE_TEST)

    def test_add_dop(self):

        add_dop_general(self, EMPTY_EXIF_FILE_TEST)

    def test_add_altitude(self):

        add_altitude_general(self, EMPTY_EXIF_FILE_TEST)

    def test_add_direction(self):

        add_direction_general(self, EMPTY_EXIF_FILE_TEST)

    def test_write_to_non_existing_file(self):

        test_datetime = datetime.datetime(2016, 8, 31, 8, 29, 26, 249000)

        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)

        empty_exifedit.add_date_time_original(test_datetime)
        empty_exifedit.write(NON_EXISTING_FILE)

        exif_data = load_exif(NON_EXISTING_FILE)
        self.assertEqual(test_datetime.strftime('%Y:%m:%d %H:%M:%S.%f')[
                         :-3], exif_data[EXIF_PRIMARY_TAGS_DICT['DateTimeOriginal']])

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

        exif_data = load_exif()
        self.assertEqual((test_altitude * test_altitude_precision, test_altitude_precision),
                         exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']][EXIF_GPS_TAGS_DICT['GPSAltitude']])

    def test_add_negative_lat_lon(self):

        test_latitude = -50.5
        test_longitude = -15.5
        precision = 1e7

        empty_exifedit = ExifEdit(EMPTY_EXIF_FILE_TEST)

        empty_exifedit.add_lat_lon(test_latitude, test_longitude, precision)
        empty_exifedit.write(EMPTY_EXIF_FILE_TEST)

        exif_data = load_exif()
        self.assertEqual((decimal_to_dms(abs(test_latitude), precision), decimal_to_dms(abs(test_longitude), precision), "S", "W"),
                         (exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']][EXIF_GPS_TAGS_DICT['GPSLatitude']],
                          exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                    ][EXIF_GPS_TAGS_DICT['GPSLongitude']],
                          exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                    ][EXIF_GPS_TAGS_DICT['GPSLatitudeRef']],
                          exif_data[EXIF_PRIMARY_TAGS_DICT['GPSInfo']][EXIF_GPS_TAGS_DICT['GPSLongitudeRef']]))

    # REPEAT CERTAIN TESTS AND ADD ADDITIONAL TESTS FOR THE CORRUPT EXIF
    def test_load_and_dump_corrupt_exif(self):

        corrupt_exifedit = ExifEdit(CORRUPT_EXIF_FILE)

        error_raised = False
        try:
            corrupt_exifedit.write(FIXED_EXIF_FILE)
        except:
            error_raised = True
        self.assertFalse(error_raised, 'EXIF load and dump back failed')

    def test_load_and_dump_corrupt_exif_2(self):

        corrupt_exifedit = ExifEdit(CORRUPT_EXIF_FILE_2)

        error_raised = False
        try:
            corrupt_exifedit.write(FIXED_EXIF_FILE_2)
        except:
            error_raised = True
        self.assertFalse(error_raised, 'EXIF load and dump back failed')

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

    def test_add_camera_make_model_corrupt_exif(self):

        add_camera_make_model_general(self, CORRUPT_EXIF_FILE)

    def test_add_camera_make_model_corrupt_exif_2(self):

        add_camera_make_model_general(self, CORRUPT_EXIF_FILE_2)

    def test_add_dop_corrupt_exif(self):

        add_dop_general(self, CORRUPT_EXIF_FILE)

    def test_add_dop_corrupt_exif_2(self):

        add_dop_general(self, CORRUPT_EXIF_FILE_2)

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


if __name__ == '__main__':
    unittest.main()
