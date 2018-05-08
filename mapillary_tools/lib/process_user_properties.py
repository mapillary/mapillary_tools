import uuid
import processing
import uploader


def process_user_properties(import_path,
                            user_name,
                            organization_name,
                            organization_key,
                            private,
                            master_upload,
                            verbose,
                            rerun):

    # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "user_process",
                                                         rerun)
    if verbose:
        processing.inform_processing_start(import_path,
                                           len(process_file_list),
                                           "user process")

    if not len(process_file_list):
        if verbose:
            print("No images to run user process")
            print("If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")
        return

    # sanity checks
    if not user_name:
        print("Error, must provide a valid user name, exiting...")
        processing.create_and_log_process_in_list(process_file_list,
                                                  import_path,
                                                  "user_process",
                                                  "failed",
                                                  verbose)
        return

    if private and not organization_name and not organization_key:
        print("Error, if the import belongs to a private repository, you need to provide a valid organization name or key to which the private repository belongs to, exiting...")
        processing.create_and_log_process_in_list(process_file_list,
                                                  import_path,
                                                  "user_process",
                                                  "failed",
                                                  verbose)
        return

    # process
    mapillary_description = {}
    # if not master upload, user information has to be read from config file
    if not master_upload:

        # try to get user properties or fail
        try:
            mapillary_description = uploader.authenticate_user(user_name)
        except:
            print("Error, user authentication failed for user " + user_name)
            processing.create_and_log_process_in_list(process_file_list,
                                                      import_path,
                                                      "user_process",
                                                      "failed",
                                                      verbose)
            return
        # organization checks
        try:
            organization_key = processing.process_organization(mapillary_description,
                                                               organization_name,
                                                               organization_key,
                                                               private)
        except:
            processing.create_and_log_process_in_list(process_file_list,
                                                      import_path,
                                                      "user_process",
                                                      "failed",
                                                      verbose)
            return
        # remove uneeded credentials
        if "user_upload_token" in mapillary_description:
            del mapillary_description["user_upload_token"]
        if "user_permission_hash" in mapillary_description:
            del mapillary_description["user_permission_hash"]
        if "user_signature_hash" in mapillary_description:
            del mapillary_description["user_signature_hash"]
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
                        processing.create_and_log_process_in_list(process_file_list,
                                                                  import_path,
                                                                  "user_process",
                                                                  "failed",
                                                                  verbose)
                        return
                except:
                    print("Error, no user key obtained for the user name " + user_name +
                          ", check if the user name is spelled correctly and if the master key is correct")
                    processing.create_and_log_process_in_list(process_file_list,
                                                              import_path,
                                                              "user_process",
                                                              "failed",
                                                              verbose)
                    return
            else:
                print("Error, no master key found.")
                print("If you are a user, run the process script without the --master_upload, if you are a Mapillary employee, make sure you have the master key in your config file.")
                processing.create_and_log_process_in_list(process_file_list,
                                                          import_path,
                                                          "user_process",
                                                          "failed",
                                                          verbose)
                return
        except:
            print("Error, no master key found.")
            print("If you are a user, run the process script without the --master_upload, if you are a Mapillary employee, make sure you have the master key in your config file.")
            processing.create_and_log_process_in_list(process_file_list,
                                                      import_path,
                                                      "user_process",
                                                      "failed",
                                                      verbose)
            return

    # a unique photo ID to check for duplicates in the backend in case the
    # image gets uploaded more than once
    mapillary_description['MAPPhotoUUID'] = str(uuid.uuid4())

    # organization entries
    if organization_key:
        mapillary_description['MAPOrganizationKey'] = organization_key
    if organization_name:
        mapillary_description['MAPOrganizationName'] = organization_name
    mapillary_description['MAPPrivate'] = private

    # create the json with the initial image description and log the user
    # properties process
    processing.create_and_log_process_in_list(process_file_list,
                                              import_path,
                                              "user_process",
                                              "success",
                                              verbose,
                                              mapillary_description)
