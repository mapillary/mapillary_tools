# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import datetime
import os
import typing as T
from pathlib import Path

import py.path
import pytest
from mapillary_tools import geo
from mapillary_tools.exif_read import (
    _parse_coord,
    ExifRead,
    parse_datetimestr_with_subsec_and_offset,
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
        from mapillary_tools.exif_read import ExifReadFromEXIF

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF BodySerialNumber": MockExifTag("ABC123"),
        }
        assert reader.extract_camera_uuid() == "ABC123"

    def test_lens_serial_only(self):
        """Test with only lens serial number present"""
        from mapillary_tools.exif_read import ExifReadFromEXIF

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF LensSerialNumber": MockExifTag("LNS456"),
        }
        assert reader.extract_camera_uuid() == "LNS456"

    def test_both_body_and_lens_serial(self):
        """Test with both body and lens serial numbers present"""
        from mapillary_tools.exif_read import ExifReadFromEXIF

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF BodySerialNumber": MockExifTag("BODY123"),
            "EXIF LensSerialNumber": MockExifTag("LENS456"),
        }
        assert reader.extract_camera_uuid() == "BODY123_LENS456"

    def test_no_serial_numbers(self):
        """Test with no serial numbers present"""
        from mapillary_tools.exif_read import ExifReadFromEXIF

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {}
        assert reader.extract_camera_uuid() is None

    def test_generic_serial_fallback(self):
        """Test fallback to generic EXIF SerialNumber"""
        from mapillary_tools.exif_read import ExifReadFromEXIF

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF SerialNumber": MockExifTag("GENERIC789"),
        }
        assert reader.extract_camera_uuid() == "GENERIC789"

    def test_makernote_serial_fallback(self):
        """Test fallback to MakerNote SerialNumber"""
        from mapillary_tools.exif_read import ExifReadFromEXIF

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "MakerNote SerialNumber": MockExifTag("MAKER123"),
        }
        assert reader.extract_camera_uuid() == "MAKER123"

    def test_body_serial_priority_over_generic(self):
        """Test that BodySerialNumber takes priority over generic SerialNumber"""
        from mapillary_tools.exif_read import ExifReadFromEXIF

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF BodySerialNumber": MockExifTag("BODY123"),
            "EXIF SerialNumber": MockExifTag("GENERIC789"),
        }
        assert reader.extract_camera_uuid() == "BODY123"

    def test_whitespace_stripped(self):
        """Test that whitespace is stripped from serial numbers"""
        from mapillary_tools.exif_read import ExifReadFromEXIF

        reader = ExifReadFromEXIF.__new__(ExifReadFromEXIF)
        reader.tags = {
            "EXIF BodySerialNumber": MockExifTag("  BODY123  "),
            "EXIF LensSerialNumber": MockExifTag("  LENS456  "),
        }
        assert reader.extract_camera_uuid() == "BODY123_LENS456"


class TestExtractCameraUuidFromXMP:
    """Test extract_camera_uuid from XMP tags"""

    def _create_xmp_reader(self, tags_dict: dict):
        """Helper to create an ExifReadFromXMP with mocked tags"""
        from mapillary_tools.exif_read import ExifReadFromXMP, XMP_NAMESPACES
        import xml.etree.ElementTree as ET

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
        reader = self._create_xmp_reader({"exifEX:BodySerialNumber": "XMP_BODY123"})
        assert reader.extract_camera_uuid() == "XMP_BODY123"

    def test_xmp_lens_serial_only(self):
        """Test XMP with only lens serial number"""
        reader = self._create_xmp_reader({"exifEX:LensSerialNumber": "XMP_LENS456"})
        assert reader.extract_camera_uuid() == "XMP_LENS456"

    def test_xmp_both_serials(self):
        """Test XMP with both body and lens serial numbers"""
        reader = self._create_xmp_reader(
            {
                "exifEX:BodySerialNumber": "XMP_BODY",
                "exifEX:LensSerialNumber": "XMP_LENS",
            }
        )
        assert reader.extract_camera_uuid() == "XMP_BODY_XMP_LENS"

    def test_xmp_no_serials(self):
        """Test XMP with no serial numbers"""
        reader = self._create_xmp_reader({})
        assert reader.extract_camera_uuid() is None

    def test_xmp_aux_serial_number(self):
        """Test XMP with aux:SerialNumber (Adobe auxiliary namespace)"""
        reader = self._create_xmp_reader({"aux:SerialNumber": "AUX_SERIAL123"})
        assert reader.extract_camera_uuid() == "AUX_SERIAL123"

    def test_xmp_aux_lens_serial_number(self):
        """Test XMP with aux:LensSerialNumber"""
        reader = self._create_xmp_reader({"aux:LensSerialNumber": "AUX_LENS456"})
        assert reader.extract_camera_uuid() == "AUX_LENS456"


