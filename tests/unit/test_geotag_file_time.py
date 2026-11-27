# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
An image with a GPS position but no capture time in its metadata gets its file
time from geotag/factory.process, if asked for (--use_file_time_as_capture_time)
and no source reads a capture time for it
"""

from __future__ import annotations

import datetime
import logging
import os
from pathlib import Path

import pytest
from mapillary_tools import constants, exceptions, types
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.options import SourceOption, SourcePathOption, SourceType
from PIL import Image
from PIL.ExifTags import GPS, IFD
from PIL.TiffImagePlugin import IFDRational

GPX = Path(__file__).parent.parent / "data" / "gpx" / "sf_30km_h.gpx"

# 2024-05-01T10:00:00Z
FILE_TIME = 1714557600.0


def _write_image(path: Path, gps: bool = True) -> Path:
    """A JPEG without any date tag, with a GPS position or not"""
    img = Image.new("RGB", (4, 4), (0, 0, 0))
    exif = img.getexif()
    if gps:
        gps_ifd = exif.get_ifd(IFD.GPSInfo)
        gps_ifd[GPS.GPSLatitudeRef] = "N"
        gps_ifd[GPS.GPSLatitude] = (
            IFDRational(24),
            IFDRational(33),
            IFDRational(3636, 100),
        )
        gps_ifd[GPS.GPSLongitudeRef] = "W"
        gps_ifd[GPS.GPSLongitude] = (
            IFDRational(81),
            IFDRational(48),
            IFDRational(2772, 100),
        )
    img.save(path, format="JPEG", exif=exif)
    os.utime(path, (FILE_TIME, FILE_TIME))
    return path


def _write_xml(xml_path: Path, image: Path, date_time_original: str | None) -> Path:
    """The output of exiftool -X for the image: its GPS, and a capture time or not"""
    date = (
        f" <ExifIFD:DateTimeOriginal>{date_time_original}</ExifIFD:DateTimeOriginal>\n"
        if date_time_original is not None
        else ""
    )
    xml_path.write_text(
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>\n"
        f"<rdf:Description rdf:about='{image.resolve().as_posix()}'\n"
        " xmlns:ExifIFD='http://ns.exiftool.org/EXIF/ExifIFD/1.0/'\n"
        " xmlns:GPS='http://ns.exiftool.org/EXIF/GPS/1.0/'>\n"
        " <GPS:GPSLatitudeRef>N</GPS:GPSLatitudeRef>\n"
        " <GPS:GPSLatitude>24.5601</GPS:GPSLatitude>\n"
        " <GPS:GPSLongitudeRef>W</GPS:GPSLongitudeRef>\n"
        " <GPS:GPSLongitude>81.8077</GPS:GPSLongitude>\n"
        f"{date}"
        "</rdf:Description>\n"
        "</rdf:RDF>\n",
        encoding="utf-8",
    )
    return xml_path


def _xml_source(xml_path: Path, use_file_time: bool = True) -> SourceOption:
    return SourceOption(
        SourceType.EXIFTOOL_XML,
        source_path=SourcePathOption(source_path=xml_path),
        use_file_time=use_file_time,
    )


def _native(use_file_time: bool = True) -> SourceOption:
    return SourceOption(SourceType.NATIVE, use_file_time=use_file_time)


def _gpx_source() -> SourceOption:
    return SourceOption(SourceType.GPX, source_path=SourcePathOption(source_path=GPX))


def _file_time_warnings(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
        and "No capture time found" in record.getMessage()
    ]


def test_the_file_time_is_given_with_a_warning(tmp_path: Path, caplog):
    image = _write_image(tmp_path / "image.jpg")

    with caplog.at_level(logging.WARNING):
        [metadata] = factory.process([image], [_native()])

    assert isinstance(metadata, types.ImageMetadata)
    assert metadata.time == FILE_TIME
    assert metadata.lat == pytest.approx(24.5601)
    assert [type(w) for w in metadata.warnings] == [exceptions.MapillaryFileTimeWarning]
    [message] = _file_time_warnings(caplog)
    assert str(image) in message
    assert "file modification time 2024-05-01T10:00:00+00:00" in message


def test_a_later_source_that_reads_a_capture_time_wins(tmp_path: Path, caplog):
    """
    ExifTool reads date tags that the native reader does not: the native
    reader's file time is not kept over the capture time that ExifTool reads
    """
    image = _write_image(tmp_path / "image.jpg")
    xml_path = _write_xml(tmp_path / "image.xml", image, "2020:01:02 03:04:05")

    with caplog.at_level(logging.WARNING):
        [metadata] = factory.process([image], [_native(), _xml_source(xml_path)])

    assert isinstance(metadata, types.ImageMetadata)
    # A naive capture time is in the local time zone
    assert metadata.time == datetime.datetime(2020, 1, 2, 3, 4, 5).timestamp()
    assert metadata.warnings == []
    assert _file_time_warnings(caplog) == []


def test_one_warning_when_every_source_gives_the_file_time(tmp_path: Path, caplog):
    image = _write_image(tmp_path / "image.jpg")
    xml_path = _write_xml(tmp_path / "image.xml", image, None)
    sources: dict[Path, SourceOption] = {}
    xml_source = _xml_source(xml_path)

    with caplog.at_level(logging.WARNING):
        [metadata] = factory.process([image], [_native(), xml_source], sources=sources)

    assert isinstance(metadata, types.ImageMetadata)
    assert metadata.time == FILE_TIME
    assert len(_file_time_warnings(caplog)) == 1
    assert sources == {image: xml_source}


def test_the_file_time_is_kept_when_exiftool_is_missing(
    tmp_path: Path, monkeypatch, caplog
):
    image = _write_image(tmp_path / "image.jpg")
    monkeypatch.setattr(constants, "EXIFTOOL_PATH", str(tmp_path / "no-exiftool"))

    with caplog.at_level(logging.WARNING):
        [metadata] = factory.process(
            [image],
            [
                _native(),
                SourceOption(SourceType.EXIFTOOL_RUNTIME, use_file_time=True),
            ],
        )

    assert isinstance(metadata, types.ImageMetadata)
    assert metadata.time == FILE_TIME
    assert len(_file_time_warnings(caplog)) == 1


@pytest.mark.parametrize("gps", [True, False])
def test_an_image_placed_on_a_gpx_track_still_fails(tmp_path: Path, gps: bool):
    """A file time would place it at a wrong position, without a word"""
    image = _write_image(tmp_path / "image.jpg", gps=gps)

    [metadata] = factory.process([image], [_gpx_source()])

    assert isinstance(metadata, types.ErrorMetadata)
    assert str(metadata.error) == "Unable to extract timestamp from the image"


def test_an_image_without_gps_still_fails(tmp_path: Path):
    image = _write_image(tmp_path / "image.jpg", gps=False)

    [metadata] = factory.process([image], [_native(), _gpx_source()])

    assert isinstance(metadata, types.ErrorMetadata)
    assert str(metadata.error) == "Unable to extract timestamp from the image"


def test_the_image_fails_unless_the_file_time_is_asked_for(tmp_path: Path, caplog):
    image = _write_image(tmp_path / "image.jpg")
    xml_path = _write_xml(tmp_path / "image.xml", image, None)

    with caplog.at_level(logging.WARNING):
        [metadata] = factory.process(
            [image],
            [_native(use_file_time=False), _xml_source(xml_path, use_file_time=False)],
        )

    assert isinstance(metadata, types.ErrorMetadata)
    assert isinstance(metadata.error, exceptions.MapillaryGeoTaggingError)
    assert str(metadata.error).startswith(
        "Unable to extract timestamp from the image: it has a GPS position but no "
        "capture time."
    )
    assert "--use_file_time_as_capture_time" in str(metadata.error)
    assert _file_time_warnings(caplog) == []
