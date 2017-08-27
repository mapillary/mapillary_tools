#!/usr/bin/env python

import sys
import urllib2, urllib
import os
from Queue import Queue
import uuid
import time
import argparse
from lib.uploader import upload_done_file, create_dirs, get_authentication_info, get_upload_token, UploadThread, upload_file_list, finalize_upload
from lib.exif import verify_exif
from lib.exif import EXIF
from lib.sequence import Sequence

'''
Script for uploading images taken with other cameras than
the Mapillary iOS or Android apps.

Intended use is for when you have used an action camera such as a GoPro
or Garmin VIRB, or any other camera where the location is included in the image EXIF.

The following EXIF tags are required:
-GPSLongitude
-GPSLatitude
-(GPSDateStamp and GPSTimeStamp) or DateTimeOriginal or DateTimeDigitized or DateTime

Before uploading put all images that belong together in a sequence, in a
specific folder, for example using 'sequence_split.py'. All images in a session
will be considered part of a single sequence.

NB: DO NOT USE THIS SCRIPT ON IMAGE FILES FROM THE MAPILLARY APPS,
USE UPLOAD.PY INSTEAD.

(assumes Python 2.x, for Python 3.x you need to change some module names)
'''


MAPILLARY_UPLOAD_URL = "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.manual.images"
NUMBER_THREADS = int(os.getenv('NUMBER_THREADS', '4'))
MOVE_FILES = True

if __name__ == '__main__':
    '''
    Use from command line as: python upload_with_authentication.py path

    You need to set the environment variables MAPILLARY_USERNAME,
    MAPILLARY_PERMISSION_HASH and MAPILLARY_SIGNATURE_HASH to your
    unique values.

    You also need upload.py in the same folder or in your PYTHONPATH since this
    script uses pieces of that.
    '''
    if sys.version_info >= (3, 0):
        raise IOError("Incompatible Python version. This script requires Python 2.x, you are using {0}.".format(sys.version_info[:2]))

    parser = argparse.ArgumentParser(description='Upload images with authentication')
    parser.add_argument('path', help='path to your photos')
    parser.add_argument('--upload_subfolders', help='option to upload subfolders', action='store_true')
    parser.add_argument('--auto_done', help='option to send DONE file without user confirmation', action='store_true')

    args = parser.parse_args()

    path = args.path
    skip_subfolders = not args.upload_subfolders
    auto_done = args.auto_done

    # if no success/failed folders, create them
    create_dirs()

    # get env variables
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_PERMISSION_HASH = os.environ['MAPILLARY_PERMISSION_HASH']
        MAPILLARY_SIGNATURE_HASH = os.environ['MAPILLARY_SIGNATURE_HASH']
    except KeyError:
        print("You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_PERMISSION_HASH or MAPILLARY_SIGNATURE_HASH. These are required.")
        sys.exit()

    # generate a sequence UUID
    sequence_id = uuid.uuid4()

    # S3 bucket
    s3_bucket = MAPILLARY_USERNAME+"/"+str(sequence_id)+"/"

    # set upload parameters
    params = {"url": MAPILLARY_UPLOAD_URL, "key": s3_bucket,
            "permission": MAPILLARY_PERMISSION_HASH, "signature": MAPILLARY_SIGNATURE_HASH,
            "move_files": MOVE_FILES}

    # get the list of images in the folder
    # Caution: all nested folders will be merged into one sequence!
    s = Sequence(path, skip_folders=['success', 'duplicates'], skip_subfolders=skip_subfolders)

    if len(s.file_list) == 0:
        print('No images in the folder or all images have all ready been uploaded to Mapillary')
        print('Note: If upload fails mid-sequence due to connection failure or similar, you should manually push the images to the server at http://www.mapillary.com/map/upload/im/ and pressing "push to Mapillary".')
        sys.exit()

    print("Uploading sequence {0}.".format(sequence_id))

    # check mapillary tag and required exif
    num_image_file = len(s.file_list)
    file_list = []
    for filepath in s.file_list:
        mapillary_tag_exists = EXIF(filepath).mapillary_tag_exists()
        if mapillary_tag_exists:
            print("File {} contains Mapillary EXIF tags, use upload.py instead.".format(filepath))

        required_exif_exist = verify_exif(filepath)
        if not required_exif_exist:
            print("File {} missing required exif".format(filepath))

        if required_exif_exist and (not mapillary_tag_exists):
            file_list.append(filepath)

    #upload valid files
    print ("Uploading {} images with valid exif tags (Skipping {}) ...".format(len(file_list), num_image_file-len(file_list)))
    upload_file_list(file_list, params)

    # ask user if finalize upload to check that everything went fine
    print("===\nFinalizing upload will submit all successful uploads and ignore all failed.\nIf all files were marked as successful, everything is fine, just press 'y'.")
    finalize_upload(params, auto_done=auto_done)
