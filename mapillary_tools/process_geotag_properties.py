import collections
import datetime
import io
import json
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 8):
    from typing import Literal  # pylint: disable=no-name-in-module
else:
    from typing_extensions import Literal

import piexif
from tqdm import tqdm

from . import constants, exceptions, exif_write, geo, types, uploader, utils
from .geotag import (
    blackvue_parser,
    camm_parser,
    geotag_from_blackvue,
    geotag_from_camm,
    geotag_from_exif,
    geotag_from_generic,
    geotag_from_gopro,
    geotag_from_gpx_file,
    geotag_from_nmea_file,
    gpmf_gps_filter,
    gpmf_parser,
    simple_mp4_parser as parser,
    utils as video_utils,
)
from .types import FileType


LOG = logging.getLogger(__name__)


GeotagSource = Literal["gopro_videos", "blackvue_videos", "camm", "exif", "gpx", "nmea"]


def _process_images(
    image_paths: T.Sequence[Path],
    geotag_source: GeotagSource,
    geotag_source_path: T.Optional[Path] = None,
    video_import_path: T.Optional[Path] = None,
    interpolation_use_gpx_start_time: bool = False,
    interpolation_offset_time: float = 0.0,
    skip_subfolders=False,
) -> T.List[types.ImageDescriptionFileOrError]:
    geotag: geotag_from_generic.GeotagFromGeneric

    if geotag_source == "exif":
        geotag = geotag_from_exif.GeotagFromEXIF(image_paths)

    else:
        if geotag_source_path is None:
            geotag_source_path = video_import_path
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path is required"
            )
        if not geotag_source_path.is_file():
            raise exceptions.MapillaryFileNotFoundError(
                f"GPX file not found: {geotag_source_path}"
            )
        if video_import_path is not None:
            # commands that trigger this branch:
            # video_process video_import_path image_paths --geotag_source gpx --geotag_source_path <gpx_file> --skip_subfolders
            image_paths = list(
                utils.filter_video_samples(
                    image_paths, video_import_path, skip_subfolders=skip_subfolders
                )
            )

        if geotag_source == "gpx":
            geotag = geotag_from_gpx_file.GeotagFromGPXFile(
                image_paths,
                geotag_source_path,
                use_gpx_start_time=interpolation_use_gpx_start_time,
                offset_time=interpolation_offset_time,
            )
        elif geotag_source == "nmea":
            geotag = geotag_from_nmea_file.GeotagFromNMEAFile(
                image_paths,
                geotag_source_path,
                use_gpx_start_time=interpolation_use_gpx_start_time,
                offset_time=interpolation_offset_time,
            )
        elif geotag_source == "gopro_videos":
            geotag = geotag_from_gopro.GeotagFromGoPro(
                image_paths,
                utils.find_videos([geotag_source_path]),
                offset_time=interpolation_offset_time,
            )
        elif geotag_source == "blackvue_videos":
            geotag = geotag_from_blackvue.GeotagFromBlackVue(
                image_paths,
                utils.find_videos([geotag_source_path]),
                offset_time=interpolation_offset_time,
            )
        elif geotag_source == "camm":
            geotag = geotag_from_camm.GeotagFromCAMM(
                image_paths,
                utils.find_videos([geotag_source_path]),
                offset_time=interpolation_offset_time,
            )
        else:
            raise RuntimeError(f"Invalid geotag source {geotag_source}")

    descs = list(types.map_descs(types.validate_and_fail_desc, geotag.to_description()))

    return descs


