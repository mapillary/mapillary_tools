import os
import sys
import unittest
from PIL import Image
import piexif
from os import path
sys.path.append("python")
from lib.exifedit import ExifEdit
from lib.pexif import JpegFile, Rational #CHANGE remove

print("piexif version: {0}".format(piexif.VERSION))

NOEXIF_FILE = os.path.join("tests", "images", "noexif.jpg")
CANON_EXIF_FILE = os.path.join("tests", "images", "r_canon.jpg")
NOT_VALID_FILE = os.path.join("tests", "images", "not_valid_file")
NOT_VALID_IMAGE_FILE = os.path.join("tests", "images", "not_valid_image_file.png")

class ExifEditTests(unittest.TestCase):
    """tests for main functions."""
    
    def test_load_image_without_exif(self):
        exif_dict = piexif.load(NOEXIF_FILE)
        none_dict = {"0th":{},
                     "Exif":{},
                     "GPS":{},
                     "Interop":{},
                     "1st":{},
                     "thumbnail":None}
        self.assertEqual(exif_dict, none_dict)
                    
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
        
        
            
if __name__ == '__main__':
    unittest.main()