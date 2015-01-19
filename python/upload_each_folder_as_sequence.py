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

    You need to set the environment variables MAPILLARY_USERNAME,
    MAPILLARY_PASSWORD to your
    unique values.

    You also need upload.py in the same folder or in your PYTHONPATH since this
    script uses pieces of that.
    '''

    # get env variables
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']
    except KeyError:
        print("You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_PASSWORD. These are required.")
        sys.exit()

    # log in, get the projects
    params = urllib.urlencode( {"email": MAPILLARY_USERNAME, "password": MAPILLARY_PASSWORD })
    response =urllib.urlopen("https://api.mapillary.com/v1/u/login", params)
    resp = json.loads(response.read())
    print json.dumps(resp)
    print resp
    upload_token = resp['upload_token']

    if len(sys.argv) > 3 or len(sys.argv) < 2:
        print("Usage: python uplaoad_each_folder_as_sequence.py path [project_name]")
        raise IOError("Bad input parameters.")
    path = sys.argv[1]

    if path.lower().endswith(".jpg"):
        # single file
        print("path must be a folder containing subfolders.")

    else:
        # folder(s)
        recursive = False
        folder_list = next(os.walk(path))[1]
        # for root, sub_folders, files in next(os.walk(path)):

        for folder in folder_list:
            dir = os.path.join(path, folder)
            print(dir)
            # file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]
            os.system("export MAPILLARY_UPLOAD_TOKEN=%s && python add_mapillary_tag_from_exif.py %s %s" % (upload_token,dir, uuid.uuid4()))
            if len(sys.argv) == 3:
                os.system("python add_project.py %s %s" % (dir, sys.argv[2]))
            # os.system("python upload.py %s" % dir)


