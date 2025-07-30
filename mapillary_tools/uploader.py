from __future__ import annotations

import concurrent.futures

import dataclasses
import io
import json
import logging
import os
import struct
import sys
import tempfile
import threading
import time
import typing as T
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

if sys.version_info >= (3, 11):
    from typing import Required
else:
    from typing_extensions import Required

import requests

from . import (
    api_v4,
    config,
    constants,
    exif_write,
    geo,
    telemetry,
    types,
    upload_api_v4,
    utils,
)
from .camm import camm_builder, camm_parser
from .gpmf import gpmf_parser
from .mp4 import simple_mp4_builder
from .serializer.description import (
    desc_file_to_exif,
    DescriptionJSONSerializer,
    validate_image_desc,
)


LOG = logging.getLogger(__name__)


class UploaderProgress(T.TypedDict, total=True):
    """
    Progress data that Uploader cares about.
    """

    # The size, in bytes, of the last chunk that has been read and upload
    chunk_size: int

    # The initial offset returned by the upload service, which is also the offset
    # uploader start uploading from.
    # Assert:
    #   - 0 <= begin_offset <= offset <= entity_size
    #   - Be non-None after at least a successful "upload_fetch_offset"
    begin_offset: int | None

    # How many bytes of the file has been uploaded so far
    offset: int

    # Size in bytes of the file (i.e. fp.tell() after seek to the end)
    # NOTE: It's different from filesize in file system
    # Assert:
    #   - offset == entity_size when "upload_end" or "upload_finished"
    entity_size: int

    # An "upload_interrupted" will increase it. Reset to 0 if a chunk is uploaded
    retries: int

    # Cluster ID after finishing the upload
    cluster_id: str


class SequenceProgress(T.TypedDict, total=False):
    """Progress data at sequence level"""

    # Used to check if it is uploaded or not
    sequence_md5sum: Required[str]

    # Used to resume from the previous upload,
    # so it has to an unique identifier (hash) of the upload content
    upload_md5sum: str

    # File type
    file_type: Required[str]

    # How many sequences in total. It's always 1 when uploading Zipfile/BlackVue/CAMM
    total_sequence_count: Required[int]

    # 0-based nth sequence. It is always 0 when uploading Zipfile/BlackVue/CAMM
    sequence_idx: Required[int]

    # How many images in the sequence. It's available only when uploading directories/Zipfiles
    sequence_image_count: int

    # MAPSequenceUUID. It is only available for directory uploading
    sequence_uuid: str

    # Path to the Zipfile/BlackVue/CAMM
    import_path: str


class Progress(SequenceProgress, UploaderProgress):
    pass


class SequenceError(Exception):
    """
    Base class for sequence specific errors. These errors will cause the
    current sequence upload to fail but will not interrupt the overall upload
    process for other sequences.
    """

    pass


class ExifError(SequenceError):
    def __init__(self, message: str, image_path: Path):
        super().__init__(message)
        self.image_path = image_path


class InvalidMapillaryZipFileError(SequenceError):
    pass


EventName = T.Literal[
    "upload_start",
    "upload_fetch_offset",
    "upload_progress",
    "upload_end",
    "upload_finished",
    "upload_interrupted",
]


class EventEmitter:
    events: dict[EventName, list]

    def __init__(self):
        self.events = {}

    def on(self, event: EventName):
        def _wrap(callback):
            self.events.setdefault(event, []).append(callback)
            return callback

        return _wrap

    def emit(self, event: EventName, *args, **kwargs):
        for callback in self.events.get(event, []):
            callback(*args, **kwargs)


@dataclasses.dataclass
class UploadResult:
    result: str | None = None
    error: Exception | None = None


