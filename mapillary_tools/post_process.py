import csv
import json
import os
import sys
import typing as T

from tqdm import tqdm

from . import exif_read, types, processing
from . import ipc
from . import uploader


def map_images_to_sequences(destination_mapping, total_files):
    unique_sequence_uuids = set()
    sequence_counter = 0
    for image in tqdm(
        total_files, desc="Reading sequence information stored in log files"
    ):
        sequence_data = processing.read_sequence_process_data(image)
        if sequence_data is not None:
            sequence_uuid = sequence_data["MAPSequenceUUID"]
            if sequence_uuid not in unique_sequence_uuids:
                sequence_counter += 1
                unique_sequence_uuids.add(sequence_uuid)
            mapping = destination_mapping.setdefault(image, {})
            mapping["sequence"] = str(sequence_counter)
        else:
            print(f"MAPSequenceUUID could not be read for image {image}")

    return destination_mapping


def get_local_mapping(import_path):
    total_files = uploader.get_total_file_list(import_path)

    local_mapping = []
    for file in tqdm(total_files, desc="Reading image uuids"):
        image_file_uuid = None
        relative_path = file.lstrip(os.path.abspath(import_path))
        log_rootpath = uploader.log_rootpath(file)
        # FIXME: remove it
        image_description_json_path = os.path.join(
            log_rootpath, "mapillary_image_description.json"
        )
        if os.path.isfile(image_description_json_path):
            image_description_json = processing.load_json(image_description_json_path)
            if "MAPPhotoUUID" in image_description_json:
                image_file_uuid = image_description_json["MAPPhotoUUID"]
            else:
                print(
                    "Error, photo uuid not in mapillary_image_description.json log file."
                )
        else:
            image_exif = exif_read.ExifRead(file)
            description = image_exif.extract_image_description()
            if description is None:
                description = ""
            try:
                image_description = json.loads(description)
            except json.JSONDecodeError:
                print(
                    f"Warning, failed to JSON decoding image description {description} from {file}",
                )
                image_description = {}
            if (
                isinstance(image_description, dict)
                and "MAPPhotoUUID" in image_description
            ):
                image_file_uuid = str(image_description["MAPPhotoUUID"])
            else:
                print(
                    f"Warning, image {file} EXIF does not contain mapillary image description and mapillary_image_description.json log file does not exist. Try to process the image using mapillary_tools."
                )
        if image_file_uuid:
            local_mapping.append((relative_path, image_file_uuid))
    return local_mapping


def post_process(
    import_path,
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
    save_local_mapping=False,
):
    # sanity check if video file is passed
    if (
        video_import_path
        and not os.path.isdir(video_import_path)
        and not os.path.isfile(video_import_path)
    ):
        print("Error, video path " + video_import_path + " does not exist, exiting...")
        sys.exit(1)

    # in case of video processing, adjust the import path
    if video_import_path:
        # set sampling path
        video_sampling_path = "mapillary_sampled_video_frames"
        video_dirname = (
            video_import_path
            if os.path.isdir(video_import_path)
            else os.path.dirname(video_import_path)
        )
        import_path = (
            os.path.join(os.path.abspath(import_path), video_sampling_path)
            if import_path
            else os.path.join(os.path.abspath(video_dirname), video_sampling_path)
        )

    if move_all_images:
        move_sequences = True
        move_duplicates = True
        move_uploaded = True

    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        print("Error, import directory " + import_path + " does not exist, exiting...")
        sys.exit(1)

    if save_local_mapping:
        local_mapping = get_local_mapping(import_path)
        local_mapping_filepath = os.path.join(
            os.path.dirname(import_path),
            os.path.basename(import_path)
            + "_mapillary_image_uuid_to_local_path_mapping.csv",
        )
        with open(local_mapping_filepath, "w") as csvfile:
            csvwriter = csv.writer(csvfile, delimiter=",")
            for row in local_mapping:
                csvwriter.writerow(row)

    total_files = uploader.get_total_file_list(import_path)
    total_files_count = len(total_files)

    uploaded_files = uploader.get_success_upload_file_list(import_path, skip_subfolders)
    uploaded_files_count = len(uploaded_files)

    failed_upload_files = uploader.get_failed_upload_file_list(
        import_path, skip_subfolders
    )
    failed_upload_files_count = len(failed_upload_files)

    duplicates_file_list = processing.get_duplicate_file_list(
        import_path, skip_subfolders
    )
    duplicates_file_list_count = len(duplicates_file_list)

    to_be_uploaded_files = uploader.get_upload_file_list(import_path, skip_subfolders)
    to_be_uploaded_files_count = len(to_be_uploaded_files)

    if summarize:
        summary_dict = {
            "total images": total_files_count,
            "upload summary": {
                "successfully uploaded": uploaded_files_count,
                "failed uploads": failed_upload_files_count,
            },
            "process summary": {},
        }

        # process logs
        process_steps: T.List[types.Process] = [
            "user_process",
            "import_meta_data_process",
            "geotag_process",
            "sequence_process",
        ]

        for step in process_steps:
            process_success = len(
                processing.get_process_status_file_list(
                    import_path, step, "success", skip_subfolders
                )
            )
            process_failed = len(
                processing.get_process_status_file_list(
                    import_path, step, "failed", skip_subfolders
                )
            )
            summary_dict["process summary"][step] = {
                "failed": process_failed,
                "success": process_success,
            }
        summary_dict["process summary"]["duplicates"] = duplicates_file_list_count
        summary_dict["process summary"][
            "processed_not_yet_uploaded"
        ] = to_be_uploaded_files_count
        print(f"Import summary for import path {import_path}:")
        print(json.dumps(summary_dict, indent=4))

        ipc.send("summary", summary_dict)

        if save_as_json:
            processing.save_json(
                summary_dict,
                os.path.join(import_path, "mapillary_import_summary.json"),
            )

    if list_file_status:
        status_list_dict = {
            "successfully uploaded": uploaded_files,
            "failed uploads": failed_upload_files,
            "duplicates": duplicates_file_list,
            "processed_not_yet_uploaded": to_be_uploaded_files,
        }
        print("")
        print(f"List of file status for import path {import_path} :")
        print(json.dumps(status_list_dict, indent=4))
        if save_as_json:
            processing.save_json(
                status_list_dict,
                os.path.join(import_path, "mapillary_import_image_status_list.json"),
            )

    split_import_path = split_import_path if split_import_path else import_path
    if move_sequences or move_duplicates or move_uploaded:
        if not os.path.isdir(split_import_path):
            print(f"Split import path {split_import_path} does not exist.")
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
        for image in to_be_uploaded_files:
            if image in destination_mapping:
                destination_mapping[image]["basic"].append("to_be_uploaded")
            else:
                destination_mapping[image] = {"basic": ["to_be_uploaded"]}

    if move_sequences:
        destination_mapping = map_images_to_sequences(destination_mapping, total_files)

    for image in destination_mapping:
        basic_destination = (
            destination_mapping[image]["basic"]
            if "basic" in destination_mapping[image]
            else []
        )
        sequence_destination = (
            destination_mapping[image]["sequence"]
            if "sequence" in destination_mapping[image]
            else ""
        )
        image_destination_path = os.path.join(
            *(
                [split_import_path]
                + basic_destination
                + [os.path.dirname(image[len(os.path.abspath(import_path)) + 1 :])]
                + [sequence_destination, os.path.basename(image)]
            )
        )
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
