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
        image_dir: Path,
        source_path: Path,
        offset_time: float = 0.0,
    ):
        self.image_dir = image_dir
        if source_path.is_dir():
            self.videos = utils.get_video_file_list(source_path, abs_path=True)
        else:
            # it is okay to not suffix with .mp4
            self.videos = [source_path]
        self.offset_time = offset_time
        super().__init__()

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs: T.List[types.ImageDescriptionFileOrError] = []
        images = utils.get_image_file_list(self.image_dir)
        for video in self.videos:
            LOG.debug("Processing CAMM video: %s", video)

            sample_images = list(utils.filter_video_samples(images, video))
            LOG.debug(
                "Found %d sample images from video %s",
                len(sample_images),
                video,
            )

            if not sample_images:
                continue

            points = camm_parser.parse_gpx(video)

            # bypass empty points to raise MapillaryGPXEmptyError
            if points and geotag_utils.is_video_stationary(
                geo.get_max_distance_from_start([(p.lat, p.lon) for p in points])
            ):
                LOG.warning(
                    "Fail %d sample images due to stationary video %s",
                    len(sample_images),
                    video,
                )
                for image in sample_images:
                    err = types.describe_error(
                        exceptions.MapillaryStationaryVideoError(
                            "Stationary CAMM video"
                        )
                    )
                    descs.append({"error": err, "filename": str(image)})
                continue

            with tqdm(
                total=len(sample_images),
                desc=f"Interpolating {video.name}",
                unit="images",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
            ) as pbar:
                geotag = GeotagFromGPXWithProgress(
                    self.image_dir,
                    sample_images,
                    points,
                    use_gpx_start_time=False,
                    use_image_start_time=True,
                    offset_time=self.offset_time,
                    progress_bar=pbar,
                )
                descs.extend(geotag.to_description())
        return descs
