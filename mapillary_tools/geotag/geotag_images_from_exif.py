# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

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
    def __init__(self, num_processes: int | None = None, use_file_time: bool = False):
        super().__init__(num_processes=num_processes)
        self.use_file_time = use_file_time

    @override
    def _generate_image_extractors(
        self, image_paths: T.Sequence[Path]
    ) -> T.Sequence[ImageEXIFExtractor]:
        return [
            ImageEXIFExtractor(path, use_file_time=self.use_file_time)
            for path in image_paths
        ]
