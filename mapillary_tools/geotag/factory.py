# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import json
import logging
import typing as T
from pathlib import Path

import jsonschema

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
    geotag_videos_from_nmea,
    geotag_videos_from_video,
)
from .options import (
    InterpolationOption,
    SOURCE_TYPE_ALIAS,
    SourceOption,
    SourcePathOption,
    SourceType,
    VIDEO_SOURCE_TYPE_ALIAS,
)


LOG = logging.getLogger(__name__)

_ALL_VIDEO_TYPES = {types.FileType.VIDEO, *types.NATIVE_VIDEO_FILETYPES}

# As a --video_geotag_source, each of the legacy sources that geotag images from
# videos reads the GPS of the videos of its type, as it did before v0.14
_VIDEO_TYPE_OF_LEGACY_SOURCE = {
    SourceType.GOPRO: types.FileType.GOPRO,
    SourceType.BLACKVUE: types.FileType.BLACKVUE,
    SourceType.CAMM: types.FileType.CAMM,
}

_VIDEO_TYPE_NAMES = {
    types.FileType.GOPRO: "GoPro",
    types.FileType.BLACKVUE: "BlackVue",
    types.FileType.CAMM: "CAMM",
}

# The XML that the exiftool_xml source reads for a file, without a source path
# or a pattern: the output of `exiftool -X` for it, named after it
_EXIFTOOL_XML_DEFAULT_PATTERN = "%g.xml"

# Sources that read a GPS track from outside the video file, as opposed to
# re-reading the telemetry embedded in it
EXTERNAL_GPS_SOURCES = frozenset({SourceType.GPX, SourceType.NMEA})


def parse_source_option(source: str, video: bool = False) -> list[SourceOption]:
    """
    Given a source string, parse it into a list of GeotagOptions objects.

    Examples:
        "native" -> [SourceOption(SourceType.NATIVE)]
        "gpx,exif" -> [SourceOption(SourceType.GPX), SourceOption(SourceType.EXIF)]
        "exif,gpx" -> [SourceOption(SourceType.EXIF), SourceOption(SourceType.GPX)]
        '{"source": "gpx"}' -> [SourceOption(SourceType.GPX)]

    A --video_geotag_source (**video**) takes the names of
    VIDEO_SOURCE_TYPE_ALIAS too.

    Raise MapillaryBadParameterError for an unknown source type, and for a
    JSON object that does not match SourceOptionSchema.
    """
    aliases = {**SOURCE_TYPE_ALIAS, **VIDEO_SOURCE_TYPE_ALIAS} if video else None

    try:
        source_type = _parse_source_type(source, aliases)
    except exceptions.MapillaryBadParameterError:
        pass
    else:
        return [SourceOption(source_type)]

    try:
        payload = json.loads(source)
    except json.JSONDecodeError:
        pass
    else:
        if aliases and isinstance(payload, dict):
            name = payload.get("source")
            if isinstance(name, str) and name in VIDEO_SOURCE_TYPE_ALIAS:
                payload = {**payload, "source": VIDEO_SOURCE_TYPE_ALIAS[name].value}
        try:
            return [SourceOption.from_dict(payload)]
        except jsonschema.ValidationError as ex:
            raise exceptions.MapillaryBadParameterError(
                f"Invalid geotag source {source}: {ex.message}"
            ) from ex

    sources = source.split(",")

    return [SourceOption(_parse_source_type(s, aliases)) for s in sources]


def _parse_source_type(
    source: str, aliases: T.Mapping[str, SourceType] | None = None
) -> SourceType:
    if aliases is None:
        aliases = SOURCE_TYPE_ALIAS
    try:
        return SourceType(aliases.get(source, source))
    except ValueError:
        raise exceptions.MapillaryBadParameterError(
            f"Invalid geotag source {source!r}. Supported source types: "
            f"{', '.join(s.value for s in SourceType)} "
            f"(aliases: {', '.join(aliases)})"
        ) from None


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
        for video_option in parse_source_option(s, video=True):
            parsed_options.append(_as_video_source(video_option))

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


