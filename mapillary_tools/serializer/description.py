from __future__ import annotations

import dataclasses
import datetime
import json
import sys
import typing as T
from pathlib import Path
from typing import TypedDict

if sys.version_info >= (3, 11):
    from typing import Required
else:
    from typing_extensions import Required

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

import jsonschema

from .. import exceptions, geo
from ..types import (
    BaseSerializer,
    describe_error_metadata,
    ErrorMetadata,
    FileType,
    ImageMetadata,
    Metadata,
    MetadataOrError,
    VideoMetadata,
)


# http://wiki.gis.com/wiki/index.php/Decimal_degrees
# decimal places	degrees	    distance
# 0	                 1.0	    111 km
# 1	                 0.1	    11.1 km
# 2	                 0.01	    1.11 km
# 3	                 0.001	    111 m
# 4	                 0.0001	    11.1 m
# 5	                 0.00001	1.11 m
# 6	                 0.000001	0.111 m
# 7	                 0.0000001	1.11 cm
# 8	                 0.00000001	1.11 mm
_COORDINATES_PRECISION = 7
_ALTITUDE_PRECISION = 3
_ANGLE_PRECISION = 3


class _CompassHeading(TypedDict, total=True):
    TrueHeading: float
    MagneticHeading: float


class _SharedDescription(TypedDict, total=False):
    filename: Required[str]
    filetype: Required[str]

    # if None or absent, it will be calculated
    md5sum: str | None
    filesize: int | None


class ImageDescription(_SharedDescription, total=False):
    MAPLatitude: Required[float]
    MAPLongitude: Required[float]
    MAPAltitude: float
    MAPCaptureTime: Required[str]
    MAPCompassHeading: _CompassHeading

    MAPDeviceMake: str
    MAPDeviceModel: str
    MAPGPSAccuracyMeters: float
    MAPCameraUUID: str
    MAPOrientation: int

    # For grouping images in a sequence
    MAPSequenceUUID: str


class VideoDescription(_SharedDescription, total=False):
    MAPGPSTrack: Required[list[T.Sequence[float | int | None]]]
    MAPDeviceMake: str
    MAPDeviceModel: str


class _ErrorObject(TypedDict, total=False):
    type: Required[str]
    message: Required[str]
    vars: dict


class ErrorDescription(TypedDict, total=False):
    filename: Required[str]
    error: Required[_ErrorObject]
    filetype: str


Description = T.Union[ImageDescription, VideoDescription]
DescriptionOrError = T.Union[ImageDescription, VideoDescription, ErrorDescription]


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


def _merge_schema(*schemas: dict) -> dict:
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


