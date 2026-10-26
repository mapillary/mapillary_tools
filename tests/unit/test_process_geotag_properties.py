# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import logging
import typing as T
from pathlib import Path

import pytest
from mapillary_tools import exceptions, process_geotag_properties as pgp, types
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


class TestNamedUnsupportedFiles:
    """
    A file named for processing that is neither an image nor a video was left
    out of the results with only a warning, as if it had not been named
    """

    @staticmethod
    def _process(monkeypatch, import_paths: list[Path]) -> list[types.MetadataOrError]:
        processed: list[Path] = []

        def process(paths, options, filetypes=None):
            processed.extend(paths)
            return []

        monkeypatch.setattr(pgp, "process", process)
        metadatas = pgp.process_geotag_properties(
            import_paths,
            None,
            geotag_source=[],
            geotag_source_path=None,
            video_geotag_source=[],
        )
        assert not processed, "only images and videos are geotagged"
        return metadatas

    def test_named_file_is_failed(self, monkeypatch, tmp_path: Path):
        photo = tmp_path / "photo.png"
        photo.write_bytes(b"not a supported image")

        [metadata] = self._process(monkeypatch, [photo])

        assert isinstance(metadata, types.ErrorMetadata)
        assert metadata.filename == photo
        assert metadata.filetype is None
        assert isinstance(metadata.error, exceptions.MapillaryUnsupportedFileError)
        assert str(metadata.error) == "Not a supported image or video"

    def test_insta360_original_is_told_to_be_stitched(
        self, monkeypatch, tmp_path: Path
    ):
        original = tmp_path / "VID_00_001.insv"
        original.write_bytes(b"not stitched")

        [metadata] = self._process(monkeypatch, [original])

        assert isinstance(metadata, types.ErrorMetadata)
        message = str(metadata.error)
        assert message.startswith("Not a supported image or video. ")
        assert "Insta360 Studio" in message
        assert '{"source": "exiftool_runtime", "pattern": "../%g.insv"}' in message

    def test_named_zip_is_left_to_upload(self, monkeypatch, tmp_path: Path):
        archive = tmp_path / "sequence.zip"
        archive.write_bytes(b"PK")

        assert self._process(monkeypatch, [archive]) == []

    def test_files_in_a_named_directory_are_left_alone(
        self, monkeypatch, tmp_path: Path
    ):
        (tmp_path / "notes.txt").write_bytes(b"not an image")
        (tmp_path / "VID_00_001.insv").write_bytes(b"not stitched")

        assert self._process(monkeypatch, [tmp_path]) == []

    def test_a_file_named_twice_is_failed_once(self, monkeypatch, tmp_path: Path):
        photo = tmp_path / "photo.png"
        photo.write_bytes(b"not a supported image")

        assert len(self._process(monkeypatch, [photo, photo])) == 1


class TestNamedSidecarFiles:
    """
    The files that accompany images and videos, named along with them (as by
    selecting all the files of a camera folder), failed the run, so that
    nothing was uploaded
    """

    @staticmethod
    def _process(
        monkeypatch, import_paths: list[Path]
    ) -> tuple[list[types.MetadataOrError], list[Path]]:
        processed: list[Path] = []

        def process(paths, options, filetypes=None):
            processed.extend(paths)
            return []

        monkeypatch.setattr(pgp, "process", process)
        metadatas = pgp.process_geotag_properties(
            import_paths,
            None,
            geotag_source=[],
            geotag_source_path=None,
            video_geotag_source=[],
        )
        return metadatas, processed

    @pytest.mark.parametrize(
        "name",
        [
            "GH010001.THM",
            "GL010001.LRV",
            "track.gpx",
            "track.NMEA",
            "GH010001.xml",
            "metadata.json",
            "GH010001.SRT",
            "notes.txt",
            "track.csv",
            "logger.log",
            "checksums.md5",
            ".DS_Store",
            "photo.XMP",
            "track.kml",
            "track.KMZ",
            "ride.fit",
            "DJI_0001.LRF",
            "IMG_0001.AAE",
            "Thumbs.db",
            "desktop.ini",
            "Desktop.INI",
        ],
    )
    def test_sidecar_is_skipped_with_a_warning(
        self, monkeypatch, caplog, tmp_path: Path, name: str
    ):
        sidecar = tmp_path / name
        sidecar.write_bytes(b"not an image")

        with caplog.at_level("WARNING"):
            metadatas, processed = self._process(monkeypatch, [sidecar])

        assert metadatas == []
        assert processed == []
        assert (
            f"Skipping {sidecar}, which is not a supported image or video"
            in caplog.text
        )

    def test_apple_double_file_is_not_read_as_an_image(
        self, monkeypatch, caplog, tmp_path: Path
    ):
        image = tmp_path / "GOPR0001.JPG"
        image.write_bytes(b"an image")
        apple_double = tmp_path / "._GOPR0001.JPG"
        apple_double.write_bytes(b"\x00\x05\x16\x07")

        with caplog.at_level("WARNING"):
            metadatas, processed = self._process(monkeypatch, [image, apple_double])

        assert metadatas == []
        assert processed == [image]
        assert f"Skipping {apple_double}" in caplog.text

    def test_other_unsupported_files_are_still_failed(
        self, monkeypatch, tmp_path: Path
    ):
        sidecar = tmp_path / "GH010001.THM"
        original = tmp_path / "VID_00_001.insv"
        for path in [sidecar, original]:
            path.write_bytes(b"not an image")

        [metadata], _ = self._process(monkeypatch, [sidecar, original])

        assert isinstance(metadata, types.ErrorMetadata)
        assert metadata.filename == original
        assert isinstance(metadata.error, exceptions.MapillaryUnsupportedFileError)


