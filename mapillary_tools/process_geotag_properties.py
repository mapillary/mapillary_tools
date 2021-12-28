import logging
import os
import typing as T
import json
import datetime
import collections

import jsonschema
import piexif
from tqdm import tqdm

from . import types, exceptions, uploader, utils
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


def validate_and_fail_desc(
    desc: types.ImageDescriptionFile,
) -> types.ImageDescriptionFileOrError:
    try:
        types.validate_desc(desc)
    except jsonschema.ValidationError as exc:
        return T.cast(
            types.ImageDescriptionFileError,
            {"error": types.describe_error(exc), "filename": desc["filename"]},
        )
    else:
        return desc


def process_geotag_properties(
    import_path: str,
    geotag_source: str,
    skip_subfolders=False,
    video_import_path: T.Optional[str] = None,
    geotag_source_path: T.Optional[str] = None,
    interpolation_use_gpx_start_time: bool = False,
    interpolation_offset_time: float = 0.0,
) -> T.List[types.ImageDescriptionFileOrError]:
    if not os.path.isdir(import_path):
        raise exceptions.MapillaryFileNotFoundError(
            f"Import directory not found: {import_path}"
        )

    if geotag_source == "exif":
        images = utils.get_image_file_list(import_path, skip_subfolders=skip_subfolders)
        LOG.debug(f"Found {len(images)} images in {import_path}")
        geotag: geotag_from_generic.GeotagFromGeneric = geotag_from_exif.GeotagFromEXIF(
            import_path, images
        )

    elif geotag_source == "gpx":
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path is required"
            )
        if not os.path.isfile(geotag_source_path):
            raise exceptions.MapillaryFileNotFoundError(
                f"GPX file not found: {geotag_source_path}"
            )
        if video_import_path is None:
            images = utils.get_image_file_list(
                import_path, skip_subfolders=skip_subfolders
            )
        else:
            images = utils.get_image_file_list(
                import_path,
                skip_subfolders=False,
            )
            images = utils.filter_video_samples(
                images, video_import_path, skip_subfolders=skip_subfolders
            )
        LOG.debug(f"Found {len(images)} images in {import_path}")
        geotag = geotag_from_gpx_file.GeotagFromGPXFile(
            import_path,
            images,
            geotag_source_path,
            use_gpx_start_time=interpolation_use_gpx_start_time,
            offset_time=interpolation_offset_time,
        )
    elif geotag_source == "nmea":
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path is required"
            )
        if not os.path.isfile(geotag_source_path):
            raise exceptions.MapillaryFileNotFoundError(
                f"NMEA file not found: {geotag_source_path}"
            )
        if video_import_path is None:
            images = utils.get_image_file_list(
                import_path, skip_subfolders=skip_subfolders
            )
        else:
            images = utils.get_image_file_list(
                import_path,
                skip_subfolders=False,
            )
            images = utils.filter_video_samples(
                images, video_import_path, skip_subfolders=skip_subfolders
            )
        LOG.debug(f"Found {len(images)} images in {import_path}")
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
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path is required"
            )
        if not os.path.exists(geotag_source_path):
            raise exceptions.MapillaryFileNotFoundError(
                f"GoPro video file or directory not found: {geotag_source_path}"
            )
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
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path is required"
            )
        if not os.path.exists(geotag_source_path):
            raise exceptions.MapillaryFileNotFoundError(
                f"BlackVue video file or directory not found: {geotag_source_path}"
            )
        geotag = geotag_from_blackvue.GeotagFromBlackVue(
            import_path,
            geotag_source_path,
            use_gpx_start_time=interpolation_use_gpx_start_time,
            offset_time=interpolation_offset_time,
        )
    else:
        raise RuntimeError(f"Invalid geotag source {geotag_source}")

    descs = geotag.to_description()

    descs = list(types.map_descs(validate_and_fail_desc, descs))

    return descs


def overwrite_exif_tags(
    image_path: str,
    desc: types.ImageDescriptionEXIF,
    overwrite_all_EXIF_tags: bool = False,
    overwrite_EXIF_time_tag: bool = False,
    overwrite_EXIF_gps_tag: bool = False,
    overwrite_EXIF_direction_tag: bool = False,
    overwrite_EXIF_orientation_tag: bool = False,
) -> None:
    image_exif = ExifEdit(image_path)

    # also try to set time and gps so image can be placed on the map for testing and
    # qc purposes
    if overwrite_all_EXIF_tags or overwrite_EXIF_time_tag:
        dt = types.map_capture_time_to_datetime(desc["MAPCaptureTime"])
        image_exif.add_date_time_original(dt)

    if overwrite_all_EXIF_tags or overwrite_EXIF_gps_tag:
        image_exif.add_lat_lon(
            desc["MAPLatitude"],
            desc["MAPLongitude"],
        )

    if overwrite_all_EXIF_tags or overwrite_EXIF_direction_tag:
        heading = desc.get("MAPCompassHeading")
        if heading is not None:
            image_exif.add_direction(heading["TrueHeading"])

    if overwrite_all_EXIF_tags or overwrite_EXIF_orientation_tag:
        if "MAPOrientation" in desc:
            image_exif.add_orientation(desc["MAPOrientation"])

    image_exif.write()


