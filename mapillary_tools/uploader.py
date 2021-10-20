import io
import json
import uuid
from typing import Optional, Iterable
import typing as T
import os
import tempfile
import logging

import time
import zipfile

import requests
import jsonschema

from . import upload_api_v4, types, exif_write


MIN_CHUNK_SIZE = 1024 * 1024  # 1MB
MAX_CHUNK_SIZE = 1024 * 1024 * 16  # 32MB
LOG = logging.getLogger(__name__)


def _find_root_dir(file_list: Iterable[str]) -> Optional[str]:
    """
    find the common root path
    """
    dirs = set()
    for path in file_list:
        dirs.add(os.path.dirname(path))
    if len(dirs) == 0:
        return None
    elif len(dirs) == 1:
        return list(dirs)[0]
    else:
        return _find_root_dir(dirs)


def _group_sequences_by_uuid(
    image_descs: T.List[types.ImageDescriptionFile],
) -> T.Dict[str, T.Dict[str, types.ImageDescriptionFile]]:
    sequences: T.Dict[str, T.Dict[str, types.ImageDescriptionFile]] = {}
    missing_sequence_uuid = str(uuid.uuid4())
    for desc in image_descs:
        sequence_uuid = desc.get("MAPSequenceUUID", missing_sequence_uuid)
        sequence = sequences.setdefault(sequence_uuid, {})
        sequence[desc["filename"]] = desc
    return sequences


class Progress(types.TypedDict, total=False):
    chunk_size: int
    # how many bytes has been uploaded
    offset: int
    # size of the zip
    entity_size: int
    # how many images in total
    total_image_count: int
    # how many sequences in total
    total_sequence_count: int
    sequence_idx: int
    # how many images in the sequence
    sequence_image_count: int
    sequence_uuid: str
    retries: int


class EventEmitter:
    events: T.Dict[str, T.List]

    def __init__(self):
        self.events = {}

    def on(self, event: str):
        def _wrap(callback):
            self.events.setdefault(event, []).append(callback)

        return _wrap

    def emit(self, event: str, *args, **kwargs):
        for callback in self.events.get(event, []):
            callback(*args, **kwargs)


class Uploader:
    def __init__(
        self, user_items: types.UserItem, emitter: EventEmitter = None, dry_run=False
    ):
        self.user_items = user_items
        self.dry_run = dry_run
        self.emitter = emitter

    def upload_zipfile(self, zip_path: str) -> int:
        return upload_zipfile(
            zip_path,
            self.user_items,
            emitter=self.emitter,
            dry_run=self.dry_run,
        )

    def upload_blackvue(self, blackvue_path: str) -> int:
        return upload_blackvue(
            blackvue_path,
            self.user_items,
            emitter=self.emitter,
            dry_run=self.dry_run,
        )

    def upload_image_dir(
        self, image_dir: str, descs: T.List[types.ImageDescriptionFile]
    ):
        return upload_image_dir(
            image_dir,
            descs,
            self.user_items,
            emitter=self.emitter,
            dry_run=self.dry_run,
        )


def _remove_non_exif_desc(
    desc: types.ImageDescriptionFile,
) -> types.ImageDescriptionEXIF:
    removed = {key: value for key, value in desc.items() if key.startswith("MAP")}
    return T.cast(types.ImageDescriptionEXIF, removed)


def upload_image_dir(
    image_dir: str,
    image_descs: T.List[types.ImageDescriptionFile],
    user_items: types.UserItem,
    emitter: EventEmitter = None,
    dry_run=False,
):
    jsonschema.validate(instance=user_items, schema=types.UserItemSchema)
    types.validate_descs(image_dir, image_descs)
    sequences = _group_sequences_by_uuid(image_descs)
    for sequence_idx, images in enumerate(sequences.values()):
        event_payload: Progress = {
            "sequence_idx": sequence_idx,
            "total_sequence_count": len(sequences),
            "sequence_image_count": len(images),
        }
        cluster_id = _zip_and_upload_single_sequence(
            image_dir,
            images,
            user_items,
            event_payload=event_payload,
            emitter=emitter,
            dry_run=dry_run,
        )


