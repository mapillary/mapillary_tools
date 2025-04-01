from __future__ import annotations

import collections
import datetime
import json
import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from . import constants, exceptions, exif_write, types, utils
from .geotag.factory import parse_source_option, process
from .geotag.options import (
    InterpolationOption,
    SourceOption,
    SourcePathOption,
    SourceType,
)

LOG = logging.getLogger(__name__)
DEFAULT_GEOTAG_SOURCE_OPTIONS = [
    SourceType.NATIVE.value,
    SourceType.EXIFTOOL_RUNTIME.value,
]


def _normalize_import_paths(import_path: Path | T.Sequence[Path]) -> T.Sequence[Path]:
    import_paths: T.Sequence[Path]
    if isinstance(import_path, Path):
        import_paths = [import_path]
    else:
        import_paths = import_path
    import_paths = list(utils.deduplicate_paths(import_paths))
    return import_paths


def _parse_source_options(
    geotag_source: list[str],
    video_geotag_source: list[str],
    geotag_source_path: Path | None,
) -> list[SourceOption]:
    parsed_options: list[SourceOption] = []

    for s in geotag_source:
        parsed_options.extend(parse_source_option(s))

    for s in video_geotag_source:
        for video_option in parse_source_option(s):
            video_option.filetypes = types.combine_filetype_filters(
                video_option.filetypes, {types.FileType.VIDEO}
            )
            parsed_options.append(video_option)

    if geotag_source_path is not None:
        for parsed_option in parsed_options:
            if parsed_option.source_path is None:
                parsed_option.source_path = SourcePathOption(
                    source_path=Path(geotag_source_path)
                )
            else:
                source_path_option = parsed_option.source_path
                if source_path_option.source_path is None:
                    source_path_option.source_path = Path(geotag_source_path)
                else:
                    LOG.warning(
                        "The option --geotag_source_path is ignored for source %s",
                        parsed_option,
                    )

    return parsed_options


def process_geotag_properties(
    import_path: Path | T.Sequence[Path],
    filetypes: set[types.FileType] | None,
    # Geotag options
    geotag_source: list[str],
    geotag_source_path: Path | None,
    video_geotag_source: list[str],
    # Global options
    # video_import_path comes from the command video_process
    video_import_path: Path | None = None,
    interpolation_use_gpx_start_time: bool = False,
    interpolation_offset_time: float = 0.0,
    num_processes: int | None = None,
    skip_subfolders=False,
) -> list[types.MetadataOrError]:
    import_paths = _normalize_import_paths(import_path)

    # Check and fail early
    for path in import_paths:
        if not path.is_file() and not path.is_dir():
            raise exceptions.MapillaryFileNotFoundError(
                f"Import file or directory not found: {path}"
            )

    if geotag_source_path is None:
        geotag_source_path = video_import_path

    if not geotag_source and not video_geotag_source:
        geotag_source = [*DEFAULT_GEOTAG_SOURCE_OPTIONS]

    options = _parse_source_options(
        geotag_source=geotag_source or [],
        video_geotag_source=video_geotag_source or [],
        geotag_source_path=geotag_source_path,
    )

    for option in options:
        option.filetypes = types.combine_filetype_filters(option.filetypes, filetypes)
        option.num_processes = num_processes
        if option.interpolation is None:
            option.interpolation = InterpolationOption(
                offset_time=interpolation_offset_time,
                use_gpx_start_time=interpolation_use_gpx_start_time,
            )

    # TODO: can find both in one pass
    image_paths = utils.find_images(import_paths, skip_subfolders=skip_subfolders)
    video_paths = utils.find_videos(import_paths, skip_subfolders=skip_subfolders)

    metadata_or_errors = process(image_paths + video_paths, options)

    return metadata_or_errors


def _apply_offsets(
    metadatas: T.Iterable[types.ImageMetadata],
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
) -> None:
    for metadata in metadatas:
        if offset_time:
            metadata.time = metadata.time + offset_time
        if metadata.angle is None:
            metadata.angle = 0.0
        metadata.angle = (metadata.angle + offset_angle) % 360


