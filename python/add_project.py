import pyexiv2
import sys
import os
import json
import urllib
import hashlib

if __name__ == '__main__':
    '''
    Use from command line as: python add_project.py path 'project name'
    '''

    # get env variables
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']

    except KeyError:
        print("You are missing one of the environment variables MAPILLARY_USERNAME or MAPILLARY_PASSWORD. These are required.")
        sys.exit()


    if len(sys.argv) != 3:
        print("Usage: python add_project.py path 'project name'")
        raise IOError("Bad input parameters.")

    path = sys.argv[1]
    project_name = sys.argv[2]
    print "Adding images in %s to project '%s'" % (path, project_name)

    # log in, get the projects
    params = urllib.urlencode( {"email": MAPILLARY_USERNAME, "password": MAPILLARY_PASSWORD })
    response =urllib.urlopen("https://api.mapillary.com/v1/u/login", params)
    resp = json.loads(response.read())
    # print resp
    projects = resp['projects']
    upload_token = resp['upload_token']

    #check projects
    found = False
    print "Your projects:"
    for project in projects:
        print "'%s'" % project['name']
        if project['name'] == project_name :
            found = True
            project_key = project['key']

    if not found :
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

    for filepath in file_list:
        base, filename = os.path.split(filepath)
        print "Processing %s" % filename
        exif = pyexiv2.ImageMetadata(filepath)
        exif.read()
        description_ = exif['Exif.Image.ImageDescription'].value
        imgDesc = json.loads(description_)
        imgDesc['MAPSettingsProject'] = project_key
        exif['Exif.Image.ImageDescription'].value = json.dumps(imgDesc)

        #adjust hash if needed or constructing the Mapillary info from scratch
        #hash = hashlib.sha256("%s%s%s" %(upload_token,MAPILLARY_USERNAME,filename)).hexdigest()
        #imgDesc['MAPSettingsUploadHash'] = hash
        exif.write()


    print "Done, processed %s files" % len(file_list)


