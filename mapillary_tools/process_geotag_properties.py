import os
import sys

from . import processing
from .error import print_error


def process_geotag_properties(
    import_path,
    geotag_source="exif",
    geotag_source_path=None,
    offset_time=0.0,
    offset_angle=0.0,
    local_time=False,
    sub_second_interval=0.0,
    use_gps_start_time=False,
    verbose=False,
    rerun=False,
    skip_subfolders=False,
    video_import_path=None,
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

    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(
            f"Error, import directory {import_path} does not exist, exiting..."
        )

    # get list of file to process
    process_file_list = processing.get_process_file_list(
        import_path, "geotag_process", rerun=rerun, skip_subfolders=skip_subfolders
    )

    if not len(process_file_list):
        print("No images to run geotag process")
        print(
            "If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun"
        )

    # sanity checks
    if geotag_source_path is None and geotag_source != "exif":
        # if geotagging from external log file, path to the external log file
        # needs to be provided, if not, exit
        print_error(
            "Error, if geotagging from external log, rather than image EXIF, you need to provide full path to the log file."
        )
        processing.create_and_log_process_in_list(
            process_file_list,
            "geotag_process",
            "failed",
            verbose=verbose,
        )
        sys.exit(1)
    elif (
        geotag_source != "exif"
        and not os.path.isfile(geotag_source_path)
        and not os.path.isdir(geotag_source_path)
    ):
        print_error(
            "Error, "
            + geotag_source_path
            + " file source of gps/time properties does not exist. If geotagging from external log, rather than image EXIF, you need to provide full path to the log file."
        )
        processing.create_and_log_process_in_list(
            process_file_list, "geotag_process", "failed", verbose=verbose
        )
        sys.exit(1)

    # function calls
    if geotag_source == "exif":
        processing.geotag_from_exif(
            process_file_list, import_path, offset_time, offset_angle, verbose
        )

    elif geotag_source == "gpx" or geotag_source == "nmea":
        processing.geotag_from_gps_trace(
            process_file_list,
            geotag_source,
            geotag_source_path,
            offset_time,
            offset_angle,
            local_time,
            sub_second_interval,
            use_gps_start_time,
            verbose,
        )
    elif geotag_source == "gopro_videos":
        processing.geotag_from_gopro_video(
            process_file_list,
            import_path,
            geotag_source_path,
            offset_time,
            offset_angle,
            local_time,
            sub_second_interval,
            use_gps_start_time,
            verbose,
        )
    elif geotag_source == "blackvue_videos":
        processing.geotag_from_blackvue_video(
            process_file_list,
            import_path,
            geotag_source_path,
            offset_time,
            offset_angle,
            local_time,
            sub_second_interval,
            use_gps_start_time,
            verbose,
        )
    print("Sub process ended")
