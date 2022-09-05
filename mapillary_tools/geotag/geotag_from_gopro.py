import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import constants, exceptions, geo, types, utils
from . import gpmf_parser, gps_filter, utils as geotag_utils
from .geotag_from_generic import GeotagFromGeneric
from .geotag_from_gpx import GeotagFromGPXWithProgress


LOG = logging.getLogger(__name__)


class GeotagFromGoPro(GeotagFromGeneric):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        video_paths: T.Sequence[Path],
        offset_time: float = 0.0,
    ):
        self.image_paths = image_paths
        self.video_paths = video_paths
        self.offset_time = offset_time
        super().__init__()

    def _filter_out_outliers(
        self, points: T.List[gpmf_parser.PointWithFix]
    ) -> T.List[gpmf_parser.PointWithFix]:
        distances = [
            geo.gps_distance((left.lat, left.lon), (right.lat, right.lon))
            for left, right in geo.pairwise(points)
        ]
        if len(distances) < 2:
            return points

        max_distance = gps_filter.upper_whisker(distances)
        LOG.debug("max distance: %f", max_distance)
        max_distance = max(
            # distance between two points hence double
            constants.GOPRO_GPS_PRECISION + constants.GOPRO_GPS_PRECISION,
            max_distance,
        )
        sequences = gps_filter.split_if(
            T.cast(T.List[geo.Point], points),
            gps_filter.distance_gt(max_distance),
        )
        LOG.debug(
            "Split to %d sequences with max distance %f", len(sequences), max_distance
        )

        ground_speeds = [
            point.gps_ground_speed
            for point in points
            if point.gps_ground_speed is not None
        ]
        if len(ground_speeds) < 2:
            return points

        max_speed = gps_filter.upper_whisker(ground_speeds)
        merged = gps_filter.dbscan(sequences, gps_filter.speed_le(max_speed))
        LOG.debug(
            "Found %d sequences after merging with max speed %f", len(merged), max_speed
        )

        return T.cast(
            T.List[gpmf_parser.PointWithFix],
            gps_filter.find_majority(merged.values()),
        )

    def _filter_noisy_points(
        self, points: T.Sequence[gpmf_parser.PointWithFix], video: Path
    ) -> T.Sequence[gpmf_parser.PointWithFix]:
        num_points = len(points)
        points = [
            p
            for p in points
            if p.gps_fix is not None and p.gps_fix.value in constants.GOPRO_GPS_FIXES
        ]
        if len(points) < num_points:
            LOG.warning(
                "Removed %d points with the GPS fix not in %s from %s",
                num_points - len(points),
                constants.GOPRO_GPS_FIXES,
                video,
            )

        num_points = len(points)
        points = [
            p
            for p in points
            if p.gps_precision is not None
            and p.gps_precision <= constants.GOPRO_MAX_DOP100
        ]
        if len(points) < num_points:
            LOG.warning(
                "Removed %d points with DoP value higher than %d from %s",
                num_points - len(points),
                constants.GOPRO_MAX_DOP100,
                video,
            )

        num_points = len(points)
        points = self._filter_out_outliers(points)
        if len(points) < num_points:
            LOG.warning(
                "Removed %d outlier points from %s",
                num_points - len(points),
                video,
            )

        return points

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs: T.List[types.ImageDescriptionFileOrError] = []

        for video_path in self.video_paths:
            LOG.debug("Processing GoPro video: %s", video_path)

            sample_images = list(
                utils.filter_video_samples(self.image_paths, video_path)
            )
            LOG.debug(
                "Found %d sample images from video %s",
                len(sample_images),
                video_path,
            )

            if not sample_images:
                continue

            points = self._filter_noisy_points(
                gpmf_parser.parse_gpx(video_path), video_path
            )

            # bypass empty points to raise MapillaryGPXEmptyError
            if points and geotag_utils.is_video_stationary(
                geo.get_max_distance_from_start([(p.lat, p.lon) for p in points])
            ):
                LOG.warning(
                    "Fail %d sample images due to stationary video %s",
                    len(sample_images),
                    video_path,
                )
                for image_path in sample_images:
                    err_desc = types.describe_error(
                        exceptions.MapillaryStationaryVideoError(
                            "Stationary GoPro video"
                        ),
                        str(image_path),
                    )
                    descs.append(err_desc)
                continue

            with tqdm(
                total=len(sample_images),
                desc=f"Interpolating {video_path.name}",
                unit="images",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
            ) as pbar:
                geotag = GeotagFromGPXWithProgress(
                    sample_images,
                    points,
                    use_gpx_start_time=False,
                    use_image_start_time=True,
                    offset_time=self.offset_time,
                    progress_bar=pbar,
                )
                descs.extend(geotag.to_description())

        return descs
