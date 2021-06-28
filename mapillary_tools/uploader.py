import io
from typing import List, Optional, Iterable, IO, Callable
import os
import sys
import tempfile
import hashlib

import time
import zipfile

import requests
from tqdm import tqdm

from . import upload_api_v4
from . import ipc
from .login import authenticate_user, wrap_http_exception


MIN_CHUNK_SIZE = 1024 * 1024  # 1MB
MAX_CHUNK_SIZE = 1024 * 1024 * 32  # 32MB


def flag_finalization(finalize_file_list):
    for file in finalize_file_list:
        finalize_flag = os.path.join(log_rootpath(file), "upload_finalized")
        open(finalize_flag, "a").close()


def get_upload_file_list(import_path: str, skip_subfolders: bool = False) -> List[str]:
    upload_file_list: List[str] = []
    if skip_subfolders:
        upload_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and preform_upload(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            upload_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and preform_upload(root, file)
            )
    return sorted(upload_file_list)


# get a list of video files in a video_file
# TODO: Create list of supported files instead of adding only these 3
def get_video_file_list(video_file, skip_subfolders=False):
    video_file_list = []
    supported_files = ("mp4", "avi", "tavi", "mov", "mkv")
    if skip_subfolders:
        video_file_list.extend(
            os.path.join(os.path.abspath(video_file), file)
            for file in os.listdir(video_file)
            if (file.lower().endswith(supported_files))
        )
    else:
        for root, _, files in os.walk(video_file):
            video_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if (file.lower().endswith(supported_files))
            )
    return sorted(video_file_list)


def get_total_file_list(import_path: str, skip_subfolders: bool = False) -> List[str]:
    total_file_list: List[str] = []
    if skip_subfolders:
        total_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            total_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
            )
    return sorted(total_file_list)


def get_failed_upload_file_list(
    import_path: str, skip_subfolders: bool = False
) -> List[str]:
    failed_upload_file_list: List[str] = []
    if skip_subfolders:
        failed_upload_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and failed_upload(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            failed_upload_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and failed_upload(root, file)
            )

    return sorted(failed_upload_file_list)


def get_success_upload_file_list(
    import_path: str, skip_subfolders: bool = False
) -> List[str]:
    success_upload_file_list: List[str] = []
    if skip_subfolders:
        success_upload_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and success_upload(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            success_upload_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and success_upload(root, file)
            )

    return sorted(success_upload_file_list)


def success_upload(root: str, file: str) -> bool:
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    upload_success = os.path.join(log_root, "upload_success")
    upload_finalization = os.path.join(log_root, "upload_finalized")
    manual_upload = os.path.join(log_root, "manual_upload")
    success = (
        os.path.isfile(upload_success) and not os.path.isfile(manual_upload)
    ) or (
        os.path.isfile(upload_success)
        and os.path.isfile(manual_upload)
        and os.path.isfile(upload_finalization)
    )
    return success


def get_success_only_manual_upload_file_list(import_path, skip_subfolders=False):
    success_only_manual_upload_file_list = []
    if skip_subfolders:
        success_only_manual_upload_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and success_only_manual_upload(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            success_only_manual_upload_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and success_only_manual_upload(root, file)
            )

    return sorted(success_only_manual_upload_file_list)


def success_only_manual_upload(root, file):
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    upload_success = os.path.join(log_root, "upload_success")
    manual_upload = os.path.join(log_root, "manual_upload")
    success = os.path.isfile(upload_success) and os.path.isfile(manual_upload)
    return success


def preform_upload(root: str, file: str) -> bool:
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    process_success = os.path.join(log_root, "mapillary_image_description_success")
    duplicate = os.path.join(log_root, "duplicate")
    upload_succes = os.path.join(log_root, "upload_success")
    upload = (
        not os.path.isfile(upload_succes)
        and os.path.isfile(process_success)
        and not os.path.isfile(duplicate)
    )
    return upload


