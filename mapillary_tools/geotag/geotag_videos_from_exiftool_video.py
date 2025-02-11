import logging
import typing as T
import xml.etree.ElementTree as ET
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, exiftool_read, geo, types, utils
from ..exiftool_read_video import ExifToolReadVideo
from ..telemetry import GPSPoint
from . import gpmf_gps_filter, utils as video_utils
from .geotag_from_generic import GeotagVideosFromGeneric

LOG = logging.getLogger(__name__)
_DESCRIPTION_TAG = "rdf:Description"


class GeotagVideosFromExifToolVideo(GeotagVideosFromGeneric):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        xml_path: Path,
        num_processes: T.Optional[int] = None,
    ):
        self.video_paths = video_paths
        self.xml_path = xml_path
        self.num_processes = num_processes
        super().__init__()

    @staticmethod
    def geotag_video(element: ET.Element) -> types.VideoMetadataOrError:
        video_path = exiftool_read.find_rdf_description_path(element)
        assert video_path is not None, "must find the path from the element"

        try:
            exif = ExifToolReadVideo(ET.ElementTree(element))

            points = exif.extract_gps_track()

            if not points:
                raise exceptions.MapillaryVideoGPSNotFoundError(
                    "No GPS data found from the video"
                )

            points = geo.extend_deduplicate_points(points)
            assert points, "must have at least one point"

            if all(isinstance(p, GPSPoint) for p in points):
                points = T.cast(
                    T.List[geo.Point],
                    gpmf_gps_filter.remove_noisy_points(
                        T.cast(T.List[GPSPoint], points)
                    ),
                )
                if not points:
                    raise exceptions.MapillaryGPSNoiseError("GPS is too noisy")

            stationary = video_utils.is_video_stationary(
                geo.get_max_distance_from_start([(p.lat, p.lon) for p in points])
            )

            if stationary:
                raise exceptions.MapillaryStationaryVideoError("Stationary video")

            video_metadata = types.VideoMetadata(
                video_path,
                md5sum=None,
                filesize=utils.get_file_size(video_path),
                filetype=types.FileType.VIDEO,
                points=points,
                make=exif.extract_make(),
                model=exif.extract_model(),
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
        rdf_description_by_path = exiftool_read.index_rdf_description_by_path(
            [self.xml_path]
        )

        error_metadatas: T.List[types.ErrorMetadata] = []
        rdf_descriptions: T.List[ET.Element] = []
        for path in self.video_paths:
            rdf_description = rdf_description_by_path.get(
                exiftool_read.canonical_path(path)
            )
            if rdf_description is None:
                exc = exceptions.MapillaryEXIFNotFoundError(
                    f"The {_DESCRIPTION_TAG} XML element for the video not found"
                )
                error_metadatas.append(
                    types.describe_error_metadata(
                        exc, path, filetype=types.FileType.VIDEO
                    )
                )
            else:
                rdf_descriptions.append(rdf_description)

        if self.num_processes is None:
            num_processes = self.num_processes
            disable_multiprocessing = False
        else:
            num_processes = max(self.num_processes, 1)
            disable_multiprocessing = self.num_processes <= 0

        with Pool(processes=num_processes) as pool:
            video_metadatas_iter: T.Iterator[types.VideoMetadataOrError]
            if disable_multiprocessing:
                video_metadatas_iter = map(
                    GeotagVideosFromExifToolVideo.geotag_video, rdf_descriptions
                )
            else:
                video_metadatas_iter = pool.imap(
                    GeotagVideosFromExifToolVideo.geotag_video,
                    rdf_descriptions,
                )
            video_metadata_or_errors = list(
                tqdm(
                    video_metadatas_iter,
                    desc="Extracting GPS tracks from ExifTool XML",
                    unit="videos",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(self.video_paths),
                )
            )

        return error_metadatas + video_metadata_or_errors