class TestVideoImportPath:
    """
    In video_process, the sources without a path of their own read the video
    import path. An exiftool_xml source without a path or a pattern reads the
    XML named after each video beside it first, as in process
    """

    @staticmethod
    def _options(
        monkeypatch,
        import_dir: Path,
        video_geotag_source: list[str],
        geotag_source_path: Path | None = None,
    ) -> list[SourceOption]:
        seen: list[T.Collection[SourceOption]] = []

        def process(paths, options, filetypes=None):
            seen.append(options)
            return []

        monkeypatch.setattr(pgp, "process", process)
        pgp.process_geotag_properties(
            import_dir,
            {types.FileType.IMAGE},
            geotag_source=[],
            geotag_source_path=geotag_source_path,
            video_geotag_source=video_geotag_source,
            video_import_path=Path("/data/videos"),
        )
        [options] = seen
        return list(options)

    def test_exiftool_xml_gets_its_default_pattern(self, monkeypatch, tmp_path):
        option = self._options(monkeypatch, tmp_path, ["exiftool_xml"])[0]

        assert option.source is SourceType.EXIFTOOL_XML
        assert option.source_path is not None
        assert option.source_path.pattern == "%g.xml"
        assert option.source_path.source_path == Path("/data/videos")

    def test_a_pattern_is_kept(self, monkeypatch, tmp_path):
        option = self._options(
            monkeypatch,
            tmp_path,
            ['{"source": "exiftool_xml", "pattern": "%g.gpx.xml"}'],
        )[0]

        assert option.source_path is not None
        assert option.source_path.pattern == "%g.gpx.xml"
        assert option.source_path.source_path == Path("/data/videos")

    def test_other_sources_get_the_import_path_only(self, monkeypatch, tmp_path):
        option = self._options(monkeypatch, tmp_path, ["native"])[0]

        assert option.source_path is not None
        assert option.source_path.pattern is None
        assert option.source_path.source_path == Path("/data/videos")

    def test_geotag_source_path_is_read_as_it_is(self, monkeypatch, tmp_path):
        option = self._options(
            monkeypatch, tmp_path, ["exiftool_xml"], Path("/data/xmls")
        )[0]

        assert option.source_path is not None
        assert option.source_path.pattern is None
        assert option.source_path.source_path == Path("/data/xmls")

    @pytest.mark.parametrize(
        "source",
        [
            "exiftool_xml",
            '{"source": "exiftool_xml", "pattern": "%g.gpx.xml"}',
            '{"source": "gpx", "source_path": "/data/track.gpx"}',
        ],
    )
    def test_no_warning_of_a_geotag_source_path_not_given(
        self, monkeypatch, tmp_path, caplog, source
    ):
        """
        The sources with a path of their own read it, not the video import
        path, without a warning about a --geotag_source_path that was not given
        """
        with caplog.at_level(logging.WARNING):
            self._options(monkeypatch, tmp_path, [source])

        assert "--geotag_source_path" not in caplog.text

    def test_warning_of_a_geotag_source_path_ignored(
        self, monkeypatch, tmp_path, caplog
    ):
        """A source with a path of its own ignores the one the user gave"""
        with caplog.at_level(logging.WARNING):
            [option, *_] = self._options(
                monkeypatch,
                tmp_path,
                ['{"source": "gpx", "source_path": "/data/track.gpx"}'],
                Path("/data/other.gpx"),
            )

        assert option.source_path is not None
        assert option.source_path.source_path == Path("/data/track.gpx")
        assert "The option --geotag_source_path is ignored for source" in caplog.text
