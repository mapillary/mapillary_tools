from __future__ import annotations

import itertools
import logging
import math
import os
import typing as T

from . import constants, exceptions, geo, types, utils
from .serializer.description import DescriptionJSONSerializer

LOG = logging.getLogger(__name__)


S = T.TypeVar("S")
R = T.TypeVar("R")
PointSequence = T.List[geo.PointLike]


def split_sequence_by(
    sequence: T.Iterable[S], reduce: T.Callable[[R, S], tuple[R, bool]], initial: R
) -> list[list[S]]:
    """
    Split a sequence into multiple subsequences based on a reduction function.

    The function processes each element through a reduce function that maintains
    state and determines whether to split the sequence at that point. When a split
    is triggered, a new subsequence starts with the current element.

    Args:
        sequence: An iterable of elements to split
        reduce: A function that takes (accumulated_state, current_element) and
               returns (new_state, should_split). If should_split is True,
               a new subsequence starts with the current element.
        initial: The initial state value passed to the reduce function

    Returns:
        A list of subsequences, where each subsequence is a list of elements

    Examples:
        >>> # Split on even numbers
        >>> def split_on_even(count, x):
        ...     return count + 1, x % 2 == 0
        >>> split_sequence_by([1, 3, 2, 4, 5, 6, 7], split_on_even, 0)
        [[1, 3], [2], [4, 5], [6, 7]]

        >>> # Split when sum exceeds threshold
        >>> def split_when_sum_exceeds_5(total, x):
        ...     total += x
        ...     return (x, True) if total > 5 else (total, False)
        >>> split_sequence_by([1, 2, 3, 4, 1, 2], split_when_sum_exceeds_5, 0)
        [[1, 2], [3], [4, 1], [2]]

        >>> # Split on specific values
        >>> def split_on_zero(_, x):
        ...     return None, x == 0
        >>> split_sequence_by([1, 2, 0, 3, 4, 0, 5], split_on_zero, None)
        [[1, 2], [0, 3, 4], [0, 5]]

        >>> # Empty sequence
        >>> split_sequence_by([], lambda s, x: (s, False), 0)
        []

        >>> # Single element
        >>> split_sequence_by([42], lambda s, x: (s, False), 0)
        [[42]]
    """

    output_sequences: list[list[S]] = []

    value = initial

    for element in sequence:
        value, should = reduce(value, element)

        if should:
            output_sequences.append([element])
        else:
            if output_sequences:
                output_sequences[-1].append(element)
            else:
                output_sequences.append([element])

    return output_sequences


def duplication_check(
    sequence: PointSequence, max_duplicate_distance: float, max_duplicate_angle: float
) -> tuple[PointSequence, list[types.ErrorMetadata]]:
    dedups: PointSequence = []
    dups: list[types.ErrorMetadata] = []

    it = iter(sequence)
    prev = next(it)
    if prev is None:
        return dedups, dups

    dedups.append(prev)

    for cur in it:
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
            dup = types.describe_error_metadata(
                exceptions.MapillaryDuplicationError(
                    msg,
                    DescriptionJSONSerializer.as_desc(cur),
                    distance=distance,
                    angle_diff=angle_diff,
                ),
                cur.filename,
                filetype=types.FileType.IMAGE,
            )
            dups.append(dup)
            # prev does not change
        else:
            dedups.append(cur)
            prev = cur
        # invariant: cur is processed

    return dedups, dups


def _group_by(
    image_metadatas: T.Iterable[types.ImageMetadata],
    group_key_func=T.Callable[[types.ImageMetadata], T.Hashable],
) -> dict[T.Hashable, list[types.ImageMetadata]]:
    grouped: dict[T.Hashable, list[types.ImageMetadata]] = {}
    for metadata in image_metadatas:
        grouped.setdefault(group_key_func(metadata), []).append(metadata)
    return grouped


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


def _avg_speed(sequence: T.Sequence[geo.PointLike]) -> float:
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


def _is_video_stationary(
    sequence: T.Sequence[geo.PointLike], max_radius_in_meters: float
) -> bool:
    if not sequence:
        return 0.0 <= max_radius_in_meters

    start = (sequence[0].lat, sequence[0].lon)
    for p in sequence:
        distance = geo.gps_distance(start, (p.lat, p.lon))
        if distance > max_radius_in_meters:
            return False

    return True


