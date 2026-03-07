# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import datetime
import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import blackvue_parser, exceptions, geo, telemetry, types, utils
from ...camm import camm_parser
from ...gpmf import gpmf_gps_filter, gpmf_parser
from ...mp4 import construct_mp4_parser, simple_mp4_parser
from .base import BaseVideoExtractor

LOG = logging.getLogger(__name__)


class GoProVideoExtractor(BaseVideoExtractor):
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

        gps_points = T.cast(
            T.List[telemetry.GPSPoint], gpmf_gps_filter.remove_noisy_points(gps_points)
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

        points: T.List[geo.Point]
        if camm_info.gps:
            points = T.cast(T.List[geo.Point], camm_info.gps)
        elif camm_info.mini_gps and camm_info.gps_datetime:
            # Type 5 points have no epoch timestamps, but the RMKN
            # maker note contains a GPS-derived UTC timestamp for the
            # first point. Use it to assign epoch times to all points.
            points = self._enrich_with_gps_datetime(
                camm_info.mini_gps, camm_info.gps_datetime
            )
        else:
            points = camm_info.mini_gps or []

        return types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=types.FileType.CAMM,
            points=points,
            make=camm_info.make,
            model=camm_info.model,
        )

    @staticmethod
    def _enrich_with_gps_datetime(
        points: T.List[geo.Point],
        gps_datetime: "datetime.datetime",
    ) -> T.List[geo.Point]:
        """Assign GPS epoch timestamps to Type 5 points using an RMKN reference.

        The gps_datetime (from the RMKN maker note) is a GPS-derived UTC
        timestamp corresponding to the first CAMM Type 5 GPS point.
        Each subsequent point's epoch is computed as:

            epoch = gps_epoch + (point.time - first_point.time)
        """

        if not points:
            return points

        gps_epoch = gps_datetime.timestamp()
        first_time = points[0].time

        LOG.info(
            "Enriching %d CAMM Type 5 points with GPS epoch from RMKN timestamp %s",
            len(points),
            gps_datetime.isoformat(),
        )

        enriched: T.List[geo.Point] = []
        for p in points:
            enriched.append(
                telemetry.CAMMGPSPoint(
                    time=p.time,
                    lat=p.lat,
                    lon=p.lon,
                    alt=p.alt,
                    angle=p.angle,
                    time_gps_epoch=gps_epoch + (p.time - first_time),
                    gps_fix_type=3 if p.alt is not None else 2,
                    horizontal_accuracy=0.0,
                    vertical_accuracy=0.0,
                    velocity_east=0.0,
                    velocity_north=0.0,
                    velocity_up=0.0,
                    speed_accuracy=0.0,
                )
            )
        return enriched


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


class NativeVideoExtractor(BaseVideoExtractor):
    def __init__(self, video_path: Path, filetypes: set[types.FileType] | None = None):
        super().__init__(video_path)
        self.filetypes = filetypes

    @override
    def extract(self) -> types.VideoMetadata:
        ft = self.filetypes
        extractor: BaseVideoExtractor

        if ft is None or types.FileType.VIDEO in ft or types.FileType.GOPRO in ft:
            extractor = GoProVideoExtractor(self.video_path)
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

        raise exceptions.MapillaryVideoGPSNotFoundError(
            "No GPS data found from the video"
        )
