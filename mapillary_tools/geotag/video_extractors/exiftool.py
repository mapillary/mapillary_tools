# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import logging
import sys
import typing as T
from pathlib import Path
from xml.etree import ElementTree as ET

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import constants, exceptions, exiftool_read_video, geo, telemetry, types, utils
from ...gpmf import gpmf_gps_filter
from .base import BaseVideoExtractor
from .gpx import describe_long_track


LOG = logging.getLogger(__name__)


class VideoExifToolExtractor(BaseVideoExtractor):
    def __init__(
        self, video_path: Path, element: ET.Element, track_path: Path | None = None
    ):
        super().__init__(video_path)
        self.element = element
        # The file that the metadata was read from, when it is not the video,
        # such as the original that a stitched video was made from
        self.track_path = track_path

    @override
    def extract(self) -> types.VideoMetadata:
        exif = exiftool_read_video.ExifToolReadVideo(ET.ElementTree(self.element))

        make = exif.extract_make()
        model = exif.extract_model()
        camera_uuid = exif.extract_camera_uuid()

        is_gopro = make is not None and make.upper() in ["GOPRO"]

        points = exif.extract_gps_track()

        if exif.far_gps_points:
            self._warn_of_far_points(len(exif.far_gps_points), len(points))

        # ExifTool has no idea if GPS is not found or found but empty
        if is_gopro:
            if not points:
                raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

            # ExifTool (since 13.04) converts GPSSpeed for GoPro to km/h, so here we convert it back to m/s
            for p in points:
                if isinstance(p, telemetry.GPSPoint) and p.ground_speed is not None:
                    p.ground_speed = p.ground_speed / 3.6

            if isinstance(points[0], telemetry.GPSPoint):
                points = T.cast(
                    T.List[geo.Point],
                    gpmf_gps_filter.remove_noisy_points(
                        T.cast(T.List[telemetry.GPSPoint], points)
                    ),
                )
                if not points:
                    raise exceptions.MapillaryGPSNoiseError("GPS is too noisy")

        if not points:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        if self.track_path is not None:
            self._warn_of_a_long_track(points)

        filetype = types.FileType.GOPRO if is_gopro else types.FileType.VIDEO

        video_metadata = types.VideoMetadata(
            self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=filetype,
            points=points,
            make=make,
            model=model,
            camera_uuid=camera_uuid,
        )

        return video_metadata

    def _warn_of_far_points(self, far_count: int, kept_count: int) -> None:
        LOG.warning(
            "%d GPS %s of %s %s left out: %s more than %g s from those of the other %s",
            far_count,
            "point" if far_count == 1 else "points",
            self.video_path.name,
            "was" if far_count == 1 else "were",
            "its GPS timestamp is" if far_count == 1 else "their GPS timestamps are",
            constants.MAX_GPX_GAP_SECONDS,
            "point" if kept_count == 1 else f"{kept_count} points",
        )

    def _warn_of_a_long_track(self, points: T.Sequence[geo.Point]) -> None:
        """
        Warn of a track read from another file that runs on for longer than
        the whole video, as process warns of a GPX track assumed to start with
        the video: the video could start anywhere along it. Only warn, since
        the track of a timelapse runs on past the end of the video too.
        """
        track = describe_long_track(
            f"The GPS track in {self.track_path}", points, self.video_path
        )
        if track is None:
            return
        LOG.warning(
            f"{track}, and is assumed to start with it. Unless the video is a "
            "timelapse of the whole track, check that the exiftool_runtime pattern "
            "names the file that the video was made from"
        )
