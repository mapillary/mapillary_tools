import os
import time

import processing
import uploader
from exif_write import ExifEdit


def process_complete(log_root,
                     completed):
    process_complete_path = os.path.join(log_root,
                                         "process_")
    if completed:
        open(process_complete_path + "success", "w").close()
        open(process_complete_path + "success" + "_" +
             str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
        if os.path.isfile(process_complete_path + "failed"):
            os.remove(process_complete_path + "failed")
    else:
        open(process_complete_path + "failed", "w").close()
        open(process_complete_path + "failed" + "_" +
             str(time.strftime("%Y:%m:%d_%H:%M:%S", time.gmtime())), "w").close()
        if os.path.isfile(process_complete_path + "success"):
            os.remove(process_complete_path + "success")


def update_mapillary_description(final_mapillary_image_description,
                                 json_file,
                                 verbose):
    try:
        properties = processing.load_json(json_file)
        if not properties:
            if verbose:
                print("Warning, no properties read from json file " + json_file)
        if "MAPSettingsEmail" in properties:
            del properties["MAPSettingsEmail"]
        final_mapillary_image_description.update(properties)
    except:
        if verbose:
            print("Warning, could not load json file " + json_file)
    return final_mapillary_image_description


def insert_MAPJson(import_path,
                   master_upload,
                   verbose,
                   skip_insert_MAPJson,
                   rerun):

    # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "process",
                                                         rerun)

    for image in process_file_list:
        # check the processing logs
        log_root = uploader.log_rootpath(import_path,
                                         image)

        duplicate_path = os.path.join(log_root,
                                      "duplicate")

        if os.path.isfile(duplicate_path):
            continue

        user_properties_process_success_path = os.path.join(log_root,
                                                            "user_process_success")
        geotag_properties_process_success_path = os.path.join(log_root,
                                                              "geotag_process_success")
        sequence_properties_process_success_path = os.path.join(log_root,
                                                                "sequence_process_success")
        upload_params_properties_process_success_path = os.path.join(log_root,
                                                                     "upload_params_process_success")
        # optional
        import_meta_data_properties_process_success_path = os.path.join(log_root,
                                                                        "import_meta_data_process_success")

        if not os.path.isfile(user_properties_process_success_path):
            if verbose:
                print("Warning, user properties process was not a success for image " +
                      image + ", therefore the process is not complete for uploading.")
            process_complete(log_root,
                             False)
            continue
        elif not os.path.isfile(geotag_properties_process_success_path):
            if verbose:
                print("Warning, geotag process was not a success for image " +
                      image + ", therefore the process is not complete for uploading.")
            process_complete(log_root,
                             False)
            continue
        elif not os.path.isfile(sequence_properties_process_success_path):
            if verbose:
                print("Warning, sequence process was not a success for image " +
                      image + ", therefore the process is not complete for uploading.")
            process_complete(log_root,
                             False)
            continue
        elif not os.path.isfile(upload_params_properties_process_success_path) and not master_upload:
            if verbose:
                print("Warning, upload params process was not a success for image " + image +
                      " and the import is not a master upload import, therefore the process is not complete for uploading.")
            process_complete(log_root,
                             False)
            continue

        # check the existing jsons
        user_properties_process_json = os.path.join(log_root,
                                                    "user_process.json")
        import_meta_data_process_json = os.path.join(log_root,
                                                     "import_meta_data_process.json")
        geotag_properties_process_json = os.path.join(log_root,
                                                      "geotag_process.json")
        sequence_properties_process_json = os.path.join(log_root,
                                                        "sequence_process.json")
        upload_params_properties_process_json = os.path.join(log_root,
                                                             "upload_params_process.json")
        settings_upload_hash_process_json = os.path.join(log_root,
                                                         "settings_upload_hash.json")

        if not os.path.isfile(user_properties_process_json):
            if verbose:
                print("Warning, user properties process did not result in a json file for image" +
                      image + ", therefore the process is not complete for uploading.")
            process_complete(log_root,
                             False)
            continue
        elif not os.path.isfile(geotag_properties_process_success_path):
            if verbose:
                print("Warning, geotag process did not result in a json file for image " +
                      image + ", therefore the process is not complete for uploading.")
            process_complete(log_root,
                             False)
            continue
        elif not os.path.isfile(sequence_properties_process_success_path):
            if verbose:
                print("Warning, sequence process did not result in a json file for image " +
                      image + ", therefore the process is not complete for uploading.")
            process_complete(log_root,
                             False)
            continue
        elif not os.path.isfile(upload_params_properties_process_success_path) and not master_upload:
            if verbose:
                print("Warning, upload params process did not result in a json file for image " + image +
                      " and the import is not a master upload import, therefore the process is not complete for uploading.")
            process_complete(log_root,
                             False)
            continue
        elif not os.path.isfile(settings_upload_hash_process_json) and not master_upload:
            if verbose:
                print("Warning, no settings upload hash set for image " + image +
                      " and the import is not a master upload import, therefore the process is not complete for uploading.")
            process_complete(log_root,
                             False)
            continue

        # merge the existing jsons that were a success

        final_mapillary_image_description = {}

        # user properties
        final_mapillary_image_description = update_mapillary_description(final_mapillary_image_description,
                                                                         user_properties_process_json,
                                                                         verbose)
        # import properties
        # extra check for the import properties, they are not required, so only
        # a warning is issued if the json file exists but no success flag or
        # the other way around
        if (os.path.isfile(import_meta_data_process_json) and not os.path.isfile(import_meta_data_properties_process_success_path)) or (not os.path.isfile(import_meta_data_process_json) and os.path.isfile(import_meta_data_properties_process_success_path)):
            if verbose:
                print(
                    "Warning, import meta data properties not processed successfully for image " + image)
        elif os.path.isfile(import_meta_data_process_json):
            final_mapillary_image_description = update_mapillary_description(final_mapillary_image_description,
                                                                             import_meta_data_process_json,
                                                                             verbose)

        # geotag properties
        final_mapillary_image_description = update_mapillary_description(final_mapillary_image_description,
                                                                         geotag_properties_process_json,
                                                                         verbose)

        # sequence properties
        final_mapillary_image_description = update_mapillary_description(final_mapillary_image_description,
                                                                         sequence_properties_process_json,
                                                                         verbose)

        # sequence properties
        if not master_upload:
            final_mapillary_image_description = update_mapillary_description(final_mapillary_image_description,
                                                                             settings_upload_hash_process_json,
                                                                             verbose)

        if not final_mapillary_image_description:
            print("Error, Mapillary meta data not read for image " + image +
                  " , Mapillary meta data needs to be read and written in the EXIF Image Description tag in order to be uploaded.")
            process_complete(log_root,
                             False)
            continue
        else:
            try:
                processing.save_json(final_mapillary_image_description,
                                     os.path.join(log_root, "mapillary_image_description.json"))
            except:
                if verbose:
                    print(
                        "Warning, mapillary image description could not be saved into the file system for image " + image)

        # insert in the EXIF image description
        if not skip_insert_MAPJson:
            try:
                image_exif = ExifEdit(image)
            except:
                print("Error, image EXIF could not be loaded for image " + image +
                      " , Mapillary meta data needs to be written in the EXIF Image Description tag in order to be uploaded.")
                process_complete(log_root,
                                 False)
                continue
            try:
                image_exif.add_image_description(
                    final_mapillary_image_description)
            except:
                print("Error, image EXIF tag Image Description could not be edited for image " + image +
                      " , Mapillary meta data needs to be written in the EXIF Image Description tag in order to be uploaded.")
                process_complete(log_root,
                                 False)
                continue
            try:
                image_exif.write()
            except:
                print("Error, image EXIF could not be written back for image " + image +
                      " , Mapillary meta data needs to be written in the EXIF Image Description tag in order to be uploaded.")
                process_complete(log_root,
                                 False)
                continue

            # log process complete
            process_complete(log_root,
                             True)
        else:
            process_complete(log_root,
                             False)
