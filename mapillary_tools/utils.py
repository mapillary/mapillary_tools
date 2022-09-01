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
    with path.open("rb") as fp:
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
    video_file: Path, skip_subfolders: bool = False
) -> T.List[Path]:
    files = iterate_files(video_file, not skip_subfolders)
    return sorted(file for file in files if is_video_file(file))


def get_image_file_list(
    import_path: Path, skip_subfolders: bool = False
) -> T.List[Path]:
    files = iterate_files(import_path, not skip_subfolders)
    return sorted(file for file in files if is_image_file(file))


def filter_video_samples(
    image_paths: T.Sequence[Path],
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

    for image_path in image_paths:
        # If you want to walk an arbitrary filesystem path upwards,
        # it is recommended to first call Path.resolve() so as to resolve symlinks and eliminate “..” components.
        image_dirname = image_path.resolve().parent.name
        if image_dirname in video_basenames:
            root, _ = os.path.splitext(image_dirname)
            if image_path.name.startswith(root + "_"):
                yield image_path


def deduplicate_paths(paths: T.Sequence[Path]) -> T.List[Path]:
    resolved_path: T.Set[Path] = set()
    dedups: T.List[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved not in resolved_path:
            resolved_path.add(resolved)
            dedups.append(p)
    return dedups


def find_images(
    import_paths: T.Sequence[Path],
    skip_subfolders: bool = False,
    check_all_paths: bool = False,
) -> T.List[Path]:
    image_paths = []
    for path in import_paths:
        if path.is_dir():
            image_paths.extend(
                get_image_file_list(path, skip_subfolders=skip_subfolders)
            )
        else:
            if check_all_paths:
                if is_image_file(path):
                    image_paths.append(path)
            else:
                image_paths.append(path)
    return deduplicate_paths(image_paths)


def find_videos(
    import_paths: T.Sequence[Path],
    skip_subfolders: bool = False,
    check_all_paths: bool = False,
) -> T.List[Path]:
    video_paths = []
    for path in import_paths:
        if path.is_dir():
            video_paths.extend(
                get_video_file_list(path, skip_subfolders=skip_subfolders)
            )
        else:
            if check_all_paths:
                if is_video_file(path):
                    video_paths.append(path)
            else:
                video_paths.append(path)
    return deduplicate_paths(video_paths)


def find_zipfiles(
    import_paths: T.Sequence[Path],
    skip_subfolders: bool = False,
    check_all_paths: bool = False,
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
            if check_all_paths:
                if path.suffix.lower() in [".zip"]:
                    zip_paths.append(path)
            else:
                zip_paths.append(path)
    return deduplicate_paths(zip_paths)
