import os
import time

import processing
import uploader
from exif_write import ExifEdit


def insert_MAPJson(import_path,
                   master_upload,
                   verbose,
                   manual_process_finalize,
                   rerun):

    # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "mapillary_image_description",
                                                         rerun)
    if verbose:
        processing.inform_processing_start(import_path,
                                           len(process_file_list),
                                           "process finalization")
    if not len(process_file_list):
        if verbose:
            print("No images to run process finalization")
            print("If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")
        return

    for image in process_file_list:
        # check the processing logs
        log_root = uploader.log_rootpath(import_path,
                                         image)

        duplicate_path = os.path.join(log_root,
                                      "duplicate")

        if os.path.isfile(duplicate_path):
            continue

        sub_commands = ["user_process", "geotag_process", "sequence_process",
                        "upload_params_process", "settings_upload_hash", "import_meta_data_process"]

        final_mapillary_image_description = {}

        mapillary_image_description_incomplete = 0
        for sub_command in sub_commands:
            sub_command_status = os.path.join(
                log_root, sub_command + "_failed")

            if os.path.isfile(sub_command_status) and sub_command != "import_meta_data_process":
                if verbose:
                    print("Warning, required {} failed for image ".format(sub_command) +
                          image)
                mapillary_image_description_incomplete = 1
                break

            sub_command_data_path = os.path.join(
                log_root, sub_command + ".json")
            if not os.path.isfile(sub_command_data_path) and sub_command != "import_meta_data_process":
                if (sub_command == "settings_upload_hash" or sub_command == "upload_params_process") and master_upload:
                    pass
                else:
                    if verbose:
                        print("Warning, required {} did not result in a valid json file for image ".format(
                            sub_command) + image)
                    mapillary_image_description_incomplete = 1
                    break
            try:
                sub_command_data = processing.load_json(sub_command_data_path)
                if not sub_command_data:
                    if verbose:
                        print(
                            "Warning, no data read from json file " + json_file)
                    mapillary_image_description_incomplete = 1
                    break

                if "MAPSettingsEmail" in sub_command_data:
                    del sub_command_data["MAPSettingsEmail"]

                final_mapillary_image_description.update(sub_command_data)
            except:
                if sub_command == "import_meta_data_process" or ((sub_command == "settings_upload_hash" or sub_command == "upload_params_process") and master_upload):
                    pass
                else:
                    if verbose:
                        print("Warning, could not load json file " +
                              sub_command_data_path)
                    mapillary_image_description_incomplete = 1
                    break

        if mapillary_image_description_incomplete:
            if verbose:
                print("Mapillary image description incomplete, image will be skipped.")
            processing.create_and_log_process(image,
                                              import_path,
                                              "mapillary_image_description",
                                              "failed",
                                              verbose=verbose)

            continue
        processing.create_and_log_process(image,
                                          import_path,
                                          "mapillary_image_description",
                                          "success",
                                          final_mapillary_image_description,
                                          verbose=verbose)

        # insert in the EXIF image description
        if manual_process_finalize:
            finalize_process = uploader.prompt_to_finalize("process")
            if not finalize_process:
                print("Mapillary image description will not be written to image EXIF.")
                processing.create_and_log_process(image,
                                                  import_path,
                                                  "mapillary_image_description",
                                                  "failed",
                                                  verbose=verbose)
                continue
        try:
            image_exif = ExifEdit(image)
        except:
            print("Error, image EXIF could not be loaded for image " + image)
            processing.create_and_log_process(image,
                                              import_path,
                                              "mapillary_image_description",
                                              "failed",
                                              verbose=verbose)
            continue
        try:
            image_exif.add_image_description(
                final_mapillary_image_description)
        except:
            print(
                "Error, image EXIF tag Image Description could not be edited for image " + image)
            processing.create_and_log_process(image,
                                              import_path,
                                              "mapillary_image_description",
                                              "failed",
                                              verbose=verbose)
            continue
        try:
            image_exif.write()
        except:
            print("Error, image EXIF could not be written back for image " + image)
            processing.create_and_log_process(image,
                                              import_path,
                                              "mapillary_image_description",
                                              "failed",
                                              verbose=verbose)
            continue
