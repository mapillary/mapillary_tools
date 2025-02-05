import itertools
import logging
import math
import os
import typing as T

from . import constants, geo, types
from .exceptions import MapillaryBadParameterError, MapillaryDuplicationError

LOG = logging.getLogger(__name__)


Point = T.TypeVar("Point", bound=geo.Point)
PointSequence = T.List[Point]


def cut_sequence_by_time_distance(
    sequence: PointSequence,
    cutoff_distance: float,
    cutoff_time: float,
) -> T.List[PointSequence]:
    sequences: T.List[PointSequence] = []

    if sequence:
        sequences.append([sequence[0]])

    for prev, cur in geo.pairwise(sequence):
        # invariant: prev is processed
        distance = geo.gps_distance(
            (prev.lat, prev.lon),
            (cur.lat, cur.lon),
        )
        if cutoff_distance <= distance:
            sequences.append([cur])
            continue
        time_diff = cur.time - prev.time
        assert 0 <= time_diff, "sequence must be sorted by capture times"
        if cutoff_time <= time_diff:
            sequences.append([cur])
            continue
        sequences[-1].append(cur)
        # invariant: cur is processed

    return sequences


def duplication_check(
    sequence: PointSequence,
    duplicate_distance: float,
    duplicate_angle: float,
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

        if distance <= duplicate_distance and (
            angle_diff is not None and angle_diff <= duplicate_angle
        ):
            dups.append(
                types.describe_error_metadata(
                    MapillaryDuplicationError(
                        f"Duplicate of its previous image in terms of distance <= {duplicate_distance} and angle <= {duplicate_angle}",
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
    sequences_by_parent: T.Dict[str, T.List[types.ImageMetadata]] = {}
    for image_metadata in image_metadatas:
        filename = image_metadata.filename.resolve()
        sequences_by_parent.setdefault(str(filename.parent), []).append(image_metadata)

    sequences = list(sequences_by_parent.values())
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


def _parse_pixels(pixels_str: str) -> int:
    pixels_str = pixels_str.strip().upper()

    if pixels_str.endswith("K"):
        return int(pixels_str[:-1]) * 1000
    elif pixels_str.endswith("M"):
        return int(pixels_str[:-1]) * 1000 * 1000
    elif pixels_str.endswith("G"):
        return int(pixels_str[:-1]) * 1000 * 1000 * 1000
    else:
        return int(pixels_str)


def process_sequence_properties(
    metadatas: T.Sequence[types.MetadataOrError],
    cutoff_distance=constants.CUTOFF_DISTANCE,
    cutoff_time=constants.CUTOFF_TIME,
    interpolate_directions=False,
    duplicate_distance=constants.DUPLICATE_DISTANCE,
    duplicate_angle=constants.DUPLICATE_ANGLE,
) -> T.List[types.MetadataOrError]:
    try:
        max_sequence_filesize_in_bytes = _parse_filesize_in_bytes(
            constants.MAX_SEQUENCE_FILESIZE
        )
    except ValueError:
        raise MapillaryBadParameterError(
            f"Expect the envvar {constants._ENV_PREFIX}MAX_SEQUENCE_FILESIZE to be a valid filesize that ends with B, K, M, or G, but got {constants.MAX_SEQUENCE_FILESIZE}"
        )

    try:
        max_sequence_pixels = _parse_pixels(constants.MAX_SEQUENCE_PIXELS)
    except ValueError:
        raise MapillaryBadParameterError(
            f"Expect the envvar {constants._ENV_PREFIX}MAX_SEQUENCE_PIXELS to be a valid number of pixels that ends with K, M, or G, but got {constants.MAX_SEQUENCE_PIXELS}"
        )

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

    sequences_by_folder = _group_sort_images_by_folder(image_metadatas)
    # make sure they are sorted
    for sequence in sequences_by_folder:
        for cur, nxt in geo.pairwise(sequence):
            assert cur.time <= nxt.time, "sequence must be sorted"

    for s in sequences_by_folder:
        _interpolate_subsecs_for_sorting(s)

    # cut sequences
    sequences_after_cut: T.List[PointSequence] = []
    for sequence in sequences_by_folder:
        cut = cut_sequence_by_time_distance(sequence, cutoff_distance, cutoff_time)
        sequences_after_cut.extend(cut)
    assert len(image_metadatas) == sum(len(s) for s in sequences_after_cut)

    # reuse imaeg_metadatas to store processed image metadatas
    image_metadatas = []

    sequence_idx = 0

    for sequence in sequences_after_cut:
        # duplication check
        dedups, dups = duplication_check(
            sequence,
            duplicate_distance=duplicate_distance,
            duplicate_angle=duplicate_angle,
        )
        assert len(sequence) == len(dedups) + len(dups)
        error_metadatas.extend(dups)

        # interpolate angles
        if interpolate_directions:
            for p in dedups:
                p.angle = None
        geo.interpolate_directions_if_none(dedups)

        # cut sequence per MAX_SEQUENCE_LENGTH images
        cut = cut_sequence(
            dedups,
            constants.MAX_SEQUENCE_LENGTH,
            max_sequence_filesize_in_bytes,
            max_sequence_pixels,
        )

        # assign sequence UUIDs
        for c in cut:
            for p in c:
                # using incremental id as shorter "uuid", so we can save some space for the desc file
                p.MAPSequenceUUID = str(sequence_idx)
                image_metadatas.append(p)
            sequence_idx += 1

    results = error_metadatas + image_metadatas + video_metadatas

    assert len(metadatas) == len(results), (
        f"expected {len(metadatas)} results but got {len(results)}"
    )
    assert sequence_idx == len(
        set(metadata.MAPSequenceUUID for metadata in image_metadatas)
    )

    return results
