#!/usr/bin/python

from __future__ import division
import sys
import os
import time
import json
import argparse

from lib.uploader import get_upload_token, get_authentication_info, get_project_key
from lib.exifedit import add_mapillary_description

'''
Script for reading the meta data for images from a json file and create the
Mapillary tags in Image Description (including the upload hashes)
needed to be able to upload without authentication.
'''

def get_args():
    p = argparse.ArgumentParser(description='Geotag one or more photos with location and orientation from GPX file.')
    p.add_argument('file_path', help='File path to the data file that contains the metadata')
    p.add_argument('--json_path', help='Output path for the json file.')
    p.add_argument('--project', help='Project name at Mapillary.')

    return p.parse_args()

if __name__ == '__main__':
    '''
    Use from command line as: python add_mapillary_tag_from_json.py image_path --json_path [json_path] --project [project]
    '''

    # Fetch authetication info from env
    info = get_authentication_info()
    if info is not None:
        MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD = info
    else:
        print("You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_EMAIL or MAPILLARY_PASSWORD. These are required.")
        sys.exit()

    upload_token = get_upload_token(MAPILLARY_EMAIL, MAPILLARY_PASSWORD)

    args = get_args()

    image_path = args.file_path
    json_path = args.json_path if args.json_path is not None else os.path.join(image_path, "mapillary_tag.json")
    project = args.project
    project_key = get_project_key(project)

    with open(json_path, "rb") as f:
        metadata = json.loads(f.read())

    for f in os.listdir(image_path):
        if f.lower().endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif')):
            if f in metadata:
                add_mapillary_description(os.path.join(image_path, f),
                                          MAPILLARY_USERNAME,
                                          MAPILLARY_EMAIL,
                                          project_key,
                                          upload_token,
                                          metadata[f])
            else:
                print "Missing metadata for {}, skipping...".format(f)
        else:
            print "Ignoring {0}".format(os.path.join(image_path, f))
