# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from mapillary_tools import exceptions, types
from mapillary_tools.exiftool_read import EXIFTOOL_NAMESPACES
from mapillary_tools.geotag import factory
from mapillary_tools.geotag.image_extractors.exif import (
    _capture_unix_time,
    ImageEXIFExtractor,
)
from mapillary_tools.geotag.image_extractors.exiftool import ImageExifToolExtractor
from mapillary_tools.geotag.options import SourceOption, SourcePathOption, SourceType
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


# 47 deg 75' is no coordinate. ExifTool, run with -n, adds it up to 48.25
# degrees
OUT_OF_RANGE_LATITUDE = (47, 75, 0)
LONGITUDE = (8, 30, 0)
INVALID_LATITUDE = (
    "Invalid GPS Latitude 47 deg 75' 0\" in the image: "
    "minutes and seconds must be between 0 and 60"
)


def _write_gps_image(path: Path, latitude: T.Tuple[float, float, float]) -> Path:
    img = Image.new("RGB", (4, 4), (0, 0, 0))
    exif = img.getexif()
    exif.get_ifd(IFD.Exif)[Base.DateTimeOriginal] = "2024:05:01 10:00:00"
    exif.get_ifd(IFD.Exif)[Base.OffsetTimeOriginal] = "+00:00"
    gps = exif.get_ifd(IFD.GPSInfo)
    gps[GPS.GPSLatitudeRef] = "N"
    gps[GPS.GPSLatitude] = tuple(IFDRational(v) for v in latitude)
    gps[GPS.GPSLongitudeRef] = "E"
    gps[GPS.GPSLongitude] = tuple(IFDRational(v) for v in LONGITUDE)
    img.save(path, format="JPEG", exif=exif)
    return path


def _exiftool_reading(latitude: T.Tuple[float, float, float]) -> ET.Element:
    """
    The XML that ExifTool, run with -n, writes for _write_gps_image(): the
    degrees that it adds the minutes and seconds up to
    """

    def degrees(dms: T.Tuple[float, float, float]) -> str:
        return str(dms[0] + dms[1] / 60 + dms[2] / 3600)

    return _exiftool_element(
        {
            "GPS:GPSLatitude": degrees(latitude),
            "GPS:GPSLatitudeRef": "N",
            "GPS:GPSLongitude": degrees(LONGITUDE),
            "GPS:GPSLongitudeRef": "E",
            "ExifIFD:DateTimeOriginal": "2024:05:01 10:00:00",
            "ExifIFD:OffsetTimeOriginal": "+00:00",
        }
    )


