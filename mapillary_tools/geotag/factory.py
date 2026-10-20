# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

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
from .options import (
    InterpolationOption,
    SOURCE_TYPE_ALIAS,
    SourceOption,
    SourcePathOption,
    SourceType,
)


LOG = logging.getLogger(__name__)

_ALL_VIDEO_TYPES = {types.FileType.VIDEO, *types.NATIVE_VIDEO_FILETYPES}

# Sources that read a GPS track from outside the video file, as opposed to
# re-reading the telemetry embedded in it. (NMEA cannot geotag videos yet: it
# skips them, and they keep the error they had)
EXTERNAL_GPS_SOURCES = frozenset({SourceType.GPX, SourceType.NMEA})


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


def parse_source_options(
    geotag_source: T.Sequence[str],
    video_geotag_source: T.Sequence[str],
    geotag_source_path: Path | None,
) -> list[SourceOption]:
    """
    Turn the raw --geotag_source / --video_geotag_source / --geotag_source_path
    arguments into the option list that process() consumes.
    """
    parsed_options: list[SourceOption] = []

    if video_geotag_source and geotag_source:
        LOG.warning(
            "Video source options will be processed BEFORE the generic source options"
        )

    for s in video_geotag_source:
        for video_option in parse_source_option(s):
            video_option.filetypes = types.combine_filetype_filters(
                video_option.filetypes, {types.FileType.VIDEO}
            )
            parsed_options.append(video_option)

    for s in geotag_source:
        parsed_options.extend(parse_source_option(s))

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


def can_geotag_videos(option: SourceOption) -> bool:
    """
    Whether process() can read positions for videos from the source: it has a
    video extractor, and its filetypes let videos through. process() returns no
    metadata at all for a video that no source can read.

    Examples:
        >>> can_geotag_videos(SourceOption(SourceType.GPX))
        True
        >>> can_geotag_videos(SourceOption(SourceType.EXIF))
        False
        >>> can_geotag_videos(
        ...     SourceOption(SourceType.NATIVE, filetypes={types.FileType.IMAGE})
        ... )
        False
    """
    if option.filetypes is not None and not option.filetypes & _ALL_VIDEO_TYPES:
        return False

    return _build_video_geotag(option) is not None


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

    # The latest error of each path left for the next geotag process, reported
    # if no later process geotags the path (or none of them handles it)
    pending_errors: dict[Path, types.ErrorMetadata] = {}

    # Videos whose own GPS was found but rejected as empty or noisy. That is a
    # verdict on the data, not on the reader that reported it, so only a source
    # outside the video may geotag them now. Another reader of the same
    # telemetry (e.g. exiftool after native) can only repeat the verdict, or
    # overturn it by reading the same bad data differently
    rejected_gps_paths: set[Path] = set()

    # Paths whose GPX track missed them, with the source that rejected them, to
    # warn about if a later source geotags them instead
    gpx_rejections: dict[Path, tuple[SourceOption, types.ErrorMetadata]] = {}

    for option in options:
        if option.source in EXTERNAL_GPS_SOURCES:
            option_paths = reprocessable_paths
        else:
            option_paths = reprocessable_paths - rejected_gps_paths

        if LOG.isEnabledFor(logging.DEBUG):
            LOG.info(
                f"==> Processing {len(option_paths)} files with source {option}..."
            )
        else:
            LOG.info(
                f"==> Processing {len(option_paths)} files with source {option.source.value}..."
            )

        image_videos, video_paths = _filter_images_and_videos(
            option_paths, option.filetypes
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

        rescued: list[
            tuple[types.MetadataOrError, SourceOption, types.ErrorMetadata]
        ] = []

        for metadata in image_metadata_or_errors + video_metadata_or_errors:
            if isinstance(metadata, types.ErrorMetadata) and _is_reprocessable(
                metadata
            ):
                # Leave what it is for the next geotag process
                if isinstance(metadata.error, exceptions.MapillaryOutsideGPXTrackError):
                    gpx_rejections[metadata.filename] = (option, metadata)
                if isinstance(
                    metadata.error,
                    (
                        exceptions.MapillaryGPXEmptyError,
                        exceptions.MapillaryGPSNoiseError,
                    ),
                ):
                    rejected_gps_paths.add(metadata.filename)
                elif metadata.filename in rejected_gps_paths and isinstance(
                    metadata.error, exceptions.MapillaryVideoGPSUnusableError
                ):
                    # Why the video's own GPS was rejected says more than the
                    # fallback finding nothing (e.g. "GPX file not found")
                    continue
                pending_errors[metadata.filename] = metadata
            else:
                final_metadatas.append(metadata)
                reprocessable_paths.remove(metadata.filename)
                pending_errors.pop(metadata.filename, None)
                rejection = gpx_rejections.pop(metadata.filename, None)
                if rejection is not None and not isinstance(
                    metadata, types.ErrorMetadata
                ):
                    rescued.append((metadata, *rejection))

        _warn_geotagged_despite_gpx(rescued, option)

        # Quit if no more paths to process
        if not reprocessable_paths:
            break

    final_metadatas.extend(pending_errors.values())

    return final_metadatas


def _warn_geotagged_despite_gpx(
    rescued: T.Sequence[
        tuple[types.MetadataOrError, SourceOption, types.ErrorMetadata]
    ],
    option: SourceOption,
) -> None:
    """
    Warn about the files whose GPX track missed them, but which the source
    **option** geotagged instead, so that a GPX that does not belong to them
    does not go unnoticed: one warning per video, and one per GPX source for
    images, of which a GPX can miss many.
    """
    images_by_gpx_option: dict[int, tuple[SourceOption, list[Path]]] = {}

    for metadata, gpx_option, rejection in rescued:
        if isinstance(metadata, types.VideoMetadata):
            LOG.warning(
                f"{rejection.error}. Geotagged it from the {option.source.value} source instead"
            )
        else:
            images_by_gpx_option.setdefault(id(gpx_option), (gpx_option, []))[1].append(
                metadata.filename
            )

    for gpx_option, image_paths in images_by_gpx_option.values():
        gpx_path = gpx_option.source_path and gpx_option.source_path.source_path
        gpx_track = f"the GPX track in {gpx_path}" if gpx_path else "the GPX track"
        if len(image_paths) == 1:
            images, them = "1 image falls", "it"
        else:
            images, them = f"{len(image_paths)} images fall", "them"
        LOG.warning(
            f"{images} outside {gpx_track}. "
            f"Geotagged {them} from the {option.source.value} source instead"
        )
        LOG.debug("Images outside %s: %s", gpx_track, [p.name for p in image_paths])


def _is_reprocessable(metadata: types.MetadataOrError) -> bool:
    if isinstance(metadata, types.ErrorMetadata):
        if isinstance(
            metadata.error,
            (
                exceptions.MapillaryGeoTaggingError,
                exceptions.MapillaryVideoGPSUnusableError,
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

    if filetypes is None:
        include_images = True
        include_videos = True
    else:
        include_images = types.FileType.IMAGE in filetypes
        include_videos = bool(filetypes & _ALL_VIDEO_TYPES)

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
            source_path=option.source_path,
            num_processes=option.num_processes,
            video_sync=option.video_sync,
            interpolation=option.interpolation,
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
