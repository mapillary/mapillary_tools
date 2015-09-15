#!/usr/bin/python

from __future__ import division
import sys
import urllib2, urllib
import os
from Queue import Queue
import hashlib
import uuid
import time
import json
import pyexiv2
import datetime, time
import base64

from upload import create_dirs, UploadThread, upload_file

'''
Script for reading the EXIF data from images and create the
Mapillary tags in Image Description (including the upload hashes)
needed to be able to upload without authentication.

This script will add all photos in the same folder to one sequence,
so group your photos into one subfolder per sequence (works deeply nested, too).

-root
    |
    |- seq1
    |  |- seq1_1.jpg
    |  |- seq1_2.jpg
    |  |
    |  |- seq2
    |     |- seq2_1.jpg
    |
    |- seq3
       |- seq3_1.jpg

The following EXIF tags are required:
-GPSLongitude
-GPSLatitude
-(GPSDateStamp and GPSTimeStamp) or DateTimeOriginal or DateTimeDigitized or DateTime
-Orientation

(assumes Python 2.x, for Python 3.x you need to change some module names)
'''


def dms_to_decimal(degrees, minutes, seconds, sign=' '):
    return (-1 if sign[0] in 'SWsw' else 1) * (
        float(degrees) +
        float(minutes) / 60 +
        float(seconds) / 3600
    )


def create_mapillary_desc(filename, username, email, upload_hash, sequence_uuid):
    '''
    Check that image file has the required EXIF fields.

    Incompatible files will be ignored server side.
    '''
    # required tags in IFD name convention
    required_exif = [
        ["Exif.GPSInfo.GPSLongitude"],
        ["Exif.GPSInfo.GPSLatitude"],
        ["Exif.Photo.DateTimeOriginal", "Exif.Photo.DateTimeDigitized", "Exif.Image.DateTime", "Exif.GPS.GPSDate"],
        ["Exif.Image.Orientation"]
    ]

    mapillary_infos = []

    print "Processing %s" % filename
    tags = pyexiv2.ImageMetadata(filename)
    tags.read()
    # for tag in tags:
    #     print "{0}  {1}".format(tag, tags[tag].value)

    # make sure all required tags are there
    for rexif in required_exif:
        vflag = False
        for subrexif in rexif:
            if not vflag:
                # print subrexif
                if subrexif in tags:
                    mapillary_infos.append(tags[subrexif])
                    vflag = True
        if not vflag:
            print("Missing required EXIF tag: {0}".format(subrexif))
            return False

    # write the mapillary tag
    mapillary_description = {}
    mapillary_description["MAPLongitude"] = dms_to_decimal(mapillary_infos[0].value[0], mapillary_infos[0].value[1],
                                                           mapillary_infos[0].value[2],
                                                           tags["Exif.GPSInfo.GPSLongitudeRef"].value)
    mapillary_description["MAPLatitude"] = dms_to_decimal(mapillary_infos[1].value[0], mapillary_infos[1].value[1],
                                                          mapillary_infos[1].value[2],
                                                          tags["Exif.GPSInfo.GPSLatitudeRef"].value)
    #required date format: 2015_01_14_09_37_01_000
    mapillary_description["MAPCaptureTime"] = datetime.datetime.strftime(mapillary_infos[2].value, "%Y_%m_%d_%H_%M_%S_000")
    mapillary_description["MAPOrientation"] = mapillary_infos[3].value
    heading = float(tags["Exif.GPSInfo.GPSImgDirection"].value) if "Exif.GPSInfo.GPSImgDirection" in tags else 0
    mapillary_description["MAPCompassHeading"] = {"TrueHeading": heading, "MagneticHeading": heading}
    mapillary_description["MAPSettingsUploadHash"] = upload_hash
    mapillary_description["MAPSettingsEmail"] = email
    mapillary_description["MAPSettingsUsername"] = username
    hash = hashlib.sha256("%s%s%s" % (upload_hash, email, base64.b64encode(filename))).hexdigest()
    mapillary_description['MAPSettingsUploadHash'] = hash
    mapillary_description['MAPPhotoUUID'] = str(uuid.uuid4())
    mapillary_description['MAPSequenceUUID'] = str(sequence_uuid)
    mapillary_description['MAPDeviceModel'] = tags["Exif.Photo.LensModel"].value if "Exif.Photo.LensModel" in tags else "none"
    mapillary_description['MAPDeviceMake'] = tags["Exif.Photo.LensMake"].value if "Exif.Photo.LensMake" in tags else "none"
    mapillary_description['MAPDeviceModel'] = tags["Exif.Image.Model"].value if (("Exif.Image.Model" in tags) and (mapillary_description['MAPDeviceModel'] == "none")) else "none"
    mapillary_description['MAPDeviceMake'] = tags["Exif.Image.Make"].value if ( ("Exif.Image.Make" in tags) and (mapillary_description['MAPDeviceMake'] == "none")) else "none"

    json_desc = json.dumps(mapillary_description)
    print "tag: {0}".format(json_desc)
    tags['Exif.Image.ImageDescription'] = json_desc
    tags.write()


def get_upload_token(mail, pwd):
    params = urllib.urlencode({"email": mail, "password": pwd})
    response = urllib.urlopen("https://api.mapillary.com/v1/u/login", params)
    resp = json.loads(response.read())
    return resp['upload_token']

if __name__ == '__main__':
    '''
    Use from command line as: python add_mapillary_tag_from_exif.py root_path [sequence_uuid]
    '''
    # get env variables
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_EMAIL = os.environ['MAPILLARY_EMAIL']
        MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']

    except KeyError:
        print(
        "You are missing one of the environment variables MAPILLARY_USERNAME, MAPILLARY_EMAIL or MAPILLARY_PASSWORD. These are required.")
        sys.exit()

    upload_token = get_upload_token(MAPILLARY_EMAIL, MAPILLARY_PASSWORD)

    args = sys.argv
    # print args
    if len(args) != 2:
        print("Usage: python add_mapillary_tag_from_exif.py root_path")
        raise IOError("Bad input parameters.")
    path = args[1]

    for root, sub_folders, files in os.walk(path):
        sequence_uuid = uuid.uuid4()
        print("Processing folder {0}, {1} files, sequence_id {2}.".format(root, len(files), sequence_uuid))
        for file in files:
            if file.lower().endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif')):
                create_mapillary_desc(os.path.join(root,file), MAPILLARY_USERNAME, MAPILLARY_EMAIL, upload_token, sequence_uuid)
            else:
                print "Ignoring {0}".format(os.path.join(root,file))
