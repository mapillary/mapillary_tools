# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import bisect
import dataclasses
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import geo, types, utils
from .base import GeotagImagesFromGeneric
from .geotag_images_from_gpx import GeotagImagesFromGPX
from .geotag_videos_from_video import GeotagVideosFromVideo
from .video_extractors.gpx import GPXVideoExtractor


LOG = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class GPSTimeline:
    """
    The Unix time of the video's GPS clock along the video: interpolated
    between its GPS timestamps, and extrapolated beyond them at the clock's
    rate. A timelapse captured its frames at those times, which one rate from
    one of them does not follow: the rate drifts from them over the video, and
    the first timestamp of a GoPro MAX timelapse can be seconds early.

    >>> timeline = GPSTimeline((0.0, 1.0, 2.0), (100.0, 104.0, 114.0), rate=10.0)
    >>> timeline.to_unix_time(0.5)
    102.0
    >>> timeline.to_unix_time(3.0)
    124.0
    """

    video_times: tuple[float, ...]
    unix_times: tuple[float, ...]
    # GPS seconds per video second beyond the timestamps
    rate: float

    @classmethod
    def read(cls, points: T.Sequence[geo.Point], rate: float) -> GPSTimeline | None:
        """
        Read the timeline from the GPS timestamps of the points, or None if they
        have none
        """
        pairs: list[tuple[float, float]] = []
        for p in points:
            unix_time = p.get_unix_time()
            if unix_time is None:
                continue
            if pairs and unix_time == pairs[-1][1]:
                # GoPro GPS5 stamps a whole block (~1s) of points with one
                # timestamp. Keep the first point of the block
                continue
            pairs.append((p.time, unix_time))

        if not pairs:
            return None

        return cls(
            video_times=tuple(v for v, _ in pairs),
            unix_times=tuple(u for _, u in pairs),
            rate=rate,
        )

    def to_unix_time(self, video_time: float) -> float:
        idx = bisect.bisect_right(self.video_times, video_time)
        if 0 < idx < len(self.video_times):
            v0, v1 = self.video_times[idx - 1], self.video_times[idx]
            u0, u1 = self.unix_times[idx - 1], self.unix_times[idx]
            return u0 + (u1 - u0) * (video_time - v0) / (v1 - v0)

        # Before the first timestamp or after the last
        anchor = 0 if idx == 0 else -1
        return (
            self.unix_times[anchor]
            + (video_time - self.video_times[anchor]) * self.rate
        )


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
            )

            image_metadatas = geotag.to_description(image_paths)

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
        like the samples, which are stamped with their capture times. A
        timelapse packs several into each second of video, as many as its GPS
        timestamps tell.
        """
        clock = GPXVideoExtractor._read_video_clock(points)
        if clock is None or clock.rate == 1.0:
            return points

        timeline = GPSTimeline.read(points, clock.rate)
        assert timeline is not None, "a GPS clock is read from GPS timestamps"
        start = timeline.to_unix_time(0.0)
        return [
            dataclasses.replace(p, time=timeline.to_unix_time(p.time) - start)
            for p in points
        ]


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
