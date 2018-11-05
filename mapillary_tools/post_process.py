import os
import sys
import processing
import uploader
import json
import shutil
from tqdm import tqdm
import csv
import exif_read


def save_local_mapping(import_path):
    local_mapping_filepath = os.path.join(os.path.dirname(
        import_path), import_path + "_mapillary_image_uuid_to_local_path_mapping.csv")

    total_files = uploader.get_total_file_list(import_path)

    local_mapping = []
    for file in tqdm(total_files, desc="Reading image uuids"):
        image_file_uuid = None
        relative_path = file.lstrip(os.path.abspath(import_path))
        log_rootpath = uploader.log_rootpath(file)
        image_description_json_path = os.path.join(
            log_rootpath, "mapillary_image_description.json")
        if os.path.isfile(image_description_json_path):
            image_description_json = processing.load_json(
                image_description_json_path)
            if "MAPPhotoUUID" in image_description_json:
                image_file_uuid = image_description_json["MAPPhotoUUID"]
            else:
                print(
                    "Error, photo uuid not in mapillary_image_description.json log file.")
        else:
            image_exif = exif_read.ExifRead(file)
            image_description = json.loads(
                image_exif.extract_image_description())
            if "MAPPhotoUUID" in image_description:
                image_file_uuid = str(image_description["MAPPhotoUUID"])
            else:
                print("Warning, image {} EXIF does not contain mapillary image description and mapillary_image_description.json log file does not exist. Try to process the image using mapillary_tools.".format(file))
        if image_file_uuid:
            local_mapping.append((relative_path, image_file_uuid))
    return local_mapping


