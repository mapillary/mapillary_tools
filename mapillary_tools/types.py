import dataclasses
import datetime
import enum
import hashlib
import json
import os
import typing as T
import uuid
from pathlib import Path
from typing import Literal, TypedDict

import jsonschema

from . import exceptions, geo, utils


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
    VIDEO = "video"
    ZIP = "zip"


@dataclasses.dataclass
class ImageMetadata(geo.Point):
    filename: Path
    # if None or absent, it will be calculated
    md5sum: T.Optional[str]
    # filetype: is always FileType.IMAGE
    width: T.Optional[int] = None
    height: T.Optional[int] = None
    MAPSequenceUUID: T.Optional[str] = None
    MAPDeviceMake: T.Optional[str] = None
    MAPDeviceModel: T.Optional[str] = None
    MAPGPSAccuracyMeters: T.Optional[float] = None
    MAPCameraUUID: T.Optional[str] = None
    MAPOrientation: T.Optional[int] = None
    # deprecated since v0.10.0; keep here for compatibility
    MAPMetaTags: T.Optional[T.Dict] = None
    # deprecated since v0.10.0; keep here for compatibility
    MAPFilename: T.Optional[str] = None
    filesize: T.Optional[int] = None

    def update_md5sum(self, image_data: T.Optional[T.BinaryIO] = None) -> None:
        if self.md5sum is None:
            if image_data is None:
                with self.filename.open("rb") as fp:
                    self.md5sum = utils.md5sum_fp(fp).hexdigest()
            else:
                self.md5sum = utils.md5sum_fp(image_data).hexdigest()

    def sort_key(self):
        """
        For sorting images in a sequence
        """
        return (self.time, self.filename.name)


@dataclasses.dataclass
class VideoMetadata:
    filename: Path
    # if None or absent, it will be calculated
    md5sum: T.Optional[str]
    filetype: FileType
    points: T.Sequence[geo.Point]
    make: T.Optional[str] = None
    model: T.Optional[str] = None
    filesize: T.Optional[int] = None

    def update_md5sum(self) -> None:
        if self.md5sum is None:
            with self.filename.open("rb") as fp:
                self.md5sum = utils.md5sum_fp(fp).hexdigest()


@dataclasses.dataclass
class ErrorMetadata:
    filename: Path
    filetype: T.Optional[FileType]
    error: Exception


ImageMetadataOrError = T.Union[ImageMetadata, ErrorMetadata]
VideoMetadataOrError = T.Union[VideoMetadata, ErrorMetadata]
Metadata = T.Union[ImageMetadata, VideoMetadata]
MetadataOrError = T.Union[Metadata, ErrorMetadata]


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
    MAPDeviceMake: str
    MAPDeviceModel: str
    MAPGPSAccuracyMeters: float
    MAPCameraUUID: str
    MAPOrientation: int


class ImageDescription(_SequenceOnly, _Image, MetaProperties, total=True):
    # filename is required
    filename: str
    # if None or absent, it will be calculated
    md5sum: T.Optional[str]
    filetype: Literal["image"]
    filesize: T.Optional[int]


class _VideoDescriptionRequired(TypedDict, total=True):
    filename: str
    # if None or absent, it will be calculated
    md5sum: T.Optional[str]
    filetype: str
    MAPGPSTrack: T.List[T.Sequence[T.Union[float, int, None]]]


class VideoDescription(_VideoDescriptionRequired, total=False):
    MAPDeviceMake: str
    MAPDeviceModel: str
    filesize: T.Optional[int]


class _ErrorDescription(TypedDict, total=False):
    # type and message are required
    type: str
    message: str
    # vars is optional
    vars: T.Dict


class _ImageDescriptionErrorRequired(TypedDict, total=True):
    filename: str
    error: _ErrorDescription


class ImageDescriptionError(_ImageDescriptionErrorRequired, total=False):
    filetype: str


