import os
import typing as T
import hashlib


def md5sum_fp(fp: T.IO[bytes]) -> str:
    md5 = hashlib.md5()
    while True:
        buf = fp.read(1024 * 1024 * 32)
        if not buf:
            break
        md5.update(buf)
    return md5.hexdigest()


def md5sum_bytes(data: bytes) -> str:
    md5 = hashlib.md5()
    md5.update(data)
    return md5.hexdigest()


def file_md5sum(path: str) -> str:
    with open(path, "rb") as fp:
        return md5sum_fp(fp)


def is_image_file(path: str) -> bool:
    basename, ext = os.path.splitext(os.path.basename(path))
    return ext.lower() in (".jpg", ".jpeg", ".tif", ".tiff", ".pgm", ".pnm")


def is_video_file(path: str) -> bool:
    basename, ext = os.path.splitext(os.path.basename(path))
    return ext.lower() in (".mp4", ".avi", ".tavi", ".mov", ".mkv")


def iterate_files(root: str, recursive: bool = False) -> T.Generator[str, None, None]:
    for dirpath, dirnames, files in os.walk(root, topdown=True):
        if not recursive:
            dirnames.clear()
        else:
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for file in files:
            yield os.path.join(dirpath, file)


def get_video_file_list(
    video_file: str, skip_subfolders: bool = False, abs_path: bool = False
) -> T.List[str]:
    files = iterate_files(video_file, not skip_subfolders)
    return sorted(
        file if abs_path else os.path.relpath(file, video_file)
        for file in files
        if is_video_file(file)
    )


def get_image_file_list(
    import_path: str, skip_subfolders: bool = False, abs_path: bool = False
) -> T.List[str]:
    files = iterate_files(import_path, not skip_subfolders)
    return sorted(
        file if abs_path else os.path.relpath(file, import_path)
        for file in files
        if is_image_file(file)
    )


def filter_video_samples(
    images: T.List[str], video_path: str, skip_subfolders: bool = False
) -> T.List[str]:
    if os.path.isdir(video_path):
        videos = set(
            os.path.basename(f)
            for f in get_video_file_list(video_path, skip_subfolders=skip_subfolders)
        )
    else:
        videos = {os.path.basename(video_path)}
    filtered = []
    for image in images:
        dirname = os.path.basename(os.path.dirname(os.path.abspath(image)))
        if dirname in videos:
            root, _ = os.path.splitext(dirname)
            if os.path.basename(image).startswith(root + "_"):
                filtered.append(image)
    return filtered
