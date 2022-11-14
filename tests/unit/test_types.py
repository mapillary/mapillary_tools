from pathlib import Path

from mapillary_tools import geo, types


def test_desc():
    metadata = types.ImageMetadata(
        filename=Path("foo").resolve(),
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
    )
    desc = types.as_desc(metadata)
    types.validate_desc(desc)
    actual = types.from_desc(desc)
    assert metadata == actual


def test_desc_video():
    ds = [
        types.VideoMetadata(
            filename=Path("foo/bar.mp4").resolve(),
            filetype=types.FileType.CAMM,
            points=[geo.Point(time=123, lat=1.331, lon=2.33, alt=3.123, angle=123)],
            make="hello",
            model="world",
        ),
        types.VideoMetadata(
            filename=Path("foo/bar.mp4").resolve(),
            filetype=types.FileType.CAMM,
            points=[geo.Point(time=123, lat=1.331, lon=2.33, alt=3.123, angle=123)],
        ),
        types.VideoMetadata(
            filename=Path("foo/bar.mp4").resolve(),
            filetype=types.FileType.CAMM,
            points=[],
        ),
    ]
    for metadata in ds:
        desc = types.as_desc_video(metadata)
        types.validate_desc_video(desc)
        actual = types.from_desc_video(desc)
        assert metadata == actual
