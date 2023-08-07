import abc
import typing as T
from pathlib import Path

from mapillary_tools import exceptions, geo

from .. import types
from . import gpmf_gps_filter, utils as video_utils


class GeotagImagesFromGeneric(abc.ABC):
    def __init__(self) -> None:
        pass

    @abc.abstractmethod
    def to_description(self) -> T.Sequence[types.ImageMetadataOrError]:
        raise NotImplementedError


class GeotagVideosFromGeneric(abc.ABC):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        num_processes: T.Optional[int] = None,
    ) -> None:
        self.video_paths = video_paths
        self.num_processes = num_processes

    @abc.abstractmethod
    def to_description(self) -> T.Sequence[types.VideoMetadataOrError]:
        raise NotImplementedError

    @staticmethod
    def process_points(points: T.Sequence[geo.Point]) -> T.Sequence[geo.Point]:
        """Deduplicates points, when possible removes noisy ones, and checks
        against stationary videos"""

        points = geo.extend_deduplicate_points(points)
        assert points, "must have at least one point"

        if all(isinstance(p, geo.PointWithFix) for p in points):
            points = T.cast(
                T.Sequence[geo.Point],
                gpmf_gps_filter.remove_noisy_points(
                    T.cast(T.Sequence[geo.PointWithFix], points)
                ),
            )
            if not points:
                raise exceptions.MapillaryGPSNoiseError("GPS is too noisy")

        stationary = video_utils.is_video_stationary(
            geo.get_max_distance_from_start([(p.lat, p.lon) for p in points])
        )

        if stationary:
            raise exceptions.MapillaryStationaryVideoError("Stationary video")

        return points
