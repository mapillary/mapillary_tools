from __future__ import annotations

import logging
import typing as T
from pathlib import Path

from .. import exiftool_read, types, utils
from . import (
    geotag_images_from_exiftool,
    geotag_images_from_video,
    geotag_videos_from_exiftool_video,
)
from .geotag_from_generic import GeotagImagesFromGeneric


LOG = logging.getLogger(__name__)


class GeotagImagesFromExifToolBothImageAndVideo(GeotagImagesFromGeneric):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        xml_path: Path,
        offset_time: float = 0.0,
        num_processes: int | None = None,
    ):
        super().__init__(image_paths, num_processes=num_processes)
        self.xml_path = xml_path
        self.offset_time = offset_time

    def geotag_samples(self) -> list[types.ImageMetadataOrError]:
        # Find all video paths in self.xml_path
        rdf_description_by_path = exiftool_read.index_rdf_description_by_path(
            [self.xml_path]
        )
        video_paths = utils.find_videos(
            [Path(pathstr) for pathstr in rdf_description_by_path.keys()],
            skip_subfolders=True,
        )
        # Find all video paths that have sample images
        samples_by_video = utils.find_all_image_samples(self.image_paths, video_paths)

        video_metadata_or_errors = (
            geotag_videos_from_exiftool_video.GeotagVideosFromExifToolVideo(
                list(samples_by_video.keys()),
                self.xml_path,
                num_processes=self.num_processes,
            ).to_description()
        )
        sample_paths = sum(samples_by_video.values(), [])
        sample_metadata_or_errors = geotag_images_from_video.GeotagImagesFromVideo(
            sample_paths,
            video_metadata_or_errors,
            offset_time=self.offset_time,
            num_processes=self.num_processes,
        ).to_description()

        return sample_metadata_or_errors

    def to_description(self) -> list[types.ImageMetadataOrError]:
        sample_metadata_or_errors = self.geotag_samples()

        sample_paths = set(metadata.filename for metadata in sample_metadata_or_errors)

        non_sample_paths = [
            path for path in self.image_paths if path not in sample_paths
        ]

        non_sample_metadata_or_errors = (
            geotag_images_from_exiftool.GeotagImagesFromExifTool(
                non_sample_paths,
                self.xml_path,
                num_processes=self.num_processes,
            ).to_description()
        )

        return sample_metadata_or_errors + non_sample_metadata_or_errors