def _process_videos(
    video_path: Path, filetypes: T.Set[types.FileType]
) -> T.Optional[types.VideoMetadata]:
    if types.FileType.CAMM in filetypes:
        with video_path.open("rb") as fp:
            try:
                points = camm_parser.extract_points(fp)
            except parser.ParsingError:
                points = None

            if points is not None:
                fp.seek(0, io.SEEK_SET)
                make, model = camm_parser.extract_camera_make_and_model(fp)
                return types.VideoMetadata(
                    video_path, types.FileType.CAMM, points, make, model
                )

    if types.FileType.GOPRO in filetypes:
        with video_path.open("rb") as fp:
            try:
                points_with_fix = gpmf_parser.extract_points(fp)
            except parser.ParsingError:
                points_with_fix = None

            if points_with_fix is not None:
                fp.seek(0, io.SEEK_SET)
                make, model = "GoPro", gpmf_parser.extract_camera_model(fp)
                video_metadata = types.VideoMetadata(
                    video_path,
                    types.FileType.GOPRO,
                    T.cast(T.List[geo.Point], points_with_fix),
                    make,
                    model,
                )
                video_metadata.points = T.cast(
                    T.List[geo.Point],
                    gpmf_gps_filter.filter_noisy_points(
                        T.cast(
                            T.List[gpmf_parser.PointWithFix],
                            video_metadata.points,
                        )
                    ),
                )
                return video_metadata

    if types.FileType.BLACKVUE in filetypes:
        with video_path.open("rb") as fp:
            try:
                points = blackvue_parser.extract_points(fp)
            except parser.ParsingError:
                points = None

            if points is not None:
                fp.seek(0, io.SEEK_SET)
                make, model = "BlackVue", blackvue_parser.extract_camera_model(fp)
                return types.VideoMetadata(
                    video_path, types.FileType.BLACKVUE, points, make, model
                )

    return None


def _normalize_import_paths(
    import_path: T.Union[Path, T.Sequence[Path]]
) -> T.Sequence[Path]:
    import_paths: T.Sequence[Path]
    if isinstance(import_path, Path):
        import_paths = [import_path]
    else:
        import_paths = import_path
    import_paths = list(utils.deduplicate_paths(import_paths))
    return import_paths


def _describe_video_metadata(
    video_metadata: types.VideoMetadata,
) -> types.VideoDescriptionFileOrError:
    if video_metadata.points:
        stationary = video_utils.is_video_stationary(
            geo.get_max_distance_from_start(
                [(p.lat, p.lon) for p in video_metadata.points]
            )
        )
        if stationary:
            return types.describe_error(
                exceptions.MapillaryStationaryVideoError(f"Stationary video"),
                video_metadata.filename,
                filetype=video_metadata.filetype,
            )
        else:
            return types.as_desc_video(video_metadata)
    else:
        return types.describe_error(
            exceptions.MapillaryGPXEmptyError("Empty GPS data found"),
            video_metadata.filename,
            filetype=video_metadata.filetype,
        )


