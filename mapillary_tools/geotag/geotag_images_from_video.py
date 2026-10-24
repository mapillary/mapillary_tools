# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import dataclasses
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import exceptions, geo, types, utils
from .base import GeotagImagesFromGeneric
from .geotag_images_from_gpx import GeotagImagesFromGPX
from .geotag_videos_from_video import GeotagVideosFromVideo
from .video_extractors.gpx import GPXVideoExtractor


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
                self._on_capture_timeline(video_metadata.points),
                use_gpx_start_time=False,
                use_image_start_time=True,
                offset_time=self.offset_time,
                num_processes=self.num_processes,
                # Gaps between trips are those of a GPX file, not of the
                # video's own track
                check_gaps=False,
            )

            image_metadatas = geotag.to_description(sample_paths)

            for metadata in image_metadatas:
                if isinstance(metadata, types.ImageMetadata):
                    metadata.MAPDeviceMake = video_metadata.make
                    metadata.MAPDeviceModel = video_metadata.model
                    metadata.MAPCameraUUID = video_metadata.camera_uuid

            final_image_metadatas.extend(image_metadatas)

        # NOTE: this method only geotags images that have a corresponding video,
        # so the number of image metadata objects returned might be less than
        # the number of the input image_paths
        assert len(final_image_metadatas) <= len(image_paths)

        return final_image_metadatas

    @classmethod
    def _on_capture_timeline(
        cls, points: T.Sequence[geo.Point]
    ) -> T.Sequence[geo.Point]:
        """
        Time the video's GPS points in GPS seconds from the start of the video,
        like the samples, which are stamped with their capture times, at the
        pace of its GPS clock: a timelapse packs several into each second of
        video, and some clocks gain on the video.
        """
        clock = GPXVideoExtractor._read_video_clock(points)
        if clock is None or clock.rate == 1.0:
            return points

        return [dataclasses.replace(p, time=p.time * clock.rate) for p in points]


class GeotagImageSamplesFromVideo(GeotagImagesFromGeneric):
    def __init__(
        self,
        source_path: Path,
        filetypes: set[types.FileType] | None = None,
        offset_time: float = 0.0,
        num_processes: int | None = None,
    ):
        super().__init__(num_processes=num_processes)
        self.source_path = source_path
        self.filetypes = filetypes
        self.offset_time = offset_time

    @override
    def to_description(
        self, image_paths: T.Sequence[Path]
    ) -> list[types.ImageMetadataOrError]:
        video_paths = utils.find_videos([self.source_path])
        image_samples_by_video_path = utils.find_all_image_samples(
            image_paths, video_paths
        )
        video_paths_with_image_samples = list(image_samples_by_video_path.keys())
        video_metadatas = GeotagVideosFromVideo(
            filetypes=self.filetypes,
            num_processes=self.num_processes,
        ).to_description(video_paths_with_image_samples)
        geotag = GeotagImagesFromVideo(
            video_metadatas,
            offset_time=self.offset_time,
            num_processes=self.num_processes,
        )
        sample_metadatas = geotag.to_description(image_paths)

        # An image that is not a frame of any of the videos has no position
        # here. Say so, rather than leave it out of the results, as a source
        # that can geotag it (e.g. exif after this one) may still do
        sample_paths = {metadata.filename for metadata in sample_metadatas}
        return sample_metadatas + [
            types.describe_error_metadata(
                exceptions.MapillaryGeoTaggingError(
                    f"Not a frame of any video in {self.source_path}"
                ),
                image_path,
                filetype=types.FileType.IMAGE,
            )
            for image_path in image_paths
            if image_path not in sample_paths
        ]
