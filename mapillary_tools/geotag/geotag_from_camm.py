import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, geo, types, utils
from . import camm_parser, utils as geotag_utils
from .geotag_from_generic import GeotagFromGeneric
from .geotag_from_gpx import GeotagFromGPXWithProgress


LOG = logging.getLogger(__name__)


class GeotagFromCAMM(GeotagFromGeneric):
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

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs: T.List[types.ImageDescriptionFileOrError] = []
        for video_path in self.video_paths:
            LOG.debug("Processing CAMM video: %s", video_path)

            sample_image_paths = list(
                utils.filter_video_samples(self.image_paths, video_path)
            )
            LOG.debug(
                "Found %d sample images from video %s",
                len(sample_image_paths),
                video_path,
            )

            if not sample_image_paths:
                continue

            points = camm_parser.parse_gpx(video_path)

            # bypass empty points to raise MapillaryGPXEmptyError
            if points and geotag_utils.is_video_stationary(
                geo.get_max_distance_from_start([(p.lat, p.lon) for p in points])
            ):
                LOG.warning(
                    "Fail %d sample images due to stationary video %s",
                    len(sample_image_paths),
                    video_path,
                )
                for image_path in sample_image_paths:
                    err_desc = types.describe_error(
                        exceptions.MapillaryStationaryVideoError(
                            "Stationary CAMM video"
                        ),
                        str(image_path),
                    )
                    descs.append(err_desc)
                continue

            with tqdm(
                total=len(sample_image_paths),
                desc=f"Interpolating {video_path.name}",
                unit="images",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
            ) as pbar:
                geotag = GeotagFromGPXWithProgress(
                    sample_image_paths,
                    points,
                    use_gpx_start_time=False,
                    use_image_start_time=True,
                    offset_time=self.offset_time,
                    progress_bar=pbar,
                )
                descs.extend(geotag.to_description())
        return descs
