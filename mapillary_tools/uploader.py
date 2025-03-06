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

from . import constants, exif_write, types, upload_api_v4, utils


LOG = logging.getLogger(__name__)


class Progress(T.TypedDict, total=False):
    # The size of the chunk, in bytes, that has been uploaded in the last request
    chunk_size: int

    # File type
    file_type: str

    # How many bytes has been uploaded so far since "upload_start"
    offset: int

    # Size in bytes of the zipfile/BlackVue/CAMM
    entity_size: int

    # How many sequences in total. It's always 1 when uploading Zipfile/BlackVue/CAMM
    total_sequence_count: int

    # 0-based nth sequence. It is always 0 when uploading Zipfile/BlackVue/CAMM
    sequence_idx: int

    # How many images in the sequence. It's available only when uploading directories/Zipfiles
    sequence_image_count: int

    # MAPSequenceUUID. It is only available for directory uploading
    sequence_uuid: str

    # An "upload_interrupted" will increase it. Reset to 0 if the chunk is uploaded
    retries: int

    # md5sum of the zipfile/BlackVue/CAMM in uploading
    md5sum: str

    # Path to the Zipfile/BlackVue/CAMM
    import_path: str

    # Cluster ID after finishing the upload
    cluster_id: str


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
    events: T.Dict[EventName, T.List]

    def __init__(self):
        self.events = {}

    def on(self, event: EventName):
        def _wrap(callback):
            self.events.setdefault(event, []).append(callback)

        return _wrap

    def emit(self, event: EventName, *args, **kwargs):
        for callback in self.events.get(event, []):
            callback(*args, **kwargs)


class Uploader:
    def __init__(
        self,
        user_items: types.UserItem,
        emitter: T.Optional[EventEmitter] = None,
        chunk_size: int = upload_api_v4.DEFAULT_CHUNK_SIZE,
        dry_run=False,
    ):
        jsonschema.validate(instance=user_items, schema=types.UserItemSchema)
        self.user_items = user_items
        self.emitter = emitter
        self.chunk_size = chunk_size
        self.dry_run = dry_run

    def upload_zipfile(
        self,
        zip_path: Path,
        event_payload: T.Optional[Progress] = None,
    ) -> T.Optional[str]:
        if event_payload is None:
            event_payload = {}

        with zipfile.ZipFile(zip_path) as ziph:
            namelist = ziph.namelist()
            if not namelist:
                LOG.warning("Skipping empty zipfile: %s", zip_path)
                return None

        final_event_payload: Progress = {
            **event_payload,  # type: ignore
            "sequence_image_count": len(namelist),
        }

        with zip_path.open("rb") as fp:
            upload_md5sum = _extract_upload_md5sum(fp)

        if upload_md5sum is None:
            with zip_path.open("rb") as fp:
                upload_md5sum = utils.md5sum_fp(fp).hexdigest()

        with zip_path.open("rb") as fp:
            return self.upload_stream(
                fp,
                upload_api_v4.ClusterFileType.ZIP,
                upload_md5sum,
                event_payload=final_event_payload,
            )

    def upload_images(
        self,
        image_metadatas: T.Sequence[types.ImageMetadata],
        event_payload: T.Optional[Progress] = None,
    ) -> T.Dict[str, str]:
        if event_payload is None:
            event_payload = {}

        _validate_metadatas(image_metadatas)
        sequences = types.group_and_sort_images(image_metadatas)
        ret: T.Dict[str, str] = {}
        for sequence_idx, (sequence_uuid, sequence) in enumerate(sequences.items()):
            final_event_payload: Progress = {
                **event_payload,  # type: ignore
                "sequence_idx": sequence_idx,
                "total_sequence_count": len(sequences),
                "sequence_image_count": len(sequence),
                "sequence_uuid": sequence_uuid,
            }
            for metadata in sequence:
                metadata.update_md5sum()
            upload_md5sum = types.sequence_md5sum(sequence)
            with tempfile.NamedTemporaryFile() as fp:
                _zip_sequence_fp(sequence, fp, upload_md5sum)
                cluster_id = self.upload_stream(
                    fp,
                    upload_api_v4.ClusterFileType.ZIP,
                    upload_md5sum,
                    final_event_payload,
                )
            if cluster_id is not None:
                ret[sequence_uuid] = cluster_id
        return ret

    def upload_stream(
        self,
        fp: T.IO[bytes],
        cluster_filetype: upload_api_v4.ClusterFileType,
        upload_md5sum: str,
        event_payload: T.Optional[Progress] = None,
    ) -> T.Optional[str]:
        if event_payload is None:
            event_payload = {}

        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        SUFFIX_MAP: T.Dict[upload_api_v4.ClusterFileType, str] = {
            upload_api_v4.ClusterFileType.ZIP: ".zip",
            upload_api_v4.ClusterFileType.CAMM: ".mp4",
            upload_api_v4.ClusterFileType.BLACKVUE: ".mp4",
        }
        session_key = f"mly_tools_{upload_md5sum}{SUFFIX_MAP[cluster_filetype]}"

        if self.dry_run:
            upload_service: upload_api_v4.UploadService = (
                upload_api_v4.FakeUploadService(
                    user_access_token=self.user_items["user_upload_token"],
                    session_key=session_key,
                    organization_id=self.user_items.get("MAPOrganizationKey"),
                    cluster_filetype=cluster_filetype,
                    chunk_size=self.chunk_size,
                )
            )
        else:
            upload_service = upload_api_v4.UploadService(
                user_access_token=self.user_items["user_upload_token"],
                session_key=session_key,
                organization_id=self.user_items.get("MAPOrganizationKey"),
                cluster_filetype=cluster_filetype,
                chunk_size=self.chunk_size,
            )

        final_event_payload: Progress = {
            **event_payload,  # type: ignore
            "entity_size": entity_size,
            "md5sum": upload_md5sum,
        }

        try:
            return _upload_stream(
                upload_service,
                fp,
                event_payload=final_event_payload,
                emitter=self.emitter,
            )
        except UploadCancelled:
            return None


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


