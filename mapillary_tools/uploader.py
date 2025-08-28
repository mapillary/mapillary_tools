from __future__ import annotations

import concurrent.futures
import dataclasses
import datetime
import email.utils
import hashlib
import io
import json
import logging
import os
import queue
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
    history,
    telemetry,
    types,
    upload_api_v4,
    utils,
    VERSION,
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


@dataclasses.dataclass(frozen=True)
class UploadOptions:
    user_items: config.UserItem
    chunk_size: int = int(constants.UPLOAD_CHUNK_SIZE_MB * 1024 * 1024)
    num_upload_workers: int = constants.MAX_IMAGE_UPLOAD_WORKERS
    # When set, upload cache will be read/write there
    # This option is exposed for testing purpose. In PROD, the path is calculated based on envvar and user_items
    upload_cache_path: Path | None = None
    dry_run: bool = False
    nofinish: bool = False
    noresume: bool = False

    def __post_init__(self):
        if self.num_upload_workers <= 0:
            raise ValueError(
                f"Expect positive num_upload_workers but got {self.num_upload_workers}"
            )

        if self.chunk_size <= 0:
            raise ValueError(f"Expect positive chunk_size but got {self.chunk_size}")


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

    # An "upload_retrying" will increase it. Reset to 0 if a chunk is uploaded
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

    # Path to the image/video/zip
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