def _check_video_limits(
    video_metadatas: T.Iterable[types.VideoMetadata],
    max_sequence_filesize_in_bytes: int,
    max_avg_speed: float,
    max_radius_for_stationary_check: float,
) -> tuple[list[types.VideoMetadata], list[types.ErrorMetadata]]:
    output_video_metadatas: list[types.VideoMetadata] = []
    error_metadatas: list[types.ErrorMetadata] = []

    for video_metadata in video_metadatas:
        try:
            is_stationary = _is_video_stationary(
                video_metadata.points,
                max_radius_in_meters=max_radius_for_stationary_check,
            )
            if is_stationary:
                raise exceptions.MapillaryStationaryVideoError("Stationary video")

            video_filesize = (
                utils.get_file_size(video_metadata.filename)
                if video_metadata.filesize is None
                else video_metadata.filesize
            )
            if video_filesize > max_sequence_filesize_in_bytes:
                raise exceptions.MapillaryFileTooLargeError(
                    f"Video file size exceeds the maximum allowed file size ({max_sequence_filesize_in_bytes} bytes)",
                )

            contains_null_island = any(
                p.lat == 0 and p.lon == 0 for p in video_metadata.points
            )
            if contains_null_island:
                raise exceptions.MapillaryNullIslandError(
                    "Found GPS coordinates in Null Island (0, 0)",
                )

            too_fast = (
                len(video_metadata.points) >= 2
                and _avg_speed(video_metadata.points) > max_avg_speed
            )
            if too_fast:
                raise exceptions.MapillaryCaptureSpeedTooFastError(
                    f"Capture speed too fast (exceeds {round(max_avg_speed, 3)} m/s)",
                )
        except exceptions.MapillaryDescriptionError as ex:
            error_metadatas.append(
                types.describe_error_metadata(
                    exc=ex,
                    filename=video_metadata.filename,
                    filetype=video_metadata.filetype,
                )
            )
        else:
            output_video_metadatas.append(video_metadata)

    if error_metadatas:
        LOG.info(
            "Found %s videos and %s errors after video limit checks",
            len(output_video_metadatas),
            len(error_metadatas),
        )

    return output_video_metadatas, error_metadatas


def _check_sequences_by_limits(
    input_sequences: T.Sequence[PointSequence],
    max_sequence_filesize_in_bytes: int,
    max_avg_speed: float,
) -> tuple[list[PointSequence], list[types.ErrorMetadata]]:
    output_sequences: list[PointSequence] = []
    output_errors: list[types.ErrorMetadata] = []

    for sequence in input_sequences:
        sequence_filesize = sum(
            utils.get_file_size(image.filename)
            if image.filesize is None
            else image.filesize
            for image in sequence
        )

        try:
            if sequence_filesize > max_sequence_filesize_in_bytes:
                raise exceptions.MapillaryFileTooLargeError(
                    f"Sequence file size exceeds the maximum allowed file size ({max_sequence_filesize_in_bytes} bytes)",
                )

            contains_null_island = any(
                image.lat == 0 and image.lon == 0 for image in sequence
            )
            if contains_null_island:
                raise exceptions.MapillaryNullIslandError(
                    "Found GPS coordinates in Null Island (0, 0)",
                )

            too_fast = len(sequence) >= 2 and _avg_speed(sequence) > max_avg_speed
            if too_fast:
                raise exceptions.MapillaryCaptureSpeedTooFastError(
                    f"Capture speed too fast (exceeds {round(max_avg_speed, 3)} m/s)",
                )
        except exceptions.MapillaryDescriptionError as ex:
            for image in sequence:
                output_errors.append(
                    types.describe_error_metadata(
                        exc=ex,
                        filename=image.filename,
                        filetype=types.FileType.IMAGE,
                    )
                )

        else:
            output_sequences.append(sequence)

    assert sum(len(s) for s in output_sequences) + len(output_errors) == sum(
        len(s) for s in input_sequences
    )

    if output_errors:
        LOG.info(
            "Found %s sequences and %s errors after sequence limit checks",
            len(output_sequences),
            len(output_errors),
        )

    return output_sequences, output_errors


def _group_by_folder_and_camera(
    image_metadatas: list[types.ImageMetadata],
) -> list[list[types.ImageMetadata]]:
    grouped = _group_by(
        image_metadatas,
        lambda metadata: (
            str(metadata.filename.parent),
            metadata.MAPDeviceMake,
            metadata.MAPDeviceModel,
            metadata.width,
            metadata.height,
        ),
    )
    for key in grouped:
        LOG.debug("Group sequences by %s: %s images", key, len(grouped[key]))
    output_sequences = list(grouped.values())

    LOG.info(
        "Found %s sequences from different folders and cameras",
        len(output_sequences),
    )

    return output_sequences


