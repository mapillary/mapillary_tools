from __future__ import annotations

import io
import typing as T
from pathlib import Path

from .. import blackvue_parser, exceptions, geo, telemetry, types, utils
from ..camm import camm_parser
from ..gpmf import gpmf_gps_filter, gpmf_parser
from ..types import FileType
from .geotag_from_generic import GenericVideoExtractor, GeotagVideosFromGeneric


class GoProVideoExtractor(GenericVideoExtractor):
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
            raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

        gps_points = T.cast(
            T.List[telemetry.GPSPoint], gpmf_gps_filter.remove_noisy_points(gps_points)
        )
        if not gps_points:
            raise exceptions.MapillaryGPSNoiseError("GPS is too noisy")

        video_metadata = types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=FileType.GOPRO,
            points=T.cast(T.List[geo.Point], gps_points),
            make=gopro_info.make,
            model=gopro_info.model,
        )

        return video_metadata


class CAMMVideoExtractor(GenericVideoExtractor):
    def extract(self) -> types.VideoMetadataOrError:
        with self.video_path.open("rb") as fp:
            camm_info = camm_parser.extract_camm_info(fp)

        if camm_info is None:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        if not camm_info.gps and not camm_info.mini_gps:
            raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

        return types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=FileType.CAMM,
            points=T.cast(T.List[geo.Point], camm_info.gps or camm_info.mini_gps),
            make=camm_info.make,
            model=camm_info.model,
        )


class BlackVueVideoExtractor(GenericVideoExtractor):
    def extract(self) -> types.VideoMetadataOrError:
        with self.video_path.open("rb") as fp:
            points = blackvue_parser.extract_points(fp)

            if points is None:
                raise exceptions.MapillaryVideoGPSNotFoundError(
                    "No GPS data found from the video"
                )

            if not points:
                raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

            fp.seek(0, io.SEEK_SET)
            make, model = "BlackVue", blackvue_parser.extract_camera_model(fp)

        video_metadata = types.VideoMetadata(
            filename=self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=FileType.BLACKVUE,
            points=points,
            make=make,
            model=model,
        )

        return video_metadata


class NativeVideoExtractor(GenericVideoExtractor):
    def __init__(self, video_path: Path, filetypes: set[FileType] | None = None):
        super().__init__(video_path)
        self.filetypes = filetypes

    def extract(self) -> types.VideoMetadataOrError:
        ft = self.filetypes
        extractor: GenericVideoExtractor

        if ft is None or FileType.VIDEO in ft or FileType.GOPRO in ft:
            extractor = GoProVideoExtractor(self.video_path)
            try:
                return extractor.extract()
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        if ft is None or FileType.VIDEO in ft or FileType.CAMM in ft:
            extractor = CAMMVideoExtractor(self.video_path)
            try:
                return extractor.extract()
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        if ft is None or FileType.VIDEO in ft or FileType.BLACKVUE in ft:
            extractor = BlackVueVideoExtractor(self.video_path)
            try:
                return extractor.extract()
            except exceptions.MapillaryVideoGPSNotFoundError:
                pass

        raise exceptions.MapillaryVideoGPSNotFoundError(
            "No GPS data found from the video"
        )


class GeotagVideosFromVideo(GeotagVideosFromGeneric):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        filetypes: set[FileType] | None = None,
        num_processes: int | None = None,
    ):
        super().__init__(video_paths, num_processes=num_processes)
        self.filetypes = filetypes

    def _generate_video_extractors(self) -> T.Sequence[GenericVideoExtractor]:
        return [
            NativeVideoExtractor(path, filetypes=self.filetypes)
            for path in self.video_paths
        ]
