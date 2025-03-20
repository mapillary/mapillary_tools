import statistics
import typing as T

from .. import geo


PointSequence = T.List[geo.Point]
Decider = T.Callable[[geo.Point, geo.Point], bool]


def calculate_point_speed(p1: geo.Point, p2: geo.Point) -> float:
    """
    Calculate the ground speed between two points (from p1 to p2).
    """
    s = geo.gps_distance((p1.lat, p1.lon), (p2.lat, p2.lon))
    t = abs(p2.time - p1.time)
    try:
        return s / t
    except ZeroDivisionError:
        return float("inf") if 0 <= s else float("-inf")


def upper_whisker(values: T.Sequence[float]) -> float:
    """
    Calculate the upper whisker (i.e. Q3 + IRQ * 1.5) of the input values.
    Values larger than it are considered as outliers.
    See https://en.wikipedia.org/wiki/Interquartile_range
    """

    values = sorted(values)
    n = len(values)
    if n < 2:
        raise statistics.StatisticsError("at least 2 values are required for IQR")
    median_idx = n // 2
    q1 = statistics.median(values[:median_idx])
    if n % 2 == 1:
        # for values [0, 1, 2, 3, 4], q3 will be [3, 4]
        q3 = statistics.median(values[median_idx + 1 :])
    else:
        # for values [0, 1, 2, 3], q3 will be [2, 3]
        q3 = statistics.median(values[median_idx:])
    irq = q3 - q1
    return q3 + irq * 1.5


def split_if(
    points: PointSequence,
    split_or_not: Decider,
) -> T.List[PointSequence]:
    if not points:
        return []

    sequences: T.List[PointSequence] = []
    for idx, point in enumerate(points):
        if sequences and not split_or_not(points[idx - 1], point):
            sequences[-1].append(point)
        else:
            sequences.append([point])
    assert len(points) == sum(len(g) for g in sequences)

    return sequences


def distance_gt(
    max_distance: float,
) -> Decider:
    """Return a callable that checks if two points are farther than the given distance."""

    def _split_or_not(p1, p2):
        distance = geo.gps_distance((p1.lat, p1.lon), (p2.lat, p2.lon))
        return distance > max_distance

    return _split_or_not


def speed_le(max_speed: float) -> Decider:
    """Return a callable that checks if the speed between two points are slower than the given speed."""

    def _split_or_not(p1, p2):
        speed = calculate_point_speed(p1, p2)
        return speed <= max_speed

    return _split_or_not


def both(
    s1: Decider,
    s2: Decider,
) -> Decider:
    def _f(p1, p2):
        return s1(p1, p2) and s2(p1, p2)

    return _f


def dbscan(
    sequences: T.Sequence[PointSequence],
    merge_or_not: Decider,
) -> T.Dict[int, PointSequence]:
    """
    One-dimension DBSCAN clustering: https://en.wikipedia.org/wiki/DBSCAN
    The input is a list of sequences, and it is guaranteed that all sequences are sorted by time.
    The function clusters sequences by checking if two sequences can be merged or not.

    - minPoints is always 1
    - merge_or_not decides if two points are in the same cluster
    """

    # find which sequences (keys) should be merged to which sequences (values)
    mergeto: T.Dict[int, int] = {}
    for left in range(len(sequences)):
        mergeto.setdefault(left, left)
        # find the first sequence to merge with
        for right in range(left + 1, len(sequences)):
            if right in mergeto:
                continue
            if merge_or_not(sequences[left][-1], sequences[right][0]):
                mergeto[right] = mergeto[left]
                break

    # merge
    merged: T.Dict[int, PointSequence] = {}
    for idx, s in enumerate(sequences):
        merged.setdefault(mergeto[idx], []).extend(s)

    return merged


def find_majority(sequences: T.Collection[PointSequence]) -> PointSequence:
    return sorted(sequences, key=lambda g: len(g), reverse=True)[0]