def zip_image_dir(
    image_dir: str,
    image_descs: T.List[types.ImageDescriptionFile],
    zip_dir: str,
):
    types.validate_descs(image_dir, image_descs)
    sequences = _group_sequences_by_uuid(image_descs)
    os.makedirs(zip_dir, exist_ok=True)
    for sequence_uuid, sequence in sequences.items():
        # FIXME: do not use UUID as filename
        zip_filename_wip = os.path.join(
            zip_dir, f"mly_tools_{sequence_uuid}.{os.getpid()}.wip"
        )
        with open(zip_filename_wip, "wb") as fp:
            _zip_sequence(image_dir, sequence, fp)
        zip_filename = os.path.join(zip_dir, f"mly_tools_{sequence_uuid}.zip")
        os.rename(zip_filename_wip, zip_filename)


def _zip_sequence(
    image_dir: str,
    sequences: T.Dict[str, types.ImageDescriptionFile],
    fp: T.IO[bytes],
) -> None:
    file_list = list(sequences.keys())
    first_image = list(sequences.values())[0]

    root_dir = _find_root_dir(file_list)
    if root_dir is None:
        sequence_uuid = first_image.get("MAPSequenceUUID")
        raise RuntimeError(f"Unable to find the root dir of sequence {sequence_uuid}")

    file_list.sort(key=lambda path: sequences[path]["MAPCaptureTime"])

    with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as ziph:
        for file in file_list:
            abspath = os.path.join(image_dir, file)
            edit = exif_write.ExifEdit(abspath)
            exif_desc = _remove_non_exif_desc(sequences[file])
            edit.add_image_description(exif_desc)
            image_bytes = edit.dump_image_bytes()
            relpath = os.path.relpath(file, root_dir)
            ziph.writestr(relpath, image_bytes)


def upload_zipfile(
    zip_path: str,
    user_items: types.UserItem,
    emitter: EventEmitter = None,
    dry_run=False,
) -> int:
    with zipfile.ZipFile(zip_path) as ziph:
        namelist = ziph.namelist()

    if not namelist:
        raise RuntimeError(f"The zip file {zip_path} is empty")

    with open(zip_path, "rb") as fp:
        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        # chunk size
        avg_image_size = int(entity_size / len(namelist))
        chunk_size = min(max(avg_image_size, MIN_CHUNK_SIZE), MAX_CHUNK_SIZE)

        session_key = os.path.basename(zip_path)
        if dry_run:
            upload_service: upload_api_v4.UploadService = (
                upload_api_v4.FakeUploadService(
                    user_access_token=user_items["user_upload_token"],
                    session_key=session_key,
                    entity_size=entity_size,
                    organization_id=user_items.get("MAPOrganizationKey"),
                )
            )
        else:
            upload_service = upload_api_v4.UploadService(
                user_access_token=user_items["user_upload_token"],
                session_key=session_key,
                entity_size=entity_size,
                organization_id=user_items.get("MAPOrganizationKey"),
            )

        return _upload_fp(
            upload_service,
            fp,
            chunk_size,
            event_payload=T.cast(
                Progress,
                {
                    "sequence_idx": 0,
                    "total_sequence_count": 1,
                    "image_count": len(namelist),
                    "entity_size": entity_size,
                    # FIXME: use uuid
                    "sequence_uuid": session_key,
                },
            ),
            emitter=emitter,
        )


