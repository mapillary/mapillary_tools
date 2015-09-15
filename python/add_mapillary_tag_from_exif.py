#!/usr/bin/env python

from __future__ import division
import sys
import urllib2, urllib
import os
from Queue import Queue
import hashlib
import uuid
import time
import json
import pyexiv2
import datetime, time
import base64

from lib.uploader import get_upload_token, get_authentication_info
from lib.exifedit import create_mapillary_description
from lib.geo import dms_to_decimal

'''
Script for reading the EXIF data from images and create the
Mapillary tags in Image Description (including the upload hashes)
needed to be able to upload without authentication.

This script will add all photos in the same folder to one sequence,
so group your photos into one subfolder per sequence (works deeply nested, too).

-root
    |
    |- seq1
    |  |- seq1_1.jpg
    |  |- seq1_2.jpg
    |  |
    |  |- seq2
    |     |- seq2_1.jpg
    |
    |- seq3
       |- seq3_1.jpg

The following EXIF tags are required:
-GPSLongitude
-GPSLatitude
-(GPSDateStamp and GPSTimeStamp) or DateTimeOriginal or DateTimeDigitized or DateTime
-Orientation

(assumes Python 2.x, for Python 3.x you need to change some module names)
'''

if __name__ == '__main__':
    '''
    Use from command line as: python add_mapillary_tag_from_exif.py root_path [sequence_uuid]
    '''

    Fetch authetication info from env
    info = get_authentication_info()
    if info is not None:
        MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD = info
    else:
        print("You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_EMAIL or MAPILLARY_PASSWORD. These are required.")
        sys.exit()

    upload_token = get_upload_token(MAPILLARY_EMAIL, MAPILLARY_PASSWORD)

    args = sys.argv

    if len(args) < 2 or len(args) > 3:
        sys.exit("Usage: python %s root_path [sequence_id]" % args[0])

    path = args[1]

    for root, sub_folders, files in os.walk(path):
        sequence_uuid = args[2] if len(args) == 3 else uuid.uuid4()
        print("Processing folder {0}, {1} files, sequence_id {2}.".format(root, len(files), sequence_uuid))
        for file in files:
            if file.lower().endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif')):
                create_mapillary_description(os.path.join(root,file), MAPILLARY_USERNAME, MAPILLARY_EMAIL, upload_token, sequence_uuid)
            else:
                print "Ignoring {0}".format(os.path.join(root,file))
