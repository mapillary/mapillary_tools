# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import io
import os
import struct
import typing as T
import xml.etree.ElementTree as ET
from pathlib import Path

import py.path
import pytest
from mapillary_tools import geo
from mapillary_tools.exif_read import (
    _parse_coord,
    ExifRead,
    ExifReadFromEXIF,
    ExifReadFromXMP,
    extract_xmp_efficiently,
    parse_datetimestr_with_subsec_and_offset,
    XMP_NAMESPACES,
)
from mapillary_tools.exif_write import ExifEdit

"""Initialize all the neccessary data"""

this_file = os.path.abspath(__file__)
this_file_dir = os.path.dirname(this_file)
data_dir = os.path.join(this_file_dir, "data")

TEST_EXIF_FILE = Path(os.path.join(data_dir, "test_exif.jpg"))


@pytest.fixture
def setup_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(data_dir)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


def gps_to_decimal(value, ref):
    sign = 1 if ref in "NE" else -1
    degrees, minutes, seconds = value
    return sign * (float(degrees) + float(minutes) / 60 + float(seconds) / 3600)


def test_read_orientation_general():
    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    orientation_ExifRead = exif_data_ExifRead.extract_orientation()
    assert 2 == orientation_ExifRead


def test_read_date_time_original_general():
    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    capture_time_ExifRead = exif_data_ExifRead.extract_capture_time()
    # exiftool -time:all tests/unit/data/test_exif.jpg
    # Date/Time Original              : 2018:06:26 17:46:33.847
    # Create Date                     : 2011:07:15 11:14:39
    # Sub Sec Time                    : 000005
    # GPS Time Stamp                  : 09:14:39
    # GPS Date Stamp                  : 2011:07:15
    # GPS Date/Time                   : 2011:07:15 09:14:39Z
    assert (
        datetime.datetime.fromisoformat("2011-07-15T09:14:39+00:00")
        == capture_time_ExifRead
    )
    # note it is not: datetime.datetime.fromisoformat("2018-06-26T17:46:33.000005") == capture_time_ExifRead
    # because "Sub Sec Time" is not subsec for "Date/Time Original"


def test_read_lat_lon_general():
    latitude_PIL, latitudeRef_PIL = (35.0, 54.0, 45.06), "N"
    longitude_PIL, longitudeRef_PIL = (14.0, 29.0, 55.7), "E"

    latitude_PIL = gps_to_decimal(latitude_PIL, latitudeRef_PIL)
    longitude_PIL = gps_to_decimal(longitude_PIL, longitudeRef_PIL)

    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    lonlat = exif_data_ExifRead.extract_lon_lat()
    assert lonlat
    longitude_ExifRead, latitude_ExifRead = lonlat

    assert (latitude_PIL, longitude_PIL) == (latitude_ExifRead, longitude_ExifRead)


def test_read_camera_make_model_general():
    make_PIL = "HTC"
    model_PIL = "Legend"

    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    make_ExifRead = exif_data_ExifRead.extract_make()
    model_ExifRead = exif_data_ExifRead.extract_model()

    assert (make_PIL, model_PIL) == (make_ExifRead, model_ExifRead)


def test_read_altitude_general():
    numerator = 69
    denominator = 1

    altitude_value_PIL = numerator / denominator

    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    altitude_ExifRead = exif_data_ExifRead.extract_altitude()

    assert altitude_value_PIL == altitude_ExifRead


def test_read_direction_general():
    numerator = 100
    denominator = 100
    direction_value_PIL = numerator / denominator

    exif_data_ExifRead = ExifRead(TEST_EXIF_FILE)
    direction_ExifRead = exif_data_ExifRead.extract_direction()

    assert direction_value_PIL == direction_ExifRead


