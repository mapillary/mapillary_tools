import itertools
import logging
import math
import os
import typing as T

from . import constants, exceptions, geo, types, utils

LOG = logging.getLogger(__name__)


PointLike = T.TypeVar("PointLike", bound=geo.Point)
PointSequence = T.List[PointLike]


def cut_sequence_by_time_or_distance(
    sequence: PointSequence,
    cutoff_distance: T.Optional[float] = None,
    cutoff_time: T.Optional[float] = None,
) -> T.List[PointSequence]:
    sequences: T.List[PointSequence] = []

    if sequence:
        sequences.append([sequence[0]])

    for prev, cur in geo.pairwise(sequence):
        # invariant: prev is processed

        # Cut by distance
        distance = geo.gps_distance(
            (prev.lat, prev.lon),
            (cur.lat, cur.lon),
        )
        if cutoff_distance is not None:
            if cutoff_distance <= distance:
                sequences.append([cur])
                continue

        # Cut by time
        time_diff = cur.time - prev.time
        assert 0 <= time_diff, "sequence must be sorted by capture times"
        if cutoff_time is not None:
            if cutoff_time <= time_diff:
                sequences.append([cur])
                continue

        sequences[-1].append(cur)
        # invariant: cur is processed

    return sequences


def duplication_check(
    sequence: PointSequence,
    max_duplicate_distance: float,
    max_duplicate_angle: float,
) -> T.Tuple[PointSequence, T.List[types.ErrorMetadata]]:
    dedups: PointSequence = []
    dups: T.List[types.ErrorMetadata] = []

    sequence_iter = iter(sequence)
    prev = next(sequence_iter)
    if prev is None:
        return dedups, dups
    dedups.append(prev)

    for cur in sequence_iter:
        # invariant: prev is processed
        distance = geo.gps_distance(
            (prev.lat, prev.lon),
            (cur.lat, cur.lon),
        )

        if prev.angle is not None and cur.angle is not None:
            angle_diff = geo.diff_bearing(prev.angle, cur.angle)
        else:
            angle_diff = None

        if distance <= max_duplicate_distance and (
            angle_diff is None or angle_diff <= max_duplicate_angle
        ):
            msg = f"Duplicate of its previous image in terms of distance <= {max_duplicate_distance} and angle <= {max_duplicate_angle}"
            dups.append(
                types.describe_error_metadata(
                    exceptions.MapillaryDuplicationError(
                        msg,
                        types.as_desc(cur),
                        distance=distance,
                        angle_diff=angle_diff,
                    ),
                    cur.filename,
                    filetype=types.FileType.IMAGE,
                ),
            )
            # prev does not change
        else:
            dedups.append(cur)
            prev = cur
        # invariant: cur is processed

    return dedups, dups


def cut_sequence(
    sequence: T.List[types.ImageMetadata],
    max_images: int,
    max_sequence_filesize: int,
    max_sequence_pixels: int,
) -> T.List[T.List[types.ImageMetadata]]:
    """
    Cut a sequence into multiple sequences by max_images or max filesize
    """
    sequences: T.List[T.List[types.ImageMetadata]] = []
    last_sequence_file_size = 0
    last_sequence_pixels = 0

    for image in sequence:
        # decent default values if width/height not available
        width = 1024 if image.width is None else image.width
        height = 1024 if image.height is None else image.height

        filesize = os.path.getsize(image.filename)

        if len(sequences) == 0:
            start_new_sequence = True
        else:
            if sequences[-1]:
                if max_images < len(sequences[-1]):
                    LOG.debug(
                        "Cut the sequence because the current sequence (%s) reaches the max number of images (%s)",
                        len(sequences[-1]),
                        max_images,
                    )
                    start_new_sequence = True
                elif max_sequence_filesize < last_sequence_file_size + filesize:
                    LOG.debug(
                        "Cut the sequence because the current sequence (%s) reaches the max filesize (%s)",
                        last_sequence_file_size + filesize,
                        max_sequence_filesize,
                    )
                    start_new_sequence = True
                elif max_sequence_pixels < last_sequence_pixels + width * height:
                    LOG.debug(
                        "Cut the sequence because the current sequence (%s) reaches the max pixels (%s)",
                        last_sequence_pixels + width * height,
                        max_sequence_pixels,
                    )
                    start_new_sequence = True
                else:
                    start_new_sequence = False
            else:
                start_new_sequence = False

        if start_new_sequence:
            sequences.append([])
            last_sequence_file_size = 0
            last_sequence_pixels = 0

        sequences[-1].append(image)
        last_sequence_file_size += filesize
        last_sequence_pixels += width * height

    assert sum(len(s) for s in sequences) == len(sequence)

    return sequences


