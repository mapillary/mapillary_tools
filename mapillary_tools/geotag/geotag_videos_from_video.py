import io
import logging
import typing as T
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, geo, types, utils
from ..camm import camm_parser
from ..mp4 import simple_mp4_parser as sparser
from ..telemetry import GPSPoint
from . import blackvue_parser, gpmf_gps_filter, gpmf_parser, utils as video_utils
from .geotag_from_generic import GeotagVideosFromGeneric

LOG = logging.getLogger(__name__)


class GeotagVideosFromVideo(GeotagVideosFromGeneric):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        filetypes: T.Optional[T.Set[types.FileType]] = None,
        num_processes: T.Optional[int] = None,
    ):
        self.video_paths = video_paths
        self.filetypes = filetypes
        self.num_processes = num_processes

    def to_description(self) -> T.List[types.VideoMetadataOrError]:
        if self.num_processes is None:
            num_processes = self.num_processes
            disable_multiprocessing = False
        else:
            num_processes = max(self.num_processes, 1)
            disable_multiprocessing = self.num_processes <= 0

        with Pool(processes=num_processes) as pool:
            video_metadatas_iter: T.Iterator[types.VideoMetadataOrError]
            if disable_multiprocessing:
                video_metadatas_iter = map(self._geotag_video, self.video_paths)
            else:
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
                except sparser.ParsingError:
                    points = None

                if points is not None:
                    fp.seek(0, io.SEEK_SET)
                    make, model = camm_parser.extract_camera_make_and_model(fp)
                    return types.VideoMetadata(
                        filename=video_path,
                        md5sum=None,
                        filesize=utils.get_file_size(video_path),
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
                except sparser.ParsingError:
                    points_with_fix = None

                if points_with_fix is not None:
                    fp.seek(0, io.SEEK_SET)
                    make, model = "GoPro", gpmf_parser.extract_camera_model(fp)
                    return types.VideoMetadata(
                        filename=video_path,
                        md5sum=None,
                        filesize=utils.get_file_size(video_path),
                        filetype=types.FileType.GOPRO,
                        points=T.cast(T.List[geo.Point], points_with_fix),
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
                except sparser.ParsingError:
                    points = None

                if points is not None:
                    fp.seek(0, io.SEEK_SET)
                    make, model = "BlackVue", blackvue_parser.extract_camera_model(fp)
                    return types.VideoMetadata(
                        filename=video_path,
                        md5sum=None,
                        filesize=utils.get_file_size(video_path),
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

            video_metadata.points = geo.extend_deduplicate_points(video_metadata.points)
            assert video_metadata.points, "must have at least one point"

            if all(isinstance(p, GPSPoint) for p in video_metadata.points):
                video_metadata.points = T.cast(
                    T.List[geo.Point],
                    gpmf_gps_filter.remove_noisy_points(
                        T.cast(T.List[GPSPoint], video_metadata.points)
                    ),
                )
                if not video_metadata.points:
                    raise exceptions.MapillaryGPSNoiseError("GPS is too noisy")

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
            if not isinstance(ex, exceptions.MapillaryDescriptionError):
                LOG.warning(
                    "Failed to geotag video %s: %s",
                    video_path,
                    str(ex),
                    exc_info=LOG.getEffectiveLevel() <= logging.DEBUG,
                )
            filetype = None if video_metadata is None else video_metadata.filetype
            return types.describe_error_metadata(
                ex,
                video_path,
                filetype=filetype,
            )

        return video_metadata
