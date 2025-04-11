from __future__ import annotations

import contextlib
import xml.etree.ElementTree as ET
from pathlib import Path

from ... import exiftool_read
from .exif import ImageEXIFExtractor


class ImageExifToolExtractor(ImageEXIFExtractor):
    def __init__(self, image_path: Path, element: ET.Element):
        super().__init__(image_path)
        self.element = element

    @contextlib.contextmanager
    def _exif_context(self):
        yield exiftool_read.ExifToolRead(ET.ElementTree(self.element))
