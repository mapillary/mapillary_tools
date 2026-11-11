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

from ... import (
    blackvue_parser,
    exceptions,
    geo,
    novatek_parser,
    telemetry,
    types,
    utils,
)
from ...camm import camm_parser
from ...gpmf import gpmf_gps_filter, gpmf_parser
from ...mp4 import construct_mp4_parser, simple_mp4_parser
from .base import BaseVideoExtractor

LOG = logging.getLogger(__name__)

# How far the first type 5 sample can be from the GPS fix in the RMKN box and
# still be that fix: the EXIF block rounds the position to 0.01 arc seconds,
# about 0.3 m
_MAX_RMKN_FIX_DISTANCE_METERS = 1.0


class GoProVideoExtractor(BaseVideoExtractor):
    def __init__(self, video_path: Path, filter_noisy_points: bool = True):
        super().__init__(video_path)
        # The noise filter is a quality gate on the track we are about to
        # publish. A caller that replaces the track (e.g. with a GPX) and only
        # needs the make/model and the GPS clock of the video passes False
        self.filter_noisy_points = filter_noisy_points

    @override
    def extract(self) -> types.VideoMetadata:
        with self.video_path.open("rb") as fp:
            gopro_info = gpmf_parser.extract_gopro_info(fp)

        if gopro_info is None:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        gps_points = gopro_info.gps
        assert gps_points is not None, "must have GPS data extracted"
        if not gps_points:
            raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

        if self.filter_noisy_points:
            gps_points = T.cast(
                T.List[telemetry.GPSPoint],
                gpmf_gps_filter.remove_noisy_points(gps_points),
            )
            if not gps_points:
                raise exceptions.MapillaryGPSNoiseError("GPS is too noisy")

        video_metadata = types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=types.FileType.GOPRO,
            points=T.cast(T.List[geo.Point], gps_points),
            make=gopro_info.make,
            model=gopro_info.model,
        )

        return video_metadata


class CAMMVideoExtractor(BaseVideoExtractor):
    @override
    def extract(self) -> types.VideoMetadata:
        with self.video_path.open("rb") as fp:
            camm_info = camm_parser.extract_camm_info(fp)

        if camm_info is None:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        if not camm_info.gps and not camm_info.mini_gps:
            raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

        mini_gps = camm_info.mini_gps or []
        if not camm_info.gps and camm_info.rmkn_gps_fix is not None:
            timestamped = self._timestamp_mini_gps(mini_gps, camm_info.rmkn_gps_fix)
            if timestamped is None:
                LOG.debug(
                    "The GPS fix in the RMKN box of %s is not its first GPS sample, so it does not date the track",
                    self.video_path.name,
                )
            else:
                mini_gps = timestamped

        # A track may mix type 6 and type 5 samples, so use both. No camera is
        # known to interleave them, and it would cost the absolute timestamps
        # of sampled frames: interpolating between the two types returns a
        # plain geo.Point (see CAMMGPSPoint.interpolate_with), so sample_video
        # falls back to the container start time.
        points: list[geo.Point] = [*(camm_info.gps or []), *mini_gps]
        points.sort(key=lambda p: p.time)

        return types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=types.FileType.CAMM,
            points=points,
            make=camm_info.make,
            model=camm_info.model,
        )

    @staticmethod
    def _timestamp_mini_gps(
        mini_gps: T.Sequence[geo.Point], rmkn_gps_fix: camm_parser.RMKNGPSFix
    ) -> list[geo.Point] | None:
        """
        Stamp type 5 samples, which have no timestamps, by the GPS fix in the
        RMKN box, which is the first of them: the time of the fix, plus each
        sample's time in the video after the first sample. None if the first
        sample is elsewhere than the fix, as then it is not that fix.

        The points are built as the description file decodes timestamped
        points, so that a video reads the same from either

        >>> fix = camm_parser.RMKNGPSFix(unix_time=1661576963.0, lat=1, lon=2)
        >>> first = geo.Point(time=0.875, lat=1, lon=2, alt=3, angle=None)
        >>> second = geo.Point(time=1.875, lat=1.00001, lon=2, alt=None, angle=None)
        >>> [p.epoch_time for p in CAMMVideoExtractor._timestamp_mini_gps([first, second], fix)]
        [1661576963.0, 1661576964.0]
        >>> CAMMVideoExtractor._timestamp_mini_gps([second], fix) is None
        True
        """
        if not mini_gps:
            return []

        first = min(mini_gps, key=lambda p: p.time)
        if (
            geo.gps_distance(
                (first.lat, first.lon), (rmkn_gps_fix.lat, rmkn_gps_fix.lon)
            )
            > _MAX_RMKN_FIX_DISTANCE_METERS
        ):
            return None

        return [
            telemetry.CAMMGPSPoint(
                time=p.time,
                lat=p.lat,
                lon=p.lon,
                alt=p.alt,
                angle=p.angle,
                epoch_time=rmkn_gps_fix.unix_time + (p.time - first.time),
                gps_fix_type=3 if p.alt is not None else 2,
                horizontal_accuracy=0.0,
                vertical_accuracy=0.0,
                velocity_east=0.0,
                velocity_north=0.0,
                velocity_up=0.0,
                speed_accuracy=0.0,
            )
            for p in mini_gps
        ]


