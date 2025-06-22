from __future__ import annotations

import dataclasses
import enum
import hashlib
import sys
import typing as T
import uuid
from pathlib import Path

if sys.version_info >= (3, 11):
    from typing import Required
else:
    from typing_extensions import Required

from . import geo, utils


class FileType(enum.Enum):
    IMAGE = "image"
    ZIP = "zip"
    # VIDEO is a superset of all NATIVE_VIDEO_FILETYPES below.
    # It also contains the videos that external geotag source (e.g. exiftool) supports
    VIDEO = "video"
    BLACKVUE = "blackvue"
    CAMM = "camm"
    GOPRO = "gopro"


NATIVE_VIDEO_FILETYPES = {
    FileType.BLACKVUE,
    FileType.CAMM,
    FileType.GOPRO,
}


@dataclasses.dataclass
class ImageMetadata(geo.Point):
    filename: Path
    # filetype should be always FileType.IMAGE
    md5sum: str | None = None
    width: int | None = None
    height: int | None = None
    filesize: int | None = None

    # Fields starting with MAP* will be written to the image EXIF
    MAPSequenceUUID: str | None = None
    MAPDeviceMake: str | None = None
    MAPDeviceModel: str | None = None
    MAPGPSAccuracyMeters: float | None = None
    MAPCameraUUID: str | None = None
    MAPOrientation: int | None = None
    MAPMetaTags: dict | None = None
    MAPFilename: str | None = None

    def update_md5sum(self, image_data: T.BinaryIO | None = None) -> None:
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
    filetype: FileType
    points: T.Sequence[geo.Point]
    md5sum: str | None = None
    make: str | None = None
    model: str | None = None
    filesize: int | None = None

    def update_md5sum(self) -> None:
        if self.md5sum is None:
            with self.filename.open("rb") as fp:
                self.md5sum = utils.md5sum_fp(fp).hexdigest()


@dataclasses.dataclass
class ErrorMetadata:
    filename: Path
    filetype: FileType
    error: Exception


ImageMetadataOrError = T.Union[ImageMetadata, ErrorMetadata]
VideoMetadataOrError = T.Union[VideoMetadata, ErrorMetadata]
Metadata = T.Union[ImageMetadata, VideoMetadata]
MetadataOrError = T.Union[Metadata, ErrorMetadata]


# Assume {GOPRO, VIDEO} are the NATIVE_VIDEO_FILETYPES:
# a             | b               = result
# {CAMM}        | {GOPRO}         = {}
# {CAMM}        | {GOPRO, VIDEO}  = {CAMM}
# {GOPRO}       | {GOPRO, VIDEO}  = {GOPRO}
# {GOPRO}       | {VIDEO}         = {GOPRO}
# {CAMM, GOPRO} | {VIDEO}         = {CAMM, GOPRO}
# {VIDEO}       | {VIDEO}         = {CAMM, GOPRO, VIDEO}
def combine_filetype_filters(
    a: set[FileType] | None, b: set[FileType] | None
) -> set[FileType] | None:
    if a is None:
        return b

    if b is None:
        return a

    # VIDEO is a superset of NATIVE_VIDEO_FILETYPES,
    # so we add NATIVE_VIDEO_FILETYPES to each set for intersection later

    if FileType.VIDEO in a:
        a = a | NATIVE_VIDEO_FILETYPES

    if FileType.VIDEO in b:
        b = b | NATIVE_VIDEO_FILETYPES

    return a.intersection(b)


M = T.TypeVar("M")


def separate_errors(
    metadatas: T.Iterable[M | ErrorMetadata],
) -> tuple[list[M], list[ErrorMetadata]]:
    good: list[M] = []
    bad: list[ErrorMetadata] = []

    for metadata in metadatas:
        if isinstance(metadata, ErrorMetadata):
            bad.append(metadata)
        else:
            good.append(metadata)

    return good, bad


def describe_error_metadata(
    exc: Exception, filename: Path, filetype: FileType
) -> ErrorMetadata:
    return ErrorMetadata(filename=filename, filetype=filetype, error=exc)


def group_and_sort_images(
    metadatas: T.Iterable[ImageMetadata],
) -> dict[str, list[ImageMetadata]]:
    # group metadatas by uuid
    sequences_by_uuid: dict[str, list[ImageMetadata]] = {}
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


def update_sequence_md5sum(sequence: T.Iterable[ImageMetadata]) -> str:
    md5 = hashlib.md5()
    for metadata in sequence:
        metadata.update_md5sum()
        assert isinstance(metadata.md5sum, str), "md5sum should be calculated"
        md5.update(metadata.md5sum.encode("utf-8"))
    return md5.hexdigest()
