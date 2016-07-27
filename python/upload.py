#!/usr/bin/python

import sys
import os
import argparse
from lib.uploader import upload_file_list
from lib.sequence import Sequence
from lib.exif import verify_mapillary_tag

'''
Script for uploading images taken with the Mapillary
iOS or Android apps.

Intended use is for cases when you have multiple SD cards
or for other reasons have copied the files to a computer
and you want to bulk upload.

NB: DO NOT USE THIS ON OTHER IMAGE FILES THAN THOSE FROM
THE MAPILLARY APPS, WITHOUT PROPER TOKENS IN EXIF, UPLOADED
FILES WILL BE IGNORED SERVER-SIDE.
'''


if __name__ == '__main__':
    '''
    Usage: python upload.py [--upload_subfolders] [--delete_after_upload] path
    '''

    if sys.version_info >= (3, 0):
        raise IOError("Incompatible Python version. This script requires Python 2.x, you are using {0}.".format(sys.version_info[:2]))

    parser = argparse.ArgumentParser(description='Upload photos taken with Mapillary apps')
    parser.add_argument('path', help='path to your photos from the Mapillary app')
    parser.add_argument('--upload_subfolders', help='option to upload subfolders', action='store_true')
    parser.add_argument('--delete_after_upload', help='option to delete images after they have been successfully uploaded', action='store_true')
    args = parser.parse_args()

    path = args.path
    skip_subfolders = not args.upload_subfolders
    s = Sequence(path, skip_folders=['success'], skip_subfolders=skip_subfolders, check_exif=False)
    num_image_file = len(s.file_list)

    file_list = [f for f in s.file_list if verify_mapillary_tag(f)]

    print ("Uploading {} images with valid mapillary tags (Skipping {})".format(len(file_list), num_image_file-len(file_list)))

    if args.delete_after_upload is True:
        delete_after_upload = 1;
    else:
        delete_after_upload = 0;

    upload_file_list(file_list, delete_after_upload)

    print("Done uploading {} images.".format(len(file_list)))