class TestGPSMinutesOutOfRange:
    """
    The native reader rejects EXIF GPS minutes or seconds outside [0, 60]. It
    said that it found no GPS, and ExifTool, which reads only the degrees that
    they add up to, geotagged the image elsewhere.
    """

    def test_exif_names_the_invalid_coordinate(self, tmp_path: Path):
        image = _write_gps_image(tmp_path / "image.jpg", OUT_OF_RANGE_LATITUDE)

        with pytest.raises(exceptions.MapillaryInvalidGPSCoordinateError) as info:
            ImageEXIFExtractor(image).extract()

        assert str(info.value) == INVALID_LATITUDE

    def test_exif_skips_it_when_told_to_skip_lonlat_errors(self, tmp_path: Path):
        """As for the capture time that a GPX source reads"""
        image = _write_gps_image(tmp_path / "image.jpg", OUT_OF_RANGE_LATITUDE)

        metadata = ImageEXIFExtractor(image, skip_lonlat_error=True).extract()

        assert (metadata.lat, metadata.lon) == (0.0, 0.0)
        assert (
            metadata.time
            == datetime.datetime(
                2024, 5, 1, 10, tzinfo=datetime.timezone.utc
            ).timestamp()
        )

    def test_exiftool_rejects_it_too(self, tmp_path: Path):
        image = _write_gps_image(tmp_path / "image.jpg", OUT_OF_RANGE_LATITUDE)

        with pytest.raises(exceptions.MapillaryInvalidGPSCoordinateError) as info:
            ImageExifToolExtractor(
                image, _exiftool_reading(OUT_OF_RANGE_LATITUDE)
            ).extract()

        assert str(info.value) == INVALID_LATITUDE

    def test_exiftool_reads_valid_minutes(self, tmp_path: Path):
        latitude = (47, 59, 60)
        image = _write_gps_image(tmp_path / "image.jpg", latitude)

        metadata = ImageExifToolExtractor(image, _exiftool_reading(latitude)).extract()

        assert metadata.lat == pytest.approx(48.0)
        assert metadata.lon == pytest.approx(8.5)

    def test_exiftool_without_gps_coordinates_is_not_checked(self, tmp_path: Path):
        """
        ExifTool drops EXIF GPS coordinates written at bad offsets, and may
        read others elsewhere
        """
        image = _write_gps_image(tmp_path / "image.jpg", OUT_OF_RANGE_LATITUDE)
        element = _exiftool_element(
            {
                "XMP-exif:GPSLatitude": "47.5",
                "XMP-exif:GPSLongitude": "8.5",
                "ExifIFD:DateTimeOriginal": "2024:05:01 10:00:00",
                "ExifIFD:OffsetTimeOriginal": "+00:00",
            }
        )

        metadata = ImageExifToolExtractor(image, element).extract()

        assert (metadata.lat, metadata.lon) == (47.5, 8.5)


class TestGPSMinutesOutOfRangeInFactory:
    """
    ExifTool, after the native reader (as by default), re-reads the same EXIF
    GPS, and geotagged the image that the native reader rejected. A GPX track
    is other data.
    """

    def test_exiftool_does_not_geotag_it(self, monkeypatch, tmp_path: Path):
        image = _write_gps_image(tmp_path / "image.jpg", OUT_OF_RANGE_LATITUDE)
        build_image_geotag = factory._build_image_geotag
        read_by_exiftool: T.List[Path] = []

        class ExifToolReading:
            """ExifTool geotagging at the degrees that the minutes add up to"""

            def to_description(self, paths):
                read_by_exiftool.extend(paths)
                return [
                    types.ImageMetadata(
                        filename=path, time=0, lat=48.25, lon=8.5, alt=None, angle=None
                    )
                    for path in paths
                ]

        def stub(option: SourceOption):
            if option.source is SourceType.EXIFTOOL_RUNTIME:
                return ExifToolReading()
            return build_image_geotag(option)

        monkeypatch.setattr(factory, "_build_image_geotag", stub)

        [result] = factory.process(
            [image],
            [
                SourceOption(SourceType.NATIVE),
                SourceOption(SourceType.EXIFTOOL_RUNTIME),
            ],
        )

        assert read_by_exiftool == []
        assert isinstance(result, types.ErrorMetadata)
        assert isinstance(result.error, exceptions.MapillaryInvalidGPSCoordinateError)
        assert str(result.error) == INVALID_LATITUDE

    def test_a_gpx_track_still_geotags_it(self, tmp_path: Path):
        image = _write_gps_image(tmp_path / "image.jpg", OUT_OF_RANGE_LATITUDE)
        gpx = tmp_path / "track.gpx"
        gpx.write_text(
            '<?xml version="1.0"?>\n'
            '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
            "<trk><trkseg>"
            '<trkpt lat="46.5" lon="7.5"><time>2024-05-01T09:59:00Z</time></trkpt>'
            '<trkpt lat="46.5" lon="7.5"><time>2024-05-01T10:01:00Z</time></trkpt>'
            "</trkseg></trk></gpx>\n"
        )

        [result] = factory.process(
            [image],
            [
                SourceOption(SourceType.NATIVE),
                SourceOption(
                    SourceType.GPX, source_path=SourcePathOption(source_path=gpx)
                ),
            ],
        )

        assert isinstance(result, types.ImageMetadata)
        assert (result.lat, result.lon) == (46.5, 7.5)
