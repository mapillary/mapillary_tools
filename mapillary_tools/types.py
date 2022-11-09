import dataclasses
import datetime
import enum
import json
import sys
import typing as T
from pathlib import Path

if sys.version_info >= (3, 8):
    from typing import Literal, TypedDict  # pylint: disable=no-name-in-module
else:
    from typing_extensions import Literal, TypedDict

import jsonschema

from . import geo


class FileType(enum.Enum):
    BLACKVUE = "blackvue"
    CAMM = "camm"
    GOPRO = "gopro"
    IMAGE = "image"
    RAW_BLACKVUE = "raw_blackvue"
    RAW_CAMM = "raw_camm"
    ZIP = "zip"


@dataclasses.dataclass
class ImageMetadata(geo.Point):
    filename: Path
    # filetype is always FileType.IMAGE
    MAPSequenceUUID: T.Optional[str] = None
    MAPMetaTags: T.Optional[T.Dict] = None
    MAPDeviceMake: T.Optional[str] = None
    MAPDeviceModel: T.Optional[str] = None
    MAPGPSAccuracyMeters: T.Optional[float] = None
    MAPCameraUUID: T.Optional[str] = None
    MAPFilename: T.Optional[str] = None
    MAPOrientation: T.Optional[int] = None


@dataclasses.dataclass
class VideoMetadata:
    filename: Path
    filetype: FileType
    points: T.Sequence[geo.Point]
    make: T.Optional[str] = None
    model: T.Optional[str] = None


@dataclasses.dataclass
class ErrorMetadata:
    filename: Path
    filetype: T.Optional[FileType]
    error: Exception


MetadataOrError = T.Union[ImageMetadata, VideoMetadata, ErrorMetadata]


class UserItem(TypedDict, total=False):
    MAPOrganizationKey: T.Union[int, str]
    # Not in use. Keep here for back-compatibility
    MAPSettingsUsername: str
    MAPSettingsUserKey: str
    user_upload_token: str


class _CompassHeading(TypedDict, total=True):
    TrueHeading: float
    MagneticHeading: float


class _ImageRequired(TypedDict, total=True):
    MAPLatitude: float
    MAPLongitude: float
    MAPCaptureTime: str


class _Image(_ImageRequired, total=False):
    MAPAltitude: float
    MAPCompassHeading: _CompassHeading


class _SequenceOnly(TypedDict, total=False):
    MAPSequenceUUID: str


class MetaProperties(TypedDict, total=False):
    MAPMetaTags: T.Dict
    MAPDeviceMake: str
    MAPDeviceModel: str
    MAPGPSAccuracyMeters: float
    MAPCameraUUID: str
    MAPFilename: str
    MAPOrientation: int


class ImageDescriptionEXIF(_SequenceOnly, _Image, MetaProperties):
    pass


class ImageDescriptionFile(ImageDescriptionEXIF, total=True):
    # filename is required
    filename: str
    filetype: Literal["image"]


class VideoDescriptionFile(TypedDict, total=False):
    filename: str
    filetype: str
    MAPGPSTrack: T.List[T.List[float]]
    MAPCaptureTime: str
    MAPDeviceMake: str
    MAPDeviceModel: str


class ErrorObject(TypedDict, total=False):
    # type and message are required
    type: str
    message: str
    # vars is optional
    vars: T.Dict


class ImageDescriptionFileError(TypedDict):
    filename: str
    error: ErrorObject


def describe_error(exc: Exception, filename: str) -> ImageDescriptionFileError:
    desc: ErrorObject = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }

    exc_vars = vars(exc)

    if exc_vars:
        # handle unserializable exceptions
        try:
            vars_json = json.dumps(exc_vars)
        except Exception:
            vars_json = ""
        if vars_json:
            desc["vars"] = json.loads(vars_json)

    return {
        "error": desc,
        "filename": filename,
    }


ImageDescriptionFileOrError = T.Union[ImageDescriptionFileError, ImageDescriptionFile]
ImageVideoDescriptionFileOrError = T.Union[
    ImageDescriptionFileError, ImageDescriptionFile, VideoDescriptionFile
]


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
            "description": "Arbitrary key for grouping images",
            "pattern": "[a-zA-Z0-9_-]+",
        },
        "MAPMetaTags": {"type": "object"},
        "MAPDeviceMake": {"type": "string"},
        "MAPDeviceModel": {"type": "string"},
        "MAPGPSAccuracyMeters": {"type": "number"},
        "MAPCameraUUID": {"type": "string"},
        "MAPFilename": {
            "type": "string",
            "description": "The base filename of the image",
        },
        "MAPOrientation": {"type": "integer"},
    },
    "required": [
        "MAPLatitude",
        "MAPLongitude",
        "MAPCaptureTime",
    ],
    "additionalProperties": False,
}

VideoDescriptionSchema = {
    "type": "object",
    "properties": {
        "MAPCaptureTime": {
            "type": "string",
            "description": "Capture time of the video",
            "pattern": "[0-9]{4}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]+",
        },
        "MAPGPSTrack": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
            },
        },
        "MAPDeviceMake": {"type": "string"},
        "MAPDeviceModel": {"type": "string"},
    },
    "required": [
        "MAPGPSTrack",
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
                "description": "The image file path",
            },
            "filetype": {
                "type": "string",
                "enum": [FileType.IMAGE.value],
                "description": "The image file type",
            },
        },
        "required": [
            "filename",
            "filetype",
        ],
    },
)

