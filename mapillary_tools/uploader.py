from __future__ import annotations

import dataclasses
import io
import json
import logging
import os
import struct
import tempfile
import time
import typing as T
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

import requests

from . import api_v4, constants, exif_write, types, upload_api_v4, utils


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
    sequence_md5sum: str

    # Used to resume from the previous upload,
    # so it has to an unique identifier (hash) of the upload content
    upload_md5sum: str

    # File type
    file_type: str

    # How many sequences in total. It's always 1 when uploading Zipfile/BlackVue/CAMM
    total_sequence_count: int

    # 0-based nth sequence. It is always 0 when uploading Zipfile/BlackVue/CAMM
    sequence_idx: int

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


class ZipImageSequence:
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
                    cls.zip_sequence_fp(sequence, wip_fp)

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

    @classmethod
    def zip_sequence_fp(
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
                zipf.writestr(zipinfo, cls._dump_image_bytes(metadata))
            assert len(sequence) == len(set(zipf.namelist()))
            zipf.comment = json.dumps({"sequence_md5sum": sequence_md5sum}).encode(
                "utf-8"
            )

        return sequence_md5sum

    @classmethod
    def extract_sequence_md5sum(cls, zip_fp: T.IO[bytes]) -> str:
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
    def _dump_image_bytes(cls, metadata: types.ImageMetadata) -> bytes:
        try:
            edit = exif_write.ExifEdit(metadata.filename)
        except struct.error as ex:
            raise ExifError(f"Failed to load EXIF: {ex}", metadata.filename) from ex

        # The cast is to fix the type checker error
        edit.add_image_description(
            T.cast(T.Dict, types.desc_file_to_exif(types.as_desc(metadata)))
        )

        try:
            return edit.dump_image_bytes()
        except struct.error as ex:
            raise ExifError(
                f"Failed to dump EXIF bytes: {ex}", metadata.filename
            ) from ex

    @classmethod
    def upload_zipfile(
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
            sequence_md5sum = cls.extract_sequence_md5sum(zip_fp)

        sequence_progress: SequenceProgress = {
            "sequence_image_count": len(namelist),
            "file_type": types.FileType.ZIP.value,
            "sequence_md5sum": sequence_md5sum,
        }

        # Send the copy of the input progress to each upload session, to avoid modifying the original one
        mutable_progress: dict[str, T.Any] = {**progress, **sequence_progress}

        with zip_path.open("rb") as zip_fp:
            file_handle = uploader.upload_stream(zip_fp, progress=mutable_progress)

        cluster_id = uploader.finish_upload(
            file_handle, api_v4.ClusterFileType.ZIP, progress=mutable_progress
        )

        return cluster_id

    @classmethod
    def zip_images_and_upload(
        cls,
        uploader: Uploader,
        image_metadatas: T.Sequence[types.ImageMetadata],
        progress: dict[str, T.Any] | None = None,
    ) -> T.Generator[tuple[str, UploadResult], None, None]:
        if progress is None:
            progress = {}

        sequences = types.group_and_sort_images(image_metadatas)

        for sequence_idx, (sequence_uuid, sequence) in enumerate(sequences.items()):
            sequence_progress: SequenceProgress = {
                "sequence_idx": sequence_idx,
                "total_sequence_count": len(sequences),
                "sequence_image_count": len(sequence),
                "sequence_uuid": sequence_uuid,
                "file_type": types.FileType.ZIP.value,
            }

            try:
                _validate_metadatas(sequence)
            except Exception as ex:
                yield sequence_uuid, UploadResult(error=ex)
                continue

            with tempfile.NamedTemporaryFile() as fp:
                try:
                    sequence_md5sum = cls.zip_sequence_fp(sequence, fp)
                except Exception as ex:
                    yield sequence_uuid, UploadResult(error=ex)
                    continue

                sequence_progress["sequence_md5sum"] = sequence_md5sum

                mutable_progress: dict[str, T.Any] = {**progress, **sequence_progress}

                try:
                    file_handle = uploader.upload_stream(fp, progress=mutable_progress)
                    cluster_id = uploader.finish_upload(
                        file_handle,
                        api_v4.ClusterFileType.ZIP,
                        progress=mutable_progress,
                    )
                except Exception as ex:
                    yield sequence_uuid, UploadResult(error=ex)
                    continue

            yield sequence_uuid, UploadResult(result=cluster_id)

    @classmethod
    def _upload_sequence(
        cls,
        uploader: Uploader,
        sequence: T.Sequence[types.ImageMetadata],
        progress: dict[str, T.Any] | None = None,
    ) -> str:
        if progress is None:
            progress = {}

        _validate_metadatas(sequence)

        # TODO: assert sequence is sorted

        # FIXME: This is a hack to disable the event emitter inside the uploader
        uploader.emittion_disabled = True

        uploader.emitter.emit("upload_start", progress)

        image_file_handles: list[str] = []
        total_bytes = 0
        for image_metadata in sequence:
            mutable_progress: dict[str, T.Any] = {
                **progress,
                "filename": str(image_metadata.filename),
            }

            bytes = cls._dump_image_bytes(image_metadata)
            total_bytes += len(bytes)
            file_handle = uploader.upload_stream(
                io.BytesIO(bytes), progress=mutable_progress
            )
            image_file_handles.append(file_handle)

            uploader.emitter.emit("upload_progress", mutable_progress)

        manifest = {
            "version": "1",
            "upload_type": "images",
            "image_handles": image_file_handles,
        }

        with io.BytesIO() as manifest_fp:
            manifest_fp.write(json.dumps(manifest).encode("utf-8"))
            manifest_fp.seek(0, io.SEEK_SET)
            manifest_file_handle = uploader.upload_stream(
                manifest_fp, session_key=f"{uuid.uuid4().hex}.json"
            )

        progress["entity_size"] = total_bytes
        uploader.emitter.emit("upload_end", progress)

        # FIXME: This is a hack to disable the event emitter inside the uploader
        uploader.emittion_disabled = False

        cluster_id = uploader.finish_upload(
            manifest_file_handle,
            api_v4.ClusterFileType.MLY_BUNDLE_MANIFEST,
            progress=progress,
        )

        return cluster_id

    @classmethod
    def upload_images(
        cls,
        uploader: Uploader,
        image_metadatas: T.Sequence[types.ImageMetadata],
        progress: dict[str, T.Any] | None = None,
    ) -> T.Generator[tuple[str, UploadResult], None, None]:
        if progress is None:
            progress = {}

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

            mutable_progress: dict[str, T.Any] = {**progress, **sequence_progress}

            try:
                cluster_id = cls._upload_sequence(
                    uploader, sequence, progress=mutable_progress
                )
            except Exception as ex:
                yield sequence_uuid, UploadResult(error=ex)
            else:
                yield sequence_uuid, UploadResult(result=cluster_id)


class Uploader:
    def __init__(
        self,
        user_items: types.UserItem,
        emitter: EventEmitter | None = None,
        chunk_size: int = int(constants.UPLOAD_CHUNK_SIZE_MB * 1024 * 1024),
        dry_run=False,
    ):
        self.user_items = user_items
        self.emittion_disabled = False
        if emitter is None:
            # An empty event emitter that does nothing
            self.emitter = EventEmitter()
        else:
            self.emitter = emitter
        self.chunk_size = chunk_size
        self.dry_run = dry_run

    def upload_stream(
        self,
        fp: T.IO[bytes],
        session_key: str | None = None,
        progress: dict[str, T.Any] | None = None,
    ) -> str:
        if progress is None:
            progress = {}

        if session_key is None:
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

        self._maybe_emit("upload_start", progress)

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

        self._maybe_emit("upload_end", progress)

        return file_handle

    def _create_upload_service(self, session_key: str) -> upload_api_v4.UploadService:
        upload_service: upload_api_v4.UploadService

        if self.dry_run:
            upload_service = upload_api_v4.FakeUploadService(
                user_access_token=self.user_items["user_upload_token"],
                session_key=session_key,
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
            self._maybe_emit("upload_interrupted", progress)
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

            self._maybe_emit("upload_progress", progress)

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

        self._maybe_emit("upload_fetch_offset", progress)

        fp.seek(begin_offset, io.SEEK_SET)

        shifted_chunks = self._chunk_with_progress_emitted(fp, progress)

        return upload_service.upload_shifted_chunks(shifted_chunks, begin_offset)

    def finish_upload(
        self,
        file_handle: str,
        cluster_filetype: api_v4.ClusterFileType,
        progress: dict[str, T.Any] | None = None,
    ) -> str:
        """Finish upload with safe retries guraranteed"""
        if progress is None:
            progress = {}

        if self.dry_run:
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
        self._maybe_emit("upload_finished", progress)

        return cluster_id

    def _maybe_emit(self, event: EventName, progress: dict[str, T.Any]):
        if not self.emittion_disabled:
            return self.emitter.emit(event, progress)


def _validate_metadatas(metadatas: T.Sequence[types.ImageMetadata]):
    for metadata in metadatas:
        types.validate_image_desc(types.as_desc(metadata))
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
