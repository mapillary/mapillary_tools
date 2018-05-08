import datetime
import uuid
import os
import json
import time
import sys
from exif_read import ExifRead
from exif_write import ExifEdit
from exif_aux import verify_exif
from geo import normalize_bearing
import config
import uploader
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


def get_process_file_list(import_path, process, rerun):
    process_file_list = []
    for root, dir, files in os.walk(import_path):
        process_file_list.extend(os.path.join(root, file) for file in files if preform_process(
            import_path, root, file, process, rerun) and file.lower().endswith(('jpg', 'jpeg', 'png', 'tif', 'tiff', 'pgm', 'pnm', 'gif')))
    return process_file_list


def preform_process(import_path, root, file, process, rerun):
    file_path = os.path.join(root, file)
    log_root = uploader.log_rootpath(import_path, file_path)
    process_succes = os.path.join(log_root, process + "_success")
    upload_succes = os.path.join(log_root, "upload_success")
    preform = not os.path.isfile(upload_succes) and (
        not os.path.isfile(process_succes) or rerun)
    return preform


def create_and_log_process_in_list(process_file_list,
                                   import_path,
                                   process,
                                   status,
                                   verbose,
                                   mapillary_description={}):
    for image in process_file_list:
        create_and_log_process(image,
                               import_path,
                               process,
                               status,
                               mapillary_description,
                               verbose)


def create_and_log_process(image, import_path, process, status, mapillary_description={}, verbose=False):
    # set log path
    log_root = uploader.log_rootpath(import_path, image)
    # make all the dirs if not there
    if not os.path.isdir(log_root):
        os.makedirs(log_root)
    # set the log flags for process
    log_process = os.path.join(
        log_root, process)
    log_process_succes = log_process + "_success"
    log_process_failed = log_process + "_failed"
    log_MAPJson = os.path.join(log_root, process + ".json")

    if status == "success" and not mapillary_description:
        status = "failed"
    elif status == "success":
        try:
            save_json(mapillary_description, log_MAPJson)
            open(log_process_succes, "w").close()
            open(log_process_succes + "_" +
                 str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
            # if there is a failed log from before, remove it
            if os.path.isfile(log_process_failed):
                os.remove(log_process_failed)
        except:
            # if the image description could not have been written to the
            # filesystem, log failed
            print("Error, " + process + " logging failed for image " + image)
            status = "failed"

    if status == "failed":
        open(log_process_failed, "w").close()
        open(log_process_failed + "_" +
             str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
        # if there is a success log from before, remove it
        if os.path.isfile(log_process_succes):
            os.remove(log_process_succes)
        # if there is meta data from before, remove it
        if os.path.isfile(log_MAPJson):
            if verbose:
                print("Warning, {} in this run has failed, previously generated properties will be removed.".format(
                    process))
            os.remove(log_MAPJson)


def process_organization(mapillary_description, organization_name, organization_key, private):
    if organization_name or organization_key:
        if not "user_upload_token" in mapillary_description or not "MAPSettingsUserKey" in mapillary_description:
            print(
                "Error, can not authenticate to validate organization import, upload token or user key missing in the config.")
            sys.exit()

    if organization_name and not organization_key:
        try:
            organization_key = uploader.get_organization_key(mapillary_description["MAPSettingsUserKey"],
                                                             organization_name,
                                                             mapillary_description["user_upload_token"])
        except:
            print("Error, could not obtain organization key, exiting...")
            sys.exit()

    if organization_key:
        # validate key
        try:
            uploader.validate_organization_key(mapillary_description["MAPSettingsUserKey"],
                                               organization_key,
                                               mapillary_description["user_upload_token"])
        except:
            print("Error, organization key validation failed, exiting...")
            sys.exit()

        # validate privacy
        try:
            uploader.validate_organization_privacy(mapillary_description["MAPSettingsUserKey"],
                                                   organization_key,
                                                   private,
                                                   mapillary_description["user_upload_token"])
        except:
            print("Error, organization privacy validation failed, exiting...")
            sys.exit()
    return organization_key


def inform_processing_start(import_path, len_process_file_list, process):
    if not len_process_file_list:
        print("No images to run {}.".format(process))
        print("If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")
        sys.exit()

    total_file_list = uploader.get_total_file_list(import_path)

    print("Running {} for {} images, skipping {} images.".format(process,
                                                                 len_process_file_list,
                                                                 len(total_file_list) - len_process_file_list))
