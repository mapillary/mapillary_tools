# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

"""
The camera make and model of a video are kept whichever source geotags it:
a video whose own GPS is missing or that ExifTool geotags still names the
camera that recorded it.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from mapillary_tools import novatek_parser
from mapillary_tools.geotag.video_extractors.exiftool import VideoExifToolExtractor
from mapillary_tools.geotag.video_extractors.gpx import GPXVideoExtractor
from mapillary_tools.geotag.video_extractors.native import (
    extract_make_and_model,
    NativeVideoExtractor,
)
from mapillary_tools.gpmf import gpmf_parser
from mapillary_tools.telemetry import GPSPoint


GOPRO_DATA = Path(__file__).parent.parent / "data" / "gopro_data"
SAMPLE_VIDEO = Path(__file__).parent.parent / "data" / "videos" / "sample-5s.mp4"

BLACKVUE_CPRT = b" Pittasoft Co., Ltd.;DR900S-1CH;1.008;English;1;D90SS1HAE00661;T69;"


def _box(box_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(data), box_type) + data


def _mvhd() -> bytes:
    # version 0: flags, creation and modification time, timescale, duration,
    # then rate, volume, reserved, matrix, pre_defined and next_track_ID
    return _box(
        b"mvhd",
        struct.pack(">I4I", 0, 0, 0, 1000, 3000)
        + struct.pack(">IH10x", 0x00010000, 0x0100)
        + struct.pack(">9I", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)
        + bytes(24)
        + struct.pack(">I", 1),
    )


def _write_video(path: Path, *boxes: bytes) -> Path:
    path.write_bytes(_box(b"ftyp", b"isom\x00\x00\x02\x00isom") + b"".join(boxes))
    return path


def _blackvue_without_gps(path: Path) -> Path:
    """A BlackVue video that never got a fix: no gps box, only the copyright box"""
    return _write_video(
        path, _box(b"free", _box(b"cprt", BLACKVUE_CPRT)), _box(b"moov", _mvhd())
    )


def _video_with_udta(path: Path, make: bytes, model: bytes) -> Path:
    udta = _box(b"udta", _box(b"@mak", make) + _box(b"@mod", model))
    return _write_video(path, _box(b"moov", _mvhd() + udta))


def _gpx(path: Path) -> Path:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="test">
  <trk><trkseg>
<trkpt lat="48.170" lon="11.590"><time>2026-09-11T15:39:41Z</time></trkpt>
<trkpt lat="48.171" lon="11.591"><time>2026-09-11T15:39:43Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""
    )
    return path


def _exiftool_element(make: str | None = None) -> ET.Element:
    make_xml = f" <IFD0:Make>{make}</IFD0:Make>\n" if make else ""
    xml = f"""\
<?xml version='1.0' encoding='UTF-8'?>
<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
<rdf:Description rdf:about='/tmp/test.mp4'
 xmlns:IFD0='http://ns.exiftool.org/EXIF/IFD0/1.0/'
 xmlns:QuickTime='http://ns.exiftool.org/QuickTime/QuickTime/1.0/'>
{make_xml} <QuickTime:GPSDateTime>2019:09:02 10:23:29.00Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>37.1</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.2</QuickTime:GPSLongitude>
 <QuickTime:GPSDateTime>2019:09:02 10:23:30.00Z</QuickTime:GPSDateTime>
 <QuickTime:GPSLatitude>37.2</QuickTime:GPSLatitude>
 <QuickTime:GPSLongitude>28.2</QuickTime:GPSLongitude>
