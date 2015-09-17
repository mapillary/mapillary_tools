#!/usr/bin/python

import sys
import urllib2, urllib
import os
from Queue import Queue
import uuid
import time
import argparse

from lib.uploader import create_mapillary_description, get_authentication_info, get_upload_token, upload_file_list
from lib.sequence import Sequence

'''
Script for uploading images taken with other cameras than
the Mapillary iOS or Android apps.

It runs in the following steps:
    - Skip images that are potential duplicates (Move to path/duplicates)
    - Group images into sequences based on gps and time
    - Add Mapillary tags to the images
    - Upload the images

The following EXIF tags are required:
-GPSLongitude
-GPSLatitude
-(GPSDateStamp and GPSTimeStamp) or DateTimeOriginal or DateTimeDigitized or DateTime
-Orientation

NB: RUN geotag_from_gpx.py first for images with GPS in a separated GPX file (e.g. GoPro)

NB: DO NOT USE THIS SCRIPT ON IMAGE FILES FROM THE MAPILLARY APPS,
USE UPLOAD.PY INSTEAD.

(assumes Python 2.x, for Python 3.x you need to change some module names)
'''

MAPILLARY_UPLOAD_URL = "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.manual.images"
NUMBER_THREADS = int(os.getenv('NUMBER_THREADS', '4'))
MOVE_FILES = True


if __name__ == '__main__':
    '''
    Use from command line as: python upload_with_preprocessing.py path

    You need to set the environment variables MAPILLARY_USERNAME,
    MAPILLARY_PERMISSION_HASH and MAPILLARY_SIGNATURE_HASH to your
    unique values.

    You also need upload.py in the same folder or in your PYTHONPATH since this
    script uses pieces of that.
    '''

    if sys.version_info >= (3, 0):
        raise IOError("Incompatible Python version. This script requires Python 2.x, you are using {0}.".format(sys.version_info[:2]))

    parser = argparse.ArgumentParser(description='Upload photos to Mapillary with preprocessing')
    parser.add_argument('path', help='path to your photos')
    parser.add_argument('--cutoff_distance', default=500, help='maximum gps distance in meters within a sequence')
    parser.add_argument('--cutoff_time', default=10, help='maximum time interval in seconds within a sequence')
    parser.add_argument('--remove_duplicates', help='flag to perform duplicate removal or not', action='store_true')
    parser.add_argument('--rerun', help='flag to rerun the preprocessing and uploading', action='store_true')
    args = parser.parse_args()

    path = sys.argv[1]
    cutoff_distance = args.cutoff_distance
    cutoff_time = args.cutoff_time

    # Fetch authetication info
    info = get_authentication_info()
    if info is not None:
        MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD = info
    else:
        print("You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_EMAIL or MAPILLARY_PASSWORD. These are required.")
        sys.exit()

    upload_token = get_upload_token(MAPILLARY_EMAIL, MAPILLARY_PASSWORD)

    # Remove duplicates in a sequence (e.g. in case of red lights and in traffic)
    if args.rerun:
        skip_folders = []
    else:
        skip_folders = ['success', 'duplicates']
    s = Sequence(path, skip_folders=skip_folders)

    if s.num_images == 0:
        print("No images in the folder or all images have been successfully uploaded to Mapillary.")
        sys.exit()

    if args.remove_duplicates:
        duplicate_groups = s.remove_duplicates()

    # Split sequence based on distance and time
    s = Sequence(path, skip_folders=['duplicates'])
    split_groups = s.split(cutoff_distance=cutoff_distance, cutoff_time=cutoff_time)

    # Add Mapillary tags
    for root, sub_folders, files in os.walk(path):
        # Add a sequence uuid per sub-folder
        sequence_uuid = uuid.uuid4()
        if ('duplicates' not in root) and ('success' not in root):
            count = 0
            for filename in files:
                if filename.lower().endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif')):
                    create_mapillary_description(os.path.join(root, filename),
                                                    MAPILLARY_USERNAME,
                                                    MAPILLARY_EMAIL,
                                                    upload_token,
                                                    sequence_uuid)
                    count += 1
                else:
                    print "Ignoring {0}".format(os.path.join(root,filename))
            if count:
                print("Processing folder {0}, {1} files, sequence_id {2}.".format(root, count, sequence_uuid))
        else:
            print("Skipping images in {}".format(root))

    # TODO: Add a confirm step before moving the files

    # Upload images
    s = Sequence(path, skip_folders=['duplicates'])
    file_list = s.file_list
    upload_file_list(file_list)