# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import typing as T
import xml.etree.ElementTree as ET

from mapillary_tools.exiftool_read import EXIFTOOL_NAMESPACES, ExifToolRead


class TestExifToolReadExtractCameraUuid:
    """Test extract_camera_uuid for ExifToolRead (image EXIF via ExifTool XML)"""

    def _create_exiftool_reader(self, tags_dict: T.Dict[str, str]) -> ExifToolRead:
        """Helper to create an ExifToolRead with mocked tags"""
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
        reader = self._create_exiftool_reader({"IFD0:SerialNumber": "IFD0SN123"})
        assert reader.extract_camera_uuid() == "IFD0SN123"

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
        reader = self._create_exiftool_reader({"XMP-aux:SerialNumber": "AUXSN456"})
        assert reader.extract_camera_uuid() == "AUXSN456"

    def test_xmp_aux_lens_serial(self):
        """Test XMP-aux:LensSerialNumber extraction"""
        reader = self._create_exiftool_reader(
            {"XMP-aux:LensSerialNumber": "AUXLENS789"}
        )
        assert reader.extract_camera_uuid() == "AUXLENS789"

    def test_xmp_combined(self):
        """Test XMP body and lens serial combined"""
        reader = self._create_exiftool_reader(
            {
                "XMP-exifEX:BodySerialNumber": "XMPBODY",
                "XMP-exifEX:LensSerialNumber": "XMPLENS",
            }
        )
        assert reader.extract_camera_uuid() == "XMPBODY_XMPLENS"

    def test_whitespace_stripped(self):
        """Test that whitespace is stripped from serial numbers"""
        reader = self._create_exiftool_reader(
            {
                "ExifIFD:BodySerialNumber": "  BODY123  ",
                "ExifIFD:LensSerialNumber": "  LENS456  ",
            }
        )
        assert reader.extract_camera_uuid() == "BODY123_LENS456"