def verify_exif_write(
    import_path: str,
    desc: types.ImageDescriptionFile,
) -> types.ImageDescriptionFileOrError:
    image_path = os.path.join(import_path, desc["filename"])
    with open(image_path, "rb") as fp:
        edit = ExifEdit(fp.read())
    edit.add_image_description(uploader.desc_file_to_exif(desc))
    try:
        edit.dump_image_bytes()
    except piexif.InvalidImageDataError as exc:
        return {
            "error": types.describe_error(exc),
            "filename": desc["filename"],
        }
    except Exception as exc:
        LOG.warning("Unknown error test writing image %s", image_path, exc_info=True)
        return {
            "error": types.describe_error(exc),
            "filename": desc["filename"],
        }
    else:
        return desc


def process_finalize(
    import_path: str,
    descs: T.List[types.ImageDescriptionFileOrError],
    skip_process_errors=False,
    overwrite_all_EXIF_tags=False,
    overwrite_EXIF_time_tag=False,
    overwrite_EXIF_gps_tag=False,
    overwrite_EXIF_direction_tag=False,
    overwrite_EXIF_orientation_tag=False,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    desc_path: str = None,
) -> None:
    if desc_path is None:
        desc_path = os.path.join(import_path, "mapillary_image_description.json")

    if offset_time:
        for desc in types.filter_out_errors(descs):
            dt = types.map_capture_time_to_datetime(desc["MAPCaptureTime"])
            desc["MAPCaptureTime"] = types.datetime_to_map_capture_time(
                dt + datetime.timedelta(seconds=offset_time)
            )

    for desc in types.filter_out_errors(descs):
        heading = desc.setdefault(
            "MAPCompassHeading",
            {
                "TrueHeading": 0.0,
                "MagneticHeading": 0.0,
            },
        )
        heading["TrueHeading"] = normalize_bearing(
            heading["TrueHeading"] + offset_angle
        )
        heading["MagneticHeading"] = normalize_bearing(
            heading["MagneticHeading"] + offset_angle
        )

    descs = list(types.map_descs(validate_and_fail_desc, descs))

    if any(
        [
            overwrite_all_EXIF_tags,
            overwrite_EXIF_time_tag,
            overwrite_EXIF_gps_tag,
            overwrite_EXIF_direction_tag,
            overwrite_EXIF_orientation_tag,
        ]
    ):
        for desc in tqdm(
            types.filter_out_errors(descs),
            desc="Overwriting EXIF",
            unit="images",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ):
            image = os.path.join(import_path, desc["filename"])
            try:
                overwrite_exif_tags(
                    image,
                    T.cast(types.ImageDescriptionEXIF, desc),
                    overwrite_all_EXIF_tags,
                    overwrite_EXIF_time_tag,
                    overwrite_EXIF_gps_tag,
                    overwrite_EXIF_direction_tag,
                    overwrite_EXIF_orientation_tag,
                )
            except Exception:
                LOG.warning(
                    f"Failed to overwrite EXIF for image {image}", exc_info=True
                )

    with tqdm(
        total=len(types.filter_out_errors(descs)),
        desc="Test EXIF writing",
        unit="images",
        disable=LOG.getEffectiveLevel() <= logging.DEBUG,
    ) as pbar:

        def _update(desc):
            new_desc = verify_exif_write(import_path, desc)
            pbar.update(1)
            return new_desc

        descs = list(types.map_descs(_update, descs))

    if desc_path == "-":
        print(json.dumps(descs, indent=4))
    else:
        with open(desc_path, "w") as fp:
            json.dump(descs, fp, indent=4)

    processed_images = types.filter_out_errors(descs)
    not_processed_images = T.cast(
        T.List[types.ImageDescriptionFileError],
        [desc for desc in descs if types.is_error(desc)],
    )
    assert len(processed_images) + len(not_processed_images) == len(descs)

    LOG.info("%8d images read in total", len(descs))
    if processed_images:
        LOG.info("%8d images processed and ready to be uploaded", len(processed_images))

    counter = collections.Counter(
        desc["error"].get("type") for desc in not_processed_images
    )

    duplicated_image_count = counter.get(
        exceptions.MapillaryDuplicationError.__name__, 0
    )
    if duplicated_image_count:
        LOG.warning(
            "%8d images skipped due to %s",
            duplicated_image_count,
            exceptions.MapillaryDuplicationError.__name__,
        )

    for error_code, count in counter.items():
        if error_code not in [exceptions.MapillaryDuplicationError.__name__]:
            if skip_process_errors:
                LOG.warning("%8d images skipped due to %s", count, error_code)
            else:
                LOG.warning("%8d images failed due to %s", count, error_code)

    LOG.info("Check the image description file for details: %s", desc_path)

    failed_count = len(not_processed_images) - duplicated_image_count

    if failed_count and not skip_process_errors:
        raise exceptions.MapillaryProcessError(
            f"Failed to process {failed_count} images. To skip these errors, specify --skip_process_errors"
        )
