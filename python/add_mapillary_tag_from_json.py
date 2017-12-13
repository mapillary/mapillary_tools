#!/usr/bin/env python

from __future__ import division
import sys
import os
import time
import json
import argparse

from lib.uploader import get_upload_token, get_authentication_info, get_project_key
from lib.exifedit import add_mapillary_description
from lib.io import progress, mkdir_p

'''
Script for reading the meta data for images from a json file and create the
Mapillary tags in Image Description (including the upload hashes)
needed to be able to upload without authentication.
'''

def get_args():
    p = argparse.ArgumentParser(description='Insert Mapillary EXIF info form an externally generated JSON file.')
    p.add_argument('file_path', help='File path to the images')
    p.add_argument('--json_path', help='Path to json file that contains metadata.')
    p.add_argument('--output_path', help='Output path for image files', default="")
    p.add_argument('--project', help='Project name at Mapillary.')
    p.add_argument('--project_key', help='Project name at Mapillary.')
    p.add_argument('--skip_authentication', help='Skip authentication', action="store_true")
    p.add_argument('--skip_validate_project', help='Skip validating project', action="store_true")

    return p.parse_args()

if __name__ == '__main__':
    '''
    Use from command line as: python add_mapillary_tag_from_json.py image_path --json_path [json_path] --project [project]
    '''

    args = get_args()
    # Retrieve/validate project key
    if not args.skip_validate_project:
        project_key = get_project_key(args.project, args.project_key)
    else:
        project_key = args.project_key or ''

    image_path = args.file_path
    json_path = args.json_path if args.json_path is not None else os.path.join(image_path, "mapillary_tag.json")
    output_path = args.output_path

    if not args.skip_authentication:
        # Fetch authentication info from env
        info = get_authentication_info()
        if info is not None:
            MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD = info
        else:
            print("You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_EMAIL or MAPILLARY_PASSWORD. These are required.")
            sys.exit()

        upload_token = get_upload_token(MAPILLARY_EMAIL, MAPILLARY_PASSWORD)
    else:
        MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD = None, None, None
        upload_token = None

    with open(json_path, "rb") as f:
        metadata = json.loads(f.read())

    mkdir_p(output_path)

    images = os.listdir(image_path)
    num_added = 0
    for i, f in enumerate(images):
        if f.lower().endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif')):
            output_file = os.path.join(output_path, os.path.basename(f))
            if f in metadata:
                add_mapillary_description(
                    os.path.join(image_path, f),
                    MAPILLARY_USERNAME,
                    MAPILLARY_EMAIL,
                    project_key,
                    upload_token,
                    metadata[f],
                    output_file)
                num_added += 1
            else:
                print "Missing metadata for {}, skipping...".format(f)
            progress(i, len(images))
        else:
            print "Ignoring {0}".format(os.path.join(image_path, f))

    with open(os.path.join(output_path, "EXIF_DONE"), "wb") as f:
        f.write(str(num_added))