</rdf:Description>
</rdf:RDF>
"""
    rdf_ns = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    element = ET.fromstring(xml).find(f"{{{rdf_ns}}}Description")
    assert element is not None
    return element


class TestExtractMakeAndModel:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("hero8.mp4", ("GoPro", "HERO8 Black")),
            ("max-360mode.mp4", ("GoPro", "GoPro Max")),
        ],
    )
    def test_gopro(self, name, expected):
        assert extract_make_and_model(GOPRO_DATA / name) == expected

    def test_blackvue_without_gps(self, tmp_path):
        video = _blackvue_without_gps(tmp_path / "20190902_132329_NF.mp4")
        assert extract_make_and_model(video) == ("BlackVue", "DR900S-1CH")

    def test_user_data_box(self, tmp_path):
        video = _video_with_udta(tmp_path / "v.mp4", b"Labpano", b"Pilot One")
        assert extract_make_and_model(video) == ("Labpano", "Pilot One")

    def test_video_that_names_no_camera(self):
        assert extract_make_and_model(SAMPLE_VIDEO) == (None, None)

    @pytest.mark.parametrize("content", [b"", b"not a real mp4"])
    def test_unreadable_video(self, tmp_path, content):
        video = tmp_path / "v.mp4"
        video.write_bytes(content)
        assert extract_make_and_model(video) == (None, None)


class TestGPXOverVideoWithoutGPS:
    def test_gopro_without_gps(self, tmp_path, monkeypatch):
        """
        A GoPro without a GPS receiver, such as the HERO12 Black, records its
        model in its telemetry all the same
        """
        info = gpmf_parser.GoProInfo(gps=[], make="GoPro", model="HERO12 Black")
        monkeypatch.setattr(gpmf_parser, "extract_gopro_info", lambda *a, **kw: info)
        video = tmp_path / "GX014387.MP4"
        video.write_bytes(b"not a real mp4")

        metadata = GPXVideoExtractor(video, _gpx(tmp_path / "track.gpx")).extract()

        assert len(metadata.points) == 2
        assert (metadata.make, metadata.model) == ("GoPro", "HERO12 Black")

    def test_blackvue_without_gps(self, tmp_path):
        video = _blackvue_without_gps(tmp_path / "20190902_132329_NF.mp4")

        metadata = GPXVideoExtractor(video, _gpx(tmp_path / "track.gpx")).extract()

        assert len(metadata.points) == 2
        assert (metadata.make, metadata.model) == ("BlackVue", "DR900S-1CH")

    def test_video_that_names_no_camera(self, tmp_path):
        metadata = GPXVideoExtractor(SAMPLE_VIDEO, _gpx(tmp_path / "t.gpx")).extract()

        assert len(metadata.points) == 2
        assert (metadata.make, metadata.model) == (None, None)


class TestExifToolExtractor:
    def test_falls_back_to_the_video(self, tmp_path):
        video = _blackvue_without_gps(tmp_path / "20190902_132329_NF.mp4")

        metadata = VideoExifToolExtractor(video, _exiftool_element()).extract()

        assert len(metadata.points) == 2
        assert (metadata.make, metadata.model) == ("BlackVue", "DR900S-1CH")

    def test_exiftool_make_wins(self, tmp_path):
        video = _blackvue_without_gps(tmp_path / "20190902_132329_NF.mp4")

        metadata = VideoExifToolExtractor(
            video, _exiftool_element("Pittasoft")
        ).extract()

        assert (metadata.make, metadata.model) == ("Pittasoft", None)


class TestNovatekExtractor:
    def test_keeps_the_user_data_box(self, tmp_path, monkeypatch):
        points = [
            GPSPoint(
                time=t,
                lat=48.17,
                lon=11.59,
                alt=None,
                angle=None,
                epoch_time=1789141181.0 + t,
                fix=None,
                precision=None,
                ground_speed=None,
            )
            for t in [0.0, 1.0]
        ]
        monkeypatch.setattr(novatek_parser, "extract_points", lambda fp: points)
        video = _video_with_udta(tmp_path / "v.mp4", b"Acme", b"Dashcam 2")

        metadata = NativeVideoExtractor(video).extract()

        assert (metadata.make, metadata.model) == ("Acme", "Dashcam 2")
