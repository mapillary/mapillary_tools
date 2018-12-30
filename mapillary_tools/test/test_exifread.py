import os
import unittest
from PIL import Image, ExifTags
from mapillary_tools.exif_read import ExifRead
from mapillary_tools.geo import decimal_to_dms
import datetime

"""Initialize all the necessary data"""

this_file = os.path.abspath(__file__)
this_file_dir = os.path.dirname(this_file)
data_dir = os.path.join(this_file_dir, "data")

TEST_EXIF_FILE = os.path.join(data_dir, "test_exif.jpg")

# more info on the standard exif tags
# https://sno.phy.queensu.ca/~phil/exiftool/TagNames/EXIF.html
EXIF_PRIMARY_TAGS_DICT = {y: x for x, y in ExifTags.TAGS.iteritems()}
EXIF_GPS_TAGS_DICT = {y: x for x, y in ExifTags.GPSTAGS.iteritems()}


def gps_to_decimal(value, ref):
    sign = 1 if ref in 'NE' else -1
    degrees = value[0][0] / float(value[0][1])
    minutes = value[1][0] / float(value[1][1])
    seconds = value[2][0] / float(value[2][1])
    return sign * (degrees + minutes / 60 + seconds / 3600)


def load_exif_PIL(filename=TEST_EXIF_FILE):

    test_image = Image.open(filename)

    exif_data = test_image._getexif()

    return exif_data


def read_image_description_general(test_obj, filename):

    exif_data_PIL = load_exif_PIL()
    image_description_PIL = str(
        exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['ImageDescription']])

    exif_data_ExifRead = ExifRead(filename)
    image_description_ExifRead = str(
        exif_data_ExifRead.extract_image_description())

    test_obj.assertEqual(image_description_ExifRead, image_description_PIL)


def read_image_history_general(test_obj, filename):

    exif_data_PIL = load_exif_PIL()
    image_history_PIL = str(
        exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['ImageHistory']])

    exif_data_ExifRead = ExifRead(filename)
    image_history_ExifRead = str(
        exif_data_ExifRead.extract_image_history())

    test_obj.assertEqual(image_history_ExifRead, image_history_PIL)


def read_orientation_general(test_obj, filename):

    exif_data_PIL = load_exif_PIL()
    orientation_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['Orientation']]

    exif_data_ExifRead = ExifRead(filename)
    orientation_ExifRead = exif_data_ExifRead.extract_orientation()

    test_obj.assertEqual(orientation_PIL, orientation_ExifRead)


def read_date_time_original_general(test_obj, filename):

    exif_data_PIL = load_exif_PIL()
    capture_time_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['DateTimeOriginal']]

    exif_data_ExifRead = ExifRead(filename)
    capture_time_ExifRead = exif_data_ExifRead.extract_capture_time()
    capture_time_ExifRead = capture_time_ExifRead.strftime("%Y:%m:%d %H:%M:%S.%f")[
        :-3]

    test_obj.assertEqual(capture_time_PIL, capture_time_ExifRead)


def read_lat_lon_general(test_obj, filename):

    exif_data_PIL = load_exif_PIL()
    latitude_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                 ][EXIF_GPS_TAGS_DICT['GPSLatitude']]
    longitude_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                  ][EXIF_GPS_TAGS_DICT['GPSLongitude']]
    latitudeRef_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                    ][EXIF_GPS_TAGS_DICT['GPSLatitudeRef']]
    longitudeRef_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                     ][EXIF_GPS_TAGS_DICT['GPSLongitudeRef']]

    latitude_PIL = gps_to_decimal(latitude_PIL, latitudeRef_PIL)
    longitude_PIL = gps_to_decimal(longitude_PIL, longitudeRef_PIL)

    exif_data_ExifRead = ExifRead(filename)
    longitude_ExifRead, latitude_ExifRead = exif_data_ExifRead.extract_lon_lat()

    test_obj.assertEqual((latitude_PIL, longitude_PIL),
                         (latitude_ExifRead, longitude_ExifRead))


def read_camera_make_model_general(test_obj, filename):

    exif_data_PIL = load_exif_PIL()
    make_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['Make']]
    model_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['Model']]

    exif_data_ExifRead = ExifRead(filename)
    make_ExifRead = exif_data_ExifRead.extract_make()
    model_ExifRead = exif_data_ExifRead.extract_model()

    test_obj.assertEqual((make_PIL, model_PIL),
                         (make_ExifRead, model_ExifRead))


def read_altitude_general(test_obj, filename):

    exif_data_PIL = load_exif_PIL()
    altitude_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                 ][EXIF_GPS_TAGS_DICT['GPSAltitude']]
    altitude_PIL = altitude_PIL[0] / float(altitude_PIL[1])

    exif_data_ExifRead = ExifRead(filename)
    altitude_ExifRead = exif_data_ExifRead.extract_altitude()

    test_obj.assertEqual(altitude_PIL,
                         altitude_ExifRead)


def read_direction_general(test_obj, filename):

    exif_data_PIL = load_exif_PIL()
    direction_PIL = exif_data_PIL[EXIF_PRIMARY_TAGS_DICT['GPSInfo']
                                  ][EXIF_GPS_TAGS_DICT['GPSImgDirection']]
    direction_PIL = direction_PIL[0] / float(direction_PIL[1])

    exif_data_ExifRead = ExifRead(filename)
    direction_ExifRead = exif_data_ExifRead.extract_direction()

    test_obj.assertEqual(direction_PIL,
                         direction_ExifRead)


class ExifReadTests(unittest.TestCase):
    """tests for main functions."""

    def test_read_image_description(self):

        read_image_description_general(self, TEST_EXIF_FILE)

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


if __name__ == '__main__':
    unittest.main()
