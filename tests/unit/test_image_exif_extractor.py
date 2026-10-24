# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from mapillary_tools import exceptions
from mapillary_tools.exiftool_read import EXIFTOOL_NAMESPACES
from mapillary_tools.geotag.image_extractors.exif import (
    _capture_unix_time,
    ImageEXIFExtractor,
)
from mapillary_tools.geotag.image_extractors.exiftool import ImageExifToolExtractor
from PIL import Image
from PIL.ExifTags import Base, GPS, IFD
from PIL.TiffImagePlugin import IFDRational


# What FLIR thermal cameras write for no date
NO_DATE = "0001:01:01 00:00:00"


def _write_image(path: Path, date_time_original: str) -> Path:
    img = Image.new("RGB", (4, 4), (0, 0, 0))
    exif = img.getexif()
    exif.get_ifd(IFD.Exif)[Base.DateTimeOriginal] = date_time_original
    gps = exif.get_ifd(IFD.GPSInfo)
    gps[GPS.GPSLatitudeRef] = "N"
    gps[GPS.GPSLatitude] = (IFDRational(24), IFDRational(33), IFDRational(3636, 100))
    gps[GPS.GPSLongitudeRef] = "W"
    gps[GPS.GPSLongitude] = (IFDRational(81), IFDRational(48), IFDRational(2772, 100))
    img.save(path, format="JPEG", exif=exif)
    return path


def _exiftool_element(tags: T.Dict[str, str]) -> ET.Element:
    root = ET.Element("rdf:Description")
    for tag, value in tags.items():
        prefix, tag_name = tag.split(":", 1)
        child = ET.SubElement(root, "{" + EXIFTOOL_NAMESPACES[prefix] + "}" + tag_name)
        child.text = value
    return root


class TestCaptureTimeWithoutUnixTime:
    """
    A capture time with no Unix time is no capture time. It was read as 1970.
    """

    def test_exif(self, tmp_path: Path):
        image = _write_image(tmp_path / "image.jpg", NO_DATE)

        with pytest.raises(
            exceptions.MapillaryGeoTaggingError, match="Unable to extract timestamp"
        ):
            ImageEXIFExtractor(image).extract()

    def test_exiftool(self, tmp_path: Path):
        image = tmp_path / "image.jpg"
        element = _exiftool_element(
            {
                "GPS:GPSLatitude": "24.5601",
                "GPS:GPSLatitudeRef": "N",
                "GPS:GPSLongitude": "81.8077",
                "GPS:GPSLongitudeRef": "W",
                "ExifIFD:DateTimeOriginal": NO_DATE,
            }
        )

        with pytest.raises(
            exceptions.MapillaryGeoTaggingError, match="Unable to extract timestamp"
        ):
            ImageExifToolExtractor(image, element).extract()

    @pytest.mark.parametrize("error", [ValueError, OverflowError, OSError])
    def test_any_conversion_error(self, error: T.Type[Exception]):
        # Naive times before 1970 raise OSError on Windows
        class Unconvertible(datetime.datetime):
            def timestamp(self) -> float:
                raise error("no Unix time")

        with pytest.raises(
            exceptions.MapillaryGeoTaggingError, match="Unable to extract timestamp"
        ):
            _capture_unix_time(Unconvertible(1969, 12, 31))

    def test_a_valid_capture_time_is_read(self, tmp_path: Path):
        image = _write_image(tmp_path / "image.jpg", "2020:01:02 03:04:05")

        metadata = ImageEXIFExtractor(image).extract()

        assert metadata.time == datetime.datetime(2020, 1, 2, 3, 4, 5).timestamp()
        assert metadata.lat == pytest.approx(24.5601)
        assert metadata.lon == pytest.approx(-81.8077)


def _write_image_with_dates(path: Path, tags: T.Dict[int, str]) -> Path:
    img = Image.new("RGB", (4, 4), (0, 0, 0))
    exif = img.getexif()
    for tag, value in tags.items():
        if tag == Base.DateTime:
            exif[tag] = value
        else:
            exif.get_ifd(IFD.Exif)[tag] = value
    gps = exif.get_ifd(IFD.GPSInfo)
    gps[GPS.GPSLatitudeRef] = "N"
    gps[GPS.GPSLatitude] = (IFDRational(24), IFDRational(33), IFDRational(3636, 100))
    gps[GPS.GPSLongitudeRef] = "W"
    gps[GPS.GPSLongitude] = (IFDRational(81), IFDRational(48), IFDRational(2772, 100))
    img.save(path, format="JPEG", exif=exif)
    return path


