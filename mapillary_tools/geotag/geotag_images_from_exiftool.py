import io
import logging
import typing as T
import xml.etree.ElementTree as ET
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from .. import exceptions, exiftool_read, types
from .geotag_from_generic import GeotagImagesFromGeneric
from .geotag_images_from_exif import GeotagImagesFromEXIF, verify_image_exif_write

LOG = logging.getLogger(__name__)


class GeotagImagesFromExifTool(GeotagImagesFromGeneric):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        xml_path: Path,
        num_processes: T.Optional[int] = None,
    ):
        self.image_paths = image_paths
        self.xml_path = xml_path
        self.num_processes = num_processes
        super().__init__()

    @staticmethod
    def geotag_image(element: ET.Element) -> types.ImageMetadataOrError:
        image_path = exiftool_read.find_rdf_description_path(element)
        assert image_path is not None, "must find the path from the element"

        try:
            exif = exiftool_read.ExifToolRead(ET.ElementTree(element))
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
        rdf_description_by_path = exiftool_read.index_rdf_description_by_path(
            [self.xml_path]
        )

        error_metadatas: T.List[types.ErrorMetadata] = []
        rdf_descriptions: T.List[ET.Element] = []
        for path in self.image_paths:
            rdf_description = rdf_description_by_path.get(
                exiftool_read.canonical_path(path)
            )
            if rdf_description is None:
                exc = exceptions.MapillaryEXIFNotFoundError(
                    f"The {exiftool_read._DESCRIPTION_TAG} XML element for the image not found"
                )
                error_metadatas.append(
                    types.describe_error_metadata(
                        exc, path, filetype=types.FileType.IMAGE
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
            image_metadatas_iter: T.Iterator[types.ImageMetadataOrError]
            if disable_multiprocessing:
                image_metadatas_iter = map(
                    GeotagImagesFromExifTool.geotag_image,
                    rdf_descriptions,
                )
            else:
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
