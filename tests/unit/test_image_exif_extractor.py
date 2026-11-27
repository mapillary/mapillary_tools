# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import os
import time
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest
from mapillary_tools import exceptions
from mapillary_tools.exiftool_read import EXIFTOOL_NAMESPACES
from mapillary_tools.geotag.image_extractors.exif import (
    _capture_unix_time,
    _earlier_file_time,
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


class TestCaptureTimeEdgeCases:
    @pytest.mark.parametrize(
        "date, offset, rejected",
        [
            (NO_DATE, None, "0001-01-01 00:00:00"),
            # 1969-12-31 22:30 in UTC
            ("1970:01:01 00:30:00", "+02:00", "1970-01-01 00:30:00+02:00"),
            # Year 10000 in UTC, in which no capture time can be written
            ("9999:12:31 23:00:00", "-05:00", "9999-12-31 23:00:00-05:00"),
        ],
    )
    def test_exif_names_the_rejected_time(
        self, tmp_path: Path, date: str, offset: T.Optional[str], rejected: str
    ):
        tags = {Base.DateTimeOriginal: date}
        if offset is not None:
            tags[Base.OffsetTimeOriginal] = offset
        image = _write_image_with_dates(tmp_path / "image.jpg", tags)

        with pytest.raises(exceptions.MapillaryGeoTaggingError) as info:
            ImageEXIFExtractor(image).extract()

        assert str(info.value) == (
            f"Unable to extract timestamp from the image: invalid capture time {rejected}"
        )

    def test_exiftool_names_the_rejected_time(self, tmp_path: Path):
        element = _exiftool_element(
            {
                "GPS:GPSLatitude": "24.5601",
                "GPS:GPSLatitudeRef": "N",
                "GPS:GPSLongitude": "81.8077",
                "GPS:GPSLongitudeRef": "W",
                "ExifIFD:DateTimeOriginal": "1970:01:01 00:30:00",
                "ExifIFD:OffsetTimeOriginal": "+02:00",
            }
        )

        with pytest.raises(exceptions.MapillaryGeoTaggingError) as info:
            ImageExifToolExtractor(tmp_path / "image.jpg", element).extract()

        assert str(info.value).endswith(
            "invalid capture time 1970-01-01 00:30:00+02:00"
        )

    def test_1970_is_judged_in_utc(self, tmp_path: Path):
        """1969-12-31 23:30 one hour west of UTC is 1970-01-01 00:30 in UTC"""
        image = _write_image_with_dates(
            tmp_path / "image.jpg",
            {
                Base.DateTimeOriginal: "1969:12:31 23:30:00",
                Base.OffsetTimeOriginal: "-01:00",
            },
        )

        metadata = ImageEXIFExtractor(image).extract()

        assert metadata.time == 1800

    def test_the_next_date_tag_is_read_after_a_rejected_time(self, tmp_path: Path):
        image = _write_image_with_dates(
            tmp_path / "image.jpg",
            {
                Base.DateTimeOriginal: "9999:12:31 23:00:00",
                Base.OffsetTimeOriginal: "-05:00",
                Base.DateTimeDigitized: "2020:01:02 03:04:05",
            },
        )

        metadata = ImageEXIFExtractor(image).extract()

        assert metadata.time == datetime.datetime(2020, 1, 2, 3, 4, 5).timestamp()


# 2024-05-01T10:00:00Z
FILE_TIME = 1714557600.0


def _gps_element(**tags: str) -> ET.Element:
    return _exiftool_element(
        {
            "GPS:GPSLatitude": "24.5601",
            "GPS:GPSLatitudeRef": "N",
            "GPS:GPSLongitude": "81.8077",
            "GPS:GPSLongitudeRef": "W",
            **tags,
        }
    )


class TestFileTimeForImagesWithoutCaptureTime:
    """
    An image with a GPS position but no capture time in its metadata gets the
    earlier of its file modification and creation times, with a warning, but
    not where the capture time places it on a track
    """

    def test_exif(self, tmp_path: Path):
        image = _write_image_with_dates(tmp_path / "image.jpg", {})
        os.utime(image, (FILE_TIME, FILE_TIME))

        metadata = ImageEXIFExtractor(image).extract()

        # On every platform: a creation time is that of the file just written,
        # or moved back to the modification time set (macOS)
        assert metadata.time == FILE_TIME
        assert metadata.lat == pytest.approx(24.5601)
        assert metadata.lon == pytest.approx(-81.8077)
        [warning] = metadata.warnings
        assert isinstance(warning, exceptions.MapillaryFileTimeWarning)
        assert vars(warning) == {
            "file_time": "modification",
            "capture_time": "2024_05_01_10_00_00_000",
        }
        assert str(warning) == (
            f"No capture time found in the metadata of the image {image}: using "
            "its file modification time 2024-05-01T10:00:00+00:00 instead. A "
            "downloaded, exported or copied file has the time of the copy, and "
            "images written in one go get times within seconds of each other, so "
            "a sequence of them is uploaded with the time of the copy or fails as "
            "too fast"
        )

    def test_exiftool(self, tmp_path: Path):
        image = tmp_path / "image.jpg"
        image.write_bytes(b"")
        os.utime(image, (FILE_TIME, FILE_TIME))

        metadata = ImageExifToolExtractor(image, _gps_element()).extract()

        assert metadata.time == FILE_TIME
        assert metadata.lat == pytest.approx(24.5601)
        [warning] = metadata.warnings
        assert isinstance(warning, exceptions.MapillaryFileTimeWarning)

    def test_an_image_on_a_track_still_fails(self, tmp_path: Path):
        """A file time would place it at the wrong position, without a word"""
        image = _write_image_with_dates(tmp_path / "image.jpg", {})
        os.utime(image, (FILE_TIME, FILE_TIME))

        with pytest.raises(exceptions.MapillaryGeoTaggingError) as info:
            ImageEXIFExtractor(image, skip_lonlat_error=True).extract()

        assert str(info.value) == "Unable to extract timestamp from the image"

    def test_an_image_without_gps_still_fails(self, tmp_path: Path):
        image = tmp_path / "image.jpg"
        Image.new("RGB", (4, 4), (0, 0, 0)).save(image, format="JPEG")
        os.utime(image, (FILE_TIME, FILE_TIME))

        with pytest.raises(exceptions.MapillaryGeoTaggingError) as info:
            ImageEXIFExtractor(image).extract()

        assert str(info.value) == (
            "Unable to extract GPS Longitude or GPS Latitude from the image"
        )

    def test_a_placeholder_date_still_fails(self, tmp_path: Path):
        image = _write_image_with_dates(
            tmp_path / "image.jpg", {Base.DateTimeOriginal: NO_DATE}
        )
        os.utime(image, (FILE_TIME, FILE_TIME))

        with pytest.raises(exceptions.MapillaryGeoTaggingError) as info:
            ImageEXIFExtractor(image).extract()

        assert str(info.value).endswith("invalid capture time 0001-01-01 00:00:00")

    def test_a_capture_time_is_read_without_a_warning(self, tmp_path: Path):
        image = _write_image_with_dates(
            tmp_path / "image.jpg", {Base.DateTimeOriginal: "2020:01:02 03:04:05"}
        )
        os.utime(image, (FILE_TIME, FILE_TIME))

        metadata = ImageEXIFExtractor(image).extract()

        assert metadata.time == datetime.datetime(2020, 1, 2, 3, 4, 5).timestamp()
        assert metadata.warnings == []

    def test_an_unreadable_file_time_fails_as_before(self, tmp_path: Path):
        """The image is gone by the time its file time is read"""
        image = tmp_path / "image.jpg"

        with pytest.raises(exceptions.MapillaryGeoTaggingError) as info:
            ImageExifToolExtractor(image, _gps_element()).extract()

        assert str(info.value) == "Unable to extract timestamp from the image"

    @pytest.mark.skipif(
        not hasattr(os.stat_result, "st_birthtime"),
        reason="os.stat() gives no creation time here (Linux, Windows before 3.12)",
    )
    def test_an_earlier_creation_time(self, tmp_path: Path):
        image = _write_image_with_dates(tmp_path / "image.jpg", {})
        later = time.time() + 24 * 3600
        os.utime(image, (later, later))

        metadata = ImageEXIFExtractor(image).extract()

        assert metadata.time == os.stat(image).st_birthtime
        assert metadata.time < later
        [warning] = metadata.warnings
        assert warning.file_time == "creation"


def _stat(**times: float) -> SimpleNamespace:
    return SimpleNamespace(**times)


class TestEarlierFileTime:
    def test_an_earlier_creation_time(self):
        stat = _stat(st_mtime=FILE_TIME + 60, st_birthtime=FILE_TIME, st_ctime=0.0)

        assert _earlier_file_time(stat, platform="darwin") == ("creation", FILE_TIME)

    def test_an_earlier_modification_time(self):
        """Copied with its modification time, the file was created later"""
        stat = _stat(st_mtime=FILE_TIME, st_birthtime=FILE_TIME + 60, st_ctime=0.0)

        assert _earlier_file_time(stat, platform="darwin") == (
            "modification",
            FILE_TIME,
        )

    def test_equal_times_are_the_modification_time(self):
        stat = _stat(st_mtime=FILE_TIME, st_birthtime=FILE_TIME)

        assert _earlier_file_time(stat, platform="darwin") == (
            "modification",
            FILE_TIME,
        )

    def test_linux_ctime_is_no_creation_time(self):
        """It is the time the inode last changed: earlier only by chance"""
        stat = _stat(st_mtime=FILE_TIME + 60, st_ctime=FILE_TIME)

        assert _earlier_file_time(stat, platform="linux") == (
            "modification",
            FILE_TIME + 60,
        )

    def test_windows_ctime_is_the_creation_time_before_python_3_12(self):
        stat = _stat(st_mtime=FILE_TIME + 60, st_ctime=FILE_TIME)

        assert _earlier_file_time(stat, platform="win32") == ("creation", FILE_TIME)

    def test_windows_birthtime_from_python_3_12(self):
        stat = _stat(
            st_mtime=FILE_TIME + 60, st_birthtime=FILE_TIME, st_ctime=FILE_TIME - 60
        )

        assert _earlier_file_time(stat, platform="win32") == ("creation", FILE_TIME)

    @pytest.mark.parametrize("unknown", [0.0, -1.0])
    def test_an_unknown_creation_time_is_ignored(self, unknown: float):
        stat = _stat(st_mtime=FILE_TIME, st_birthtime=unknown)

        assert _earlier_file_time(stat, platform="darwin") == (
            "modification",
            FILE_TIME,
        )

    def test_no_file_time(self):
        stat = _stat(st_mtime=0.0, st_birthtime=-1.0)

        assert _earlier_file_time(stat, platform="darwin") is None
