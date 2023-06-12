import logging
import typing as T
import xml.etree.ElementTree as ET
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, geo, types
from ..exiftool_read_video import ExifToolReadVideo
from . import geotag_images_from_exiftool, utils as video_utils
from .geotag_from_generic import GeotagVideosFromGeneric

LOG = logging.getLogger(__name__)
_DESCRIPTION_TAG = "rdf:Description"


class GeotagVideosFromExifToolVideo(GeotagVideosFromGeneric):
    def __init__(self, video_paths: T.Sequence[Path], xml_path: Path):
        self.video_paths = video_paths
        self.xml_path = xml_path
        super().__init__()

    @staticmethod
    def geotag_video(element: ET.Element) -> types.VideoMetadataOrError:
        video_path = geotag_images_from_exiftool.find_rdf_description_path(element)
        assert video_path is not None, "must find the path from the element"

        try:
            exif = ExifToolReadVideo(ET.ElementTree(element))

            points = exif.extract_gps_track()

            if not points:
                raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

            stationary = video_utils.is_video_stationary(
                geo.get_max_distance_from_start([(p.lat, p.lon) for p in points])
            )

            if stationary:
                raise exceptions.MapillaryStationaryVideoError("Stationary video")
        except Exception as ex:
            return types.describe_error_metadata(
                ex, video_path, filetype=types.FileType.VIDEO
            )

        video_metadata = types.VideoMetadata(
            video_path,
            md5sum=None,
            filetype=types.FileType.VIDEO,
            points=points,
            make=exif.extract_make(),
            model=exif.extract_model(),
        )

        LOG.debug("Calculating MD5 checksum for %s", str(video_metadata.filename))
        try:
            video_metadata.update_md5sum()
        except Exception as ex:
            return types.describe_error_metadata(
                ex, video_path, filetype=types.FileType.VIDEO
            )

        return video_metadata

    def to_description(self) -> T.List[types.VideoMetadataOrError]:
        rdf_description_by_path = (
            geotag_images_from_exiftool.index_rdf_description_by_path([self.xml_path])
        )

        error_metadatas: T.List[types.ErrorMetadata] = []
        rdf_descriptions: T.List[ET.Element] = []
        for path in self.video_paths:
            rdf_description = rdf_description_by_path.get(
                geotag_images_from_exiftool.canonical_path(path)
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

        with Pool() as pool:
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
