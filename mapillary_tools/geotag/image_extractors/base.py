from __future__ import annotations

import abc
from pathlib import Path

from ... import types


class BaseImageExtractor(abc.ABC):
    """
    Extracts metadata from an image file.
    """

    def __init__(self, image_path: Path):
        self.image_path = image_path

    def extract(self) -> types.ImageMetadataOrError:
        raise NotImplementedError
