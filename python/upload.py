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
        description='Upload photos with the required Mapillary meta data embedded')
    parser.add_argument('path', help='path to your photos')
    args = parser.parse_args()

    # set import path
    import_path = os.path.abspath(args.path)
    # check if import path exists and exit if it doesnt
    if not os.path.isdir(import_path):
        print("Import directory doesnt not exist")
        sys.exit()

    # read in all the images in the import path
    image_list = []
    for root, dir, files in os.walk(import_path):
        image_list.extend(os.path.join(root, file) for file in files if
                          file.lower().endswith(".jpg"))
    # check if any images in the list and if not, exit
    if not len(image_list):
        print("No images in the import directory or images dont have the extension .jpg")
        sys.exit()

    # prepare upload lists
    image_upload_list = []
    failed_image_upload_list = []
    # check logs
    params = {}
    for image in image_list:
        # get the root of the image log path
        log_root = uploader.log_rootpath(import_path, image)
        # if there is no process_failed flag and no duplicate flag and no
        # upload_success flag, the image can be considered for upload
        if not os.path.isfile(os.path.join(log_root, "process_failed")) and not os.path.isfile(os.path.join(log_root, "duplicate")) and not os.path.isfile(os.path.join(log_root, "upload_success")):
            # if there is a upload_failed flag, the image was attempted to be
            # uploaded already, so it is a different use case
            if os.path.isfile(os.path.join(log_root, "upload_failed")):
                failed_image_upload_list.append(image)
            else:
                image_upload_list.append(image)
            # set the path for the potential upload params
            upload_params_path = os.path.join(log_root, "upload_params")
            # if they exist, load them to the dictionary of params, with image
            # paths as keys
            if os.path.isfile(upload_params_path):
                with open(upload_params_path, "rb") as jf:
                    params[image] = json.load(jf)

    # check if any failed uploads and prompt user if the upload should be
    # attempted again
    if len(failed_image_upload_list):
        upload_failed = raw_input(
            "Retry uploading previously failed image uploads? [y/n]: ")
        # if yes, add images to the upload list
        if upload_failed in ["y", "Y", "yes", "Yes"]:
            image_upload_list.extend(failed_image_upload_list)

    # check if any images to be uploaded, if not exit
    if not len(image_upload_list):
        print("All images have already been uploaded")
        sys.exit()

    # verify the images in the upload list, they need to have the image
    # description and certain MAP properties
    file_list = [f for f in image_upload_list if verify_mapillary_tag(f)]

    # inform how many images are to be uploaded and how many are being skipped
    # from upload
    print("Uploading {} images with valid mapillary tags (Skipping {})".format(
        len(file_list), len(image_list) - len(file_list)))

    # call the actual upload, passing the list of images, the root of the
    # import and the upload params
    uploader.upload_file_list(file_list, import_path, params)

    # inform upload has finished and print out the summary
    print("Done uploading {} images.".format(
        len(file_list)))  # improve upload summary