def process_geotag_properties(
    import_path: T.Union[Path, T.Sequence[Path]],
    filetypes: T.Set[FileType],
    geotag_source: GeotagSource,
    geotag_source_path: T.Optional[Path] = None,
    # video_import_path comes from the command video_process
    video_import_path: T.Optional[Path] = None,
    interpolation_use_gpx_start_time: bool = False,
    interpolation_offset_time: float = 0.0,
    skip_subfolders=False,
) -> T.List[types.ImageVideoDescriptionFileOrError]:
    filetypes = set(types.FileType(f) for f in filetypes)
    import_paths = _normalize_import_paths(import_path)
    expected_descs_length = 0

    # Check and fail early
    for path in import_paths:
        if not path.is_file() and not path.is_dir():
            raise exceptions.MapillaryFileNotFoundError(
                f"Import file or directory not found: {path}"
            )

    descs: T.List[types.ImageVideoDescriptionFileOrError] = []

    # if more than one filetypes speficied, check filename suffixes,
    # i.e. files not ended with .jpg or .mp4 will be ignored
    check_file_suffix = len(filetypes) > 1

    if FileType.IMAGE in filetypes:
        image_paths = utils.find_images(
            import_paths,
            skip_subfolders=skip_subfolders,
            check_file_suffix=check_file_suffix,
        )
        expected_descs_length += len(image_paths)
        descs.extend(
            _process_images(
                image_paths,
                geotag_source=geotag_source,
                geotag_source_path=geotag_source_path,
                video_import_path=video_import_path,
                interpolation_use_gpx_start_time=interpolation_use_gpx_start_time,
                interpolation_offset_time=interpolation_offset_time,
                skip_subfolders=skip_subfolders,
            )
        )

    if (
        types.FileType.CAMM in filetypes
        or types.FileType.GOPRO in filetypes
        or types.FileType.BLACKVUE in filetypes
    ):
        video_paths = utils.find_videos(
            import_paths,
            skip_subfolders=skip_subfolders,
            check_file_suffix=check_file_suffix,
        )
        expected_descs_length += len(video_paths)
        for video_path in tqdm(
            video_paths,
            desc="Extracting GPS tracks from videos",
            unit="videos",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
        ):
            LOG.debug("Extracting GPS track from %s", str(video_path))
            video_metadata = _process_videos(video_path, filetypes)
            if video_metadata:
                descs.append(_describe_video_metadata(video_metadata))
            else:
                descs.append(
                    types.describe_error(
                        exceptions.MapillaryVideoError(
                            "No GPS data found from the video"
                        ),
                        video_path,
                        filetype=None,
                    )
                )

    assert expected_descs_length == len(
        descs
    ), f"expected {expected_descs_length} descs, got {len(descs)}"
    # filenames should be deduplicated in utils.find_images/utils.find_videos
    assert len(descs) == len(
        set(desc["filename"] for desc in descs)
    ), "duplicate filenames found"

    return descs


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
        return types.describe_error(
            exc, Path(desc["filename"]), filetype=FileType(desc["filetype"])
        )
    except Exception as exc:
        LOG.warning(
            "Unknown error test writing image %s", desc["filename"], exc_info=True
        )
        return types.describe_error(
            exc, Path(desc["filename"]), filetype=FileType(desc["filetype"])
        )
    else:
        return desc


def _apply_offsets(
    descs: T.Sequence[types.ImageDescriptionFileOrError],
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
) -> None:
    for desc in types.filter_out_errors(descs):
        if offset_time:
            # for desc in types.filter_out_errors(descs):
            dt = types.map_capture_time_to_datetime(desc["MAPCaptureTime"])
            desc["MAPCaptureTime"] = types.datetime_to_map_capture_time(
                dt + datetime.timedelta(seconds=offset_time)
            )

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


def _verify_exif_writing(descs: T.Sequence[types.ImageDescriptionFileOrError]) -> None:
    with tqdm(
        total=len(types.filter_out_errors(descs)),
        desc="Verifying image EXIF writing",
        unit="images",
        disable=LOG.getEffectiveLevel() <= logging.DEBUG,
    ) as pbar:

        def _update(desc: types.ImageDescriptionFile):
            new_desc = _verify_exif_write(desc)
            pbar.update(1)
            return new_desc

        list(types.map_descs(_update, descs))


def _write_descs(
    descs: T.Sequence[types.ImageVideoDescriptionFileOrError],
    desc_path: str,
) -> None:
    if desc_path == "-":
        print(json.dumps(descs, indent=2))
    else:
        with open(desc_path, "w") as fp:
            json.dump(descs, fp)
        LOG.info("Check the image description file for details: %s", desc_path)


def _is_error_skipped(
    error_type: str, skipped_process_errors: T.Set[T.Type[Exception]]
):
    skipped_process_error_names = set(err.__name__ for err in skipped_process_errors)
    skip_all = Exception in skipped_process_errors
    return skip_all or error_type in skipped_process_error_names


def _show_stats(
    descs: T.Sequence[types.ImageVideoDescriptionFileOrError],
    skipped_process_errors: T.Set[T.Type[Exception]],
) -> None:
    descs_by_filetype: T.Dict[
        types.FileType, T.List[types.ImageVideoDescriptionFileOrError]
    ] = {}
    for desc in descs:
        filetype = desc.get("filetype")
        if filetype:
            descs_by_filetype.setdefault(types.FileType(filetype), []).append(desc)

    for filetype, group in descs_by_filetype.items():
        _show_stats_per_filetype(group, filetype, skipped_process_errors)

    error_descs = T.cast(
        T.Sequence[types.ImageDescriptionFileError],
        [desc for desc in descs if types.is_error(desc)],
    )

    critical_error_descs = [
        desc
        for desc in error_descs
        if not _is_error_skipped(types.error_type(desc), skipped_process_errors)
    ]
    if critical_error_descs:
        raise exceptions.MapillaryProcessError(
            f"Failed to process {len(critical_error_descs)} files. To skip these errors, specify --skip_process_errors"
        )


