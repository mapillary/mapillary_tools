import hashlib
import os
import typing as T
from pathlib import Path


# Use "hashlib._Hash" instead of hashlib._Hash because:
# AttributeError: module 'hashlib' has no attribute '_Hash'
def md5sum_fp(
    fp: T.IO[bytes], md5: T.Optional["hashlib._Hash"] = None
) -> "hashlib._Hash":
    if md5 is None:
        md5 = hashlib.md5()
    while True:
        buf = fp.read(1024 * 1024 * 32)
        if not buf:
            break
        md5.update(buf)
    return md5


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


def filter_video_samples(
    image_paths: T.Sequence[Path],
    video_path: Path,
    skip_subfolders: bool = False,
) -> T.Generator[Path, None, None]:
    if video_path.is_dir():
        video_basenames = set(
            f.name
            for f in iterate_files(video_path, not skip_subfolders)
            if is_video_file(f)
        )
    else:
        video_basenames = {video_path.name}

    for image_path in image_paths:
        # If you want to walk an arbitrary filesystem path upwards,
        # it is recommended to first call Path.resolve() so as to resolve symlinks and eliminate “..” components.
        image_dirname = image_path.resolve().parent.name
        if image_dirname in video_basenames:
            root, _ = os.path.splitext(image_dirname)
            if image_path.name.startswith(root + "_"):
                yield image_path


def deduplicate_paths(paths: T.Iterable[Path]) -> T.Generator[Path, None, None]:
    resolved_paths: T.Set[Path] = set()
    for p in paths:
        resolved = p.resolve()
        if resolved not in resolved_paths:
            resolved_paths.add(resolved)
            yield p


def find_images(
    import_paths: T.Sequence[Path],
    skip_subfolders: bool = False,
    check_file_suffix: bool = False,
) -> T.List[Path]:
    image_paths: T.List[Path] = []
    for path in import_paths:
        if path.is_dir():
            image_paths.extend(
                file
                for file in iterate_files(path, not skip_subfolders)
                if is_image_file(file)
            )
        else:
            if check_file_suffix:
                if is_image_file(path):
                    image_paths.append(path)
            else:
                image_paths.append(path)
    return list(deduplicate_paths(image_paths))


def find_videos(
    import_paths: T.Sequence[Path],
    skip_subfolders: bool = False,
    check_file_suffix: bool = False,
) -> T.List[Path]:
    video_paths: T.List[Path] = []
    for path in import_paths:
        if path.is_dir():
            video_paths.extend(
                file
                for file in iterate_files(path, not skip_subfolders)
                if is_video_file(file)
            )
        else:
            if check_file_suffix:
                if is_video_file(path):
                    video_paths.append(path)
            else:
                video_paths.append(path)
    return list(deduplicate_paths(video_paths))


def find_zipfiles(
    import_paths: T.Sequence[Path],
    skip_subfolders: bool = False,
    check_file_suffix: bool = False,
) -> T.List[Path]:
    zip_paths: T.List[Path] = []
    for path in import_paths:
        if path.is_dir():
            zip_paths.extend(
                file
                for file in iterate_files(path, not skip_subfolders)
                if file.suffix.lower() in [".zip"]
            )
        else:
            if check_file_suffix:
                if path.suffix.lower() in [".zip"]:
                    zip_paths.append(path)
            else:
                zip_paths.append(path)
    return list(deduplicate_paths(zip_paths))
