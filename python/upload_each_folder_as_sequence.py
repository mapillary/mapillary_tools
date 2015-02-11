__author__ = 'peterneubauer'

import sys
import os
import uuid
import urllib, urllib2
import json

reload(sys)
sys.setdefaultencoding("utf-8")

if __name__ == '__main__':
    '''
    Use from command line as: python uplaoad_each_folder_as_sequence.py path [project_name]

    This script requires sub-scripts add_mapillary_tag_from_exif.py, add_project.py and 
    upload.py
    
    You need to set the environment variables MAPILLARY_USERNAME, MAPILLARY_USERNAME,
    MAPILLARY_PASSWORD to your
    unique values.

    You also need upload.py in the same folder or in your PYTHONPATH since this
    script uses pieces of that.
    '''

    # get env variables
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_EMAIL = os.environ['MAPILLARY_EMAIL']
        MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']
    except KeyError:
        print(
        "You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD. These are required.")
        sys.exit()

    # log in, get the projects
    params = urllib.urlencode({"email": MAPILLARY_EMAIL, "password": MAPILLARY_PASSWORD})
    response = urllib.urlopen("https://api.mapillary.com/v1/u/login", params)
    resp = json.loads(response.read())
    print json.dumps(resp)
    print resp
    upload_token = resp['upload_token']

    if len(sys.argv) > 3 or len(sys.argv) < 2:
        print("Usage: python upload_each_folder_as_sequence.py path [project_name]")
        raise IOError("Bad input parameters.")
    path = sys.argv[1]

    if path.lower().endswith(".jpg"):
        # single file
        print("path must be a folder containing subfolders.")

    else:
        # folder(s)
        recursive = False
        # folder_list = next(os.walk(path))[1]
        for root, sub_folders, files in os.walk(path):
            print root
            os.environ["MAPILLARY_UPLOAD_TOKEN"] = upload_token
            os.system("python add_mapillary_tag_from_exif.py %s %s" % (
            root, uuid.uuid4()))
            if len(sys.argv) == 3:
                os.system("python add_project.py %s %s" % (root, sys.argv[2]))
                # os.system("python upload.py %s" % dir)


