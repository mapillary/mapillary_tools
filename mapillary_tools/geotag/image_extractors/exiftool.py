# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import contextlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from ... import exif_read, exiftool_read, types
from .exif import ImageEXIFExtractor, invalid_gps_coordinate


class ImageExifToolExtractor(ImageEXIFExtractor):
    def __init__(self, image_path: Path, element: ET.Element):
        super().__init__(image_path)
        self.element = element

    @contextlib.contextmanager
    def _exif_context(self):
        yield exiftool_read.ExifToolRead(ET.ElementTree(self.element))

    @override
    def extract(self) -> types.ImageMetadata:
        self._check_gps_minutes_and_seconds()
        return super().extract()

    def _check_gps_minutes_and_seconds(self) -> None:
        """
        ExifTool, run with -n, gives the EXIF GPS latitude and longitude as the
        degrees that it adds the minutes and seconds up to, even minutes or
        seconds of more than 60, so 10 deg 75' 30" reads as 11.2583 degrees.
        Read the minutes and seconds from the image, and reject them as the
        native source does (see exif_read.gps_to_decimal())
        """
        for tag in ["GPS:GPSLatitude", "GPS:GPSLongitude"]:
            if self.element.find(tag, exiftool_read.EXIFTOOL_NAMESPACES) is None:
                # ExifTool read no coordinates from the EXIF GPS, such as those
                # written at bad offsets, which it drops
                return

        try:
            exif = exif_read.ExifReadFromEXIF(self.image_path)
        except OSError:
            return

        if exif.extract_lon_lat() is None and exif.rejected_gps_coordinate is not None:
            raise invalid_gps_coordinate(exif.rejected_gps_coordinate)
