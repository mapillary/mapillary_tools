# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from mapillary_tools.geo import Point
from mapillary_tools.serializer.gpx import GPXSerializer
from mapillary_tools.telemetry import CAMMGPSPoint, GPSFix, GPSPoint
from mapillary_tools.types import (
    ErrorMetadata,
    FileType,
    ImageMetadata,
    VideoMetadata,
)


def _make_image(
    filename: str,
    time: float,
    lat: float,
    lon: float,
    alt: float = 100.0,
    seq_uuid: str | None = None,
) -> ImageMetadata:
    return ImageMetadata(
        time=time,
        lat=lat,
        lon=lon,
        alt=alt,
        angle=45.0,
        filename=Path(filename),
        MAPSequenceUUID=seq_uuid,
        MAPFilename=filename,
    )


def _make_video(filename: str, points: list[Point]) -> VideoMetadata:
    return VideoMetadata(
        filename=Path(filename),
        filetype=FileType.CAMM,
        points=points,
    )


def _make_error(filename: str) -> ErrorMetadata:
    return ErrorMetadata(
        filename=Path(filename),
        filetype=FileType.IMAGE,
        error=ValueError("test error"),
    )


def _parse_gpx(data: bytes) -> ET.Element:
    return ET.fromstring(data.decode("utf-8"))


class TestGPXSerializerSerialize:
    def test_empty_metadatas(self):
        result = GPXSerializer.serialize([])
        root = _parse_gpx(result)
        assert root.tag.endswith("gpx")
        # No tracks
        tracks = root.findall(".//{http://www.topografix.com/GPX/1/1}trk")
        assert len(tracks) == 0

    def test_single_image(self):
        img = _make_image("img1.jpg", time=1000.0, lat=48.0, lon=11.0, seq_uuid="seq1")
        result = GPXSerializer.serialize([img])
        root = _parse_gpx(result)
        tracks = root.findall(".//{http://www.topografix.com/GPX/1/1}trk")
        assert len(tracks) == 1
        points = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        assert len(points) == 1
        assert float(points[0].attrib["lat"]) == 48.0
        assert float(points[0].attrib["lon"]) == 11.0

    def test_multiple_images_same_sequence(self):
        imgs = [
            _make_image("img1.jpg", time=1000.0, lat=48.0, lon=11.0, seq_uuid="seq1"),
            _make_image("img2.jpg", time=1001.0, lat=48.1, lon=11.1, seq_uuid="seq1"),
        ]
        result = GPXSerializer.serialize(imgs)
        root = _parse_gpx(result)
        tracks = root.findall(".//{http://www.topografix.com/GPX/1/1}trk")
        assert len(tracks) == 1
        points = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        assert len(points) == 2

    def test_multiple_sequences(self):
        imgs = [
            _make_image("img1.jpg", time=1000.0, lat=48.0, lon=11.0, seq_uuid="seq1"),
            _make_image("img2.jpg", time=2000.0, lat=49.0, lon=12.0, seq_uuid="seq2"),
        ]
        result = GPXSerializer.serialize(imgs)
        root = _parse_gpx(result)
        tracks = root.findall(".//{http://www.topografix.com/GPX/1/1}trk")
        assert len(tracks) == 2

    def test_video_metadata(self):
        pts = [
            Point(time=1.0, lat=48.0, lon=11.0, alt=100.0, angle=0.0),
            Point(time=2.0, lat=48.1, lon=11.1, alt=110.0, angle=10.0),
        ]
        video = _make_video("video.mp4", pts)
        result = GPXSerializer.serialize([video])
        root = _parse_gpx(result)
        tracks = root.findall(".//{http://www.topografix.com/GPX/1/1}trk")
        assert len(tracks) == 1
        points = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        assert len(points) == 2

    def test_error_metadata(self):
        err = _make_error("bad.jpg")
        result = GPXSerializer.serialize([err])
        root = _parse_gpx(result)
        tracks = root.findall(".//{http://www.topografix.com/GPX/1/1}trk")
        assert len(tracks) == 1
        # Error tracks have no track points
        points = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        assert len(points) == 0

    def test_mixed_metadatas(self):
        img = _make_image("img1.jpg", time=1000.0, lat=48.0, lon=11.0, seq_uuid="s1")
        pts = [Point(time=1.0, lat=49.0, lon=12.0, alt=100.0, angle=0.0)]
        video = _make_video("video.mp4", pts)
        err = _make_error("bad.jpg")
        result = GPXSerializer.serialize([img, video, err])
        root = _parse_gpx(result)
        tracks = root.findall(".//{http://www.topografix.com/GPX/1/1}trk")
        # 1 error track + 1 image sequence track + 1 video track
        assert len(tracks) == 3

    def test_serialize_returns_utf8_bytes(self):
        result = GPXSerializer.serialize([])
        assert isinstance(result, bytes)
        text = result.decode("utf-8")
        assert "<?xml" in text


class TestGPXSerializerAsGPXPoint:
    def test_basic_point(self):
        p = Point(time=1000.0, lat=48.0, lon=11.0, alt=500.0, angle=90.0)
        gpx_pt = GPXSerializer.as_gpx_point(p)
        assert gpx_pt.latitude == 48.0
        assert gpx_pt.longitude == 11.0
        assert gpx_pt.elevation == 500.0
        assert gpx_pt.time is not None

    def test_image_metadata_point_has_name(self):
        img = _make_image("photo.jpg", time=1000.0, lat=48.0, lon=11.0)
        gpx_pt = GPXSerializer.as_gpx_point(img)
        assert gpx_pt.name == "photo.jpg"

    def test_camm_gps_point_uses_gps_epoch_time(self):
        p = CAMMGPSPoint(
            time=5.0,
            lat=48.0,
            lon=11.0,
            alt=100.0,
            angle=0.0,
            time_gps_epoch=1700000000.0,
            gps_fix_type=3,
            horizontal_accuracy=1.0,
            vertical_accuracy=1.0,
            velocity_east=0.0,
            velocity_north=0.0,
            velocity_up=0.0,
            speed_accuracy=0.5,
        )
        gpx_pt = GPXSerializer.as_gpx_point(p)
        # time should be based on time_gps_epoch, not the video time (5.0)
        assert gpx_pt.time is not None
        assert gpx_pt.time.timestamp() == 1700000000.0

    def test_gps_point_with_epoch_time(self):
        p = GPSPoint(
            time=5.0,
            lat=48.0,
            lon=11.0,
            alt=100.0,
            angle=0.0,
            epoch_time=1700000000.0,
            fix=GPSFix.FIX_3D,
            precision=1.0,
            ground_speed=10.0,
        )
        gpx_pt = GPXSerializer.as_gpx_point(p)
        assert gpx_pt.time is not None
        assert gpx_pt.time.timestamp() == 1700000000.0

    def test_gps_point_without_epoch_time(self):
        p = GPSPoint(
            time=1000.0,
            lat=48.0,
            lon=11.0,
            alt=100.0,
            angle=0.0,
            epoch_time=None,
            fix=GPSFix.FIX_3D,
            precision=1.0,
            ground_speed=10.0,
        )
        gpx_pt = GPXSerializer.as_gpx_point(p)
        # Falls through without setting epoch_time; uses original time
        assert gpx_pt.time is not None
        assert gpx_pt.time.timestamp() == 1000.0

    def test_point_with_none_alt(self):
        p = Point(time=1000.0, lat=48.0, lon=11.0, alt=None, angle=None)
        gpx_pt = GPXSerializer.as_gpx_point(p)
        assert gpx_pt.elevation is None