def _as_video_source(option: SourceOption) -> SourceOption:
    """
    Limit a --video_geotag_source option to videos. The legacy gopro, blackvue
    and camm sources, which otherwise geotag images from videos, read the
    video's own GPS as the native source does, from the videos of their type

    >>> option = _as_video_source(SourceOption(SourceType.GOPRO))
    >>> option.source, option.filetypes
    (<SourceType.NATIVE: 'native'>, {<FileType.GOPRO: 'gopro'>})
    >>> option = _as_video_source(SourceOption(SourceType.GPX))
    >>> option.source, option.filetypes
    (<SourceType.GPX: 'gpx'>, {<FileType.VIDEO: 'video'>})
    """
    video_type = _VIDEO_TYPE_OF_LEGACY_SOURCE.get(option.source)
    if video_type is not None:
        option.source = SourceType.NATIVE
        option.filetypes = types.combine_filetype_filters(
            option.filetypes, {video_type}
        )
        option.named_video_type = video_type
    option.filetypes = types.combine_filetype_filters(
        option.filetypes, {types.FileType.VIDEO}
    )
    return option


def can_geotag_videos(option: SourceOption) -> bool:
    """
    Whether process() can read positions for videos from the source: it has a
    video extractor, and its filetypes let videos through. process() fails a
    video that no source can read.

    Examples:
        >>> can_geotag_videos(SourceOption(SourceType.GPX))
        True
        >>> can_geotag_videos(SourceOption(SourceType.NMEA))
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
    # --filetypes, which the filetypes of every option are limited to already
    filetypes: set[types.FileType] | None = None,
) -> list[types.MetadataOrError]:
    if not options:
        raise ValueError("No geotag options provided")

    video_types = _video_types_asked_for(filetypes)

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

    # Videos let through to sources that cannot geotag videos (e.g. exif), with
    # those sources, to report if no other source geotags them or fails to
    unread_videos: dict[Path, list[SourceType]] = {}

    # Paths let through to any source
    handed_paths: set[Path] = set()

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
        handed_paths.update(image_videos, video_paths)

        if image_videos:
            image_geotag = _build_image_geotag(option)
            image_metadata_or_errors = (
                image_geotag.to_description(image_videos) if image_geotag else []
            )
        else:
            image_metadata_or_errors = []

        if video_paths:
            video_geotag = _build_video_geotag(option)
            if video_geotag is None:
                for path in video_paths:
                    unread_videos.setdefault(path, []).append(option.source)
            video_metadata_or_errors = (
                video_geotag.to_description(video_paths) if video_geotag else []
            )
            if option.named_video_type is not None:
                video_metadata_or_errors = [
                    _say_of_another_type(metadata, option.named_video_type)
                    for metadata in video_metadata_or_errors
                ]
        else:
            video_metadata_or_errors = []

        rescued: list[
            tuple[types.MetadataOrError, SourceOption, types.ErrorMetadata]
        ] = []

        for metadata in image_metadata_or_errors + video_metadata_or_errors:
            if video_types is not None and _is_of_other_type(
                metadata, option, video_types
            ):
                # Its type, known only once it is read, is not one asked for:
                # leave it out, as the files of other kinds
                LOG.debug(
                    "Skipping %s, which is not of the file types %s",
                    metadata.filename,
                    filetypes,
                )
                reprocessable_paths.remove(metadata.filename)
                pending_errors.pop(metadata.filename, None)
                gpx_rejections.pop(metadata.filename, None)
            elif isinstance(metadata, types.ErrorMetadata) and _is_reprocessable(
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

    unread_paths = [
        path
        for path in unread_videos
        if path in reprocessable_paths and path not in pending_errors
    ]

    # Files that no source was let through, as the filetypes of every source
    # leave them out (e.g. sources for images only, or a source for BlackVue
    # videos with --filetypes gopro), but those that --filetypes leaves out
    sourceless_images, sourceless_videos = _filter_images_and_videos(
        sorted(reprocessable_paths - handed_paths), filetypes
    )

    # Files that sources were let through, but that none of them described,
    # nor said why, which they should not do: so that every file given gets
    # one entry, but those that --filetypes leaves out
    described_paths = {metadata.filename for metadata in final_metadatas}
    unhandled_images, unhandled_videos = _filter_images_and_videos(
        sorted(
            (reprocessable_paths & handed_paths) - described_paths - set(unread_paths)
        ),
        filetypes,
    )

    if video_types is not None and (
        unread_paths or sourceless_videos or unhandled_videos
    ):
        # Limited to some types of video, a video that no source read may not
        # be of any of them. Those of other types are left out, as the videos
        # found to be of other types
        kept_paths = set(
            _videos_not_of_other_types(
                unread_paths + sourceless_videos + unhandled_videos,
                video_types,
                # The same for every option (see process_geotag_properties)
                num_processes=next(iter(options)).num_processes,
            )
        )
        unread_paths = [path for path in unread_paths if path in kept_paths]
        sourceless_videos = [path for path in sourceless_videos if path in kept_paths]
        unhandled_videos = [path for path in unhandled_videos if path in kept_paths]

    final_metadatas.extend(
        _describe_unread_video(path, unread_videos[path]) for path in unread_paths
    )
    final_metadatas.extend(
        _describe_sourceless_file(path, options, filetypes)
        for path in sourceless_images + sourceless_videos
    )
    final_metadatas.extend(
        _describe_unhandled_file(path, options)
        for path in unhandled_images + unhandled_videos
    )

    return final_metadatas


def _videos_not_of_other_types(
    video_paths: T.Sequence[Path],
    video_types: set[types.FileType],
    num_processes: int | None = None,
) -> list[Path]:
    """
    The videos of **video_paths** that are of the types **video_types**, or of
    a type that cannot be told: all but those in which the native reader, given
    those types, recognizes none of them, as process() tells while geotagging
    (see _is_of_other_type)
    """
    LOG.info(
        f"==> Reading the type of {len(video_paths)} videos that no source can geotag..."
    )
    native = SourceOption(
        SourceType.NATIVE, filetypes=video_types, num_processes=num_processes
    )
    video_geotag = geotag_videos_from_video.GeotagVideosFromVideo(
        filetypes=native.filetypes, num_processes=native.num_processes
    )
    other_types = {
        metadata.filename
        for metadata in video_geotag.to_description(video_paths)
        if _is_of_other_type(metadata, native, video_types)
    }
    return [path for path in video_paths if path not in other_types]


def _describe_sourceless_file(
    path: Path,
    options: T.Iterable[SourceOption],
    filetypes: set[types.FileType] | None,
) -> types.ErrorMetadata:
    """
    Describe a file that no source of **options** was let through, limited to
    --filetypes **filetypes**, rather than leave it out of the results as if it
    had not been there

    >>> video_only = SourceOption(SourceType.NATIVE, filetypes={types.FileType.VIDEO})
    >>> _describe_sourceless_file(Path("i.jpg"), [video_only], None).error
    MapillaryGeoTaggingError('No geotag source is given for this image: the geotag source native is limited to other file types')
    >>> # For BlackVue videos, limited to --filetypes gopro
    >>> blackvue_only = SourceOption(SourceType.NATIVE, filetypes=set())
    >>> _describe_sourceless_file(Path("v.mp4"), [blackvue_only], {types.FileType.GOPRO}).error
    MapillaryVideoGPSNotFoundError('--filetypes gopro leaves no geotag source for this video: the geotag source native is limited to other file types')
    >>> images_only = [
    ...     SourceOption(SourceType.NATIVE, filetypes={types.FileType.IMAGE}),
    ...     SourceOption(SourceType.EXIFTOOL_RUNTIME, filetypes={types.FileType.IMAGE}),
    ... ]
    >>> filetypes = {types.FileType.IMAGE, types.FileType.GOPRO}
    >>> _describe_sourceless_file(Path("v.mp4"), images_only, filetypes).error
    MapillaryVideoGPSNotFoundError('--filetypes gopro,image leaves no geotag source for this video: the geotag sources native, exiftool_runtime are limited to other file types')
    """
    kind = "image" if utils.is_image_file(path) else "video"
    if filetypes is None:
        no_source = f"No geotag source is given for this {kind}"
    else:
        asked_for = ",".join(sorted(filetype.value for filetype in filetypes))
        no_source = f"--filetypes {asked_for} leaves no geotag source for this {kind}"
    names = list(dict.fromkeys(option.source.value for option in options))
    sources = (
        f"the geotag sources {', '.join(names)} are"
        if len(names) > 1
        else f"the geotag source {names[0]} is"
    )
    message = f"{no_source}: {sources} limited to other file types"
    if kind == "image":
        return types.describe_error_metadata(
            exceptions.MapillaryGeoTaggingError(message),
            path,
            filetype=types.FileType.IMAGE,
        )
    return types.describe_error_metadata(
        exceptions.MapillaryVideoGPSNotFoundError(message),
        path,
        filetype=types.FileType.VIDEO,
    )


def _describe_unhandled_file(
    path: Path, options: T.Iterable[SourceOption]
) -> types.ErrorMetadata:
    """
    Describe a file that the sources of **options** were let through, but that
    none of them described, rather than leave it out of the results as if it
    had not been there

    >>> options = [SourceOption(SourceType.NATIVE), SourceOption(SourceType.EXIFTOOL_RUNTIME)]
    >>> _describe_unhandled_file(Path("i.jpg"), options).error
    MapillaryGeoTaggingError('The geotag sources native, exiftool_runtime gave no result for this image')
    >>> _describe_unhandled_file(Path("v.mp4"), options[:1]).error
    MapillaryVideoGPSNotFoundError('The geotag source native gave no result for this video')
    """
    names = list(dict.fromkeys(option.source.value for option in options))
    sources = (
        f"The geotag sources {', '.join(names)}"
        if len(names) > 1
        else f"The geotag source {names[0]}"
    )
    if utils.is_image_file(path):
        return types.describe_error_metadata(
            exceptions.MapillaryGeoTaggingError(
                f"{sources} gave no result for this image"
            ),
            path,
            filetype=types.FileType.IMAGE,
        )
    return types.describe_error_metadata(
        exceptions.MapillaryVideoGPSNotFoundError(
            f"{sources} gave no result for this video"
        ),
        path,
        filetype=types.FileType.VIDEO,
    )


def _say_of_another_type(
    metadata: types.VideoMetadataOrError, video_type: types.FileType
) -> types.VideoMetadataOrError:
    """
    Say that a video in which the native reader, limited to the videos of
    **video_type** by the name of the source, finds no GPS is of another
    type, rather than that it has no GPS. The error stays the one the native
    reader reports, which tells process() what to do with the video

    >>> not_found = types.describe_error_metadata(
    ...     exceptions.MapillaryVideoGPSNotFoundError("No GPS data found from the video"),
    ...     Path("v.mp4"),
    ...     filetype=types.FileType.VIDEO,
    ... )
    >>> said = _say_of_another_type(not_found, types.FileType.GOPRO)
    >>> type(said.error).__name__, str(said.error)
    ('MapillaryVideoGPSNotFoundError', 'Not a GoPro video: the geotag source gopro reads GoPro videos only')
    >>> noisy = types.describe_error_metadata(
    ...     exceptions.MapillaryGPSNoiseError("GPS is too noisy"),
    ...     Path("v.mp4"),
    ...     filetype=types.FileType.VIDEO,
    ... )
    >>> _say_of_another_type(noisy, types.FileType.GOPRO) is noisy
    True
    """
    if not (
        isinstance(metadata, types.ErrorMetadata)
        and type(metadata.error) is exceptions.MapillaryVideoGPSNotFoundError
    ):
        return metadata

    name = _VIDEO_TYPE_NAMES[video_type]
    return types.describe_error_metadata(
        exceptions.MapillaryVideoGPSNotFoundError(
            f"Not a {name} video: the geotag source {video_type.value} reads {name} videos only"
        ),
        metadata.filename,
        filetype=metadata.filetype,
    )


def _describe_unread_video(
    video_path: Path, sources: T.Sequence[SourceType]
) -> types.ErrorMetadata:
    """
    Describe a video that only sources that cannot geotag videos were given,
    rather than leave it out of the results as if it had not been there

    >>> _describe_unread_video(Path("v.mp4"), [SourceType.EXIF]).error
    MapillaryVideoGPSNotFoundError('The geotag source exif cannot geotag videos')
    >>> _describe_unread_video(Path("v.mp4"), [SourceType.EXIF, SourceType.GOPRO]).error
    MapillaryVideoGPSNotFoundError('The geotag sources exif, gopro cannot geotag videos')
    """
    names = ", ".join(dict.fromkeys(source.value for source in sources))
    plural = "s" if len(set(sources)) > 1 else ""
    return types.describe_error_metadata(
        exceptions.MapillaryVideoGPSNotFoundError(
            f"The geotag source{plural} {names} cannot geotag videos"
        ),
        video_path,
        filetype=types.FileType.VIDEO,
    )


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


def _video_types_asked_for(
    filetypes: set[types.FileType] | None,
) -> set[types.FileType] | None:
    """
    The types of video that --filetypes limits processing to, or None if it
    lets videos of every type through

    >>> _video_types_asked_for({types.FileType.IMAGE, types.FileType.GOPRO})
    {<FileType.GOPRO: 'gopro'>}
    >>> _video_types_asked_for({types.FileType.GOPRO, types.FileType.VIDEO}) is None
    True
    >>> _video_types_asked_for(None) is None
    True
    """
    if filetypes is None or types.FileType.VIDEO in filetypes:
        return None
    return filetypes & types.NATIVE_VIDEO_FILETYPES


def _is_of_other_type(
    metadata: types.MetadataOrError,
    option: SourceOption,
    video_types: set[types.FileType],
) -> bool:
    """
    Whether the source **option** found a video to be of none of the types
    **video_types** asked for, which _filter_images_and_videos() cannot tell by
    its name: it read the video as another type, or it is the native reader,
    which tries only the readers of the types it is given, and finds no GPS
    data only in a video that none of them recognizes. A generic video is of a
    type that is not known, and is kept.

    >>> gopro = {types.FileType.GOPRO}
    >>> video = types.VideoMetadata(Path("v.mp4"), types.FileType.VIDEO, points=[])
    >>> _is_of_other_type(video, SourceOption(SourceType.GPX), gopro)
    False
    >>> blackvue = types.VideoMetadata(Path("v.mp4"), types.FileType.BLACKVUE, points=[])
    >>> _is_of_other_type(blackvue, SourceOption(SourceType.EXIFTOOL_RUNTIME), gopro)
    True
    >>> not_found = types.describe_error_metadata(
    ...     exceptions.MapillaryVideoGPSNotFoundError("No GPS data found from the video"),
    ...     Path("v.mp4"),
    ...     filetype=types.FileType.VIDEO,
    ... )
    >>> _is_of_other_type(not_found, SourceOption(SourceType.NATIVE, filetypes=gopro), gopro)
    True

    Limited further by its own filetypes, a source found only that the video is
    of none of those, and leaves it to the next source:

    >>> _is_of_other_type(
    ...     not_found,
    ...     SourceOption(SourceType.NATIVE, filetypes=gopro),
    ...     {types.FileType.GOPRO, types.FileType.BLACKVUE},
    ... )
    False
    """
    if isinstance(metadata, types.VideoMetadata):
        return (
            metadata.filetype in types.NATIVE_VIDEO_FILETYPES
            and metadata.filetype not in video_types
        )

    if isinstance(metadata, types.ErrorMetadata):
        return (
            option.source is SourceType.NATIVE
            and isinstance(metadata.error, exceptions.MapillaryVideoGPSNotFoundError)
            and option.filetypes is not None
            and types.FileType.VIDEO not in option.filetypes
            and video_types <= option.filetypes
        )

    return False


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


def _exiftool_xml_source_path(option: SourceOption) -> SourcePathOption:
    """
    Where the exiftool_xml source finds the XML of an image or a video: at its
    source path or by its pattern, or by default, as the README documents, in
    the XML named after the file beside it

    >>> _exiftool_xml_source_path(SourceOption(SourceType.EXIFTOOL_XML))
    SourcePathOption(pattern='%g.xml', source_path=None)
    """
    if option.source_path is None:
        return SourcePathOption(pattern=_EXIFTOOL_XML_DEFAULT_PATTERN)
    return option.source_path


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
        return geotag_images_from_exiftool.GeotagImagesFromExifToolWithSamples(
            source_path=_exiftool_xml_source_path(option),
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
        >>> geotagger = _build_video_geotag(opt)
        >>> geotagger.__class__.__name__
        'GeotagVideosFromNMEA'

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
        # Only by its own pattern: the source path that --geotag_source_path, or
        # the video import path in video_process, gives every source is not one
        # for exiftool to read
        return geotag_videos_from_exiftool.GeotagVideosFromExifToolRunner(
            pattern=None if option.source_path is None else option.source_path.pattern,
            num_processes=option.num_processes,
        )

    elif option.source is SourceType.EXIFTOOL_XML:
        return geotag_videos_from_exiftool.GeotagVideosFromExifToolXML(
            source_path=_exiftool_xml_source_path(option),
        )

    elif option.source is SourceType.GPX:
        return geotag_videos_from_gpx.GeotagVideosFromGPX(
            source_path=option.source_path,
            num_processes=option.num_processes,
            video_sync=option.video_sync,
            interpolation=option.interpolation,
        )

    elif option.source is SourceType.NMEA:
        return geotag_videos_from_nmea.GeotagVideosFromNMEA(
            source_path=option.source_path,
            num_processes=option.num_processes,
            video_sync=option.video_sync,
            interpolation=option.interpolation,
        )

    elif option.source is SourceType.EXIF:
        # Legacy image-specific geotag types
        return None

    elif option.source in [SourceType.GOPRO, SourceType.BLACKVUE, SourceType.CAMM]:
        # Legacy image-specific geotag types
        return None

    else:
        raise ValueError(f"Invalid geotag source {option.source}")
