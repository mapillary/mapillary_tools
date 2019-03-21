import os
import time
import uuid
import sys
import processing
import uploader
from tqdm import tqdm

from .error import print_error

def add_EXIF_insert_arguments(parser):
    parser.add_argument('--skip_EXIF_insert',
        help='Skip inserting the extracted data into image EXIF.',
        action='store_true', default=False, required=False)
    parser.add_argument('--keep_original',
        help='Do not overwrite original images, instead save the processed images in a new directory called "processed_images" located in .mapillary in the import_path.',
        action='store_true', default=False, required=False)
    parser.add_argument('--overwrite_all_EXIF_tags',
        help='Overwrite the rest of the EXIF tags, whose values are changed during the processing. Default is False, which will result in the processed values to be inserted only in the EXIF Image Description tag.',
        action='store_true', default=False, required=False)
    parser.add_argument('--overwrite_EXIF_time_tag',
        help='Overwrite the capture time EXIF tag with the value obtained in process.',
        action='store_true', default=False, required=False)
    parser.add_argument('--overwrite_EXIF_gps_tag',
        help='Overwrite the gps EXIF tag with the value obtained in process.',
        action='store_true', default=False, required=False)
    parser.add_argument('--overwrite_EXIF_direction_tag',
        help='Overwrite the camera direction EXIF tag with the value obtained in process.',
        action='store_true', default=False, required=False)
    parser.add_argument('--overwrite_EXIF_orientation_tag',
        help='Overwrite the orientation EXIF tag with the value obtained in process.',
        action='store_true', default=False, required=False)


def insert_MAPJson(import_path,
                   master_upload=False,
                   verbose=False,
                   rerun=False,
                   skip_subfolders=False,
                   skip_EXIF_insert=False,
                   keep_original=False,
                   video_import_path=None,
                   overwrite_all_EXIF_tags=False,
                   overwrite_EXIF_time_tag=False,
                   overwrite_EXIF_gps_tag=False,
                   overwrite_EXIF_direction_tag=False,
                   overwrite_EXIF_orientation_tag=False):

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
                                                         "mapillary_image_description",
                                                         rerun,
                                                         verbose,
                                                         skip_subfolders)
    if not len(process_file_list):
        print("No images to run process finalization")
        print("If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")

    for image in tqdm(process_file_list, desc="Inserting mapillary image description in image EXIF"):
        # check the processing logs
        log_root = uploader.log_rootpath(image)

        duplicate_path = os.path.join(log_root,
                                      "duplicate")

        if os.path.isfile(duplicate_path):
            continue

        final_mapillary_image_description = processing.get_final_mapillary_image_description(log_root,
                                                                                             image,
                                                                                             master_upload,
                                                                                             verbose,
                                                                                             skip_EXIF_insert,
                                                                                             keep_original,
                                                                                             overwrite_all_EXIF_tags,
                                                                                             overwrite_EXIF_time_tag,
                                                                                             overwrite_EXIF_gps_tag,
                                                                                             overwrite_EXIF_direction_tag,
                                                                                             overwrite_EXIF_orientation_tag)

        processing.create_and_log_process(image,
                                          "mapillary_image_description",
                                          "success",
                                          final_mapillary_image_description,
                                          verbose=verbose)

    print("Sub process ended")
