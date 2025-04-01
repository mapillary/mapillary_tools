from __future__ import annotations

import contextlib
import logging
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import constants, exceptions, exiftool_read, types
from ..exiftool_runner import ExiftoolRunner
from .geotag_from_generic import GeotagImagesFromGeneric
from .geotag_images_from_exif import ImageEXIFExtractor

LOG = logging.getLogger(__name__)


class ImageExifToolExtractor(ImageEXIFExtractor):
    def __init__(self, image_path: Path, element: ET.Element):
        super().__init__(image_path)
        self.element = element

    @contextlib.contextmanager
    def _exif_context(self):
        yield exiftool_read.ExifToolRead(ET.ElementTree(self.element))


class GeotagImagesFromExifTool(GeotagImagesFromGeneric):
    def __init__(
        self,
        image_paths: T.Sequence[Path],
        xml_path: Path,
        num_processes: int | None = None,
    ):
        self.xml_path = xml_path
        super().__init__(image_paths=image_paths, num_processes=num_processes)

    def _generate_image_extractors(
        self,
    ) -> T.Sequence[ImageExifToolExtractor | types.ErrorMetadata]:
        rdf_description_by_path = exiftool_read.index_rdf_description_by_path(
            [self.xml_path]
        )

        results: list[ImageExifToolExtractor | types.ErrorMetadata] = []

        for path in self.image_paths:
            rdf_description = rdf_description_by_path.get(
                exiftool_read.canonical_path(path)
            )
            if rdf_description is None:
                exc = exceptions.MapillaryEXIFNotFoundError(
                    f"The {exiftool_read._DESCRIPTION_TAG} XML element for the image not found"
                )
                results.append(
                    types.describe_error_metadata(
                        exc, path, filetype=types.FileType.IMAGE
                    )
                )
            else:
                results.append(ImageExifToolExtractor(path, rdf_description))

        return results


class GeotagImagesFromExifToolRunner(GeotagImagesFromGeneric):
    def _generate_image_extractors(
        self,
    ) -> T.Sequence[ImageExifToolExtractor | types.ErrorMetadata]:
        runner = ExiftoolRunner(constants.EXIFTOOL_PATH)

        LOG.debug(
            "Extracting XML from %d images with exiftool command: %s",
            len(self.image_paths),
            " ".join(runner._build_args_read_stdin()),
        )
        try:
            xml = runner.extract_xml(self.image_paths)
        except FileNotFoundError as ex:
            raise exceptions.MapillaryExiftoolNotFoundError(ex) from ex

        rdf_description_by_path = (
            exiftool_read.index_rdf_description_by_path_from_xml_element(
                ET.fromstring(xml)
            )
        )

        results: list[ImageExifToolExtractor | types.ErrorMetadata] = []

        for path in self.image_paths:
            rdf_description = rdf_description_by_path.get(
                exiftool_read.canonical_path(path)
            )
            if rdf_description is None:
                exc = exceptions.MapillaryEXIFNotFoundError(
                    f"The {exiftool_read._DESCRIPTION_TAG} XML element for the image not found"
                )
                results.append(
                    types.describe_error_metadata(
                        exc, path, filetype=types.FileType.IMAGE
                    )
                )
            else:
                results.append(ImageExifToolExtractor(path, rdf_description))

        return results