def _show_stats_per_filetype(
    descs: T.Sequence[types.ImageVideoDescriptionFileOrError],
    filetype: types.FileType,
    skipped_process_errors: T.Set[T.Type[Exception]],
):
    processed_files: T.List[types.ImageVideoDescriptionFile] = types.filter_out_errors(
        descs
    )
    not_processed_files = T.cast(
        T.Sequence[types.ImageDescriptionFileError],
        [desc for desc in descs if types.is_error(desc)],
    )
    assert len(processed_files) + len(not_processed_files) == len(descs)

    LOG.info("%8d %s(s) read in total", len(descs), filetype.value)
    if processed_files:
        LOG.info(
            "\t %8d %s(s) are ready to be uploaded",
            len(processed_files),
            filetype.value,
        )

    error_counter = collections.Counter(
        types.error_type(desc) for desc in not_processed_files
    )

    for error_type, count in error_counter.items():
        if _is_error_skipped(error_type, skipped_process_errors):
            LOG.warning(
                "\t %8d %s(s) skipped due to %s", count, filetype.value, error_type
            )
        else:
            LOG.error(
                "\t %8d %s(s) failed due to %s", count, filetype.value, error_type
            )


def process_finalize(
    import_path: T.Union[T.Sequence[Path], Path],
    descs: T.Sequence[types.ImageVideoDescriptionFileOrError],
    skip_process_errors: bool = False,
    overwrite_all_EXIF_tags: bool = False,
    overwrite_EXIF_time_tag: bool = False,
    overwrite_EXIF_gps_tag: bool = False,
    overwrite_EXIF_direction_tag: bool = False,
    overwrite_EXIF_orientation_tag: bool = False,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    desc_path: T.Optional[str] = None,
) -> T.List[types.ImageVideoDescriptionFileOrError]:
    initial_descs_length = len(descs)

    _apply_offsets(
        types.filter_image_descs(descs),
        offset_time=offset_time,
        offset_angle=offset_angle,
    )

    descs = list(types.map_descs(types.validate_and_fail_desc, descs))

    _overwrite_exif_tags(
        types.filter_image_descs(descs),
        all_tags=overwrite_all_EXIF_tags,
        time_tag=overwrite_EXIF_time_tag,
        gps_tag=overwrite_EXIF_gps_tag,
        direction_tag=overwrite_EXIF_direction_tag,
        orientation_tag=overwrite_EXIF_orientation_tag,
    )

    _verify_exif_writing(types.filter_image_descs(descs))

    if desc_path is None:
        import_paths = _normalize_import_paths(import_path)
        if len(import_paths) == 1 and import_paths[0].is_dir():
            desc_path = str(
                import_paths[0].joinpath(constants.IMAGE_DESCRIPTION_FILENAME)
            )
        else:
            if 1 < len(import_paths):
                LOG.warning(
                    "Writing descriptions to STDOUT, because multiple import paths are specified"
                )
            else:
                LOG.warning(
                    'Writing descriptions to STDOUT, because the import path "%s" is NOT a directory',
                    str(import_paths[0]),
                )
            desc_path = "-"

    if desc_path != "\x00":
        # write descs first because _show_stats() may raise an exception
        _write_descs(descs, desc_path)

    skipped_process_errors: T.Set[T.Type[Exception]]
    if skip_process_errors:
        # skip all exceptions
        skipped_process_errors = {Exception}
    else:
        skipped_process_errors = {exceptions.MapillaryDuplicationError}

    _show_stats(descs, skipped_process_errors=skipped_process_errors)

    assert initial_descs_length == len(descs)

    return descs
