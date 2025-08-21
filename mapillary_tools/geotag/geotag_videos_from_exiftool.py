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
from . import options
from .base import GeotagVideosFromGeneric
from .utils import index_rdf_description_by_path
from .video_extractors.exiftool import VideoExifToolExtractor

LOG = logging.getLogger(__name__)


class GeotagVideosFromExifToolXML(GeotagVideosFromGeneric):
    def __init__(
        self, source_path: options.SourcePathOption, num_processes: int | None = None
    ):
        super().__init__(num_processes=num_processes)
        self.source_path = source_path

    @classmethod
    def build_video_extractors_from_etree(
        cls, rdf_by_path: dict[str, ET.Element], video_paths: T.Iterable[Path]
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
        rdf_by_path = self.find_rdf_by_path(self.source_path, video_paths)
        return self.build_video_extractors_from_etree(rdf_by_path, video_paths)

    @classmethod
    def find_rdf_by_path(
        cls, option: options.SourcePathOption, paths: T.Iterable[Path]
    ) -> dict[str, ET.Element]:
        # Find RDF descriptions by path in RDF description
        # Sources are matched based on the paths in "rdf:about" in XML elements
        # {"source_path": "/path/to/exiftool.xml"}
        # {"source_path": "/path/to/exiftool_xmls/"}
        if option.source_path is not None:
            return index_rdf_description_by_path([option.source_path])

        # Find RDF descriptions by pattern matching
        # i.e. "video.mp4" matches "/path/to/video.xml" regardless of "rdf:about"
        # {"pattern": "/path/to/%g.xml"}
        if option.pattern is not None:
            rdf_by_path = {}
            for path in paths:
                canonical_path = exiftool_read.canonical_path(path)

                # Skip non-existent resolved source paths to avoid verbose warnings
                resolved_source_path = option.resolve(path)
                if not resolved_source_path.exists():
                    continue

                rdf_by_about = index_rdf_description_by_path([resolved_source_path])
                if not rdf_by_about:
                    continue

                rdf = rdf_by_about.get(canonical_path)
                if rdf is None:
                    about, rdf = list(rdf_by_about.items())[0]
                    if len(rdf_by_about) > 1:
                        LOG.warning(
                            f"Found {len(rdf_by_about)} RDFs in the XML source {resolved_source_path}. Using the first RDF (with rdf:about={about}) for {path}"
                        )
                rdf_by_path[canonical_path] = rdf

            return rdf_by_path

        raise AssertionError("Either source_path or pattern must be provided")


class GeotagVideosFromExifToolRunner(GeotagVideosFromGeneric):
    @override
    def _generate_video_extractors(
        self, video_paths: T.Sequence[Path]
    ) -> T.Sequence[VideoExifToolExtractor | types.ErrorMetadata]:
        if constants.EXIFTOOL_PATH is None:
            runner = ExiftoolRunner()
        else:
            runner = ExiftoolRunner(constants.EXIFTOOL_PATH)

        LOG.debug(
            "Extracting XML from %d videos with ExifTool command: %s",
            len(video_paths),
            " ".join(runner._build_args_read_stdin()),
        )
        try:
            xml = runner.extract_xml(video_paths)
        except FileNotFoundError as ex:
            exiftool_ex = exceptions.MapillaryExiftoolNotFoundError(ex)
            return [
                types.describe_error_metadata(
                    exiftool_ex, video_path, filetype=types.FileType.VIDEO
                )
                for video_path in video_paths
            ]

        try:
            xml_element = ET.fromstring(xml)
        except ET.ParseError as ex:
            LOG.warning(
                "Failed to parse ExifTool XML: %s",
                str(ex),
                exc_info=LOG.isEnabledFor(logging.DEBUG),
            )
            rdf_by_path = {}
        else:
            rdf_by_path = exiftool_read.index_rdf_description_by_path_from_xml_element(
                xml_element
            )

        return GeotagVideosFromExifToolXML.build_video_extractors_from_etree(
            rdf_by_path, video_paths
        )
