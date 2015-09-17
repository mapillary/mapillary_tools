#!/usr/bin/python

import sys
import os
from lib.uploader import upload_file_list

'''
Script for uploading images taken with the Mapillary
iOS or Android apps.

Intended use is for cases when you have multiple SD cards
or for other reasons have copied the files to a computer
and you want to bulk upload.

Requires exifread, run "pip install exifread" first
(or use your favorite installer).

NB: DO NOT USE THIS ON OTHER IMAGE FILES THAN THOSE FROM
THE MAPILLARY APPS, WITHOUT PROPER TOKENS IN EXIF, UPLOADED
FILES WILL BE IGNORED SERVER-SIDE.
'''

if __name__ == '__main__':
    '''
    Use from command line as: python upload.py path
    '''

    if sys.version_info >= (3, 0):
        raise IOError("Incompatible Python version. This script requires Python 2.x, you are using {0}.".format(sys.version_info[:2]))

    if len(sys.argv) > 2:
        print("Usage: python upload.py path")
        raise IOError("Bad input parameters.")

    path = sys.argv[1]

    if path.lower().endswith(".jpg"):
        # single file
        file_list = [path]
    else:
        # folder(s)
        file_list = []
        for root, sub_folders, files in os.walk(path):
            if '/success' not in root:
                file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]

    upload_file_list(file_list)

    print("Done uploading {}.".format(len(file_list)))
