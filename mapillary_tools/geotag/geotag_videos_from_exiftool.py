from __future__ import annotations

import logging
import sys
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .. import constants, exceptions, exiftool_read, types
from ..exiftool_runner import ExiftoolRunner
from .base import GeotagVideosFromGeneric
from .video_extractors.exiftool import VideoExifToolExtractor

LOG = logging.getLogger(__name__)


class GeotagVideosFromExifToolXML(GeotagVideosFromGeneric):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        xml_path: Path,
        num_processes: int | None = None,
    ):
        super().__init__(video_paths, num_processes=num_processes)
        self.xml_path = xml_path

    @override
    def _generate_video_extractors(
        self,
    ) -> T.Sequence[VideoExifToolExtractor | types.ErrorMetadata]:
        rdf_description_by_path = exiftool_read.index_rdf_description_by_path(
            [self.xml_path]
        )

        results: list[VideoExifToolExtractor | types.ErrorMetadata] = []

        for path in self.video_paths:
            rdf_description = rdf_description_by_path.get(
                exiftool_read.canonical_path(path)
            )
            if rdf_description is None:
                exc = exceptions.MapillaryEXIFNotFoundError(
                    f"The {exiftool_read._DESCRIPTION_TAG} XML element for the video not found"
                )
                results.append(
                    types.describe_error_metadata(
                        exc, path, filetype=types.FileType.VIDEO
                    )
                )
            else:
                results.append(VideoExifToolExtractor(path, rdf_description))

        return results


class GeotagVideosFromExifToolRunner(GeotagVideosFromGeneric):
    @override
    def _generate_video_extractors(
        self,
    ) -> T.Sequence[VideoExifToolExtractor | types.ErrorMetadata]:
        runner = ExiftoolRunner(constants.EXIFTOOL_PATH)

        LOG.debug(
            "Extracting XML from %d videos with exiftool command: %s",
            len(self.video_paths),
            " ".join(runner._build_args_read_stdin()),
        )

        try:
            xml = runner.extract_xml(self.video_paths)
        except FileNotFoundError as ex:
            raise exceptions.MapillaryExiftoolNotFoundError(ex) from ex

        rdf_description_by_path = (
            exiftool_read.index_rdf_description_by_path_from_xml_element(
                ET.fromstring(xml)
            )
        )

        results: list[VideoExifToolExtractor | types.ErrorMetadata] = []

        for path in self.video_paths:
            rdf_description = rdf_description_by_path.get(
                exiftool_read.canonical_path(path)
            )
            if rdf_description is None:
                exc = exceptions.MapillaryEXIFNotFoundError(
                    f"The {exiftool_read._DESCRIPTION_TAG} XML element for the video not found"
                )
                results.append(
                    types.describe_error_metadata(
                        exc, path, filetype=types.FileType.VIDEO
                    )
                )
            else:
                results.append(VideoExifToolExtractor(path, rdf_description))

        return results
