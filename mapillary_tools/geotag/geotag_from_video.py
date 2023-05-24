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

LOG = logging.getLogger(__name__)


class GeotagFromVideo:
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        filetypes: T.Optional[T.Set[types.FileType]] = None,
    ):
        self.video_paths = video_paths
        self.filetypes = filetypes

    def to_descriptions(self) -> T.List[types.VideoMetadataOrError]:
        with Pool() as pool:
            video_metadatas = pool.imap(
                self._geotag_video,
                self.video_paths,
            )
            return list(
                tqdm(
                    video_metadatas,
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
        return GeotagFromVideo.geotag_video(video_path, self.filetypes)

    @staticmethod
    def geotag_video(
        video_path: Path,
        filetypes: T.Optional[T.Set[types.FileType]] = None,
    ) -> types.VideoMetadataOrError:
        video_metadata = None
        if filetypes is None or types.FileType.CAMM in filetypes:
            with video_path.open("rb") as fp:
                try:
                    points = camm_parser.extract_points(fp)
                except parser.ParsingError:
                    points = None

                if points is not None:
                    fp.seek(0, io.SEEK_SET)
                    make, model = camm_parser.extract_camera_make_and_model(fp)
                    video_metadata = types.VideoMetadata(
                        video_path, None, types.FileType.CAMM, points, make, model
                    )

        if filetypes is None or types.FileType.GOPRO in filetypes:
            with video_path.open("rb") as fp:
                try:
                    points_with_fix = gpmf_parser.extract_points(fp)
                except parser.ParsingError:
                    points_with_fix = None

                if points_with_fix is not None:
                    fp.seek(0, io.SEEK_SET)
                    make, model = "GoPro", gpmf_parser.extract_camera_model(fp)
                    video_metadata = types.VideoMetadata(
                        video_path,
                        None,
                        types.FileType.GOPRO,
                        T.cast(T.List[geo.Point], points_with_fix),
                        make,
                        model,
                    )
                    video_metadata.points = T.cast(
                        T.List[geo.Point],
                        gpmf_gps_filter.filter_noisy_points(
                            T.cast(
                                T.List[gpmf_parser.PointWithFix],
                                video_metadata.points,
                            )
                        ),
                    )

        if filetypes is None or types.FileType.BLACKVUE in filetypes:
            with video_path.open("rb") as fp:
                try:
                    points = blackvue_parser.extract_points(fp)
                except parser.ParsingError:
                    points = None

                if points is not None:
                    fp.seek(0, io.SEEK_SET)
                    make, model = "BlackVue", blackvue_parser.extract_camera_model(fp)
                    video_metadata = types.VideoMetadata(
                        video_path, None, types.FileType.BLACKVUE, points, make, model
                    )

        if video_metadata is None:
            return types.describe_error_metadata(
                exceptions.MapillaryVideoError("No GPS data found from the video"),
                video_path,
                filetype=None,
            )

        if not video_metadata.points:
            return types.describe_error_metadata(
                exceptions.MapillaryGPXEmptyError("Empty GPS data found"),
                video_metadata.filename,
                filetype=video_metadata.filetype,
            )

        stationary = video_utils.is_video_stationary(
            geo.get_max_distance_from_start(
                [(p.lat, p.lon) for p in video_metadata.points]
            )
        )
        if stationary:
            return types.describe_error_metadata(
                exceptions.MapillaryStationaryVideoError("Stationary video"),
                video_metadata.filename,
                filetype=video_metadata.filetype,
            )

        if not isinstance(video_metadata, types.ErrorMetadata):
            LOG.debug("Calculating MD5 checksum for %s", str(video_metadata.filename))
            video_metadata.update_md5sum()

        return video_metadata
