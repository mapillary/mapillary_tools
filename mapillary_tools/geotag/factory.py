from __future__ import annotations

import json
import logging
import typing as T
from pathlib import Path

from .. import exceptions, types, utils
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
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.info(
                f"==> Processing {len(reprocessable_paths)} files with source {option}..."
            )
        else:
            LOG.info(
                f"==> Processing {len(reprocessable_paths)} files with source {option.source.value}..."
            )

        image_videos, video_paths = _filter_images_and_videos(
            reprocessable_paths, option.filetypes
        )

        if image_videos:
            image_geotag = _build_image_geotag(option)
            image_metadata_or_errors = (
                image_geotag.to_description(image_videos) if image_geotag else []
            )
        else:
            image_metadata_or_errors = []

        if video_paths:
            video_geotag = _build_video_geotag(option)
            video_metadata_or_errors = (
                video_geotag.to_description(video_paths) if video_geotag else []
            )
        else:
            video_metadata_or_errors = []

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
                exceptions.MapillaryExiftoolNotFoundError,
                exceptions.MapillaryExifToolXMLNotFoundError,
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


def _build_image_geotag(option: SourceOption) -> base.GeotagImagesFromGeneric | None:
    """
    Build a GeotagImagesFromGeneric object based on the provided option.
    """
    if option.interpolation is None:
        interpolation = InterpolationOption()
    else:
        interpolation = option.interpolation

    if option.source in [SourceType.EXIF, SourceType.NATIVE]:
        return geotag_images_from_exif.GeotagImagesFromEXIF(
            num_processes=option.num_processes
        )

    if option.source is SourceType.EXIFTOOL_RUNTIME:
        return geotag_images_from_exiftool.GeotagImagesFromExifToolRunner(
            num_processes=option.num_processes
        )

    elif option.source is SourceType.EXIFTOOL_XML:
        # This is to ensure 'video_process --geotag={"source": "exiftool_xml", "source_path": "/tmp/xml_path"}'
        # to work
        if option.source_path is None:
            raise exceptions.MapillaryBadParameterError(
                "source_path must be provided for EXIFTOOL_XML source"
            )
        return geotag_images_from_exiftool.GeotagImagesFromExifToolWithSamples(
            source_path=option.source_path,
            num_processes=option.num_processes,
        )

    elif option.source is SourceType.GPX:
        return geotag_images_from_gpx_file.GeotagImagesFromGPXFile(
            source_path=_ensure_source_path(option),
            use_gpx_start_time=interpolation.use_gpx_start_time,
            offset_time=interpolation.offset_time,
            num_processes=option.num_processes,
        )

    elif option.source is SourceType.NMEA:
        return geotag_images_from_nmea_file.GeotagImagesFromNMEAFile(
            source_path=_ensure_source_path(option),
            use_gpx_start_time=interpolation.use_gpx_start_time,
            offset_time=interpolation.offset_time,
            num_processes=option.num_processes,
        )

    elif option.source in [SourceType.GOPRO, SourceType.BLACKVUE, SourceType.CAMM]:
        return geotag_images_from_video.GeotagImageSamplesFromVideo(
            _ensure_source_path(option),
            offset_time=interpolation.offset_time,
            num_processes=option.num_processes,
        )

    else:
        raise ValueError(f"Invalid geotag source {option.source}")


def _build_video_geotag(option: SourceOption) -> base.GeotagVideosFromGeneric | None:
    """
    Build a GeotagVideosFromGeneric object based on the provided option.

    Examples:
        >>> from pathlib import Path
        >>> from mapillary_tools.geotag.options import SourceOption, SourceType
        >>> opt = SourceOption(SourceType.NATIVE)
        >>> geotagger = _build_video_geotag(opt)
        >>> geotagger.__class__.__name__
        'GeotagVideosFromVideo'

        >>> opt = SourceOption(SourceType.EXIFTOOL_RUNTIME)
        >>> geotagger = _build_video_geotag(opt)
        >>> geotagger.__class__.__name__
        'GeotagVideosFromExifToolRunner'

        >>> opt = SourceOption(SourceType.EXIFTOOL_XML, source_path=Path("/tmp/test.xml"))
        >>> geotagger = _build_video_geotag(opt)
        >>> geotagger.__class__.__name__
        'GeotagVideosFromExifToolXML'

        >>> opt = SourceOption(SourceType.GPX, source_path=Path("/tmp/test.gpx"))
        >>> geotagger = _build_video_geotag(opt)
        >>> geotagger.__class__.__name__
        'GeotagVideosFromGPX'

        >>> opt = SourceOption(SourceType.NMEA, source_path=Path("/tmp/test.nmea"))
        >>> _build_video_geotag(opt) is None
        True

        >>> opt = SourceOption(SourceType.EXIF)
        >>> _build_video_geotag(opt) is None
        True

        >>> opt = SourceOption(SourceType.GOPRO)
        >>> _build_video_geotag(opt) is None
        True

        >>> try:
        ...     _build_video_geotag(SourceOption("invalid"))
        ... except ValueError as e:
        ...     "Invalid geotag source" in str(e)
        True
    """
    if option.source is SourceType.NATIVE:
        return geotag_videos_from_video.GeotagVideosFromVideo(
            num_processes=option.num_processes, filetypes=option.filetypes
        )

    if option.source is SourceType.EXIFTOOL_RUNTIME:
        return geotag_videos_from_exiftool.GeotagVideosFromExifToolRunner(
            num_processes=option.num_processes
        )

    elif option.source is SourceType.EXIFTOOL_XML:
        if option.source_path is None:
            raise exceptions.MapillaryBadParameterError(
                "source_path must be provided for EXIFTOOL_XML source"
            )
        return geotag_videos_from_exiftool.GeotagVideosFromExifToolXML(
            source_path=option.source_path,
        )

    elif option.source is SourceType.GPX:
        return geotag_videos_from_gpx.GeotagVideosFromGPX(
            source_path=option.source_path, num_processes=option.num_processes
        )

    elif option.source is SourceType.NMEA:
        # TODO: geotag videos from NMEA
        return None

    elif option.source is SourceType.EXIF:
        # Legacy image-specific geotag types
        return None

    elif option.source in [SourceType.GOPRO, SourceType.BLACKVUE, SourceType.CAMM]:
        # Legacy image-specific geotag types
        return None

    else:
        raise ValueError(f"Invalid geotag source {option.source}")
