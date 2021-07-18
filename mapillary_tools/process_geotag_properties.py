import os
import sys
import typing as T

from . import processing


def process_geotag_properties(
    video_import_path: T.Optional[str] = None,
    import_path: T.Optional[str] = None,
    geotag_source="exif",
    geotag_source_path: T.Optional[str] = None,
    offset_time=0.0,
    offset_angle=0.0,
    local_time=False,
    use_gps_start_time=False,
    rerun=False,
    skip_subfolders=False,
) -> None:
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

    if not process_file_list:
        print("No images to run geotag process")
        return

    if geotag_source == "exif":
        processing.geotag_from_exif(process_file_list, offset_time, offset_angle)

    elif geotag_source == "gpx":
        if geotag_source_path is None:
            raise RuntimeError(
                "GPX file is required to be specified with --geotag_source_path"
            )
        processing.geotag_from_gpx_file(
            process_file_list,
            geotag_source_path,
            offset_time=offset_time,
            offset_angle=offset_angle,
            local_time=local_time,
            use_gps_start_time=use_gps_start_time,
        )
    elif geotag_source == "nmea":
        if geotag_source_path is None:
            raise RuntimeError(
                "NMEA file is required to be specified with --geotag_source_path"
            )
        processing.geotag_from_nmea_file(
            process_file_list,
            geotag_source_path,
            offset_time=offset_time,
            offset_angle=offset_angle,
            local_time=local_time,
            use_gps_start_time=use_gps_start_time,
        )
    elif geotag_source == "gopro_videos":
        if geotag_source_path is None:
            geotag_source_path = video_import_path
        if geotag_source_path is None:
            raise RuntimeError("geotag_source_path is required")
        processing.geotag_from_gopro_video(
            process_file_list,
            geotag_source_path,
            offset_time=offset_time,
            offset_angle=offset_angle,
            local_time=local_time,
            use_gps_start_time=use_gps_start_time,
        )
    elif geotag_source == "blackvue_videos":
        if geotag_source_path is None:
            geotag_source_path = video_import_path
        if geotag_source_path is None:
            raise RuntimeError("geotag_source_path is required")
        processing.geotag_from_blackvue_video(
            process_file_list,
            geotag_source_path,
            offset_time=offset_time,
            offset_angle=offset_angle,
            local_time=local_time,
            use_gps_start_time=use_gps_start_time,
        )
    else:
        raise RuntimeError(f"Invalid geotag source {geotag_source}")
