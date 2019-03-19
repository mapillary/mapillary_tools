import os
import sys
import processing
import uploader
import json
import shutil
from tqdm import tqdm
import csv
import exif_read
from . import ipc


def map_images_to_sequences(destination_mapping, total_files):
    unique_sequence_uuids = []
    sequence_counter = 0
    for image in tqdm(total_files, desc="Reading sequence information stored in log files"):
        log_root = uploader.log_rootpath(image)
        sequence_data_path = os.path.join(
            log_root, "sequence_process.json")
        sequence_uuid = ""
        sequence_data = None
        if os.path.isfile(sequence_data_path):
            sequence_data = processing.load_json(sequence_data_path)
        if sequence_data and "MAPSequenceUUID" in sequence_data:
            sequence_uuid = sequence_data["MAPSequenceUUID"]
        if sequence_uuid:
            if sequence_uuid not in unique_sequence_uuids:
                sequence_counter += 1
                unique_sequence_uuids.append(sequence_uuid)
            if image in destination_mapping:
                destination_mapping[image]["sequence"] = str(sequence_counter)
            else:
                destination_mapping[image] = {
                    "sequence": str(sequence_counter)}
        else:
            print("MAPSequenceUUID could not be read for image {}".format(image))
    return destination_mapping


def get_local_mapping(import_path):
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
                 move_all_images=False,
                 move_duplicates=False,
                 move_uploaded=False,
                 move_sequences=False,
                 save_as_json=False,
                 list_file_status=False,
                 push_images=False,
                 skip_subfolders=False,
                 verbose=False,
                 save_local_mapping=False):

    # return if nothing specified
    if not any([summarize, move_all_images, list_file_status, push_images, move_duplicates, move_uploaded, save_local_mapping, move_sequences]):
        print("No post processing action specified.")
        return

    # sanity check if video file is passed
    if video_import_path and not os.path.isdir(video_import_path) and not os.path.isfile(video_import_path):
        print("Error, video path " + video_import_path +
              " does not exist, exiting...")
        sys.exit(1)
    if move_all_images:
        move_sequences = True
        move_duplicates = True
        move_uploaded = True
    # in case of video processing, adjust the import path
    if video_import_path:
        # set sampling path
        video_sampling_path = "mapillary_sampled_video_frames"
        video_dirname = video_import_path if os.path.isdir(
            video_import_path) else os.path.dirname(video_import_path)
        import_path = os.path.join(os.path.abspath(import_path), video_sampling_path) if import_path else os.path.join(
            os.path.abspath(video_dirname), video_sampling_path)

    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " does not exist, exiting...")
        sys.exit(1)
    if save_local_mapping:
        local_mapping = get_local_mapping(import_path)
        with open(local_mapping_filepath, "w") as csvfile:
            csvwriter = csv.writer(csvfile, delimiter=",")
            for row in local_mapping:
                csvwriter.writerow(row)
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

    if any([summarize, list_file_status, move_uploaded]):
        # upload logs
        uploaded_files = uploader.get_success_upload_file_list(
            import_path, skip_subfolders)
        uploaded_files_count = len(uploaded_files)
        failed_upload_files = uploader.get_failed_upload_file_list(
            import_path, skip_subfolders)
        failed_upload_files_count = len(failed_upload_files)
        to_be_finalized_files = uploader.get_finalize_file_list(import_path)
        to_be_finalized_files_count = len(to_be_finalized_files)
        to_be_uploaded_files = uploader.get_upload_file_list(
            import_path, skip_subfolders)
        to_be_uploaded_files_count = len(to_be_uploaded_files)
    if any([summarize, move_sequences]):
        total_files = uploader.get_total_file_list(import_path)
        total_files_count = len(total_files)
    if any([summarize, move_duplicates, list_file_status]):
        duplicates_file_list = processing.get_duplicate_file_list(
            import_path, skip_subfolders)
        duplicates_file_list_count = len(duplicates_file_list)
    if summarize:
        summary_dict = {}
        summary_dict["total images"] = total_files_count
        summary_dict["upload summary"] = {
            "successfully uploaded": uploaded_files_count,
            "failed uploads": failed_upload_files_count,
            "uploaded to be finalized": to_be_finalized_files_count
        }
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
        summary_dict["process summary"]["duplicates"] = duplicates_file_list_count
        summary_dict["process summary"]["processed_not_yet_uploaded"] = to_be_uploaded_files_count
        print("Import summary for import path {} :".format(import_path))
        print(json.dumps(summary_dict, indent=4))

        ipc.send('summary', summary_dict)

        if save_as_json:
            try:
                processing.save_json(summary_dict, os.path.join(
                    import_path, "mapillary_import_summary.json"))
            except Exception as e:
                print("Could not save summary into json at {}, due to {}".format(
                    os.path.join(import_path, "mapillary_import_summary.json"), e))
    if list_file_status:
        status_list_dict = {}
        status_list_dict["successfully uploaded"] = uploaded_files
        status_list_dict["failed uploads"] = failed_upload_files
        status_list_dict["uploaded to be finalized"] = to_be_finalized_files
        status_list_dict["duplicates"] = duplicates_file_list
        status_list_dict["processed_not_yet_uploaded"] = to_be_uploaded_files
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
    split_import_path = split_import_path if split_import_path else import_path
    if any([move_sequences, move_duplicates, move_uploaded]):
        if not os.path.isdir(split_import_path):
            print("Split import path {} does not exist.".format(
                split_import_path))
            sys.exit(1)

    destination_mapping = {}
    if move_duplicates:
        for image in duplicates_file_list:
            destination_mapping[image] = {"basic": ["duplicates"]}
    if move_uploaded:
        for image in uploaded_files:
            if image in destination_mapping:
                destination_mapping[image]["basic"].append("uploaded")
            else:
                destination_mapping[image] = {"basic": ["uploaded"]}
        for image in failed_upload_files:
            if image in destination_mapping:
                destination_mapping[image]["basic"].append("failed_upload")
            else:
                destination_mapping[image] = {"basic": ["failed_upload"]}
        for image in to_be_finalized_files:
            if image in destination_mapping:
                destination_mapping[image]["basic"].append(
                    "uploaded_not_finalized")
            else:
                destination_mapping[image] = {
                    "basic": ["uploaded_not_finalized"]}
        for image in to_be_uploaded_files:
            if image in destination_mapping:
                destination_mapping[image]["basic"].append("to_be_uploaded")
            else:
                destination_mapping[image] = {"basic": ["to_be_uploaded"]}
    if move_sequences:
        destination_mapping = map_images_to_sequences(
            destination_mapping, total_files)
    for image in destination_mapping:
        basic_destination = destination_mapping[image]["basic"] if "basic" in destination_mapping[image] else [
        ]
        sequence_destination = destination_mapping[image][
            "sequence"] if "sequence" in destination_mapping[image] else ""
        image_destination_path = os.path.join(*([split_import_path] + basic_destination + [
                                              os.path.dirname(image[len(os.path.abspath(import_path)) + 1:])] + [sequence_destination, os.path.basename(image)]))
        if not os.path.isdir(os.path.dirname(image_destination_path)):
            os.makedirs(os.path.dirname(image_destination_path))
        os.rename(image, image_destination_path)
        image_logs_dir = uploader.log_rootpath(image)
        destination_logs_dir = uploader.log_rootpath(image_destination_path)
        if not os.path.isdir(image_logs_dir):
            continue
        if not os.path.isdir(os.path.dirname(destination_logs_dir)):
            os.makedirs(os.path.dirname(destination_logs_dir))
        os.rename(image_logs_dir, destination_logs_dir)
