import io
from typing import List, Optional, Iterable, Generator
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
from .login import wrap_http_exception


MIN_CHUNK_SIZE = 1024 * 1024  # 1MB
MAX_CHUNK_SIZE = 1024 * 1024 * 32  # 32MB
LOG = logging.getLogger()


def is_image_file(path: str) -> bool:
    basename, ext = os.path.splitext(os.path.basename(path))
    return ext.lower() in (".jpg", ".jpeg", ".tif", ".tiff", ".pgm", ".pnm")


def is_video_file(path: str) -> bool:
    basename, ext = os.path.splitext(os.path.basename(path))
    return ext.lower() in (".mp4", ".avi", ".tavi", ".mov", ".mkv")


def iterate_files(root: str, recursive=False) -> Generator[str, None, None]:
    for dirpath, dirnames, files in os.walk(root, topdown=True):
        if not recursive:
            dirnames.clear()
        else:
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for file in files:
            yield os.path.join(dirpath, file)


def get_upload_file_list(import_path: str, skip_subfolders: bool = False) -> List[str]:
    files = iterate_files(import_path, not skip_subfolders)
    return sorted(
        file for file in files if is_image_file(file) and preform_upload(file)
    )


def get_video_file_list(video_file, skip_subfolders=False) -> T.List[str]:
    files = iterate_files(video_file, not skip_subfolders)
    return sorted(file for file in files if is_video_file(file))


def get_total_file_list(import_path: str, skip_subfolders: bool = False) -> List[str]:
    files = iterate_files(import_path, not skip_subfolders)
    return sorted(file for file in files if is_image_file(file))


def get_failed_upload_file_list(
    import_path: str, skip_subfolders: bool = False
) -> List[str]:
    files = iterate_files(import_path, not skip_subfolders)
    return sorted(file for file in files if is_image_file(file) and failed_upload(file))


def get_success_upload_file_list(
    import_path: str, skip_subfolders: bool = False
) -> List[str]:
    files = iterate_files(import_path, not skip_subfolders)
    return sorted(
        file for file in files if is_image_file(file) and success_upload(file)
    )


def success_upload(file_path: str) -> bool:
    log_root = log_rootpath(file_path)
    upload_success = os.path.join(log_root, "upload_success")
    success = os.path.isfile(upload_success)
    return success


def preform_upload(file_path: str) -> bool:
    log_root = log_rootpath(file_path)
    process_success = os.path.join(log_root, "mapillary_image_description.json")
    duplicate = os.path.join(log_root, "duplicate")
    upload_succes = os.path.join(log_root, "upload_success")
    upload = (
        not os.path.isfile(upload_succes)
        and os.path.isfile(process_success)
        and not os.path.isfile(duplicate)
    )
    return upload


def failed_upload(file_path: str) -> bool:
    log_root = log_rootpath(file_path)
    process_failed = os.path.join(log_root, "mapillary_image_description.error.json")
    duplicate = os.path.join(log_root, "duplicate")
    upload_failed = os.path.join(log_root, "upload_failed")
    failed = (
        os.path.isfile(upload_failed)
        and not os.path.isfile(process_failed)
        and not os.path.isfile(duplicate)
    )
    return failed


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
        cluster_id = upload_single_sequence(
            images, user_items, sequence_idx, len(sequences), dry_run=dry_run
        )
        if not dry_run:
            for path in images:
                create_upload_log(path, "upload_success")


