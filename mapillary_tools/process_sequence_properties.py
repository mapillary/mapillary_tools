import dataclasses
import os
import typing as T
import uuid
from pathlib import Path

from . import constants, geo, types
from .exceptions import MapillaryDuplicationError


@dataclasses.dataclass
class DescPoint(geo.Point):
    _desc: types.ImageDescriptionFile
    sequence_uuid: T.Optional[str] = None

    def __init__(self, desc: types.ImageDescriptionFile):
        self._desc = desc
        super().__init__(
            time=geo.as_unix_time(
                types.map_capture_time_to_datetime(desc["MAPCaptureTime"])
            ),
            lat=desc["MAPLatitude"],
            lon=desc["MAPLongitude"],
            alt=desc.get("MAPAltitude"),
            angle=desc.get("MAPCompassHeading", {}).get("TrueHeading"),
        )

    def as_desc(self) -> types.ImageDescriptionFile:
        new_desc = T.cast(
            types.ImageDescriptionFile,
            {
                **self._desc,
                **types.as_desc(self),
            },
        )
        if self.sequence_uuid is not None:
            new_desc["MAPSequenceUUID"] = self.sequence_uuid
        return new_desc


GPXSequence = T.List[geo.Point]


def cut_sequences(
    sequence: GPXSequence,
    cutoff_distance: float,
    cutoff_time: float,
) -> T.List[GPXSequence]:
    sequences: T.List[GPXSequence] = []

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
    sequence: GPXSequence,
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
    sequence: GPXSequence,
    duplicate_distance: float,
    duplicate_angle: float,
) -> T.Tuple[GPXSequence, GPXSequence]:
    dup_indices = find_duplicates(
        sequence,
        duplicate_distance=duplicate_distance,
        duplicate_angle=duplicate_angle,
    )
    dup_set = set(dup_indices)
    dedups = [image for idx, image in enumerate(sequence) if idx not in dup_set]
    dups = [image for idx, image in enumerate(sequence) if idx in dup_set]
    return dedups, dups


def interpolate_directions_if_none(sequence: GPXSequence) -> None:
    for cur, nex in geo.pairwise(sequence):
        if cur.angle is None:
            cur.angle = geo.compute_bearing(cur.lat, cur.lon, nex.lat, nex.lon)

    if 2 <= len(sequence):
        if sequence[-1].angle is None:
            sequence[-1].angle = sequence[-2].angle


def cap_sequence(sequence: GPXSequence) -> T.List[GPXSequence]:
    sequences: T.List[GPXSequence] = []
    for idx in range(0, len(sequence), constants.MAX_SEQUENCE_LENGTH):
        sequences.append([])
        for image in sequence[idx : idx + constants.MAX_SEQUENCE_LENGTH]:
            sequences[-1].append(image)
    return sequences


def group_and_sort_descs_by_folder(
    descs: T.List[types.ImageDescriptionFile],
) -> T.List[T.List[types.ImageDescriptionFile]]:
    # group descs by parent directory
    sequences_by_parent: T.Dict[str, T.List[types.ImageDescriptionFile]] = {}
    for desc in descs:
        filename = Path(desc["filename"]).resolve()
        sequences_by_parent.setdefault(str(filename.parent), []).append(desc)

    sequences = list(sequences_by_parent.values())
    for sequence in sequences:
        # Sort images in a sequence by capture time
        # and then filename (in case capture times are the same)
        sequence.sort(
            key=lambda desc: (
                types.map_capture_time_to_datetime(desc["MAPCaptureTime"]),
                os.path.basename(desc["filename"]),
            )
        )

    return sequences


def process_sequence_properties(
    descs: T.List[types.ImageDescriptionFileOrError],
    cutoff_distance=constants.CUTOFF_DISTANCE,
    cutoff_time=constants.CUTOFF_TIME,
    interpolate_directions=False,
    duplicate_distance=constants.DUPLICATE_DISTANCE,
    duplicate_angle=constants.DUPLICATE_ANGLE,
) -> T.List[types.ImageDescriptionFileOrError]:
    error_descs: T.List[types.ImageDescriptionFileError] = []
    good_descs: T.List[types.ImageDescriptionFile] = []
    processed_descs: T.List[types.ImageDescriptionFile] = []

    for desc in descs:
        if types.is_error(desc):
            error_descs.append(T.cast(types.ImageDescriptionFileError, desc))
        else:
            good_descs.append(T.cast(types.ImageDescriptionFile, desc))

    groups = group_and_sort_descs_by_folder(good_descs)
    # make sure they are sorted
    for group in groups:
        for cur, nxt in geo.pairwise(group):
            assert types.map_capture_time_to_datetime(
                cur["MAPCaptureTime"]
            ) <= types.map_capture_time_to_datetime(
                nxt["MAPCaptureTime"]
            ), "sequence must be sorted"

    # cut sequences
    sequences = []
    for group in groups:
        s: GPXSequence = [DescPoint(desc) for desc in group]
        sequences.extend(cut_sequences(s, cutoff_distance, cutoff_time))
    assert len(good_descs) == sum(len(s) for s in sequences)

    for sequence in sequences:

        # duplication check
        sequence, dups = duplication_check(
            sequence,
            duplicate_distance=duplicate_distance,
            duplicate_angle=duplicate_angle,
        )
        for dup in dups:
            desc = T.cast(DescPoint, dup).as_desc()
            error_descs.append(
                types.describe_error(
                    MapillaryDuplicationError("duplicated", desc), desc["filename"]
                ),
            )

        # interpolate angles
        if interpolate_directions:
            for p in sequence:
                p.angle = None
        interpolate_directions_if_none(sequence)

        # cut sequence per MAX_SEQUENCE_LENGTH images
        capped = cap_sequence(sequence)

        # assign sequence UUIDs
        for s in capped:
            sequence_uuid = str(uuid.uuid4())
            for p in T.cast(T.List[DescPoint], s):
                p.sequence_uuid = sequence_uuid
                processed_descs.append(p.as_desc())

    assert len(descs) == len(error_descs) + len(processed_descs)

    return T.cast(T.List[types.ImageDescriptionFileOrError], error_descs) + T.cast(
        T.List[types.ImageDescriptionFileOrError], processed_descs
    )
