#!/usr/bin/python

import sys
import urllib2, urllib
import os
from Queue import Queue
import uuid
import time
import argparse
import json

from lib.uploader import create_mapillary_description, get_authentication_info, get_upload_token, upload_file_list, upload_done_file
from lib.sequence import Sequence
from lib.exif import is_image, verify_exif

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
NUMBER_THREADS = int(os.getenv('NUMBER_THREADS', '2'))
MOVE_FILES = True

def log_file(path):
    return os.path.join(path, 'UPLOAD_LOG.txt')

def write_log(path):
    with open(log_file(path), 'wb') as f:
        f.write(lines)

def read_log(path):
    if os.path.exists(log_file(path)):
        with open(log_file(path), 'rb') as f:
            lines = f.read()
    else:
        return None
    return lines

def edit_log_file(path):
    return os.path.join(path, 'EDIT_LOG.json')

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
    parser.add_argument('--cutoff_distance', default=300, help='maximum gps distance in meters within a sequence')
    parser.add_argument('--cutoff_time', default=30, help='maximum time interval in seconds within a sequence')
    parser.add_argument('--remove_duplicates', help='flag to perform duplicate removal or not', action='store_true')
    parser.add_argument('--rerun', help='flag to rerun the preprocessing and uploading', action='store_true')
    parser.add_argument('--skip_upload', help='upload to server or not', action='store_true')
    args = parser.parse_args()

    path = sys.argv[1]
    cutoff_distance = args.cutoff_distance
    cutoff_time = args.cutoff_time
    skip_upload = args.skip_upload

    # Fetch authetication info
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_EMAIL = os.environ['MAPILLARY_EMAIL']
        MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']
        MAPILLARY_PERMISSION_HASH = os.environ['MAPILLARY_PERMISSION_HASH']
        MAPILLARY_SIGNATURE_HASH = os.environ['MAPILLARY_SIGNATURE_HASH']
    except KeyError:
        print("You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_PERMISSION_HASH or MAPILLARY_SIGNATURE_HASH. These are required.")
        sys.exit()
    upload_token = get_upload_token(MAPILLARY_EMAIL, MAPILLARY_PASSWORD)

    # Check whether the directory has been processed before
    logs = read_log(path)
    retry_upload = False
    if logs is not None:
        s = Sequence(path)
        total_failed = len([f for f in s.file_list if 'failed' in f])
        print("This folder has been processed before. See summary below: \n{}".format(logs))
        if total_failed:
            print ("There are {} failed images.".format(total_failed))
            proceed = raw_input("Retry uploading failed images? [y/n]: ")
            if proceed in ["y", "Y", "yes", "Yes"]:
                retry_upload = True
                print("Start uploading failed images ...")
            elif proceed in ["n", "N", "no", "No"]:
                retry_upload = False
                print("Aborted. No retry on failed uploads")
                sys.exit()
            else:
                print('Please answer y or n. Try again.')
        else:
            print("Aborted. All uploads were successfully in your last upload section.")
            sys.exit()

    duplicate_groups = {}
    split_groups = {}
    missing_groups = []
    s3_bucket_list = []
    total_uploads = 0

    if (not retry_upload) and (not os.path.exists(edit_log_file(path))):
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
            print("\n=== Removing potentially duplicate images ...")
            duplicate_groups = s.remove_duplicates()

        # Split sequence based on distance and time
        print("\n=== Spliting photos into sequences based on time and distance ...")
        s = Sequence(path, skip_folders=['duplicates'])
        split_groups = s.split(cutoff_distance=cutoff_distance, cutoff_time=cutoff_time)

    if not os.path.exists(edit_log_file(path)) or args.rerun:

        # Add Mapillary tags
        print("\n=== Adding Mapillary tags and uploading per sequence ...")
        sequence_list = {}
        for root, sub_folders, files in os.walk(path):
            if ('duplicates' not in root) and ('success' not in root):
                # Add a sequence uuid per sub-folder
                if len(files) > 0:
                    sequence_uuid = uuid.uuid4()
                    print("  sequence uuid: {}".format(sequence_uuid))
                s = Sequence(root, skip_folders=['duplicates', 'success'])
                directions = s.interpolate_direction()
                file_list = []
                for filename in files:
                    if is_image(filename):
                        filepath = os.path.join(root, filename)
                        if verify_exif(filepath):
                            if not retry_upload:
                                # skip creating new sequence id for failed images
                                create_mapillary_description(filepath,
                                                                MAPILLARY_USERNAME,
                                                                MAPILLARY_EMAIL,
                                                                upload_token,
                                                                sequence_uuid,
                                                                directions[filepath])
                            file_list.append(filepath)
                        else:
                            missing_groups.append(filepath)
                    else:
                        print "   Ignoring {0}".format(os.path.join(root,filename))

                count = len(file_list)
                if count > 0:
                    sequence_list[str(sequence_uuid)] = file_list
            else:
                print("      Skipping images in {}".format(root))

        with open(edit_log_file(path), 'wb') as f:
            f.write(json.dumps(sequence_list, indent=4))
    else:
        with open(edit_log_file(path), 'rb') as f:
            sequence_list = json.loads(f.read())

    if not skip_upload:
        # Uploading images in each subfolder as a sequence
        for sequence_uuid, file_list in sequence_list.iteritems():
            file_list = [str(f) for f in file_list if os.path.exists(f)]
            count = len(file_list)
            s3_bucket = MAPILLARY_USERNAME+"/"+str(sequence_uuid)+"/"
            s3_bucket_list.append(s3_bucket)
            if count and not skip_upload:
                # upload a sequence
                print 'Uploading sequence {} to {}'.format(str(sequence_uuid), s3_bucket)

                # set upload parameters
                params = {"url": MAPILLARY_UPLOAD_URL,
                          "key": s3_bucket,
                          "permission": MAPILLARY_PERMISSION_HASH,
                          "signature": MAPILLARY_SIGNATURE_HASH,
                          "move_files": MOVE_FILES}

                # Upload images
                total_uploads += len(file_list)
                upload_file_list(file_list, params)

    # A short summary of the uploads
    s = Sequence(path)
    total_success = len([f for f in s.file_list if 'success' in f])
    total_failed = len([f for f in s.file_list if 'failed' in f])

    print('\n========= Summary of your uploads ==============')
    lines = []
    if duplicate_groups:
        lines.append('Duplicates (skipping):')
        lines.append('  groups:       {}'.format(len(duplicate_groups)))
        lines.append('  total:        {}'.format(sum([len(g) for g in duplicate_groups])))
    if missing_groups:
        lines.append('Missing Required EXIF (skipping):')
        lines.append('  total:        {}'.format(sum([len(g) for g in missing_groups])))

    lines.append('Sequences:')
    lines.append('  groups:       {}'.format(len(split_groups)))
    lines.append('  total:        {}'.format(sum([len(g) for g in split_groups])))
    lines.append('Uploads:')
    lines.append('  total:        {}'.format(total_uploads))
    lines.append('  success:      {}'.format(total_success))
    lines.append('  failed:       {}'.format(total_failed))

    lines = '\n'.join(lines)
    print lines
    print("==================================================")

    print("You can now preview your uploads at http://www.mapillary.com/map/upload/im")
    print s3_bucket_list
    if not skip_upload:
        # Finalizing the upload by uploading done files for all sequence
        print("\nFinalizing upload will submit all successful uploads and ignore all failed and duplicates.")
        print("If all files were marked as successful, everything is fine, just press 'y'.")

        # ask 3 times if input is unclear
        for i in range(3):
            proceed = raw_input("Finalize upload? [y/n]: ")
            if proceed in ["y", "Y", "yes", "Yes"]:
                for s3_bucket in s3_bucket_list:
                    # upload an empty DONE file for each sequence
                    params = {"url": MAPILLARY_UPLOAD_URL,
                              "key": s3_bucket,
                              "permission": MAPILLARY_PERMISSION_HASH,
                              "signature": MAPILLARY_SIGNATURE_HASH,
                              "move_files": False}
                    upload_done_file(params)
                    print("Done uploading.")
                    # store the logs after finalizing
                break
            elif proceed in ["n", "N", "no", "No"]:
                print("Aborted. No files were submitted. Try again if you had failures.")
                break
            else:
                if i==2:
                    print("Aborted. No files were submitted. Try again if you had failures.")
                else:
                    print('Please answer y or n. Try again.')
        write_log(path)

