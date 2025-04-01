from __future__ import annotations

import logging
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import constants, exceptions, exiftool_read, geo, types, utils
from ..exiftool_read_video import ExifToolReadVideo
from ..exiftool_runner import ExiftoolRunner
from ..gpmf import gpmf_gps_filter
from ..telemetry import GPSPoint
from .geotag_from_generic import GenericVideoExtractor, GeotagVideosFromGeneric

LOG = logging.getLogger(__name__)


class VideoExifToolExtractor(GenericVideoExtractor):
    def __init__(self, video_path: Path, element: ET.Element):
        super().__init__(video_path)
        self.element = element

    def extract(self) -> types.VideoMetadataOrError:
        exif = ExifToolReadVideo(ET.ElementTree(self.element))

        make = exif.extract_make()
        model = exif.extract_model()

        is_gopro = make is not None and make.upper() in ["GOPRO"]

        points = exif.extract_gps_track()

        # ExifTool has no idea if GPS is not found or found but empty
        if is_gopro:
            if not points:
                raise exceptions.MapillaryGPXEmptyError("Empty GPS data found")

            # ExifTool (since 13.04) converts GPSSpeed for GoPro to km/h, so here we convert it back to m/s
            for p in points:
                if isinstance(p, GPSPoint) and p.ground_speed is not None:
                    p.ground_speed = p.ground_speed / 3.6

            if isinstance(points[0], GPSPoint):
                points = T.cast(
                    T.List[geo.Point],
                    gpmf_gps_filter.remove_noisy_points(
                        T.cast(T.List[GPSPoint], points)
                    ),
                )
                if not points:
                    raise exceptions.MapillaryGPSNoiseError("GPS is too noisy")

        if not points:
            raise exceptions.MapillaryVideoGPSNotFoundError(
                "No GPS data found from the video"
            )

        filetype = types.FileType.GOPRO if is_gopro else types.FileType.VIDEO

        video_metadata = types.VideoMetadata(
            self.video_path,
            filesize=utils.get_file_size(self.video_path),
            filetype=filetype,
            points=points,
            make=make,
            model=model,
        )

        return video_metadata


class GeotagVideosFromExifToolVideo(GeotagVideosFromGeneric):
    def __init__(
        self,
        video_paths: T.Sequence[Path],
        xml_path: Path,
        num_processes: int | None = None,
    ):
        super().__init__(video_paths, num_processes=num_processes)
        self.xml_path = xml_path

    def _generate_video_extractors(
        self,
    ) -> T.Sequence[GenericVideoExtractor | types.ErrorMetadata]:
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
    def _generate_video_extractors(
        self,
    ) -> T.Sequence[GenericVideoExtractor | types.ErrorMetadata]:
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
