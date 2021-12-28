import os
import typing as T
import datetime
import uuid
import itertools

from . import types
from .geo import compute_bearing, gps_distance, diff_bearing, pairwise
from .exceptions import MapillaryDuplicationError

MAX_SEQUENCE_LENGTH = 500


class _GPXPoint:
    desc: types.ImageDescriptionFile

    def __init__(self, desc: types.ImageDescriptionFile):
        self.desc = desc

    @property
    def filename(self) -> str:
        return self.desc["filename"]

    @property
    def lat(self) -> float:
        return self.desc["MAPLatitude"]

    @property
    def lon(self) -> float:
        return self.desc["MAPLongitude"]

    @property
    def time(self) -> datetime.datetime:
        return types.map_capture_time_to_datetime(self.desc["MAPCaptureTime"])

    @property
    def angle(self) -> T.Optional[float]:
        return self.desc.get("MAPCompassHeading", {}).get("TrueHeading")


GPXSequence = T.List[_GPXPoint]


def cut_sequences(
    sequence: GPXSequence,
    cutoff_distance: float,
    cutoff_time: float,
) -> T.List[GPXSequence]:
    sequences: T.List[T.List[_GPXPoint]] = []

    if sequence:
        sequences.append([sequence[0]])

    for prev, cur in pairwise(sequence):
        # invariant: prev is processed
        distance = gps_distance(
            (prev.lat, prev.lon),
            (cur.lat, cur.lon),
        )
        if cutoff_distance <= distance:
            sequences.append([cur])
            continue
        time_diff = (cur.time - prev.time).total_seconds()
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
        distance = gps_distance(
            (prev.lat, prev.lon),
            (cur.lat, cur.lon),
        )
        distance_duplicated = distance <= duplicate_distance

        if prev.angle is not None and cur.angle is not None:
            bearing_delta = diff_bearing(prev.angle, cur.angle)
            angle_duplicated = bearing_delta <= duplicate_angle
        else:
            angle_duplicated = False

        if distance_duplicated and angle_duplicated:
            duplicates.append(idx + 1)
            continue

        prev = cur

    return duplicates


def group_descs_by_folder(
    descs: T.List[types.ImageDescriptionFile],
) -> T.List[T.List[types.ImageDescriptionFile]]:
    descs.sort(key=lambda desc: os.path.dirname(desc["filename"]))
    group = itertools.groupby(descs, key=lambda desc: os.path.dirname(desc["filename"]))
    sequences = []
    for _, sequence in group:
        sequences.append(list(sequence))
    return sequences


def duplication_check(
    sequence: GPXSequence,
    duplicate_distance: float,
    duplicate_angle: float,
) -> T.Tuple[GPXSequence, T.List[types.ImageDescriptionFileError]]:
    dup_indices = find_duplicates(
        sequence,
        duplicate_distance=duplicate_distance,
        duplicate_angle=duplicate_angle,
    )
    dup_set = set(dup_indices)
    dups = [image for idx, image in enumerate(sequence) if idx in dup_set]
    failures: T.List[types.ImageDescriptionFileError] = []
    for image in dups:
        error: types.ImageDescriptionFileError = {
            "error": types.describe_error(
                MapillaryDuplicationError("duplicated", image.desc)
            ),
            "filename": image.filename,
        }

        failures.append(error)

    dedups = [image for idx, image in enumerate(sequence) if idx not in dup_set]
    return dedups, failures


def interpolate(sequence: GPXSequence, interpolate_directions: bool) -> GPXSequence:
    interpolated: GPXSequence = []
    for cur, nex in pairwise(sequence):
        # should interpolate or not
        if interpolate_directions or cur.angle is None:
            new_bearing = compute_bearing(cur.lat, cur.lon, nex.lat, nex.lon)
            new_desc = T.cast(
                types.ImageDescriptionFile,
                {
                    **cur.desc,
                    "MAPCompassHeading": {
                        "TrueHeading": new_bearing,
                        "MagneticHeading": new_bearing,
                    },
                },
            )
            interpolated.append(_GPXPoint(new_desc))
        else:
            interpolated.append(cur)

    if interpolated:
        assert len(interpolated) == len(sequence) - 1
    else:
        assert len(sequence) <= 1

    # interpolate the last image's angle
    # can interpolate or not
    if 2 <= len(sequence) and interpolated[-1] is not None:
        # should interpolate or not
        if interpolate_directions or sequence[-1] is None:
            new_desc = T.cast(
                types.ImageDescriptionFile,
                {
                    **sequence[-1].desc,
                    "MAPCompassHeading": {
                        "TrueHeading": interpolated[-1].angle,
                        "MagneticHeading": interpolated[-1].angle,
                    },
                },
            )
            interpolated.append(_GPXPoint(new_desc))
        else:
            interpolated.append(sequence[-1])
    else:
        interpolated.append(sequence[-1])

    assert len(interpolated) == len(sequence)

    return interpolated


def cap_sequence(sequence: GPXSequence) -> T.List[GPXSequence]:
    sequences: T.List[GPXSequence] = []
    for idx in range(0, len(sequence), MAX_SEQUENCE_LENGTH):
        sequences.append([])
        for image in sequence[idx : idx + MAX_SEQUENCE_LENGTH]:
            sequences[-1].append(image)
    return sequences


def process_sequence_properties(
    descs: T.List[types.ImageDescriptionFileOrError],
    cutoff_distance=600.0,
    cutoff_time=60.0,
    interpolate_directions=False,
    duplicate_distance=0.1,
    duplicate_angle=5,
) -> T.List[types.ImageDescriptionFileOrError]:
    groups = group_descs_by_folder(types.filter_out_errors(descs))

    sequences = []
    for group in groups:
        sequences.extend(
            cut_sequences(
                [_GPXPoint(desc) for desc in group], cutoff_distance, cutoff_time
            )
        )

    processed = [desc for desc in descs if types.is_error(desc)]

    for sequence in sequences:
        # duplication check
        passed, failed = duplication_check(
            sequence,
            duplicate_distance=duplicate_distance,
            duplicate_angle=duplicate_angle,
        )
        for desc in failed:
            processed.append(desc)

        # interpolate angles
        interpolated = interpolate(passed, interpolate_directions)

        # cut sequence per MAX_SEQUENCE_LENGTH images
        capped = cap_sequence(interpolated)

        for s in capped:
            sequence_uuid = str(uuid.uuid4())
            for p in s:
                processed.append(
                    T.cast(
                        types.ImageDescriptionFile,
                        {**p.desc, "MAPSequenceUUID": sequence_uuid},
                    )
                )

    assert len(descs) == len(processed)

    return processed
