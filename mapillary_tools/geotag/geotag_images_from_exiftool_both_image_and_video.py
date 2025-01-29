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
        num_processes: T.Optional[int] = None,
    ):
        self.image_paths = image_paths
        self.xml_path = xml_path
        self.offset_time = offset_time
        self.num_processes = num_processes
        super().__init__()

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        # will return this list
        final_image_metadatas: T.List[types.ImageMetadataOrError] = []

        # find the images that can be geotagged from EXIF
        image_metadatas_from_exiftool = (
            geotag_images_from_exiftool.GeotagImagesFromExifTool(
                self.image_paths,
                self.xml_path,
                num_processes=self.num_processes,
            ).to_description()
        )

        # find all video paths in self.xml_path
        rdf_description_by_path = exiftool_read.index_rdf_description_by_path(
            [self.xml_path]
        )
        video_paths = utils.find_videos(
            [Path(pathstr) for pathstr in rdf_description_by_path.keys()],
            skip_subfolders=True,
        )

        # will try to geotag these error metadatas from video later
        error_metadata_by_image_path = {}
        for image_metadata in image_metadatas_from_exiftool:
            if isinstance(image_metadata, types.ErrorMetadata):
                error_metadata_by_image_path[image_metadata.filename] = image_metadata
            else:
                final_image_metadatas.append(image_metadata)

        maybe_image_samples = list(error_metadata_by_image_path.keys())

        # find all video paths that have sample images
        video_paths_with_image_samples = list(
            utils.find_all_image_samples(maybe_image_samples, video_paths).keys()
        )

        video_metadatas = (
            geotag_videos_from_exiftool_video.GeotagVideosFromExifToolVideo(
                video_paths_with_image_samples,
                self.xml_path,
                num_processes=self.num_processes,
            ).to_description()
        )

        image_metadatas_from_video = geotag_images_from_video.GeotagImagesFromVideo(
            maybe_image_samples,
            video_metadatas,
            offset_time=self.offset_time,
            num_processes=self.num_processes,
        ).to_description()
        final_image_metadatas.extend(image_metadatas_from_video)

        # add back error metadatas that can not be geotagged at all
        actual_image_sample_paths = set(
            image_metadata.filename for image_metadata in image_metadatas_from_video
        )
        for path, error_metadata in error_metadata_by_image_path.items():
            if path not in actual_image_sample_paths:
                final_image_metadatas.append(error_metadata)

        assert len(final_image_metadatas) <= len(self.image_paths)
        return final_image_metadatas
