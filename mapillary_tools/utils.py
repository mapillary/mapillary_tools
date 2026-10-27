# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import typing as T
from pathlib import Path


# Use "hashlib._Hash" instead of hashlib._Hash because:
# AttributeError: module 'hashlib' has no attribute '_Hash'
def md5sum_fp(fp: T.IO[bytes], md5: "hashlib._Hash | None" = None) -> "hashlib._Hash":
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
        ".36p",
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


def sanitize_serial(s: str | None) -> str | None:
    """
    Sanitize a serial number by removing all non-alphanumeric characters.
    Returns None if the input is None or if the result is empty after cleaning.
    """
    if s is None:
        return None
    cleaned = "".join(c for c in s if c.isalnum())
    return cleaned if cleaned else None


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
    image_paths: T.Iterable[Path], video_paths: T.Iterable[Path]
) -> dict[Path, list[Path]]:
    """
    The samples of each video among the images, but those that could be of
    several videos of the same name (see find_image_samples)
    """
    samples_by_video, _ = find_image_samples(image_paths, video_paths)
    return samples_by_video


def find_image_samples(
    image_paths: T.Iterable[Path], video_paths: T.Iterable[Path]
) -> tuple[dict[Path, list[Path]], dict[Path, list[Path]]]:
    """
    Find the samples of each video among the images. sample_video() names the
    samples of a video after it, in a folder named after it, at the path of the
    video relative to the folder of videos it samples (e.g. the samples of
    VIDEOS/x/clip.mp4 are OUT/x/clip.mp4/clip_0_000001.jpg, ...).

    Videos of the same name in different folders are told apart by their paths
    relative to the deepest folder that holds them all: the folder of a sample
    ends with the path of its video, the longest of them if several match. A
    sample whose folder ends with none of them, which could be of any of them,
    is a sample of none.

    Returns the samples of each video, and the videos that each sample that
    could be of several videos could be of.

    >>> images = [
    ...     Path("OUT/x/clip.mp4/clip_0_000001.jpg"),
    ...     Path("OUT/y/clip.mp4/clip_0_000001.jpg"),
    ...     Path("OUT/clip.mp4/clip_0_000001.jpg"),
    ...     Path("OUT/x/clip.mp4/other.jpg"),
    ... ]
    >>> videos = [Path("VIDEOS/x/clip.mp4"), Path("VIDEOS/y/clip.mp4")]
    >>> samples, ambiguous = find_image_samples(images, videos)
    >>> {video.as_posix(): [p.as_posix() for p in paths] for video, paths in samples.items()}
    {'VIDEOS/x/clip.mp4': ['OUT/x/clip.mp4/clip_0_000001.jpg'], 'VIDEOS/y/clip.mp4': ['OUT/y/clip.mp4/clip_0_000001.jpg']}
    >>> {image.as_posix(): [p.as_posix() for p in paths] for image, paths in ambiguous.items()}
    {'OUT/clip.mp4/clip_0_000001.jpg': ['VIDEOS/x/clip.mp4', 'VIDEOS/y/clip.mp4']}
    """
    videos = list(deduplicate_paths(video_paths))
    # Absolute with their symbolic links kept, as sample_video() names the
    # folders of the videos after the paths it was given
    absolute_videos = [Path(os.path.abspath(video)) for video in videos]
    try:
        root: Path | None = (
            Path(os.path.commonpath([video.parent for video in absolute_videos]))
            if absolute_videos
            else None
        )
    except ValueError:
        # On different drives
        root = None

    # The videos of each name, with their paths relative to the root
    videos_by_name: dict[str, list[tuple[Path, tuple[str, ...]]]] = {}
    for video, absolute_video in zip(videos, absolute_videos):
        if root is None:
            relative_parts: tuple[str, ...] = (absolute_video.name,)
        else:
            relative_parts = absolute_video.relative_to(root).parts
        videos_by_name.setdefault(absolute_video.name, []).append(
            (video, relative_parts)
        )

    samples_by_video: dict[Path, list[Path]] = {}
    ambiguous: dict[Path, list[Path]] = {}
    for image_path in image_paths:
        # Made absolute first, to walk the path upwards: the folder of a
        # sample is named after its video
        sample_dir = Path(os.path.abspath(image_path)).parent
        candidates = videos_by_name.get(sample_dir.name, [])
        stem, _ = os.path.splitext(sample_dir.name)
        if not candidates or not image_path.name.startswith(stem + "_"):
            continue

        matching = [
            (video, parts)
            for video, parts in candidates
            if sample_dir.parts[-len(parts) :] == parts
        ]
        if matching:
            longest = max(len(parts) for _, parts in matching)
            best = [video for video, parts in matching if len(parts) == longest]
            if 1 < len(best):
                # Told apart by no path, as videos on different drives
                ambiguous[image_path] = best
                continue
            video = best[0]
        elif len(candidates) == 1:
            video, _ = candidates[0]
        else:
            ambiguous[image_path] = [video for video, _ in candidates]
            continue
        samples_by_video.setdefault(video, []).append(image_path)

    return samples_by_video, ambiguous


def deduplicate_paths(paths: T.Iterable[Path]) -> T.Generator[Path, None, None]:
    resolved_paths: set[Path] = set()
    for p in paths:
        resolved = p.resolve()
        if resolved not in resolved_paths:
            resolved_paths.add(resolved)
            yield p


def find_images(
    import_paths: T.Iterable[Path],
    skip_subfolders: bool = False,
) -> list[Path]:
    image_paths: list[Path] = []
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
    import_paths: T.Iterable[Path],
    skip_subfolders: bool = False,
) -> list[Path]:
    video_paths: list[Path] = []
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
    import_paths: T.Iterable[Path],
    skip_subfolders: bool = False,
) -> list[Path]:
    zip_paths: list[Path] = []
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


def find_xml_files(import_paths: T.Iterable[Path]) -> list[Path]:
    xml_paths: list[Path] = []
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


def get_file_size_quietly(path: Path) -> int:
    try:
        return get_file_size(path)
    except Exception:
        return 0


TMapIn = T.TypeVar("TMapIn")
TMapOut = T.TypeVar("TMapOut")


def mp_map_maybe(
    func: T.Callable[[TMapIn], TMapOut],
    iterable: T.Iterable[TMapIn],
    num_processes: int | None = None,
) -> T.Generator[TMapOut, None, None]:
    if num_processes is None:
        max_workers = None
        disable_multiprocessing = False
    else:
        max_workers = max(num_processes, 1)
        disable_multiprocessing = num_processes <= 0

    if disable_multiprocessing:
        yield from map(func, iterable)
    else:
        app_logger = logging.getLogger(get_app_name())
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=configure_logger,
            initargs=(None, app_logger.getEffectiveLevel()),
        ) as executor:
            yield from executor.map(func, iterable)


def configure_logger(
    logger: logging.Logger | None = None, level: int = logging.INFO
) -> logging.Logger:
    """Configure logging in each worker process"""
    if logger is None:
        # Root logger if app name is ""
        logger = logging.getLogger(get_app_name())

    logger.setLevel(level)

    # A worker process that is forked inherits the handler of its parent,
    # and a second one would print each of its messages twice
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d - %(levelname)-7s - %(message)s",
        datefmt="%H:%M:%S",
    )
    handler: logging.Handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger


def get_app_name() -> str:
    if __name__:
        return __name__.split(".")[0]
    else:
        # Rare case
        return ""
