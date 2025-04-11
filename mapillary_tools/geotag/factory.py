from __future__ import annotations

import json
import logging
import typing as T
from pathlib import Path

from .. import exceptions, types, utils
from ..types import FileType
from . import (
    base,
    geotag_images_from_exif,
    geotag_images_from_exiftool,
    geotag_images_from_gpx_file,
    geotag_images_from_nmea_file,
    geotag_images_from_video,
    geotag_videos_from_exiftool,
    geotag_videos_from_gpx,
    geotag_videos_from_video,
)
from .options import InterpolationOption, SOURCE_TYPE_ALIAS, SourceOption, SourceType


LOG = logging.getLogger(__name__)


def parse_source_option(source: str) -> list[SourceOption]:
    """
    Given a source string, parse it into a list of GeotagOptions objects.

    Examples:
        "native" -> [SourceOption(SourceType.NATIVE)]
        "gpx,exif" -> [SourceOption(SourceType.GPX), SourceOption(SourceType.EXIF)]
        "exif,gpx" -> [SourceOption(SourceType.EXIF), SourceOption(SourceType.GPX)]
        '{"source": "gpx"}' -> [SourceOption(SourceType.GPX)]
    """

    try:
        source_type = SourceType(SOURCE_TYPE_ALIAS.get(source, source))
    except ValueError:
        pass
    else:
        return [SourceOption(source_type)]

    try:
        payload = json.loads(source)
    except json.JSONDecodeError:
        pass
    else:
        return [SourceOption.from_dict(payload)]

    sources = source.split(",")

    return [SourceOption(SourceType(SOURCE_TYPE_ALIAS.get(s, s))) for s in sources]


def process(
    # Collection: ABC for sized iterable container classes
    paths: T.Iterable[Path],
    options: T.Collection[SourceOption],
) -> list[types.MetadataOrError]:
    if not options:
        raise ValueError("No geotag options provided")

    final_metadatas: list[types.MetadataOrError] = []

    # Paths (image path or video path) that will be sent to the next geotag process
    reprocessable_paths = set(paths)

    for idx, option in enumerate(options):
        LOG.debug("Processing %d files with %s", len(reprocessable_paths), option)

        image_metadata_or_errors = _geotag_images(reprocessable_paths, option)
        video_metadata_or_errors = _geotag_videos(reprocessable_paths, option)

        more_option = idx < len(options) - 1

        for metadata in image_metadata_or_errors + video_metadata_or_errors:
            if more_option and _is_reprocessable(metadata):
                # Leave what it is for the next geotag process
                pass
            else:
                final_metadatas.append(metadata)
                reprocessable_paths.remove(metadata.filename)

        # Quit if no more paths to process
        if not reprocessable_paths:
            break

    return final_metadatas


def _is_reprocessable(metadata: types.MetadataOrError) -> bool:
    if isinstance(metadata, types.ErrorMetadata):
        if isinstance(
            metadata.error,
            (
                exceptions.MapillaryGeoTaggingError,
                exceptions.MapillaryVideoGPSNotFoundError,
            ),
        ):
            return True

    return False


def _filter_images_and_videos(
    paths: T.Iterable[Path],
    filetypes: set[types.FileType] | None = None,
) -> tuple[list[Path], list[Path]]:
    image_paths = []
    video_paths = []

    ALL_VIDEO_TYPES = {types.FileType.VIDEO, *types.NATIVE_VIDEO_FILETYPES}

    if filetypes is None:
        include_images = True
        include_videos = True
    else:
        include_images = types.FileType.IMAGE in filetypes
        include_videos = bool(filetypes & ALL_VIDEO_TYPES)

    for path in paths:
        if utils.is_image_file(path):
            if include_images:
                image_paths.append(path)

        elif utils.is_video_file(path):
            if include_videos:
                video_paths.append(path)

    return image_paths, video_paths


def _ensure_source_path(option: SourceOption) -> Path:
    if option.source_path is None or option.source_path.source_path is None:
        raise exceptions.MapillaryBadParameterError(
            f"source_path must be provided for {option.source}"
        )
    return option.source_path.source_path