class BlackVueVideoExtractor(BaseVideoExtractor):
    @override
    def extract(self) -> types.VideoMetadata:
        with self.video_path.open("rb") as fp:
            blackvue_info = blackvue_parser.extract_blackvue_info(fp)

        if blackvue_info is None:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        if not blackvue_info.gps:
            raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

        video_metadata = types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=types.FileType.BLACKVUE,
            points=blackvue_info.gps,
            make=blackvue_info.make,
            model=blackvue_info.model,
        )

        return video_metadata


class NovatekVideoExtractor(BaseVideoExtractor):
    @override
    def extract(self) -> types.VideoMetadata:
        with self.video_path.open("rb") as fp:
            points = novatek_parser.extract_points(fp)

        # Unsupported or empty GPS data is left to ExifTool
        if not points:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        return types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=types.FileType.VIDEO,
            points=T.cast(T.List[geo.Point], points),
        )


class NativeVideoExtractor(BaseVideoExtractor):
    def __init__(
        self,
        video_path: Path,
        filetypes: set[types.FileType] | None = None,
        filter_noisy_points: bool = True,
    ):
        super().__init__(video_path)
        self.filetypes = filetypes
        self.filter_noisy_points = filter_noisy_points

    @override
    def extract(self) -> types.VideoMetadata:
        ft = self.filetypes
        extractor: BaseVideoExtractor

        if ft is None or types.FileType.VIDEO in ft or types.FileType.GOPRO in ft:
            extractor = GoProVideoExtractor(
                self.video_path, filter_noisy_points=self.filter_noisy_points
            )
            try:
                return extractor.extract()
            except simple_mp4_parser.BoxNotFoundError as ex:
                raise exceptions.MapillaryInvalidVideoError(
                    f"Invalid video: {ex}"
                ) from ex
            except construct_mp4_parser.BoxNotFoundError as ex:
                raise exceptions.MapillaryInvalidVideoError(
                    f"Invalid video: {ex}"
                ) from ex
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        if ft is None or types.FileType.VIDEO in ft or types.FileType.CAMM in ft:
            extractor = CAMMVideoExtractor(self.video_path)
            try:
                return extractor.extract()
            except simple_mp4_parser.BoxNotFoundError as ex:
                raise exceptions.MapillaryInvalidVideoError(
                    f"Invalid video: {ex}"
                ) from ex
            except construct_mp4_parser.BoxNotFoundError as ex:
                raise exceptions.MapillaryInvalidVideoError(
                    f"Invalid video: {ex}"
                ) from ex
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        if ft is None or types.FileType.VIDEO in ft or types.FileType.BLACKVUE in ft:
            extractor = BlackVueVideoExtractor(self.video_path)
            try:
                return extractor.extract()
            except simple_mp4_parser.BoxNotFoundError as ex:
                raise exceptions.MapillaryInvalidVideoError(
                    f"Invalid video: {ex}"
                ) from ex
            except construct_mp4_parser.BoxNotFoundError as ex:
                raise exceptions.MapillaryInvalidVideoError(
                    f"Invalid video: {ex}"
                ) from ex
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        if ft is None or types.FileType.VIDEO in ft:
            extractor = NovatekVideoExtractor(self.video_path)
            try:
                return extractor.extract()
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        raise exceptions.MapillaryVideoGPSNotFoundError(
            "No GPS data found from the video"
        )
