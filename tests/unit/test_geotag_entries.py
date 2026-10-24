# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
Every file given to geotag/factory.process gets exactly one entry, but those
that --filetypes leaves out.
"""

from __future__ import annotations

import collections
import shutil
import typing as T
from pathlib import Path

import pytest
from mapillary_tools import exceptions, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import SourceOption, SourcePathOption, SourceType

DATA = Path(__file__).parent.parent / "data"
UNIT_DATA = Path(__file__).parent / "data"

GOPRO_VIDEO = DATA / "gopro_data" / "max-360mode.mp4"
OTHER_VIDEO = DATA / "videos" / "sample-5s.mp4"
GPX = DATA / "gpx" / "sf_30km_h.gpx"


def _inputs(tmp_path: Path) -> tuple[list[Path], list[Path]]:
    """
    Images (one with GPS, one without, one in the folder that sample_video
    writes the frames of the GoPro video to) and videos (a GoPro video, and a
    video without GPS)
    """
    gps_image = tmp_path / "images" / "with_gps.jpg"
    gps_image.parent.mkdir()
    shutil.copyfile(DATA / "images" / "DSC00001.JPG", gps_image)
    no_gps_image = tmp_path / "images" / "no_gps.jpg"
    shutil.copyfile(UNIT_DATA / "empty_exif.jpg", no_gps_image)
    frame = tmp_path / "frames" / GOPRO_VIDEO.name / f"{GOPRO_VIDEO.stem}_0_000001.jpg"
    frame.parent.mkdir(parents=True)
    shutil.copyfile(UNIT_DATA / "test_exif.jpg", frame)
    return [gps_image, no_gps_image, frame], [GOPRO_VIDEO, OTHER_VIDEO]


def _legacy(source: SourceType) -> SourceOption:
    # Geotag images from the videos beside the GoPro video
    return SourceOption(
        source, source_path=SourcePathOption(source_path=GOPRO_VIDEO.parent)
    )


def _limited(source: SourceType, filetypes: set[types.FileType]) -> SourceOption:
    return SourceOption(source, filetypes=filetypes)


def _gpx() -> SourceOption:
    return SourceOption(SourceType.GPX, source_path=SourcePathOption(source_path=GPX))


SOURCES: dict[str, T.Callable[[], list[SourceOption]]] = {
    "native": lambda: [SourceOption(SourceType.NATIVE)],
    "exif": lambda: [SourceOption(SourceType.EXIF)],
    "gpx": lambda: [_gpx()],
    "gopro": lambda: [_legacy(SourceType.GOPRO)],
    "gopro,exif": lambda: [_legacy(SourceType.GOPRO), SourceOption(SourceType.EXIF)],
    "blackvue,native": lambda: [
        _legacy(SourceType.BLACKVUE),
        SourceOption(SourceType.NATIVE),
    ],
    "native for images": lambda: [_limited(SourceType.NATIVE, {types.FileType.IMAGE})],
    "native for gopro, gpx": lambda: [
        _limited(SourceType.NATIVE, {types.FileType.GOPRO}),
        _gpx(),
    ],
}

FILETYPES: dict[str, set[types.FileType] | None] = {
    "all": None,
    "image": {types.FileType.IMAGE},
    "video": {types.FileType.VIDEO},
    "gopro": {types.FileType.GOPRO},
    "image,blackvue": {types.FileType.IMAGE, types.FileType.BLACKVUE},
}


@pytest.mark.parametrize("filetypes_name", FILETYPES)
@pytest.mark.parametrize("sources_name", SOURCES)
def test_every_input_gets_one_entry(
    tmp_path: Path, sources_name: str, filetypes_name: str
):
    images, videos = _inputs(tmp_path)
    filetypes = FILETYPES[filetypes_name]
    options = SOURCES[sources_name]()
    for option in options:
        # As process_geotag_properties limits them
        option.filetypes = types.combine_filetype_filters(option.filetypes, filetypes)
        option.num_processes = 0

    metadatas = factory.process(images + videos, options, filetypes)

    counts = collections.Counter(metadata.filename for metadata in metadatas)
    assert all(count == 1 for count in counts.values()), counts

    # --filetypes leaves out the files of other types: images by their names,
    # and videos once a source reads them as of other types. A source that does
    # not tell the type of a video (gpx) may keep a video of another type
    expected = set()
    if filetypes is None or types.FileType.IMAGE in filetypes:
        expected.update(images)
    if filetypes is None or types.FileType.VIDEO in filetypes:
        expected.update(videos)
    elif types.FileType.GOPRO in filetypes:
        expected.add(GOPRO_VIDEO)
    assert expected <= set(counts) <= expected | set(videos)


def test_an_image_not_a_frame_of_any_video_is_reported(tmp_path: Path):
    """
    The legacy sources that geotag images from videos left out an image that is
    not a frame of any of the videos, as if it had not been given
    """
    images, _ = _inputs(tmp_path)

    metadatas = factory.process(images[:1], [_legacy(SourceType.GOPRO)])

    assert len(metadatas) == 1
    assert isinstance(metadatas[0], types.ErrorMetadata)
    assert isinstance(metadatas[0].error, exceptions.MapillaryGeoTaggingError)
    assert str(metadatas[0].error) == (
        f"Not a frame of any video in {GOPRO_VIDEO.parent}"
    )


def test_a_later_source_geotags_an_image_not_a_frame_of_any_video(tmp_path: Path):
    images, _ = _inputs(tmp_path)

    metadatas = factory.process(
        images[:1], [_legacy(SourceType.GOPRO), SourceOption(SourceType.EXIF)]
    )

    assert len(metadatas) == 1
    assert isinstance(metadatas[0], types.ImageMetadata)
    assert metadatas[0].lat == pytest.approx(45.5169031)


def test_a_file_no_source_describes_is_reported(monkeypatch, tmp_path: Path):
    """
    A file that the sources were let through, but none described, is reported,
    and not left out
    """
    images, _ = _inputs(tmp_path)

    class Silent:
        def to_description(self, paths):
            return []

    monkeypatch.setattr(factory, "_build_image_geotag", lambda option: Silent())

    metadatas = factory.process(images[:1], [SourceOption(SourceType.EXIF)])

    assert len(metadatas) == 1
    assert isinstance(metadatas[0], types.ErrorMetadata)
    assert str(metadatas[0].error) == (
        "The geotag source exif gave no result for this image"
    )