# BELOW demonstrates the pseudocode for a typical upload workflow
# and when upload events are emitted
#################################################################
# def pseudo_upload(metadata):
#     emit("upload_start")
#     while True:
#         try:
#             if is_sequence(metadata):
#                 for image in metadata:
#                     upload_stream(image.read())
#                     emit("upload_progress")
#             elif is_video(metadata):
#                 offset = fetch_offset()
#                 emit("upload_fetch_offset")
#                 for chunk in metadata.read()[offset:]:
#                     upload_stream(chunk)
#                     emit("upload_progress")
#         except BaseException as ex:  # Include KeyboardInterrupt
#             if retryable(ex):
#                 emit("upload_retrying")
#                 continue
#             else:
#                 emit("upload_failed")
#                 raise ex
#         else:
#             break
#     emit("upload_end")
#     finish_upload(data)
#     emit("upload_finished")
EventName = T.Literal[
    "upload_start",
    "upload_fetch_offset",
    "upload_progress",
    "upload_retrying",
    "upload_end",
    "upload_failed",
    "upload_finished",
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
        # If upload in a random order, then interrupted uploads has a higher chance to expire.
        # Therefore sort videos to make sure interrupted uploads are resumed as early as possible
        sorted_video_metadatas = sorted(video_metadatas, key=lambda m: m.filename)

        for idx, video_metadata in enumerate(sorted_video_metadatas):
            LOG.debug(f"Checksum for video {video_metadata.filename}...")
            try:
                video_metadata.update_md5sum()
            except Exception as ex:
                yield video_metadata, UploadResult(error=ex)
                continue

            assert isinstance(video_metadata.md5sum, str), "md5sum should be updated"

            progress: SequenceProgress = {
                "total_sequence_count": len(sorted_video_metadatas),
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
        # If upload in a random order, then interrupted uploads has a higher chance to expire.
        # Therefore sort zipfiles to make sure interrupted uploads are resumed as early as possible
        sorted_zip_paths = sorted(zip_paths)

        for idx, zip_path in enumerate(sorted_zip_paths):
            progress: SequenceProgress = {
                "total_sequence_count": len(sorted_zip_paths),
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

        if sequence:
            LOG.debug(f"Checksum for sequence {sequence[0].MAPSequenceUUID}...")
        sequence_md5sum = types.update_sequence_md5sum(sequence)

        with zipfile.ZipFile(zip_fp, "w", zipfile.ZIP_DEFLATED) as zipf:
            for idx, metadata in enumerate(sequence):
                # Arcname should be unique, the name does not matter
                arcname = f"{idx}.jpg"
                zipinfo = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
                zipf.writestr(zipinfo, CachedImageUploader.dump_image_bytes(metadata))
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
                _suffix_session_key(upload_md5sum, api_v4.ClusterFileType.ZIP)
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


class ImageSequenceUploader:
    def __init__(self, upload_options: UploadOptions, emitter: EventEmitter):
        self.upload_options = upload_options
        self.emitter = emitter
        # Create a single shared SingleImageUploader instance that will be used across all uploads
        cache = _maybe_create_persistent_cache_instance(self.upload_options)
        if cache:
            cache.clear_expired()
        self.cached_image_uploader = CachedImageUploader(
            self.upload_options, cache=cache
        )

    def upload_images(
        self, image_metadatas: T.Sequence[types.ImageMetadata]
    ) -> T.Generator[tuple[str, UploadResult], None, None]:
        sequences = types.group_and_sort_images(image_metadatas)

        for sequence_idx, (sequence_uuid, sequence) in enumerate(sequences.items()):
            LOG.debug(f"Checksum for image sequence {sequence_uuid}...")
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
                cluster_id = self._upload_sequence_and_finish(
                    sequence,
                    sequence_progress=T.cast(dict[str, T.Any], sequence_progress),
                )
            except Exception as ex:
                yield sequence_uuid, UploadResult(error=ex)
            else:
                yield sequence_uuid, UploadResult(result=cluster_id)

    def _upload_sequence_and_finish(
        self,
        sequence: T.Sequence[types.ImageMetadata],
        sequence_progress: dict[str, T.Any],
    ) -> str:
        _validate_metadatas(sequence)

        sequence_progress["entity_size"] = sum(m.filesize or 0 for m in sequence)
        self.emitter.emit("upload_start", sequence_progress)

        try:
            # Retries will be handled in the call (but no upload event emissions)
            image_file_handles = self._upload_images_parallel(
                sequence, sequence_progress
            )
        except BaseException as ex:  # Include KeyboardInterrupt
            self.emitter.emit("upload_failed", sequence_progress)
            raise ex

        manifest_file_handle = self._upload_manifest(image_file_handles)

        self.emitter.emit("upload_end", sequence_progress)

        uploader = Uploader(self.upload_options, emitter=self.emitter)
        cluster_id = uploader.finish_upload(
            manifest_file_handle,
            api_v4.ClusterFileType.MLY_BUNDLE_MANIFEST,
            progress=sequence_progress,
        )

        return cluster_id

    def _upload_manifest(self, image_file_handles: T.Sequence[str]) -> str:
        uploader = Uploader(self.upload_options)

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
            return uploader.upload_stream(
                manifest_fp, session_key=f"{_prefixed_uuid4()}.json"
            )

    def _upload_images_parallel(
        self,
        sequence: T.Sequence[types.ImageMetadata],
        sequence_progress: dict[str, T.Any],
    ) -> list[str]:
        if not sequence:
            return []

        max_workers = min(self.upload_options.num_upload_workers, len(sequence))

        # Lock is used to synchronize event emission
        lock = threading.Lock()

        # Push all images into the queue
        image_queue: queue.Queue[tuple[int, types.ImageMetadata]] = queue.Queue()
        for idx, image_metadata in enumerate(sequence):
            image_queue.put((idx, image_metadata))

        upload_interrupted = threading.Event()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self._upload_images_from_queue,
                    image_queue,
                    lock,
                    upload_interrupted,
                    sequence_progress,
                )
                for _ in range(max_workers)
            ]

            indexed_image_file_handles = []

            try:
                for future in futures:
                    indexed_image_file_handles.extend(future.result())
            except KeyboardInterrupt as ex:
                upload_interrupted.set()
                raise ex

        # All tasks should be done here, so below is more like assertion
        image_queue.join()
        if sys.version_info >= (3, 13):
            image_queue.shutdown()

        file_handles: list[str] = []

        indexed_image_file_handles.sort()

        # Important to guarantee the order
        assert len(indexed_image_file_handles) == len(sequence)
        for expected_idx, (idx, file_handle) in enumerate(indexed_image_file_handles):
            assert expected_idx == idx
            file_handles.append(file_handle)

        return file_handles

    def _upload_images_from_queue(
        self,
        image_queue: queue.Queue[tuple[int, types.ImageMetadata]],
        lock: threading.Lock,
        upload_interrupted: threading.Event,
        sequence_progress: dict[str, T.Any],
    ) -> list[tuple[int, str]]:
        indexed_file_handles = []

        with api_v4.create_user_session(
            self.upload_options.user_items["user_upload_token"]
        ) as user_session:
            while True:
                # Assert that all images are already pushed into the queue
                try:
                    idx, image_metadata = image_queue.get_nowait()
                except queue.Empty:
                    break

                # Main thread will handle the interruption
                if upload_interrupted.is_set():
                    break

                # Create a new mutatble progress to keep the sequence_progress immutable
                image_progress = {
                    **sequence_progress,
                    "import_path": str(image_metadata.filename),
                }

                # image_progress will be updated during uploading
                file_handle = self.cached_image_uploader.upload(
                    user_session, image_metadata, image_progress
                )

                # Update chunk_size (it was constant if set)
                image_progress["chunk_size"] = image_metadata.filesize

                # Main thread will handle the interruption
                if upload_interrupted.is_set():
                    break

                with lock:
                    self.emitter.emit("upload_progress", image_progress)

                indexed_file_handles.append((idx, file_handle))

                image_queue.task_done()

        return indexed_file_handles


class CachedImageUploader:
    def __init__(
        self,
        upload_options: UploadOptions,
        cache: history.PersistentCache | None = None,
    ):
        self.upload_options = upload_options
        self.cache = cache
        if self.cache:
            self.cache.clear_expired()

    # Thread-safe
    def upload(
        self,
        user_session: requests.Session,
        image_metadata: types.ImageMetadata,
        image_progress: dict[str, T.Any],
    ) -> str:
        image_bytes = self.dump_image_bytes(image_metadata)

        uploader = Uploader(self.upload_options, user_session=user_session)

        session_key = uploader._gen_session_key(io.BytesIO(image_bytes), image_progress)

        file_handle = self._get_cached_file_handle(session_key)

        if file_handle is None:
            # image_progress will be updated during uploading
            file_handle = uploader.upload_stream(
                io.BytesIO(image_bytes),
                session_key=session_key,
                progress=image_progress,
            )
            self._set_file_handle_cache(session_key, file_handle)

        return file_handle

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

    # Thread-safe
    def _get_cached_file_handle(self, key: str) -> str | None:
        if self.cache is None:
            return None

        if _is_uuid(key):
            return None

        return self.cache.get(key)

    # Thread-safe
    def _set_file_handle_cache(self, key: str, value: str) -> None:
        if self.cache is None:
            return

        if _is_uuid(key):
            return

        self.cache.set(key, value)


class Uploader:
    def __init__(
        self,
        upload_options: UploadOptions,
        user_session: requests.Session | None = None,
        emitter: EventEmitter | None = None,
    ):
        self.upload_options = upload_options
        self.user_session = user_session
        if emitter is None:
            # An empty event emitter that does nothing
            self.emitter = EventEmitter()
        else:
            self.emitter = emitter

    def upload_stream(
        self,
        fp: T.IO[bytes],
        session_key: str | None = None,
        progress: dict[str, T.Any] | None = None,
    ) -> str:
        if progress is None:
            progress = {}

        if session_key is None:
            session_key = self._gen_session_key(fp, progress)

        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        progress["entity_size"] = entity_size
        progress["chunk_size"] = self.upload_options.chunk_size
        progress["retries"] = 0
        progress["begin_offset"] = None

        self.emitter.emit("upload_start", progress)

        while True:
            try:
                if self.user_session is not None:
                    file_handle = self._upload_stream_retryable(
                        self.user_session,
                        fp,
                        session_key,
                        T.cast(UploaderProgress, progress),
                    )
                else:
                    with api_v4.create_user_session(
                        self.upload_options.user_items["user_upload_token"]
                    ) as user_session:
                        file_handle = self._upload_stream_retryable(
                            user_session,
                            fp,
                            session_key,
                            T.cast(UploaderProgress, progress),
                        )
            except BaseException as ex:  # Include KeyboardInterrupt
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

        if self.upload_options.dry_run or self.upload_options.nofinish:
            cluster_id = "0"
        else:
            organization_id = self.upload_options.user_items.get("MAPOrganizationKey")

            with api_v4.create_user_session(
                self.upload_options.user_items["user_upload_token"]
            ) as user_session:
                resp = api_v4.finish_upload(
                    user_session,
                    file_handle,
                    cluster_filetype,
                    organization_id=organization_id,
                )

            body = api_v4.jsonify_response(resp)
            # TODO: Validate cluster_id
            cluster_id = body.get("cluster_id")

        progress["cluster_id"] = cluster_id
        self.emitter.emit("upload_finished", progress)

        return cluster_id

    def _create_upload_service(
        self, user_session: requests.Session, session_key: str
    ) -> upload_api_v4.UploadService:
        upload_service: upload_api_v4.UploadService

        if self.upload_options.dry_run:
            upload_path = os.getenv("MAPILLARY_UPLOAD_ENDPOINT")
            upload_service = upload_api_v4.FakeUploadService(
                user_session,
                session_key,
                upload_path=Path(upload_path) if upload_path is not None else None,
            )
            LOG.info(
                "Dry-run mode enabled, uploading to %s",
                upload_service.upload_path.joinpath(session_key),
            )
        else:
            upload_service = upload_api_v4.UploadService(user_session, session_key)

        return upload_service

    def _handle_upload_exception(
        self, ex: BaseException, progress: UploaderProgress
    ) -> None:
        retries = progress.get("retries", 0)
        begin_offset = progress.get("begin_offset")
        offset = progress.get("offset")

        LOG.warning(
            f"Error uploading {self._upload_name(progress)} at {offset=} since {begin_offset=}: {ex.__class__.__name__}: {ex}"
        )

        if retries <= constants.MAX_UPLOAD_RETRIES:
            retriable, retry_after_sec = _is_retriable_exception(ex)
            if retriable:
                self.emitter.emit("upload_retrying", progress)

                # Keep things immutable here. Will increment retries in the caller
                retries += 1
                if _is_immediate_retriable_exception(ex):
                    sleep_for = 0
                else:
                    sleep_for = min(2**retries, 16)
                sleep_for += retry_after_sec

                LOG.info(
                    f"Retrying in {sleep_for} seconds ({retries}/{constants.MAX_UPLOAD_RETRIES})"
                )
                if sleep_for:
                    time.sleep(sleep_for)

                return

        self.emitter.emit("upload_failed", progress)
        raise ex

    @classmethod
    def _upload_name(cls, progress: UploaderProgress):
        # Strictly speaking these sequence properties should not be exposed in this context
        # TODO: Maybe move these logging statements to event handlers
        sequence_uuid: str | None = T.cast(
            T.Union[str, None], progress.get("sequence_uuid")
        )
        import_path = T.cast(T.Union[str, None], progress.get("import_path"))
        if sequence_uuid is not None:
            if import_path is None:
                name: str = f"sequence_{sequence_uuid}"
            else:
                name = f"sequence_{sequence_uuid}/{Path(import_path).name}"
        else:
            name = Path(import_path or "unknown").name
        return name

    def _chunk_with_progress_emitted(
        self, stream: T.IO[bytes], progress: UploaderProgress
    ) -> T.Generator[bytes, None, None]:
        for chunk in upload_api_v4.UploadService.chunkize_byte_stream(
            stream, self.upload_options.chunk_size
        ):
            yield chunk

            progress["offset"] += len(chunk)
            progress["chunk_size"] = len(chunk)
            # Whenever a chunk is uploaded, reset retries
            progress["retries"] = 0

            self.emitter.emit("upload_progress", progress)

    def _upload_stream_retryable(
        self,
        user_session: requests.Session,
        fp: T.IO[bytes],
        session_key: str,
        progress: UploaderProgress | None = None,
    ) -> str:
        """Upload the stream with safe retries guraranteed"""
        if progress is None:
            progress = T.cast(UploaderProgress, {})

        upload_service = self._create_upload_service(user_session, session_key)

        if "entity_size" not in progress:
            fp.seek(0, io.SEEK_END)
            entity_size = fp.tell()
            progress["entity_size"] = entity_size

        begin_offset = upload_service.fetch_offset()

        progress["begin_offset"] = begin_offset
        progress["offset"] = begin_offset

        self.emitter.emit("upload_fetch_offset", progress)

        # Estimate the read timeout
        if not constants.MIN_UPLOAD_SPEED:
            read_timeout = None
        else:
            remaining_bytes = abs(progress["entity_size"] - begin_offset)
            read_timeout = max(
                api_v4.REQUESTS_TIMEOUT,
                remaining_bytes / constants.MIN_UPLOAD_SPEED,
            )

        # Upload from begin_offset
        fp.seek(begin_offset, io.SEEK_SET)
        shifted_chunks = self._chunk_with_progress_emitted(fp, progress)

        # Start uploading
        return upload_service.upload_shifted_chunks(
            shifted_chunks, begin_offset, read_timeout=read_timeout
        )

    def _gen_session_key(self, fp: T.IO[bytes], progress: dict[str, T.Any]) -> str:
        if self.upload_options.noresume:
            # Generate a unique UUID for session_key when noresume is True
            # to prevent resuming from previous uploads
            session_key = f"{_prefixed_uuid4()}"
        else:
            fp.seek(0, io.SEEK_SET)
            session_key = utils.md5sum_fp(fp).hexdigest()

        filetype = progress.get("file_type")
        if filetype is not None:
            session_key = _suffix_session_key(session_key, types.FileType(filetype))

        return session_key


def _validate_metadatas(metadatas: T.Sequence[types.ImageMetadata]):
    for metadata in metadatas:
        validate_image_desc(DescriptionJSONSerializer.as_desc(metadata))
        if not metadata.filename.is_file():
            raise FileNotFoundError(f"No such file {metadata.filename}")


def _is_immediate_retriable_exception(ex: BaseException) -> bool:
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

    return False


def _is_retriable_exception(ex: BaseException) -> tuple[bool, int]:
    """
    Determine if an exception should be retried and how long to wait.

    Args:
        ex: Exception to check for retryability

    Returns:
        Tuple of (retriable, retry_after_sec) where:
        - retriable: True if the exception should be retried
        - retry_after_sec: Seconds to wait before retry (>= 0)

    Examples:
    >>> resp = requests.Response()
    >>> resp._content = b"foo"
    >>> resp.status_code = 400
    >>> ex = requests.HTTPError("error", response=resp)
    >>> _is_retriable_exception(ex)
    (False, 0)
    >>> resp._content = b'{"backoff": 13000, "debug_info": {"retriable": false, "type": "RequestRateLimitedError", "message": "Request rate limit has been exceeded"}}'
    >>> resp.status_code = 400
    >>> ex = requests.HTTPError("error", response=resp)
    >>> _is_retriable_exception(ex)
    (True, 13)
    >>> resp._content = b'{"backoff": "foo", "debug_info": {"retriable": false, "type": "RequestRateLimitedError", "message": "Request rate limit has been exceeded"}}'
    >>> resp.status_code = 400
    >>> ex = requests.HTTPError("error", response=resp)
    >>> _is_retriable_exception(ex)
    (True, 10)
    >>> resp._content = b'{"debug_info": {"retriable": false, "type": "RequestRateLimitedError", "message": "Request rate limit has been exceeded"}}'
    >>> resp.status_code = 400
    >>> ex = requests.HTTPError("error", response=resp)
    >>> _is_retriable_exception(ex)
    (True, 10)
    >>> resp._content = b"foo"
    >>> resp.status_code = 429
    >>> ex = requests.HTTPError("error", response=resp)
    >>> _is_retriable_exception(ex)
    (True, 10)
    >>> resp._content = b"foo"
    >>> resp.status_code = 429
    >>> ex = requests.HTTPError("error", response=resp)
    >>> _is_retriable_exception(ex)
    (True, 10)
    >>> resp._content = b'{"backoff": 12000, "debug_info": {"retriable": false, "type": "RequestRateLimitedError", "message": "Request rate limit has been exceeded"}}'
    >>> resp.status_code = 429
    >>> ex = requests.HTTPError("error", response=resp)
    >>> _is_retriable_exception(ex)
    (True, 12)
    >>> resp._content = b'{"backoff": 12000, "debug_info": {"retriable": false, "type": "RequestRateLimitedError", "message": "Request rate limit has been exceeded"}}'
    >>> resp.headers = {"Retry-After": "1"}
    >>> resp.status_code = 503
    >>> ex = requests.HTTPError("error", response=resp)
    >>> _is_retriable_exception(ex)
    (True, 1)
    """

    DEFAULT_RETRY_AFTER_RATE_LIMIT_SEC = 10

    if isinstance(ex, (requests.ConnectionError, requests.Timeout)):
        return True, 0

    if isinstance(ex, requests.HTTPError) and isinstance(
        ex.response, requests.Response
    ):
        status_code = ex.response.status_code

        # Always retry with some delay
        if status_code == 429:
            retry_after_sec = (
                _parse_retry_after_from_header(ex.response)
                or DEFAULT_RETRY_AFTER_RATE_LIMIT_SEC
            )

            try:
                data = ex.response.json()
            except requests.JSONDecodeError:
                return True, retry_after_sec

            backoff_ms = _parse_backoff(data.get("backoff"))
            if backoff_ms is None:
                return True, retry_after_sec
            else:
                return True, max(0, int(int(backoff_ms) / 1000))

        if 400 <= status_code < 500:
            try:
                data = ex.response.json()
            except requests.JSONDecodeError:
                return False, (_parse_retry_after_from_header(ex.response) or 0)

            debug_info = data.get("debug_info", {})

            if isinstance(debug_info, dict):
                error_type = debug_info.get("type")
            else:
                error_type = None

            # The server may respond 429 RequestRateLimitedError but with retryable=False
            # We should retry for this case regardless
            # e.g. HTTP 429 {"backoff": 10000, "debug_info": {"retriable": false, "type": "RequestRateLimitedError", "message": "Request rate limit has been exceeded"}}
            if error_type == "RequestRateLimitedError":
                backoff_ms = _parse_backoff(data.get("backoff"))
                if backoff_ms is None:
                    return True, (
                        _parse_retry_after_from_header(ex.response)
                        or DEFAULT_RETRY_AFTER_RATE_LIMIT_SEC
                    )
                else:
                    return True, max(0, int(int(backoff_ms) / 1000))

            return debug_info.get("retriable", False), 0

        if 500 <= status_code < 600:
            return True, (_parse_retry_after_from_header(ex.response) or 0)

    return False, 0


def _parse_backoff(backoff: T.Any) -> int | None:
    if backoff is not None:
        try:
            backoff_ms = int(backoff)
        except (ValueError, TypeError):
            backoff_ms = None
    else:
        backoff_ms = None
    return backoff_ms


def _parse_retry_after_from_header(resp: requests.Response) -> int | None:
    """
    Parse Retry-After header from HTTP response.
    See See https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Retry-After

    Args:
        resp: HTTP response object with headers

    Returns:
        Number of seconds to wait (>= 0) or None if header missing/invalid.

    Examples:
    >>> resp = requests.Response()
    >>> resp.headers = {"Retry-After": "1"}
    >>> _parse_retry_after_from_header(resp)
    1
    >>> resp.headers = {"Retry-After": "-1"}
    >>> _parse_retry_after_from_header(resp)
    0
    >>> resp.headers = {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
    >>> _parse_retry_after_from_header(resp)
    0
    >>> resp.headers = {"Retry-After": "Wed, 21 Oct 2315 07:28:00"}
    >>> _parse_retry_after_from_header(resp)
    """

    value = resp.headers.get("Retry-After")
    if value is None:
        return None

    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        pass

    # e.g. "Wed, 21 Oct 2015 07:28:00 GMT"
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (ValueError, TypeError):
        dt = None

    if dt is None:
        LOG.warning(f"Error parsing Retry-After: {value}")
        return None

    try:
        delta = dt - datetime.datetime.now(datetime.timezone.utc)
    except (TypeError, ValueError):
        # e.g. TypeError: can't subtract offset-naive and offset-aware datetimes
        return None

    return max(0, int(delta.total_seconds()))


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


def _suffix_session_key(
    key: str, filetype: api_v4.ClusterFileType | types.FileType
) -> str:
    is_uuid_before = _is_uuid(key)

    key = f"mly_tools_{key}{_SUFFIX_MAP[filetype]}"

    assert _is_uuid(key) is is_uuid_before

    return key


def _prefixed_uuid4():
    prefixed = f"uuid_{uuid.uuid4().hex}"
    assert _is_uuid(prefixed)
    return prefixed


def _is_uuid(key: str) -> bool:
    return key.startswith("uuid_") or key.startswith("mly_tools_uuid_")


def _build_upload_cache_path(upload_options: UploadOptions) -> Path:
    # Different python/CLI versions use different cache (dbm) formats.
    # Separate them to avoid conflicts
    py_version_parts = [str(part) for part in sys.version_info[:3]]
    version = f"py_{'_'.join(py_version_parts)}_{VERSION}"
    # File handles are not sharable between different users
    user_id = str(
        upload_options.user_items.get(
            "MAPSettingsUserKey", upload_options.user_items["user_upload_token"]
        )
    )
    # Use hash to avoid log sensitive data
    user_fingerprint = utils.md5sum_fp(
        io.BytesIO((api_v4.MAPILLARY_CLIENT_TOKEN + user_id).encode("utf-8")),
        md5=hashlib.sha256(),
    ).hexdigest()[:24]

    cache_path = (
        Path(constants.UPLOAD_CACHE_DIR)
        .joinpath(version)
        .joinpath(user_fingerprint)
        .joinpath("cached_file_handles")
    )

    return cache_path


def _maybe_create_persistent_cache_instance(
    upload_options: UploadOptions,
) -> history.PersistentCache | None:
    """Create a persistent cache instance if caching is enabled."""

    if upload_options.dry_run:
        LOG.debug("Dry-run mode enabled, skipping caching upload file handles")
        return None

    if upload_options.upload_cache_path is None:
        if not constants.UPLOAD_CACHE_DIR:
            LOG.debug(
                "Upload cache directory is set empty, skipping caching upload file handles"
            )
            return None

        cache_path = _build_upload_cache_path(upload_options)
    else:
        cache_path = upload_options.upload_cache_path

    LOG.debug(f"File handle cache path: {cache_path}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    return history.PersistentCache(str(cache_path.resolve()))
