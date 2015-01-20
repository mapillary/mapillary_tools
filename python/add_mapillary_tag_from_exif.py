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
Script for uploading images taken with other cameras than
the Mapillary iOS or Android apps.

Intended use is for when you have used an action camera such as a GoPro
or Garmin VIRB, or any other camera where the location is included in the image EXIF.

The following EXIF tags are required:
-GPSLongitude
-GPSLatitude
-(GPSDateStamp and GPSTimeStamp) or DateTimeOriginal or DateTimeDigitized or DateTime
-Orientation

Before uploading put all images that belong together in a sequence, in a
specific folder, for example using 'time_split.py'. All images in a session
will be considered part of a single sequence.

NB: DO NOT USE THIS SCRIPT ON IMAGE FILES FROM THE MAPILLARY APPS,
USE UPLOAD.PY INSTEAD.

(assumes Python 2.x, for Python 3.x you need to change some module names)
'''


def dms_to_decimal(degrees, minutes, seconds, sign=' '):
    """Convert degrees, minutes, seconds into decimal degrees.

    # >>> dms_to_decimal(10, 10, 10)
    10.169444444444444
    # >>> dms_to_decimal(8, 9, 10, 'S')
    -8.152777777777779
    """
    return (-1 if sign[0] in 'SWsw' else 1) * (
        float(degrees) +
        float(minutes) / 60 +
        float(seconds) / 3600
    )


def create_mapillary_desc(filename, email, upload_hash, sequence_uuid):
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
    with open(filename, 'r+') as f:
        tags = pyexiv2.ImageMetadata(filepath)
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
    mapillary_description["MAPCaptureTime"] = time.mktime(mapillary_infos[2].value.timetuple()) * 1000
    mapillary_description["MAPOrientation"] = mapillary_infos[3].value
    heading = float(tags["Exif.GPSInfo.GPSImgDirection"].value) if "Exif.GPSInfo.GPSImgDirection" in tags else 0
    mapillary_description["MAPCompassHeading"] = {"TrueHeading": heading, "MagneticHeading": heading}
    mapillary_description["MAPSettingsUploadHash"] = upload_hash
    mapillary_description["MAPSettingsEmail"] = email
    hash = hashlib.sha256("%s%s%s" % (upload_hash, email, base64.b64encode(filename))).hexdigest()
    mapillary_description['MAPSettingsUploadHash'] = hash
    mapillary_description['MAPPhotoUUID'] = str(uuid.uuid4())
    mapillary_description['MAPSequenceUUID'] = str(sequence_uuid)
    mapillary_description['MAPDeviceModel'] = tags["Exif.Photo.LensModel"].value if "Exif.Photo.LensModel" in tags else "none"
    mapillary_description['MAPDeviceMake'] = tags["Exif.Photo.LensMake"].value if "Exif.Photo.LensMake" in tags else "none"

    json_desc = json.dumps(mapillary_description)
    print "tag: {0}".format(json_desc)
    tags['Exif.Image.ImageDescription'] = json_desc
    tags.write()


if __name__ == '__main__':
    '''
    Use from command line as: python add_mapillary_tag_from_exif.py root_path [sequence_uuid]
    '''
    # get env variables
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_UPLOAD_TOKEN = os.environ['MAPILLARY_UPLOAD_TOKEN']

    except KeyError:
        print(
        "You are missing one of the environment variables MAPILLARY_USERNAME or MAPILLARY_UPLOAD_TOKEN. These are required.")
        sys.exit()
    # log in, get the projects
    # print resp

    args = sys.argv
    print args
    if len(args) < 2 or len(args) > 3:
        print("Usage: python add_mapillary_tag_from_exif.py root_path [sequence_id]")
        raise IOError("Bad input parameters.")
    path = args[1]

    if path.lower().endswith(".jpg"):
        # single file
        file_list = [path]
    else:
        # folder(s)
        file_list = []

    for root, sub_folders, files in os.walk(path):
        file_list += [os.path.join(root, filename) for filename in files if filename.lower().endswith(".jpg")]

    for filepath in file_list:
        sequence_uuid = args[2] if len(args) == 3 else uuid.uuid4()
        create_mapillary_desc(filepath, MAPILLARY_USERNAME, MAPILLARY_UPLOAD_TOKEN, sequence_uuid)
