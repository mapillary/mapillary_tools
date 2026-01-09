# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import datetime
from pathlib import Path

from mapillary_tools import geo, types
from mapillary_tools.serializer import description


def test_desc():
    metadatas = [
        types.ImageMetadata(
            filename=Path("foo").resolve(),
            md5sum="1233",
            lat=1,
            lon=2,
            alt=3,
            angle=4,
            time=5,
            MAPMetaTags={"foo": "bar", "baz": 1.2},
            MAPSequenceUUID="MAPSequenceUUID",
            MAPDeviceMake="MAPDeviceMake",
            MAPDeviceModel="MAPDeviceModel",
            MAPGPSAccuracyMeters=23,
            MAPCameraUUID="MAPCameraUUID",
            MAPFilename="MAPFilename",
            MAPOrientation=1,
            # width and height are not seralized yet so they have to be None to pass the conversion
            width=None,
            height=None,
        ),
        types.ImageMetadata(
            filename=Path("foo").resolve(),
            md5sum=None,
            lat=1,
            lon=2,
            alt=3,
            angle=4,
            time=5,
            MAPMetaTags={"foo": "bar", "baz": 1.2},
            MAPOrientation=1,
        ),
    ]
    for metadata in metadatas:
        desc = description.DescriptionJSONSerializer.as_desc(metadata)
        description.validate_image_desc(desc)
        actual = description.DescriptionJSONSerializer.from_desc(desc)
        assert metadata == actual


def test_desc_video():
    ds = [
        types.VideoMetadata(
            filename=Path("foo/bar.mp4").resolve(),
            md5sum="123",
            filetype=types.FileType.CAMM,
            points=[geo.Point(time=123, lat=1.331, lon=2.33, alt=3.123, angle=123)],
            make="hello",
            model="world",
        ),
        types.VideoMetadata(
            filename=Path("foo/bar.mp4").resolve(),
            md5sum=None,
            filetype=types.FileType.CAMM,
            points=[geo.Point(time=123, lat=1.331, lon=2.33, alt=3.123, angle=123)],
        ),
        types.VideoMetadata(
            filename=Path("foo/bar.mp4").resolve(),
            md5sum="456",
            filetype=types.FileType.CAMM,
            points=[],
        ),
    ]
    for metadata in ds:
        desc = description.DescriptionJSONSerializer._as_video_desc(metadata)
        description.validate_video_desc(desc)
        actual = description.DescriptionJSONSerializer._from_video_desc(desc)
        assert metadata == actual


def test_datetimes():
    ct = description.build_capture_time(0)
    assert ct == "1970_01_01_00_00_00_000"
    ct = description.build_capture_time(0.123456)
    assert ct == "1970_01_01_00_00_00_123"
    ct = description.build_capture_time(0.000456)
    assert ct == "1970_01_01_00_00_00_000"
    dt = description.parse_capture_time(ct)
    assert dt == datetime.datetime(1970, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
    x = datetime.datetime.fromisoformat("2020-01-01T00:00:12.123567+08:00")
    assert "2019_12_31_16_00_12_123" == description.build_capture_time(x)
    assert (
        abs(
            geo.as_unix_time(
                description.parse_capture_time(description.build_capture_time(x))
            )
            - geo.as_unix_time(x)
        )
        < 0.001
    )
    x = datetime.datetime.now()
    assert (
        abs(
            geo.as_unix_time(
                description.parse_capture_time(description.build_capture_time(x))
            )
            - geo.as_unix_time(x)
        )
        < 0.001
    )
    x = x.astimezone()
    assert (
        abs(
            geo.as_unix_time(
                description.parse_capture_time(description.build_capture_time(x))
            )
            - geo.as_unix_time(x)
        )
        < 0.001
    )
