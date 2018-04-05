import datetime
import uuid
import shutil
import hashlib
import base64
import os
import json
import time

from lib.exif_read import ExifRead
from lib.exif_write import ExifEdit
from lib.exif_aux import verify_exif
from lib.geo import normalize_bearing
import lib.config as config
import lib.uploader as uploader
LOCAL_CONFIG_FILEPATH = uploader.LOCAL_CONFIG_FILEPATH
STATUS_PAIRS = {"success": "failed",
                "failed": "success"
                }
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


def load_json(file_path):
    try:
        with open(file_path, "rb") as f:
            dict = json.load(f)
        return dict
    except:
        return {}


def save_json(data, file_path):
    with open(file_path, "wb") as f:
        f.write(json.dumps(data, indent=4))


def update_json(data, file_path, process):
    original_data = load_json(file_path)
    original_data[process] = data
    save_json(original_data, file_path)


def basic_processing(full_image_list, import_path, user_name, master_upload, orientation, device_make, device_model, GPS_accuracy, add_file_name):
    mapillary_description = {}
    # get rest of user properties
    if not master_upload:
        mapillary_description = uploader.authenticate_user(
            user_name, import_path)
    else:
        try:
            master_key = uploader.get_master_key()  # TODO
            mapillary_description["MAPVideoSecure"] = master_key
            try:
                user_key = uploader.get_user_key(user_name, master_key)  # TODO
                mapillary_description["MAPSettingsUserKey"] = user_key
            except:
                print("Error, no user key obtained for the user name " + user_name +
                      ", check if the user name is spelled correctly and if the master key is correct")
                sys.exit()
        except:
            print("Error, no master key found.")
            print("If you are a user, run the process script without the --master_upload, if you are a Mapillary employee, make sure you have the master key in your config file.")
            sys.exit()

    # add import properties if in user args
    if orientation:
        orientation = format_orientation(orientation)
        mapillary_description["MAPOrientation"] = orientation
    if device_make:
        mapillary_description['MAPDeviceMake'] = device_make
    if device_model:
        mapillary_description['MAPDeviceModel'] = device_model
    if GPS_accuracy:
        mapillary_description['MAPGPSAccuracyMeters'] = GPS_accuracy

    # a unique photo ID to check for duplicates in the backend in case the
    # image gets uploaded more than once
    mapillary_description['MAPPhotoUUID'] = str(uuid.uuid4())

    # update local config with import properties
    if not master_upload:
        config.update_config(LOCAL_CONFIG_FILEPATH.format(
            import_path), user_name, mapillary_description)

    # verify and log basic processing
    for image in full_image_list:
        exif = ExifRead(image)
        if add_file_name:
            if 'MAPExternalProperties' in mapillary_description:
                mapillary_description['MAPExternalProperties']["original_file_name"] = image
            else:
                mapillary_description['MAPExternalProperties'] = {
                    "original_file_name": image}
        if "MAPOrientation" not in mapillary_description:
            try:
                mapillary_description["MAPOrientation"] = exif.extract_orientation(
                )
            except:
                pass
        if 'MAPDeviceMake' not in mapillary_description:
            try:
                mapillary_description["MAPDeviceMake"] = exif.extract_make(
                )
            except:
                pass
        if 'MAPDeviceModel' not in mapillary_description:
            try:
                mapillary_description["MAPDeviceModel"] = exif.extract_model(
                )
            except:
                pass
        log_full_process(
            image, import_path, mapillary_description, "basic_process")

    return mapillary_description


