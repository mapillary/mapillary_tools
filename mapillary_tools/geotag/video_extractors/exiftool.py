from __future__ import annotations

import sys
import typing as T
from pathlib import Path
from xml.etree import ElementTree as ET

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import exceptions, exiftool_read_video, geo, telemetry, types, utils
from ...gpmf import gpmf_gps_filter
from .base import BaseVideoExtractor


class VideoExifToolExtractor(BaseVideoExtractor):
    def __init__(self, video_path: Path, element: ET.Element):
        super().__init__(video_path)
        self.element = element

    @override
    def extract(self) -> types.VideoMetadataOrError:
        exif = exiftool_read_video.ExifToolReadVideo(ET.ElementTree(self.element))

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
                if isinstance(p, telemetry.GPSPoint) and p.ground_speed is not None:
                    p.ground_speed = p.ground_speed / 3.6

            if isinstance(points[0], telemetry.GPSPoint):
                points = T.cast(
                    T.List[geo.Point],
                    gpmf_gps_filter.remove_noisy_points(
                        T.cast(T.List[telemetry.GPSPoint], points)
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