def test_parse():
    dt = parse_datetimestr_with_subsec_and_offset("2019:02:01 12:13:14")
    assert dt
    assert dt.tzinfo is None
    assert dt.timetuple() == (2019, 2, 1, 12, 13, 14, 4, 32, -1)

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:03:03 23:00:00.123", "456", "+12:12:11"
    )
    assert str(dt) == "2019-03-03 23:00:00.456000+12:12:11"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 22:00:00.123", "1456", "+12:34"
    )
    assert str(dt) == "2019-01-01 22:00:00.145600+12:34"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 22:00:00.123", "0456", "+12:34"
    )
    assert str(dt) == "2019-01-01 22:00:00.045600+12:34"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 01:00:00.123456789", None, "-10:34"
    )
    assert str(dt) == "2019-01-01 01:00:00.123457-10:34"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 01:00:00.123456789", None, "-24:00"
    )
    assert str(dt) == "2019-01-01 01:00:00.123457+00:00"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 01:00:00.123456789", None, "24:00"
    )
    assert str(dt) == "2019-01-01 01:00:00.123457+00:00"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 01:00:00.123456789", None, "24:23"
    )
    assert str(dt) == "2019-01-01 01:00:00.123457+00:23"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 24:00:00.123456789", None, "24:23"
    )
    assert str(dt) == "2019-01-02 00:00:00.123457+00:23"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019:01:01 24:88:00.123456789", None, "-24:23"
    )
    assert str(dt) == "2019-01-02 01:28:00.123457-00:23"

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.123456Z",
    )
    assert str(dt) == "2019-01-01 12:22:00.123456+00:00", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.123456+11:00",
    )
    assert str(dt) == "2019-01-01 12:22:00.123456+11:00", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.456789+11:00", "123", "+01:00"
    )
    assert str(dt) == "2019-01-01 12:22:00.123000+01:00", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.123456",
    )
    assert str(dt) == "2019-01-01 12:22:00.123456", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2019-01-01T12:22:00.123",
    )
    assert str(dt) == "2019-01-01 12:22:00.123000", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2021:10:10 17:29:54.124+02:00",
    )
    assert str(dt) == "2021-10-10 17:29:54.124000+02:00", dt

    dt = parse_datetimestr_with_subsec_and_offset(
        "2021:10:10 17:29:54.124-02:00",
    )
    assert str(dt) == "2021-10-10 17:29:54.124000-02:00", dt


@pytest.mark.parametrize(
    "raw_coord,raw_ref,expected",
    [
        (None, "", None),
        ("foo", "N", None),
        ("0.0", "foo", None),
        ("0.0", "N", 0),
        ("1.5", "N", 1.5),
        ("1.5", "S", -1.5),
        ("-1.5", "N", -1.5),
        ("-1.5", "S", 1.5),
        ("-1.5", "S", 1.5),
        ("33,18.32N", "N", 33.30533),
        ("33,18.32N", "S", 33.30533),
        ("33,18.32S", "", -33.30533),
        ("44,24.54E", "", 44.40900),
        ("44,24.54W", "", -44.40900),
    ],
)
def test_parse_coordinates(
    raw_coord: T.Optional[str], raw_ref: str, expected: T.Optional[float]
):
    assert _parse_coord(raw_coord, raw_ref) == pytest.approx(expected)


# test ExifWrite write a timestamp and ExifRead read it back
def test_read_and_write(setup_data: py.path.local):
    image_path = Path(setup_data, "test_exif.jpg")
    dts = [
        datetime.datetime.now(),
        datetime.datetime.now(datetime.timezone.utc),
        # 86400 is total seconds of one day (24 * 3600)
        # to avoid "OSError: [Errno 22] Invalid argument" in WINDOWS https://bugs.python.org/issue36759
        datetime.datetime.fromtimestamp(86400),
        datetime.datetime.fromtimestamp(86400, tz=datetime.timezone.utc),
        datetime.datetime.fromtimestamp(86400.0000001, tz=datetime.timezone.utc),
        datetime.datetime.fromtimestamp(86400.123456, tz=datetime.timezone.utc),
        datetime.datetime.fromtimestamp(86400.0123, tz=datetime.timezone.utc),
    ]
    dts = dts[:] + [dt.astimezone() for dt in dts]
    dts = dts[:] + [dt.astimezone(datetime.timezone.utc) for dt in dts]

    for dt in dts:
        edit = ExifEdit(image_path)
        edit.add_gps_datetime(dt)
        edit.add_date_time_original(dt)
        edit.write()
        read = ExifRead(image_path)
        actual = read.extract_capture_time()
        assert actual
        assert geo.as_unix_time(dt) == geo.as_unix_time(actual), (dt, actual)

    for dt in dts:
        edit = ExifEdit(image_path)
        edit.add_gps_datetime(dt)
        edit.write()
        read = ExifRead(image_path)
        actual = read.extract_gps_datetime()
        assert actual
        assert geo.as_unix_time(dt) == geo.as_unix_time(actual)