class VideoUploader:
    @classmethod
    def upload_videos(
        cls, mly_uploader: Uploader, video_metadatas: T.Sequence[types.VideoMetadata]
    ) -> T.Generator[tuple[types.VideoMetadata, UploadResult], None, None]:
        for idx, video_metadata in enumerate(video_metadatas):
            try:
                video_metadata.update_md5sum()
            except Exception as ex:
                yield video_metadata, UploadResult(error=ex)
                continue

            assert isinstance(video_metadata.md5sum, str), "md5sum should be updated"

            progress: SequenceProgress = {
                "total_sequence_count": len(video_metadatas),
                "sequence_idx": idx,
                "file_type": video_metadata.filetype.value,
                "import_path": str(video_metadata.filename),
                "sequence_md5sum": video_metadata.md5sum,
            }

            try:
                with cls.build_camm_stream(video_metadata) as camm_fp:
                    # Upload the mp4 stream
                    file_handle = mly_uploader.upload_stream(
                        T.cast(T.IO[bytes], camm_fp),
                        progress=T.cast(T.Dict[str, T.Any], progress),
                    )

                cluster_id = mly_uploader.finish_upload(
                    file_handle,
                    api_v4.ClusterFileType.CAMM,
                    progress=T.cast(T.Dict[str, T.Any], progress),
                )
            except Exception as ex:
                yield video_metadata, UploadResult(error=ex)
            else:
                yield video_metadata, UploadResult(result=cluster_id)

    @classmethod
    @contextmanager
    def build_camm_stream(cls, video_metadata: types.VideoMetadata):
        # Convert video metadata to CAMMInfo
        camm_info = cls.prepare_camm_info(video_metadata)

        # Create the CAMM sample generator
        camm_sample_generator = camm_builder.camm_sample_generator2(camm_info)

        with video_metadata.filename.open("rb") as src_fp:
            # Build the mp4 stream with the CAMM samples
            yield simple_mp4_builder.transform_mp4(src_fp, camm_sample_generator)

    @classmethod
    def prepare_camm_info(
        cls, video_metadata: types.VideoMetadata
    ) -> camm_parser.CAMMInfo:
        camm_info = camm_parser.CAMMInfo(
            make=video_metadata.make or "", model=video_metadata.model or ""
        )

        for point in video_metadata.points:
            if isinstance(point, telemetry.CAMMGPSPoint):
                if camm_info.gps is None:
                    camm_info.gps = []
                camm_info.gps.append(point)

            elif isinstance(point, telemetry.GPSPoint):
                # There is no proper CAMM entry for GoPro GPS
                if camm_info.mini_gps is None:
                    camm_info.mini_gps = []
                camm_info.mini_gps.append(point)

            elif isinstance(point, geo.Point):
                if camm_info.mini_gps is None:
                    camm_info.mini_gps = []
                camm_info.mini_gps.append(point)
            else:
                raise ValueError(f"Unknown point type: {point}")

        if constants.MAPILLARY__EXPERIMENTAL_ENABLE_IMU:
            if video_metadata.filetype is types.FileType.GOPRO:
                with video_metadata.filename.open("rb") as fp:
                    gopro_info = gpmf_parser.extract_gopro_info(fp, telemetry_only=True)
                if gopro_info is not None:
                    camm_info.accl = gopro_info.accl or []
                    camm_info.gyro = gopro_info.gyro or []
                    camm_info.magn = gopro_info.magn or []

        return camm_info


