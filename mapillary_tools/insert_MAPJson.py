import logging
import os
import sys

from tqdm import tqdm

from . import processing
from .error import print_error


LOG = logging.getLogger()


def insert_MAPJson(
    import_path,
    verbose=False,
    rerun=False,
    skip_subfolders=False,
    video_import_path=None,
    overwrite_all_EXIF_tags=False,
    overwrite_EXIF_time_tag=False,
    overwrite_EXIF_gps_tag=False,
    overwrite_EXIF_direction_tag=False,
    overwrite_EXIF_orientation_tag=False,
):
    # sanity check if video file is passed
    if (
        video_import_path
        and not os.path.isdir(video_import_path)
        and not os.path.isfile(video_import_path)
    ):
        print(f"Error, video path {video_import_path} does not exist, exiting...")
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

    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        print_error(f"Error, import directory {import_path} does not exist, exiting...")
        sys.exit(1)

    # get list of file to process
    process_file_list = processing.get_process_file_list(
        import_path,
        "mapillary_image_description",
        rerun=rerun,
        skip_subfolders=skip_subfolders,
    )
    process_file_list = [
        file for file in process_file_list if not processing.is_duplicate(file)
    ]

    if not len(process_file_list):
        print("No images to run process finalization")
        return

    for image in tqdm(
        process_file_list, unit="files", desc="Processing image description"
    ):
        final_mapillary_image_description = (
            processing.get_final_mapillary_image_description(
                image,
            )
        )

        if final_mapillary_image_description is None:
            processing.create_and_log_process(
                image,
                "mapillary_image_description",
                "failed",
                {},
                verbose=verbose,
            )
        else:
            try:
                _overwritten = processing.overwrite_exif_tags(
                    image,
                    final_mapillary_image_description,
                    overwrite_all_EXIF_tags,
                    overwrite_EXIF_time_tag,
                    overwrite_EXIF_gps_tag,
                    overwrite_EXIF_direction_tag,
                    overwrite_EXIF_orientation_tag,
                )
            except Exception:
                LOG.warning(f"Failed to overwrite EXIF", exc_info=True)

            processing.create_and_log_process(
                image,
                "mapillary_image_description",
                "success",
                final_mapillary_image_description,
                verbose=verbose,
            )
