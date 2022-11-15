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


# http://wiki.gis.com/wiki/index.php/Decimal_degrees
# decimal places	degrees	distance
# 0	                 1.0	111 km
# 1	                 0.1	11.1 km
# 2	                 0.01	1.11 km
# 3	                 0.001	111 m
# 4	                 0.0001	11.1 m
# 5	                 0.00001	1.11 m
# 6	                 0.000001	0.111 m
# 7	                 0.0000001	1.11 cm
# 8	                 0.00000001	1.11 mm
_COORDINATES_PRECISION = 7
_ALTITUDE_PRECISION = 3
_ANGLE_PRECISION = 3


class FileType(enum.Enum):
    BLACKVUE = "blackvue"
    CAMM = "camm"
    GOPRO = "gopro"
    IMAGE = "image"


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


class _VideoDescriptionFileRequired(TypedDict, total=True):
    filename: str
    filetype: str
    MAPGPSTrack: T.List[T.Sequence[T.Union[float, int, None]]]


class VideoDescriptionFile(_VideoDescriptionFileRequired, total=False):
    MAPDeviceMake: str
    MAPDeviceModel: str


class ErrorObject(TypedDict, total=False):
    # type and message are required
    type: str
    message: str
    # vars is optional
    vars: T.Dict


class ImageDescriptionFileError(TypedDict, total=False):
    filename: str
    error: ErrorObject
    filetype: str


