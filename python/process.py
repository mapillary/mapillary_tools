#!/usr/bin/env python

import sys
import os
import uuid
import argparse
import json

import lib.processing_aux as process
from lib.sequence import Sequence
import lib.io

'''
Script for uploading images taken with other cameras than
the Mapillary iOS or Android apps.
It runs in the following steps:
    - Mark images that are potential duplicates and will not be uploaded
    - Group images into sequences based on gps and time
    - Interpolate compass angles for each sequence
    - Add Mapillary tags to the images
The following EXIF tags are required:
-GPSLongitude
-GPSLatitude
-(GPSDateStamp and GPSTimeStamp) or DateTimeOriginal or DateTimeDigitized or DateTime
(assumes Python 2.x, for Python 3.x you need to change some module names)
'''

MAPILLARY_UPLOAD_URL = "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.manual.images"
MAPILLARY_DIRECT_UPLOAD_URL = "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.images"


def log_file(path):
    return os.path.join(path, 'UPLOAD_LOG.txt')


def write_log(lines, path):
    with open(log_file(path), 'wb') as f:
        f.write(lines)


def read_log(path):
    if os.path.exists(log_file(path)):
        with open(log_file(path), 'rb') as f:
            lines = f.read()
    else:
        return None
    return lines


def processing_log_file(path):
    return os.path.join(path, 'PROCESSING_LOG.json')


def read_processing_log(path):
    with open(processing_log_file(path), 'rb') as f:
        log = json.loads(f.read())
    return log


def write_processing_log(log, path):
    with open(processing_log_file(path), 'wb') as f:
        f.write(json.dumps(log, indent=4))
    return log


def get_args():
    parser = argparse.ArgumentParser(
        description='Process photos to have them uploaded to Mapillary')
    parser.add_argument('path', help='path to your photos')
    parser.add_argument(
        '--rerun', help='rerun the processing', action='store_true')
    parser.add_argument("--user_name", help="user name", required=True)
    parser.add_argument('--cutoff_distance', default=600., type=float,
                        help='maximum gps distance in meters within a sequence')
    parser.add_argument('--cutoff_time', default=60., type=float,
                        help='maximum time interval in seconds within a sequence')
    parser.add_argument('--interpolate_directions',
                        help='perform interploation of directions', action='store_true')
    parser.add_argument('--offset_angle', default=0., type=float,
                        help='offset camera angle (90 for right facing, 180 for rear facing, -90 for left facing)')
    parser.add_argument('--remove_duplicates',
                        help='perform duplicate removal', action='store_true')
    parser.add_argument('--duplicate_distance',
                        help='max distance for two images to be considered duplicates in meters', default=0.1)
    parser.add_argument(
        '--duplicate_angle', help='max angle for two images to be considered duplicates in degrees', default=5)
    parser.add_argument(
        '--project', help="add project name in case validation is required", default=None)
    parser.add_argument(
        '--project_key', help="add project to EXIF (project key)", default=None)
    parser.add_argument('--skip_validate_project',
                        help="do not validate project key or projectd name", action='store_true')
    parser.add_argument(
        '--verbose', help='print debug info', action='store_true')
    parser.add_argument(
        "--device_make", help="Specify device manufacturer", default=None)
    parser.add_argument(
        "--device_model", help="Specify device model", default=None)
    parser.add_argument(
        '--add_file_name', help="add original file name to EXIF", action='store_true')
    parser.add_argument('--orientation', help='rotate images in degrees',
                        choices=[0, 90, 180, 270], type=int, default=None)
    parser.add_argument(
        "--GPS_accuracy", help="GPS accuracy in meters", default=None)
    parser.add_argument('--only_basic_processing',
                        help='run only the basic processing', action='store_true', default=False)
    parser.add_argument('--only_geotagging', help='run only the geotagging',
                        action='store_true', default=False)
    parser.add_argument('--only_sequence_processing',
                        help='run only the sequence processing', action='store_true', default=False)
    parser.add_argument('--only_QC', help='run only the quality check',
                        action='store_true', default=False)
    parser.add_argument('--only_upload_params_processing',
                        help='run only the upload params processing', action='store_true', default=False)
    parser.add_argument('--only_insert_MAPJson',
                        help='run only the insertion of MAPJsons into image EXIF tag Image Description', action='store_true', default=False)
    parser.add_argument('--skip_basic_processing',
                        help='skip only the basic processing', action='store_true', default=False)
    parser.add_argument('--skip_geotagging', help='skip only the geotagging',
                        action='store_true', default=False)
    parser.add_argument('--skip_sequence_processing',
                        help='skip only the sequence processing', action='store_true', default=False)
    parser.add_argument('--skip_QC', help='skip only the quality check',
                        action='store_true', default=False)
    parser.add_argument('--skip_upload_params_processing',
                        help='skip only the upload params processing', action='store_true', default=False)
    parser.add_argument('--skip_insert_MAPJson',
                        help='skip only the insertion of MAPJsons into image EXIF tag Image Description', action='store_true', default=False)
    parser.add_argument('--master_upload', help='Process images with a master key, note: only used by Mapillary employees',
                        action='store_true', default=False)
    parser.add_argument(
        '--geotag_source', help='Provide the source of date/time and gps information needed for geotagging.', action='store',
        choices=['exif', 'gpx', 'csv', 'json'], default="exif")
    parser.add_argument(
        '--geotag_source_path', help='Provide the path to the file source of date/time and gps information needed for geotagging.', action='store',
        default=None)
    return parser.parse_args()


