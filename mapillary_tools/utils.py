import hashlib
import os
import typing as T
from pathlib import Path


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


def file_md5sum(path: Path) -> str:
    with open(path, "rb") as fp:
        return md5sum_fp(fp)


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in (".jpg", ".jpeg", ".tif", ".tiff", ".pgm", ".pnm")


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in (
        ".mp4",
        ".avi",
        ".tavi",
        ".mov",
        ".mkv",
        # GoPro Max video filename extension
        ".360",
    )


def iterate_files(root: Path, recursive: bool = False) -> T.Generator[Path, None, None]:
    for dirpath, dirnames, files in os.walk(root, topdown=True):
        if not recursive:
            dirnames.clear()
        else:
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for file in files:
            if file.startswith("."):
                continue
            yield Path(dirpath).joinpath(file)


def get_video_file_list(
    video_file: Path, skip_subfolders: bool = False, abs_path: bool = False
) -> T.List[Path]:
    files = iterate_files(video_file, not skip_subfolders)
    return sorted(
        file if abs_path else file.relative_to(video_file)
        for file in files
        if is_video_file(file)
    )


def get_image_file_list(
    import_path: Path, skip_subfolders: bool = False, abs_path: bool = False
) -> T.List[Path]:
    files = iterate_files(import_path, not skip_subfolders)
    return sorted(
        file if abs_path else file.relative_to(import_path)
        for file in files
        if is_image_file(file)
    )


def filter_video_samples(
    images: T.Sequence[Path],
    video_path: Path,
    skip_subfolders: bool = False,
) -> T.Generator[Path, None, None]:
    if video_path.is_dir():
        video_basenames = set(
            f.name
            for f in get_video_file_list(video_path, skip_subfolders=skip_subfolders)
        )
    else:
        video_basenames = {video_path.name}

    for image in images:
        image_dirname = image.absolute().parent.name
        if image_dirname in video_basenames:
            root, _ = os.path.splitext(image_dirname)
            if image.name.startswith(root + "_"):
                yield image