# Tests for extract_camera_uuid


class MockExifTag:
    """Mock class for exifread tag values"""

    def __init__(self, values):
        self.values = values


class TestExtractCameraUuidFromEXIF:
    """Test extract_camera_uuid from EXIF tags"""

    def test_body_serial_only(self):
        """Test with only body serial number present"""

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF BodySerialNumber": MockExifTag("ABC123"),
        }
        assert reader.extract_camera_uuid() == "ABC123"

    def test_lens_serial_only(self):
        """Test with only lens serial number present"""

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF LensSerialNumber": MockExifTag("LNS456"),
        }
        assert reader.extract_camera_uuid() == "LNS456"

    def test_both_body_and_lens_serial(self):
        """Test with both body and lens serial numbers present"""

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF BodySerialNumber": MockExifTag("BODY123"),
            "EXIF LensSerialNumber": MockExifTag("LENS456"),
        }
        assert reader.extract_camera_uuid() == "BODY123_LENS456"

    def test_no_serial_numbers(self):
        """Test with no serial numbers present"""

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {}
        assert reader.extract_camera_uuid() is None

    def test_generic_serial_fallback(self):
        """Test fallback to generic EXIF SerialNumber"""

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF SerialNumber": MockExifTag("GENERIC789"),
        }
        assert reader.extract_camera_uuid() == "GENERIC789"

    def test_makernote_serial_fallback(self):
        """Test fallback to MakerNote SerialNumber"""

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "MakerNote SerialNumber": MockExifTag("MAKER123"),
        }
        assert reader.extract_camera_uuid() == "MAKER123"

    def test_body_serial_priority_over_generic(self):
        """Test that BodySerialNumber takes priority over generic SerialNumber"""

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF BodySerialNumber": MockExifTag("BODY123"),
            "EXIF SerialNumber": MockExifTag("GENERIC789"),
        }
        assert reader.extract_camera_uuid() == "BODY123"

    def test_whitespace_stripped(self):
        """Test that whitespace is stripped from serial numbers"""

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF BodySerialNumber": MockExifTag("  BODY123  "),
            "EXIF LensSerialNumber": MockExifTag("  LENS456  "),
        }
        assert reader.extract_camera_uuid() == "BODY123_LENS456"

    def test_special_characters_removed(self):
        """Test that special characters are removed from serial numbers"""

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF BodySerialNumber": MockExifTag("BODY-123:456"),
            "EXIF LensSerialNumber": MockExifTag("LENS/789.ABC"),
        }
        assert reader.extract_camera_uuid() == "BODY123456_LENS789ABC"


class TestExtractCameraUuidFromXMP:
    """Test extract_camera_uuid from XMP tags"""

    def _create_xmp_reader(self, tags_dict: dict):
        """Helper to create an ExifReadFromXMP with mocked tags"""
        # Build a minimal XMP document
        rdf_ns = XMP_NAMESPACES["rdf"]
        xmp_xml = f'''<?xml version="1.0"?>
        <x:xmpmeta xmlns:x="adobe:ns:meta/">
            <rdf:RDF xmlns:rdf="{rdf_ns}">
                <rdf:Description'''

        # Add namespace declarations
        for prefix, uri in XMP_NAMESPACES.items():
            if prefix in ["rdf", "x"]:
                continue
            xmp_xml += f' xmlns:{prefix}="{uri}"'

        # Add attributes
        for key, value in tags_dict.items():
            xmp_xml += f' {key}="{value}"'

        xmp_xml += """>
                </rdf:Description>
            </rdf:RDF>
        </x:xmpmeta>"""

        etree = ET.ElementTree(ET.fromstring(xmp_xml))
        return ExifReadFromXMP(etree)

    def test_xmp_body_serial_only(self):
        """Test XMP with only body serial number"""
        reader = self._create_xmp_reader({"exifEX:BodySerialNumber": "XMPBODY123"})
        assert reader.extract_camera_uuid() == "XMPBODY123"

    def test_xmp_lens_serial_only(self):
        """Test XMP with only lens serial number"""
        reader = self._create_xmp_reader({"exifEX:LensSerialNumber": "XMPLENS456"})
        assert reader.extract_camera_uuid() == "XMPLENS456"

    def test_xmp_both_serials(self):
        """Test XMP with both body and lens serial numbers"""
        reader = self._create_xmp_reader(
            {
                "exifEX:BodySerialNumber": "XMPBODY",
                "exifEX:LensSerialNumber": "XMPLENS",
            }
        )
        assert reader.extract_camera_uuid() == "XMPBODY_XMPLENS"

    def test_xmp_no_serials(self):
        """Test XMP with no serial numbers"""
        reader = self._create_xmp_reader({})
        assert reader.extract_camera_uuid() is None

    def test_xmp_aux_serial_number(self):
        """Test XMP with aux:SerialNumber (Adobe auxiliary namespace)"""
        reader = self._create_xmp_reader({"aux:SerialNumber": "AUXSERIAL123"})
        assert reader.extract_camera_uuid() == "AUXSERIAL123"

    def test_xmp_aux_lens_serial_number(self):
        """Test XMP with aux:LensSerialNumber"""
        reader = self._create_xmp_reader({"aux:LensSerialNumber": "AUXLENS456"})
        assert reader.extract_camera_uuid() == "AUXLENS456"