class TestExtractCameraUuidIntegration:
    """Integration tests using real image file"""

    def test_real_image_camera_uuid(self):
        """Test extract_camera_uuid on test image (likely returns None as test image may not have serial)"""
        exif_data = ExifRead(TEST_EXIF_FILE)
        # The test image likely doesn't have serial numbers, so we just verify it doesn't crash
        result = exif_data.extract_camera_uuid()
        assert result is None or isinstance(result, str)


class TestVideoExtractCameraUuid:
    """Test extract_camera_uuid for video EXIF reader"""

    def _create_video_exif_reader(self, tags_dict: dict):
        """Helper to create an ExifToolReadVideo with mocked tags"""
        from mapillary_tools.exiftool_read_video import (
            ExifToolReadVideo,
            EXIFTOOL_NAMESPACES,
        )
        import xml.etree.ElementTree as ET

        # Build XML with child elements (not attributes) - this is how ExifTool XML works
        root = ET.Element(
            "rdf:RDF", {"xmlns:rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"}
        )

        # Add child elements for each tag
        for key, value in tags_dict.items():
            prefix, tag_name = key.split(":")
            if prefix in EXIFTOOL_NAMESPACES:
                full_tag = "{" + EXIFTOOL_NAMESPACES[prefix] + "}" + tag_name
                child = ET.SubElement(root, full_tag)
                child.text = value

        etree = ET.ElementTree(root)
        return ExifToolReadVideo(etree)

    def test_gopro_serial(self):
        """Test extraction of GoPro serial number"""
        reader = self._create_video_exif_reader(
            {"GoPro:SerialNumber": "C3456789012345"}
        )
        assert reader.extract_camera_uuid() == "C3456789012345"

    def test_insta360_serial(self):
        """Test extraction of Insta360 serial number"""
        reader = self._create_video_exif_reader(
            {"Insta360:SerialNumber": "INST360SERIAL"}
        )
        assert reader.extract_camera_uuid() == "INST360SERIAL"

    def test_exif_body_serial(self):
        """Test extraction of standard EXIF body serial number"""
        reader = self._create_video_exif_reader({"ExifIFD:BodySerialNumber": "BODY123"})
        assert reader.extract_camera_uuid() == "BODY123"

    def test_exif_body_and_lens_serial(self):
        """Test extraction of both body and lens serial numbers"""
        reader = self._create_video_exif_reader(
            {
                "ExifIFD:BodySerialNumber": "BODY123",
                "ExifIFD:LensSerialNumber": "LENS456",
            }
        )
        assert reader.extract_camera_uuid() == "BODY123_LENS456"

    def test_no_serial(self):
        """Test with no serial numbers present"""
        reader = self._create_video_exif_reader({})
        assert reader.extract_camera_uuid() is None

    def test_gopro_priority(self):
        """Test that GoPro serial takes priority over generic serial"""
        reader = self._create_video_exif_reader(
            {
                "GoPro:SerialNumber": "GOPRO123",
                "IFD0:SerialNumber": "GENERIC789",
            }
        )
        assert reader.extract_camera_uuid() == "GOPRO123"


