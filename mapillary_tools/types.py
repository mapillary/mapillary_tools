import datetime
import sys
import typing as T

if sys.version_info >= (3, 8):
    from typing import TypedDict, Literal  # pylint: disable=no-name-in-module
else:
    from typing_extensions import TypedDict, Literal

import jsonschema


class UserItem(TypedDict, total=False):
    MAPOrganizationKey: T.Union[int, str]
    # Not in use. Keep here for back-compatibility
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


class _SequenceOnly(TypedDict, total=False):
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


class ImageDescriptionEXIF(_SequenceOnly, Image, MetaProperties):
    pass


class ImageDescriptionFile(ImageDescriptionEXIF, total=True):
    # filename is required
    filename: str


class ErrorObject(TypedDict, total=False):
    # type and message are required
    type: str
    message: str
    # vars is optional
    vars: T.Dict


def describe_error(exc: Exception) -> ErrorObject:
    desc: ErrorObject = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }
    exc_vars = vars(exc)
    if exc_vars:
        desc["vars"] = exc_vars
    return desc


class ImageDescriptionFileError(TypedDict):
    filename: str
    error: ErrorObject


ImageDescriptionFileOrError = T.Union[ImageDescriptionFileError, ImageDescriptionFile]


UserItemSchema = {
    "type": "object",
    "properties": {
        "MAPOrganizationKey": {"type": ["integer", "string"]},
        # Not in use. Keep here for back-compatibility
        "MAPSettingsUsername": {"type": "string"},
        "MAPSettingsUserKey": {"type": "string"},
        "user_upload_token": {"type": "string"},
    },
    "required": ["user_upload_token"],
    "additionalProperties": True,
}

ImageDescriptionEXIFSchema = {
    "type": "object",
    "properties": {
        "MAPLatitude": {
            "type": "number",
            "description": "Latitude of the image",
            "minimum": -90,
            "maximum": 90,
        },
        "MAPLongitude": {
            "type": "number",
            "description": "Longitude of the image",
            "minimum": -180,
            "maximum": 180,
        },
        "MAPAltitude": {"type": "number", "description": "Altitude of the image"},
        "MAPCaptureTime": {
            "type": "string",
            "description": "Capture time of the image",
            "pattern": "[0-9]{4}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]+",
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
            "pattern": "[a-zA-Z0-9_-]+",
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


def merge_schema(*schemas: T.Dict) -> T.Dict:
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
        "required": sorted(set(all_required)),
        "additionalProperties": additional_properties,
    }


ImageDescriptionFileSchema = merge_schema(
    ImageDescriptionEXIFSchema,
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


def validate_desc(desc: ImageDescriptionFile) -> None:
    jsonschema.validate(instance=desc, schema=ImageDescriptionFileSchema)
    try:
        map_capture_time_to_datetime(desc["MAPCaptureTime"])
    except ValueError as exc:
        raise jsonschema.ValidationError(
            str(exc), instance=desc, schema=ImageDescriptionFileSchema
        )


def is_error(desc: ImageDescriptionFileOrError) -> bool:
    return "error" in desc


def map_descs(
    func: T.Callable[[ImageDescriptionFile], ImageDescriptionFileOrError],
    descs: T.List[ImageDescriptionFileOrError],
) -> T.Iterator[ImageDescriptionFileOrError]:
    def _f(desc: ImageDescriptionFileOrError) -> ImageDescriptionFileOrError:
        if is_error(desc):
            return desc
        else:
            return func(T.cast(ImageDescriptionFile, desc))

    return map(_f, descs)


def filter_out_errors(
    descs: T.List[ImageDescriptionFileOrError],
) -> T.List[ImageDescriptionFile]:
    return T.cast(
        T.List[ImageDescriptionFile], [desc for desc in descs if not is_error(desc)]
    )


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

    print(json.dumps(ImageDescriptionFileSchema, indent=4))