def _check_sequences_duplication(
    input_sequences: T.Sequence[PointSequence],
    duplicate_distance: float,
    duplicate_angle: float,
) -> tuple[list[PointSequence], list[types.ErrorMetadata]]:
    output_sequences: list[PointSequence] = []
    output_errors: list[types.ErrorMetadata] = []

    for sequence in input_sequences:
        output_sequence, errors = duplication_check(
            sequence,
            max_duplicate_distance=duplicate_distance,
            max_duplicate_angle=duplicate_angle,
        )
        assert len(sequence) == len(output_sequence) + len(errors)
        output_sequences.append(output_sequence)
        output_errors.extend(errors)

    assert sum(len(s) for s in output_sequences) + len(output_errors) == sum(
        len(s) for s in input_sequences
    )

    if output_errors:
        LOG.info(
            "Found %s sequences and %s errors after duplication check",
            len(output_sequences),
            len(output_errors),
        )

    return output_sequences, output_errors


class SplitState(T.TypedDict, total=False):
    sequence_images: int
    sequence_file_size: int
    sequence_pixels: int
    split: bool
    image: types.ImageMetadata


def _split_sequences_by_limits(
    input_sequences: T.Sequence[PointSequence],
    max_sequence_filesize_in_bytes: float | None = None,
    max_sequence_pixels: float | None = None,
    max_sequence_images: int | None = None,
    cutoff_time: float | None = None,
    cutoff_distance: float | None = None,
) -> list[PointSequence]:
    def _should_split_by_max_sequence_images(
        state: SplitState, _: types.ImageMetadata
    ) -> tuple[SplitState, bool]:
        if max_sequence_images is None:
            return state, False

        split = state.get("split", False)

        if split:
            new_sequence_images = 1
        else:
            new_sequence_images = state.get("sequence_images", 0) + 1
            split = max_sequence_images < new_sequence_images
            if split:
                LOG.debug(
                    f"Split because {new_sequence_images=} < {max_sequence_images=}"
                )

        state["sequence_images"] = new_sequence_images

        return state, split

    def _should_split_by_cutoff_time(
        state: SplitState, image: types.ImageMetadata
    ) -> tuple[SplitState, bool]:
        if cutoff_time is None:
            return state, False

        split = state.get("split", False)

        if split:
            pass
        else:
            last_image = state.get("image")
            if last_image is not None:
                diff = image.time - last_image.time
                split = cutoff_time < diff
                if split:
                    LOG.debug(f"Split because {cutoff_time=}  < {diff=}")

        state["image"] = image

        return state, split

    def _should_split_by_cutoff_distance(
        state: SplitState, image: types.ImageMetadata
    ) -> tuple[SplitState, bool]:
        if cutoff_distance is None:
            return state, False

        split = state.get("split", False)

        if split:
            pass
        else:
            last_image = state.get("image")
            if last_image is not None:
                diff = geo.gps_distance(
                    (last_image.lat, last_image.lon), (image.lat, image.lon)
                )
                split = cutoff_distance < diff
                if split:
                    LOG.debug(f"Split because {cutoff_distance=} < {diff=}")

        state["image"] = image

        return state, split

    def _should_split_by_max_sequence_filesize(
        state: SplitState, image: types.ImageMetadata
    ) -> tuple[SplitState, bool]:
        if max_sequence_filesize_in_bytes is None:
            return state, False

        split = state.get("split", False)

        if image.filesize is None:
            filesize = os.path.getsize(image.filename)
        else:
            filesize = image.filesize

        if split:
            new_sequence_file_size = filesize
        else:
            sequence_file_size = state.get("sequence_file_size", 0)
            new_sequence_file_size = sequence_file_size + filesize
            split = max_sequence_filesize_in_bytes < new_sequence_file_size
            if split:
                LOG.debug(
                    f"Split because {max_sequence_filesize_in_bytes=} < {new_sequence_file_size=}"
                )

        state["sequence_file_size"] = new_sequence_file_size

        return state, split

    def _should_split_by_max_sequence_pixels(
        state: SplitState, image: types.ImageMetadata
    ) -> tuple[SplitState, bool]:
        if max_sequence_pixels is None:
            return state, False

        split = state.get("split", False)

        # Decent default values if width/height not available
        width = 1024 if image.width is None else image.width
        height = 1024 if image.height is None else image.height
        pixels = width * height

        if split:
            new_sequence_pixels = pixels
        else:
            sequence_pixels = state.get("sequence_pixels", 0)
            new_sequence_pixels = sequence_pixels + pixels
            split = max_sequence_pixels < new_sequence_pixels
            if split:
                LOG.debug(
                    f"Split because {max_sequence_pixels=} < {new_sequence_pixels=}"
                )

        state["sequence_pixels"] = new_sequence_pixels

        return state, split

    def _should_split_agg(
        state: SplitState, image: types.ImageMetadata
    ) -> tuple[SplitState, bool]:
        split = False

        for should_split in [
            _should_split_by_max_sequence_images,
            _should_split_by_cutoff_time,
            _should_split_by_cutoff_distance,
            _should_split_by_max_sequence_filesize,
            _should_split_by_max_sequence_pixels,
        ]:
            state, split = should_split(state, image)
            if split:
                state["split"] = True

        return state, split

    output_sequences = []
    for sequence in input_sequences:
        output_sequences.extend(
            split_sequence_by(
                sequence, _should_split_agg, initial=T.cast(SplitState, {})
            )
        )

    assert sum(len(s) for s in output_sequences) == sum(len(s) for s in input_sequences)

    if len(input_sequences) != len(output_sequences):
        LOG.info(
            f"Split {len(input_sequences)} into {len(output_sequences)} sequences by limits"
        )

    return output_sequences


