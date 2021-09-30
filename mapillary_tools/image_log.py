import json
import os
import typing as T
from typing import Generator, List, Optional, cast

from . import types, ipc
from .utils import force_decode


def log_rootpath(filepath: str) -> str:
    return os.path.join(
        os.path.dirname(filepath),
        ".mapillary",
        "logs",
        os.path.basename(filepath),
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


def get_video_file_list(video_file, skip_subfolders=False) -> T.List[str]:
    files = iterate_files(video_file, not skip_subfolders)
    return sorted(file for file in files if is_video_file(file))


def get_total_file_list(import_path: str, skip_subfolders: bool = False) -> List[str]:
    files = iterate_files(import_path, not skip_subfolders)
    return sorted(file for file in files if is_image_file(file))


def process_success(image: str) -> bool:
    log_root = log_rootpath(image)
    return os.path.isfile(os.path.join(log_root, "mapillary_image_description.json"))


def process_failed(image: str) -> bool:
    log_root = log_rootpath(image)
    return os.path.isfile(
        os.path.join(log_root, "mapillary_image_description.error.json")
    )


def upload_success(image: str) -> bool:
    log_root = log_rootpath(image)
    return os.path.isfile(os.path.join(log_root, "upload_success"))


def upload_failed(image: str) -> bool:
    log_root = log_rootpath(image)
    return os.path.isfile(os.path.join(log_root, "upload_failed"))


_IMAGE_STATE: T.Dict[str, T.Dict[types.Process, T.Tuple[types.Status, T.Mapping]]] = {}


def create_and_log_process_in_memory(
    image: str,
    process: types.Process,
    status: types.Status,
    description: T.Mapping,
) -> None:
    _IMAGE_STATE.setdefault(image, {})[process] = (status, description)
    decoded_image = force_decode(image)
    ipc.send(
        process,
        {
            "image": decoded_image,
            "status": status,
            "description": description,
        },
    )


def log_failed_in_memory(image: str, process: types.Process, exc: Exception):
    desc = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }
    exc_vars = vars(exc)
    if exc_vars:
        desc["vars"] = exc_vars
    return create_and_log_process_in_memory(image, process, "failed", desc)


def log_in_memory(image: str, process: types.Process, desc: T.Mapping):
    return create_and_log_process_in_memory(image, process, "success", desc)


def create_and_log_process(
    image: str,
    process: types.Process,
    status: types.Status,
    description: T.Mapping,
) -> None:
    log_root = log_rootpath(image)
    if not os.path.isdir(log_root):
        os.makedirs(log_root)

    log_MAPJson = os.path.join(log_root, process + ".json")
    log_MAPJson_failed = os.path.join(log_root, process + ".error.json")

    if status == "success":
        save_json(description, log_MAPJson)
        if os.path.isfile(log_MAPJson_failed):
            os.remove(log_MAPJson_failed)
    elif status == "failed":
        save_json(description, log_MAPJson_failed)
        if os.path.isfile(log_MAPJson):
            os.remove(log_MAPJson)
    else:
        raise ValueError(f"Invalid status {status}")

    decoded_image = force_decode(image)

    ipc.send(
        process,
        {
            "image": decoded_image,
            "status": status,
            "description": description,
        },
    )


def load_json(file_path: str):
    # FIXME: what if file_path does not exist
    with open(file_path) as fp:
        try:
            return json.load(fp)
        except json.JSONDecodeError:
            raise RuntimeError(f"Error JSON decoding {file_path}")


def save_json(data: T.Mapping, file_path: str) -> None:
    try:
        buf = json.dumps(data, indent=4)
    except Exception:
        # FIXME: more explicit
        raise RuntimeError(f"Error JSON serializing {data}")
    with open(file_path, "w") as f:
        f.write(buf)


def processed_images_rootpath(filepath: str) -> str:
    return os.path.join(
        os.path.dirname(filepath),
        ".mapillary",
        "processed_images",
        os.path.basename(filepath),
    )


def read_process_data(image: str, process: types.Process) -> Optional[dict]:
    log_root = log_rootpath(image)
    path = os.path.join(log_root, f"{process}.json")
    if not os.path.isfile(path):
        return None
    return load_json(path)


def read_failed_process_data(image: str, process: types.Process) -> Optional[dict]:
    log_root = log_rootpath(image)
    path = os.path.join(log_root, f"{process}.error.json")
    if not os.path.isfile(path):
        return None
    return load_json(path)


def read_process_data_from_memory(
    image: str, process: types.Process
) -> Optional[T.Tuple[types.Status, T.Mapping]]:
    state = _IMAGE_STATE.get(image)
    if state is None:
        return None
    return state.get(process)


def read_image_description(image) -> Optional[types.FinalImageDescription]:
    return cast(
        Optional[types.FinalImageDescription],
        read_process_data(image, "mapillary_image_description"),
    )
