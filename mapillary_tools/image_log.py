import os
import typing as T
from typing import Generator, List, Optional

from . import types


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


_IMAGE_STATE: T.Dict[str, T.Dict[types.Process, T.Tuple[types.Status, T.Mapping]]] = {}


def _create_and_log_process_in_memory(
    image: str,
    process: types.Process,
    status: types.Status,
    description: T.Mapping,
) -> None:
    _IMAGE_STATE.setdefault(image, {})[process] = (status, description)


def log_failed_in_memory(image: str, process: types.Process, exc: Exception):
    desc: T.Dict = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }
    exc_vars = vars(exc)
    if exc_vars:
        desc["vars"] = exc_vars
    return _create_and_log_process_in_memory(image, process, "failed", desc)


def log_in_memory(image: str, process: types.Process, desc: T.Mapping):
    return _create_and_log_process_in_memory(image, process, "success", desc)


def read_process_data_from_memory(
    image: str, process: types.Process
) -> Optional[T.Tuple[types.Status, T.Mapping]]:
    state = _IMAGE_STATE.get(image)
    if state is None:
        return None
    return state.get(process)
