import collections
import datetime
import itertools
import json
import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from . import constants, exceptions, exif_write, history, types, utils
from .geotag import (
    geotag_from_generic,
    geotag_images_from_exif,
    geotag_images_from_exiftool_both_image_and_video,
    geotag_images_from_gpx_file,
    geotag_images_from_nmea_file,
    geotag_images_from_video,
    geotag_videos_from_exiftool_video,
    geotag_videos_from_video,
)
from .types import FileType, VideoMetadataOrError

from .video_data_extraction.cli_options import CliOptions, CliParserOptions
from .video_data_extraction.extract_video_data import VideoDataExtractor


LOG = logging.getLogger(__name__)


GeotagSource = T.Literal[
    "gopro_videos", "blackvue_videos", "camm", "exif", "gpx", "nmea", "exiftool"
]

VideoGeotagSource = T.Literal[
    "video",
    "camm",
    "gopro",
    "blackvue",
    "gpx",
    "nmea",
    "exiftool_xml",
    "exiftool_runtime",
]


def _process_images(
    image_paths: T.Sequence[Path],
    geotag_source: GeotagSource,
    geotag_source_path: T.Optional[Path] = None,
    video_import_path: T.Optional[Path] = None,
    interpolation_use_gpx_start_time: bool = False,
    interpolation_offset_time: float = 0.0,
    num_processes: T.Optional[int] = None,
    skip_subfolders=False,
) -> T.Sequence[types.ImageMetadataOrError]:
    geotag: geotag_from_generic.GeotagImagesFromGeneric

    if video_import_path is not None:
        # commands that trigger this branch:
        # video_process video_import_path image_paths --geotag_source gpx --geotag_source_path <gpx_file> --skip_subfolders
        image_paths = list(
            utils.filter_video_samples(
                image_paths, video_import_path, skip_subfolders=skip_subfolders
            )
        )

    if geotag_source == "exif":
        geotag = geotag_images_from_exif.GeotagImagesFromEXIF(
            image_paths, num_processes=num_processes
        )

    else:
        if geotag_source_path is None:
            geotag_source_path = video_import_path
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path (--geotag_source_path) is required"
            )
        if geotag_source == "exiftool":
            if not geotag_source_path.exists():
                raise exceptions.MapillaryFileNotFoundError(
                    f"Geotag source file not found: {geotag_source_path}"
                )
        else:
            if not geotag_source_path.is_file():
                raise exceptions.MapillaryFileNotFoundError(
                    f"Geotag source file not found: {geotag_source_path}"
                )

        if geotag_source == "gpx":
            geotag = geotag_images_from_gpx_file.GeotagImagesFromGPXFile(
                image_paths,
                geotag_source_path,
                use_gpx_start_time=interpolation_use_gpx_start_time,
                offset_time=interpolation_offset_time,
                num_processes=num_processes,
            )
        elif geotag_source == "nmea":
            geotag = geotag_images_from_nmea_file.GeotagImagesFromNMEAFile(
                image_paths,
                geotag_source_path,
                use_gpx_start_time=interpolation_use_gpx_start_time,
                offset_time=interpolation_offset_time,
                num_processes=num_processes,
            )
        elif geotag_source in ["gopro_videos", "blackvue_videos", "camm"]:
            map_geotag_source_to_filetype: T.Dict[GeotagSource, FileType] = {
                "gopro_videos": FileType.GOPRO,
                "blackvue_videos": FileType.BLACKVUE,
                "camm": FileType.CAMM,
            }
            video_paths = utils.find_videos([geotag_source_path])
            image_samples_by_video_path = utils.find_all_image_samples(
                image_paths, video_paths
            )
            video_paths_with_image_samples = list(image_samples_by_video_path.keys())
            video_metadatas = geotag_videos_from_video.GeotagVideosFromVideo(
                video_paths_with_image_samples,
                filetypes={map_geotag_source_to_filetype[geotag_source]},
                num_processes=num_processes,
            ).to_description()
            geotag = geotag_images_from_video.GeotagImagesFromVideo(
                image_paths,
                video_metadatas,
                offset_time=interpolation_offset_time,
                num_processes=num_processes,
            )
        elif geotag_source == "exiftool":
            geotag = geotag_images_from_exiftool_both_image_and_video.GeotagImagesFromExifToolBothImageAndVideo(
                image_paths,
                geotag_source_path,
            )
        else:
            raise RuntimeError(f"Invalid geotag source {geotag_source}")

    return geotag.to_description()