def _geotag_images(
    paths: T.Iterable[Path], option: SourceOption
) -> list[types.ImageMetadataOrError]:
    image_paths, _ = _filter_images_and_videos(paths, option.filetypes)

    if not image_paths:
        return []

    if option.interpolation is None:
        interpolation = InterpolationOption()
    else:
        interpolation = option.interpolation

    geotag: base.GeotagImagesFromGeneric

    if option.source is SourceType.NATIVE:
        geotag = geotag_images_from_exif.GeotagImagesFromEXIF(
            num_processes=option.num_processes
        )
        return geotag.to_description(image_paths)

    if option.source is SourceType.EXIFTOOL_RUNTIME:
        geotag = geotag_images_from_exiftool.GeotagImagesFromExifToolRunner(
            num_processes=option.num_processes
        )
        try:
            return geotag.to_description(image_paths)
        except exceptions.MapillaryExiftoolNotFoundError as ex:
            LOG.warning('Skip "%s" because: %s', option.source.value, ex)
            return []

    elif option.source is SourceType.EXIFTOOL_XML:
        # This is to ensure 'video_process --geotag={"source": "exiftool_xml", "source_path": "/tmp/xml_path"}'
        # to work
        geotag = geotag_images_from_exiftool.GeotagImagesFromExifToolWithSamples(
            xml_path=_ensure_source_path(option),
            num_processes=option.num_processes,
        )
        return geotag.to_description(image_paths)

    elif option.source is SourceType.GPX:
        geotag = geotag_images_from_gpx_file.GeotagImagesFromGPXFile(
            source_path=_ensure_source_path(option),
            use_gpx_start_time=interpolation.use_gpx_start_time,
            offset_time=interpolation.offset_time,
            num_processes=option.num_processes,
        )
        return geotag.to_description(image_paths)

    elif option.source is SourceType.NMEA:
        geotag = geotag_images_from_nmea_file.GeotagImagesFromNMEAFile(
            source_path=_ensure_source_path(option),
            use_gpx_start_time=interpolation.use_gpx_start_time,
            offset_time=interpolation.offset_time,
            num_processes=option.num_processes,
        )

        return geotag.to_description(image_paths)

    elif option.source is SourceType.EXIF:
        geotag = geotag_images_from_exif.GeotagImagesFromEXIF(
            num_processes=option.num_processes
        )
        return geotag.to_description(image_paths)

    elif option.source in [
        SourceType.GOPRO,
        SourceType.BLACKVUE,
        SourceType.CAMM,
    ]:
        map_geotag_source_to_filetype: dict[SourceType, FileType] = {
            SourceType.GOPRO: FileType.GOPRO,
            SourceType.BLACKVUE: FileType.BLACKVUE,
            SourceType.CAMM: FileType.CAMM,
        }
        video_paths = utils.find_videos([_ensure_source_path(option)])
        image_samples_by_video_path = utils.find_all_image_samples(
            image_paths, video_paths
        )
        video_paths_with_image_samples = list(image_samples_by_video_path.keys())
        video_metadatas = geotag_videos_from_video.GeotagVideosFromVideo(
            filetypes={map_geotag_source_to_filetype[option.source]},
            num_processes=option.num_processes,
        ).to_description(video_paths_with_image_samples)
        geotag = geotag_images_from_video.GeotagImagesFromVideo(
            video_metadatas,
            offset_time=interpolation.offset_time,
            num_processes=option.num_processes,
        )
        return geotag.to_description(image_paths)

    else:
        raise ValueError(f"Invalid geotag source {option.source}")


def _geotag_videos(
    paths: T.Iterable[Path], option: SourceOption
) -> list[types.VideoMetadataOrError]:
    _, video_paths = _filter_images_and_videos(paths, option.filetypes)

    if not video_paths:
        return []

    geotag: base.GeotagVideosFromGeneric

    if option.source is SourceType.NATIVE:
        geotag = geotag_videos_from_video.GeotagVideosFromVideo(
            num_processes=option.num_processes, filetypes=option.filetypes
        )
        return geotag.to_description(video_paths)

    if option.source is SourceType.EXIFTOOL_RUNTIME:
        geotag = geotag_videos_from_exiftool.GeotagVideosFromExifToolRunner(
            num_processes=option.num_processes
        )
        try:
            return geotag.to_description(video_paths)
        except exceptions.MapillaryExiftoolNotFoundError as ex:
            LOG.warning('Skip "%s" because: %s', option.source.value, ex)
            return []

    elif option.source is SourceType.EXIFTOOL_XML:
        geotag = geotag_videos_from_exiftool.GeotagVideosFromExifToolXML(
            xml_path=_ensure_source_path(option),
        )
        return geotag.to_description(video_paths)

    elif option.source is SourceType.GPX:
        geotag = geotag_videos_from_gpx.GeotagVideosFromGPX()
        return geotag.to_description(video_paths)

    elif option.source is SourceType.NMEA:
        # TODO: geotag videos from NMEA
        return []

    elif option.source is SourceType.EXIF:
        # Legacy image-specific geotag types
        return []

    elif option.source in [
        SourceType.GOPRO,
        SourceType.BLACKVUE,
        SourceType.CAMM,
    ]:
        # Legacy image-specific geotag types
        return []

    else:
        raise ValueError(f"Invalid geotag source {option.source}")
