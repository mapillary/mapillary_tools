# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import datetime
import logging
import typing as T
from pathlib import Path

import humanize
from tqdm import tqdm

from . import constants, exceptions, exif_write, types, utils
from .geotag.factory import give_video_import_path, parse_source_options, process
from .geotag.options import InterpolationOption, SourceOption, SourceType
from .serializer.description import (
    DescriptionJSONSerializer,
    validate_and_fail_metadata,
)
from .serializer.gpx import GPXSerializer

LOG = logging.getLogger(__name__)
DEFAULT_GEOTAG_SOURCE_OPTIONS = [
    SourceType.NATIVE.value,
    SourceType.EXIFTOOL_RUNTIME.value,
]

# Files that cameras and other tools write beside images and videos: GoPro
# thumbnails (.THM) and low-resolution proxies (.LRV), GPS logs, metadata,
# subtitles (.SRT), notes and checksums. Selecting all the files of a camera
# folder names them along with its images and videos
_SIDECAR_EXTENSIONS = frozenset(
    {
        ".thm",
        ".lrv",
        ".gpx",
        ".nmea",
        ".xml",
        ".json",
        ".srt",
        ".txt",
        ".csv",
        ".log",
        ".md5",
    }
)


def _normalize_import_paths(import_path: Path | T.Sequence[Path]) -> T.Sequence[Path]:
    import_paths: T.Sequence[Path]
    if isinstance(import_path, Path):
        import_paths = [import_path]
    else:
        import_paths = import_path
    import_paths = list(utils.deduplicate_paths(import_paths))
    return import_paths


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

    # A named file that accompanies images and videos is skipped with a word,
    # not failed: a user who names all the files of a camera folder means its
    # images and videos. Zip files, also the AppleDouble file of one, are left
    # to process_and_upload
    sidecar_paths = [
        path
        for path in import_paths
        if path.is_file() and path.suffix.lower() != ".zip" and _is_sidecar_file(path)
    ]
    for path in sidecar_paths:
        LOG.warning("Skipping %s, which is not a supported image or video", path)
    import_paths = [path for path in import_paths if path not in sidecar_paths]

    # A directory is searched for the files it can process, and the others in
    # it are left alone, but any other file named explicitly is failed if it
    # cannot be processed: it was meant to be uploaded. A zip file is uploaded
    # as it is, by process_and_upload
    unsupported_metadatas = [
        _describe_unsupported_file(path)
        for path in import_paths
        if path.is_file()
        and not (
            utils.is_image_file(path)
            or utils.is_video_file(path)
            or path.suffix.lower() == ".zip"
        )
    ]

    if not geotag_source and not video_geotag_source:
        geotag_source = [*DEFAULT_GEOTAG_SOURCE_OPTIONS]

    options = parse_source_options(
        geotag_source=geotag_source or [],
        video_geotag_source=video_geotag_source or [],
        geotag_source_path=geotag_source_path,
    )

    # In video_process, the sources without a path of their own read the video
    # import path
    if geotag_source_path is None and video_import_path is not None:
        give_video_import_path(options, video_import_path)

    # --video_geotag_source applies to videos only. Without --geotag_source,
    # images (such as the frames that video_process samples) are geotagged by
    # the default sources, as they are when neither option is given
    if not geotag_source:
        options.extend(
            SourceOption(SourceType(source), filetypes={types.FileType.IMAGE})
            for source in DEFAULT_GEOTAG_SOURCE_OPTIONS
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

    metadata_or_errors = process(image_paths + video_paths, options, filetypes)

    return metadata_or_errors + unsupported_metadatas


def _is_sidecar_file(path: Path) -> bool:
    """
    Whether a file is one that accompanies images and videos (see
    _SIDECAR_EXTENSIONS), or one that macOS writes beside them: .DS_Store, and
    the AppleDouble file ._NAME of each file it copies to a drive that cannot
    hold its metadata, which has the extension of that file but is no image or
    video

    >>> [_is_sidecar_file(Path(name)) for name in ["GH010001.THM", "GL010001.LRV", "track.GPX"]]
    [True, True, True]
    >>> [_is_sidecar_file(Path(name)) for name in ["._GOPR0001.JPG", ".DS_Store"]]
    [True, True]
    >>> [_is_sidecar_file(Path(name)) for name in ["GOPR0001.JPG", "VID_00_001.insv", "photo.png"]]
    [False, False, False]
    """
    return (
        path.name.startswith("._")
        or path.name.casefold() == ".ds_store"
        or path.suffix.lower() in _SIDECAR_EXTENSIONS
    )


def _describe_unsupported_file(path: Path) -> types.ErrorMetadata:
    """
    The error of a file named for processing that is neither an image nor a
    video that can be processed. An Insta360 original (.insv) is stitched first

    >>> metadata = _describe_unsupported_file(Path("notes.txt"))
    >>> str(metadata.error)
    'Not a supported image or video'
    >>> metadata.filetype is None
    True
    """
    message = "Not a supported image or video"
    if path.suffix.lower() == ".insv":
        message += (
            ". Stitch the Insta360 original with Insta360 Studio first, then"
            " geotag the stitched video by the original with"
            """ --video_geotag_source '{"source": "exiftool_runtime", "pattern": "../%g.insv"}'"""
        )
    return types.describe_error_metadata(
        exceptions.MapillaryUnsupportedFileError(message), path, filetype=None
    )


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
        disable=LOG.isEnabledFor(logging.DEBUG),
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
        descs = DescriptionJSONSerializer.serialize(metadatas)
        print(descs.decode("utf-8"))
    else:
        normalized_suffix = Path(desc_path).suffix.strip().lower()
        if normalized_suffix in [".gpx"]:
            descs = GPXSerializer.serialize(metadatas)
        else:
            descs = DescriptionJSONSerializer.serialize(metadatas)
        with open(desc_path, "wb") as fp:
            fp.write(descs)
        LOG.info("Check the description file for details: %s", desc_path)


def _is_error_skipped(
    error_type: type[Exception], skipped_process_errors: set[type[Exception]]
):
    return (Exception in skipped_process_errors) or (
        error_type in skipped_process_errors
    )


def _show_stats(
    metadatas: T.Sequence[types.MetadataOrError],
    skipped_process_errors: set[T.Type[Exception]],
) -> None:
    LOG.info("==> Process summary")

    # None for the files that are neither images nor videos
    metadatas_by_filetype: dict[types.FileType | None, list[types.MetadataOrError]] = {}
    for metadata in metadatas:
        filetype: types.FileType | None
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
        and not _is_error_skipped(type(metadata.error), skipped_process_errors)
    ]
    if critical_error_metadatas:
        raise exceptions.MapillaryProcessError(
            f"Failed to process {len(critical_error_metadatas)} files. To skip these errors, specify --skip_process_errors"
        )


