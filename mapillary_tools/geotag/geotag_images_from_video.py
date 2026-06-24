# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

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
from ..gpmf import gps_smoother, gps_weigher
from .base import GeotagImagesFromGeneric
from .geotag_images_from_gpx import GeotagImagesFromGPX
from .geotag_videos_from_video import GeotagVideosFromVideo


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

            # If weighted points available, refine positions with weighted median
            has_weights = (
                video_metadata.point_weights is not None
                and video_metadata.point_sigma_xys is not None
            )
            if has_weights:
                _apply_weighted_interpolation(
                    image_metadatas,
                    video_metadata,
                )

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
        return geotag.to_description(image_paths)


def _apply_weighted_interpolation(
    image_metadatas: list[types.ImageMetadataOrError],
    video_metadata: types.VideoMetadata,
) -> None:
    """Refine image positions using weighted median interpolation.

    Modifies ImageMetadata objects in-place: updates lat, lon, and sets
    MAPGPSAccuracyMeters.

    The image metadata times are in image-EXIF time (absolute), but the
    video points are in video-relative time (0 to duration). GeotagImagesFromGPX
    shifts video points by adding the first image's time. We apply the same
    shift here so the query times align.
    """
    assert video_metadata.point_weights is not None
    assert video_metadata.point_sigma_xys is not None

    # Frame-sampling path only: smooth the GPS track (speed-gate + sigma-weighted
    # Kalman/RTS) before interpolating image positions. Falls back to the raw points
    # if numpy is unavailable. NOTE: this does NOT touch the native CAMM muxing path,
    # which still muxes the unsmoothed track (see PR description).
    points = gps_smoother.smooth_gps_points(video_metadata.points)
    weights = video_metadata.point_weights
    sigma_xys = video_metadata.point_sigma_xys

    # Find the time shift: first image time = offset added to video-relative times
    valid_images = [m for m in image_metadatas if isinstance(m, types.ImageMetadata)]
    if not valid_images:
        return
    first_image_time = min(m.time for m in valid_images)

    # Shift video point times to match image time frame
    times = [first_image_time + p.time for p in points]
    lats = [p.lat for p in points]
    lons = [p.lon for p in points]

    for metadata in valid_images:
        lat, lon, accuracy = gps_weigher.weighted_interpolate(
            metadata.time,
            times,
            lats,
            lons,
            weights,
            sigma_xys,
        )
        metadata.lat = lat
        metadata.lon = lon
        metadata.MAPGPSAccuracyMeters = round(accuracy, 2)
