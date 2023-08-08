import logging
import typing as T
import xml.etree.ElementTree as ET
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm
from mapillary_tools import geo

from mapillary_tools.geotag import (
    external_geotag_source_helper,
    geotag_images_from_gpx_file,
)

from .. import exceptions, types
from .geotag_from_generic import GeotagVideosFromGeneric

LOG = logging.getLogger(__name__)


class GeotagVideosFromGpx(GeotagVideosFromGeneric):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        xml_path: T.Optional[Path],
        num_processes: T.Optional[int] = None,
    ):
        self.xml_path = xml_path
        self.video_geotag_pairs: T.Dict[Path, Path] = {}
        super().__init__(video_paths=video_paths, num_processes=num_processes)

    def _geotag_video(self, video_path: Path) -> types.VideoMetadataOrError:
        try:
            tracks = geotag_images_from_gpx_file.parse_gpx(
                self.video_geotag_pairs[video_path]
            )
            points: T.Sequence[geo.Point] = sum(tracks, [])

            if not points:
                raise exceptions.MapillaryVideoGPSNotFoundError(
                    "No GPS data found from the video"
                )

            points = GeotagVideosFromGeneric.process_points(points)
            for p in points:
                p.time = p.time - points[0].time

            video_metadata = types.VideoMetadata(
                video_path,
                md5sum=None,
                filetype=types.FileType.VIDEO,
                points=points,
                make=None,
                model=None,
            )

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
            return types.describe_error_metadata(
                ex, video_path, filetype=types.FileType.VIDEO
            )

        return video_metadata

    def to_description(self) -> T.List[types.VideoMetadataOrError]:
        error_metadatas: T.List[types.ErrorMetadata] = []
        
        if self.num_processes is None:
            num_processes = self.num_processes
            disable_multiprocessing = False
        else:
            num_processes = max(self.num_processes, 1)
            disable_multiprocessing = self.num_processes <= 0

        self.video_geotag_pairs = external_geotag_source_helper.match_videos_and_geotag_files(
                self.video_paths, self.xml_path, ["gpx"]
            )

        with Pool(processes=num_processes) as pool:
            video_metadatas_iter: T.Iterator[types.VideoMetadataOrError]
            if disable_multiprocessing:
                video_metadatas_iter = map(self._geotag_video, self.video_paths)
            else:
                video_metadatas_iter = pool.imap(
                    self._geotag_video,
                    self.video_paths,
                )
            video_metadata_or_errors = list(
                tqdm(
                    video_metadatas_iter,
                    desc="Extracting GPS tracks from GPX",
                    unit="videos",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(self.video_paths),
                )
            )

        return error_metadatas + video_metadata_or_errors
