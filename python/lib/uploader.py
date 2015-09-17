from lib.exif import EXIF, exif_gps_fields, exif_datetime_fields
from lib.geo import dms_to_decimal
import pyexiv2
import json
import os
import urllib
import datetime
import hashlib
import base64
import uuid

def create_mapillary_description(filename, username, email, upload_hash, sequence_uuid, verbose=False):
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

    if verbose:
        print ("Processing %s" % filename)

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
    if verbose:
        print "tag: {0}".format(json_desc)
    tags['Exif.Image.ImageDescription'] = json_desc
    tags.write()

def exif_gps_fields():
    '''
    GPS fields in EXIF
    '''
    return [  ["GPS GPSLongitude", "EXIF GPS GPSLongitude"],
              ["GPS GPSLatitude", "EXIF GPS GPSLatitude"] ]

def exif_datetime_fields():
    '''
    Date time fileds in EXIF
    '''
    return [["EXIF DateTimeOriginal",
            "EXIF DateTimeDigitized",
            "Image DateTime",
            "GPS GPSDate",
            "EXIF GPS GPSDate"]]

def get_upload_token(mail, pwd):
    '''
    Get upload token
    '''
    params = urllib.urlencode({"email": mail, "password": pwd})
    response = urllib.urlopen("https://api.mapillary.com/v1/u/login", params)
    resp = json.loads(response.read())
    return resp['upload_token']

def get_authentication_info():
    '''
    Get authentication information from env
    '''
    MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
    MAPILLARY_EMAIL = os.environ['MAPILLARY_EMAIL']
    MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']
    try:
        MAPILLARY_USERNAME = os.environ['MAPILLARY_USERNAME']
        MAPILLARY_EMAIL = os.environ['MAPILLARY_EMAIL']
        MAPILLARY_PASSWORD = os.environ['MAPILLARY_PASSWORD']
    except KeyError:
        return None
    return MAPILLARY_USERNAME, MAPILLARY_EMAIL, MAPILLARY_PASSWORD

def upload_done_file(params):
    print("Upload a DONE file to tell the backend that the sequence is all uploaded and ready to submit.")
    if not os.path.exists("DONE"):
        open("DONE", 'a').close()
    #upload
    upload_file("DONE", **params)
    #remove
    if os.path.exists("DONE"):
        os.remove("DONE")

def verify_exif(filename):
    '''
    Check that image file has the required EXIF fields.

    Incompatible files will be ignored server side.
    '''
    # required tags in IFD name convention
    required_exif = exif_gps_fields() + exif_datetime_fields() + [["Image Orientation"]]
    exif = EXIF(filename)
    tags = exif.tags
    required_exif_exist = exif.fileds_exist(required_exif)

    # make sure no Mapillary tags
    mapillary_tag_exists = exif.mapillary_tag_exists()
    if mapillary_tag_exists:
        print("File contains Mapillary EXIF tags, use upload.py instead.")
        return False

    return required_exif_exist