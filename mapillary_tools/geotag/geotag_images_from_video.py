from __future__ import annotations

import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import types, utils
from .base import GeotagImagesFromGeneric
from .geotag_images_from_gpx import GeotagImagesFromGPX


LOG = logging.getLogger(__name__)


class GeotagImagesFromVideo(GeotagImagesFromGeneric):
    def __init__(
        self,
        video_metadatas: T.Sequence[types.VideoMetadataOrError],
        offset_time: float = 0.0,
        num_processes: int | None = None,
    ):
        super().__init__(num_processes=num_processes)
        self.video_metadatas = video_metadatas
        self.offset_time = offset_time

    @override
    def to_description(
        self, image_paths: T.Sequence[Path]
    ) -> list[types.ImageMetadataOrError]:
        # Will return this list
        final_image_metadatas: list[types.ImageMetadataOrError] = []

        video_metadatas, video_error_metadatas = types.separate_errors(
            self.video_metadatas
        )

        for video_error_metadata in video_error_metadatas:
            video_path = video_error_metadata.filename
            sample_paths = list(utils.filter_video_samples(image_paths, video_path))
            LOG.debug(
                "Found %d sample images from video %s with error: %s",
                len(sample_paths),
                video_path,
                video_error_metadata.error,
            )
            for sample_path in sample_paths:
                image_error_metadata = types.describe_error_metadata(
                    video_error_metadata.error,
                    sample_path,
                    filetype=types.FileType.IMAGE,
                )
                final_image_metadatas.append(image_error_metadata)

        for video_metadata in video_metadatas:
            video_path = video_metadata.filename

            sample_paths = list(utils.filter_video_samples(image_paths, video_path))
            LOG.debug(
                "Found %d sample images from video %s",
                len(sample_paths),
                video_path,
            )

            geotag = GeotagImagesFromGPX(
                video_metadata.points,
                use_gpx_start_time=False,
                use_image_start_time=True,
                offset_time=self.offset_time,
                num_processes=self.num_processes,
            )

            image_metadatas = geotag.to_description(image_paths)

            for metadata in image_metadatas:
                if isinstance(metadata, types.ImageMetadata):
                    metadata.MAPDeviceMake = video_metadata.make
                    metadata.MAPDeviceModel = video_metadata.model

            final_image_metadatas.extend(image_metadatas)

        # NOTE: this method only geotags images that have a corresponding video,
        # so the number of image metadata objects returned might be less than
        # the number of the input image_paths
        assert len(final_image_metadatas) <= len(image_paths)

        return final_image_metadatas