def failed_upload(root: str, file: str) -> bool:
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    process_failed = os.path.join(log_root, "mapillary_image_description_failed")
    duplicate = os.path.join(log_root, "duplicate")
    upload_failed = os.path.join(log_root, "upload_failed")
    failed = (
        os.path.isfile(upload_failed)
        and not os.path.isfile(process_failed)
        and not os.path.isfile(duplicate)
    )
    return failed


def get_finalize_file_list(
    import_path: str, skip_subfolders: bool = False
) -> List[str]:
    finalize_file_list: List[str] = []
    if skip_subfolders:
        finalize_file_list.extend(
            os.path.join(os.path.abspath(import_path), file)
            for file in os.listdir(import_path)
            if file.lower().endswith(
                ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
            )
            and preform_finalize(import_path, file)
        )
    else:
        for root, _, files in os.walk(import_path):
            if os.path.join(".mapillary", "logs") in root:
                continue
            finalize_file_list.extend(
                os.path.join(os.path.abspath(root), file)
                for file in files
                if file.lower().endswith(
                    ("jpg", "jpeg", "tif", "tiff", "pgm", "pnm", "gif")
                )
                and preform_finalize(root, file)
            )

    return sorted(finalize_file_list)


def preform_finalize(root: str, file: str) -> bool:
    file_path = os.path.join(root, file)
    log_root = log_rootpath(file_path)
    upload_succes = os.path.join(log_root, "upload_success")
    upload_finalized = os.path.join(log_root, "upload_finalized")
    manual_upload = os.path.join(log_root, "manual_upload")
    finalize = (
        os.path.isfile(upload_succes)
        and not os.path.isfile(upload_finalized)
        and os.path.isfile(manual_upload)
    )
    return finalize


def print_summary(file_list):
    # inform upload has finished and print out the summary
    print(f"Done uploading {len(file_list)} images.")  # improve upload summary


def progress(count, total, suffix=""):
    """
    Display progress bar
    sources: https://gist.github.com/vladignatyev/06860ec2040cb497f0f3
    """
    bar_len = 60
    filled_len = int(round(bar_len * count / float(total)))
    percents = round(100.0 * count / float(total), 1)
    bar = "=" * filled_len + "-" * (bar_len - filled_len)
    sys.stdout.write(f"[{bar}] {percents}% {suffix}\r")
    sys.stdout.flush()


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


