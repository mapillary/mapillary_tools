import os
import sys
import unittest
from PIL import Image
from PIL import ExifTags
from os import path
sys.path.append("python")
from lib.exifedit import ExifEdit
import json
import datetime
import shutil
import math

def decimal_to_deg_min_sec(value, precision):
    '''
    Convert the degrees in float to degrees, minutes and seconds as tuple of tuples with precision identifier.
    >>> latitude = 23.122886
    >>> deg_to_deg_min_sec(latitude)
    ((23.0, 1), (7.0, 1), (223896.0, 10000))#CHECK the precision on the seconds
    '''
    deg = math.floor(value)
    min = math.floor((value-deg)*60)
    sec = math.floor((value-deg-min/60) * 36000000)

    return ((deg, 1), (min, 1), (sec, precision))


EMPTY_EXIF_FILE = os.path.join("tests", "data", "empty_exif.jpg")
EMPTY_EXIF_FILE_TEST = os.path.join("tests", "data", "tmp", "empty_exif.jpg")
NOT_VALID_FILE = os.path.join("tests", "data", "not_valid_file")
NOT_VALID_IMAGE_FILE = os.path.join("tests", "data", "not_valid_image_file.png")
MAPILLARY_JSON_METADATA = os.path.join("tests", "data", "map_metadata.json")

"""Initialize all the neccessary data"""
NONE_DICT = {"0th":{},
            "Exif":{},
            "GPS":{},
            "Interop":{},
            "1st":{},
            "thumbnail":None}

with open(MAPILLARY_JSON_METADATA) as json_file:
    JSON_DICT = json.load(json_file)
    
EXIFEDIT_EMPTY = ExifEdit(EMPTY_EXIF_FILE)   
        
class ExifEditTests(unittest.TestCase):
    """tests for main functions."""
    
    def setUp(self):
        if not os.path.exists(os.path.join("tests", "data", "tmp")):
            os.makedirs(os.path.join("tests", "data", "tmp"))  
        self._cleanup_test_file()      
        
    def tearDown(self):
        shutil.rmtree(os.path.join("tests", "data", "tmp"))
            
    def test_class_instance_unexisting_file(self):
        self.assertRaises(IOError, ExifEdit, "un_existing_file")
        
        
    def test_add_image_description(self):
        
        EXIFEDIT_EMPTY.add_image_description(JSON_DICT)
        
        TEST_exif_data = self._write_and_load_exif()
        
        self.assertEqual(json.dumps(JSON_DICT), TEST_exif_data[270])
         
    def test_add_orientation(self):
        
        test_orientation = 2
        
        EXIFEDIT_EMPTY.add_orientation(test_orientation)
        
        TEST_exif_data = self._write_and_load_exif()

        self.assertEqual(test_orientation, TEST_exif_data[274])
            
    def test_add_date_time_original(self):
        
        test_datetime = datetime.datetime.strptime(JSON_DICT["MAPCaptureTime"]+"000", "%Y_%m_%d_%H_%M_%S_%f")
        
        EXIFEDIT_EMPTY.add_date_time_original(test_datetime)

        TEST_exif_data = self._write_and_load_exif()

        self.assertEqual(test_datetime.strftime('%Y:%m:%d %H:%M:%S'), TEST_exif_data[36867])
        
    def test_add_lat_lon(self):
        
        test_latitude = 50.5
        test_longitude = 15.5
        
        EXIFEDIT_EMPTY.add_lat_lon(test_latitude, test_longitude)

        TEST_exif_data = self._write_and_load_exif()
                
        self.assertEqual((decimal_to_deg_min_sec(test_latitude, 50000000), decimal_to_deg_min_sec(test_longitude, 50000000)), (TEST_exif_data[34853][2], TEST_exif_data[34853][4]))
        
    def test_add_camera_make_model(self):
        
        test_make = "test_make"
        test_model = "test_model"
        
        EXIFEDIT_EMPTY.add_camera_make_model(test_make, test_model)

        TEST_exif_data = self._write_and_load_exif()

        self.assertEqual((test_make, test_model), (TEST_exif_data[271], TEST_exif_data[272]))
    
    def test_add_dop(self):
        
        test_dop = 10.5
        test_dop_precision = 100
        
        EXIFEDIT_EMPTY.add_dop(test_dop, test_dop_precision)

        TEST_exif_data = self._write_and_load_exif()

        self.assertEqual((test_dop*test_dop_precision, test_dop_precision), TEST_exif_data[34853][11])
        
    def test_add_altitude(self):
        
        test_altitude = 15.5
        test_altitude_precision = 100
        
        EXIFEDIT_EMPTY.add_altitude(test_altitude, test_altitude_precision)

        TEST_exif_data = self._write_and_load_exif()

        self.assertEqual((test_altitude*test_altitude_precision, test_altitude_precision), TEST_exif_data[34853][6])
    
    def test_add_direction(self):
        
        test_direction = 1
        test_direction_ref = "D"
        test_direction_precision = 100
        
        EXIFEDIT_EMPTY.add_direction(test_direction, test_direction_ref, test_direction_precision)

        TEST_exif_data = self._write_and_load_exif()

        self.assertEqual((test_direction*test_direction_precision, test_direction_precision), TEST_exif_data[34853][17])

    def _cleanup_test_file(self):        
        #copy the original empty file to the tmp, to have it empty again
        shutil.copy2(EMPTY_EXIF_FILE, EMPTY_EXIF_FILE_TEST)
    
    def _write_and_load_exif(self):   
        
        EXIFEDIT_EMPTY.write(EMPTY_EXIF_FILE_TEST)   
    
        TEST_IMAGE = Image.open(EMPTY_EXIF_FILE_TEST)

        TEST_IMAGE_exif_data = TEST_IMAGE._getexif()
        
        self._cleanup_test_file()  #this might be too much to do in every step since unique exif tags are changed in each function
        
        return   TEST_IMAGE_exif_data
        
if __name__ == '__main__':
    unittest.main()