def _process_videos(
    geotag_source: str,
    geotag_source_path: T.Optional[Path],
    video_paths: T.Sequence[Path],
    num_processes: T.Optional[int],
    filetypes: T.Optional[T.Set[FileType]],
) -> T.Sequence[VideoMetadataOrError]:
    geotag: geotag_from_generic.GeotagVideosFromGeneric
    if geotag_source == "exiftool":
        if geotag_source_path is None:
            raise exceptions.MapillaryFileNotFoundError(
                "Geotag source path (--geotag_source_path) is required"
            )
        if not geotag_source_path.exists():
            raise exceptions.MapillaryFileNotFoundError(
                f"Geotag source file not found: {geotag_source_path}"
            )
        geotag = geotag_videos_from_exiftool_video.GeotagVideosFromExifToolVideo(
            video_paths,
            geotag_source_path,
            num_processes=num_processes,
        )
    else:
        geotag = geotag_videos_from_video.GeotagVideosFromVideo(
            video_paths,
            filetypes=filetypes,
            num_processes=num_processes,
        )
    return geotag.to_description()


def _normalize_import_paths(
    import_path: T.Union[Path, T.Sequence[Path]],
) -> T.Sequence[Path]:
    import_paths: T.Sequence[Path]
    if isinstance(import_path, Path):
        import_paths = [import_path]
    else:
        import_paths = import_path
    import_paths = list(utils.deduplicate_paths(import_paths))
    return import_paths


