import os
import hashlib
import base64
import time

import lib.processor as processor
import lib.uploader as uploader


def process_upload_params(full_image_list, import_path, user_name, verbose):

    try:
        credentials = uploader.authenticate_user(
            user_name, import_path)
    except:
        print("Error, user authentication failed for user " + user_name)
        return
    if "user_upload_token" not in credentials or "user_permission_hash" not in credentials or "user_signature_hash" not in credentials:
        print("Error, user authentication failed for user " + user_name)
        return

    user_upload_token = credentials["user_upload_token"]
    user_permission_hash = credentials["user_permission_hash"]
    user_signature_hash = credentials["user_signature_hash"]
    user_email = credentials["MAPSettingsEmail"]

    for image in full_image_list:
        # check the status of the sequence processing
        log_root = uploader.log_rootpath(import_path, image)
        if not os.path.isdir(log_root):
            if verbose:
                print("Warning, sequence process has not been done for image " + image +
                      ", therefore it will not be included in the upload params processing.")
            processor.create_and_log_process(
                image, import_path, {}, "upload_params_process")
            continue
        # check if geotag process was a success
        log_sequence_process_success = os.path.join(
            log_root, "sequence_process_success")
        if not os.path.isfile(log_sequence_process_success):
            if verbose:
                print("Warning, sequence process failed for image " + image +
                      ", therefore it will not be included in the upload params processing.")
            processor.create_and_log_process(
                image, import_path, {}, "upload_params_process")
            continue
        duplicate_flag_path = os.path.join(
            log_root, "duplicate")
        upload_params_process_success_path = os.path.join(
            log_root, "upload_params_process_success")
        if os.path.isfile(duplicate_flag_path):
            if verbose:
                print("Warning, duplicate flag for " + image +
                      ", therefore it will not be included in the upload params processing.")
                open(upload_params_process_success_path, "w").close()
                open(upload_params_process_success_path + "_" +
                     str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
            continue

        # load the sequence json
        sequence_process_json_path = os.path.join(
            log_root, "sequence_process.json")
        sequence_data = ""
        try:
            sequence_data = processor.load_json(
                sequence_process_json_path)
        except:
            if verbose:
                print("Warning, sequence data not read for image " + image +
                      ", therefore it will not be included in the upload params processing.")
            processor.create_and_log_process(
                image, import_path, {}, "upload_params_process")
            continue
        if "MAPSequenceUUID" in sequence_data:
            sequence_uuid = sequence_data["MAPSequenceUUID"]
            upload_params = {
                "url": "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.manual.images",
                "key": user_name + "/" + sequence_uuid + "/",
                "permission": user_permission_hash,
                "signature": user_signature_hash
            }

            try:
                settings_upload_hash = hashlib.sha256("%s%s%s" % (
                    user_upload_token, user_email, base64.b64encode(image))).hexdigest()
                processor.save_json(
                    {"MAPSettingsUploadHash": settings_upload_hash}, os.path.join(log_root, "settings_upload_hash.json"))
            except:
                if verbose:
                    print("Warning, settings upload hash not set for image " + image +
                          ", therefore it will not be uploaded.")
                processor.create_and_log_process(
                    image, import_path, {}, "upload_params_process")
                continue

            processor.create_and_log_process(
                image, import_path, upload_params, "upload_params_process")
        else:
            if verbose:
                print("Warning, sequence uuid not in sequence data for image " + image +
                      ", therefore it will not be included in the upload params processing.")
            processor.create_and_log_process(
                image, import_path, {}, "upload_params_process")
            continue