def _overwrite_exif_tags(
    metadatas: T.Sequence[types.ImageMetadata],
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

    for metadata in tqdm(
        metadatas,
        desc="Overwriting EXIF",
        unit="images",
        disable=LOG.getEffectiveLevel() <= logging.DEBUG,
    ):
        dt = datetime.datetime.fromtimestamp(metadata.time, datetime.timezone.utc)
        dt = dt.replace(tzinfo=datetime.timezone.utc)

        try:
            image_exif = exif_write.ExifEdit(metadata.filename)

            if all_tags or time_tag:
                image_exif.add_date_time_original(dt)
                image_exif.add_gps_datetime(dt)

            if all_tags or gps_tag:
                image_exif.add_lat_lon(metadata.lat, metadata.lon)

            if all_tags or direction_tag:
                if metadata.angle is not None:
                    image_exif.add_direction(metadata.angle)

            if all_tags or orientation_tag:
                if metadata.MAPOrientation is not None:
                    image_exif.add_orientation(metadata.MAPOrientation)

            image_exif.write()
        except Exception:
            LOG.warning(
                "Failed to overwrite EXIF for image %s",
                metadata.filename,
                exc_info=True,
            )


def _write_metadatas(
    metadatas: T.Sequence[types.MetadataOrError],
    desc_path: str,
) -> None:
    if desc_path == "-":
        descs = [types.as_desc(metadata) for metadata in metadatas]
        print(json.dumps(descs, indent=2))
    else:
        descs = [types.as_desc(metadata) for metadata in metadatas]
        with open(desc_path, "w") as fp:
            json.dump(descs, fp)
        LOG.info("Check the description file for details: %s", desc_path)


def _is_error_skipped(error_type: str, skipped_process_errors: set[T.Type[Exception]]):
    skipped_process_error_names = set(err.__name__ for err in skipped_process_errors)
    skip_all = Exception in skipped_process_errors
    return skip_all or error_type in skipped_process_error_names


def _show_stats(
    metadatas: T.Sequence[types.MetadataOrError],
    skipped_process_errors: set[T.Type[Exception]],
) -> None:
    metadatas_by_filetype: dict[types.FileType, list[types.MetadataOrError]] = {}
    for metadata in metadatas:
        if isinstance(metadata, types.ImageMetadata):
            filetype = types.FileType.IMAGE
        else:
            filetype = metadata.filetype
        metadatas_by_filetype.setdefault(filetype, []).append(metadata)

    for filetype, group in metadatas_by_filetype.items():
        _show_stats_per_filetype(group, filetype, skipped_process_errors)

    critical_error_metadatas = [
        metadata
        for metadata in metadatas
        if isinstance(metadata, types.ErrorMetadata)
        and not _is_error_skipped(
            metadata.error.__class__.__name__, skipped_process_errors
        )
    ]
    if critical_error_metadatas:
        raise exceptions.MapillaryProcessError(
            f"Failed to process {len(critical_error_metadatas)} files. To skip these errors, specify --skip_process_errors"
        )


def _show_stats_per_filetype(
    metadatas: T.Collection[types.MetadataOrError],
    filetype: types.FileType,
    skipped_process_errors: set[T.Type[Exception]],
):
    good_metadatas: list[types.Metadata]
    good_metadatas, error_metadatas = types.separate_errors(metadatas)

    filesize_to_upload = sum(
        [0 if m.filesize is None else m.filesize for m in good_metadatas]
    )

    LOG.info("%8d %s(s) read in total", len(metadatas), filetype.value)
    if good_metadatas:
        LOG.info(
            "\t %8d %s(s) (%s MB) are ready to be uploaded",
            len(good_metadatas),
            filetype.value,
            round(filesize_to_upload / 1024 / 1024, 1),
        )

    error_counter = collections.Counter(
        metadata.error.__class__.__name__ for metadata in error_metadatas
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


def _validate_metadatas(
    metadatas: T.Collection[types.MetadataOrError], num_processes: int | None
) -> list[types.MetadataOrError]:
    LOG.debug("Validating %d metadatas", len(metadatas))

    # validating metadatas is slow, hence multiprocessing

    # Do not pass error metadatas where the error object can not be pickled for multiprocessing to work
    # Otherwise we get:
    # TypeError: __init__() missing 3 required positional arguments: 'image_time', 'gpx_start_time', and 'gpx_end_time'
    # See https://stackoverflow.com/a/61432070
    good_metadatas, error_metadatas = types.separate_errors(metadatas)
    map_results = utils.mp_map_maybe(
        types.validate_and_fail_metadata,
        T.cast(T.Iterable[types.Metadata], good_metadatas),
        num_processes=num_processes,
    )

    validated_metadatas = list(
        tqdm(
            map_results,
            desc="Validating metadatas",
            unit="metadata",
            disable=LOG.getEffectiveLevel() <= logging.DEBUG,
            total=len(good_metadatas),
        )
    )

    return validated_metadatas + error_metadatas


def process_finalize(
    import_path: T.Sequence[Path] | Path,
    metadatas: list[types.MetadataOrError],
    skip_process_errors: bool = False,
    device_make: str | None = None,
    device_model: str | None = None,
    overwrite_all_EXIF_tags: bool = False,
    overwrite_EXIF_time_tag: bool = False,
    overwrite_EXIF_gps_tag: bool = False,
    overwrite_EXIF_direction_tag: bool = False,
    overwrite_EXIF_orientation_tag: bool = False,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    desc_path: str | None = None,
    num_processes: int | None = None,
) -> list[types.MetadataOrError]:
    image_metadatas: list[types.ImageMetadata] = []
    video_metadatas: list[types.VideoMetadata] = []

    for metadata in metadatas:
        if isinstance(metadata, types.VideoMetadata):
            video_metadatas.append(metadata)
        elif isinstance(metadata, types.ImageMetadata):
            image_metadatas.append(metadata)

    for metadata in video_metadatas:
        if device_make is not None:
            metadata.make = device_make
        if device_model is not None:
            metadata.model = device_model

    for metadata in image_metadatas:
        if device_make is not None:
            metadata.MAPDeviceMake = device_make
        if device_model is not None:
            metadata.MAPDeviceModel = device_model
        # Add the basename
        metadata.MAPFilename = metadata.filename.name

    # modified in place
    _apply_offsets(
        image_metadatas,
        offset_time=offset_time,
        offset_angle=offset_angle,
    )

    metadatas = _validate_metadatas(metadatas, num_processes=num_processes)

    # image_metadatas and video_metadatas get stale after the validation,
    # hence delete them to avoid confusion
    del image_metadatas
    del video_metadatas

    _overwrite_exif_tags(
        # Search image metadatas again because some of them might have been failed
        [
            metadata
            for metadata in metadatas
            if isinstance(metadata, types.ImageMetadata)
        ],
        all_tags=overwrite_all_EXIF_tags,
        time_tag=overwrite_EXIF_time_tag,
        gps_tag=overwrite_EXIF_gps_tag,
        direction_tag=overwrite_EXIF_direction_tag,
        orientation_tag=overwrite_EXIF_orientation_tag,
    )

    # find the description file path
    if desc_path is None:
        import_paths = _normalize_import_paths(import_path)
        if len(import_paths) == 1 and import_paths[0].is_dir():
            desc_path = str(
                import_paths[0].joinpath(constants.IMAGE_DESCRIPTION_FILENAME)
            )
        else:
            if 1 < len(import_paths):
                LOG.warning(
                    "Writing the description file to STDOUT, because multiple import paths are specified"
                )
            else:
                LOG.warning(
                    'Writing the description file to STDOUT, because the import path "%s" is NOT a directory',
                    str(import_paths[0]) if import_paths else "",
                )
            desc_path = "-"

    # process_and_upload will set desc_path to "\x00"
    # then all metadatas will be passed to the upload command directly
    if desc_path != "\x00":
        # write descs first because _show_stats() may raise an exception
        _write_metadatas(metadatas, desc_path)

    # Show stats
    skipped_process_errors: set[T.Type[Exception]]
    if skip_process_errors:
        # Skip all exceptions
        skipped_process_errors = {Exception}
    else:
        skipped_process_errors = {exceptions.MapillaryDuplicationError}
    _show_stats(metadatas, skipped_process_errors=skipped_process_errors)

    return metadatas