class TestExtractCameraUuidIntegration:
    """Integration tests using real image file"""

    def test_real_image_camera_uuid(self):
        """Test extract_camera_uuid on test image (likely returns None as test image may not have serial)"""
        exif_data = ExifRead(TEST_EXIF_FILE)
        # The test image likely doesn't have serial numbers, so we just verify it doesn't crash
        result = exif_data.extract_camera_uuid()
        assert result is None or isinstance(result, str)


def _build_xmp_doc(tags: T.Dict[str, str]) -> str:
    """Build an XMP packet whose rdf:Description carries ``tags`` as attributes."""
    rdf_ns = XMP_NAMESPACES["rdf"]
    xml = (
        '<?xml version="1.0"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        f'<rdf:RDF xmlns:rdf="{rdf_ns}">'
        "<rdf:Description"
    )
    for prefix, uri in XMP_NAMESPACES.items():
        if prefix in ("rdf", "x"):
            continue
        xml += f' xmlns:{prefix}="{uri}"'
    for key, value in tags.items():
        xml += f' {key}="{value}"'
    xml += "></rdf:Description></rdf:RDF></x:xmpmeta>"
    return xml


def _make_xmp_reader(tags: T.Dict[str, str]) -> ExifReadFromXMP:
    return ExifReadFromXMP(ET.ElementTree(ET.fromstring(_build_xmp_doc(tags))))


def _build_jpeg_with_xmp(xmp_xml: str) -> bytes:
    """Build a minimal JPEG containing ``xmp_xml`` in an APP1 XMP segment."""
    identifier = b"http://ns.adobe.com/xap/1.0/\x00"
    payload = identifier + xmp_xml.encode("utf-8")
    # APP1 length field counts itself (2 bytes) plus the payload
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return b"\xff\xd8" + app1 + b"\xff\xd9"  # SOI ... EOI


