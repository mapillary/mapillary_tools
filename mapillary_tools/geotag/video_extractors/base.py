from __future__ import annotations

import abc
from pathlib import Path

from ... import types


class BaseVideoExtractor(abc.ABC):
    """
    Extracts metadata from a video file.
    """

    def __init__(self, video_path: Path):
        self.video_path = video_path

    def extract(self) -> types.VideoMetadataOrError:
        raise NotImplementedError
