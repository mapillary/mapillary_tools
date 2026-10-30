# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import json
import typing as T
from pathlib import Path

from . import types, utils


PROCESS_REPORT_SCHEMA_VERSION = 1


class ProcessReportDetails(T.TypedDict):
    extension: str


class ProcessReportSkippedFile(T.TypedDict):
    filename: str
    category: T.Literal["unsupported"]
    reason_code: T.Literal["unsupported_format"]
    details: ProcessReportDetails


class ProcessReportWarning(T.TypedDict):
    filename: str
    # The class name of the warning, such as MapillaryGPXAlignmentWarning
    type: str
    message: str
    # The attributes of the warning, which its type defines
    vars: dict[str, T.Any]


class ProcessReport(T.TypedDict):
    schema_version: int
    discovered_file_count: int
    processed_file_count: int
    skipped_file_count: int
    skipped_files: list[ProcessReportSkippedFile]
    # What processing warned of about the files that it still processed
    warnings: list[ProcessReportWarning]


# These files can accompany capture media but are not themselves process inputs.
# Explicitly supplied files are never ignored, regardless of their name or suffix.
_IGNORED_DISCOVERED_EXTENSIONS = {
    ".exif",
    ".fit",
    ".gpx",
    ".json",
    ".kml",
    ".kmz",
    ".lrv",
    ".nmea",
    ".srt",
    ".tcx",
    ".thm",
    ".vtt",
    ".xml",
    ".xmp",
    ".zip",
}
_IGNORED_DISCOVERED_FILENAMES = {
    ".ds_store",
    "desktop.ini",
    "ehthumbs.db",
    "thumbs.db",
}
_IGNORED_DISCOVERED_DIRNAMES = {"__macosx"}


def _is_supported_process_file(path: Path) -> bool:
    # An AppleDouble file (._NAME), which macOS writes beside each file it
    # copies to a drive that cannot hold its metadata, has the extension of
    # that file but is no image or video. A folder scan never finds it, as it
    # is hidden
    if path.name.startswith("._"):
        return False
    return utils.is_image_file(path) or utils.is_video_file(path)


def _is_ignored_discovered_file(path: Path, import_root: Path) -> bool:
    if path.name.casefold() in _IGNORED_DISCOVERED_FILENAMES:
        return True
    if path.suffix.lower() in _IGNORED_DISCOVERED_EXTENSIONS:
        return True

    try:
        relative_parts = path.relative_to(import_root).parts[:-1]
    except ValueError:
        relative_parts = path.parts[:-1]
    return any(
        part.casefold() in _IGNORED_DISCOVERED_DIRNAMES for part in relative_parts
    )


def _unsupported_file(path: Path) -> ProcessReportSkippedFile:
    return {
        "filename": str(path.resolve()),
        "category": "unsupported",
        "reason_code": "unsupported_format",
        "details": {"extension": path.suffix.lower()},
    }


def build_process_report(
    import_path: Path | T.Sequence[Path],
    skip_subfolders: bool = False,
) -> ProcessReport:
    if isinstance(import_path, Path):
        import_paths = [import_path]
    else:
        import_paths = list(import_path)
    import_paths = list(utils.deduplicate_paths(import_paths))

    processed_paths: dict[Path, Path] = {}
    unsupported_paths: dict[Path, Path] = {}
    explicit_paths: set[Path] = set()

    # Explicit regular files take precedence over directory filtering. In
    # particular, explicitly selected hidden, system, and sidecar files must be
    # reported as unsupported instead of silently ignored.
    for path in import_paths:
        if not path.is_file():
            continue
        resolved = path.resolve()
        explicit_paths.add(resolved)
        if _is_supported_process_file(path):
            processed_paths[resolved] = path
        else:
            unsupported_paths[resolved] = path

    for import_root in (path for path in import_paths if path.is_dir()):
        discovered_paths = sorted(
            utils.iterate_files(import_root, recursive=not skip_subfolders),
            key=lambda path: str(path.resolve()),
        )
        for path in discovered_paths:
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in explicit_paths:
                continue
            if _is_supported_process_file(path):
                processed_paths[resolved] = path
            elif not _is_ignored_discovered_file(path, import_root):
                unsupported_paths[resolved] = path

    skipped_files = sorted(
        (_unsupported_file(path) for path in unsupported_paths.values()),
        key=lambda skipped: skipped["filename"],
    )
    processed_file_count = len(processed_paths)
    skipped_file_count = len(skipped_files)
    return {
        "schema_version": PROCESS_REPORT_SCHEMA_VERSION,
        "discovered_file_count": processed_file_count + skipped_file_count,
        "processed_file_count": processed_file_count,
        "skipped_file_count": skipped_file_count,
        "skipped_files": skipped_files,
        "warnings": [],
    }


def build_process_warnings(
    metadatas: T.Iterable[types.MetadataOrError],
) -> list[ProcessReportWarning]:
    """
    The warnings that geotagging gave the files it geotagged, by file name
    """
    warnings: list[ProcessReportWarning] = []
    for metadata in metadatas:
        if not isinstance(metadata, types.VideoMetadata):
            continue
        for warning in metadata.warnings:
            warnings.append(
                {
                    "filename": str(metadata.filename.resolve()),
                    "type": warning.__class__.__name__,
                    "message": str(warning),
                    "vars": dict(vars(warning)),
                }
            )
    # Stable, so that the warnings of a file stay in the order given
    return sorted(warnings, key=lambda warning: warning["filename"])


def write_process_report(path: Path, report: ProcessReport) -> None:
    with path.open("w", encoding="utf-8") as fp:
        json.dump(
            report,
            fp,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fp.write("\n")
