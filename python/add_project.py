#!/usr/bin/env python
import pyexiv2
import sys
import os
import json
import urllib
import argparse
from lib import io

reload(sys)
sys.setdefaultencoding("utf-8")

def get_args():
    parser = argparse.ArgumentParser(description='Add project id to Mapillary EXIF')
    parser.add_argument('path', help='path to your photos')
    parser.add_argument('project_name', help='name of the project')
    parser.add_argument('--overwrite', help='overwrite existing project id', action='store_true')
    args = parser.parse_args()
    return args

if __name__ == '__main__':
    '''
    Use from command line as: python add_project.py path 'project name'
    '''

    # get env variables
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_EMAIL = os.environ['MAPILLARY_EMAIL']
        MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']

    except KeyError:
        sys.exit("You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_EMAIL or MAPILLARY_PASSWORD. These are required.")

    args = get_args()
    path = args.path
    project_name = args.project_name
    overwrite = args.overwrite
    print "Adding images in %s to project '%s'" % (path, project_name)

    # log in, get the projects
    params = urllib.urlencode( {"email": MAPILLARY_EMAIL, "password": MAPILLARY_PASSWORD })
    response =urllib.urlopen("https://a.mapillary.com/v1/u/login", params)
    response_read = response.read()
    resp = json.loads(response_read)
    projects = resp['projects']
    upload_token = resp['upload_token']

    # check projects
    found = False
    print "Your projects:"
    for project in projects:
        if project['name'].decode('utf-8') == project_name:
            found = True
            project_key = project['key']

    if not found :
        for project in projects:
            print project['name']
        print "Could not find project name '%s' in your projects, exiting." % project_name
        sys.exit()

    if path.lower().endswith(".jpg"):
        # single file
        file_list = [path]
    else:
        # folder(s)
        file_list = []
        for root, sub_folders, files in os.walk(path):
            file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]

    num_file = len(file_list)
    for i, filepath in enumerate(file_list):
        base, filename = os.path.split(filepath)
        io.progress(i+1, num_file)
        exif = pyexiv2.ImageMetadata(filepath)
        exif.read()
        description_ = exif['Exif.Image.ImageDescription'].value
        imgDesc = json.loads(description_)
        if 'MAPSettingsProject' not in imgDesc or overwrite:
            imgDesc['MAPSettingsProject'] = project_key
            exif['Exif.Image.ImageDescription'].value = json.dumps(imgDesc)
            exif.write()

    print "Done, processed %s files" % len(file_list)