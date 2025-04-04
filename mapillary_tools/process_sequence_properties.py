from __future__ import annotations

import itertools
import logging
import math
import os
import typing as T

from . import constants, exceptions, geo, types, utils

LOG = logging.getLogger(__name__)


SeqItem = T.TypeVar("SeqItem")
PointSequence = T.List[geo.PointLike]


def split_sequence_by(
    sequence: T.Sequence[SeqItem],
    should_split: T.Callable[[SeqItem, SeqItem], bool],
) -> list[list[SeqItem]]:
    """
    Split a sequence into multiple sequences by should_split(prev, cur) => True
    """
    output_sequences: list[list[SeqItem]] = []

    seq = iter(sequence)

    prev = next(seq, None)
    if prev is None:
        return output_sequences

    output_sequences.append([prev])

    for cur in seq:
        # invariant: prev is processed
        if should_split(prev, cur):
            output_sequences.append([cur])
        else:
            output_sequences[-1].append(cur)
        prev = cur
        # invariant: cur is processed

    assert sum(len(s) for s in output_sequences) == len(sequence)

    return output_sequences


def split_sequence_by_agg(
    sequence: T.Sequence[SeqItem],
    should_split_with_sequence_state: T.Callable[[SeqItem, dict], bool],
) -> list[list[SeqItem]]:
    """
    Split a sequence by should_split_with_sequence_state(cur, sequence_state) => True
    """
    output_sequences: list[list[SeqItem]] = []
    sequence_state: dict = {}

    for cur in sequence:
        start_new_sequence = should_split_with_sequence_state(cur, sequence_state)

        if not output_sequences:
            output_sequences.append([])

        if start_new_sequence:
            # DO NOT reset the state because it contains the information of current item
            # sequence_state = {}
            if output_sequences[-1]:
                output_sequences.append([])

        output_sequences[-1].append(cur)

    assert sum(len(s) for s in output_sequences) == len(sequence)

    return output_sequences


