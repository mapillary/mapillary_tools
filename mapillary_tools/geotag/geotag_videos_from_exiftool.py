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
from .utils import index_rdf_description_by_path
from .video_extractors.exiftool import VideoExifToolExtractor

LOG = logging.getLogger(__name__)


class GeotagVideosFromExifToolXML(GeotagVideosFromGeneric):
    def __init__(
        self,
        xml_path: Path,
        num_processes: int | None = None,
    ):
        super().__init__(num_processes=num_processes)
        self.xml_path = xml_path

    @classmethod
    def build_image_extractors(
        cls,
        rdf_by_path: dict[str, ET.Element],
        video_paths: T.Iterable[Path],
    ) -> list[VideoExifToolExtractor | types.ErrorMetadata]:
        results: list[VideoExifToolExtractor | types.ErrorMetadata] = []

        for path in video_paths:
            rdf = rdf_by_path.get(exiftool_read.canonical_path(path))
            if rdf is None:
                ex = exceptions.MapillaryExifToolXMLNotFoundError(
                    "Cannot find the video in the ExifTool XML"
                )
                results.append(
                    types.describe_error_metadata(
                        ex, path, filetype=types.FileType.VIDEO
                    )
                )
            else:
                results.append(VideoExifToolExtractor(path, rdf))

        return results

    @override
    def _generate_video_extractors(
        self, video_paths: T.Sequence[Path]
    ) -> T.Sequence[VideoExifToolExtractor | types.ErrorMetadata]:
        rdf_by_path = index_rdf_description_by_path([self.xml_path])
        return self.build_image_extractors(rdf_by_path, video_paths)


class GeotagVideosFromExifToolRunner(GeotagVideosFromGeneric):
    @override
    def _generate_video_extractors(
        self, video_paths: T.Sequence[Path]
    ) -> T.Sequence[VideoExifToolExtractor | types.ErrorMetadata]:
        runner = ExiftoolRunner(constants.EXIFTOOL_PATH)

        LOG.debug(
            "Extracting XML from %d videos with ExifTool command: %s",
            len(video_paths),
            " ".join(runner._build_args_read_stdin()),
        )
        try:
            xml = runner.extract_xml(video_paths)
        except FileNotFoundError as ex:
            raise exceptions.MapillaryExiftoolNotFoundError(ex) from ex

        try:
            xml_element = ET.fromstring(xml)
        except ET.ParseError as ex:
            LOG.warning(
                "Failed to parse ExifTool XML: %s",
                str(ex),
                exc_info=LOG.getEffectiveLevel() <= logging.DEBUG,
            )
            rdf_by_path = {}
        else:
            rdf_by_path = exiftool_read.index_rdf_description_by_path_from_xml_element(
                xml_element
            )

        return GeotagVideosFromExifToolXML.build_image_extractors(
            rdf_by_path, video_paths
        )