def post_process(import_path,
                 split_import_path=None,
                 video_import_path=None,
                 summarize=False,
                 move_images=False,
                 move_duplicates=False,
                 move_uploaded=False,
                 save_as_json=False,
                 list_file_status=False,
                 push_images=False,
                 skip_subfolders=False,
                 verbose=False,
                 save_local_mapping=False):

    # return if nothing specified
    if not summarize and not move_images and not list_file_status and not push_images and not move_duplicates and not move_uploaded and not save_local_mapping:
        print("No post processing action specified.")
        return

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
    if save_local_mapping:
        local_mapping = save_local_mapping(import_path)
        with open(local_mapping_filepath, "w") as csvfile:
            csvwriter = csv.writer(csvfile, delimiter=",")
            for row in local_mapping:
                csvwriter.writerow(row)
    else:
        print("Reading import logs for import path {}...".format(import_path))

        # collect logs
        summary_dict = {}
        status_list_dict = {}

        total_files = uploader.get_total_file_list(import_path)
        total_files_count = len(total_files)

        # upload logs
        uploaded_files = uploader.get_success_upload_file_list(
            import_path, skip_subfolders)
        uploaded_files_count = len(uploaded_files)

        failed_upload_files = uploader.get_failed_upload_file_list(
            import_path, skip_subfolders)
        failed_upload_files_count = len(failed_upload_files)

        to_be_finalized_files = uploader.get_finalize_file_list(import_path)
        to_be_finalized_files_count = len(to_be_finalized_files)

        summary_dict["total images"] = total_files_count
        summary_dict["upload summary"] = {
            "successfully uploaded": uploaded_files_count,
            "failed uploads": failed_upload_files_count,
            "uploaded to be finalized": to_be_finalized_files_count
        }

        status_list_dict["successfully uploaded"] = uploaded_files
        status_list_dict["failed uploads"] = failed_upload_files
        status_list_dict["uploaded to be finalized"] = to_be_finalized_files

        # process logs
        summary_dict["process summary"] = {}
        process_steps = ["user_process", "import_meta_process", "geotag_process",
                         "sequence_process", "upload_params_process", "mapillary_image_description"]
        process_status = ["success", "failed"]
        for step in process_steps:

            process_success = len(processing.get_process_status_file_list(
                import_path, step, "success", skip_subfolders))
            process_failed = len(processing.get_process_status_file_list(
                import_path, step, "failed", skip_subfolders))

            summary_dict["process summary"][step] = {
                "failed": process_failed,
                "success": process_success
            }

        duplicates_file_list = processing.get_duplicate_file_list(
            import_path, skip_subfolders)
        duplicates_file_list_count = len(duplicates_file_list)

        summary_dict["process summary"]["duplicates"] = duplicates_file_list_count
        status_list_dict["duplicates"] = duplicates_file_list

        # processed for upload
        to_be_uploaded_files = uploader.get_upload_file_list(
            import_path, skip_subfolders)
        to_be_uploaded_files_count = len(to_be_uploaded_files)
        summary_dict["process summary"]["processed_not_yet_uploaded"] = to_be_uploaded_files_count
        status_list_dict["processed_not_yet_uploaded"] = to_be_uploaded_files

        # summary
        if summarize:
            print("")
            print("Import summary for import path {} :".format(import_path))
            print(json.dumps(summary_dict, indent=4))

            if save_as_json:

                try:
                    processing.save_json(summary_dict, os.path.join(
                        import_path, "mapillary_import_summary.json"))
                except Exception as e:
                    print("Could not save summary into json at {}, due to {}".format(
                        os.path.join(import_path, "mapillary_import_summary.json"), e))

        # list file status
        if list_file_status:
            print("")
            print("List of file status for import path {} :".format(import_path))
            print(json.dumps(status_list_dict, indent=4))

            if save_as_json:

                try:
                    processing.save_json(status_list_dict, os.path.join(
                        import_path, "mapillary_import_image_status_list.json"))
                except Exception as e:
                    print("Could not save image status list into json at {}, due to {}".format(
                        os.path.join(import_path, "mapillary_import_image_status_list.json"), e))

        # push images that were uploaded successfully
        # collect upload params
        if push_images:
            to_be_pushed_files = uploader.get_success_only_manual_upload_file_list(
                import_path, skip_subfolders)
            params = {}
            for image in tqdm(to_be_pushed_files, desc="Pushing images"):
                log_root = uploader.log_rootpath(image)
                upload_params_path = os.path.join(
                    log_root, "upload_params_process.json")
                if os.path.isfile(upload_params_path):
                    with open(upload_params_path, "rb") as jf:
                        params[image] = json.load(
                            jf, object_hook=uploader.ascii_encode_dict)

            # get the s3 locations of the sequences
            finalize_params = uploader.process_upload_finalization(
                to_be_pushed_files, params)
            uploader.finalize_upload(finalize_params)
            # flag finalization for each file
            uploader.flag_finalization(to_be_pushed_files)

        if move_images or move_duplicates or move_uploaded:
            print("")
            print("Note that images will be moved along with their mapillary logs in order to preserve the import status")
            defualt_split_import_path = os.path.join(
                import_path, "mapillary_import_split_images")
            if not split_import_path:
                final_split_path = defualt_split_import_path
                print("")
                print(
                    "Split import path not provided and will therefore be set to default path {}".format(defualt_split_import_path))
            if split_import_path:
                if not os.path.isfile(split_import_path):
                    final_split_path = defualt_split_import_path
                    print("Split import path does not exist, split import path will be set to default path {}".format(
                        defualt_split_import_path))
                else:
                    final_split_path = split_import_path
            print("")
            print("Splitting import path {} into {} based on image import status...".format(
                import_path, final_split_path))
            if move_images:
                move_duplicates = True
                move_uploaded = True
                # move failed uploads
                if not len(failed_upload_files):
                    print("")
                    print(
                        "There are no failed upload images in the specified import path.")
                else:
                    failed_upload_path = os.path.join(
                        final_split_path, "upload_failed")

                    if not os.path.isdir(failed_upload_path):
                        os.makedirs(failed_upload_path)

                    for failed in failed_upload_files:
                        failed_upload_image_path = os.path.join(
                            failed_upload_path, os.path.basename(failed))
                        os.rename(failed, failed_upload_path)
                        failed_upload_log_path = os.path.dirname(uploader.log_rootpath(
                            failed_upload_image_path))
                        if not os.path.isdir(failed_upload_log_path):
                            os.makedirs(failed_upload_log_path)
                        shutil.move(uploader.log_rootpath(failed),
                                    failed_upload_log_path)
                    print("")
                    print("Done moving failed upload images to {}".format(
                        failed_upload_path))
            if move_duplicates:
                if not len(duplicates_file_list):
                    print("")
                    print("There were no duplicates flagged in the specified import path. If you are processing the images with mapillary_tools and would like to flag duplicates, you must specify --advanced --flag_duplicates")
                else:
                    duplicate_path = os.path.join(
                        final_split_path, "duplicates")
                    if not os.path.isdir(duplicate_path):
                        os.makedirs(duplicate_path)
                    for duplicate in duplicates_file_list:
                        duplicate_image_path = os.path.join(
                            duplicate_path, os.path.basename(duplicate))
                        os.rename(duplicate, duplicate_image_path)
                        duplicate_log_path = os.path.dirname(uploader.log_rootpath(
                            duplicate_image_path))
                        if not os.path.isdir(duplicate_log_path):
                            os.makedirs(duplicate_log_path)
                        shutil.move(uploader.log_rootpath(duplicate),
                                    duplicate_log_path)
                    print("")
                    print("Done moving duplicate images to {}".format(
                        duplicate_path))
            if move_uploaded:
                if not len(uploaded_files):
                    print("")
                    print(
                        "There are no successfuly uploaded images in the specified import path.")
                else:
                    upload_success_path = os.path.join(
                        final_split_path, "upload_success")

                    if not os.path.isdir(upload_success_path):
                        os.makedirs(upload_success_path)

                    for uploaded in uploaded_files:
                        uploaded_image_path = os.path.join(
                            upload_success_path, os.path.basename(uploaded))
                        os.rename(uploaded, upload_success_path)
                        uploaded_log_path = os.path.dirname(uploader.log_rootpath(
                            uploaded_image_path))
                        if not os.path.isdir(uploaded_log_path):
                            os.makedirs(uploaded_log_path)
                        shutil.move(uploader.log_rootpath(uploaded),
                                    uploaded_log_path)
                    print("")
                    print("Done moving successfully uploaded images to {}".format(
                        upload_success_path))
