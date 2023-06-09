import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import types, utils
from . import geotag_videos_from_video
from .geotag_from_generic import GeotagImagesFromGeneric
from .geotag_images_from_gpx import GeotagFromGPXWithProgress


LOG = logging.getLogger(__name__)


class GeotagFromGoPro(GeotagImagesFromGeneric):
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
            LOG.debug("Processing GoPro video: %s", video_path)

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

            video_metadata = geotag_videos_from_video.GeotagFromVideo.geotag_video(
                video_path, filetypes={types.FileType.GOPRO}
            )

            if isinstance(video_metadata, types.ErrorMetadata):
                for image_path in sample_image_paths:
                    err_metadata = types.describe_error_metadata(
                        video_metadata.error,
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
                    video_metadata.points,
                    use_gpx_start_time=False,
                    use_image_start_time=True,
                    offset_time=self.offset_time,
                    progress_bar=pbar,
                )
                this_metadatas = geotag.to_description()
                all_metadatas.extend(this_metadatas)

            # update make and model
            LOG.debug(
                'Found camera make "%s" and model "%s"',
                video_metadata.make,
                video_metadata.model,
            )
            for metadata in this_metadatas:
                if isinstance(metadata, types.ImageMetadata):
                    metadata.MAPDeviceMake = video_metadata.make
                    metadata.MAPDeviceModel = video_metadata.model

        return all_metadatas