def _group_sort_images_by_folder(
    image_metadatas: T.List[types.ImageMetadata],
) -> T.List[T.List[types.ImageMetadata]]:
    # group images by parent directory
    sequences_by_group_key: T.Dict[T.Tuple, T.List[types.ImageMetadata]] = {}
    for image_metadata in image_metadatas:
        filename = image_metadata.filename.resolve()
        # Make sure a sequence comes from the same folder and the same camera
        group_key = (
            str(filename.parent),
            image_metadata.MAPDeviceMake,
            image_metadata.MAPDeviceModel,
            image_metadata.width,
            image_metadata.height,
        )
        sequences_by_group_key.setdefault(group_key, []).append(image_metadata)

    sequences = list(sequences_by_group_key.values())
    for sequence in sequences:
        sequence.sort(
            key=lambda metadata: metadata.sort_key(),
        )

    return sequences


def _interpolate_subsecs_for_sorting(sequence: PointSequence) -> None:
    """
    Update the timestamps make sure they are unique and sorted
    in the same order by interpolating subseconds
    Examples:
    - Input: 1, 1, 1, 1, 1, 2
    - Output: 1, 1.2, 1.4, 1.6, 1.8, 2
    """

    gidx = 0
    for _, g in itertools.groupby(sequence, key=lambda point: int(point.time * 1e3)):
        # invariant gidx is the idx of g[0] in sequence
        group = list(g)
        if len(group) <= 1:
            gidx += len(group)
            continue

        t = sequence[gidx].time
        nt = min(
            (
                sequence[gidx + len(group)].time
                if gidx + len(group) < len(sequence)
                else math.floor(t + 1.0)
            ),
            math.floor(t + 1.0),
        )
        assert t <= nt, f"expect sorted but got {t} > {nt}"
        interval = (nt - t) / len(group)
        for idx, point in enumerate(group):
            point.time = group[0].time + idx * interval
        gidx = gidx + len(group)

    for cur, nxt in geo.pairwise(sequence):
        assert cur.time <= nxt.time, (
            f"sequence must be sorted but got {cur.time} > {nxt.time}"
        )


def _parse_filesize_in_bytes(filesize_str: str) -> int:
    filesize_str = filesize_str.strip().upper()

    try:
        if filesize_str.endswith("B"):
            return int(filesize_str[:-1])
        elif filesize_str.endswith("K"):
            return int(filesize_str[:-1]) * 1024
        elif filesize_str.endswith("M"):
            return int(filesize_str[:-1]) * 1024 * 1024
        elif filesize_str.endswith("G"):
            return int(filesize_str[:-1]) * 1024 * 1024 * 1024
        else:
            return int(filesize_str)
    except ValueError:
        raise exceptions.MapillaryBadParameterError(
            f"Expect valid file size that ends with B, K, M, or G, but got {filesize_str}"
        )


def _parse_pixels(pixels_str: str) -> int:
    pixels_str = pixels_str.strip().upper()

    try:
        if pixels_str.endswith("K"):
            return int(pixels_str[:-1]) * 1000
        elif pixels_str.endswith("M"):
            return int(pixels_str[:-1]) * 1000 * 1000
        elif pixels_str.endswith("G"):
            return int(pixels_str[:-1]) * 1000 * 1000 * 1000
        else:
            return int(pixels_str)
    except ValueError:
        raise exceptions.MapillaryBadParameterError(
            f"Expect valid number of pixels that ends with K, M, or G, but got {pixels_str}"
        )


def _avg_speed(sequence: T.Sequence[PointLike]) -> float:
    total_distance = 0.0
    for cur, nxt in geo.pairwise(sequence):
        total_distance += geo.gps_distance(
            (cur.lat, cur.lon),
            (nxt.lat, nxt.lon),
        )

    if sequence:
        time_diff = sequence[-1].time - sequence[0].time
    else:
        time_diff = 0.0

    if time_diff == 0.0:
        return float("inf")

    return total_distance / time_diff


