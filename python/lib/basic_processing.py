import os
import json
import time
from uploader import log_rootpath


def save_json(data, file_path):
    with open(file_path, "wb") as f:
        f.write(json.dumps(data, indent=4))


def create_basic_json(full_image_list, import_path, mapillary_description, add_file_name):
    for image in full_image_list:
        log_root = log_rootpath(import_path, image)
        log_MAPJson = os.path.join(
            log_root, "mapillary_image_description.json")
        log_basic_processing = os.path.join(
            log_root, "basic_process")
        if not os.path.isdir(log_root):
            os.makedirs(log_root)
        # add file name if needed
        if add_file_name:
            if 'MAPExternalProperties' in mapillary_description:
                mapillary_description['MAPExternalProperties']["original_file_name"] = image
            else:
                mapillary_description['MAPExternalProperties'] = {
                    "original_file_name": image}
        # remove hashes if there
        if "user_permission_hash" in mapillary_description:
            del mapillary_description["user_permission_hash"]
        if "user_signature_hash" in mapillary_description:
            del mapillary_description["user_signature_hash"]
        try:
            save_json(mapillary_description, log_MAPJson)
            open(log_basic_processing + "_success", "w").close()
            open(log_basic_processing + "_success_" +
                 str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
        except:
            open(log_basic_processing + "_failed", "w").close()
            open(log_basic_processing + "_failed_" +
                 str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
