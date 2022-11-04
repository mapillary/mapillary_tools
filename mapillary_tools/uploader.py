import io
import json
import logging
import os
import sys
import tempfile
import time
import typing as T
import uuid
import zipfile
from pathlib import Path

import jsonschema

import requests

if sys.version_info >= (3, 8):
    from typing import Literal  # pylint: disable=no-name-in-module
else:
    from typing_extensions import Literal

from . import constants, exif_write, types, upload_api_v4, utils


LOG = logging.getLogger(__name__)


def _group_sequences_by_uuid(
    descs: T.Sequence[types.ImageDescriptionFile],
) -> T.Dict[str, T.Dict[str, types.ImageDescriptionFile]]:
    sequences: T.Dict[str, T.Dict[str, types.ImageDescriptionFile]] = {}
    missing_sequence_uuid = str(uuid.uuid4())
    for desc in descs:
        sequence_uuid = desc.get("MAPSequenceUUID", missing_sequence_uuid)
        sequence = sequences.setdefault(sequence_uuid, {})
        sequence[desc["filename"]] = desc
    return sequences


class Progress(types.TypedDict, total=False):
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


EventName = Literal[
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
        self, zip_path: Path, event_payload: T.Optional[Progress] = None
    ) -> T.Optional[str]:
        if event_payload is None:
            event_payload = {}

        with zipfile.ZipFile(zip_path) as ziph:
            namelist = ziph.namelist()
            if not namelist:
                LOG.warning(f"Skipping empty zipfile: %s", zip_path)
                return None
            upload_md5sum = _hash_zipfile(ziph)

        final_event_payload: Progress = {
            **event_payload,  # type: ignore
            "sequence_image_count": len(namelist),
        }

        with zip_path.open("rb") as fp:
            try:
                return self._upload_fp(
                    fp,
                    upload_md5sum,
                    "zip",
                    event_payload=final_event_payload,
                )
            except UploadCancelled:
                return None

    def upload_blackvue_fp(
        self, fp: T.IO[bytes], event_payload: T.Optional[Progress] = None
    ) -> T.Optional[str]:
        if event_payload is None:
            event_payload = {}

        upload_md5sum = utils.md5sum_fp(fp)
        try:
            return self._upload_fp(
                fp,
                upload_md5sum,
                "mly_blackvue_video",
                event_payload=event_payload,
            )
        except UploadCancelled:
            return None

    def upload_camm_fp(
        self,
        fp: T.IO[bytes],
        event_payload: T.Optional[Progress] = None,
    ) -> T.Optional[str]:
        if event_payload is None:
            event_payload = {}

        upload_md5sum = utils.md5sum_fp(fp)
        try:
            return self._upload_fp(
                fp,
                upload_md5sum,
                "mly_camm_video",
                event_payload=event_payload,
            )
        except UploadCancelled:
            return None

    def upload_images(
        self,
        descs: T.Sequence[types.ImageDescriptionFile],
        event_payload: T.Optional[Progress] = None,
    ) -> T.Dict[str, str]:
        if event_payload is None:
            event_payload = {}

        _validate_descs(descs)
        sequences = _group_sequences_by_uuid(descs)
        ret: T.Dict[str, str] = {}
        for sequence_idx, (sequence_uuid, images) in enumerate(sequences.items()):
            final_event_payload: Progress = {
                **event_payload,  # type: ignore
                "sequence_idx": sequence_idx,
                "total_sequence_count": len(sequences),
                "sequence_image_count": len(images),
                "sequence_uuid": sequence_uuid,
            }
            with tempfile.NamedTemporaryFile() as fp:
                upload_md5sum = _zip_sequence_fp(images, fp)
                try:
                    cluster_id: T.Optional[str] = self._upload_fp(
                        fp,
                        upload_md5sum,
                        "zip",
                        final_event_payload,
                    )
                except UploadCancelled:
                    cluster_id = None
            if cluster_id is not None:
                ret[sequence_uuid] = cluster_id
        return ret

    def _upload_fp(
        self,
        fp: T.IO[bytes],
        upload_md5sum: str,
        file_type: upload_api_v4.FileType,
        event_payload: T.Optional[Progress] = None,
    ) -> str:
        if event_payload is None:
            event_payload = {}

        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        SUFFIX_MAP: T.Dict[upload_api_v4.FileType, str] = {
            "zip": ".zip",
            "mly_camm_video": ".mp4",
            "mly_blackvue_video": ".mp4",
        }
        session_key = f"mly_tools_{upload_md5sum}{SUFFIX_MAP[file_type]}"

        if self.dry_run:
            upload_service: upload_api_v4.UploadService = (
                upload_api_v4.FakeUploadService(
                    user_access_token=self.user_items["user_upload_token"],
                    session_key=session_key,
                    entity_size=entity_size,
                    organization_id=self.user_items.get("MAPOrganizationKey"),
                    file_type=file_type,
                    chunk_size=self.chunk_size,
                )
            )
        else:
            upload_service = upload_api_v4.UploadService(
                user_access_token=self.user_items["user_upload_token"],
                session_key=session_key,
                entity_size=entity_size,
                organization_id=self.user_items.get("MAPOrganizationKey"),
                file_type=file_type,
                chunk_size=self.chunk_size,
            )

        final_event_payload: Progress = {
            **event_payload,  # type: ignore
            "entity_size": entity_size,
            "md5sum": upload_md5sum,
        }

        return _upload_fp(
            upload_service,
            fp,
            event_payload=final_event_payload,
            emitter=self.emitter,
        )


