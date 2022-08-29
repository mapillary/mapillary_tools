import logging
import os
import pathlib
import typing as T

from tqdm import tqdm

from .. import geo, types, utils
from ..exceptions import (
    MapillaryInvalidBlackVueVideoError,
    MapillaryStationaryVideoError,
)
from ..geo import get_max_distance_from_start
from . import blackvue_parser, utils as geotag_utils
from .geotag_from_generic import GeotagFromGeneric
from .geotag_from_gpx import GeotagFromGPXWithProgress

LOG = logging.getLogger(__name__)


class GeotagFromBlackVue(GeotagFromGeneric):
    def __init__(
        self,
        image_dir: str,
        source_path: str,
        use_gpx_start_time: bool = False,
        offset_time: float = 0.0,
    ):
        super().__init__()
        self.image_dir = image_dir
        if os.path.isdir(source_path):
            self.blackvue_videos = utils.get_video_file_list(source_path, abs_path=True)
        else:
            # it is okay to not suffix with .mp4
            self.blackvue_videos = [source_path]
        self.source_path = source_path
        self.use_gpx_start_time = use_gpx_start_time
        self.offset_time = offset_time

    def to_description(self) -> T.List[types.ImageDescriptionFileOrError]:
        descs: T.List[types.ImageDescriptionFileOrError] = []

        images = utils.get_image_file_list(self.image_dir)
        for blackvue_video in self.blackvue_videos:
            LOG.debug("Processing BlackVue video: %s", blackvue_video)

            sample_images = utils.filter_video_samples(images, blackvue_video)
            LOG.debug(
                "Found %d sample images from video %s",
                len(sample_images),
                blackvue_video,
            )

            if not sample_images:
                continue

            try:
                points = blackvue_parser.parse_gps_points(pathlib.Path(blackvue_video))
            except MapillaryInvalidBlackVueVideoError:
                for image in sample_images:
                    err = types.describe_error(
                        MapillaryInvalidBlackVueVideoError(
                            f"Unable to parse the BlackVue video: {blackvue_video}"
                        )
                    )
                    descs.append({"error": err, "filename": image})
                continue

            # bypass empty points to raise MapillaryGPXEmptyError
            if points and geotag_utils.is_video_stationary(
                get_max_distance_from_start([(p.lat, p.lon) for p in points])
            ):
                LOG.warning(
                    "Fail %d sample images due to stationary video %s",
                    len(sample_images),
                    blackvue_video,
                )
                for image in sample_images:
                    err = types.describe_error(
                        MapillaryStationaryVideoError("Stationary BlackVue video")
                    )
                    descs.append({"error": err, "filename": image})
                continue

            model = blackvue_parser.find_camera_model(pathlib.Path(blackvue_video))
            LOG.debug(
                f"Found BlackVue camera model %s from video %s", model, blackvue_video
            )

            with tqdm(
                total=len(sample_images),
                desc=f"Interpolating {os.path.basename(blackvue_video)}",
                unit="images",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
            ) as pbar:
                geotag = GeotagFromGPXWithProgress(
                    self.image_dir,
                    sample_images,
                    points,
                    use_gpx_start_time=self.use_gpx_start_time,
                    offset_time=self.offset_time,
                    progress_bar=pbar,
                )
                for desc in geotag.to_description():
                    if not types.is_error(desc):
                        desc = T.cast(types.ImageDescriptionFile, desc)
                        desc["MAPDeviceMake"] = "Blackvue"
                        if model:
                            desc["MAPDeviceModel"] = model
                    descs.append(desc)

        return descs
