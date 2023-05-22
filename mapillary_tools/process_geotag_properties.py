import collections
import datetime
import json
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 8):
    from typing import Literal  # pylint: disable=no-name-in-module
else:
    from typing_extensions import Literal

from tqdm import tqdm

from . import constants, exceptions, exif_write, history, types, utils
from .geotag import (
    geotag_from_blackvue,
    geotag_from_camm,
    geotag_from_exif,
    geotag_from_generic,
    geotag_from_gopro,
    geotag_from_gpx_file,
    geotag_from_nmea_file,
    geotag_from_video,
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
) -> T.List[types.ImageMetadataOrError]:
    geotag: geotag_from_generic.GeotagFromGeneric

    if video_import_path is not None:
        # commands that trigger this branch:
        # video_process video_import_path image_paths --geotag_source gpx --geotag_source_path <gpx_file> --skip_subfolders
        image_paths = list(
            utils.filter_video_samples(
                image_paths, video_import_path, skip_subfolders=skip_subfolders
            )
        )

    if geotag_source == "exif":
        geotag = geotag_from_exif.GeotagFromEXIF(image_paths)

    else:
        if geotag_source_path is None:
            geotag_source_path = video_import_path
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path (--geotag_source_path) is required"
            )
        if not geotag_source_path.is_file():
            raise exceptions.MapillaryFileNotFoundError(
                f"Geotag source file not found: {geotag_source_path}"
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

    return geotag.to_description()


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
) -> T.List[types.MetadataOrError]:
    filetypes = set(FileType(f) for f in filetypes)
    import_paths = _normalize_import_paths(import_path)

    # Check and fail early
    for path in import_paths:
        if not path.is_file() and not path.is_dir():
            raise exceptions.MapillaryFileNotFoundError(
                f"Import file or directory not found: {path}"
            )

    metadatas: T.List[types.MetadataOrError] = []

    # if more than one filetypes speficied, check filename suffixes,
    # i.e. files not ended with .jpg or .mp4 will be ignored
    check_file_suffix = len(filetypes) > 1

    if FileType.IMAGE in filetypes:
        image_paths = utils.find_images(
            import_paths,
            skip_subfolders=skip_subfolders,
            check_file_suffix=check_file_suffix,
        )
        image_metadatas = _process_images(
            image_paths,
            geotag_source=geotag_source,
            geotag_source_path=geotag_source_path,
            video_import_path=video_import_path,
            interpolation_use_gpx_start_time=interpolation_use_gpx_start_time,
            interpolation_offset_time=interpolation_offset_time,
            skip_subfolders=skip_subfolders,
        )
        metadatas.extend(image_metadatas)

    if (
        FileType.CAMM in filetypes
        or FileType.GOPRO in filetypes
        or FileType.BLACKVUE in filetypes
    ):
        video_paths = utils.find_videos(
            import_paths,
            skip_subfolders=skip_subfolders,
            check_file_suffix=check_file_suffix,
        )
        geotag = geotag_from_video.GeotagFromVideo(video_paths, filetypes=filetypes)
        metadatas.extend(geotag.to_descriptions())

    # filenames should be deduplicated in utils.find_images/utils.find_videos
    assert len(metadatas) == len(
        set(metadata.filename for metadata in metadatas)
    ), "duplicate filenames found"

    return metadatas


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
        dt = datetime.datetime.utcfromtimestamp(metadata.time)
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


def _is_error_skipped(
    error_type: str, skipped_process_errors: T.Set[T.Type[Exception]]
):
    skipped_process_error_names = set(err.__name__ for err in skipped_process_errors)
    skip_all = Exception in skipped_process_errors
    return skip_all or error_type in skipped_process_error_names