class TestExifReadFromXMPMetadata:
    """Tests for reading metadata from XMP."""

    def test_extract_altitude(self):
        assert (
            _make_xmp_reader({"exif:GPSAltitude": "123.5"}).extract_altitude() == 123.5
        )

    def test_extract_altitude_missing(self):
        assert _make_xmp_reader({}).extract_altitude() is None

    def test_extract_lon_lat_numeric(self):
        reader = _make_xmp_reader(
            {
                "exif:GPSLatitude": "50.5",
                "exif:GPSLatitudeRef": "N",
                "exif:GPSLongitude": "15.5",
                "exif:GPSLongitudeRef": "E",
            }
        )
        assert reader.extract_lon_lat() == (15.5, 50.5)

    def test_extract_lon_lat_adobe_format(self):
        reader = _make_xmp_reader(
            {
                "exif:GPSLatitude": "33,18.32N",
                "exif:GPSLatitudeRef": "N",
                "exif:GPSLongitude": "44,24.54E",
                "exif:GPSLongitudeRef": "E",
            }
        )
        lonlat = reader.extract_lon_lat()
        assert lonlat is not None
        lon, lat = lonlat
        assert lat == pytest.approx(33.30533, abs=1e-4)
        assert lon == pytest.approx(44.40900, abs=1e-4)

    def test_extract_lon_lat_missing(self):
        assert _make_xmp_reader({}).extract_lon_lat() is None

    def test_extract_make_and_model_stripped(self):
        reader = _make_xmp_reader({"tiff:Make": "Canon ", "tiff:Model": " EOS "})
        assert reader.extract_make() == "Canon"
        assert reader.extract_model() == "EOS"

    def test_extract_make_lens_fallback(self):
        assert (
            _make_xmp_reader({"exifEX:LensMake": "LensCo"}).extract_make() == "LensCo"
        )

    def test_extract_make_missing(self):
        assert _make_xmp_reader({}).extract_make() is None
        assert _make_xmp_reader({}).extract_model() is None

    def test_extract_width_height(self):
        reader = _make_xmp_reader(
            {"exif:PixelXDimension": "1920", "exif:PixelYDimension": "1080"}
        )
        assert reader.extract_width() == 1920
        assert reader.extract_height() == 1080

    def test_extract_width_height_gpano_fallback(self):
        assert (
            _make_xmp_reader({"GPano:FullPanoWidthPixels": "4096"}).extract_width()
            == 4096
        )
        assert (
            _make_xmp_reader(
                {"GPano:CroppedAreaImageHeightPixels": "2048"}
            ).extract_height()
            == 2048
        )

    def test_extract_orientation(self):
        assert _make_xmp_reader({"tiff:Orientation": "3"}).extract_orientation() == 3

    def test_extract_orientation_invalid_defaults_to_1(self):
        assert _make_xmp_reader({"tiff:Orientation": "99"}).extract_orientation() == 1

    def test_extract_orientation_missing_defaults_to_1(self):
        assert _make_xmp_reader({}).extract_orientation() == 1

    def test_extract_direction(self):
        assert (
            _make_xmp_reader({"exif:GPSImgDirection": "180.5"}).extract_direction()
            == 180.5
        )

    def test_extract_direction_track_fallback(self):
        assert _make_xmp_reader({"exif:GPSTrack": "90.0"}).extract_direction() == 90.0

    def test_extract_direction_missing(self):
        assert _make_xmp_reader({}).extract_direction() is None

    def test_extract_exif_datetime(self):
        reader = _make_xmp_reader({"exif:DateTimeOriginal": "2021:07:15 15:37:30"})
        assert reader.extract_exif_datetime() == datetime.datetime(
            2021, 7, 15, 15, 37, 30
        )

    def test_extract_exif_datetime_digitized_fallback(self):
        reader = _make_xmp_reader({"exif:DateTimeDigitized": "2020:01:02 03:04:05"})
        assert reader.extract_exif_datetime() == datetime.datetime(2020, 1, 2, 3, 4, 5)

    def test_extract_exif_datetime_missing(self):
        assert _make_xmp_reader({}).extract_exif_datetime() is None

    def test_extract_gps_datetime_iso(self):
        reader = _make_xmp_reader({"exif:GPSTimeStamp": "2021-07-15T05:37:30Z"})
        assert reader.extract_gps_datetime() == datetime.datetime(
            2021, 7, 15, 5, 37, 30, tzinfo=datetime.timezone.utc
        )

    def test_extract_gps_datetime_separate_date_and_time(self):
        reader = _make_xmp_reader(
            {
                "exif:GPSDateStamp": "2021:07:15",
                "exif:GPSTimeStamp": "05:37:30",
            }
        )
        assert reader.extract_gps_datetime() == datetime.datetime(
            2021, 7, 15, 5, 37, 30, tzinfo=datetime.timezone.utc
        )

    def test_extract_gps_datetime_missing(self):
        assert _make_xmp_reader({}).extract_gps_datetime() is None

    def test_extract_capture_time_prefers_gps(self):
        reader = _make_xmp_reader(
            {
                "exif:GPSTimeStamp": "2021-07-15T05:37:30Z",
                "exif:DateTimeOriginal": "2000:01:01 00:00:00",
            }
        )
        assert reader.extract_capture_time() == datetime.datetime(
            2021, 7, 15, 5, 37, 30, tzinfo=datetime.timezone.utc
        )

    def test_extract_capture_time_falls_back_to_exif(self):
        reader = _make_xmp_reader({"exif:DateTimeOriginal": "2021:07:15 15:37:30"})
        assert reader.extract_capture_time() == datetime.datetime(
            2021, 7, 15, 15, 37, 30
        )

    def test_extract_capture_time_missing(self):
        assert _make_xmp_reader({}).extract_capture_time() is None


