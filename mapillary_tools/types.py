import datetime
import sys
import typing as T

if sys.version_info >= (3, 8):
    from typing import TypedDict, Literal  # pylint: disable=no-name-in-module
else:
    from typing_extensions import TypedDict, Literal


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


class Image(ImageRequired, total=False):
    MAPAltitude: float
    MAPPhotoUUID: str
    MAPCompassHeading: CompassHeading


class _SequenceOnly(TypedDict, total=True):
    MAPSequenceUUID: str


class Sequence(_SequenceOnly, total=False):
    MAPCompassHeading: CompassHeading


class MetaProperties(TypedDict, total=False):
    MAPMetaTags: T.Dict
    MAPDeviceMake: str
    MAPDeviceModel: str
    MAPGPSAccuracyMeters: float
    MAPCameraUUID: str
    MAPFilename: str
    MAPOrientation: int


class FinalImageDescription(_SequenceOnly, User, Image, MetaProperties):
    pass


class ImageDescriptionJSON(FinalImageDescription):
    filename: str


class FinalImageDescriptionError(TypedDict):
    filename: str
    error: T.Dict


FinalImageDescriptionOrError = T.Union[
    FinalImageDescriptionError, FinalImageDescription
]


class FinalImageDescriptionFromGeoJSON(FinalImageDescription):
    pass


UserItemSchema = {
    "type": "object",
    "properties": {
        "MAPOrganizationKey": {"type": "string"},
        "MAPSettingsUsername": {"type": "string"},
        "MAPSettingsUserKey": {"type": "string"},
        "user_upload_token": {"type": "string"},
    },
    "required": ["MAPSettingsUserKey", "user_upload_token"],
    "additionalProperties": False,
}

FinalImageDescriptionSchema = {
    "type": "object",
    "properties": {
        "MAPOrganizationKey": {
            "type": "string",
            "description": "Organization ID. Upload for which organization",
        },
        "MAPSettingsUsername": {"type": "string"},
        "MAPSettingsUserKey": {
            "type": "string",
            "description": "User ID. Upload to which Mapillary user",
        },
        "MAPLatitude": {"type": "number", "description": "Latitude of the image"},
        "MAPLongitude": {"type": "number", "description": "Longitude of the image"},
        "MAPAltitude": {"type": "number", "description": "Altitude of the image"},
        "MAPCaptureTime": {
            "type": "string",
            "description": "Capture time of the image",
        },
        "MAPPhotoUUID": {"type": "string"},
        "MAPCompassHeading": {
            "type": "object",
            "properties": {
                "TrueHeading": {"type": "number"},
                "MagneticHeading": {"type": "number"},
            },
            "required": ["TrueHeading", "MagneticHeading"],
            "additionalProperties": False,
        },
        "MAPSequenceUUID": {
            "type": "string",
            "description": "Arbitrary key used to group images",
        },
        "MAPMetaTags": {"type": "object"},
        "MAPDeviceMake": {"type": "string"},
        "MAPDeviceModel": {"type": "string"},
        "MAPGPSAccuracyMeters": {"type": "number"},
        "MAPCameraUUID": {"type": "string"},
        "MAPFilename": {"type": "string"},
        "MAPOrientation": {"type": "integer"},
    },
    "required": [
        "MAPLatitude",
        "MAPLongitude",
        "MAPCaptureTime",
    ],
    "additionalProperties": False,
}


def merge_schema(*schemas: T.Dict):
    for s in schemas:
        assert s.get("type") == "object", "must be all object schemas"
    properties = {}
    all_required = []
    additional_properties = True
    for s in schemas:
        properties.update(s.get("properties", {}))
        all_required += s.get("required", [])
        if "additionalProperties" in s:
            additional_properties = s["additionalProperties"]
    return {
        "type": "object",
        "properties": properties,
        "required": list(set(all_required)),
        "additionalProperties": additional_properties,
    }


ImageDescriptionJSONSchema = merge_schema(
    FinalImageDescriptionSchema,
    {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "The image file's path relative to the image directory",
            },
        },
        "required": [
            "filename",
        ],
    },
)

Process = Literal[
    "import_meta_data_process",
    "geotag_process",
    "sequence_process",
    "mapillary_image_description",
]

Status = Literal["success", "failed"]


def datetime_to_map_capture_time(time: datetime.datetime) -> str:
    return datetime.datetime.strftime(time, "%Y_%m_%d_%H_%M_%S_%f")[:-3]


def map_capture_time_to_datetime(time: str) -> datetime.datetime:
    return datetime.datetime.strptime(time, "%Y_%m_%d_%H_%M_%S_%f")


class GPXPoint(T.NamedTuple):
    # Put it first for sorting
    time: datetime.datetime
    lat: float
    lon: float
    alt: T.Optional[float]

    def as_desc(self) -> Image:
        desc: Image = {
            "MAPLatitude": self.lat,
            "MAPLongitude": self.lon,
            "MAPCaptureTime": datetime_to_map_capture_time(self.time),
        }
        if self.alt is not None:
            desc["MAPAltitude"] = self.alt
        return desc


class GPXPointAngle(T.NamedTuple):
    point: GPXPoint
    angle: T.Optional[float]

    def as_desc(self) -> Image:
        desc = self.point.as_desc()
        if self.angle is not None:
            desc["MAPCompassHeading"] = {
                "TrueHeading": self.angle,
                "MagneticHeading": self.angle,
            }
        return desc


if __name__ == "__main__":
    import json

    print(json.dumps(ImageDescriptionJSONSchema, indent=4))
