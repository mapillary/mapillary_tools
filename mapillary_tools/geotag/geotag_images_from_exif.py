from __future__ import annotations

import logging
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from .base import GeotagImagesFromGeneric
from .image_extractors.exif import ImageEXIFExtractor

LOG = logging.getLogger(__name__)


class GeotagImagesFromEXIF(GeotagImagesFromGeneric):
    @override
    def _generate_image_extractors(
        self, image_paths: T.Sequence[Path]
    ) -> T.Sequence[ImageEXIFExtractor]:
        return [ImageEXIFExtractor(path) for path in image_paths]