def _show_stats(
    metadatas: T.Sequence[types.MetadataOrError],
    skipped_process_errors: T.Set[T.Type[Exception]],
) -> None:
    metadatas_by_filetype: T.Dict[FileType, T.List[types.MetadataOrError]] = {}
    for metadata in metadatas:
        filetype: T.Optional[FileType]
        if isinstance(metadata, types.ImageMetadata):
            filetype = FileType.IMAGE
        else:
            filetype = metadata.filetype
        if filetype:
            metadatas_by_filetype.setdefault(FileType(filetype), []).append(metadata)

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
    metadatas: T.Sequence[types.MetadataOrError],
    filetype: FileType,
    skipped_process_errors: T.Set[T.Type[Exception]],
):
    good_metadatas: T.List[T.Union[types.VideoMetadata, types.ImageMetadata]] = []
    error_metadatas: T.List[types.ErrorMetadata] = []
    for metadata in metadatas:
        if isinstance(metadata, types.ErrorMetadata):
            error_metadatas.append(metadata)
        else:
            good_metadatas.append(metadata)

    LOG.info("%8d %s(s) read in total", len(metadatas), filetype.value)
    if good_metadatas:
        LOG.info(
            "\t %8d %s(s) are ready to be uploaded",
            len(good_metadatas),
            filetype.value,
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


_IT = T.TypeVar("_IT")


def split_if(
    it: T.Iterable[_IT], sep: T.Callable[[_IT], bool]
) -> T.Tuple[T.List[_IT], T.List[_IT]]:
    yes, no = [], []
    for e in it:
        if sep(e):
            yes.append(e)
        else:
            no.append(e)
    return yes, no


def _check_upload_status(
    metadatas: T.Sequence[types.MetadataOrError],
) -> T.List[types.MetadataOrError]:
    groups = types.group_and_sort_images(
        [
            metadata
            for metadata in metadatas
            if isinstance(metadata, types.ImageMetadata)
        ]
    )
    uploaded_sequence_uuids = set()
    for sequence_uuid, group in groups.items():
        for m in group:
            m.update_md5sum()
        sequence_md5sum = types.sequence_md5sum(group)
        if history.is_uploaded(sequence_md5sum):
            uploaded_sequence_uuids.add(sequence_uuid)

    output: T.List[types.MetadataOrError] = []
    for metadata in metadatas:
        if isinstance(metadata, types.ImageMetadata):
            if metadata.MAPSequenceUUID in uploaded_sequence_uuids:
                output.append(
                    types.describe_error_metadata(
                        exceptions.MapillaryUploadedAlreadyError(
                            "The image was already uploaded",
                            types.as_desc(metadata),
                        ),
                        filename=metadata.filename,
                        filetype=types.FileType.IMAGE,
                    )
                )
            else:
                output.append(metadata)
        elif isinstance(metadata, types.VideoMetadata):
            metadata.update_md5sum()
            assert isinstance(metadata.md5sum, str)
            if history.is_uploaded(metadata.md5sum):
                output.append(
                    types.describe_error_metadata(
                        exceptions.MapillaryUploadedAlreadyError(
                            "The video was already uploaded",
                            types.as_desc(metadata),
                        ),
                        filename=metadata.filename,
                        filetype=metadata.filetype,
                    )
                )
            else:
                output.append(metadata)
        else:
            output.append(metadata)
    assert len(output) == len(metadatas), "length mismatch"
    return output


def process_finalize(
    import_path: T.Union[T.Sequence[Path], Path],
    metadatas: T.List[types.MetadataOrError],
    skip_process_errors: bool = False,
    overwrite_all_EXIF_tags: bool = False,
    overwrite_EXIF_time_tag: bool = False,
    overwrite_EXIF_gps_tag: bool = False,
    overwrite_EXIF_direction_tag: bool = False,
    overwrite_EXIF_orientation_tag: bool = False,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    desc_path: T.Optional[str] = None,
) -> T.List[types.MetadataOrError]:
    # modified in place
    _apply_offsets(
        [
            metadata
            for metadata in metadatas
            if isinstance(metadata, types.ImageMetadata)
        ],
        offset_time=offset_time,
        offset_angle=offset_angle,
    )

    LOG.info("Validating %d metadatas", len(metadatas))
    metadatas = [types.validate_and_fail_metadata(metadata) for metadata in metadatas]

    LOG.info("Checking upload status for %d metadatas", len(metadatas))
    metadatas = _check_upload_status(metadatas)

    _overwrite_exif_tags(
        # search image metadatas again because some of them might have been failed
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

    # show stats
    skipped_process_errors: T.Set[T.Type[Exception]]
    if skip_process_errors:
        # skip all exceptions
        skipped_process_errors = {Exception}
    else:
        skipped_process_errors = {
            exceptions.MapillaryDuplicationError,
            exceptions.MapillaryUploadedAlreadyError,
        }
    _show_stats(metadatas, skipped_process_errors=skipped_process_errors)

    return metadatas
