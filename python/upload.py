#!/usr/bin/env python

import sys
import os
import argparse
from lib import uploader
import json
from lib.sequence import Sequence
from lib.exif_aux import verify_mapillary_tag

'''
'''
LOG_FILEPATH = '.mapillary/log'

if __name__ == '__main__':
    '''
    Use from command line as: python upload.py import_path
    '''

    if sys.version_info >= (3, 0):
        raise IOError("Incompatible Python version. This script requires Python 2.x, you are using {0}.".format(
            sys.version_info[:2]))

    parser = argparse.ArgumentParser(
        description='Upload photos with the required meta data embedded')
    parser.add_argument('path', help='path to your photos')
    args = parser.parse_args()

    import_path = args.path
    # check if import path exists
    if not os.path.isdir(import_path):
        print("Import directory doesnt not exist")
        sys.exit()

    image_list = []
    for root, dir, files in os.walk(import_path):
        image_list.extend(os.path.join(root, file) for file in files if
                          file.lower().endswith(".jpg"))

    # check if any images in the list
    if not len(image_list):
        print("No images in the import directory or images dont have the extension .jpg")
        sys.exit()

    # prepare upload lists
    image_upload_list = image_list[:]
    # check for upload log
    log_filepath = os.path.join(import_path, LOG_FILEPATH)
    log = {}
    if os.path.isfile(log_filepath):
        with open(log_filepath) as jf:
            log = json.loads(jf.read())

    params = None
    # check the logged images if any
    for image in log.keys():
        image_log = log[image]
        if "uploading_log" in image_log:
            if "upload" in image_log["uploading_log"]:
                if (image_log["uploading_log"]["upload"] == "success") and (image in image_upload_list):
                    del image_upload_list[image_upload_list.index(image)]
        if "processing_log" in image_log:
            if ("process_completed" not in image_log["processing_log"]) or (("process_completed" in image_log["processing_log"]) and ("duplicate" in image_log["processing_log"])):
                del image_upload_list[image_upload_list.index(image)]
        if "upload_params" in image_log:
            params[image] = image_log["upload_params"]
    # check if any images to be uploaded
    if not len(image_upload_list):
        print("All images have already been uploaded")
        sys.exit()

    file_list = [f for f in image_upload_list if verify_mapillary_tag(f)]

    print("Uploading {} images with valid mapillary tags (Skipping {})".format(
        len(file_list), len(image_list) - len(file_list)))

    uploader.upload_file_list(file_list, import_path, params)

    print("Done uploading {} images.".format(
        len(file_list)))  # improve upload summary