def upload_blackvue(
    blackvue_path: str,
    user_items: types.UserItem,
    emitter: EventEmitter = None,
    dry_run=False,
) -> int:
    with open(blackvue_path, "rb") as fp:
        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        # chunk size
        avg_image_size = entity_size
        chunk_size = min(max(avg_image_size, MIN_CHUNK_SIZE), MAX_CHUNK_SIZE)

        session_key = os.path.basename(blackvue_path)
        if dry_run:
            upload_service: upload_api_v4.UploadService = (
                upload_api_v4.FakeUploadService(
                    user_access_token=user_items["user_upload_token"],
                    session_key=session_key,
                    entity_size=entity_size,
                    organization_id=user_items.get("MAPOrganizationKey"),
                    file_type="mly_blackvue_video",
                )
            )
        else:
            upload_service = upload_api_v4.UploadService(
                user_access_token=user_items["user_upload_token"],
                session_key=session_key,
                entity_size=entity_size,
                organization_id=user_items.get("MAPOrganizationKey"),
                file_type="mly_blackvue_video",
            )

        return _upload_fp(
            upload_service,
            fp,
            chunk_size,
            event_payload=T.cast(
                Progress,
                {
                    "sequence_idx": 0,
                    "total_sequence_count": 1,
                    "entity_size": entity_size,
                    # FIXME: use uuid
                    "sequence_uuid": session_key,
                },
            ),
            emitter=emitter,
        )


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
    chunk_size: int,
    event_payload: Progress = None,
    emitter: EventEmitter = None,
) -> int:
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
        try:
            offset = upload_service.fetch_offset()
            upload_service.callbacks = [_reset_retries]
            if emitter:
                mutable_payload["offset"] = offset
                mutable_payload["retries"] = retries
                emitter.emit("upload_fetch_offset", mutable_payload)
                upload_service.callbacks.append(
                    _setup_callback(emitter, mutable_payload)
                )
            file_handle = upload_service.upload(
                fp, chunk_size=chunk_size, offset=offset
            )
        except Exception as ex:
            if retries < 200 and is_retriable_exception(ex):
                if emitter:
                    emitter.emit("upload_interrupted", mutable_payload)
                retries += 1
                sleep_for = min(2 ** retries, 16)
                LOG.warning(
                    f"Error uploading, resuming in {sleep_for} seconds",
                    exc_info=True,
                )
                time.sleep(sleep_for)
            else:
                if isinstance(ex, requests.HTTPError):
                    raise upload_api_v4.wrap_http_exception(ex) from ex
                else:
                    raise ex
        else:
            break

    if emitter:
        emitter.emit("upload_end", mutable_payload)

    # TODO: retry here
    try:
        cluster_id = upload_service.finish(file_handle)
    except requests.HTTPError as ex:
        raise upload_api_v4.wrap_http_exception(ex) from ex

    return cluster_id


def _zip_and_upload_single_sequence(
    image_dir: str,
    sequences: T.Dict[str, types.ImageDescriptionFile],
    user_items: types.UserItem,
    event_payload: Progress,
    emitter: EventEmitter = None,
    dry_run=False,
) -> int:
    file_list = list(sequences.keys())
    first_image = list(sequences.values())[0]
    sequence_uuid = first_image.get("MAPSequenceUUID")

    root_dir = _find_root_dir(file_list)
    if root_dir is None:
        raise RuntimeError(f"Unable to find the root dir of sequence {sequence_uuid}")

    with tempfile.NamedTemporaryFile() as fp:
        _zip_sequence(image_dir, sequences, fp)

        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        # chunk size
        avg_image_size = int(entity_size / len(sequences))
        chunk_size = min(max(avg_image_size, MIN_CHUNK_SIZE), MAX_CHUNK_SIZE)

        if dry_run:
            upload_service: upload_api_v4.UploadService = (
                upload_api_v4.FakeUploadService(
                    user_items["user_upload_token"],
                    session_key=f"mly_tools_{sequence_uuid}.zip",
                    entity_size=entity_size,
                    organization_id=user_items.get("MAPOrganizationKey"),
                )
            )
        else:
            upload_service = upload_api_v4.UploadService(
                user_items["user_upload_token"],
                session_key=f"mly_tools_{sequence_uuid}.zip",
                entity_size=entity_size,
                organization_id=user_items.get("MAPOrganizationKey"),
            )

        cluster_id = _upload_fp(
            upload_service,
            fp,
            chunk_size,
            event_payload=T.cast(
                Progress,
                {
                    **event_payload,
                    "entity_size": entity_size,
                    "sequence_uuid": sequence_uuid,
                },
            ),
            emitter=emitter,
        )

        return cluster_id
