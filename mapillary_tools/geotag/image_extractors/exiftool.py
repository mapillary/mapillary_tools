# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

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
