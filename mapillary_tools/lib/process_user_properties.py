import uuid

import processing
import uploader


def finalize_user_properties_process(process_file_list,
                                     import_path,
                                     mapillary_description,
                                     verbose):
    for image in process_file_list:
        processing.create_and_log_process(image,
                                          import_path,
                                          mapillary_description,
                                          "user_process",
                                          verbose)


def process_user_properties(import_path,
                            user_name,
                            master_upload,
                            verbose,
                            rerun):

    # process specific
    if not user_name:
        print("Error, must provide a valid user name, exiting...")
        sys.exit()

    # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "user_process",
                                                         rerun)

    # process
    mapillary_description = {}
    # if not master upload, user information has to be read from config file
    if not master_upload:
        try:
            mapillary_description = uploader.authenticate_user(
                user_name, import_path)
            # remove uneeded credentials
            if "user_upload_token" in mapillary_description:
                del mapillary_description["user_upload_token"]
            if "user_permission_hash" in mapillary_description:
                del mapillary_description["user_permission_hash"]
            if "user_signature_hash" in mapillary_description:
                del mapillary_description["user_signature_hash"]
        except:
            print("Error, user authentication failed for user " + user_name)
            finalize_user_properties_process(process_file_list,
                                             import_path,
                                             {},
                                             verbose)
            return
    else:
        try:
            master_key = uploader.get_master_key()
            if master_key:
                mapillary_description["MAPVideoSecure"] = master_key
                mapillary_description["MAPSettingsUsername"] = user_name
                try:
                    user_key = uploader.get_user_key(user_name)
                    if user_key:
                        mapillary_description["MAPSettingsUserKey"] = user_key
                    else:
                        print("Error, no user key obtained for the user name " + user_name +
                              ", check if the user name is spelled correctly and if the master key is correct")
                        finalize_user_properties_process(process_file_list,
                                                         import_path,
                                                         {},
                                                         verbose)
                        return
                except:
                    print("Error, no user key obtained for the user name " + user_name +
                          ", check if the user name is spelled correctly and if the master key is correct")
                    finalize_user_properties_process(process_file_list,
                                                     import_path,
                                                     {},
                                                     verbose)
                    return
            else:
                print("Error, no master key found.")
                print("If you are a user, run the process script without the --master_upload, if you are a Mapillary employee, make sure you have the master key in your config file.")
                finalize_user_properties_process(process_file_list,
                                                 import_path,
                                                 {},
                                                 verbose)
                return
        except:
            print("Error, no master key found.")
            print("If you are a user, run the process script without the --master_upload, if you are a Mapillary employee, make sure you have the master key in your config file.")
            finalize_user_properties_process(process_file_list,
                                             import_path,
                                             {},
                                             verbose)
            return

    # a unique photo ID to check for duplicates in the backend in case the
    # image gets uploaded more than once
    mapillary_description['MAPPhotoUUID'] = str(uuid.uuid4())

    # create the json with the initial image description and log the user
    # properties process
    finalize_user_properties_process(process_file_list,
                                     import_path,
                                     mapillary_description,
                                     verbose)
