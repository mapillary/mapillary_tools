import datetime
import uuid
import os
import json
import time

from exif_read import ExifRead
from exif_write import ExifEdit
from exif_aux import verify_exif
from geo import normalize_bearing
import config
import uploader
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


def create_and_log_process(image, import_path, mapillary_description, process, verbose=False):
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
    # if the image description is empty, the process has failed
    if not mapillary_description:
        if (process != "import_meta_data_process") and (process != "user_process"):
            print("Error, " + process + " failed for image " + image)
            open(log_process_failed, "w").close()
            open(log_process_failed + "_" +
                 str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
            # if there is a success log from before, remove it
            if os.path.isfile(log_process_succes):
                os.remove(log_process_succes)
        elif(process == "import_meta_data_process"):
            # if there is a success log from before, remove it
            if os.path.isfile(log_process_succes):
                os.remove(log_process_succes)
            # if previously read import meta properties, remove them
            log_MAPJson = os.path.join(log_root, process + ".json")
            if os.path.isfile(log_MAPJson):
                if verbose:
                    print("Warning, no import meta data set for image " + image +
                          "in this import, previously generated import meta data will not be used")
                os.remove(log_MAPJson)
    # if the image description is not empty, write it in the filesystem and
    # log success
    else:
        log_MAPJson = os.path.join(
            log_root, process + ".json")
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
            open(log_process_failed, "w").close()
            open(log_process_failed + "_" +
                 str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
            if os.path.isfile(log_process_succes):
                os.remove(log_process_succes)
