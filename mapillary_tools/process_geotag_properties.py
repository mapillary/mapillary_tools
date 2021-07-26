import os
import typing as T

from . import image_log
from . import processing


def process_geotag_properties(
    import_path: T.Optional[str] = None,
    video_import_path: T.Optional[str] = None,
    geotag_source="exif",
    geotag_source_path: T.Optional[str] = None,
    offset_time=0.0,
    offset_angle=0.0,
    local_time=False,
    use_gps_start_time=False,
    rerun=False,
    skip_subfolders=False,
) -> None:
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(
            f"Error, import directory {import_path} does not exist, exiting..."
        )

    process_file_list = image_log.get_process_file_list(
        import_path,
        "mapillary_image_description",
        rerun=rerun,
        skip_subfolders=skip_subfolders,
    )

    if not process_file_list:
        print("No images to run geotag process")
        return

    if geotag_source == "exif":
        return processing.geotag_from_exif(process_file_list, offset_time, offset_angle)

    elif geotag_source == "gpx":
        if geotag_source_path is None:
            raise RuntimeError(
                "GPX file is required to be specified with --geotag_source_path"
            )
        return processing.geotag_from_gpx_file(
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
        return processing.geotag_from_nmea_file(
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
        return processing.geotag_from_gopro_video(
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
        return processing.geotag_from_blackvue_video(
            process_file_list,
            geotag_source_path,
            offset_time=offset_time,
            offset_angle=offset_angle,
            local_time=local_time,
            use_gps_start_time=use_gps_start_time,
        )
    else:
        raise RuntimeError(f"Invalid geotag source {geotag_source}")
