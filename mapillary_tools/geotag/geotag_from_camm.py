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

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        all_metadatas: T.List[types.ImageMetadataOrError] = []
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
                    err_metadata = types.describe_error_metadata(
                        exceptions.MapillaryStationaryVideoError(
                            "Stationary CAMM video"
                        ),
                        image_path,
                        filetype=types.FileType.IMAGE,
                    )
                    all_metadatas.append(err_metadata)
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
                this_metadatas = geotag.to_description()
                all_metadatas.extend(this_metadatas)

            # update make and model
            with video_path.open("rb") as fp:
                make, model = camm_parser.extract_camera_make_and_model(fp)
            LOG.debug('Found camera make "%s" and model "%s"', make, model)

            for metadata in this_metadatas:
                if isinstance(metadata, types.ImageMetadata):
                    metadata.MAPDeviceMake = make
                    metadata.MAPDeviceModel = model

        return all_metadatas