class ZipUploader:
    @classmethod
    def upload_zipfiles(
        cls, mly_uploader: Uploader, zip_paths: T.Sequence[Path]
    ) -> T.Generator[tuple[Path, UploadResult], None, None]:
        for idx, zip_path in enumerate(zip_paths):
            progress: SequenceProgress = {
                "total_sequence_count": len(zip_paths),
                "sequence_idx": idx,
                "import_path": str(zip_path),
                "file_type": types.FileType.ZIP.value,
                "sequence_md5sum": "",  # Placeholder, will be set in upload_zipfile
            }
            try:
                cluster_id = cls._upload_zipfile(
                    mly_uploader,
                    zip_path,
                    progress=T.cast(T.Dict[str, T.Any], progress),
                )
            except Exception as ex:
                yield zip_path, UploadResult(error=ex)
            else:
                yield zip_path, UploadResult(result=cluster_id)

    @classmethod
    def zip_images(
        cls, metadatas: T.Sequence[types.ImageMetadata], zip_dir: Path
    ) -> None:
        """
        Group images into sequences and zip each sequence into a zipfile.
        """
        sequences = types.group_and_sort_images(metadatas)
        os.makedirs(zip_dir, exist_ok=True)

        for sequence_uuid, sequence in sequences.items():
            _validate_metadatas(sequence)
            # For atomicity we write into a WIP file and then rename to the final file
            wip_zip_filename = zip_dir.joinpath(
                f".mly_zip_{uuid.uuid4()}_{sequence_uuid}_{os.getpid()}_{int(time.time())}"
            )
            with cls._wip_file_context(wip_zip_filename) as wip_path:
                with wip_path.open("wb") as wip_fp:
                    cls._zip_sequence_fp(sequence, wip_fp)

    @classmethod
    def zip_images_and_upload(
        cls, uploader: Uploader, image_metadatas: T.Sequence[types.ImageMetadata]
    ) -> T.Generator[tuple[str, UploadResult], None, None]:
        sequences = types.group_and_sort_images(image_metadatas)

        for sequence_idx, (sequence_uuid, sequence) in enumerate(sequences.items()):
            try:
                _validate_metadatas(sequence)
            except Exception as ex:
                yield sequence_uuid, UploadResult(error=ex)
                continue

            with tempfile.NamedTemporaryFile() as fp:
                try:
                    sequence_md5sum = cls._zip_sequence_fp(sequence, fp)
                except Exception as ex:
                    yield sequence_uuid, UploadResult(error=ex)
                    continue

                sequence_progress: SequenceProgress = {
                    "sequence_idx": sequence_idx,
                    "total_sequence_count": len(sequences),
                    "sequence_image_count": len(sequence),
                    "sequence_uuid": sequence_uuid,
                    "file_type": types.FileType.ZIP.value,
                    "sequence_md5sum": sequence_md5sum,
                }

                try:
                    file_handle = uploader.upload_stream(
                        fp, progress=T.cast(T.Dict[str, T.Any], sequence_progress)
                    )
                    cluster_id = uploader.finish_upload(
                        file_handle,
                        api_v4.ClusterFileType.ZIP,
                        progress=T.cast(T.Dict[str, T.Any], sequence_progress),
                    )
                except Exception as ex:
                    yield sequence_uuid, UploadResult(error=ex)
                    continue

            yield sequence_uuid, UploadResult(result=cluster_id)

    @classmethod
    def _upload_zipfile(
        cls,
        uploader: Uploader,
        zip_path: Path,
        progress: dict[str, T.Any] | None = None,
    ) -> str:
        if progress is None:
            progress = {}

        with zipfile.ZipFile(zip_path) as ziph:
            namelist = ziph.namelist()
            if not namelist:
                raise InvalidMapillaryZipFileError("Zipfile has no files")

        with zip_path.open("rb") as zip_fp:
            sequence_md5sum = cls._extract_sequence_md5sum(zip_fp)

        # Send the copy of the input progress to each upload session, to avoid modifying the original one
        mutable_progress: SequenceProgress = {
            **T.cast(SequenceProgress, progress),
            "sequence_image_count": len(namelist),
            "sequence_md5sum": sequence_md5sum,
            "file_type": types.FileType.ZIP.value,
        }

        with zip_path.open("rb") as zip_fp:
            file_handle = uploader.upload_stream(
                zip_fp, progress=T.cast(T.Dict[str, T.Any], mutable_progress)
            )

        cluster_id = uploader.finish_upload(
            file_handle,
            api_v4.ClusterFileType.ZIP,
            progress=T.cast(T.Dict[str, T.Any], mutable_progress),
        )

        return cluster_id

    @classmethod
    def _zip_sequence_fp(
        cls,
        sequence: T.Sequence[types.ImageMetadata],
        zip_fp: T.IO[bytes],
    ) -> str:
        """
        Write a sequence of ImageMetadata into the zipfile handle.
        The sequence has to be one sequence and sorted.
        """

        sequence_groups = types.group_and_sort_images(sequence)
        assert len(sequence_groups) == 1, (
            f"Only one sequence is allowed but got {len(sequence_groups)}: {list(sequence_groups.keys())}"
        )

        sequence_md5sum = types.update_sequence_md5sum(sequence)

        with zipfile.ZipFile(zip_fp, "w", zipfile.ZIP_DEFLATED) as zipf:
            for idx, metadata in enumerate(sequence):
                # Arcname should be unique, the name does not matter
                arcname = f"{idx}.jpg"
                zipinfo = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
                zipf.writestr(zipinfo, ImageUploader.dump_image_bytes(metadata))
            assert len(sequence) == len(set(zipf.namelist()))
            zipf.comment = json.dumps(
                {"sequence_md5sum": sequence_md5sum},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

        return sequence_md5sum

    @classmethod
    def _extract_sequence_md5sum(cls, zip_fp: T.IO[bytes]) -> str:
        with zipfile.ZipFile(zip_fp, "r", zipfile.ZIP_DEFLATED) as ziph:
            comment = ziph.comment

        if not comment:
            raise InvalidMapillaryZipFileError("No comment found in the zipfile")

        try:
            decoded = comment.decode("utf-8")
            zip_metadata = json.loads(decoded)
        except UnicodeDecodeError as ex:
            raise InvalidMapillaryZipFileError(str(ex)) from ex
        except json.JSONDecodeError as ex:
            raise InvalidMapillaryZipFileError(str(ex)) from ex

        sequence_md5sum = zip_metadata.get("sequence_md5sum")

        if not sequence_md5sum and not isinstance(sequence_md5sum, str):
            raise InvalidMapillaryZipFileError("No sequence_md5sum found")

        return sequence_md5sum

    @classmethod
    @contextmanager
    def _wip_file_context(cls, wip_path: Path):
        try:
            os.remove(wip_path)
        except FileNotFoundError:
            pass
        try:
            yield wip_path

            with wip_path.open("rb") as fp:
                upload_md5sum = utils.md5sum_fp(fp).hexdigest()

            done_path = wip_path.parent.joinpath(
                _session_key(upload_md5sum, api_v4.ClusterFileType.ZIP)
            )

            try:
                os.remove(done_path)
            except FileNotFoundError:
                pass
            wip_path.rename(done_path)
        finally:
            try:
                os.remove(wip_path)
            except FileNotFoundError:
                pass


class ImageUploader:
    @classmethod
    def upload_images(
        cls, uploader: Uploader, image_metadatas: T.Sequence[types.ImageMetadata]
    ) -> T.Generator[tuple[str, UploadResult], None, None]:
        sequences = types.group_and_sort_images(image_metadatas)

        for sequence_idx, (sequence_uuid, sequence) in enumerate(sequences.items()):
            sequence_md5sum = types.update_sequence_md5sum(sequence)

            sequence_progress: SequenceProgress = {
                "sequence_idx": sequence_idx,
                "total_sequence_count": len(sequences),
                "sequence_image_count": len(sequence),
                "sequence_uuid": sequence_uuid,
                "file_type": types.FileType.IMAGE.value,
                "sequence_md5sum": sequence_md5sum,
            }

            try:
                cluster_id = cls._upload_sequence(
                    uploader,
                    sequence,
                    progress=T.cast(dict[str, T.Any], sequence_progress),
                )
            except Exception as ex:
                yield sequence_uuid, UploadResult(error=ex)
            else:
                yield sequence_uuid, UploadResult(result=cluster_id)

    @classmethod
    def dump_image_bytes(cls, metadata: types.ImageMetadata) -> bytes:
        try:
            edit = exif_write.ExifEdit(metadata.filename)
        except struct.error as ex:
            raise ExifError(f"Failed to load EXIF: {ex}", metadata.filename) from ex

        # The cast is to fix the type checker error
        edit.add_image_description(
            T.cast(
                T.Dict, desc_file_to_exif(DescriptionJSONSerializer.as_desc(metadata))
            )
        )

        try:
            return edit.dump_image_bytes()
        except struct.error as ex:
            raise ExifError(
                f"Failed to dump EXIF bytes: {ex}", metadata.filename
            ) from ex

    @classmethod
    def _upload_sequence(
        cls,
        uploader: Uploader,
        sequence: T.Sequence[types.ImageMetadata],
        progress: dict[str, T.Any] | None = None,
    ) -> str:
        if progress is None:
            progress = {}

        # FIXME: This is a hack to disable the event emitter inside the uploader
        uploader_without_emitter = uploader.copy_uploader_without_emitter()

        lock = threading.Lock()

        def _upload_image(image_metadata: types.ImageMetadata) -> str:
            mutable_progress = {
                **(progress or {}),
                "filename": str(image_metadata.filename),
            }

            bytes = cls.dump_image_bytes(image_metadata)
            file_handle = uploader_without_emitter.upload_stream(
                io.BytesIO(bytes), progress=mutable_progress
            )

            mutable_progress["chunk_size"] = image_metadata.filesize

            with lock:
                uploader.emitter.emit("upload_progress", mutable_progress)

            return file_handle

        _validate_metadatas(sequence)

        progress["entity_size"] = sum(m.filesize or 0 for m in sequence)

        # TODO: assert sequence is sorted

        uploader.emitter.emit("upload_start", progress)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=constants.MAX_IMAGE_UPLOAD_WORKERS
        ) as executor:
            image_file_handles = list(executor.map(_upload_image, sequence))

        manifest = {
            "version": "1",
            "upload_type": "images",
            "image_handles": image_file_handles,
        }

        with io.BytesIO() as manifest_fp:
            manifest_fp.write(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            manifest_fp.seek(0, io.SEEK_SET)
            manifest_file_handle = uploader_without_emitter.upload_stream(
                manifest_fp, session_key=f"{uuid.uuid4().hex}.json"
            )

        uploader.emitter.emit("upload_end", progress)

        cluster_id = uploader.finish_upload(
            manifest_file_handle,
            api_v4.ClusterFileType.MLY_BUNDLE_MANIFEST,
            progress=progress,
        )

        return cluster_id


class Uploader:
    def __init__(
        self,
        user_items: config.UserItem,
        emitter: EventEmitter | None = None,
        chunk_size: int = int(constants.UPLOAD_CHUNK_SIZE_MB * 1024 * 1024),
        dry_run: bool = False,
        nofinish: bool = False,
        noresume: bool = False,
    ):
        self.user_items = user_items
        if emitter is None:
            # An empty event emitter that does nothing
            self.emitter = EventEmitter()
        else:
            self.emitter = emitter
        self.chunk_size = chunk_size
        self.dry_run = dry_run
        self.nofinish = nofinish
        self.noresume = noresume

    def upload_stream(
        self,
        fp: T.IO[bytes],
        session_key: str | None = None,
        progress: dict[str, T.Any] | None = None,
    ) -> str:
        if progress is None:
            progress = {}

        if session_key is None:
            if self.noresume:
                # Generate a unique UUID for session_key when noresume is True
                # to prevent resuming from previous uploads
                unique_id = "uuid_" + uuid.uuid4().hex
                filetype = progress.get("file_type")
                if filetype is not None:
                    session_key = _session_key(unique_id, types.FileType(filetype))
                else:
                    session_key = unique_id
            else:
                fp.seek(0, io.SEEK_SET)
                md5sum = utils.md5sum_fp(fp).hexdigest()
                filetype = progress.get("file_type")
                if filetype is not None:
                    session_key = _session_key(md5sum, types.FileType(filetype))
                else:
                    session_key = md5sum

        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        upload_service = self._create_upload_service(session_key)

        progress["entity_size"] = entity_size
        progress["chunk_size"] = self.chunk_size
        progress["retries"] = 0
        progress["begin_offset"] = None

        self.emitter.emit("upload_start", progress)

        while True:
            try:
                file_handle = self._upload_stream_retryable(
                    upload_service, fp, T.cast(UploaderProgress, progress)
                )
            except Exception as ex:
                self._handle_upload_exception(ex, T.cast(UploaderProgress, progress))
            else:
                break

            progress["retries"] += 1

        self.emitter.emit("upload_end", progress)

        return file_handle

    def finish_upload(
        self,
        file_handle: str,
        cluster_filetype: api_v4.ClusterFileType,
        progress: dict[str, T.Any] | None = None,
    ) -> str:
        """Finish upload with safe retries guraranteed"""
        if progress is None:
            progress = {}

        if self.dry_run or self.nofinish:
            cluster_id = "0"
        else:
            resp = api_v4.finish_upload(
                self.user_items["user_upload_token"],
                file_handle,
                cluster_filetype,
                organization_id=self.user_items.get("MAPOrganizationKey"),
            )

            data = resp.json()
            cluster_id = data.get("cluster_id")

            # TODO: validate cluster_id

        progress["cluster_id"] = cluster_id
        self.emitter.emit("upload_finished", progress)

        return cluster_id

    def copy_uploader_without_emitter(self) -> Uploader:
        return Uploader(
            self.user_items,
            emitter=None,
            chunk_size=self.chunk_size,
            dry_run=self.dry_run,
            nofinish=self.nofinish,
            noresume=self.noresume,
        )

    def _create_upload_service(self, session_key: str) -> upload_api_v4.UploadService:
        upload_service: upload_api_v4.UploadService

        if self.dry_run:
            upload_path = os.getenv("MAPILLARY_UPLOAD_ENDPOINT")
            upload_service = upload_api_v4.FakeUploadService(
                user_access_token=self.user_items["user_upload_token"],
                session_key=session_key,
                upload_path=Path(upload_path) if upload_path is not None else None,
            )
            LOG.info(
                "Dry run mode enabled. Data will be uploaded to %s",
                upload_service.upload_path.joinpath(session_key),
            )
        else:
            upload_service = upload_api_v4.UploadService(
                user_access_token=self.user_items["user_upload_token"],
                session_key=session_key,
            )

        return upload_service

    def _handle_upload_exception(
        self, ex: Exception, progress: UploaderProgress
    ) -> None:
        retries = progress["retries"]
        begin_offset = progress.get("begin_offset")
        chunk_size = progress["chunk_size"]

        if retries <= constants.MAX_UPLOAD_RETRIES and _is_retriable_exception(ex):
            self.emitter.emit("upload_interrupted", progress)
            LOG.warning(
                # use %s instead of %d because offset could be None
                "Error uploading chunk_size %d at begin_offset %s: %s: %s",
                chunk_size,
                begin_offset,
                ex.__class__.__name__,
                str(ex),
            )
            # Keep things immutable here. Will increment retries in the caller
            retries += 1
            if _is_immediate_retry(ex):
                sleep_for = 0
            else:
                sleep_for = min(2**retries, 16)
            LOG.info(
                "Retrying in %d seconds (%d/%d)",
                sleep_for,
                retries,
                constants.MAX_UPLOAD_RETRIES,
            )
            if sleep_for:
                time.sleep(sleep_for)
        else:
            raise ex

    def _chunk_with_progress_emitted(
        self,
        stream: T.IO[bytes],
        progress: UploaderProgress,
    ) -> T.Generator[bytes, None, None]:
        for chunk in upload_api_v4.UploadService.chunkize_byte_stream(
            stream, self.chunk_size
        ):
            yield chunk

            progress["offset"] += len(chunk)
            progress["chunk_size"] = len(chunk)
            # Whenever a chunk is uploaded, reset retries
            progress["retries"] = 0

            self.emitter.emit("upload_progress", progress)

    def _upload_stream_retryable(
        self,
        upload_service: upload_api_v4.UploadService,
        fp: T.IO[bytes],
        progress: UploaderProgress,
    ) -> str:
        """Upload the stream with safe retries guraranteed"""

        begin_offset = upload_service.fetch_offset()

        progress["begin_offset"] = begin_offset
        progress["offset"] = begin_offset

        self.emitter.emit("upload_fetch_offset", progress)

        fp.seek(begin_offset, io.SEEK_SET)

        shifted_chunks = self._chunk_with_progress_emitted(fp, progress)

        return upload_service.upload_shifted_chunks(shifted_chunks, begin_offset)


def _validate_metadatas(metadatas: T.Sequence[types.ImageMetadata]):
    for metadata in metadatas:
        validate_image_desc(DescriptionJSONSerializer.as_desc(metadata))
        if not metadata.filename.is_file():
            raise FileNotFoundError(f"No such file {metadata.filename}")


def _is_immediate_retry(ex: Exception):
    if (
        isinstance(ex, requests.HTTPError)
        and isinstance(ex.response, requests.Response)
        and ex.response.status_code == 412
    ):
        try:
            resp = ex.response.json()
        except json.JSONDecodeError:
            return False
        # resp: {"debug_info":{"retriable":true,"type":"OffsetInvalidError","message":"Request starting offset is invalid"}}
        return resp.get("debug_info", {}).get("retriable", False)


def _is_retriable_exception(ex: Exception):
    if isinstance(ex, (requests.ConnectionError, requests.Timeout)):
        return True

    if isinstance(ex, requests.HTTPError) and isinstance(
        ex.response, requests.Response
    ):
        if 400 <= ex.response.status_code < 500:
            try:
                resp = ex.response.json()
            except json.JSONDecodeError:
                return False
            return resp.get("debug_info", {}).get("retriable", False)
        else:
            return True

    return False


def _session_key(
    upload_md5sum: str, filetype: api_v4.ClusterFileType | types.FileType
) -> str:
    _SUFFIX_MAP: dict[api_v4.ClusterFileType | types.FileType, str] = {
        api_v4.ClusterFileType.ZIP: ".zip",
        api_v4.ClusterFileType.CAMM: ".mp4",
        api_v4.ClusterFileType.BLACKVUE: ".mp4",
        types.FileType.IMAGE: ".jpg",
        types.FileType.ZIP: ".zip",
        types.FileType.BLACKVUE: ".mp4",
        types.FileType.CAMM: ".mp4",
        types.FileType.GOPRO: ".mp4",
        types.FileType.VIDEO: ".mp4",
    }

    return f"mly_tools_{upload_md5sum}{_SUFFIX_MAP[filetype]}"
