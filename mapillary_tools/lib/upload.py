#!/usr/bin/env python

import sys
import os
import uploader
import json
from exif_aux import verify_mapillary_tag

'''
'''
LOG_FILEPATH = '.mapillary/log'


def upload(import_path, manual_done=False, skip_subfolders=False):

    # check if import path exists and exit if it doesnt
    if not os.path.isdir(import_path):
        print("Import directory does not exist")
        sys.exit()

    # get list of file to process
    total_file_list = uploader.get_total_file_list(
        import_path, skip_subfolders)
    upload_file_list = uploader.get_upload_file_list(
        import_path, skip_subfolders)
    failed_file_list = uploader.get_failed_upload_file_list(
        import_path, skip_subfolders)

    if len(failed_file_list):
        upload_failed = raw_input(
            "Retry uploading previously failed image uploads? [y/n]: ")
        # if yes, add images to the upload list
        if upload_failed in ["y", "Y", "yes", "Yes"]:
            upload_file_list.extend(failed_file_list)

    # verify the images in the upload list, they need to have the image
    # description and certain MAP properties
    upload_file_list = [f for f in upload_file_list if verify_mapillary_tag(f)]

    if not len(upload_file_list):
        print("No images to upload.")
        print("Check if images have already been uploaded or do not contain required embedded Mapillary meta data.")
        sys.exit()

    # get upload params
    params = {}
    for image in total_file_list:
        log_root = uploader.log_rootpath(import_path, image)
        upload_params_path = os.path.join(
            log_root, "upload_params_process.json")
        if os.path.isfile(upload_params_path):
            with open(upload_params_path, "rb") as jf:
                params[image] = json.load(
                    jf, object_hook=uploader.ascii_encode_dict)

    # inform how many images are to be uploaded and how many are being skipped
    # from upload
    print("Uploading {} images with valid mapillary tags (Skipping {})".format(
        len(upload_file_list), len(total_file_list) - len(upload_file_list)))

    # call the actual upload, passing the list of images, the root of the
    # import and the upload params
    uploader.upload_file_list(upload_file_list, import_path, params)

    # finalize manual uploads if necessary
    finalize_file_list = uploader.get_finalize_file_list(
        import_path, skip_subfolders)

    # if manual uploads a DONE file needs to be uploaded to let the harvester
    # know the sequence is done uploading
    if len(finalize_file_list):
        finalize_all = 1
        if manual_done:
            finalize_all = uploader.prompt_to_finalize("uploads")
        if finalize_all:
            # get the s3 locations of the sequences
            finalize_params = uploader.process_upload_finalization(
                finalize_file_list, params)
            uploader.finalize_upload(finalize_params)
            # flag finalization for each file
            uploader.flag_finalization(import_path, finalize_file_list)
        else:
            print("Uploads will not be finalized.")
            print("If you wish to finalize your uploads, run the upload tool again.")
            sys.exit()

    uploader.print_summary(upload_file_list)
