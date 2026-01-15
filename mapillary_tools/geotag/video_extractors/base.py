# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

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

    def extract(self) -> types.VideoMetadata:
        raise NotImplementedError