def upload_sequence_v4(
    file_list: list, sequence_uuid: str, file_params: dict, dry_run=False
):
    first_image = list(file_params.values())[0]
    user_name = first_image["user_name"]

    def _read_captured_at(path):
        return file_params.get(path, {}).get("MAPCaptureTime", "")

    # Sorting images by captured_at
    file_list.sort(key=_read_captured_at)

    root_dir = find_root_dir(file_list)
    if root_dir is None:
        raise RuntimeError(f"Unable to find the root dir of sequence {sequence_uuid}")

    credentials = authenticate_user(user_name)
    user_access_token = credentials["user_upload_token"]

    with tempfile.NamedTemporaryFile() as fp:
        # compressing
        with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as ziph:
            with tqdm(total=len(file_list), desc="Compressing") as pbar:
                for fullpath in file_list:
                    relpath = os.path.relpath(fullpath, root_dir)
                    ziph.write(fullpath, relpath)
                    pbar.update(1)
        fp.seek(0, io.SEEK_END)
        entity_size = fp.tell()

        # chunk size
        avg_image_size = int(entity_size / len(file_list))
        chunk_size = min(max(avg_image_size, MIN_CHUNK_SIZE), MAX_CHUNK_SIZE)

        service = upload_api_v4.UploadService(user_access_token, chunk_size=chunk_size)

        # md5sum
        fp.seek(0, io.SEEK_SET)
        md5 = hashlib.md5()
        while True:
            buf = fp.read(MAX_CHUNK_SIZE)
            if not buf:
                break
            md5.update(buf)
        md5sum = md5.hexdigest()

        # uploading
        fp.seek(0, io.SEEK_SET)
        session_key = f"mly_tools_{md5sum}"
        initial_offset = service.fetch_offset(session_key)
        with tqdm(
            total=entity_size,
            initial=initial_offset,
            desc="Uploading",
        ) as pbar:
            uploaded_bytes = initial_offset

            def _notify_progress(chunk: bytes, _):
                nonlocal uploaded_bytes
                uploaded_bytes += len(chunk)
                assert uploaded_bytes <= entity_size
                ipc.send(
                    "upload",
                    {
                        "chunk_size": len(chunk),
                        "sequence_path": root_dir,
                        "sequence_uuid": sequence_uuid,
                        "total_bytes": entity_size,
                        "uploaded_bytes": uploaded_bytes,
                    },
                )
                pbar.update(len(chunk))

            try:
                upload_resp = service.upload(
                    session_key,
                    fp,
                    entity_size,
                    callback=_notify_progress,
                )
            except requests.HTTPError as ex:
                if not dry_run:
                    for path in file_list:
                        create_upload_log(path, "upload_failed")
                raise wrap_http_exception(ex)

    upload_resp_json = upload_resp.json()
    try:
        file_handle = upload_resp_json["h"]
    except KeyError:
        raise RuntimeError(
            f"File handle not found in the upload response {upload_resp.text}"
        )

    if dry_run:
        return

    organization_id = first_image.get("MAPOrganizationKey")

    if organization_id is None:
        print(f"Finishing upload {sequence_uuid}")
    else:
        print(f"Finishing upload {sequence_uuid} for organization {organization_id}")

    finish_resp = service.finish(file_handle, organization_id=organization_id)
    try:
        finish_resp.raise_for_status()
    except requests.HTTPError as ex:
        for path in file_list:
            create_upload_log(path, "upload_failed")
        raise wrap_http_exception(ex)

    # check cluster id
    finish_data = finish_resp.json()
    cluster_id = finish_data.get("cluster_id")
    if cluster_id is None:
        for path in file_list:
            create_upload_log(path, "upload_failed")
        raise RuntimeError(
            f"Upload server error: failed to create the cluster {finish_resp.text}"
        )
    else:
        print(f"Cluster {cluster_id} created")

    for path in file_list:
        create_upload_log(path, "upload_success")

    flag_finalization(file_list)


def log_rootpath(filepath: str) -> str:
    return os.path.join(
        os.path.dirname(filepath),
        ".mapillary",
        "logs",
        os.path.splitext(os.path.basename(filepath))[0],
    )


def log_folder(filepath: str) -> str:
    return os.path.join(os.path.dirname(filepath), ".mapillary", "logs")


def create_upload_log(filepath: str, status: str) -> None:
    assert status in ["upload_success", "upload_failed"], f"invalid status {status}"
    upload_log_root = log_rootpath(filepath)
    upload_log_filepath = os.path.join(upload_log_root, status)
    opposite_status = {
        "upload_success": "upload_failed",
        "upload_failed": "upload_success",
    }
    upload_opposite_log_filepath = os.path.join(
        upload_log_root, opposite_status[status]
    )
    suffix = str(time.strftime("%Y_%m_%d_%H_%M_%S", time.gmtime()))
    if not os.path.isdir(upload_log_root):
        os.makedirs(upload_log_root)
        open(upload_log_filepath, "w").close()
        open(f"{upload_log_filepath}_{suffix}", "w").close()
    else:
        if not os.path.isfile(upload_log_filepath):
            open(upload_log_filepath, "w").close()
            open(f"{upload_log_filepath}_{suffix}", "w").close()
        if os.path.isfile(upload_opposite_log_filepath):
            os.remove(upload_opposite_log_filepath)