def describe_error(
    exc: Exception, filename: Path, filetype: T.Optional[FileType]
) -> ImageDescriptionFileError:
    err: ErrorObject = {
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
            err["vars"] = json.loads(vars_json)

    desc: ImageDescriptionFileError = {
        "error": err,
        "filename": str(filename.resolve()),
    }
    if filetype is not None:
        desc["filetype"] = filetype.value

    return desc


ImageDescriptionFileOrError = T.Union[ImageDescriptionFileError, ImageDescriptionFile]
VideoDescriptionFileOrError = T.Union[VideoDescriptionFile, ImageDescriptionFileError]
ImageVideoDescriptionFile = T.Union[ImageDescriptionFile, VideoDescriptionFile]
ImageVideoDescriptionFileOrError = T.Union[
    ImageVideoDescriptionFile, ImageDescriptionFileError
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
        "MAPAltitude": {
            "type": "number",
            "description": "Altitude of the image, in meters",
        },
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
            "description": "Camera angle of the image, in degrees. If null, the angle will be interpolated",
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
        "MAPGPSTrack": {
            "type": "array",
            "items": {
                "type": "array",
                "description": "track point",
                "prefixItems": [
                    {
                        "type": "number",
                        "description": "Time offset of the track point, in milliseconds, relative to the beginning of the video",
                    },
                    {
                        "type": "number",
                        "description": "Longitude of the track point",
                    },
                    {
                        "type": "number",
                        "description": "Latitude of the track point",
                    },
                    {
                        "type": ["number", "null"],
                        "description": "Altitude of the track point in meters",
                    },
                    {
                        "type": ["number", "null"],
                        "description": "Camera angle of the track point, in degrees. If null, the angle will be interpolated",
                    },
                ],
            },
        },
        "MAPDeviceMake": {
            "type": "string",
            "description": "Device make, e.g. GoPro, BlackVue, Insta360",
        },
        "MAPDeviceModel": {
            "type": "string",
            "description": "Device model, e.g. HERO10 Black, DR900S-1CH, Insta360 Titan",
        },
    },
    "required": [
        "MAPGPSTrack",
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
                "description": "Absolute path of the image",
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
                "description": "Absolute path of the video",
            },
            "filetype": {
                "type": "string",
                "enum": [
                    FileType.CAMM.value,
                    FileType.GOPRO.value,
                    FileType.BLACKVUE.value,
                ],
                "description": "The video file type",
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


def validate_desc(desc: ImageDescriptionFile) -> None:
    jsonschema.validate(instance=desc, schema=ImageDescriptionFileSchema)
    try:
        map_capture_time_to_datetime(desc["MAPCaptureTime"])
    except ValueError as exc:
        raise jsonschema.ValidationError(
            str(exc), instance=desc, schema=ImageDescriptionFileSchema
        )


def validate_desc_video(desc: VideoDescriptionFile) -> None:
    jsonschema.validate(instance=desc, schema=VideoDescriptionFileSchema)


def is_error(desc: ImageVideoDescriptionFileOrError) -> bool:
    return "error" in desc


def error_type(desc: ImageDescriptionFileError) -> str:
    return T.cast(str, desc["error"]["type"])


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


_X = T.TypeVar(
    "_X", VideoDescriptionFile, ImageDescriptionFile, ImageVideoDescriptionFile
)


def filter_out_errors(
    descs: T.Sequence[T.Union[_X, ImageDescriptionFileError]],
) -> T.List[_X]:
    return T.cast(
        T.List[_X],
        [desc for desc in descs if not is_error(desc)],
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
        "filename": str(metadata.filename.resolve()),
        "filetype": FileType.IMAGE.value,
        "MAPLatitude": round(metadata.lat, _COORDINATES_PRECISION),
        "MAPLongitude": round(metadata.lon, _COORDINATES_PRECISION),
        "MAPCaptureTime": datetime_to_map_capture_time(metadata.time),
    }
    if metadata.alt is not None:
        desc["MAPAltitude"] = round(metadata.alt, _ALTITUDE_PRECISION)
    if metadata.angle is not None:
        desc["MAPCompassHeading"] = {
            "TrueHeading": round(metadata.angle, _ANGLE_PRECISION),
            "MagneticHeading": round(metadata.angle, _ANGLE_PRECISION),
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
        lat=desc["MAPLatitude"],
        lon=desc["MAPLongitude"],
        alt=desc.get("MAPAltitude"),
        time=geo.as_unix_time(map_capture_time_to_datetime(desc["MAPCaptureTime"])),
        angle=desc.get("MAPCompassHeading", {}).get("TrueHeading"),
        **kwargs,
    )


def _encode_point(p: geo.Point) -> T.Sequence[T.Union[float, int, None]]:
    entry = [
        int(p.time * 1000),
        round(p.lon, _COORDINATES_PRECISION),
        round(p.lat, _COORDINATES_PRECISION),
        round(p.alt, _ALTITUDE_PRECISION) if p.alt is not None else None,
        round(p.angle, _ANGLE_PRECISION) if p.angle is not None else None,
    ]
    return entry


def _decode_point(entry: T.Sequence[T.Any]) -> geo.Point:
    time_ms, lon, lat, alt, angle = entry
    return geo.Point(time=time_ms / 1000, lon=lon, lat=lat, alt=alt, angle=angle)


def as_desc_video(video_metadata: VideoMetadata) -> VideoDescriptionFile:
    desc: VideoDescriptionFile = {
        "filename": str(video_metadata.filename.resolve()),
        "filetype": video_metadata.filetype.value,
        "MAPGPSTrack": [_encode_point(p) for p in video_metadata.points],
    }
    if video_metadata.make:
        desc["MAPDeviceMake"] = video_metadata.make
    if video_metadata.model:
        desc["MAPDeviceModel"] = video_metadata.model
    return desc


def from_desc_video(desc: VideoDescriptionFile) -> VideoMetadata:
    return VideoMetadata(
        filename=Path(desc["filename"]),
        filetype=FileType(desc["filetype"]),
        points=[_decode_point(entry) for entry in desc["MAPGPSTrack"]],
        make=desc.get("MAPDeviceMake"),
        model=desc.get("MAPDeviceModel"),
    )


_Y = T.TypeVar(
    "_Y",
    ImageDescriptionFileOrError,
    VideoDescriptionFileOrError,
    ImageVideoDescriptionFileOrError,
)


def validate_and_fail_desc(
    desc: _Y,
) -> _Y:
    if is_error(desc):
        return desc

    filetype = desc.get("filetype")
    try:
        if filetype == FileType.IMAGE.value:
            validate_desc(T.cast(ImageDescriptionFile, desc))
        else:
            validate_desc_video(T.cast(VideoDescriptionFile, desc))
    except jsonschema.ValidationError as exc:
        return describe_error(
            exc,
            Path(desc["filename"]),
            filetype=FileType(filetype) if filetype else None,
        )

    return desc


if __name__ == "__main__":
    print(json.dumps(ImageVideoDescriptionFileSchema, indent=4))
