import os
import hashlib
import base64
import time

import processing
import uploader


def process_upload_params(import_path,
                          user_name,
                          master_upload,
                          verbose,
                          rerun):

    # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "upload_params_process",
                                                         rerun)
    if verbose and not master_upload:
        processing.inform_processing_start(import_path,
                                           len(process_file_list),
                                           "upload_params_process")
    if not len(process_file_list):
        if verbose:
            print("No images to run upload params process")
            print("If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")
        return

    # sanity checks
    if not user_name:
        print("Error, must provide a valid user name, exiting...")
        processing.create_and_log_process_in_list(process_file_list,
                                                  import_path,
                                                  "upload_params_process"
                                                  "failed",
                                                  verbose)
        return

    if not master_upload:
        try:
            credentials = uploader.authenticate_user(user_name)
        except:
            print("Error, user authentication failed for user " + user_name)
            processing.create_and_log_process_in_list(process_file_list,
                                                      import_path,
                                                      "upload_params_process"
                                                      "failed",
                                                      verbose)
            return
        if credentials == None or "user_upload_token" not in credentials or "user_permission_hash" not in credentials or "user_signature_hash" not in credentials:
            print("Error, user authentication failed for user " + user_name)
            processing.create_and_log_process_in_list(process_file_list,
                                                      import_path,
                                                      "upload_params_process"
                                                      "failed",
                                                      verbose)
            return

        user_upload_token = credentials["user_upload_token"]
        user_permission_hash = credentials["user_permission_hash"]
        user_signature_hash = credentials["user_signature_hash"]
        user_email = credentials["MAPSettingsEmail"]

    for image in process_file_list:
        # check the status of the sequence processing
        log_root = uploader.log_rootpath(import_path,
                                         image)
        if master_upload:
            if os.path.isfile(os.path.join(log_root, "upload_params_process.json")):
                os.remove(os.path.join(log_root, "upload_params_process.json"))
            continue
        if not os.path.isdir(log_root):
            if verbose:
                print("Warning, sequence process has not been done for image " + image +
                      ", therefore it will not be included in the upload params processing.")
                processing.create_and_log_process(image,
                                                  import_path,
                                                  "upload_params_process",
                                                  "failed",
                                                  verbose=verbose)
                continue

        # check if geotag process was a success
        log_sequence_process_success = os.path.join(
            log_root, "sequence_process_success")
        if not os.path.isfile(log_sequence_process_success):
            if verbose:
                print("Warning, sequence process failed for image " + image +
                      ", therefore it will not be included in the upload params processing.")
            processing.create_and_log_process(image,
                                              import_path,
                                              "upload_params_process",
                                              "failed",
                                              verbose=verbose)
            continue
        duplicate_flag_path = os.path.join(log_root,
                                           "duplicate")
        upload_params_process_success_path = os.path.join(log_root,
                                                          "upload_params_process_success")
        if os.path.isfile(duplicate_flag_path):
            if verbose:
                print("Warning, duplicate flag for " + image +
                      ", therefore it will not be included in the upload params processing.")
            open(upload_params_process_success_path, "w").close()
            open(upload_params_process_success_path + "_" +
                 str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
            continue

        # load the sequence json
        sequence_process_json_path = os.path.join(log_root,
                                                  "sequence_process.json")
        sequence_data = ""
        try:
            sequence_data = processing.load_json(
                sequence_process_json_path)
        except:
            if verbose:
                print("Warning, sequence data not read for image " + image +
                      ", therefore it will not be included in the upload params processing.")
            processing.create_and_log_process(image,
                                              import_path,
                                              "upload_params_process",
                                              "failed",
                                              verbose=verbose)
            continue
        if "MAPSequenceUUID" in sequence_data:
            sequence_uuid = sequence_data["MAPSequenceUUID"]
            upload_params = {
                "url": "https://s3-eu-west-1.amazonaws.com/mapillary.uploads.manual.images",
                "permission": user_permission_hash,
                "signature": user_signature_hash,
                "key": user_name + "/" + sequence_uuid + "/"
            }

            try:
                settings_upload_hash = hashlib.sha256("%s%s%s" % (user_upload_token,
                                                                  user_email,
                                                                  base64.b64encode(image))).hexdigest()
                processing.save_json({"MAPSettingsUploadHash": settings_upload_hash},
                                     os.path.join(log_root, "settings_upload_hash.json"))
            except:
                if verbose:
                    print("Warning, settings upload hash not set for image " + image +
                          ", therefore it will not be uploaded.")
                processing.create_and_log_process(image,
                                                  import_path,
                                                  "upload_params_process",
                                                  "failed",
                                                  verbose=verbose)
                continue

            processing.create_and_log_process(image,
                                              import_path,
                                              "upload_params_process",
                                              "success",
                                              upload_params,
                                              verbose=verbose)
            # flag manual upload
            log_manual_upload = os.path.join(
                log_root, "manual_upload")
            open(log_manual_upload, 'a').close()
        else:
            if verbose:
                print("Warning, sequence uuid not in sequence data for image " + image +
                      ", therefore it will not be included in the upload params processing.")
            processing.create_and_log_process(image,
                                              import_path,
                                              "upload_params_process",
                                              "failed",
                                              verbose=verbose)
            continue