def upload_single_sequence(
    sequences: T.Dict[str, types.FinalImageDescription],
    user_items: types.User,
    sequence_idx: int,
    total_sequences: int,
    dry_run=False,
) -> int:
    first_image = list(sequences.values())[0]

    sequence_uuid = first_image["MAPSequenceUUID"]

    file_list = list(sequences.keys())

    root_dir = find_root_dir(file_list)
    if root_dir is None:
        raise RuntimeError(f"Unable to find the root dir of sequence {sequence_uuid}")

    file_list.sort(key=lambda path: sequences[path]["MAPCaptureTime"])

    user_access_token = user_items["user_upload_token"]

    def _gen_notify_progress(uploaded_bytes: int):
        def _notify_progress(chunk: bytes, _):
            nonlocal uploaded_bytes
            uploaded_bytes += len(chunk)
            assert (
                uploaded_bytes <= entity_size
            ), f"expect {uploaded_bytes} <= {entity_size}"
            payload = {
                "chunk_size": len(chunk),
                "sequence_path": root_dir,
                "sequence_uuid": sequence_uuid,
                "total_bytes": entity_size,
                "uploaded_bytes": uploaded_bytes,
                "sequence_idx": sequence_idx,
                "total_sequences": total_sequences,
            }
            ipc.send("upload", payload)

        return _notify_progress

    def _build_desc(desc: str) -> str:
        return f"{desc} {sequence_idx + 1}/{total_sequences}"

    retryable_errors = (
        requests.HTTPError,
        requests.ConnectionError,
        requests.Timeout,
    )

    md5 = hashlib.md5()

    with tempfile.NamedTemporaryFile() as fp:
        # compressing
        with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as ziph:
            for file in tqdm(file_list, unit="files", desc=_build_desc("Compressing")):
                relpath = os.path.relpath(file, root_dir)
                edit = exif_write.ExifEdit(file)
                edit.add_image_description(sequences[file])
                image_bytes = edit.dump_image_bytes()
                md5.update(image_bytes)
                ziph.writestr(relpath, image_bytes)

        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        # chunk size
        avg_image_size = int(entity_size / len(file_list))
        chunk_size = min(max(avg_image_size, MIN_CHUNK_SIZE), MAX_CHUNK_SIZE)

        # md5sum
        md5sum = md5.hexdigest()

        # uploading
        if dry_run:
            service: upload_api_v4.UploadService = upload_api_v4.FakeUploadService(
                user_access_token,
                session_key=f"mly_tools_{md5sum}.zip",
                entity_size=entity_size,
            )
        else:
            service = upload_api_v4.UploadService(
                user_access_token,
                session_key=f"mly_tools_{md5sum}.zip",
                entity_size=entity_size,
            )

        retries = 0

        # when it progresses, we reset retries
        def _reset_retries(_, __):
            nonlocal retries
            retries = 0

        while True:
            with tqdm(
                total=entity_size,
                desc=_build_desc("Uploading"),
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
            ) as pbar:
                update_pbar = lambda chunk, _: pbar.update(len(chunk))
                fp.seek(0, io.SEEK_SET)
                try:
                    offset = service.fetch_offset()
                    pbar.update(offset)
                    service.callbacks = [
                        update_pbar,
                        _reset_retries,
                        _gen_notify_progress(offset),
                    ]
                    file_handle = service.upload(
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

    organization_id = first_image.get("MAPOrganizationKey")

    # TODO: retry here
    try:
        return service.finish(file_handle, organization_id=organization_id)
    except requests.HTTPError as ex:
        raise wrap_http_exception(ex) from ex


def log_rootpath(filepath: str) -> str:
    return os.path.join(
        os.path.dirname(filepath),
        ".mapillary",
        "logs",
        os.path.splitext(os.path.basename(filepath))[0],
    )


def create_upload_log(filepath: str, status: str) -> None:
    assert status in ["upload_success", "upload_failed"], f"invalid status {status}"
    log_root = log_rootpath(filepath)
    upload_log_filepath = os.path.join(log_root, status)
    opposite_status = {
        "upload_success": "upload_failed",
        "upload_failed": "upload_success",
    }
    upload_opposite_log_filepath = os.path.join(log_root, opposite_status[status])
    if not os.path.isdir(log_root):
        os.makedirs(log_root)
        open(upload_log_filepath, "w").close()
    else:
        if not os.path.isfile(upload_log_filepath):
            open(upload_log_filepath, "w").close()
        if os.path.isfile(upload_opposite_log_filepath):
            os.remove(upload_opposite_log_filepath)