def zip_images(
    metadatas: T.List[types.ImageMetadata],
    zip_dir: Path,
) -> None:
    _validate_metadatas(metadatas)
    sequences = types.group_and_sort_images(metadatas)
    os.makedirs(zip_dir, exist_ok=True)
    for sequence_uuid, sequence in sequences.items():
        for metadata in sequence:
            metadata.update_md5sum()
        upload_md5sum = types.sequence_md5sum(sequence)
        timestamp = int(time.time())
        wip_zip_filename = zip_dir.joinpath(
            f".mly_zip_{uuid.uuid4()}_{sequence_uuid}_{os.getpid()}_{timestamp}"
        )
        zip_filename = zip_dir.joinpath(f"mly_tools_{upload_md5sum}.zip")
        with wip_file_context(wip_zip_filename, zip_filename) as wip_dir:
            with wip_dir.open("wb") as fp:
                _zip_sequence_fp(sequence, fp, upload_md5sum)


def _zip_sequence_fp(
    sequence: T.Sequence[types.ImageMetadata],
    fp: T.IO[bytes],
    upload_md5sum: str,
) -> None:
    arcname_idx = 0
    arcnames = set()
    with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as ziph:
        for metadata in sequence:
            edit = exif_write.ExifEdit(metadata.filename)
            # The cast is to fix the type checker error
            edit.add_image_description(
                T.cast(T.Dict, types.desc_file_to_exif(types.as_desc(metadata)))
            )
            image_bytes = edit.dump_image_bytes()
            arcname: str = metadata.filename.name
            # make sure the arcname is unique, otherwise zipfile.extractAll will eliminate duplicated ones
            while arcname in arcnames:
                arcname_idx += 1
                arcname = (
                    f"{metadata.filename.stem}_{arcname_idx}{metadata.filename.suffix}"
                )
            arcnames.add(arcname)
            zipinfo = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            ziph.writestr(zipinfo, image_bytes)
            ziph.comment = json.dumps({"upload_md5sum": upload_md5sum}).encode("utf-8")
        assert len(sequence) == len(set(ziph.namelist()))


def _extract_upload_md5sum(fp: T.IO[bytes]) -> T.Optional[str]:
    with zipfile.ZipFile(fp, "r", zipfile.ZIP_DEFLATED) as ziph:
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


def _setup_callback(emitter: EventEmitter, mutable_payload: Progress):
    def _callback(chunk: bytes, _):
        assert isinstance(emitter, EventEmitter)
        mutable_payload["offset"] += len(chunk)
        mutable_payload["chunk_size"] = len(chunk)
        emitter.emit("upload_progress", mutable_payload)

    return _callback


def _upload_stream(
    upload_service: upload_api_v4.UploadService,
    fp: T.IO[bytes],
    event_payload: T.Optional[Progress] = None,
    emitter: T.Optional[EventEmitter] = None,
) -> str:
    retries = 0

    if event_payload is None:
        event_payload = {}

    mutable_payload = T.cast(Progress, {**event_payload})

    # when it progresses, we reset retries
    def _reset_retries(_, __):
        nonlocal retries
        retries = 0

    if emitter:
        emitter.emit("upload_start", mutable_payload)

    while True:
        fp.seek(0, io.SEEK_SET)
        begin_offset: T.Optional[int] = None
        try:
            begin_offset = upload_service.fetch_offset()
            upload_service.callbacks = [_reset_retries]
            if emitter:
                mutable_payload["offset"] = begin_offset
                mutable_payload["retries"] = retries
                emitter.emit("upload_fetch_offset", mutable_payload)
                upload_service.callbacks.append(
                    _setup_callback(emitter, mutable_payload)
                )
            file_handle = upload_service.upload(fp, offset=begin_offset)
        except Exception as ex:
            if retries < constants.MAX_UPLOAD_RETRIES and _is_retriable_exception(ex):
                if emitter:
                    emitter.emit("upload_interrupted", mutable_payload)
                LOG.warning(
                    # use %s instead of %d because offset could be None
                    "Error uploading chunk_size %d at begin_offset %s: %s: %s",
                    upload_service.chunk_size,
                    begin_offset,
                    ex.__class__.__name__,
                    str(ex),
                )
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
        else:
            break

    if emitter:
        emitter.emit("upload_end", mutable_payload)

    # TODO: retry here
    cluster_id = upload_service.finish(file_handle)

    if emitter:
        mutable_payload["cluster_id"] = cluster_id
        emitter.emit("upload_finished", mutable_payload)

    return cluster_id
