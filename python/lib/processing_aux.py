import datetime
import uuid
import shutil
import hashlib
import base64

from lib.exif_read import ExifRead
from lib.exif_write import ExifEdit
from lib.exif_aux import verify_exif
from lib.geo import normalize_bearing

'''
auxillary processing functions
'''


def format_orientation(orientation):
    '''
    Convert orientation from clockwise degrees to exif tag

    # see http://sylvana.net/jpegcrop/exif_orientation.html
    '''
    mapping = {
        0: 1,
        90: 6,
        180: 3,
        270: 8,
    }
    if orientation not in mapping:
        raise ValueError("Orientation value has to be 0, 90, 180, or 270")

    return mapping[orientation]


def is_image(filename):
    return filename.lower().endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif'))


def create_mapillary_description(filename, username, email, userkey,
                                 upload_hash, sequence_uuid,
                                 interpolated_heading=None,
                                 offset_angle=0.0,
                                 timestamp=None,
                                 orientation=None,
                                 project="",
                                 secret_hash=None,
                                 external_properties=None,
                                 verbose=False,
                                 make="",
                                 model="",
                                 GPS_accuracy=""):
    '''
    Check that image file has the required EXIF fields.

    Incompatible files will be ignored server side.
    '''
    # read exif
    exif = ExifRead(filename)

    if not verify_exif(filename):
        return False

    if orientation is None:
        orientation = exif.extract_orientation()

    # write the mapillary tag
    mapillary_description = {}

    # lat, lon of the image, takes precedence over EXIF GPS values
    mapillary_description["MAPLongitude"], mapillary_description["MAPLatitude"] = exif.extract_lon_lat()

    # altitude of the image, takes precedence over EXIF GPS values, assumed 0
    # if missing
    mapillary_description["MAPAltitude"] = exif.extract_altitude()

    # capture time: required date format: 2015_01_14_09_37_01_000, TZ MUST be
    # UTC
    if timestamp is None:
        timestamp = exif.extract_capture_time()

    # The capture time of the image in UTC. Will take precedence over any
    # other time tags in the EXIF
    mapillary_description["MAPCaptureTime"] = datetime.datetime.strftime(
        timestamp, "%Y_%m_%d_%H_%M_%S_%f")[:-3]

    # EXIF orientation of the image
    mapillary_description["MAPOrientation"] = orientation
    heading = exif.extract_direction()

    if heading is None:
        heading = 0.0
    heading = normalize_bearing(
        interpolated_heading + offset_angle) if interpolated_heading is not None else normalize_bearing(heading + offset_angle)

    # bearing of the image
    mapillary_description["MAPCompassHeading"] = {
        "TrueHeading": heading, "MagneticHeading": heading}

    # authentication
    assert(email is not None or userkey is not None)
    if email is not None:
        mapillary_description["MAPSettingsEmail"] = email
    if username is not None:
        mapillary_description["MAPSettingsUsername"] = username

    # use this if available, and omit MAPSettingsUsername and MAPSettingsEmail
    # for privacy reasons
    if userkey is not None:
        mapillary_description["MAPSettingsUserKey"] = userkey
    if upload_hash is not None:
        settings_upload_hash = hashlib.sha256("%s%s%s" % (
            upload_hash, email, base64.b64encode(filename))).hexdigest()
        # this is not checked in the backend right now, will likely be changed to have user_key instead of email as part
        # of the hash
        mapillary_description['MAPSettingsUploadHash'] = settings_upload_hash

    # a unique photo ID to check for duplicates in the backend in case the
    # image gets uploaded more than once
    mapillary_description['MAPPhotoUUID'] = str(uuid.uuid4())
    # a sequene ID to make the images go together (order by MAPCaptureTime)
    mapillary_description['MAPSequenceUUID'] = str(sequence_uuid)

    # The device manufacturer
    if make:
        mapillary_description['MAPDeviceMake'] = make
    else:
        mapillary_description['MAPDeviceMake'] = exif.extract_make()

    # The device model
    if model:
        mapillary_description['MAPDeviceModel'] = model
    else:
        mapillary_description['MAPDeviceModel'] = exif.extract_model()

    if upload_hash is None and secret_hash is not None:
        mapillary_description['MAPVideoSecure'] = secret_hash

    mapillary_description["MAPSettingsProject"] = project

    # external properties (optional)
    if external_properties is not None:
        # externl proerties can be saved and searched in Mapillary later on
        mapillary_description['MAPExternalProperties'] = external_properties

    if make:
        mapillary_description['MAPDeviceMake'] = make

    if model:
        mapillary_description['MAPDeviceModel'] = model
    if GPS_accuracy:
        mapillary_description['MAPGPSAccuracyMeters'] = float(GPS_accuracy)

    # write to file
    if verbose:
        print("tag: {0}".format(mapillary_description))
    metadata = ExifEdit(filename)
    metadata.add_image_description(mapillary_description)
    metadata.add_orientation(orientation)
    metadata.add_direction(heading)
    metadata.write()


def add_exif_data(filename, data, output_file=None):
    """Add minimal exif data to an image"""
    if output_file is not None:
        shutil.copy(filename, output_file)
        filename = output_file
    metadata = ExifEdit(filename)
    metadata.add_orientation(data.get("orientation", 1))
    metadata.add_direction(data.get("bearing", 0))
    metadata.add_lat_lon(data["lat"], data["lon"])
    metadata.add_date_time_original(data["capture_time"])
    metadata.add_camera_make_model(data["make"], data["model"])
    metadata.write()