class TestExtractXmpEfficiently:
    """Tests for locating XMP metadata embedded in a JPEG."""

    def test_returns_xmp_when_present(self):
        xmp = _build_xmp_doc({"tiff:Make": "Canon"})
        result = extract_xmp_efficiently(io.BytesIO(_build_jpeg_with_xmp(xmp)))
        assert result is not None
        assert "<x:xmpmeta" in result
        assert "</x:xmpmeta>" in result

    def test_returns_none_without_soi(self):
        assert extract_xmp_efficiently(io.BytesIO(b"not a jpeg")) is None

    def test_returns_none_when_no_xmp_segment(self):
        # SOI immediately followed by EOI: valid JPEG start, no APP1/XMP
        assert extract_xmp_efficiently(io.BytesIO(b"\xff\xd8\xff\xd9")) is None

    def test_skips_non_xmp_app1_segment(self):
        # An APP1 segment that is not XMP (e.g. an EXIF identifier) is skipped,
        # and the following XMP APP1 segment is still found.
        exif_id = b"Exif\x00\x00rest-of-exif"
        exif_app1 = b"\xff\xe1" + struct.pack(">H", len(exif_id) + 2) + exif_id
        xmp_app1 = _build_jpeg_with_xmp(_build_xmp_doc({"tiff:Make": "Canon"}))[2:]
        data = b"\xff\xd8" + exif_app1 + xmp_app1
        result = extract_xmp_efficiently(io.BytesIO(data))
        assert result is not None
        assert "Canon" in result


class TestExifReadXmpFallback:
    """Reading metadata from a JPEG whose values live in XMP, not EXIF."""

    def _make_reader(self, tags: T.Dict[str, str]) -> ExifRead:
        jpeg = _build_jpeg_with_xmp(_build_xmp_doc(tags))
        return ExifRead(io.BytesIO(jpeg))

    def test_make_model_fallback(self):
        reader = self._make_reader({"tiff:Make": "XMPMake", "tiff:Model": "XMPModel"})
        assert reader.extract_make() == "XMPMake"
        assert reader.extract_model() == "XMPModel"

    def test_altitude_fallback(self):
        assert (
            self._make_reader({"exif:GPSAltitude": "123.5"}).extract_altitude() == 123.5
        )

    def test_lon_lat_fallback(self):
        reader = self._make_reader(
            {
                "exif:GPSLatitude": "50.5",
                "exif:GPSLatitudeRef": "N",
                "exif:GPSLongitude": "15.5",
                "exif:GPSLongitudeRef": "E",
            }
        )
        assert reader.extract_lon_lat() == (15.5, 50.5)

    def test_width_height_fallback(self):
        reader = self._make_reader(
            {"exif:PixelXDimension": "1920", "exif:PixelYDimension": "1080"}
        )
        assert reader.extract_width() == 1920
        assert reader.extract_height() == 1080

    def test_capture_time_fallback(self):
        reader = self._make_reader({"exif:DateTimeOriginal": "2020:01:02 03:04:05"})
        assert reader.extract_capture_time() == datetime.datetime(2020, 1, 2, 3, 4, 5)

    def test_camera_uuid_fallback(self):
        reader = self._make_reader(
            {"exif:SerialNumber": "BODYX", "exif:LensSerialNumber": "LENSY"}
        )
        assert reader.extract_camera_uuid() == "BODYX_LENSY"

    def test_no_xmp_and_no_exif_returns_none(self):
        # A JPEG with neither EXIF nor XMP: every extractor returns None.
        reader = ExifRead(io.BytesIO(b"\xff\xd8\xff\xd9"))
        assert reader.extract_make() is None
        assert reader.extract_lon_lat() is None
        assert reader.extract_capture_time() is None
        assert reader.extract_camera_uuid() is None
