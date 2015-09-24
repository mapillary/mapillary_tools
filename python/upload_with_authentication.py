#!/usr/bin/python

import sys
import urllib2, urllib
import os
from Queue import Queue
import uuid
import time
from lib.uploader import upload_done_file, create_dirs, get_authentication_info, get_upload_token, UploadThread
from lib.exif import verify_exif
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
-Orientation

Before uploading put all images that belong together in a sequence, in a
specific folder, for example using 'sequence_split.py'. All images in a session
will be considered part of a single sequence.

NB: DO NOT USE THIS SCRIPT ON IMAGE FILES FROM THE MAPILLARY APPS,
USE UPLOAD.PY INSTEAD.

(assumes Python 2.x, for Python 3.x you need to change some module names)
'''


MAPILLARY_UPLOAD_URL = "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.manual.images"
NUMBER_THREADS = int(os.getenv('NUMBER_THREADS', '4'))
MOVE_FILES = False

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

    if len(sys.argv) < 2:
        print("Usage: python upload_with_authentication.py path")
        raise IOError("Bad input parameters.")
    path = sys.argv[1]

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
    print("Uploading sequence {0}.".format(sequence_id))

    # set upload parameters
    params = {"url": MAPILLARY_UPLOAD_URL, "key": s3_bucket,
            "permission": MAPILLARY_PERMISSION_HASH, "signature": MAPILLARY_SIGNATURE_HASH,
            "move_files": MOVE_FILES}

    # get the list of images in the folder (nested folders will be merged into one sequence)
    s = Sequence(path, skip_folders=['success'])
    file_list = s.file_list

    # create upload queue with all files
    q = Queue()
    for filepath in file_list:
        # make sure no Mapillary tags
        mapillary_tag_exists = exif.mapillary_tag_exists()
        if mapillary_tag_exists:
            print("File contains Mapillary EXIF tags, use upload.py instead.")
        if verify_exif(filepath) and (not mapillary_tag_exists):
            q.put(filepath)
        else:
            print("Skipping: {0}".format(filepath))

    # create uploader threads with permission parameters
    uploaders = [UploadThread(q, params) for i in range(NUMBER_THREADS)]

    # start uploaders as daemon threads that can be stopped (ctrl-c)
    try:
        for uploader in uploaders:
            uploader.daemon = True
            uploader.start()

        for uploader in uploaders:
            uploaders[i].join(1)

        while q.unfinished_tasks:
            time.sleep(1)
        q.join()
    except (KeyboardInterrupt, SystemExit):
        print("\nBREAK: Stopping upload.")
        sys.exit()

    # ask user if finalize upload to check that everything went fine
    print("===\nFinalizing upload will submit all successful uploads and ignore all failed.\nIf all files were marked as successful, everything is fine, just press 'y'.")

    # ask 3 times if input is unclear
    for i in range(3):
        proceed = raw_input("Finalize upload? [y/n]: ")
        if proceed in ["y", "Y", "yes", "Yes"]:
            # upload an empty DONE file
            upload_done_file(params)
            print("Done uploading.")
            break
        elif proceed in ["n", "N", "no", "No"]:
            print("Aborted. No files were submitted. Try again if you had failures.")
            break
        else:
            if i==2:
                print("Aborted. No files were submitted. Try again if you had failures.")
            else:
                print('Please answer y or n. Try again.')
