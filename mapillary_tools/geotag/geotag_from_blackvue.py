import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, geo, types, utils
from . import blackvue_parser, utils as geotag_utils
from .geotag_from_generic import GeotagFromGeneric
from .geotag_from_gpx import GeotagFromGPXWithProgress

LOG = logging.getLogger(__name__)


class GeotagFromBlackVue(GeotagFromGeneric):
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
        all_descs: T.List[types.ImageDescriptionFileOrError] = []

        for video_path in self.video_paths:
            LOG.debug("Processing BlackVue video: %s", video_path)

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

            points = blackvue_parser.parse_gps_points(video_path)

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
                            "Stationary BlackVue video"
                        ),
                        str(image_path),
                    )
                    all_descs.append(err_desc)
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
                this_descs = geotag.to_description()
                all_descs.extend(this_descs)

            # update make and model
            with video_path.open("rb") as fp:
                make, model = "BlackVue", blackvue_parser.extract_camera_model(fp)
            LOG.debug(f'Found camera make "%s" and model "%s"', make, model)
            for desc in types.filter_out_errors(this_descs):
                if make:
                    desc["MAPDeviceMake"] = make
                if model:
                    desc["MAPDeviceModel"] = model

        return all_descs