def desc_file_to_exif(
    desc: types.ImageDescriptionFile,
) -> types.ImageDescriptionEXIF:
    not_needed = ["MAPPhotoUUID", "MAPSequenceUUID"]
    removed = {
        key: value
        for key, value in desc.items()
        if key.startswith("MAP") and key not in not_needed
    }
    return T.cast(types.ImageDescriptionEXIF, removed)


def _validate_descs(descs: T.Sequence[types.ImageDescriptionFile]):
    for desc in descs:
        types.validate_desc(desc)
        if not os.path.isfile(desc["filename"]):
            raise RuntimeError(f"Image not found: {desc['filename']}")


def zip_images(
    descs: T.List[types.ImageDescriptionFile],
    zip_dir: Path,
):
    _validate_descs(descs)
    sequences = _group_sequences_by_uuid(descs)
    os.makedirs(zip_dir, exist_ok=True)
    for sequence_uuid, sequence in sequences.items():
        zip_filename_wip = zip_dir.joinpath(
            f"mly_tools_{sequence_uuid}.{os.getpid()}.wip"
        )
        with zip_filename_wip.open("wb") as fp:
            upload_md5sum = _zip_sequence_fp(sequence, fp)
        zip_filename = zip_dir.joinpath(f"mly_tools_{upload_md5sum}.zip")
        os.rename(zip_filename_wip, zip_filename)


# Instead of hashing the zip file content, we hash the filename list,
# because the zip content could be changed due to EXIF change
# (e.g. changes in MAPMetaTag in image description)
def _hash_zipfile(ziph: zipfile.ZipFile) -> str:
    # namelist is List[str]
    namelist = ziph.namelist()
    concat = "".join(os.path.splitext(os.path.basename(name))[0] for name in namelist)
    return utils.md5sum_bytes(concat.encode("utf-8"))


def _zip_sequence_fp(
    sequence: T.Dict[str, types.ImageDescriptionFile],
    fp: T.IO[bytes],
) -> str:
    descs = list(sequence.values())
    descs.sort(
        key=lambda desc: (
            types.map_capture_time_to_datetime(desc["MAPCaptureTime"]),
            desc["filename"],
        )
    )
    with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as ziph:
        for desc in descs:
            edit = exif_write.ExifEdit(desc["filename"])
            with open(desc["filename"], "rb") as fp:
                md5sum = utils.md5sum_fp(fp)
            # The cast is to fix the type checker error
            exif_desc = T.cast(T.Dict, desc_file_to_exif(desc))
            edit.add_image_description(exif_desc)
            image_bytes = edit.dump_image_bytes()
            # To make sure the zip file deterministic, i.e. zip same files result in same content (same hashes),
            # we use md5 as the name, and an constant as the modification time
            _, ext = os.path.splitext(desc["filename"])
            arcname = f"{md5sum}{ext.lower()}"
            zipinfo = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            ziph.writestr(zipinfo, image_bytes)

        return _hash_zipfile(ziph)


def is_immediate_retry(ex: Exception):
    if isinstance(ex, requests.HTTPError) and ex.response.status_code == 412:
        try:
            resp = ex.response.json()
        except json.JSONDecodeError:
            return False
        # resp: {"debug_info":{"retriable":true,"type":"OffsetInvalidError","message":"Request starting offset is invalid"}}
        return resp.get("debug_info", {}).get("retriable", False)


def is_retriable_exception(ex: Exception):
    if isinstance(ex, (requests.ConnectionError, requests.Timeout)):
        return True

    if isinstance(ex, requests.HTTPError):
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


def _upload_fp(
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
            if retries < constants.MAX_UPLOAD_RETRIES and is_retriable_exception(ex):
                if emitter:
                    emitter.emit("upload_interrupted", mutable_payload)
                LOG.warning(
                    # use %s instead of %d because offset could be None
                    f"Error uploading chunk_size %d at begin_offset %s: %s: %s",
                    upload_service.chunk_size,
                    begin_offset,
                    ex.__class__.__name__,
                    str(ex),
                )
                retries += 1
                if is_immediate_retry(ex):
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
