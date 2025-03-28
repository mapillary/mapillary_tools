from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import time
import typing as T
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

import jsonschema
import requests

from . import api_v4, constants, exif_write, types, upload_api_v4, utils


LOG = logging.getLogger(__name__)


class UploaderProgress(T.TypedDict, total=True):
    """
    Progress data that Uploader cares about.
    """

    # The size of the chunk, in bytes, that has been read and upload
    chunk_size: int

    begin_offset: int | None

    # How many bytes has been uploaded so far since "upload_start"
    offset: int

    # Size in bytes of the zipfile/BlackVue/CAMM
    entity_size: int

    # An "upload_interrupted" will increase it. Reset to 0 if the chunk is uploaded
    retries: int

    # Cluster ID after finishing the upload
    cluster_id: str


class SequenceProgress(T.TypedDict, total=False):
    """Progress data at sequence level"""

    # md5sum of the zipfile/BlackVue/CAMM in uploading
    md5sum: str

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


class UploadCancelled(Exception):
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

        return _wrap

    def emit(self, event: EventName, *args, **kwargs):
        for callback in self.events.get(event, []):
            callback(*args, **kwargs)


class ZipImageSequence:
    @classmethod
    def zip_images(
        cls, metadatas: T.Sequence[types.ImageMetadata], zip_dir: Path
    ) -> None:
        """
        Group images into sequences and zip each sequence into a zipfile.
        """
        _validate_metadatas(metadatas)
        sequences = types.group_and_sort_images(metadatas)
        os.makedirs(zip_dir, exist_ok=True)

        for sequence_uuid, sequence in sequences.items():
            # For atomicity we write into a WIP file and then rename to the final file
            wip_zip_filename = zip_dir.joinpath(
                f".mly_zip_{uuid.uuid4()}_{sequence_uuid}_{os.getpid()}_{int(time.time())}"
            )
            upload_md5sum = types.update_sequence_md5sum(sequence)
            filename = _session_key(upload_md5sum, upload_api_v4.ClusterFileType.ZIP)
            zip_filename = zip_dir.joinpath(filename)
            with wip_file_context(wip_zip_filename, zip_filename) as wip_path:
                with wip_path.open("wb") as wip_fp:
                    actual_md5sum = cls.zip_sequence_fp(sequence, wip_fp)
                    assert actual_md5sum == upload_md5sum, "md5sum mismatch"

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

        upload_md5sum = types.update_sequence_md5sum(sequence)

        with zipfile.ZipFile(zip_fp, "w", zipfile.ZIP_DEFLATED) as zipf:
            arcnames: set[str] = set()
            for metadata in sequence:
                cls._write_imagebytes_in_zip(zipf, metadata, arcnames=arcnames)
            assert len(sequence) == len(set(zipf.namelist()))
            zipf.comment = json.dumps({"upload_md5sum": upload_md5sum}).encode("utf-8")

        return upload_md5sum

    @classmethod
    def extract_upload_md5sum(cls, zip_fp: T.IO[bytes]) -> str | None:
        with zipfile.ZipFile(zip_fp, "r", zipfile.ZIP_DEFLATED) as ziph:
            comment = ziph.comment
        if not comment:
            return None
        try:
            upload_md5sum = json.loads(comment.decode("utf-8")).get("upload_md5sum")
        except Exception:
            return None
        if not upload_md5sum:
            return None
        return str(upload_md5sum)

    @classmethod
    def _uniq_arcname(cls, filename: Path, arcnames: set[str]):
        arcname: str = filename.name

        # make sure the arcname is unique, otherwise zipfile.extractAll will eliminate duplicated ones
        arcname_idx = 0
        while arcname in arcnames:
            arcname_idx += 1
            arcname = f"{filename.stem}_{arcname_idx}{filename.suffix}"

        return arcname

    @classmethod
    def _write_imagebytes_in_zip(
        cls,
        zipf: zipfile.ZipFile,
        metadata: types.ImageMetadata,
        arcnames: set[str] | None = None,
    ):
        if arcnames is None:
            arcnames = set()

        edit = exif_write.ExifEdit(metadata.filename)
        # The cast is to fix the type checker error
        edit.add_image_description(
            T.cast(T.Dict, types.desc_file_to_exif(types.as_desc(metadata)))
        )
        image_bytes = edit.dump_image_bytes()

        arcname = cls._uniq_arcname(metadata.filename, arcnames)
        arcnames.add(arcname)

        zipinfo = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
        zipf.writestr(zipinfo, image_bytes)

    @classmethod
    def prepare_zipfile_and_upload(
        cls,
        zip_path: Path,
        uploader: Uploader,
        progress: dict[str, T.Any] | None = None,
    ) -> str | None:
        if progress is None:
            progress = {}

        with zipfile.ZipFile(zip_path) as ziph:
            namelist = ziph.namelist()
            if not namelist:
                LOG.warning("Skipping empty zipfile: %s", zip_path)
                return None

        with zip_path.open("rb") as zip_fp:
            upload_md5sum = cls.extract_upload_md5sum(zip_fp)

        if upload_md5sum is None:
            with zip_path.open("rb") as zip_fp:
                upload_md5sum = utils.md5sum_fp(zip_fp).hexdigest()

        sequence_progress: SequenceProgress = {
            "sequence_image_count": len(namelist),
            "file_type": types.FileType.ZIP.value,
            "md5sum": upload_md5sum,
        }

        session_key = _session_key(upload_md5sum, upload_api_v4.ClusterFileType.ZIP)

        with zip_path.open("rb") as zip_fp:
            return uploader.upload_stream(
                zip_fp,
                upload_api_v4.ClusterFileType.ZIP,
                session_key,
                # Send the copy of the input progress to each upload session, to avoid modifying the original one
                progress=T.cast(T.Dict[str, T.Any], {**progress, **sequence_progress}),
            )

    @classmethod
    def prepare_images_and_upload(
        cls,
        image_metadatas: T.Sequence[types.ImageMetadata],
        uploader: Uploader,
        progress: dict[str, T.Any] | None = None,
    ) -> dict[str, str]:
        if progress is None:
            progress = {}

        _validate_metadatas(image_metadatas)
        sequences = types.group_and_sort_images(image_metadatas)
        ret: dict[str, str] = {}
        for sequence_idx, (sequence_uuid, sequence) in enumerate(sequences.items()):
            sequence_progress: SequenceProgress = {
                "sequence_idx": sequence_idx,
                "total_sequence_count": len(sequences),
                "sequence_image_count": len(sequence),
                "sequence_uuid": sequence_uuid,
                "file_type": types.FileType.IMAGE.value,
            }

            with tempfile.NamedTemporaryFile() as fp:
                upload_md5sum = cls.zip_sequence_fp(sequence, fp)

                sequence_progress["md5sum"] = upload_md5sum

                session_key = _session_key(
                    upload_md5sum, upload_api_v4.ClusterFileType.ZIP
                )

                cluster_id = uploader.upload_stream(
                    fp,
                    upload_api_v4.ClusterFileType.ZIP,
                    session_key,
                    # Send the copy of the input progress to each upload session, to avoid modifying the original one
                    progress=T.cast(
                        T.Dict[str, T.Any], {**progress, **sequence_progress}
                    ),
                )

            if cluster_id is not None:
                ret[sequence_uuid] = cluster_id
        return ret