def _show_stats_per_filetype(
    metadatas: T.Collection[types.MetadataOrError],
    filetype: types.FileType | None,
    skipped_process_errors: set[T.Type[Exception]],
):
    good_metadatas: list[types.Metadata]
    good_metadatas, error_metadatas = types.separate_errors(metadatas)

    LOG.info(
        f"{len(metadatas)} {'other file' if filetype is None else filetype.value} read in total"
    )
    if good_metadatas:
        total_filesize = sum(
            [0 if m.filesize is None else m.filesize for m in good_metadatas]
        )
        LOG.info(
            f"\t{len(good_metadatas)} ({humanize.naturalsize(total_filesize)}) ready"
        )

    errors_by_type: dict[type[Exception], list[types.ErrorMetadata]] = {}
    for metadata in error_metadatas:
        errors_by_type.setdefault(type(metadata.error), []).append(metadata)

    for error_type, errors in errors_by_type.items():
        total_filesize = sum([utils.get_file_size_quietly(m.filename) for m in errors])
        if _is_error_skipped(error_type, skipped_process_errors):
            LOG.warning(
                f"\t{len(errors)} ({humanize.naturalsize(total_filesize)}) {error_type.__name__}"
            )
        else:
            LOG.error(
                f"\t{len(errors)} ({humanize.naturalsize(total_filesize)}) {error_type.__name__}"
            )


def _validate_metadatas(
    metadatas: T.Collection[types.MetadataOrError], num_processes: int | None
) -> list[types.MetadataOrError]:
    LOG.info(f"==> Validating {len(metadatas)} metadatas...")

    # validating metadatas is slow, hence multiprocessing

    # Do not pass error metadatas where the error object can not be pickled for multiprocessing to work
    # Otherwise we get:
    # TypeError: __init__() missing 3 required positional arguments: 'image_time', 'gpx_start_time', and 'gpx_end_time'
    # See https://stackoverflow.com/a/61432070
    good_metadatas, error_metadatas = types.separate_errors(metadatas)

    validated_metadatas = list(
        utils.mp_map_maybe(
            validate_and_fail_metadata,
            T.cast(T.Iterable[types.Metadata], good_metadatas),
            num_processes=num_processes,
        )
    )

    return T.cast(list[types.MetadataOrError], validated_metadatas + error_metadatas)


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