VideoDescriptionFileSchema = merge_schema(
    VideoDescriptionSchema,
    {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "The video file path",
            },
            "filetype": {
                "type": "string",
                "enum": [
                    FileType.CAMM.value,
                    FileType.GOPRO.value,
                    FileType.BLACKVUE.value,
                ],
                "description": "The file type",
            },
        },
        "required": [
            "filename",
            "filetype",
        ],
    },
)


ImageVideoDescriptionFileSchema = {
    "oneOf": [VideoDescriptionFileSchema, ImageDescriptionFileSchema]
}


def validate_desc(desc: T.Union[ImageDescriptionFile, VideoDescriptionFile]) -> None:
    jsonschema.validate(instance=desc, schema=ImageVideoDescriptionFileSchema)
    try:
        map_capture_time_to_datetime(desc["MAPCaptureTime"])
    except ValueError as exc:
        raise jsonschema.ValidationError(
            str(exc), instance=desc, schema=ImageVideoDescriptionFileSchema
        )


def is_error(desc: ImageVideoDescriptionFileOrError) -> bool:
    return "error" in desc


_D = T.TypeVar("_D", ImageVideoDescriptionFileOrError, ImageDescriptionFileOrError)


def map_descs(
    func: T.Callable[[ImageDescriptionFile], _D],
    descs: T.Sequence[_D],
) -> T.Iterator[_D]:
    def _f(desc: _D) -> _D:
        if is_error(desc):
            return desc
        else:
            return func(T.cast(ImageDescriptionFile, desc))

    return map(_f, descs)


def filter_out_errors(
    descs: T.Sequence[ImageVideoDescriptionFileOrError],
) -> T.List[ImageDescriptionFile]:
    return T.cast(
        T.List[ImageDescriptionFile], [desc for desc in descs if not is_error(desc)]
    )


def filter_image_descs(
    descs: T.Sequence[ImageVideoDescriptionFileOrError],
) -> T.List[ImageDescriptionFile]:
    return T.cast(
        T.List[ImageDescriptionFile],
        [
            desc
            for desc in descs
            if not is_error(desc) and desc.get("filetype") == FileType.IMAGE.value
        ],
    )


def datetime_to_map_capture_time(time: T.Union[datetime.datetime, int, float]) -> str:
    if isinstance(time, (float, int)):
        dt = datetime.datetime.utcfromtimestamp(time)
    else:
        dt = time
    return datetime.datetime.strftime(dt, "%Y_%m_%d_%H_%M_%S_%f")[:-3]


def map_capture_time_to_datetime(time: str) -> datetime.datetime:
    return datetime.datetime.strptime(time, "%Y_%m_%d_%H_%M_%S_%f")


def as_desc(metadata: ImageMetadata) -> ImageDescriptionFile:
    desc: ImageDescriptionFile = {
        "filename": str(metadata.filename),
        "filetype": FileType.IMAGE.value,
        "MAPLatitude": metadata.lat,
        "MAPLongitude": metadata.lon,
        "MAPCaptureTime": datetime_to_map_capture_time(metadata.time),
    }
    if metadata.alt is not None:
        desc["MAPAltitude"] = metadata.alt
    if metadata.angle is not None:
        desc["MAPCompassHeading"] = {
            "TrueHeading": metadata.angle,
            "MagneticHeading": metadata.angle,
        }
    fields = dataclasses.fields(metadata)
    for field in fields:
        if field.name.startswith("MAP"):
            value = getattr(metadata, field.name)
            if value is not None:
                # ignore error: TypedDict key must be a string literal;
                # expected one of ("MAPMetaTags", "MAPDeviceMake", "MAPDeviceModel", "MAPGPSAccuracyMeters", "MAPCameraUUID", ...)
                desc[field.name] = value  # type: ignore
    return desc


def as_desc_video(video_metadata: VideoMetadata) -> VideoDescriptionFile:
    if video_metadata.points:
        capture_time = datetime_to_map_capture_time(video_metadata.points[0].time)
    else:
        # Should not happen because we report empty GPS as errors
        capture_time = datetime_to_map_capture_time(0)
    desc: VideoDescriptionFile = {
        "filename": str(video_metadata.filename),
        "filetype": video_metadata.filetype.value,
        "MAPGPSTrack": [
            [round(p.lon, 6), round(p.lat, 6)] for p in video_metadata.points
        ],
        "MAPCaptureTime": capture_time,
    }
    if video_metadata.make:
        desc["MAPDeviceMake"] = video_metadata.make
    if video_metadata.model:
        desc["MAPDeviceModel"] = video_metadata.model
    return desc


def from_desc(desc: ImageDescriptionFile) -> ImageMetadata:
    kwargs: T.Dict = {}
    for k, v in desc.items():
        if k not in [
            "filename",
            "filetype",
            "MAPLatitude",
            "MAPLongitude",
            "MAPAltitude",
            "MAPCaptureTime",
            "MAPCompassHeading",
        ]:
            kwargs[k] = v

    return ImageMetadata(
        filename=Path(desc["filename"]),
        lat=round(desc["MAPLatitude"], 6),
        lon=round(desc["MAPLongitude"], 6),
        alt=desc.get("MAPAltitude"),
        time=geo.as_unix_time(map_capture_time_to_datetime(desc["MAPCaptureTime"])),
        angle=desc.get("MAPCompassHeading", {}).get("TrueHeading"),
        **kwargs,
    )


if __name__ == "__main__":
    print(json.dumps(ImageVideoDescriptionFileSchema, indent=4))