class TestExifToolReadExtractCameraUuid:
    """Test extract_camera_uuid for ExifToolRead (image EXIF via ExifTool XML)"""

    def _create_exiftool_reader(self, tags_dict: dict):
        """Helper to create an ExifToolRead with mocked tags"""
        from mapillary_tools.exiftool_read import ExifToolRead, EXIFTOOL_NAMESPACES
        import xml.etree.ElementTree as ET

        # Build XML structure that ExifToolRead expects
        root = ET.Element("rdf:Description")

        for tag, value in tags_dict.items():
            prefix, tag_name = tag.split(":", 1)
            if prefix in EXIFTOOL_NAMESPACES:
                full_tag = "{" + EXIFTOOL_NAMESPACES[prefix] + "}" + tag_name
                child = ET.SubElement(root, full_tag)
                child.text = value

        etree = ET.ElementTree(root)
        return ExifToolRead(etree)

    def test_body_serial_only(self):
        """Test extraction with only body serial number"""
        reader = self._create_exiftool_reader({"ExifIFD:BodySerialNumber": "BODY12345"})
        assert reader.extract_camera_uuid() == "BODY12345"

    def test_lens_serial_only(self):
        """Test extraction with only lens serial number"""
        reader = self._create_exiftool_reader({"ExifIFD:LensSerialNumber": "LENS67890"})
        assert reader.extract_camera_uuid() == "LENS67890"

    def test_both_body_and_lens_serial(self):
        """Test extraction with both body and lens serial numbers"""
        reader = self._create_exiftool_reader(
            {
                "ExifIFD:BodySerialNumber": "BODY123",
                "ExifIFD:LensSerialNumber": "LENS456",
            }
        )
        assert reader.extract_camera_uuid() == "BODY123_LENS456"

    def test_no_serial_numbers(self):
        """Test with no serial numbers present"""
        reader = self._create_exiftool_reader({})
        assert reader.extract_camera_uuid() is None

    def test_generic_serial_fallback(self):
        """Test that ExifIFD:SerialNumber is used as fallback for body serial"""
        reader = self._create_exiftool_reader({"ExifIFD:SerialNumber": "GENERIC123"})
        assert reader.extract_camera_uuid() == "GENERIC123"

    def test_ifd0_serial_fallback(self):
        """Test that IFD0:SerialNumber is used as fallback"""
        reader = self._create_exiftool_reader({"IFD0:SerialNumber": "IFD0_SN_123"})
        assert reader.extract_camera_uuid() == "IFD0_SN_123"

    def test_body_serial_priority_over_generic(self):
        """Test that BodySerialNumber takes priority over generic SerialNumber"""
        reader = self._create_exiftool_reader(
            {
                "ExifIFD:BodySerialNumber": "BODY999",
                "ExifIFD:SerialNumber": "GENERIC888",
            }
        )
        assert reader.extract_camera_uuid() == "BODY999"

    def test_xmp_exifex_body_serial(self):
        """Test XMP-exifEX:BodySerialNumber extraction"""
        reader = self._create_exiftool_reader(
            {"XMP-exifEX:BodySerialNumber": "XMPBODY123"}
        )
        assert reader.extract_camera_uuid() == "XMPBODY123"

    def test_xmp_aux_serial(self):
        """Test XMP-aux:SerialNumber extraction"""
        reader = self._create_exiftool_reader({"XMP-aux:SerialNumber": "AUX_SN_456"})
        assert reader.extract_camera_uuid() == "AUX_SN_456"

    def test_xmp_aux_lens_serial(self):
        """Test XMP-aux:LensSerialNumber extraction"""
        reader = self._create_exiftool_reader(
            {"XMP-aux:LensSerialNumber": "AUX_LENS_789"}
        )
        assert reader.extract_camera_uuid() == "AUX_LENS_789"

    def test_xmp_combined(self):
        """Test XMP body and lens serial combined"""
        reader = self._create_exiftool_reader(
            {
                "XMP-exifEX:BodySerialNumber": "XMP_BODY",
                "XMP-exifEX:LensSerialNumber": "XMP_LENS",
            }
        )
        assert reader.extract_camera_uuid() == "XMP_BODY_XMP_LENS"

    def test_whitespace_stripped(self):
        """Test that whitespace is stripped from serial numbers"""
        reader = self._create_exiftool_reader(
            {
                "ExifIFD:BodySerialNumber": "  BODY123  ",
                "ExifIFD:LensSerialNumber": "  LENS456  ",
            }
        )
        assert reader.extract_camera_uuid() == "BODY123_LENS456"