def process_sequence_properties(
    metadatas: T.Sequence[types.MetadataOrError],
    cutoff_distance: float = constants.CUTOFF_DISTANCE,
    cutoff_time: float = constants.CUTOFF_TIME,
    interpolate_directions: bool = False,
    duplicate_distance: float = constants.DUPLICATE_DISTANCE,
    duplicate_angle: float = constants.DUPLICATE_ANGLE,
    max_avg_speed: float = constants.MAX_AVG_SPEED,
) -> list[types.MetadataOrError]:
    max_sequence_filesize_in_bytes = _parse_filesize_in_bytes(
        constants.MAX_SEQUENCE_FILESIZE
    )
    max_sequence_pixels = _parse_pixels(constants.MAX_SEQUENCE_PIXELS)

    error_metadatas: list[types.ErrorMetadata] = []
    image_metadatas: list[types.ImageMetadata] = []
    video_metadatas: list[types.VideoMetadata] = []

    for metadata in metadatas:
        if isinstance(metadata, types.ErrorMetadata):
            error_metadatas.append(metadata)
        elif isinstance(metadata, types.ImageMetadata):
            image_metadatas.append(metadata)
        elif isinstance(metadata, types.VideoMetadata):
            video_metadatas.append(metadata)
        else:
            raise RuntimeError(f"invalid metadata type: {metadata}")

    if video_metadatas:
        # Check limits for videos
        video_metadatas, video_error_metadatas = _check_video_limits(
            video_metadatas,
            max_sequence_filesize_in_bytes=max_sequence_filesize_in_bytes,
            max_avg_speed=max_avg_speed,
            max_radius_for_stationary_check=10.0,
        )
        error_metadatas.extend(video_error_metadatas)

    if image_metadatas:
        sequences: list[PointSequence]

        # Group by folder and camera
        sequences = _group_by_folder_and_camera(image_metadatas)

        # Make sure each sequence is sorted (in-place update)
        for sequence in sequences:
            sequence.sort(
                key=lambda metadata: metadata.sort_key(),
            )

        # Interpolate subseconds for same timestamps (in-place update)
        for sequence in sequences:
            _interpolate_subsecs_for_sorting(sequence)

        # Split sequences by max number of images, max filesize, max pixels, and cutoff time
        # NOTE: Do not split by distance here because it affects the speed limit check
        sequences = _split_sequences_by_limits(
            sequences,
            max_sequence_filesize_in_bytes=max_sequence_filesize_in_bytes,
            max_sequence_pixels=max_sequence_pixels,
            max_sequence_images=constants.MAX_SEQUENCE_LENGTH,
            cutoff_time=cutoff_time,
        )

        # Duplication check
        sequences, errors = _check_sequences_duplication(
            sequences,
            duplicate_distance=duplicate_distance,
            duplicate_angle=duplicate_angle,
        )
        error_metadatas.extend(errors)

        # Interpolate angles (in-place update)
        for sequence in sequences:
            if interpolate_directions:
                for image in sequence:
                    image.angle = None
            geo.interpolate_directions_if_none(sequence)

        # Check limits for sequences
        sequences, errors = _check_sequences_by_limits(
            sequences,
            max_sequence_filesize_in_bytes=max_sequence_filesize_in_bytes,
            max_avg_speed=max_avg_speed,
        )
        error_metadatas.extend(errors)

        # Split sequences by cutoff distance
        # NOTE: The speed limit check probably rejects most of anomalies
        sequences = _split_sequences_by_limits(
            sequences, cutoff_distance=cutoff_distance
        )

        # Assign sequence UUIDs (in-place update)
        sequence_idx = 0
        for sequence in sequences:
            for image in sequence:
                # using incremental id as shorter "uuid", so we can save some space for the desc file
                image.MAPSequenceUUID = str(sequence_idx)
            sequence_idx += 1

        image_metadatas = []
        for sequence in sequences:
            image_metadatas.extend(sequence)

        assert sequence_idx == len(
            set(metadata.MAPSequenceUUID for metadata in image_metadatas)
        )

    results = error_metadatas + image_metadatas + video_metadatas

    assert len(metadatas) == len(results), (
        f"expected {len(metadatas)} results but got {len(results)}"
    )

    return results