def process_geotag_properties(
    vars_args: T.Dict,  # Hello, I'm a hack
    import_path: T.Union[Path, T.Sequence[Path]],
    filetypes: T.Set[FileType],
    geotag_source: GeotagSource,
    geotag_source_path: T.Optional[Path] = None,
    # video_import_path comes from the command video_process
    video_import_path: T.Optional[Path] = None,
    interpolation_use_gpx_start_time: bool = False,
    interpolation_offset_time: float = 0.0,
    skip_subfolders=False,
    num_processes: T.Optional[int] = None,
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

    if FileType.IMAGE in filetypes:
        image_paths = utils.find_images(import_paths, skip_subfolders=skip_subfolders)
        if image_paths:
            image_metadatas = _process_images(
                image_paths,
                geotag_source=geotag_source,
                geotag_source_path=geotag_source_path,
                video_import_path=video_import_path,
                interpolation_use_gpx_start_time=interpolation_use_gpx_start_time,
                interpolation_offset_time=interpolation_offset_time,
                num_processes=num_processes,
                skip_subfolders=skip_subfolders,
            )
            metadatas.extend(image_metadatas)

    # --video_geotag_source is still experimental, for videos execute it XOR the legacy code
    if vars_args["video_geotag_source"]:
        metadatas.extend(_process_videos_beta(vars_args))
    else:
        if (
            FileType.CAMM in filetypes
            or FileType.GOPRO in filetypes
            or FileType.BLACKVUE in filetypes
            or FileType.VIDEO in filetypes
        ):
            video_paths = utils.find_videos(
                import_paths, skip_subfolders=skip_subfolders
            )
            if video_paths:
                video_metadata = _process_videos(
                    geotag_source,
                    geotag_source_path,
                    video_paths,
                    num_processes,
                    filetypes,
                )
                metadatas.extend(video_metadata)

    # filenames should be deduplicated in utils.find_images/utils.find_videos
    assert len(metadatas) == len(set(metadata.filename for metadata in metadatas)), (
        "duplicate filenames found"
    )

    return metadatas


def _process_videos_beta(vars_args: T.Dict):
    geotag_sources = vars_args["video_geotag_source"]
    geotag_sources_opts: T.List[CliParserOptions] = []
    for source in geotag_sources:
        parsed_opts: CliParserOptions = {}
        try:
            parsed_opts = json.loads(source)
        except ValueError:
            if source not in T.get_args(VideoGeotagSource):
                raise exceptions.MapillaryBadParameterError(
                    "Unknown beta source %s or invalid JSON", source
                )
            parsed_opts = {"source": source}

        if "source" not in parsed_opts:
            raise exceptions.MapillaryBadParameterError("Missing beta source name")

        geotag_sources_opts.append(parsed_opts)

    options: CliOptions = {
        "paths": vars_args["import_path"],
        "recursive": vars_args["skip_subfolders"] is False,
        "geotag_sources_options": geotag_sources_opts,
        "geotag_source_path": vars_args["geotag_source_path"],
        "num_processes": vars_args["num_processes"],
        "device_make": vars_args["device_make"],
        "device_model": vars_args["device_model"],
    }
    extractor = VideoDataExtractor(options)
    return extractor.process()


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
    filesize_to_upload = 0
    error_metadatas: T.List[types.ErrorMetadata] = []
    for metadata in metadatas:
        if isinstance(metadata, types.ErrorMetadata):
            error_metadatas.append(metadata)
        else:
            good_metadatas.append(metadata)
            filesize_to_upload += metadata.filesize or 0

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


def _validate_metadatas(
    metadatas: T.Sequence[types.MetadataOrError], num_processes: T.Optional[int]
) -> T.List[types.MetadataOrError]:
    # validating metadatas is slow, hence multiprocessing
    if num_processes is None:
        pool_num_processes = None
        disable_multiprocessing = False
    else:
        pool_num_processes = max(num_processes, 1)
        disable_multiprocessing = num_processes <= 0
    with Pool(processes=pool_num_processes) as pool:
        validated_metadatas_iter: T.Iterator[types.MetadataOrError]
        if disable_multiprocessing:
            validated_metadatas_iter = map(types.validate_and_fail_metadata, metadatas)
        else:
            # Do not pass error metadatas where the error object can not be pickled for multiprocessing to work
            # Otherwise we get:
            # TypeError: __init__() missing 3 required positional arguments: 'image_time', 'gpx_start_time', and 'gpx_end_time'
            # See https://stackoverflow.com/a/61432070
            yes, no = split_if(metadatas, lambda m: isinstance(m, types.ErrorMetadata))
            no_iter = pool.imap(
                types.validate_and_fail_metadata,
                no,
            )
            validated_metadatas_iter = itertools.chain(yes, no_iter)
        return list(
            tqdm(
                validated_metadatas_iter,
                desc="Validating metadatas",
                unit="metadata",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                total=len(metadatas),
            )
        )


def process_finalize(
    import_path: T.Union[T.Sequence[Path], Path],
    metadatas: T.List[types.MetadataOrError],
    skip_process_errors: bool = False,
    device_make: T.Optional[str] = None,
    device_model: T.Optional[str] = None,
    overwrite_all_EXIF_tags: bool = False,
    overwrite_EXIF_time_tag: bool = False,
    overwrite_EXIF_gps_tag: bool = False,
    overwrite_EXIF_direction_tag: bool = False,
    overwrite_EXIF_orientation_tag: bool = False,
    offset_time: float = 0.0,
    offset_angle: float = 0.0,
    desc_path: T.Optional[str] = None,
    num_processes: T.Optional[int] = None,
) -> T.List[types.MetadataOrError]:
    for metadata in metadatas:
        if isinstance(metadata, types.VideoMetadata):
            if device_make is not None:
                metadata.make = device_make
            if device_model is not None:
                metadata.model = device_model
        elif isinstance(metadata, types.ImageMetadata):
            if device_make is not None:
                metadata.MAPDeviceMake = device_make
            if device_model is not None:
                metadata.MAPDeviceModel = device_model

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

    LOG.debug("Validating %d metadatas", len(metadatas))
    metadatas = _validate_metadatas(metadatas, num_processes)

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