def duplication_check(
    sequence: PointSequence,
    max_duplicate_distance: float,
    max_duplicate_angle: float,
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
                    types.as_desc(cur),
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


def _split_sequences_by_cutoff_time(
    input_sequences: T.Sequence[PointSequence], cutoff_time: float
) -> list[PointSequence]:
    def _should_split_by_cutoff_time(
        prev: types.ImageMetadata, cur: types.ImageMetadata
    ) -> bool:
        time_diff = cur.time - prev.time
        assert 0 <= time_diff, "sequence must be sorted by capture times"
        should = cutoff_time < time_diff
        if should:
            LOG.debug(
                "Split because the capture time gap %s seconds exceeds cutoff_time (%s seconds): %s: %s -> %s",
                round(time_diff, 2),
                round(cutoff_time, 2),
                prev.filename.parent,
                prev.filename.name,
                cur.filename.name,
            )
        return should

    output_sequences = []
    for sequence in input_sequences:
        output_sequences.extend(
            split_sequence_by(sequence, should_split=_should_split_by_cutoff_time)
        )

    assert sum(len(s) for s in output_sequences) == sum(len(s) for s in input_sequences)

    LOG.info(
        "Found %s sequences after split by cutoff_time %d seconds",
        len(output_sequences),
        cutoff_time,
    )

    return output_sequences


def _split_sequences_by_cutoff_distance(
    input_sequences: T.Sequence[PointSequence], cutoff_distance: float
) -> list[PointSequence]:
    def _should_split_by_cutoff_distance(
        prev: types.ImageMetadata, cur: types.ImageMetadata
    ) -> bool:
        distance = geo.gps_distance(
            (prev.lat, prev.lon),
            (cur.lat, cur.lon),
        )
        should = cutoff_distance < distance
        if should:
            LOG.debug(
                "Split because the distance gap %s meters exceeds cutoff_distance (%s meters): %s: %s -> %s",
                round(distance, 2),
                round(cutoff_distance, 2),
                prev.filename.parent,
                prev.filename.name,
                cur.filename.name,
            )
        return should

    output_sequences = []
    for sequence in input_sequences:
        output_sequences.extend(
            split_sequence_by(sequence, _should_split_by_cutoff_distance)
        )

    assert sum(len(s) for s in output_sequences) == sum(len(s) for s in input_sequences)

    LOG.info(
        "Found %s sequences after split by cutoff_distance %d meters",
        len(output_sequences),
        cutoff_distance,
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

    LOG.info(
        "Found %s sequences and %s errors after duplication check",
        len(output_sequences),
        len(output_errors),
    )

    return output_sequences, output_errors


def _split_sequences_by_limits(
    input_sequences: T.Sequence[PointSequence],
    max_sequence_filesize_in_bytes: float,
    max_sequence_pixels: float,
) -> list[PointSequence]:
    max_sequence_images = constants.MAX_SEQUENCE_LENGTH
    max_sequence_filesize = max_sequence_filesize_in_bytes

    def _should_split(image: types.ImageMetadata, sequence_state: dict) -> bool:
        last_sequence_images = sequence_state.get("last_sequence_images", 0)
        last_sequence_file_size = sequence_state.get("last_sequence_file_size", 0)
        last_sequence_pixels = sequence_state.get("last_sequence_pixels", 0)

        # decent default values if width/height not available
        width = 1024 if image.width is None else image.width
        height = 1024 if image.height is None else image.height
        pixels = width * height

        if image.filesize is None:
            filesize = os.path.getsize(image.filename)
        else:
            filesize = image.filesize

        new_sequence_images = last_sequence_images + 1
        new_sequence_file_size = last_sequence_file_size + filesize
        new_sequence_pixels = last_sequence_pixels + pixels

        if max_sequence_images < new_sequence_images:
            LOG.debug(
                "Split because the current sequence (%s) reaches the max number of images (%s)",
                new_sequence_images,
                max_sequence_images,
            )
            start_new_sequence = True
        elif max_sequence_filesize < new_sequence_file_size:
            LOG.debug(
                "Split because the current sequence (%s) reaches the max filesize (%s)",
                new_sequence_file_size,
                max_sequence_filesize,
            )
            start_new_sequence = True
        elif max_sequence_pixels < new_sequence_pixels:
            LOG.debug(
                "Split because the current sequence (%s) reaches the max pixels (%s)",
                new_sequence_pixels,
                max_sequence_pixels,
            )
            start_new_sequence = True
        else:
            start_new_sequence = False

        if not start_new_sequence:
            sequence_state["last_sequence_images"] = new_sequence_images
            sequence_state["last_sequence_file_size"] = new_sequence_file_size
            sequence_state["last_sequence_pixels"] = new_sequence_pixels
        else:
            sequence_state["last_sequence_images"] = 1
            sequence_state["last_sequence_file_size"] = filesize
            sequence_state["last_sequence_pixels"] = pixels

        return start_new_sequence

    output_sequences = []
    for sequence in input_sequences:
        output_sequences.extend(
            split_sequence_by_agg(
                sequence, should_split_with_sequence_state=_should_split
            )
        )

    assert sum(len(s) for s in output_sequences) == sum(len(s) for s in input_sequences)

    LOG.info("Found %s sequences after split by sequence limits", len(output_sequences))

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

        # Split sequences by cutoff time
        # NOTE: Do not split by distance here because it affects the speed limit check
        sequences = _split_sequences_by_cutoff_time(sequences, cutoff_time=cutoff_time)

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

        # Split sequences by max number of images, max filesize, and max pixels
        sequences = _split_sequences_by_limits(
            sequences,
            max_sequence_filesize_in_bytes=max_sequence_filesize_in_bytes,
            max_sequence_pixels=max_sequence_pixels,
        )

        # Check limits for sequences
        sequences, errors = _check_sequences_by_limits(
            sequences,
            max_sequence_filesize_in_bytes=max_sequence_filesize_in_bytes,
            max_avg_speed=max_avg_speed,
        )
        error_metadatas.extend(errors)

        # Split sequences by cutoff distance
        # NOTE: The speed limit check probably rejects most of anomalies
        sequences = _split_sequences_by_cutoff_distance(
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
