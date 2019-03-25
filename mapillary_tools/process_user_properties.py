import processing
import os
import sys
from .error import print_error


def add_user_arguments(parser):
    parser.add_argument('--user_name',
        help='Mapillary user name for the upload.',
        required=True)

def add_organization_arguments(parser):
    parser.add_argument('--organization_username',
        help='Specify organization user name.',
        default=None, required=False)
    parser.add_argument('--organization_key',
        help='Specify organization key.',
        default=None, required=False)
    parser.add_argument('--private',
        help='Specify whether the import is private.',
        action='store_true', default=False, required=False)

def add_mapillary_arguments(parser):
    parser.add_argument('--master_upload',
        help='Process / upload performed on behalf of the specified user account. Note: only for Mapillary employee use.',
        action='store_true', default=False, required=False)


def process_user_properties(import_path,
                            user_name,
                            organization_username=None,
                            organization_key=None,
                            private=False,
                            master_upload=False,
                            verbose=False,
                            rerun=False,
                            skip_subfolders=False,
                            video_import_path=None):

    # sanity check if video file is passed
    if video_import_path and not os.path.isdir(video_import_path) and not os.path.isfile(video_import_path):
        print("Error, video path " + video_import_path +
              " does not exist, exiting...")
        sys.exit(1)

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
        print_error("Error, import directory " + import_path +
                    " does not exist, exiting...")
        sys.exit(1)

    # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "user_process",
                                                         rerun,
                                                         verbose,
                                                         skip_subfolders)
    if not len(process_file_list):
        print("No images to run user process")
        print("If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")

    # sanity checks
    if not user_name:
        print_error("Error, must provide a valid user name, exiting...")
        processing.create_and_log_process_in_list(process_file_list,
                                                  "user_process",
                                                  "failed",
                                                  verbose)
        sys.exit(1)

    if private and not organization_username and not organization_key:
        print_error("Error, if the import belongs to a private repository, you need to provide a valid organization user name or key to which the private repository belongs to, exiting...")
        processing.create_and_log_process_in_list(process_file_list,
                                                  "user_process",
                                                  "failed",
                                                  verbose)
        sys.exit(1)

    # function calls
    if not master_upload:
        user_properties = processing.user_properties(user_name,
                                                     import_path,
                                                     process_file_list,
                                                     organization_username,
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
                                              "user_process",
                                              "success",
                                              verbose,
                                              user_properties)
    print("Sub process ended")
