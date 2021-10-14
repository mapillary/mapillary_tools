import logging
import os
import typing as T
import json
import datetime

from . import image_log, types, error
from .exif_write import ExifEdit
from .geo import normalize_bearing
from .geotag import (
    geotag_from_exif,
    geotag_from_gopro,
    geotag_from_nmea_file,
    geotag_from_blackvue,
    geotag_from_gpx_file,
    geotag_from_generic,
)


LOG = logging.getLogger(__name__)


def process_geotag_properties(
    import_path: str,
    geotag_source: str,
    skip_subfolders=False,
    video_import_path: T.Optional[str] = None,
    geotag_source_path: T.Optional[str] = None,
    interpolation_use_gpx_start_time: bool = False,
    interpolation_offset_time: float = 0.0,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
) -> T.List[types.FinalImageDescriptionOrError]:
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(
            f"Error, import directory {import_path} does not exist, exiting..."
        )

    if geotag_source == "exif":
        images = image_log.get_total_file_list(
            import_path, skip_subfolders=skip_subfolders
        )
        geotag: geotag_from_generic.GeotagFromGeneric = geotag_from_exif.GeotagFromEXIF(
            import_path, images
        )

    elif geotag_source == "gpx":
        if geotag_source_path is None:
            raise RuntimeError(
                "GPX file is required to be specified with --geotag_source_path"
            )
        images = image_log.get_total_file_list(
            import_path, skip_subfolders=skip_subfolders
        )
        geotag = geotag_from_gpx_file.GeotagFromGPXFile(
            import_path,
            images,
            geotag_source_path,
        )
    elif geotag_source == "nmea":
        if geotag_source_path is None:
            raise RuntimeError(
                "NMEA file is required to be specified with --geotag_source_path"
            )
        images = image_log.get_total_file_list(
            import_path, skip_subfolders=skip_subfolders
        )
        geotag = geotag_from_nmea_file.GeotagFromNMEAFile(
            import_path,
            images,
            geotag_source_path,
            use_gpx_start_time=interpolation_use_gpx_start_time,
            offset_time=interpolation_offset_time,
        )
    elif geotag_source == "gopro_videos":
        if geotag_source_path is None:
            geotag_source_path = video_import_path
        if geotag_source_path is None:
            raise RuntimeError("geotag_source_path is required")
        geotag = geotag_from_gopro.GeotagFromGoPro(
            import_path,
            geotag_source_path,
            use_gpx_start_time=interpolation_use_gpx_start_time,
            offset_time=interpolation_offset_time,
        )
    elif geotag_source == "blackvue_videos":
        if geotag_source_path is None:
            geotag_source_path = video_import_path
        if geotag_source_path is None:
            raise RuntimeError("geotag_source_path is required")
        geotag = geotag_from_blackvue.GeotagFromBlackVue(
            import_path,
            geotag_source_path,
            use_gpx_start_time=interpolation_use_gpx_start_time,
            offset_time=interpolation_offset_time,
        )
    else:
        raise RuntimeError(f"Invalid geotag source {geotag_source}")

    descs = geotag.to_description()

    for desc in descs:
        if "error" not in desc:
            desc = T.cast(types.ImageDescriptionJSON, desc)
            if offset_time:
                dt = types.map_capture_time_to_datetime(desc["MAPCaptureTime"])
                desc["MAPCaptureTime"] = types.datetime_to_map_capture_time(
                    dt + datetime.timedelta(seconds=offset_time)
                )
            if offset_angle:
                heading = desc.get("MAPCompassHeading")
                if heading is not None:
                    heading["TrueHeading"] = normalize_bearing(
                        heading["TrueHeading"] + offset_angle
                    )
                    heading["MagneticHeading"] = normalize_bearing(
                        heading["MagneticHeading"] + offset_angle
                    )

    return descs


def overwrite_exif_tags(
    image_path: str,
    desc: types.FinalImageDescription,
    overwrite_all_EXIF_tags: bool = False,
    overwrite_EXIF_time_tag: bool = False,
    overwrite_EXIF_gps_tag: bool = False,
    overwrite_EXIF_direction_tag: bool = False,
    overwrite_EXIF_orientation_tag: bool = False,
) -> None:
    modified = False

    image_exif = ExifEdit(image_path)

    # also try to set time and gps so image can be placed on the map for testing and
    # qc purposes
    if overwrite_all_EXIF_tags or overwrite_EXIF_time_tag:
        dt = types.map_capture_time_to_datetime(desc["MAPCaptureTime"])
        image_exif.add_date_time_original(dt)
        modified = True

    if overwrite_all_EXIF_tags or overwrite_EXIF_gps_tag:
        image_exif.add_lat_lon(
            desc["MAPLatitude"],
            desc["MAPLongitude"],
        )
        modified = True

    if overwrite_all_EXIF_tags or overwrite_EXIF_direction_tag:
        heading = desc.get("MAPCompassHeading")
        if heading is not None:
            image_exif.add_direction(heading["TrueHeading"])
            modified = True

    if overwrite_all_EXIF_tags or overwrite_EXIF_orientation_tag:
        if "MAPOrientation" in desc:
            image_exif.add_orientation(desc["MAPOrientation"])
            modified = True

    if modified:
        image_exif.write()


def insert_MAPJson(
    import_path: str,
    descs: T.List[types.FinalImageDescriptionOrError],
    skip_process_errors=False,
    overwrite_all_EXIF_tags=False,
    overwrite_EXIF_time_tag=False,
    overwrite_EXIF_gps_tag=False,
    overwrite_EXIF_direction_tag=False,
    overwrite_EXIF_orientation_tag=False,
    desc_path: str = None,
) -> None:
    if desc_path is None:
        desc_path = os.path.join(import_path, "mapillary_image_description.json")

    for desc in descs:
        image = os.path.join(import_path, desc["filename"])
        try:
            overwrite_exif_tags(
                image,
                T.cast(types.FinalImageDescription, desc),
                overwrite_all_EXIF_tags,
                overwrite_EXIF_time_tag,
                overwrite_EXIF_gps_tag,
                overwrite_EXIF_direction_tag,
                overwrite_EXIF_orientation_tag,
            )
        except Exception:
            LOG.warning(f"Failed to overwrite EXIF for image {image}", exc_info=True)

    if desc_path == "-":
        print(json.dumps(descs, indent=4))
    else:
        with open(desc_path, "w") as fp:
            json.dump(descs, fp, indent=4)

    processed_images = [desc for desc in descs if "error" not in desc]
    not_processed_images = T.cast(
        T.List[types.FinalImageDescriptionError],
        [desc for desc in descs if "error" in desc],
    )
    duplicated_images = [
        desc
        for desc in not_processed_images
        if desc["error"].get("type") == error.MapillaryDuplicationError.__name__
    ]

    summary = {
        "total_images": len(descs),
        "processed_images": len(processed_images),
        "failed_images": len(not_processed_images) - len(duplicated_images),
        "duplicated_images": len(duplicated_images),
    }

    LOG.info(json.dumps(summary, indent=4))
    if 0 < summary["failed_images"]:
        if skip_process_errors:
            LOG.warning("Skipping %s failed images", summary["failed_images"])
        else:
            raise RuntimeError(
                f"Failed to process {summary['failed_images']} images. Check {desc_path} for details. Specify --skip_process_errors to skip these errors"
            )
    LOG.info(f"Check {desc_path} for details")
