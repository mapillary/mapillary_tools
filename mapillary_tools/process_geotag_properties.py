import collections
import datetime
import json
import logging
import typing as T
from pathlib import Path

import jsonschema
import piexif
from tqdm import tqdm

from . import constants, exceptions, exif_write, types, uploader, utils
from .geotag import (
    geotag_from_blackvue,
    geotag_from_camm,
    geotag_from_exif,
    geotag_from_generic,
    geotag_from_gopro,
    geotag_from_gpx_file,
    geotag_from_nmea_file,
)


LOG = logging.getLogger(__name__)


def _validate_and_fail_desc(
    desc: types.ImageDescriptionFile,
) -> types.ImageDescriptionFileOrError:
    try:
        types.validate_desc(desc)
    except jsonschema.ValidationError as exc:
        return types.describe_error(exc, desc["filename"])
    else:
        return desc


def process_geotag_properties(
    import_path: T.Union[Path, T.Sequence[Path]],
    geotag_source: str,
    skip_subfolders=False,
    video_import_path: T.Optional[Path] = None,
    geotag_source_path: T.Optional[Path] = None,
    interpolation_use_gpx_start_time: bool = False,
    interpolation_offset_time: float = 0.0,
) -> T.List[types.ImageDescriptionFileOrError]:
    import_paths: T.Sequence[Path]
    if isinstance(import_path, Path):
        import_paths = [import_path]
    else:
        import_paths = import_path
    import_paths = list(utils.deduplicate_paths(import_paths))

    if not import_paths:
        return []

    # Check and fail early
    for path in import_paths:
        if not path.is_file() and not path.is_dir():
            raise exceptions.MapillaryFileNotFoundError(
                f"Import file or directory not found: {path}"
            )

    geotag: geotag_from_generic.GeotagFromGeneric

    if geotag_source == "exif":
        image_paths = utils.find_images(import_paths, skip_subfolders=skip_subfolders)
        LOG.debug("Found %d images in total", len(image_paths))
        geotag = geotag_from_exif.GeotagFromEXIF(image_paths)

    elif geotag_source == "gpx":
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path is required"
            )
        if not geotag_source_path.is_file():
            raise exceptions.MapillaryFileNotFoundError(
                f"GPX file not found: {geotag_source_path}"
            )
        if video_import_path is None:
            image_paths = utils.find_images(
                import_paths, skip_subfolders=skip_subfolders
            )
        else:
            image_paths = utils.find_images(import_paths, skip_subfolders=False)
            image_paths = list(
                utils.filter_video_samples(
                    image_paths, video_import_path, skip_subfolders=skip_subfolders
                )
            )
        LOG.debug(f"Found %d images in total", len(image_paths))
        geotag = geotag_from_gpx_file.GeotagFromGPXFile(
            image_paths,
            geotag_source_path,
            use_gpx_start_time=interpolation_use_gpx_start_time,
            offset_time=interpolation_offset_time,
        )
    elif geotag_source == "nmea":
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path is required"
            )

        if not geotag_source_path.is_file():
            raise exceptions.MapillaryFileNotFoundError(
                f"NMEA file not found: {geotag_source_path}"
            )

        if video_import_path is None:
            image_paths = utils.find_images(
                import_paths, skip_subfolders=skip_subfolders
            )
        else:
            image_paths = utils.find_images(import_paths, skip_subfolders=False)
            image_paths = list(
                utils.filter_video_samples(
                    image_paths, video_import_path, skip_subfolders=skip_subfolders
                )
            )
        LOG.debug(f"Found %d images in total", len(image_paths))
        geotag = geotag_from_nmea_file.GeotagFromNMEAFile(
            image_paths,
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
        if not geotag_source_path.exists():
            raise exceptions.MapillaryFileNotFoundError(
                f"GoPro video file or directory not found: {geotag_source_path}"
            )
        image_paths = utils.find_images(import_paths, skip_subfolders=False)
        geotag = geotag_from_gopro.GeotagFromGoPro(
            image_paths,
            utils.find_videos([geotag_source_path]),
            offset_time=interpolation_offset_time,
        )
    elif geotag_source == "blackvue_videos":
        if geotag_source_path is None:
            geotag_source_path = video_import_path
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path is required"
            )
        if not geotag_source_path.exists():
            raise exceptions.MapillaryFileNotFoundError(
                f"BlackVue video file or directory not found: {geotag_source_path}"
            )
        image_paths = utils.find_images(import_paths, skip_subfolders=False)
        geotag = geotag_from_blackvue.GeotagFromBlackVue(
            image_paths,
            utils.find_videos([geotag_source_path]),
            offset_time=interpolation_offset_time,
        )
    elif geotag_source == "camm":
        if geotag_source_path is None:
            geotag_source_path = video_import_path
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path is required"
            )
        if not geotag_source_path.exists():
            raise exceptions.MapillaryFileNotFoundError(
                f"CAMM video file or directory not found: {geotag_source_path}"
            )
        image_paths = utils.find_images(import_paths, skip_subfolders=False)
        geotag = geotag_from_camm.GeotagFromCAMM(
            image_paths,
            utils.find_videos([geotag_source_path]),
            offset_time=interpolation_offset_time,
        )
    else:
        raise RuntimeError(f"Invalid geotag source {geotag_source}")

    return list(types.map_descs(_validate_and_fail_desc, geotag.to_description()))