class Uploader:
    def __init__(
        self,
        user_items: types.UserItem,
        emitter: EventEmitter | None = None,
        chunk_size: int = int(constants.UPLOAD_CHUNK_SIZE_MB * 1024 * 1024),
        dry_run=False,
    ):
        jsonschema.validate(instance=user_items, schema=types.UserItemSchema)
        self.user_items = user_items
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
        cluster_filetype: upload_api_v4.ClusterFileType,
        session_key: str,
        progress: dict[str, T.Any] | None = None,
    ) -> str | None:
        if progress is None:
            progress = {}

        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        upload_service = self._create_upload_service(session_key, cluster_filetype)

        progress["entity_size"] = entity_size
        progress["chunk_size"] = self.chunk_size
        progress["retries"] = 0
        progress["begin_offset"] = None

        try:
            self.emitter.emit("upload_start", progress)
        except UploadCancelled:
            # TODO: Right now it is thrown in upload_start only
            return None

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

        # TODO: retry here
        cluster_id = self._finish_upload_retryable(upload_service, file_handle)
        progress["cluster_id"] = cluster_id

        self.emitter.emit("upload_finished", progress)

        return cluster_id

    def _create_upload_service(
        self, session_key: str, cluster_filetype: upload_api_v4.ClusterFileType
    ) -> upload_api_v4.UploadService:
        upload_service: upload_api_v4.UploadService

        if self.dry_run:
            upload_service = upload_api_v4.FakeUploadService(
                user_access_token=self.user_items["user_upload_token"],
                session_key=session_key,
                cluster_filetype=cluster_filetype,
            )
        else:
            upload_service = upload_api_v4.UploadService(
                user_access_token=self.user_items["user_upload_token"],
                session_key=session_key,
                cluster_filetype=cluster_filetype,
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

    def _finish_upload_retryable(
        self, upload_service: upload_api_v4.UploadService, file_handle: str
    ) -> str:
        """Finish upload with safe retries guraranteed"""

        if self.dry_run:
            cluster_id = "0"
        else:
            resp = api_v4.finish_upload(
                self.user_items["user_upload_token"],
                file_handle,
                upload_service.cluster_filetype,
                organization_id=self.user_items.get("MAPOrganizationKey"),
            )

            data = resp.json()
            cluster_id = data.get("cluster_id")

            # TODO: validate cluster_id

        return cluster_id


def _validate_metadatas(metadatas: T.Sequence[types.ImageMetadata]):
    for metadata in metadatas:
        types.validate_image_desc(types.as_desc(metadata))
        if not metadata.filename.is_file():
            raise FileNotFoundError(f"No such file {metadata.filename}")


@contextmanager
def wip_file_context(wip_path: Path, done_path: Path):
    assert wip_path != done_path, "should not be the same file"
    try:
        os.remove(wip_path)
    except FileNotFoundError:
        pass
    try:
        yield wip_path
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
    upload_md5sum: str, cluster_filetype: upload_api_v4.ClusterFileType
) -> str:
    SUFFIX_MAP: dict[upload_api_v4.ClusterFileType, str] = {
        upload_api_v4.ClusterFileType.ZIP: ".zip",
        upload_api_v4.ClusterFileType.CAMM: ".mp4",
        upload_api_v4.ClusterFileType.BLACKVUE: ".mp4",
    }

    return f"mly_tools_{upload_md5sum}{SUFFIX_MAP[cluster_filetype]}"
