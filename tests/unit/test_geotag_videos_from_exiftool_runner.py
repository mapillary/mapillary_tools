# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
The exiftool_runtime source reads each video, or the file that its pattern
names after the video, such as the Insta360 original of a stitched video.
"""

from __future__ import annotations

import typing as T
from pathlib import Path

import pytest
from mapillary_tools import exceptions, exiftool_runner, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import SourceOption, SourcePathOption, SourceType


def _rdf(path: Path, model: str) -> str:
    return f"""\
<rdf:Description rdf:about='{path.resolve().as_posix()}'
 xmlns:IFD0='http://ns.exiftool.org/EXIF/IFD0/1.0/'
 xmlns:QuickTime='http://ns.exiftool.org/QuickTime/QuickTime/1.0/'>
 <IFD0:Make>Insta360</IFD0:Make>
 <IFD0:Model>{model}</IFD0:Model>
 <QuickTime:GPSDateTime>2023:08:25 14:19:28Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>47.3598583</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>8.5211333</QuickTime:GPSLongitude>
 <QuickTime:GPSDateTime>2023:08:25 14:19:38Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>47.3594</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>8.5216</QuickTime:GPSLongitude>
</rdf:Description>"""


class _FakeRunner:
    """
    Stands in for ExifTool: the XML of the files it is given, each described as
    a camera model named after the file
    """

    def __init__(self, calls: list[tuple[bool, list[Path]]]):
        self.calls = calls

    def __call__(self, *args, fast: bool = True, **kwargs) -> _FakeRunner:
        self.fast = fast
        return self

    def _build_args_read_stdin(self) -> list[str]:
        return ["exiftool"]

    def extract_xml(self, paths: T.Sequence[Path]) -> str:
        self.calls.append((self.fast, list(paths)))
        descriptions = "\n".join(_rdf(path, path.name) for path in paths)
        return (
            "<?xml version='1.0' encoding='UTF-8'?>\n"
            "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>\n"
            f"{descriptions}\n</rdf:RDF>"
        )


@pytest.fixture
def exiftool_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bool, list[Path]]]:
    calls: list[tuple[bool, list[Path]]] = []
    monkeypatch.setattr(
        "mapillary_tools.geotag.geotag_videos_from_exiftool.ExiftoolRunner",
        _FakeRunner(calls),
    )
    return calls


def _process(video_path: Path, option: SourceOption) -> types.MetadataOrError:
    option.filetypes = {types.FileType.VIDEO}
    [metadata] = factory.process([video_path], [option])
    return metadata


def test_the_video_itself_by_default(tmp_path: Path, exiftool_calls):
    video_path = tmp_path / "stitched" / "VID_00_006.mp4"
    video_path.parent.mkdir()
    video_path.write_bytes(b"")

    metadata = _process(video_path, SourceOption(SourceType.EXIFTOOL_RUNTIME))

    assert isinstance(metadata, types.VideoMetadata)
    assert metadata.filename == video_path
    assert metadata.model == "VID_00_006.mp4"
    assert exiftool_calls == [(False, [video_path.resolve()])]


def test_the_file_the_pattern_names(tmp_path: Path, exiftool_calls):
    video_path = tmp_path / "stitched" / "VID_00_006.mp4"
    video_path.parent.mkdir()
    video_path.write_bytes(b"")
    original_path = tmp_path / "VID_00_006.insv"
    original_path.write_bytes(b"")

    metadata = _process(
        video_path,
        SourceOption(
            SourceType.EXIFTOOL_RUNTIME,
            source_path=SourcePathOption(pattern="../%g.insv"),
        ),
    )

    # The video, with the metadata of its original
    assert isinstance(metadata, types.VideoMetadata)
    assert metadata.filename == video_path
    assert metadata.model == "VID_00_006.insv"
    assert len(metadata.points) == 2
    assert exiftool_calls == [(False, [original_path.resolve()])]


def test_a_file_the_pattern_names_not_found(tmp_path: Path, exiftool_calls):
    video_path = tmp_path / "VID_00_006.mp4"
    video_path.write_bytes(b"")

    metadata = _process(
        video_path,
        SourceOption(
            SourceType.EXIFTOOL_RUNTIME,
            source_path=SourcePathOption(pattern="../%g.insv"),
        ),
    )

    assert isinstance(metadata, types.ErrorMetadata)
    assert isinstance(metadata.error, exceptions.MapillaryVideoGPSNotFoundError)
    assert str(metadata.error).startswith("File not found for video: ")
    assert exiftool_calls == []


def test_not_the_source_path_given_to_every_source(tmp_path: Path, exiftool_calls):
    """
    --geotag_source_path, or the video import path in video_process, is not a
    file for exiftool to read for each video
    """
    video_path = tmp_path / "VID_00_006.mp4"
    video_path.write_bytes(b"")
    gpx_path = tmp_path / "track.gpx"
    gpx_path.write_text("")

    metadata = _process(
        video_path,
        SourceOption(
            SourceType.EXIFTOOL_RUNTIME,
            source_path=SourcePathOption(source_path=gpx_path),
        ),
    )

    assert isinstance(metadata, types.VideoMetadata)
    assert exiftool_calls == [(False, [video_path.resolve()])]


def test_fast_skips_the_end_of_files():
    assert "-fast" in exiftool_runner.ExiftoolRunner()._build_args_read_stdin()
    assert (
        "-fast"
        not in exiftool_runner.ExiftoolRunner(fast=False)._build_args_read_stdin()
    )
