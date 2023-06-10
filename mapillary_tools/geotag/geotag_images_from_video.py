import logging
import typing as T
from pathlib import Path

from tqdm import tqdm

from .. import types, utils
from . import geotag_videos_from_video
from .geotag_from_generic import GeotagImagesFromGeneric
from .geotag_images_from_gpx import GeotagImagesFromGPXWithProgress


LOG = logging.getLogger(__name__)


class GeotagImagesFromVideo(GeotagImagesFromGeneric):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        video_paths: T.Sequence[Path],
        filetypes: T.Optional[T.Set[types.FileType]] = None,
        offset_time: float = 0.0,
    ):
        self.image_paths = image_paths
        self.video_paths = video_paths
        self.filetypes = filetypes
        self.offset_time = offset_time
        super().__init__()

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        # find videos that have sample images
        # TODO: this is a bit inefficient O(M*N) where M is the number of videos and N is the number of images
        video_paths = [
            video_path
            for video_path in self.video_paths
            if list(utils.filter_video_samples(self.image_paths, video_path))
        ]

        geotag_videos = geotag_videos_from_video.GeotagVideosFromVideo(
            video_paths, filetypes=self.filetypes
        )
        video_metadatas = geotag_videos.to_description()
        assert len(video_metadatas) == len(video_paths)

        all_image_metadatas: T.List[types.ImageMetadataOrError] = []

        for video_path, video_metadata in zip(video_paths, video_metadatas):
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
                    err_metadata = types.describe_error_metadata(
                        video_metadata.error,
                        sample_image_path,
                        filetype=types.FileType.IMAGE,
                    )
                    all_image_metadatas.append(err_metadata)
                continue

            with tqdm(
                total=len(sample_image_paths),
                desc=f"Interpolating {video_path.name}",
                unit="images",
                disable=LOG.getEffectiveLevel() <= logging.DEBUG,
            ) as pbar:
                geotag = GeotagImagesFromGPXWithProgress(
                    sample_image_paths,
                    video_metadata.points,
                    use_gpx_start_time=False,
                    use_image_start_time=True,
                    offset_time=self.offset_time,
                    progress_bar=pbar,
                )
                this_metadatas = geotag.to_description()
                all_image_metadatas.extend(this_metadatas)

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

        # NOTE: this method only geotags images that have a corresponding video,
        # so the number of image metadata objects returned might be less than
        # the number of the input image_paths
        assert len(all_image_metadatas) <= len(self.image_paths)

        return all_image_metadatas
