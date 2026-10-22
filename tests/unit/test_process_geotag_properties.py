# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import typing as T
from pathlib import Path

import pytest
from mapillary_tools import process_geotag_properties as pgp, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import SourceOption, SourceType


class TestSourcesByFileType:
    """
    The sources that each kind of file is geotagged by: --video_geotag_source
    applies to videos, and --geotag_source to images, and to videos as well
    when it is the only one given. A kind of file that neither option names
    gets the default sources.
    """

    @pytest.fixture
    def import_dir(self, tmp_path: Path) -> Path:
        (tmp_path / "image.jpg").touch()
        (tmp_path / "video.mp4").touch()
        return tmp_path

    @staticmethod
    def _sources(
        monkeypatch,
        import_dir: Path,
        geotag_source: list[str],
        video_geotag_source: list[str],
        filetypes: set[types.FileType] | None = None,
    ) -> dict[str, list[SourceType]]:
        """The sources, in order, that process() tries on the image and the video"""
        seen: list[T.Collection[SourceOption]] = []

        def process(paths, options, filetypes=None):
            seen.append(options)
            return []

        monkeypatch.setattr(pgp, "process", process)
        pgp.process_geotag_properties(
            import_dir,
            filetypes,
            geotag_source=geotag_source,
            geotag_source_path=None,
            video_geotag_source=video_geotag_source,
        )

        [options] = seen
        sources: dict[str, list[SourceType]] = {"image": [], "video": []}
        for option in options:
            images, videos = factory._filter_images_and_videos(
                [import_dir / "image.jpg", import_dir / "video.mp4"], option.filetypes
            )
            if images:
                sources["image"].append(option.source)
            if videos:
                sources["video"].append(option.source)
        return sources

    DEFAULT = [SourceType.NATIVE, SourceType.EXIFTOOL_RUNTIME]

    def test_neither_option(self, monkeypatch, import_dir):
        assert self._sources(monkeypatch, import_dir, [], []) == {
            "image": self.DEFAULT,
            "video": self.DEFAULT,
        }

    def test_geotag_source_alone_applies_to_videos_too(self, monkeypatch, import_dir):
        assert self._sources(monkeypatch, import_dir, ["exif"], []) == {
            "image": [SourceType.EXIF],
            "video": [SourceType.EXIF],
        }

    def test_video_geotag_source_alone_leaves_images_the_default(
        self, monkeypatch, import_dir
    ):
        """Images were left with no source at all, and went missing"""
        assert self._sources(monkeypatch, import_dir, [], ["gpx"]) == {
            "image": self.DEFAULT,
            "video": [SourceType.GPX],
        }

    def test_both_options(self, monkeypatch, import_dir):
        assert self._sources(monkeypatch, import_dir, ["exif"], ["gpx"]) == {
            "image": [SourceType.EXIF],
            "video": [SourceType.GPX, SourceType.EXIF],
        }

    def test_video_process_geotags_the_frames_by_the_default(
        self, monkeypatch, import_dir
    ):
        """video_process geotags the frames it samples, which are images only"""
        assert self._sources(
            monkeypatch, import_dir, [], ["native"], filetypes={types.FileType.IMAGE}
        ) == {"image": self.DEFAULT, "video": []}
