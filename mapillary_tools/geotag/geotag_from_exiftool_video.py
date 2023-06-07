import logging
import typing as T
import xml.etree.ElementTree as ET
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, geo, types, utils

from ..exiftool_read import EXIFTOOL_NAMESPACES
from ..exiftool_read_video import ExifToolReadVideo
from . import utils as video_utils
from .geotag_from_generic import GeotagFromVideoGeneric

LOG = logging.getLogger(__name__)
_DESCRIPTION_TAG = "rdf:Description"


def _canonical_path(path: Path) -> str:
    return str(path.resolve().as_posix())


def _rdf_description_path(element: ET.Element) -> T.Optional[Path]:
    about = element.get("{" + EXIFTOOL_NAMESPACES["rdf"] + "}about")
    if about is None:
        return None
    return Path(about)


class GeotagFromExifToolVideo(GeotagFromVideoGeneric):
    def __init__(self, video_paths: T.Sequence[Path], xml_path: Path):
        self.video_paths = video_paths
        self.xml_path = xml_path
        super().__init__()

    @staticmethod
    def geotag_video(element: ET.Element) -> types.VideoMetadataOrError:
        video_path = _rdf_description_path(element)
        assert video_path is not None, "must find the path from the element"

        try:
            exif = ExifToolReadVideo(ET.ElementTree(element))
        except Exception as ex:
            return types.describe_error_metadata(
                ex, video_path, filetype=types.FileType.VIDEO
            )

        points = exif.extract_gps_track()
        if not points:
            return types.describe_error_metadata(
                exceptions.MapillaryGPXEmptyError("Empty GPS data found"),
                video_path,
                filetype=types.FileType.VIDEO,
            )

        video_metadata = types.VideoMetadata(
            video_path,
            md5sum=None,
            filetype=types.FileType.VIDEO,
            points=points,
            make=exif.extract_make(),
            model=exif.extract_model(),
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

    def to_description(self) -> T.List[types.VideoMetadataOrError]:
        rdf_description_by_path: T.Dict[str, ET.Element] = {}
        for xml_path in utils.find_xml_files([self.xml_path]):
            try:
                etree = ET.parse(xml_path)
            except ET.ParseError:
                continue

            elements = etree.iterfind(_DESCRIPTION_TAG, namespaces=EXIFTOOL_NAMESPACES)
            for element in elements:
                path = _rdf_description_path(element)
                if path is not None:
                    rdf_description_by_path[_canonical_path(path)] = element

        error_metadatas: T.List[types.ErrorMetadata] = []
        rdf_descriptions: T.List[ET.Element] = []
        for path in self.video_paths:
            rdf_description = rdf_description_by_path.get(_canonical_path(path))
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
            video_metadatas = pool.imap(
                GeotagFromExifToolVideo.geotag_video,
                rdf_descriptions,
            )
            video_metadata_or_errors = list(
                tqdm(
                    video_metadatas,
                    desc="Extracting GPS tracks from videos",
                    unit="videos",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(self.video_paths),
                )
            )

        return error_metadatas + video_metadata_or_errors