ImageDescriptionFileSchema = _merge_schema(
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


ImageDescriptionFileSchemaValidator = jsonschema.Draft202012Validator(
    ImageDescriptionFileSchema
)


VideoDescriptionFileSchema = _merge_schema(
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


VideoDescriptionFileSchemaValidator = jsonschema.Draft202012Validator(
    VideoDescriptionFileSchema
)


ImageVideoDescriptionFileSchema = {
    "oneOf": [VideoDescriptionFileSchema, ImageDescriptionFileSchema]
}


class DescriptionJSONSerializer(BaseSerializer):
    @override
    @classmethod
    def serialize(cls, metadatas: T.Sequence[MetadataOrError]) -> bytes:
        descs = [cls.as_desc(m) for m in metadatas]
        return json.dumps(descs, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @override
    @classmethod
    def deserialize(cls, data: bytes) -> list[Metadata]:
        descs = json.loads(data)
        return [cls.from_desc(desc) for desc in descs if "error" not in desc]

    @override
    @classmethod
    def deserialize_stream(cls, data: T.IO[bytes]) -> list[Metadata]:
        descs = json.load(data)
        return [cls.from_desc(desc) for desc in descs if "error" not in desc]

    @T.overload
    @classmethod
    def as_desc(cls, metadata: ImageMetadata) -> ImageDescription: ...

    @T.overload
    @classmethod
    def as_desc(cls, metadata: ErrorMetadata) -> ErrorDescription: ...

    @T.overload
    @classmethod
    def as_desc(cls, metadata: VideoMetadata) -> VideoDescription: ...

    @classmethod
    def as_desc(cls, metadata):
        if isinstance(metadata, ErrorMetadata):
            return cls._as_error_desc(
                metadata.error, metadata.filename, metadata.filetype
            )

        elif isinstance(metadata, VideoMetadata):
            return cls._as_video_desc(metadata)

        else:
            assert isinstance(metadata, ImageMetadata)
            return cls._as_image_desc(metadata)

    @classmethod
    def _as_error_desc(
        cls, exc: Exception, filename: Path, filetype: FileType | None
    ) -> ErrorDescription:
        err: _ErrorObject = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }

        exc_vars = vars(exc)

        if exc_vars:
            # handle unserializable exceptions
            try:
                vars_json = json.dumps(exc_vars, sort_keys=True, separators=(",", ":"))
            except Exception:
                vars_json = ""
            if vars_json:
                err["vars"] = json.loads(vars_json)

        desc: ErrorDescription = {
            "error": err,
            "filename": str(filename.resolve()),
        }
        if filetype is not None:
            desc["filetype"] = filetype.value

        return desc

    @classmethod
    def _as_video_desc(cls, metadata: VideoMetadata) -> VideoDescription:
        desc: VideoDescription = {
            "filename": str(metadata.filename.resolve()),
            "md5sum": metadata.md5sum,
            "filetype": metadata.filetype.value,
            "filesize": metadata.filesize,
            "MAPGPSTrack": [PointEncoder.encode(p) for p in metadata.points],
        }
        if metadata.make:
            desc["MAPDeviceMake"] = metadata.make
        if metadata.model:
            desc["MAPDeviceModel"] = metadata.model
        return desc

    @classmethod
    def _as_image_desc(cls, metadata: ImageMetadata) -> ImageDescription:
        desc: ImageDescription = {
            "filename": str(metadata.filename.resolve()),
            "md5sum": metadata.md5sum,
            "filesize": metadata.filesize,
            "filetype": FileType.IMAGE.value,
            "MAPLatitude": round(metadata.lat, _COORDINATES_PRECISION),
            "MAPLongitude": round(metadata.lon, _COORDINATES_PRECISION),
            "MAPCaptureTime": build_capture_time(metadata.time),
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
    @classmethod
    def from_desc(cls, desc: ImageDescription) -> ImageMetadata: ...

    @T.overload
    @classmethod
    def from_desc(cls, desc: VideoDescription) -> VideoMetadata: ...

    @classmethod
    def from_desc(cls, desc):
        if "error" in desc:
            raise ValueError("Cannot deserialize error description")

        if desc["filetype"] == FileType.IMAGE.value:
            return cls._from_image_desc(desc)
        else:
            return cls._from_video_desc(desc)

    @classmethod
    def _from_image_desc(cls, desc) -> ImageMetadata:
        validate_image_desc(desc)

        kwargs: dict = {}
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
            time=geo.as_unix_time(parse_capture_time(desc["MAPCaptureTime"])),
            angle=desc.get("MAPCompassHeading", {}).get("TrueHeading"),
            width=None,
            height=None,
            **kwargs,
        )

    @classmethod
    def _from_video_desc(cls, desc: VideoDescription) -> VideoMetadata:
        validate_video_desc(desc)

        return VideoMetadata(
            filename=Path(desc["filename"]),
            md5sum=desc.get("md5sum"),
            filesize=desc.get("filesize"),
            filetype=FileType(desc["filetype"]),
            points=[PointEncoder.decode(entry) for entry in desc["MAPGPSTrack"]],
            make=desc.get("MAPDeviceMake"),
            model=desc.get("MAPDeviceModel"),
        )


class PointEncoder:
    @classmethod
    def encode(cls, p: geo.Point) -> T.Sequence[float | int | None]:
        entry = [
            int(p.time * 1000),
            round(p.lon, _COORDINATES_PRECISION),
            round(p.lat, _COORDINATES_PRECISION),
            round(p.alt, _ALTITUDE_PRECISION) if p.alt is not None else None,
            round(p.angle, _ANGLE_PRECISION) if p.angle is not None else None,
        ]
        return entry

    @classmethod
    def decode(cls, entry: T.Sequence[T.Any]) -> geo.Point:
        time_ms, lon, lat, alt, angle = entry
        return geo.Point(time=time_ms / 1000, lon=lon, lat=lat, alt=alt, angle=angle)


def build_capture_time(time: datetime.datetime | int | float) -> str:
    if isinstance(time, (float, int)):
        dt = datetime.datetime.fromtimestamp(time, datetime.timezone.utc)
        # otherwise it will be assumed to be in local time
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        # otherwise it will be assumed to be in local time
        dt = time.astimezone(datetime.timezone.utc)
    return datetime.datetime.strftime(dt, "%Y_%m_%d_%H_%M_%S_%f")[:-3]


def parse_capture_time(time: str) -> datetime.datetime:
    dt = datetime.datetime.strptime(time, "%Y_%m_%d_%H_%M_%S_%f")
    dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def validate_image_desc(desc: T.Any) -> None:
    try:
        ImageDescriptionFileSchemaValidator.validate(desc)
    except jsonschema.ValidationError as ex:
        # do not use str(ex) which is more verbose
        raise exceptions.MapillaryMetadataValidationError(ex.message) from ex

    try:
        parse_capture_time(desc["MAPCaptureTime"])
    except ValueError as ex:
        raise exceptions.MapillaryMetadataValidationError(str(ex)) from ex


def validate_video_desc(desc: T.Any) -> None:
    try:
        VideoDescriptionFileSchemaValidator.validate(desc)
    except jsonschema.ValidationError as ex:
        # do not use str(ex) which is more verbose
        raise exceptions.MapillaryMetadataValidationError(ex.message) from ex


def validate_and_fail_metadata(metadata: MetadataOrError) -> MetadataOrError:
    if isinstance(metadata, ErrorMetadata):
        return metadata

    if isinstance(metadata, ImageMetadata):
        filetype = FileType.IMAGE
        validate = validate_image_desc
    else:
        assert isinstance(metadata, VideoMetadata)
        filetype = metadata.filetype
        validate = validate_video_desc

    try:
        validate(DescriptionJSONSerializer.as_desc(metadata))
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


def desc_file_to_exif(desc: ImageDescription) -> ImageDescription:
    not_needed = ["MAPSequenceUUID"]
    removed = {
        key: value
        for key, value in desc.items()
        if key.startswith("MAP") and key not in not_needed
    }
    return T.cast(ImageDescription, removed)


if __name__ == "__main__":
    print(json.dumps(ImageVideoDescriptionFileSchema, indent=4))
