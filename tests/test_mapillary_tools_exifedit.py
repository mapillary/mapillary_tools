import os
import sys
import unittest
from PIL import Image
import piexif
from os import path
sys.path.append("python")
from lib.exifedit import ExifEdit
from lib.pexif import JpegFile, Rational #CHANGE remove
import json
import datetime

print("piexif version: {0}".format(piexif.VERSION))

NOEXIF_FILE = os.path.join("tests", "images", "noexif.jpg")
CANON_EXIF_FILE = os.path.join("tests", "images", "r_canon.jpg")
NOT_VALID_FILE = os.path.join("tests", "images", "not_valid_file")
NOT_VALID_IMAGE_FILE = os.path.join("tests", "images", "not_valid_image_file.png")
MAPILLARY_IMAGE_FILE = os.path.join("tests", "images", "map_exif_image.jpg")
MAPILLARY_JSON_METADATA = os.path.join("tests", "images", "map_metadata.json")

"""Initialize all the neccessary data"""
NONE_DICT = {"0th":{},
            "Exif":{},
            "GPS":{},
            "Interop":{},
            "1st":{},
            "thumbnail":None}

with open(MAPILLARY_JSON_METADATA) as json_file:
    JSON_DICT = json.load(json_file)
    
EXIFEDIT_CANON = ExifEdit(CANON_EXIF_FILE)   
    
EXIF_MAPILLARY = piexif.load(MAPILLARY_IMAGE_FILE)
    
class ExifEditTests(unittest.TestCase):
    """tests for main functions."""
            
    def test_class_instance_unexisting_file(self):
        self.assertRaises(IOError, ExifEdit, "un_existing_file")
        
    #CHANGE remove this and uncomment below functions  
    def test_class_instance_unvalid_file(self):
        self.assertRaises(JpegFile.InvalidFile, ExifEdit, NOT_VALID_FILE)

    ''' #CHANGE
    def test_class_instance_unvalid_file(self):
        self.assertRaises(ValueError, ExifEdit, NOT_VALID_FILE)
   
    def test_class_instance_unvalid_image_file(self):
        self.assertRaises(piexif.InvalidImageDataError, ExifEdit, NOT_VALID_IMAGE_FILE)
        
    '''
        
    def test_add_image_description(self):
        
        EXIFEDIT_CANON.add_image_description(JSON_DICT)

        #CHANGE delete below line and uncomment next line
        self.assertEqual(EXIF_MAPILLARY['0th'][piexif.ImageIFD.ImageDescription], EXIFEDIT_CANON.ef.exif.primary.ImageDescription)
        #self.assertEqual(EXIF_MAPILLARY['0th'][piexif.ImageIFD.ImageDescription], EXIFEDIT_CANON.ef['0th'][piexif.ImageIFD.ImageDescription])
        
    def test_add_orientation(self):
        
        EXIFEDIT_CANON.add_orientation(2)
        
        #CHANGE delete below line and uncomment next line
        self.assertEqual([EXIF_MAPILLARY['0th'][piexif.ImageIFD.Orientation]], EXIFEDIT_CANON.ef.exif.primary.Orientation)
        #self.assertEqual([EXIF_MAPILLARY['0th'][piexif.ImageIFD.Orientation]], EXIFEDIT_CANON.ef['0th'][piexif.ImageIFD.Orientation])
    
    def test_add_date_time_original(self):
        date_time = datetime.datetime.strptime(JSON_DICT["MAPCaptureTime"]+"000", "%Y_%m_%d_%H_%M_%S_%f")
        EXIFEDIT_CANON.add_date_time_original(date_time)

        #CHANGE delete below line and uncomment next line
        self.assertEqual(EXIF_MAPILLARY['Exif'][piexif.ExifIFD.DateTimeOriginal], EXIFEDIT_CANON.ef.exif.primary.ExtendedEXIF.DateTimeOriginal)
        #self.assertEqual([EXIF_MAPILLARY['0th'][piexif.ImageIFD.Orientation]], EXIFEDIT_CANON.ef['0th'][piexif.ImageIFD.Orientation])
        
    def test_add_lat_lon(self):
        
        EXIFEDIT_CANON.add_lat_lon(JSON_DICT["MAPLatitude"],JSON_DICT["MAPLongitude"])
        
        #CHANGE delete below line and uncomment next line
        canon_lat_latref_lon_lon_ref = (EXIFEDIT_CANON.ef.exif.primary.GPS.GPSLatitude, EXIFEDIT_CANON.ef.exif.primary.GPS.GPSLatitudeRef,
                                        EXIFEDIT_CANON.ef.exif.primary.GPS.GPSLongitude, EXIFEDIT_CANON.ef.exif.primary.GPS.GPSLongitudeRef)
        
        #canon_lat_latref_lon_lon_ref = (EXIFEDIT_CANON["GPS"][piexif.GPSIFD.GPSLatitude], EXIFEDIT_CANON["GPS"][piexif.GPSIFD.GPSLatitudeRef],
        #                                EXIFEDIT_CANON["GPS"][piexif.GPSIFD.GPSLongitude], EXIFEDIT_CANON["GPS"][piexif.GPSIFD.GPSLongitudeRef])
        
        
        map_lat_latref_lon_lon_ref = (EXIF_MAPILLARY["GPS"][piexif.GPSIFD.GPSLatitude], EXIF_MAPILLARY["GPS"][piexif.GPSIFD.GPSLatitudeRef],
                                      EXIF_MAPILLARY["GPS"][piexif.GPSIFD.GPSLongitude], EXIF_MAPILLARY["GPS"][piexif.GPSIFD.GPSLongitudeRef])
                                                                                                              
        #CHANGE delete below line and uncomment next line
        #self.assertEqual(map_lat_latref_lon_lon_ref, canon_lat_latref_lon_lon_ref)
        #self.assertEqual[(EXIF_MAPILLARY['0th'][piexif.ImageIFD.Orientation]], EXIFEDIT_CANON.ef['0th'][piexif.ImageIFD.Orientation])
        
    '''
    
    def add_camera_make_model(self, make, model):
        """ Add camera make and model."""
        self.ef.exif.primary.Make = make
        self.ef.exif.primary.Model = model

    def add_dop(self, dop, perc=100):
        """Add GPSDOP (float)."""
        self.ef.exif.primary.GPS.GPSDOP = [Rational(abs(dop * perc), perc)]

    def add_altitude(self, altitude, precision=100):
        """Add altitude (pre is the precision)."""
        ref = '\x00' if altitude > 0 else '\x01'
        self.ef.exif.primary.GPS.GPSAltitude = [Rational(abs(altitude * precision), precision)]
        self.ef.exif.primary.GPS.GPSAltitudeRef = [ref]

    def add_direction(self, direction, ref="T", precision=100):
        """Add image direction."""
        self.ef.exif.primary.GPS.GPSImgDirection = [Rational(abs(direction * precision), precision)]
        self.ef.exif.primary.GPS.GPSImgDirectionRef = ref

    '''
    
            
if __name__ == '__main__':
    unittest.main()