if __name__ == '__main__':
    '''
    Use from command line as: python processing.py path --user_name
    '''

    if sys.version_info >= (3, 0):
        raise IOError("Incompatible Python version. This script requires Python 2.x, you are using {0}.".format(
            sys.version_info[:2]))

    args = get_args()

    # check functions to be called, TODO improve this is too much duplicate
    # code
    skip_basic_processing = args.skip_basic_processing
    skip_geotagging = args.skip_geotagging
    skip_sequence_processing = args.skip_sequence_processing
    skip_QC = args.skip_QC
    skip_upload_params_processing = args.skip_upload_params_processing
    skip_insert_MAPJson = args.skip_insert_MAPJson

    if args.only_basic_processing:
        skip_geotagging = True
        skip_QC = True
        skip_upload_params_processing = True
        skip_insert_MAPJson = True
        skip_sequence_processing = True
    if args.only_geotagging:
        skip_basic_processing = True
        skip_QC = True
        skip_upload_params_processing = True
        skip_insert_MAPJson = True
        skip_sequence_processing = True
    if args.only_QC:
        skip_geotagging = True
        skip_basic_processing = True
        skip_upload_params_processing = True
        skip_insert_MAPJson = True
        skip_sequence_processing = True
    if args.only_upload_params_processing:
        skip_basic_processing = True
        skip_QC = True
        skip_geotagging = True
        skip_insert_MAPJson = True
        skip_sequence_processing = True
    if args.only_insert_MAPJson:
        skip_geotagging = True
        skip_QC = True
        skip_upload_params_processing = True
        skip_basic_processing = True
        skip_sequence_processing = True
    if args.only_sequence_processing:
        skip_geotagging = True
        skip_QC = True
        skip_upload_params_processing = True
        skip_basic_processing = True
        skip_insert_MAPJson = True

    # import path to images
    import_path = os.path.abspath(args.path)
    if not os.path.isdir(import_path):
        print("Import directory doesnt not exist")
        sys.exit()

    # user properties
    user_name = args.user_name
    master_upload = args.master_upload

    if not user_name:
        print("Error, must provide user_name")
        sys.exit()

    # get the full image list
    full_image_list = []
    for root, dir, files in os.walk(import_path):
        full_image_list.extend(os.path.join(root, file) for file in files if
                               file.lower().endswith(".jpg"))

    # check if any images in the list
    if not len(full_image_list):
        print("No images in the import directory or images dont have the extension .jpg")
        sys.exit()

    #import properties
    device_make = args.device_make
    device_model = args.device_model
    GPS_accuracy = args.GPS_accuracy
    add_file_name = args.add_file_name
    orientation = args.orientation

    '''
    path = args.path
    cutoff_distance = args.cutoff_distance
    cutoff_time = args.cutoff_time
    offset_angle = args.offset_angle
    interpolate_directions = args.interpolate_directions
    orientation = args.orientation
    verbose = args.verbose
    add_file_name = args.add_file_name
    make = args.make
    model = args.model
    GPS_accuracy=args.GPS_accuracy
    
    # Retrieve/validate project key TODO changes here
    if not args.skip_validate_project:
        project_key = get_project_key(args.project, args.project_key)
    else:
        project_key = args.project_key or ''
    
    # Map orientation from degrees to tags
    if orientation is not None:
        orientation = format_orientation(orientation)
    
    # Distance/Angle threshold for duplicate removal
    # NOTE: This might lead to removal of panorama sequences
    min_duplicate_distance = float(args.duplicate_distance)
    min_duplicate_angle = float(args.duplicate_angle)
    
    '''
    basic_mapillary_description = {}
    if not skip_basic_processing:
        basic_mapillary_description = process.basic_processing(
            full_image_list, import_path, user_name, master_upload, orientation, device_make, device_model, GPS_accuracy, add_file_name)

    # geotag properties
    geotag_source = args.geotag_source
    geotag_source_path = args.geotag_source_path
    offset_angle = args.offset_angle
    geotagged_mapillary_descriptions = {}

    if geotag_source_path == None and geotag_source != "exif":
        print("Error, if geotagging from external log, rather than image EXIF, you need to provide full path to the log file.")
        sys.exit()

    if not skip_geotagging:
        geotagged_mapillary_descriptions = process.geotagging(
            full_image_list, import_path, geotag_source, geotag_source_path, offset_angle)

    if not skip_sequence_processing:
        # do sequence processing
        pass
    if not skip_QC:
        # do QC
        pass
    if not skip_upload_params_processing:
        # create the upload params
        pass
    if not skip_insert_MAPJson:
        # insert all in to EXIF Image Description
        pass
