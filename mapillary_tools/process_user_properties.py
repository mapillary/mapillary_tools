import processing
import os
import sys


def process_user_properties(import_path,
                            user_name,
                            organization_name=None,
                            organization_key=None,
                            private=False,
                            master_upload=False,
                            verbose=False,
                            rerun=False,
                            skip_subfolders=False):
    # basic check for all
    import_path = os.path.abspath(import_path)
    if not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " doesnt not exist, exiting...")
        sys.exit()

    # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "user_process",
                                                         rerun,
                                                         verbose,
                                                         skip_subfolders)
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

    # function calls
    if not master_upload:
        user_properties = processing.user_properties(user_name,
                                                     import_path,
                                                     process_file_list,
                                                     organization_name,
                                                     organization_key,
                                                     private,
                                                     verbose)
    else:
        user_properties = processing.user_properties_master(user_name,
                                                            import_path,
                                                            process_file_list,
                                                            organization_key,
                                                            private,
                                                            verbose)
    # write data and logs
    processing.create_and_log_process_in_list(process_file_list,
                                              import_path,
                                              "user_process",
                                              "success",
                                              verbose,
                                              user_properties)