def log_full_process(image, import_path, mapillary_description, process):
    log_root = uploader.log_rootpath(import_path, image)
    if not os.path.isdir(log_root):
        os.makedirs(log_root)
    log_process = os.path.join(
        log_root, process)
    log_process_succes = log_process + "_success"
    log_process_failed = log_process + "_failed"
    if not mapillary_description:
        print("Error, " + process + " failed for image " + image)
        open(log_process_failed, "w").close()
        open(log_process_failed + "_" +
             str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
        if os.path.isfile(log_process_succes):
            os.remove(log_process_succes)
    else:
        log_MAPJson = os.path.join(
            log_root, process + ".json")
        try:
            save_json(mapillary_description, log_MAPJson)
            open(log_process_succes, "w").close()
            open(log_process_succes + "_" +
                 str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
            if os.path.isfile(log_process_failed):
                os.remove(log_process_failed)
        except:
            print("Error, " + process + " logging failed for image " + image)
            open(log_process_failed, "w").close()
            open(log_process_failed + "_" +
                 str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
            if os.path.isfile(log_process_succes):
                os.remove(log_process_succes)


def log_image_process(image, import_path, process, status):
    log_root = uploader.log_rootpath(import_path, image)
    if not os.path.isdir(log_root):
        os.makedirs(log_root)
    log_process = os.path.join(
        log_root, process + "_" + status)
    log_process_opposite = os.path.join(
        log_root, process + "_" + STATUS_PAIRS[status])
    open(log_process, "w").close()
    open(log_process + "_" +
         str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
    if os.path.isfile(log_process_opposite):
        os.remove(log_process_opposite)


def geotagging(full_image_list, import_path, geotag_source, geotag_source_path=None, offset_angle=0):
    mapillary_descriptions = {}
    if geotag_source == "exif":
        mapillary_descriptions = geotag_from_exif(
            full_image_list, import_path, offset_angle)
    elif geotag_source == "gpx":
        mapillary_descriptions = geotag_from_gpx(
            full_image_list, import_path, geotag_source_path, offset_angle)
    elif geotag_source == "csv":
        mapillary_descriptions = geotag_from_csv(
            full_image_list, import_path, geotag_source_path, offset_angle)
    else:
        mapillary_descriptions = geotag_from_json(
            full_image_list, import_path, geotag_source_path, offset_angle)

    return mapillary_descriptions


def geotag_from_exif(full_image_list, import_path, offset_angle):
    mapillary_descriptions = {}
    for image in full_image_list:
        if image not in mapillary_descriptions:
            mapillary_descriptions[image] = {}
        try:
            exif = ExifRead(image)
            try:
                mapillary_descriptions[image]["MAPLongitude"], mapillary_descriptions[image]["MAPLatitude"] = exif.extract_lon_lat(
                )
                try:
                    timestamp = exif.extract_capture_time()
                    mapillary_descriptions[image]["MAPCaptureTime"] = datetime.datetime.strftime(
                        timestamp, "%Y_%m_%d_%H_%M_%S_%f")[:-3]
                    # optional fields
                    try:
                        mapillary_descriptions[image]["MAPAltitude"] = exif.extract_altitude(
                        )
                    except:
                        pass
                    try:
                        heading = exif.extract_direction()
                        if heading is None:
                            heading = 0.0
                        heading = normalize_bearing(heading + offset_angle)
                        # bearing of the image
                        mapillary_description["MAPCompassHeading"] = {
                            "TrueHeading": heading, "MagneticHeading": heading}
                    except:
                        pass
                    log_full_process(
                        image, import_path, mapillary_descriptions[image], "geotagging_process")
                except:
                    print("Error, can not read capture time from the image EXIF, choose another source of information or make sure images have a valid EXIF containing capture time.")
                    log_image_process(image, import_path,
                                      "geotagging_process", "failed")
            except:
                print("Error, can not read latitude and longitude from the image EXIF, choose another source of information or make sure images have a valid EXIF containing latitude and longitude.")
                log_image_process(image, import_path,
                                  "geotagging_process", "failed")
        except:
            print("Error, can not read image EXIF, choose another source of date/time and gps information or make sure images have a valid EXIF.")
            log_image_process(image, import_path,
                              "geotagging_process", "failed")
    return mapillary_descriptions


def geotag_from_gpx(full_image_list, import_path, geotag_source_path):
    mapillary_descriptions = {}
    return mapillary_descriptions


def geotag_from_csv(full_image_list, import_path, geotag_source_path):
    mapillary_descriptions = {}
    return mapillary_descriptions


def geotag_from_json(full_image_list, import_path, geotag_source_path):
    mapillary_descriptions = {}
    return mapillary_descriptions


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

    if project:
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
