from pathlib import Path

from mapillary_tools import types


def test_desc():
    metadata = types.ImageMetadata(
        filename=Path("foo"),
        lat=1,
        lon=2,
        alt=3,
        angle=4,
        time=5,
        MAPMetaTags={"foo": "bar", "baz": 1.2},
        MAPPhotoUUID="MAPPhotoUUID",
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
