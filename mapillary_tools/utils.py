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
    return path.suffix.lower() in (
        ".jpg",
        ".jpeg",
        ".jpe",
        ".tif",
        ".tiff",
        ".pgm",
        ".pnm",
    )


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in (
        ".mp4",
        ".avi",
        ".tavi",
        ".dv",
        ".m2t",
        ".m2ts",
        ".m4v",
        ".mqv",
        ".mts",
        ".ts",
        ".mov",
        ".qt",
        ".mkv",
        # GoPro Max video filename extension
        ".360",
    )


def iterate_files(
    root: Path, recursive: bool = False, follow_hidden_dirs: bool = False
) -> T.Generator[Path, None, None]:
    for dirpath, dirnames, files in os.walk(root, topdown=True):
        if not recursive:
            dirnames.clear()
        else:
            if not follow_hidden_dirs:
                dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for file in files:
            if file.startswith("."):
                continue
            yield Path(dirpath).joinpath(file)


def filter_video_samples(
    image_paths: T.Sequence[Path],
    video_filename_or_dir: Path,
    skip_subfolders: bool = False,
) -> T.Generator[Path, None, None]:
    if video_filename_or_dir.is_dir():
        video_paths = list(
            set(
                path
                for path in iterate_files(video_filename_or_dir, not skip_subfolders)
                if is_video_file(path)
            )
        )
    else:
        video_paths = [video_filename_or_dir]

    image_samples_by_video_path = find_all_image_samples(image_paths, list(video_paths))

    for image_paths in image_samples_by_video_path.values():
        for image_path in image_paths:
            yield image_path


def find_all_image_samples(
    image_paths: T.Sequence[Path], video_paths: T.Sequence[Path]
) -> T.Dict[Path, T.List[Path]]:
    # TODO: not work with the same filenames, e.g. foo/hello.mp4 and bar/hello.mp4
    video_basenames = {path.name: path for path in video_paths}

    image_samples_by_video_path: T.Dict[Path, T.List[Path]] = {}
    for image_path in image_paths:
        # If you want to walk an arbitrary filesystem path upwards,
        # it is recommended to first call Path.resolve() so as to resolve symlinks and eliminate “..” components.
        image_dirname = image_path.resolve().parent.name
        if image_dirname in video_basenames:
            root, _ = os.path.splitext(image_dirname)
            if image_path.name.startswith(root + "_"):
                video_path = video_basenames[image_dirname]
                image_samples_by_video_path.setdefault(video_path, []).append(
                    image_path
                )

    return image_samples_by_video_path


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
            if is_image_file(path):
                image_paths.append(path)
    return list(deduplicate_paths(image_paths))


def find_videos(
    import_paths: T.Sequence[Path],
    skip_subfolders: bool = False,
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
            if is_video_file(path):
                video_paths.append(path)
    return list(deduplicate_paths(video_paths))


def find_zipfiles(
    import_paths: T.Sequence[Path],
    skip_subfolders: bool = False,
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
            if path.suffix.lower() in [".zip"]:
                zip_paths.append(path)
    return list(deduplicate_paths(zip_paths))


def find_xml_files(import_paths: T.Sequence[Path]) -> T.List[Path]:
    xml_paths: T.List[Path] = []
    for path in import_paths:
        if path.is_dir():
            # XML could be hidden in hidden folders
            # for example: exiftool -progress -w! /tmp/exiftool_outputs/%d%f.xml -r -n -ee -api LargeFileSupport=1 -X /path/to/.hidden_dirs/images/example.jpg
            # The XML output will be /tmp/exiftool_outputs/path/to/.hidden_dirs/images/example.jpg
            xml_paths.extend(
                file
                for file in iterate_files(path, recursive=True, follow_hidden_dirs=True)
                if file.suffix.lower() in [".xml"]
            )
        else:
            if path.suffix.lower() in [".xml"]:
                xml_paths.append(path)
    return list(deduplicate_paths(xml_paths))


def get_file_size(path: Path) -> int:
    return os.path.getsize(path)
