import io
import logging
import typing as T
import xml.etree.ElementTree as ET
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, types, utils
from ..exiftool_read import EXIFTOOL_NAMESPACES, ExifToolRead
from .geotag_from_generic import GeotagImagesFromGeneric
from .geotag_images_from_exif import GeotagImagesFromEXIF, verify_image_exif_write

LOG = logging.getLogger(__name__)
_DESCRIPTION_TAG = "rdf:Description"


def canonical_path(path: Path) -> str:
    return str(path.resolve().as_posix())


def find_rdf_description_path(element: ET.Element) -> T.Optional[Path]:
    about = element.get("{" + EXIFTOOL_NAMESPACES["rdf"] + "}about")
    if about is None:
        return None
    return Path(about)


def index_rdf_description_by_path(
    xml_paths: T.Sequence[Path],
) -> T.Dict[str, ET.Element]:
    rdf_description_by_path: T.Dict[str, ET.Element] = {}

    for xml_path in utils.find_xml_files(xml_paths):
        try:
            etree = ET.parse(xml_path)
        except ET.ParseError as ex:
            verbose = LOG.getEffectiveLevel() <= logging.DEBUG
            if verbose:
                LOG.warning(f"Failed to parse {xml_path}", exc_info=verbose)
            else:
                LOG.warning(f"Failed to parse {xml_path}: {ex}", exc_info=verbose)
            continue

        elements = etree.iterfind(_DESCRIPTION_TAG, namespaces=EXIFTOOL_NAMESPACES)
        for element in elements:
            path = find_rdf_description_path(element)
            if path is not None:
                rdf_description_by_path[canonical_path(path)] = element

    return rdf_description_by_path


class GeotagImagesFromExifTool(GeotagImagesFromGeneric):
    def __init__(self, image_paths: T.Sequence[Path], xml_path: Path):
        self.image_paths = image_paths
        self.xml_path = xml_path
        super().__init__()

    @staticmethod
    def geotag_image(element: ET.Element) -> types.ImageMetadataOrError:
        image_path = find_rdf_description_path(element)
        assert image_path is not None, "must find the path from the element"

        try:
            exif = ExifToolRead(ET.ElementTree(element))
            image_metadata = GeotagImagesFromEXIF.build_image_metadata(
                image_path, exif, skip_lonlat_error=False
            )
            # load the image bytes into memory to avoid reading it multiple times
            with image_path.open("rb") as fp:
                image_bytesio = io.BytesIO(fp.read())
            image_bytesio.seek(0, io.SEEK_SET)
            verify_image_exif_write(
                image_metadata,
                image_bytes=image_bytesio.read(),
            )
        except Exception as ex:
            return types.describe_error_metadata(
                ex, image_path, filetype=types.FileType.IMAGE
            )

        image_bytesio.seek(0, io.SEEK_SET)
        image_metadata.update_md5sum(image_bytesio)

        return image_metadata

    def to_description(self) -> T.List[types.ImageMetadataOrError]:
        rdf_description_by_path = index_rdf_description_by_path([self.xml_path])

        error_metadatas: T.List[types.ErrorMetadata] = []
        rdf_descriptions: T.List[ET.Element] = []
        for path in self.image_paths:
            rdf_description = rdf_description_by_path.get(canonical_path(path))
            if rdf_description is None:
                exc = exceptions.MapillaryEXIFNotFoundError(
                    f"The {_DESCRIPTION_TAG} XML element for the image not found"
                )
                error_metadatas.append(
                    types.describe_error_metadata(
                        exc, path, filetype=types.FileType.IMAGE
                    )
                )
            else:
                rdf_descriptions.append(rdf_description)

        with Pool() as pool:
            image_metadatas_iter = pool.imap(
                GeotagImagesFromExifTool.geotag_image,
                rdf_descriptions,
            )
            image_metadata_or_errors = list(
                tqdm(
                    image_metadatas_iter,
                    desc="Extracting geotags from ExifTool XML",
                    unit="images",
                    disable=LOG.getEffectiveLevel() <= logging.DEBUG,
                    total=len(self.image_paths),
                )
            )

        return error_metadatas + image_metadata_or_errors
