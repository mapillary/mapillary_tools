import io
import uuid
from typing import Optional, Iterable
import typing as T
import os
import tempfile
import hashlib
import logging

import time
import zipfile

import requests
from tqdm import tqdm
import jsonschema

from . import upload_api_v4, types, ipc, exif_write
from .image_log import create_upload_log
from .login import wrap_http_exception


MIN_CHUNK_SIZE = 1024 * 1024  # 1MB
MAX_CHUNK_SIZE = 1024 * 1024 * 32  # 32MB
LOG = logging.getLogger()


def find_root_dir(file_list: Iterable[str]) -> Optional[str]:
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
        return find_root_dir(dirs)


def upload_images(
    image_descriptions: T.Dict[str, types.FinalImageDescription],
    user_items: types.User,
    dry_run=False,
):
    jsonschema.validate(instance=user_items, schema=types.UserItemSchema)
    sequences: T.Dict[str, T.Dict[str, types.FinalImageDescription]] = {}
    for path, desc in image_descriptions.items():
        merged: types.FinalImageDescription = T.cast(
            types.FinalImageDescription, {**desc, **user_items}
        )
        del merged["user_upload_token"]
        jsonschema.validate(instance=merged, schema=types.FinalImageDescriptionSchema)
        sequence = sequences.setdefault(desc["MAPSequenceUUID"], {})
        sequence[path] = merged

    for sequence_idx, images in enumerate(sequences.values()):
        cluster_id = _upload_single_sequence(
            images, user_items, sequence_idx, len(sequences), dry_run=dry_run
        )
        if not dry_run:
            for path in images:
                create_upload_log(path, "upload_success")


class Notifier:
    def __init__(self, sequnece_info: dict):
        self.uploaded_bytes = 0
        self.sequence_info = sequnece_info

    def notify_progress(self, chunk: bytes, _):
        self.uploaded_bytes += len(chunk)
        payload = {
            "chunk_size": len(chunk),
            "uploaded_bytes": self.uploaded_bytes,
            **self.sequence_info,
        }
        ipc.send("upload", payload)


def zip_sequence(
    sequences: T.Dict[str, types.FinalImageDescription],
    fp: T.IO[bytes],
    tqdm_desc: str = "Compressing",
) -> str:
    file_list = list(sequences.keys())
    first_image = list(sequences.values())[0]
    sequence_uuid = first_image["MAPSequenceUUID"]

    root_dir = find_root_dir(file_list)
    if root_dir is None:
        raise RuntimeError(f"Unable to find the root dir of sequence {sequence_uuid}")

    sequence_md5 = hashlib.md5()

    file_list.sort(key=lambda path: sequences[path]["MAPCaptureTime"])

    # compressing
    with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as ziph:
        for file in tqdm(file_list, unit="files", desc=tqdm_desc):
            relpath = os.path.relpath(file, root_dir)
            edit = exif_write.ExifEdit(file)
            edit.add_image_description(sequences[file])
            image_bytes = edit.dump_image_bytes()
            sequence_md5.update(image_bytes)
            ziph.writestr(relpath, image_bytes)

    return sequence_md5.hexdigest()


def upload_zipped_sequence(
    user_items: types.User,
    fp: T.IO[bytes],
    entity_size: int,
    chunk_size: int,
    session_key: str = None,
    tqdm_desc: str = "Uploading",
    notifier: Optional[Notifier] = None,
    dry_run: bool = False,
) -> int:
    """
    :param fp: the file handle to a zipped sequence file. Will always upload from the beginning
    :param entity_size: the size of the whole zipped sequence file
    :param session_key: the upload session key used to identify an upload
    :return: cluster ID
    """

    if session_key is None:
        session_key = str(uuid.uuid4())

    user_access_token = user_items["user_upload_token"]

    # uploading
    if dry_run:
        upload_service: upload_api_v4.UploadService = upload_api_v4.FakeUploadService(
            user_access_token,
            session_key=session_key,
            entity_size=entity_size,
        )
    else:
        upload_service = upload_api_v4.UploadService(
            user_access_token,
            session_key=session_key,
            entity_size=entity_size,
        )

    retries = 0

    retryable_errors = (
        requests.HTTPError,
        requests.ConnectionError,
        requests.Timeout,
    )

    # when it progresses, we reset retries
    def _reset_retries(_, __):
        nonlocal retries
        retries = 0

    while True:
        with tqdm(
            total=upload_service.entity_size,
            desc=tqdm_desc,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
        ) as pbar:
            fp.seek(0, io.SEEK_SET)
            update_pbar = lambda chunk, _: pbar.update(len(chunk))
            try:
                offset = upload_service.fetch_offset()
                # set the initial progress
                pbar.update(offset)
                upload_service.callbacks = [
                    update_pbar,
                    _reset_retries,
                ]
                if notifier:
                    notifier.uploaded_bytes = offset
                    upload_service.callbacks.append(notifier.notify_progress)
                file_handle = upload_service.upload(
                    fp, chunk_size=chunk_size, offset=offset
                )
            except Exception as ex:
                if retries < 200 and isinstance(ex, retryable_errors):
                    retries += 1
                    sleep_for = min(2 ** retries, 16)
                    LOG.warning(
                        f"Error uploading, resuming in {sleep_for} seconds",
                        exc_info=True,
                    )
                    time.sleep(sleep_for)
                else:
                    if isinstance(ex, requests.HTTPError):
                        raise wrap_http_exception(ex) from ex
                    else:
                        raise ex
            else:
                break

    organization_id = user_items.get("MAPOrganizationKey")

    # TODO: retry here
    try:
        return upload_service.finish(file_handle, organization_id=organization_id)
    except requests.HTTPError as ex:
        raise wrap_http_exception(ex) from ex


def _upload_single_sequence(
    sequences: T.Dict[str, types.FinalImageDescription],
    user_items: types.User,
    sequence_idx: int,
    total_sequences: int,
    dry_run=False,
) -> int:
    def _build_desc(desc: str) -> str:
        return f"{desc} {sequence_idx + 1}/{total_sequences}"

    file_list = list(sequences.keys())
    first_image = list(sequences.values())[0]
    sequence_uuid = first_image["MAPSequenceUUID"]

    root_dir = find_root_dir(file_list)
    if root_dir is None:
        raise RuntimeError(f"Unable to find the root dir of sequence {sequence_uuid}")

    with tempfile.NamedTemporaryFile() as fp:
        sequence_md5 = zip_sequence(sequences, fp, tqdm_desc=_build_desc("Compressing"))

        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        # chunk size
        avg_image_size = int(entity_size / len(sequences))
        chunk_size = min(max(avg_image_size, MIN_CHUNK_SIZE), MAX_CHUNK_SIZE)

        notifier = Notifier(
            {
                "sequence_path": root_dir,
                "sequence_uuid": sequence_uuid,
                "total_bytes": entity_size,
                "sequence_idx": sequence_idx,
                "total_sequences": total_sequences,
            }
        )

        return upload_zipped_sequence(
            user_items,
            fp,
            entity_size,
            chunk_size,
            session_key=f"mly_tools_{sequence_md5}.zip",
            tqdm_desc=_build_desc("Uploading"),
            notifier=notifier,
            dry_run=dry_run,
        )