def _check_video_limits(
    video_metadatas: T.Sequence[types.VideoMetadata],
    max_sequence_filesize_in_bytes: int,
    max_avg_speed: float,
) -> T.Tuple[T.List[types.VideoMetadata], T.List[types.ErrorMetadata]]:
    error_metadatas: T.List[types.ErrorMetadata] = []
    output_video_metadatas: T.List[types.VideoMetadata] = []

    for video_metadata in video_metadatas:
        if video_metadata.filesize is None:
            filesize = utils.get_file_size(video_metadata.filename)
        else:
            filesize = video_metadata.filesize

        if filesize > max_sequence_filesize_in_bytes:
            error_metadatas.append(
                types.describe_error_metadata(
                    exc=exceptions.MapillaryFileTooLargeError(
                        f"Video file size exceeds the maximum allowed file size ({max_sequence_filesize_in_bytes} bytes)",
                    ),
                    filename=video_metadata.filename,
                    filetype=video_metadata.filetype,
                )
            )
        elif any(p.lat == 0 and p.lon == 0 for p in video_metadata.points):
            error_metadatas.append(
                types.describe_error_metadata(
                    exc=exceptions.MapillaryNullIslandError(
                        "Found GPS coordinates in Null Island (0, 0)",
                    ),
                    filename=video_metadata.filename,
                    filetype=video_metadata.filetype,
                )
            )
        elif (
            len(video_metadata.points) >= 2
            and _avg_speed(video_metadata.points) > max_avg_speed
        ):
            error_metadatas.append(
                types.describe_error_metadata(
                    exc=exceptions.MapillaryCaptureSpeedTooFastError(
                        f"Capture speed is too fast (exceeds {round(max_avg_speed, 3)} m/s)",
                    ),
                    filename=video_metadata.filename,
                    filetype=video_metadata.filetype,
                )
            )
        else:
            output_video_metadatas.append(video_metadata)

    return output_video_metadatas, error_metadatas


def _check_sequence_limits(
    sequences: T.Sequence[PointSequence],
    max_sequence_filesize_in_bytes: int,
    max_avg_speed: float,
) -> T.Tuple[T.List[PointSequence], T.List[types.ErrorMetadata]]:
    error_metadatas: T.List[types.ErrorMetadata] = []
    output_sequences: T.List[PointSequence] = []

    for sequence in sequences:
        filesize = 0
        for image in sequence:
            if image.filesize is None:
                filesize += utils.get_file_size(image.filename)
            else:
                filesize += image.filesize

        if filesize > max_sequence_filesize_in_bytes:
            for image in sequence:
                error_metadatas.append(
                    types.describe_error_metadata(
                        exc=exceptions.MapillaryFileTooLargeError(
                            f"Sequence file size exceeds the maximum allowed file size ({max_sequence_filesize_in_bytes} bytes)",
                        ),
                        filename=image.filename,
                        filetype=types.FileType.IMAGE,
                    )
                )
        elif any(image.lat == 0 and image.lon == 0 for image in sequence):
            for image in sequence:
                error_metadatas.append(
                    types.describe_error_metadata(
                        exc=exceptions.MapillaryNullIslandError(
                            "Found GPS coordinates in Null Island (0, 0)",
                        ),
                        filename=image.filename,
                        filetype=types.FileType.IMAGE,
                    )
                )
        elif len(sequence) >= 2 and _avg_speed(sequence) > max_avg_speed:
            for image in sequence:
                error_metadatas.append(
                    types.describe_error_metadata(
                        exc=exceptions.MapillaryCaptureSpeedTooFastError(
                            f"Capture speed is too fast (exceeds {round(max_avg_speed, 3)} m/s)",
                        ),
                        filename=image.filename,
                        filetype=types.FileType.IMAGE,
                    )
                )
        else:
            output_sequences.append(sequence)

    return output_sequences, error_metadatas


