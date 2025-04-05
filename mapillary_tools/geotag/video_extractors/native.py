from __future__ import annotations

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
from .base import BaseVideoExtractor


class GoProVideoExtractor(BaseVideoExtractor):
    @override
    def extract(self) -> types.VideoMetadataOrError:
        with self.video_path.open("rb") as fp:
            gopro_info = gpmf_parser.extract_gopro_info(fp)

        if gopro_info is None:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        gps_points = gopro_info.gps
        assert gps_points is not None, "must have GPS data extracted"
        if not gps_points:
            # Instead of raising an exception, return error metadata to tell the file type
            ex: exceptions.MapillaryDescriptionError = (
                exceptions.MapillaryGPXEmptyError("Empty GPS data found")
            )
            return types.describe_error_metadata(
                ex, self.video_path, filetype=types.FileType.GOPRO
            )

        gps_points = T.cast(
            T.List[telemetry.GPSPoint], gpmf_gps_filter.remove_noisy_points(gps_points)
        )
        if not gps_points:
            # Instead of raising an exception, return error metadata to tell the file type
            ex = exceptions.MapillaryGPSNoiseError("GPS is too noisy")
            return types.describe_error_metadata(
                ex, self.video_path, filetype=types.FileType.GOPRO
            )

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
    def extract(self) -> types.VideoMetadataOrError:
        with self.video_path.open("rb") as fp:
            camm_info = camm_parser.extract_camm_info(fp)

        if camm_info is None:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        if not camm_info.gps and not camm_info.mini_gps:
            # Instead of raising an exception, return error metadata to tell the file type
            ex: exceptions.MapillaryDescriptionError = (
                exceptions.MapillaryGPXEmptyError("Empty GPS data found")
            )
            return types.describe_error_metadata(
                ex, self.video_path, filetype=types.FileType.CAMM
            )

        return types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=types.FileType.CAMM,
            points=T.cast(T.List[geo.Point], camm_info.gps or camm_info.mini_gps),
            make=camm_info.make,
            model=camm_info.model,
        )


class BlackVueVideoExtractor(BaseVideoExtractor):
    @override
    def extract(self) -> types.VideoMetadataOrError:
        with self.video_path.open("rb") as fp:
            blackvue_info = blackvue_parser.extract_blackvue_info(fp)

        if blackvue_info is None:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        if not blackvue_info.gps:
            # Instead of raising an exception, return error metadata to tell the file type
            ex: exceptions.MapillaryDescriptionError = (
                exceptions.MapillaryGPXEmptyError("Empty GPS data found")
            )
            return types.describe_error_metadata(
                ex, self.video_path, filetype=types.FileType.BLACKVUE
            )

        video_metadata = types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=types.FileType.BLACKVUE,
            points=blackvue_info.gps or [],
            make=blackvue_info.make,
            model=blackvue_info.model,
        )

        return video_metadata


class NativeVideoExtractor(BaseVideoExtractor):
    def __init__(self, video_path: Path, filetypes: set[types.FileType] | None = None):
        super().__init__(video_path)
        self.filetypes = filetypes

    @override
    def extract(self) -> types.VideoMetadataOrError:
        ft = self.filetypes
        extractor: BaseVideoExtractor

        if ft is None or types.FileType.VIDEO in ft or types.FileType.GOPRO in ft:
            extractor = GoProVideoExtractor(self.video_path)
            try:
                return extractor.extract()
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        if ft is None or types.FileType.VIDEO in ft or types.FileType.CAMM in ft:
            extractor = CAMMVideoExtractor(self.video_path)
            try:
                return extractor.extract()
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        if ft is None or types.FileType.VIDEO in ft or types.FileType.BLACKVUE in ft:
            extractor = BlackVueVideoExtractor(self.video_path)
            try:
                return extractor.extract()
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        raise exceptions.MapillaryVideoGPSNotFoundError(
            "No GPS data found from the video"
        )
