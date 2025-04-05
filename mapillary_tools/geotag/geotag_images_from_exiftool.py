from __future__ import annotations

import logging
import sys
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import constants, exceptions, exiftool_read, types, utils
from ..exiftool_runner import ExiftoolRunner
from .base import GeotagImagesFromGeneric
from .geotag_images_from_video import GeotagImagesFromVideo
from .geotag_videos_from_exiftool import GeotagVideosFromExifToolXML
from .image_extractors.exiftool import ImageExifToolExtractor

LOG = logging.getLogger(__name__)


class GeotagImagesFromExifToolXML(GeotagImagesFromGeneric):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        xml_path: Path,
        num_processes: int | None = None,
    ):
        self.xml_path = xml_path
        super().__init__(image_paths=image_paths, num_processes=num_processes)

    @override
    def _generate_image_extractors(
        self,
    ) -> T.Sequence[ImageExifToolExtractor | types.ErrorMetadata]:
        rdf_description_by_path = exiftool_read.index_rdf_description_by_path(
            [self.xml_path]
        )

        results: list[ImageExifToolExtractor | types.ErrorMetadata] = []

        for path in self.image_paths:
            rdf_description = rdf_description_by_path.get(
                exiftool_read.canonical_path(path)
            )
            if rdf_description is None:
                exc = exceptions.MapillaryEXIFNotFoundError(
                    f"The {exiftool_read._DESCRIPTION_TAG} XML element for the image not found"
                )
                results.append(
                    types.describe_error_metadata(
                        exc, path, filetype=types.FileType.IMAGE
                    )
                )
            else:
                results.append(ImageExifToolExtractor(path, rdf_description))

        return results


class GeotagImagesFromExifToolRunner(GeotagImagesFromGeneric):
    @override
    def _generate_image_extractors(
        self,
    ) -> T.Sequence[ImageExifToolExtractor | types.ErrorMetadata]:
        runner = ExiftoolRunner(constants.EXIFTOOL_PATH)

        LOG.debug(
            "Extracting XML from %d images with exiftool command: %s",
            len(self.image_paths),
            " ".join(runner._build_args_read_stdin()),
        )
        try:
            xml = runner.extract_xml(self.image_paths)
        except FileNotFoundError as ex:
            raise exceptions.MapillaryExiftoolNotFoundError(ex) from ex

        rdf_description_by_path = (
            exiftool_read.index_rdf_description_by_path_from_xml_element(
                ET.fromstring(xml)
            )
        )

        results: list[ImageExifToolExtractor | types.ErrorMetadata] = []

        for path in self.image_paths:
            rdf_description = rdf_description_by_path.get(
                exiftool_read.canonical_path(path)
            )
            if rdf_description is None:
                exc = exceptions.MapillaryEXIFNotFoundError(
                    f"The {exiftool_read._DESCRIPTION_TAG} XML element for the image not found"
                )
                results.append(
                    types.describe_error_metadata(
                        exc, path, filetype=types.FileType.IMAGE
                    )
                )
            else:
                results.append(ImageExifToolExtractor(path, rdf_description))

        return results


class GeotagImagesFromExifToolWithSamples(GeotagImagesFromGeneric):
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

        video_metadata_or_errors = GeotagVideosFromExifToolXML(
            list(samples_by_video.keys()),
            self.xml_path,
            num_processes=self.num_processes,
        ).to_description()
        sample_paths = sum(samples_by_video.values(), [])
        sample_metadata_or_errors = GeotagImagesFromVideo(
            sample_paths,
            video_metadata_or_errors,
            offset_time=self.offset_time,
            num_processes=self.num_processes,
        ).to_description()

        return sample_metadata_or_errors

    @override
    def to_description(self) -> list[types.ImageMetadataOrError]:
        sample_metadata_or_errors = self.geotag_samples()

        sample_paths = set(metadata.filename for metadata in sample_metadata_or_errors)

        non_sample_paths = [
            path for path in self.image_paths if path not in sample_paths
        ]

        non_sample_metadata_or_errors = GeotagImagesFromExifToolXML(
            non_sample_paths,
            self.xml_path,
            num_processes=self.num_processes,
        ).to_description()

        return sample_metadata_or_errors + non_sample_metadata_or_errors
