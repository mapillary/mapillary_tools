# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

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
from . import options
from .base import GeotagImagesFromGeneric
from .geotag_images_from_video import describe_ambiguous_sample, GeotagImagesFromVideo
from .geotag_videos_from_exiftool import GeotagVideosFromExifToolXML
from .image_extractors.exiftool import ImageExifToolExtractor

LOG = logging.getLogger(__name__)


class GeotagImagesFromExifToolXML(GeotagImagesFromGeneric):
    def __init__(
        self, source_path: options.SourcePathOption, num_processes: int | None = None
    ):
        self.source_path = source_path
        super().__init__(num_processes=num_processes)

    @classmethod
    def build_image_extractors(
        cls, rdf_by_path: dict[str, ET.Element], image_paths: T.Iterable[Path]
    ) -> list[ImageExifToolExtractor | types.ErrorMetadata]:
        results: list[ImageExifToolExtractor | types.ErrorMetadata] = []

        for path in image_paths:
            rdf = rdf_by_path.get(exiftool_read.canonical_path(path))
            if rdf is None:
                ex = exceptions.MapillaryExifToolXMLNotFoundError(
                    "Cannot find the image in the ExifTool XML"
                )
                results.append(
                    types.describe_error_metadata(
                        ex, path, filetype=types.FileType.IMAGE
                    )
                )
            else:
                results.append(ImageExifToolExtractor(path, rdf))

        return results

    @override
    def _generate_image_extractors(
        self, image_paths: T.Sequence[Path]
    ) -> T.Sequence[ImageExifToolExtractor | types.ErrorMetadata]:
        rdf_by_path = GeotagVideosFromExifToolXML.find_rdf_by_path(
            self.source_path, image_paths
        )
        return self.build_image_extractors(rdf_by_path, image_paths)


class GeotagImagesFromExifToolRunner(GeotagImagesFromGeneric):
    @override
    def _generate_image_extractors(
        self, image_paths: T.Sequence[Path]
    ) -> T.Sequence[ImageExifToolExtractor | types.ErrorMetadata]:
        if constants.EXIFTOOL_PATH is None:
            runner = ExiftoolRunner()
        else:
            runner = ExiftoolRunner(constants.EXIFTOOL_PATH)

        LOG.debug(
            "Extracting XML from %d images with ExifTool command: %s",
            len(image_paths),
            " ".join(runner._build_args_read_stdin()),
        )
        try:
            xml = runner.extract_xml(image_paths)
        except FileNotFoundError as ex:
            exiftool_ex = exceptions.MapillaryExiftoolNotFoundError(ex)
            return [
                types.describe_error_metadata(
                    exiftool_ex, image_path, filetype=types.FileType.IMAGE
                )
                for image_path in image_paths
            ]

        try:
            xml_element = ET.fromstring(xml)
        except ET.ParseError as ex:
            LOG.warning(
                "Failed to parse ExifTool XML: %s",
                str(ex),
                exc_info=LOG.isEnabledFor(logging.DEBUG),
            )
            rdf_by_path = {}
        else:
            rdf_by_path = exiftool_read.index_rdf_description_by_path_from_xml_element(
                xml_element
            )

        return GeotagImagesFromExifToolXML.build_image_extractors(
            rdf_by_path, image_paths
        )


class GeotagImagesFromExifToolWithSamples(GeotagImagesFromGeneric):
    def __init__(
        self,
        source_path: options.SourcePathOption,
        offset_time: float = 0.0,
        num_processes: int | None = None,
    ):
        super().__init__(num_processes=num_processes)
        self.source_path = source_path
        self.offset_time = offset_time

    def geotag_samples(
        self, image_paths: T.Sequence[Path]
    ) -> list[types.ImageMetadataOrError]:
        sample_metadata_or_errors = self._geotag_samples_by_pattern(image_paths)
        named_paths = set(metadata.filename for metadata in sample_metadata_or_errors)
        image_paths = [path for path in image_paths if path not in named_paths]

        # Find all video paths in self.xml_path
        rdf_by_path = GeotagVideosFromExifToolXML.find_rdf_by_path(
            self.source_path, image_paths
        )
        video_paths = utils.find_videos(
            [Path(canonical_path) for canonical_path in rdf_by_path.keys()],
            skip_subfolders=True,
        )

        return sample_metadata_or_errors + self._geotag_samples_of(
            image_paths, video_paths, self.source_path
        )

    def _geotag_samples_by_pattern(
        self, image_paths: T.Sequence[Path]
    ) -> list[types.ImageMetadataOrError]:
        """
        Geotag the samples of the videos whose XML the pattern names. A pattern
        names the XML of a video after the video, not after its samples: in
        video_process, given the video import path (a video or a directory of
        videos) as the source path, resolve it against the videos that the
        samples were taken from, found there. The source path would override
        the pattern otherwise, and read the video import path as the XML.
        """
        if self.source_path.pattern is None or self.source_path.source_path is None:
            return []

        pattern = options.SourcePathOption(pattern=self.source_path.pattern)
        video_paths = [
            video_path
            for video_path in utils.find_videos([self.source_path.source_path])
            if pattern.resolve(video_path).is_file()
        ]

        return self._geotag_samples_of(image_paths, video_paths, pattern)

    def _geotag_samples_of(
        self,
        image_paths: T.Sequence[Path],
        video_paths: T.Sequence[Path],
        source_path: options.SourcePathOption,
    ) -> list[types.ImageMetadataOrError]:
        # Find all video paths that have sample images
        samples_by_video, ambiguous_samples = utils.find_image_samples(
            image_paths, video_paths
        )

        video_metadata_or_errors = GeotagVideosFromExifToolXML(
            source_path, num_processes=self.num_processes
        ).to_description(list(samples_by_video.keys()))
        sample_paths = sum(samples_by_video.values(), [])
        sample_metadata_or_errors = GeotagImagesFromVideo(
            video_metadata_or_errors,
            offset_time=self.offset_time,
            num_processes=self.num_processes,
            samples_by_video=samples_by_video,
        ).to_description(sample_paths)

        return sample_metadata_or_errors + [
            describe_ambiguous_sample(image_path, candidates)
            for image_path, candidates in ambiguous_samples.items()
        ]

    @override
    def to_description(
        self, image_paths: T.Sequence[Path]
    ) -> list[types.ImageMetadataOrError]:
        sample_metadata_or_errors = self.geotag_samples(image_paths)

        sample_paths = set(metadata.filename for metadata in sample_metadata_or_errors)

        non_sample_paths = [path for path in image_paths if path not in sample_paths]

        non_sample_metadata_or_errors = GeotagImagesFromExifToolXML(
            self.source_path, num_processes=self.num_processes
        ).to_description(non_sample_paths)

        return sample_metadata_or_errors + non_sample_metadata_or_errors
