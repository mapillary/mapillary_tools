import os
import sys
import processing
import uploader
from tqdm import tqdm


def process_upload_params(import_path,
                          user_name,
                          master_upload=False,
                          verbose=False,
                          rerun=False,
                          skip_subfolders=False,
                          video_import_path=None):

    # sanity check if video file is passed
    if video_import_path and not os.path.isdir(video_import_path):
        print("Error, video path " + video_import_path +
              " does not exist, exiting...")
        sys.exit(1)

    # in case of video processing, adjust the import path
    if video_import_path:
        # set sampling path
        video_sampling_path = "mapillary_sampled_video_frames"
        import_path = os.path.join(os.path.abspath(import_path), video_sampling_path) if import_path else os.path.join(
            os.path.abspath(video_import_path), video_sampling_path)

    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " does not exist, exiting...")
        sys.exit(1)

    # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "upload_params_process",
                                                         rerun,
                                                         verbose,
                                                         skip_subfolders)
    if not len(process_file_list):
        print("No images to run upload params process")
        print("If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")

    # sanity checks
    if not user_name:
        print("Error, must provide a valid user name, exiting...")
        processing.create_and_log_process_in_list(process_file_list,
                                                  "upload_params_process"
                                                  "failed",
                                                  verbose)
        sys.exit(1)

    if not master_upload:
        try:
            credentials = uploader.authenticate_user(user_name)
        except:
            print("Error, user authentication failed for user " + user_name)
            processing.create_and_log_process_in_list(process_file_list,
                                                      "upload_params_process"
                                                      "failed",
                                                      verbose)
            sys.exit(1)
        if credentials == None or "user_upload_token" not in credentials or "user_permission_hash" not in credentials or "user_signature_hash" not in credentials:
            print("Error, user authentication failed for user " + user_name)
            processing.create_and_log_process_in_list(process_file_list,
                                                      "upload_params_process"
                                                      "failed",
                                                      verbose)
            sys.exit(1)

        user_upload_token = credentials["user_upload_token"]
        user_permission_hash = credentials["user_permission_hash"]
        user_signature_hash = credentials["user_signature_hash"]
        user_key = credentials["MAPSettingsUserKey"]

    for image in tqdm(process_file_list, desc="Processing image upload parameters"):

        # check the status of the sequence processing
        log_root = uploader.log_rootpath(image)
        duplicate_flag_path = os.path.join(log_root,
                                           "duplicate")
        upload_params_path = os.path.join(
            log_root, "upload_params_process.json")

        if os.path.isfile(upload_params_path):
            os.remove(upload_params_path)

        if os.path.isfile(duplicate_flag_path) or master_upload:
            continue

        upload_params_properties = processing.get_upload_param_properties(log_root,
                                                                          image,
                                                                          user_name,
                                                                          user_upload_token,
                                                                          user_permission_hash,
                                                                          user_signature_hash,
                                                                          user_key,
                                                                          verbose)
        processing.create_and_log_process(image,
                                          "upload_params_process",
                                          "success",
                                          upload_params_properties,
                                          verbose=verbose)
        # flag manual upload
        log_manual_upload = os.path.join(
            log_root, "manual_upload")
        open(log_manual_upload, 'a').close()

    print("Sub process ended")