def _verify_exif_write(
    desc: types.ImageDescriptionFile,
) -> types.ImageDescriptionFileOrError:
    with open(desc["filename"], "rb") as fp:
        edit = exif_write.ExifEdit(fp.read())
    # The cast is to fix the type error in Python3.6:
    # Argument 1 to "add_image_description" of "ExifEdit" has incompatible type "ImageDescriptionEXIF"; expected "Dict[str, Any]"
    edit.add_image_description(T.cast(T.Dict, uploader.desc_file_to_exif(desc)))
    try:
        edit.dump_image_bytes()
    except piexif.InvalidImageDataError as exc:
        return types.describe_error(exc, desc["filename"])
    except Exception as exc:
        LOG.warning(
            "Unknown error test writing image %s", desc["filename"], exc_info=True
        )
        return types.describe_error(exc, desc["filename"])
    else:
        return desc


def _apply_offsets(
    descs: T.Sequence[types.ImageDescriptionFileOrError],
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
) -> None:
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
        heading["TrueHeading"] = (heading["TrueHeading"] + offset_angle) % 360
        heading["MagneticHeading"] = (heading["MagneticHeading"] + offset_angle) % 360


def _overwrite_exif_tags(
    descs: T.Sequence[types.ImageDescriptionFileOrError],
    all_tags=False,
    time_tag=False,
    gps_tag=False,
    direction_tag=False,
    orientation_tag=False,
) -> None:
    should_write = any(
        [
            all_tags,
            time_tag,
            gps_tag,
            direction_tag,
            orientation_tag,
        ]
    )

    if not should_write:
        return

    for desc in tqdm(
        types.filter_out_errors(descs),
        desc="Overwriting EXIF",
        unit="images",
        disable=LOG.getEffectiveLevel() <= logging.DEBUG,
    ):
        try:
            image_exif = exif_write.ExifEdit(desc["filename"])

            if all_tags or time_tag:
                dt = types.map_capture_time_to_datetime(desc["MAPCaptureTime"])
                image_exif.add_date_time_original(dt)

            if all_tags or gps_tag:
                image_exif.add_lat_lon(
                    desc["MAPLatitude"],
                    desc["MAPLongitude"],
                )

            if all_tags or direction_tag:
                heading = desc.get("MAPCompassHeading")
                if heading is not None:
                    image_exif.add_direction(heading["TrueHeading"])

            if all_tags or orientation_tag:
                if "MAPOrientation" in desc:
                    image_exif.add_orientation(desc["MAPOrientation"])

            image_exif.write()
        except Exception:
            LOG.warning(
                "Failed to overwrite EXIF for image %s",
                desc["filename"],
                exc_info=True,
            )


