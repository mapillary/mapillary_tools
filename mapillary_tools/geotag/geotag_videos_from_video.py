import io
import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, geo, types
from . import (
    blackvue_parser,
    camm_parser,
    gpmf_gps_filter,
    gpmf_parser,
    simple_mp4_parser as parser,
    utils as video_utils,
)
from .geotag_from_generic import GeotagVideosFromGeneric

LOG = logging.getLogger(__name__)


class GeotagVideosFromVideo(GeotagVideosFromGeneric):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        filetypes: T.Optional[T.Set[types.FileType]] = None,
    ):
        self.video_paths = video_paths
        self.filetypes = filetypes

    def to_description(self) -> T.List[types.VideoMetadataOrError]:
        with Pool() as pool:
            video_metadatas_iter = pool.imap(
                self._geotag_video,
                self.video_paths,
            )
            return list(
                tqdm(
                    video_metadatas_iter,
                    desc="Extracting GPS tracks from videos",
                    unit="videos",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(self.video_paths),
                )
            )

    def _geotag_video(
        self,
        video_path: Path,
    ) -> types.VideoMetadataOrError:
        return GeotagVideosFromVideo.geotag_video(video_path, self.filetypes)

    @staticmethod
    def _extract_video_metadata(
        video_path: Path,
        filetypes: T.Optional[T.Set[types.FileType]] = None,
    ) -> T.Optional[types.VideoMetadata]:
        if (
            filetypes is None
            or types.FileType.VIDEO in filetypes
            or types.FileType.CAMM in filetypes
        ):
            with video_path.open("rb") as fp:
                try:
                    points = camm_parser.extract_points(fp)
                except parser.ParsingError:
                    points = None

                if points is not None:
                    fp.seek(0, io.SEEK_SET)
                    make, model = camm_parser.extract_camera_make_and_model(fp)
                    return types.VideoMetadata(
                        filename=video_path,
                        md5sum=None,
                        filetype=types.FileType.CAMM,
                        points=points,
                        make=make,
                        model=model,
                    )

        if (
            filetypes is None
            or types.FileType.VIDEO in filetypes
            or types.FileType.GOPRO in filetypes
        ):
            with video_path.open("rb") as fp:
                try:
                    points_with_fix = gpmf_parser.extract_points(fp)
                except parser.ParsingError:
                    points_with_fix = None

                if points_with_fix is not None:
                    fp.seek(0, io.SEEK_SET)
                    make, model = "GoPro", gpmf_parser.extract_camera_model(fp)
                    points = T.cast(
                        T.List[geo.Point],
                        gpmf_gps_filter.filter_noisy_points(points_with_fix),
                    )
                    return types.VideoMetadata(
                        filename=video_path,
                        md5sum=None,
                        filetype=types.FileType.GOPRO,
                        points=points,
                        make=make,
                        model=model,
                    )

        if (
            filetypes is None
            or types.FileType.VIDEO in filetypes
            or types.FileType.BLACKVUE in filetypes
        ):
            with video_path.open("rb") as fp:
                try:
                    points = blackvue_parser.extract_points(fp)
                except parser.ParsingError:
                    points = None

                if points is not None:
                    fp.seek(0, io.SEEK_SET)
                    make, model = "BlackVue", blackvue_parser.extract_camera_model(fp)
                    return types.VideoMetadata(
                        filename=video_path,
                        md5sum=None,
                        filetype=types.FileType.BLACKVUE,
                        points=points,
                        make=make,
                        model=model,
                    )

        return None

    @staticmethod
    def geotag_video(
        video_path: Path,
        filetypes: T.Optional[T.Set[types.FileType]] = None,
    ) -> types.VideoMetadataOrError:
        video_metadata = None
        try:
            video_metadata = GeotagVideosFromVideo._extract_video_metadata(
                video_path, filetypes
            )

            if video_metadata is None:
                raise exceptions.MapillaryVideoError("No GPS data found from the video")

            if not video_metadata.points:
                raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

            stationary = video_utils.is_video_stationary(
                geo.get_max_distance_from_start(
                    [(p.lat, p.lon) for p in video_metadata.points]
                )
            )
            if stationary:
                raise exceptions.MapillaryStationaryVideoError("Stationary video")

            LOG.debug("Calculating MD5 checksum for %s", str(video_metadata.filename))
            video_metadata.update_md5sum()
        except Exception as ex:
            if video_metadata is None:
                return types.describe_error_metadata(
                    ex,
                    video_path,
                    filetype=None,
                )
            else:
                return types.describe_error_metadata(
                    ex,
                    video_metadata.filename,
                    filetype=video_metadata.filetype,
                )

        return video_metadata
