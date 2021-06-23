import typing as T
import sys

if sys.version_info >= (3, 8):
    from typing import TypedDict, Literal, overload  # pylint: disable=no-name-in-module
else:
    from typing_extensions import TypedDict, Literal, overload


class User(TypedDict, total=False):
    MAPOrganizationKey: str
    MAPSettingsUsername: str
    MAPSettingsUserKey: str
    user_upload_token: str


class CompassHeading(TypedDict, total=True):
    TrueHeading: float
    MagneticHeading: float


class ImageRequired(TypedDict, total=True):
    MAPLatitude: float
    MAPLongitude: float
    MAPCaptureTime: str
    MAPCompassHeading: CompassHeading


class Image(ImageRequired, total=False):
    MAPAltitude: float
    MAPPhotoUUID: str


class SequenceOnly(TypedDict, total=True):
    MAPSequenceUUID: str


class Sequence(SequenceOnly, total=True):
    MAPCompassHeading: CompassHeading
    MAPCaptureTime: str


class MetaProperties(TypedDict, total=False):
    MAPMetaTags: T.Dict
    MAPDeviceMake: str
    MAPDeviceModel: str
    MAPGPSAccuracyMeters: float
    MAPCameraUUID: str
    MAPFilename: str
    MAPOrientation: int


class FinalImageDescription(SequenceOnly, User, Image, MetaProperties):
    pass


Process = Literal[
    "user_process",
    "import_meta_data_process",
    "geotag_process",
    "sequence_process",
    "mapillary_image_description",
]