def process_sequence_properties(
    metadatas: T.Sequence[types.MetadataOrError],
    cutoff_distance: float = constants.CUTOFF_DISTANCE,
    cutoff_time: float = constants.CUTOFF_TIME,
    interpolate_directions: bool = False,
    duplicate_distance: float = constants.DUPLICATE_DISTANCE,
    duplicate_angle: float = constants.DUPLICATE_ANGLE,
    max_avg_speed: float = constants.MAX_AVG_SPEED,
) -> T.List[types.MetadataOrError]:
    max_sequence_filesize_in_bytes = _parse_filesize_in_bytes(
        constants.MAX_SEQUENCE_FILESIZE
    )
    max_sequence_pixels = _parse_pixels(constants.MAX_SEQUENCE_PIXELS)

    error_metadatas: T.List[types.ErrorMetadata] = []
    image_metadatas: T.List[types.ImageMetadata] = []
    video_metadatas: T.List[types.VideoMetadata] = []

    for metadata in metadatas:
        if isinstance(metadata, types.ErrorMetadata):
            error_metadatas.append(metadata)
        elif isinstance(metadata, types.ImageMetadata):
            image_metadatas.append(metadata)
        elif isinstance(metadata, types.VideoMetadata):
            video_metadatas.append(metadata)
        else:
            raise RuntimeError(f"invalid metadata type: {metadata}")

    # Check limits for videos
    video_metadatas, video_error_metadatas = _check_video_limits(
        video_metadatas,
        max_sequence_filesize_in_bytes=max_sequence_filesize_in_bytes,
        max_avg_speed=max_avg_speed,
    )
    error_metadatas.extend(video_error_metadatas)

    input_sequences: T.List[PointSequence]
    output_sequences: T.List[PointSequence]

    input_sequences = _group_sort_images_by_folder(image_metadatas)
    if input_sequences:
        assert isinstance(input_sequences[0], list)

    # make sure they are sorted
    for sequence in input_sequences:
        for cur, nxt in geo.pairwise(sequence):
            assert cur.time <= nxt.time, "sequence must be sorted"

    for sequence in input_sequences:
        _interpolate_subsecs_for_sorting(sequence)

    # Cut sequences by time or distance
    # NOTE: do not cut by distance here because it affects the speed limit check
    output_sequences = []
    for sequence in input_sequences:
        output_sequences.extend(
            cut_sequence_by_time_or_distance(sequence, cutoff_time=cutoff_time)
        )
    assert len(image_metadatas) == sum(len(s) for s in output_sequences)

    # Duplication check
    input_sequences = output_sequences
    if input_sequences:
        assert isinstance(input_sequences[0], list)
    output_sequences = []
    for sequence in input_sequences:
        output_sequence, errors = duplication_check(
            sequence,
            max_duplicate_distance=duplicate_distance,
            max_duplicate_angle=duplicate_angle,
        )
        assert len(sequence) == len(output_sequence) + len(errors)
        output_sequences.append(output_sequence)
        error_metadatas.extend(errors)

    # Interpolate angles
    input_sequences = output_sequences
    if input_sequences:
        assert isinstance(input_sequences[0], list)
    for sequence in input_sequences:
        if interpolate_directions:
            for image in sequence:
                image.angle = None
        geo.interpolate_directions_if_none(sequence)
    output_sequences = input_sequences

    # Cut sequences by max number of images, max filesize, and max pixels
    input_sequences = output_sequences
    if input_sequences:
        assert isinstance(input_sequences[0], list)
    output_sequences = []
    for sequence in input_sequences:
        output_sequences.extend(
            cut_sequence(
                sequence,
                constants.MAX_SEQUENCE_LENGTH,
                max_sequence_filesize_in_bytes,
                max_sequence_pixels,
            )
        )

    # Check limits for sequences
    output_sequences, errors = _check_sequence_limits(
        input_sequences, max_sequence_filesize_in_bytes, max_avg_speed
    )
    error_metadatas.extend(errors)
    if output_sequences:
        assert isinstance(output_sequences[0], list)

    # Assign sequence UUIDs
    sequence_idx = 0
    image_metadatas = []
    input_sequences = output_sequences
    for sequence in input_sequences:
        # assign sequence UUIDs
        for image in sequence:
            # using incremental id as shorter "uuid", so we can save some space for the desc file
            image.MAPSequenceUUID = str(sequence_idx)
            image_metadatas.append(image)
        sequence_idx += 1
    output_sequences = input_sequences

    results = error_metadatas + image_metadatas + video_metadatas

    assert len(metadatas) == len(results), (
        f"expected {len(metadatas)} results but got {len(results)}"
    )
    assert sequence_idx == len(
        set(metadata.MAPSequenceUUID for metadata in image_metadatas)
    )

    return results
