import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import types, utils

from .geotag_from_generic import GeotagImagesFromGeneric
from .geotag_images_from_gpx import GeotagImagesFromGPXWithProgress


LOG = logging.getLogger(__name__)


class GeotagImagesFromVideo(GeotagImagesFromGeneric):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        video_metadatas: T.Sequence[types.VideoMetadataOrError],
        offset_time: float = 0.0,
        num_processes: T.Optional[int] = None,
    ):
        self.image_paths = image_paths
        self.video_metadatas = video_metadatas
        self.offset_time = offset_time
        self.num_processes = num_processes
        super().__init__()

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        # will return this list
        final_image_metadatas: T.List[types.ImageMetadataOrError] = []

        for video_metadata in self.video_metadatas:
            video_path = video_metadata.filename
            LOG.debug("Processing video: %s", video_path)

            sample_image_paths = list(
                utils.filter_video_samples(self.image_paths, video_path)
            )
            LOG.debug(
                "Found %d sample images from video %s",
                len(sample_image_paths),
                video_path,
            )

            if isinstance(video_metadata, types.ErrorMetadata):
                for sample_image_path in sample_image_paths:
                    error_metadata = types.describe_error_metadata(
                        video_metadata.error,
                        sample_image_path,
                        filetype=types.FileType.IMAGE,
                    )
                    final_image_metadatas.append(error_metadata)
                continue

            with tqdm(
                total=len(sample_image_paths),
                desc=f"Interpolating {video_path.name}",
                unit="images",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
            ) as pbar:
                image_metadatas = GeotagImagesFromGPXWithProgress(
                    sample_image_paths,
                    video_metadata.points,
                    use_gpx_start_time=False,
                    use_image_start_time=True,
                    offset_time=self.offset_time,
                    num_processes=self.num_processes,
                    progress_bar=pbar,
                ).to_description()
                final_image_metadatas.extend(image_metadatas)

            # update make and model
            LOG.debug(
                'Found camera make "%s" and model "%s"',
                video_metadata.make,
                video_metadata.model,
            )
            for metadata in image_metadatas:
                if isinstance(metadata, types.ImageMetadata):
                    metadata.MAPDeviceMake = video_metadata.make
                    metadata.MAPDeviceModel = video_metadata.model

        # NOTE: this method only geotags images that have a corresponding video,
        # so the number of image metadata objects returned might be less than
        # the number of the input image_paths
        assert len(final_image_metadatas) <= len(self.image_paths)

        return final_image_metadatas