class TestPlaceholderCaptureTimes:
    """
    Cameras without a clock write dates before 1970, at which no image was
    captured. One with a time zone offset had a Unix time, and crashed the
    run where the description is written.
    """

    @pytest.mark.parametrize(
        "date",
        [NO_DATE, "1904:02:07 13:28:44", "1969:12:31 19:00:00"],
    )
    def test_exif(self, tmp_path: Path, date: str):
        image = _write_image_with_dates(
            tmp_path / "image.jpg",
            {Base.DateTimeOriginal: date, Base.OffsetTimeOriginal: "+01:00"},
        )

        with pytest.raises(
            exceptions.MapillaryGeoTaggingError, match="Unable to extract timestamp"
        ):
            ImageEXIFExtractor(image).extract()

    def test_exif_reads_the_next_date_tag(self, tmp_path: Path):
        image = _write_image_with_dates(
            tmp_path / "image.jpg",
            {
                Base.DateTimeOriginal: "1904:02:07 13:28:44",
                Base.DateTimeDigitized: "2020:01:02 03:04:05",
            },
        )

        metadata = ImageEXIFExtractor(image).extract()

        assert metadata.time == datetime.datetime(2020, 1, 2, 3, 4, 5).timestamp()

    def test_exif_reads_the_modify_date_last(self, tmp_path: Path):
        image = _write_image_with_dates(
            tmp_path / "image.jpg",
            {
                Base.DateTimeOriginal: NO_DATE,
                Base.DateTimeDigitized: NO_DATE,
                Base.DateTime: "2020:01:02 03:04:05",
            },
        )

        metadata = ImageEXIFExtractor(image).extract()

        assert metadata.time == datetime.datetime(2020, 1, 2, 3, 4, 5).timestamp()

    @pytest.mark.parametrize(
        "date",
        [NO_DATE, "1904:02:07 13:28:44", "1969:12:31 19:00:00"],
    )
    def test_exiftool(self, tmp_path: Path, date: str):
        element = _exiftool_element(
            {
                "GPS:GPSLatitude": "24.5601",
                "GPS:GPSLatitudeRef": "N",
                "GPS:GPSLongitude": "81.8077",
                "GPS:GPSLongitudeRef": "W",
                "ExifIFD:DateTimeOriginal": date,
                "ExifIFD:OffsetTimeOriginal": "+01:00",
            }
        )

        with pytest.raises(
            exceptions.MapillaryGeoTaggingError, match="Unable to extract timestamp"
        ):
            ImageExifToolExtractor(tmp_path / "image.jpg", element).extract()

    def test_exiftool_reads_the_next_date_tag(self, tmp_path: Path):
        element = _exiftool_element(
            {
                "GPS:GPSLatitude": "24.5601",
                "GPS:GPSLatitudeRef": "N",
                "GPS:GPSLongitude": "81.8077",
                "GPS:GPSLongitudeRef": "W",
                "GPS:GPSDateStamp": "1904:02:07",
                "GPS:GPSTimeStamp": "13:28:44",
                "ExifIFD:DateTimeOriginal": "1969:12:31 19:00:00",
                "ExifIFD:CreateDate": "2020:01:02 03:04:05",
            }
        )
        image = tmp_path / "image.jpg"
        image.write_bytes(b"")

        metadata = ImageExifToolExtractor(image, element).extract()

        assert metadata.time == datetime.datetime(2020, 1, 2, 3, 4, 5).timestamp()

    def test_a_capture_time_from_1970_is_read(self, tmp_path: Path):
        image = _write_image_with_dates(
            tmp_path / "image.jpg",
            {
                Base.DateTimeOriginal: "1970:01:02 00:00:00",
                Base.OffsetTimeOriginal: "+00:00",
            },
        )

        metadata = ImageEXIFExtractor(image).extract()

        assert metadata.time == 24 * 3600