def _test_exif_writing(descs: T.Sequence[types.ImageDescriptionFileOrError]) -> None:
    with tqdm(
        total=len(types.filter_out_errors(descs)),
        desc="Test EXIF writing",
        unit="images",
        disable=LOG.getEffectiveLevel() <= logging.DEBUG,
    ) as pbar:

        def _update(desc):
            new_desc = _verify_exif_write(desc)
            pbar.update(1)
            return new_desc

        descs = list(types.map_descs(_update, descs))


def _write_descs(
    descs: T.Sequence[types.ImageDescriptionFileOrError],
    desc_path: str,
) -> None:
    if desc_path == "-":
        print(json.dumps(descs, indent=4))
    else:
        with open(desc_path, "w") as fp:
            json.dump(descs, fp, indent=4)
    LOG.info("Check the image description file for details: %s", desc_path)


def _show_stats(
    descs: T.Sequence[types.ImageDescriptionFileOrError], skip_process_errors: bool
) -> None:
    processed_images = types.filter_out_errors(descs)
    not_processed_images = T.cast(
        T.Sequence[types.ImageDescriptionFileError],
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

    failed_count = len(not_processed_images) - duplicated_image_count

    if failed_count and not skip_process_errors:
        raise exceptions.MapillaryProcessError(
            f"Failed to process {failed_count} images. To skip these errors, specify --skip_process_errors"
        )


def process_finalize(
    import_path: T.Union[T.Sequence[Path], Path],
    descs: T.Sequence[types.ImageDescriptionFileOrError],
    skip_process_errors: bool = False,
    overwrite_all_EXIF_tags: bool = False,
    overwrite_EXIF_time_tag: bool = False,
    overwrite_EXIF_gps_tag: bool = False,
    overwrite_EXIF_direction_tag: bool = False,
    overwrite_EXIF_orientation_tag: bool = False,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    desc_path: T.Optional[str] = None,
) -> T.List[types.ImageDescriptionFileOrError]:
    import_paths: T.Sequence[Path]
    if isinstance(import_path, Path):
        import_paths = [import_path]
    else:
        assert isinstance(import_path, list)
        import_paths = import_path
    import_paths = list(utils.deduplicate_paths(import_paths))

    if not import_paths:
        return []

    # Check and fail early
    for path in import_paths:
        if not path.is_file() and not path.is_dir():
            raise exceptions.MapillaryFileNotFoundError(
                f"Import file or directory not found: {path}"
            )

    _apply_offsets(descs, offset_time=offset_time, offset_angle=offset_angle)

    descs = list(types.map_descs(_validate_and_fail_desc, descs))

    _overwrite_exif_tags(
        descs,
        all_tags=overwrite_all_EXIF_tags,
        time_tag=overwrite_EXIF_time_tag,
        gps_tag=overwrite_EXIF_gps_tag,
        direction_tag=overwrite_EXIF_direction_tag,
        orientation_tag=overwrite_EXIF_orientation_tag,
    )

    _test_exif_writing(descs)

    if desc_path is None:
        if len(import_paths) == 1 and import_paths[0].is_dir():
            desc_path = str(
                import_paths[0].joinpath(constants.IMAGE_DESCRIPTION_FILENAME)
            )
        else:
            if 1 < len(import_paths):
                LOG.warning(
                    "Writing image descriptions to STDOUT, because multiple import paths are specified"
                )
            else:
                LOG.warning(
                    'Writing image descriptions to STDOUT, because the import path "%s" is a file',
                    str(import_paths[0]),
                )
            desc_path = "-"

    if desc_path != "\x00":
        # write descs first because _show_stats() may raise an exception
        _write_descs(descs, desc_path)

    _show_stats(descs, skip_process_errors=skip_process_errors)

    return descs
