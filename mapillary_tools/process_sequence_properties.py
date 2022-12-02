import typing as T

from . import constants, geo, types
from .exceptions import MapillaryDuplicationError


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


def find_duplicates(
    sequence: PointSequence,
    duplicate_distance: float,
    duplicate_angle: float,
) -> T.List[int]:
    if not sequence:
        return []

    duplicates = []
    sequence_iter = iter(sequence)
    prev = next(sequence_iter)
    for idx, cur in enumerate(sequence_iter):
        distance = geo.gps_distance(
            (prev.lat, prev.lon),
            (cur.lat, cur.lon),
        )
        distance_duplicated = distance <= duplicate_distance

        if prev.angle is not None and cur.angle is not None:
            bearing_delta = geo.diff_bearing(prev.angle, cur.angle)
            angle_duplicated = bearing_delta <= duplicate_angle
        else:
            angle_duplicated = False

        if distance_duplicated and angle_duplicated:
            duplicates.append(idx + 1)
            continue

        prev = cur

    return duplicates


def duplication_check(
    sequence: PointSequence,
    duplicate_distance: float,
    duplicate_angle: float,
) -> T.Tuple[PointSequence, PointSequence]:
    dup_indices = find_duplicates(
        sequence,
        duplicate_distance=duplicate_distance,
        duplicate_angle=duplicate_angle,
    )
    dup_set = set(dup_indices)
    dedups = [image for idx, image in enumerate(sequence) if idx not in dup_set]
    dups = [image for idx, image in enumerate(sequence) if idx in dup_set]
    return dedups, dups


def cut_sequence_by_max_images(
    sequence: PointSequence, max_images: int
) -> T.List[PointSequence]:
    sequences: T.List[PointSequence] = []
    for idx in range(0, len(sequence), max_images):
        sequences.append([])
        for image in sequence[idx : idx + max_images]:
            sequences[-1].append(image)
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
        # Sort images in a sequence by capture time
        # and then filename (in case capture times are the same)
        sequence.sort(
            key=lambda metadata: (
                metadata.time,
                metadata.filename.name,
            )
        )

    return sequences


def process_sequence_properties(
    metadatas: T.List[types.MetadataOrError],
    cutoff_distance=constants.CUTOFF_DISTANCE,
    cutoff_time=constants.CUTOFF_TIME,
    interpolate_directions=False,
    duplicate_distance=constants.DUPLICATE_DISTANCE,
    duplicate_angle=constants.DUPLICATE_ANGLE,
) -> T.List[types.MetadataOrError]:
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
        for dup in dups:
            error_metadatas.append(
                types.describe_error_metadata(
                    MapillaryDuplicationError("duplicated", types.as_desc(dup)),
                    dup.filename,
                    filetype=types.FileType.IMAGE,
                ),
            )

        # interpolate angles
        if interpolate_directions:
            for p in dedups:
                p.angle = None
        geo.interpolate_directions_if_none(dedups)

        # cut sequence per MAX_SEQUENCE_LENGTH images
        cut = cut_sequence_by_max_images(dedups, constants.MAX_SEQUENCE_LENGTH)

        # assign sequence UUIDs
        for c in cut:
            for p in c:
                # using incremental id as shorter "uuid", so we can save some space for the desc file
                p.MAPSequenceUUID = str(sequence_idx)
                image_metadatas.append(p)
            sequence_idx += 1

    results = error_metadatas + image_metadatas + video_metadatas

    assert len(metadatas) == len(
        results
    ), f"expected {len(metadatas)} results but got {len(results)}"
    assert sequence_idx == len(
        set(metadata.MAPSequenceUUID for metadata in image_metadatas)
    )

    return results