def _describe_error_desc(
    exc: Exception, filename: Path, filetype: T.Optional[FileType]
) -> ImageDescriptionError:
    err: _ErrorDescription = {
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

    desc: ImageDescriptionError = {
        "error": err,
        "filename": str(filename.resolve()),
    }
    if filetype is not None:
        desc["filetype"] = filetype.value

    return desc


def describe_error_metadata(
    exc: Exception, filename: Path, filetype: T.Optional[FileType]
) -> ErrorMetadata:
    return ErrorMetadata(filename=filename, filetype=filetype, error=exc)


Description = T.Union[ImageDescription, VideoDescription]
DescriptionOrError = T.Union[ImageDescription, VideoDescription, ImageDescriptionError]


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
        # deprecated since v0.10.0; keep here for compatibility
        "MAPMetaTags": {"type": "object"},
        "MAPDeviceMake": {"type": "string"},
        "MAPDeviceModel": {"type": "string"},
        "MAPGPSAccuracyMeters": {"type": "number"},
        "MAPCameraUUID": {"type": "string"},
        # deprecated since v0.10.0; keep here for compatibility
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
            "md5sum": {
                "type": ["string", "null"],
                "description": "MD5 checksum of the image content. If not provided, the uploader will compute it",
            },
            "filesize": {
                "type": ["number", "null"],
                "description": "File size",
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
            "md5sum": {
                "type": ["string", "null"],
                "description": "MD5 checksum of the video content. If not provided, the uploader will compute it",
            },
            "filesize": {
                "type": ["number", "null"],
                "description": "File size",
            },
            "filetype": {
                "type": "string",
                "enum": [
                    FileType.CAMM.value,
                    FileType.GOPRO.value,
                    FileType.BLACKVUE.value,
                    FileType.VIDEO.value,
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


def validate_image_desc(desc: T.Any) -> None:
    try:
        jsonschema.validate(instance=desc, schema=ImageDescriptionFileSchema)
    except jsonschema.ValidationError as ex:
        # do not use str(ex) which is more verbose
        raise exceptions.MapillaryMetadataValidationError(ex.message)
    try:
        map_capture_time_to_datetime(desc["MAPCaptureTime"])
    except ValueError as ex:
        raise exceptions.MapillaryMetadataValidationError(str(ex))


def validate_video_desc(desc: T.Any) -> None:
    try:
        jsonschema.validate(instance=desc, schema=VideoDescriptionFileSchema)
    except jsonschema.ValidationError as ex:
        # do not use str(ex) which is more verbose
        raise exceptions.MapillaryMetadataValidationError(ex.message)


def datetime_to_map_capture_time(time: T.Union[datetime.datetime, int, float]) -> str:
    if isinstance(time, (float, int)):
        dt = datetime.datetime.utcfromtimestamp(time)
        # otherwise it will be assumed to be in local time
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        # otherwise it will be assumed to be in local time
        dt = time.astimezone(datetime.timezone.utc)
    return datetime.datetime.strftime(dt, "%Y_%m_%d_%H_%M_%S_%f")[:-3]


def map_capture_time_to_datetime(time: str) -> datetime.datetime:
    dt = datetime.datetime.strptime(time, "%Y_%m_%d_%H_%M_%S_%f")
    dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


@T.overload
def as_desc(metadata: ImageMetadata) -> ImageDescription: ...


@T.overload
def as_desc(metadata: ErrorMetadata) -> ImageDescriptionError: ...


@T.overload
def as_desc(metadata: VideoMetadata) -> VideoDescription: ...


def as_desc(metadata):
    if isinstance(metadata, ErrorMetadata):
        return _describe_error_desc(
            metadata.error, metadata.filename, metadata.filetype
        )
    elif isinstance(metadata, VideoMetadata):
        return _as_video_desc(metadata)
    else:
        assert isinstance(metadata, ImageMetadata)
        return _as_image_desc(metadata)


def _as_video_desc(metadata: VideoMetadata) -> VideoDescription:
    desc: VideoDescription = {
        "filename": str(metadata.filename.resolve()),
        "md5sum": metadata.md5sum,
        "filetype": metadata.filetype.value,
        "filesize": metadata.filesize,
        "MAPGPSTrack": [_encode_point(p) for p in metadata.points],
    }
    if metadata.make:
        desc["MAPDeviceMake"] = metadata.make
    if metadata.model:
        desc["MAPDeviceModel"] = metadata.model
    return desc


def _as_image_desc(metadata: ImageMetadata) -> ImageDescription:
    desc: ImageDescription = {
        "filename": str(metadata.filename.resolve()),
        "md5sum": metadata.md5sum,
        "filesize": metadata.filesize,
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


@T.overload
def from_desc(metadata: ImageDescription) -> ImageMetadata: ...


@T.overload
def from_desc(metadata: VideoDescription) -> VideoMetadata: ...


def from_desc(desc):
    assert "error" not in desc
    if desc["filetype"] == FileType.IMAGE.value:
        return _from_image_desc(desc)
    else:
        return _from_video_desc(desc)


def _from_image_desc(desc) -> ImageMetadata:
    kwargs: T.Dict = {}
    for k, v in desc.items():
        if k not in [
            "filename",
            "md5sum",
            "filesize",
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
        md5sum=desc.get("md5sum"),
        filesize=desc.get("filesize"),
        lat=desc["MAPLatitude"],
        lon=desc["MAPLongitude"],
        alt=desc.get("MAPAltitude"),
        time=geo.as_unix_time(map_capture_time_to_datetime(desc["MAPCaptureTime"])),
        angle=desc.get("MAPCompassHeading", {}).get("TrueHeading"),
        width=None,
        height=None,
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


def _from_video_desc(desc: VideoDescription) -> VideoMetadata:
    return VideoMetadata(
        filename=Path(desc["filename"]),
        md5sum=desc["md5sum"],
        filesize=desc["filesize"],
        filetype=FileType(desc["filetype"]),
        points=[_decode_point(entry) for entry in desc["MAPGPSTrack"]],
        make=desc.get("MAPDeviceMake"),
        model=desc.get("MAPDeviceModel"),
    )


def validate_and_fail_desc(desc: DescriptionOrError) -> DescriptionOrError:
    if "error" in desc:
        return desc

    filetype = desc.get("filetype")
    try:
        if filetype == FileType.IMAGE.value:
            validate_image_desc(desc)
        else:
            validate_video_desc(desc)
    except exceptions.MapillaryMetadataValidationError as ex:
        return _describe_error_desc(
            ex,
            Path(desc["filename"]),
            filetype=FileType(filetype) if filetype else None,
        )

    if not os.path.isfile(desc["filename"]):
        return _describe_error_desc(
            exceptions.MapillaryMetadataValidationError(
                f"No such file {desc['filename']}"
            ),
            Path(desc["filename"]),
            filetype=FileType(filetype) if filetype else None,
        )

    return desc


# Same as validate_and_fail_desc but for the metadata dataclass
def validate_and_fail_metadata(metadata: MetadataOrError) -> MetadataOrError:
    if isinstance(metadata, ErrorMetadata):
        return metadata

    filetype: T.Optional[FileType] = None
    try:
        if isinstance(metadata, ImageMetadata):
            filetype = FileType.IMAGE
            validate_image_desc(as_desc(metadata))
        else:
            assert isinstance(metadata, VideoMetadata)
            filetype = metadata.filetype
            validate_video_desc(as_desc(metadata))
    except exceptions.MapillaryMetadataValidationError as ex:
        # rethrow because the original error is too verbose
        return describe_error_metadata(
            ex,
            metadata.filename,
            filetype=filetype,
        )

    if not metadata.filename.is_file():
        return describe_error_metadata(
            exceptions.MapillaryMetadataValidationError(
                f"No such file {metadata.filename}"
            ),
            metadata.filename,
            filetype=filetype,
        )

    return metadata


def desc_file_to_exif(
    desc: ImageDescription,
) -> ImageDescription:
    not_needed = ["MAPSequenceUUID"]
    removed = {
        key: value
        for key, value in desc.items()
        if key.startswith("MAP") and key not in not_needed
    }
    return T.cast(ImageDescription, removed)


def group_and_sort_images(
    metadatas: T.Sequence[ImageMetadata],
) -> T.Dict[str, T.List[ImageMetadata]]:
    # group metadatas by uuid
    sequences_by_uuid: T.Dict[str, T.List[ImageMetadata]] = {}
    missing_sequence_uuid = str(uuid.uuid4())
    for metadata in metadatas:
        if metadata.MAPSequenceUUID is None:
            sequence_uuid = missing_sequence_uuid
        else:
            sequence_uuid = metadata.MAPSequenceUUID
        sequences_by_uuid.setdefault(sequence_uuid, []).append(metadata)

    # deduplicate and sort metadatas per uuid
    sorted_sequences_by_uuid = {}
    for sequence_uuid, sequence in sequences_by_uuid.items():
        dedups = {metadata.filename.resolve(): metadata for metadata in sequence}
        sorted_sequences_by_uuid[sequence_uuid] = sorted(
            dedups.values(),
            key=lambda metadata: metadata.sort_key(),
        )
    return sorted_sequences_by_uuid


def sequence_md5sum(sequence: T.Iterable[ImageMetadata]) -> str:
    md5 = hashlib.md5()
    for metadata in sequence:
        assert isinstance(metadata.md5sum, str), "md5sum should be calculated"
        md5.update(metadata.md5sum.encode("utf-8"))
    return md5.hexdigest()


if __name__ == "__main__":
    print(json.dumps(ImageVideoDescriptionFileSchema, indent=4))
