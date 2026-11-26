# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import io
import json
import logging
import os
import sys
import typing as T
from pathlib import Path

import pytest

from mapillary_tools import exceptions, types, upload, utils


def _image(filename: Path) -> types.ImageMetadata:
    return types.ImageMetadata(
        filename=filename,
        lat=1.0,
        lon=2.0,
        alt=None,
        angle=None,
        time=1.0,
        MAPSequenceUUID="0",
    )


def _video(filename: Path) -> types.VideoMetadata:
    return types.VideoMetadata(
        filename=filename, filetype=types.FileType.CAMM, points=[]
    )


def _find_upload_candidates_by_file_type(
    metadatas: T.Sequence[types.Metadata],
    import_paths: T.Sequence[Path],
    skip_subfolders: bool,
):
    """How the candidates were found before: one scan per file type"""
    resolved_images = {
        p.resolve()
        for p in utils.find_images(import_paths, skip_subfolders=skip_subfolders)
    }
    resolved_videos = {
        p.resolve()
        for p in utils.find_videos(import_paths, skip_subfolders=skip_subfolders)
    }
    return upload._UploadCandidates(
        [
            m
            for m in metadatas
            if isinstance(m, types.ImageMetadata)
            and m.filename.resolve() in resolved_images
        ],
        [
            m
            for m in metadatas
            if isinstance(m, types.VideoMetadata)
            and m.filename.resolve() in resolved_videos
        ],
        [
            p
            for p in utils.find_zipfiles(import_paths, skip_subfolders=skip_subfolders)
            if not p.name.startswith("._")
        ],
    )


@pytest.fixture
def capture_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "capture"
    for name in [
        "a.jpg",
        "b.JPG",
        "c.mp4",
        "d.zip",
        "notes.txt",
        ".hidden.jpg",
        "sub/e.jpg",
        "sub/f.mov",
        "sub/g.zip",
        ".hidden_folder/h.jpg",
    ]:
        root.joinpath(name).parent.mkdir(parents=True, exist_ok=True)
        root.joinpath(name).touch()
    (tmp_path / "elsewhere.jpg").touch()
    monkeypatch.chdir(tmp_path)
    return root


def _capture_metadatas(root: Path) -> list[types.Metadata]:
    return [
        _image(root / "sub" / "e.jpg"),
        _image(root / "b.JPG"),
        _video(root / "sub" / "f.mov"),
        _image(root / "a.jpg"),
        _video(root / "c.mp4"),
        # Under the import path, but not found by a scan
        _image(root / ".hidden.jpg"),
        _image(root / ".hidden_folder" / "h.jpg"),
        # Not under the import path
        _image(root.parent / "elsewhere.jpg"),
        # A video with an image name is not uploaded as a video
        _video(root / "a.jpg"),
    ]


@pytest.mark.parametrize("skip_subfolders", [False, True])
def test_find_upload_candidates(capture_tree: Path, skip_subfolders: bool):
    metadatas = _capture_metadatas(capture_tree)

    candidates = upload._find_upload_candidates(
        metadatas, [capture_tree], skip_subfolders=skip_subfolders
    )

    if skip_subfolders:
        assert candidates == upload._UploadCandidates(
            [metadatas[1], metadatas[3]],
            [metadatas[4]],
            [capture_tree / "d.zip"],
        )
    else:
        # In the order of the metadatas
        assert candidates == upload._UploadCandidates(
            [metadatas[0], metadatas[1], metadatas[3]],
            [metadatas[2], metadatas[4]],
            [capture_tree / "d.zip", capture_tree / "sub" / "g.zip"],
        )
    assert candidates == _find_upload_candidates_by_file_type(
        metadatas, [capture_tree], skip_subfolders=skip_subfolders
    )


def test_find_upload_candidates_once_from_overlapping_paths(capture_tree: Path):
    metadatas = _capture_metadatas(capture_tree)
    import_paths = [
        # Relative to the working directory
        Path("capture"),
        capture_tree / "sub" / ".." / "a.jpg",
        capture_tree / "sub",
        capture_tree / "sub" / "g.zip",
        # Hidden, but named
        capture_tree / ".hidden.jpg",
    ]
    if not sys.platform.startswith("win"):
        (capture_tree.parent / "linked_capture").symlink_to(capture_tree)
        (capture_tree.parent / "linked_image.jpg").symlink_to(
            capture_tree.parent / "elsewhere.jpg"
        )
        import_paths += [
            capture_tree.parent / "linked_capture",
            capture_tree.parent / "linked_image.jpg",
        ]

    candidates = upload._find_upload_candidates(
        metadatas, import_paths, skip_subfolders=False
    )

    image_metadatas = [metadatas[0], metadatas[1], metadatas[3], metadatas[5]]
    if not sys.platform.startswith("win"):
        # Found through the link to it
        image_metadatas.append(metadatas[7])
    assert candidates == upload._UploadCandidates(
        image_metadatas,
        [metadatas[2], metadatas[4]],
        [Path("capture") / "d.zip", Path("capture") / "sub" / "g.zip"],
    )
    assert candidates == _find_upload_candidates_by_file_type(
        metadatas, import_paths, skip_subfolders=False
    )


@pytest.mark.skipif(
    sys.platform.startswith("win") or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="Folder permissions do not apply on Windows or to root",
)
def test_find_upload_candidates_in_a_folder_that_cannot_be_searched(
    capture_tree: Path,
):
    metadatas = _capture_metadatas(capture_tree)
    folder = capture_tree / "sub"
    # Listed, but its files cannot be looked at
    folder.chmod(0o600)
    try:
        candidates = upload._find_upload_candidates(
            metadatas, [capture_tree], skip_subfolders=False
        )
        expected = _find_upload_candidates_by_file_type(
            metadatas, [capture_tree], skip_subfolders=False
        )
    finally:
        folder.chmod(0o700)

    assert candidates == expected
    assert [m.filename for m in candidates.image_metadatas] == [
        folder / "e.jpg",
        capture_tree / "b.JPG",
        capture_tree / "a.jpg",
    ]


def test_find_upload_candidates_skips_import_paths_not_found(
    capture_tree: Path, caplog: pytest.LogCaptureFixture
):
    metadatas = _capture_metadatas(capture_tree)
    # Processed, then deleted
    (capture_tree / "b.JPG").unlink()
    (capture_tree / "sub" / "f.mov").unlink()
    import_paths = [
        capture_tree / "a.jpg",
        capture_tree / "b.JPG",
        capture_tree / "c.mp4",
        capture_tree / "sub" / "f.mov",
        capture_tree / "deleted_folder",
        capture_tree / "d.zip",
    ]

    candidates = upload._find_upload_candidates(
        metadatas, import_paths, skip_subfolders=False
    )

    missing_paths = (
        capture_tree / "b.JPG",
        capture_tree / "sub" / "f.mov",
        capture_tree / "deleted_folder",
    )
    assert candidates == upload._UploadCandidates(
        [metadatas[3]], [metadatas[4]], [capture_tree / "d.zip"], missing_paths
    )
    found_paths = [p for p in import_paths if p.exists()]
    assert candidates._replace(
        missing_import_paths=()
    ) == _find_upload_candidates_by_file_type(
        metadatas, found_paths, skip_subfolders=False
    )
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert errors == [
        f"Skipping {path}: import file or directory not found" for path in missing_paths
    ]


@pytest.mark.skipif(
    sys.platform.startswith("win") or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="Folder permissions do not apply on Windows or to root",
)
def test_find_upload_candidates_skips_import_files_that_cannot_be_looked_at(
    capture_tree: Path,
):
    metadatas = _capture_metadatas(capture_tree)
    folder = capture_tree / "sub"
    import_paths = [capture_tree / "a.jpg", folder / "e.jpg", folder / "f.mov"]
    # Listed, but its files cannot be looked at
    folder.chmod(0o600)
    try:
        normalized_paths = upload._normalize_import_paths(import_paths)
        candidates = upload._find_upload_candidates(
            metadatas, normalized_paths, skip_subfolders=False
        )
    finally:
        folder.chmod(0o700)

    assert normalized_paths == import_paths
    assert candidates == upload._UploadCandidates(
        [metadatas[3]], [], [], (folder / "e.jpg", folder / "f.mov")
    )


def test_normalize_import_paths_found_or_not(tmp_path: Path):
    found = tmp_path / "found.jpg"
    found.touch()
    folder = tmp_path / "folder"
    folder.mkdir()
    deleted = tmp_path / "deleted.jpg"

    # Kept to look for the files to upload, which skips those not found
    assert upload._normalize_import_paths([deleted, found, folder, found]) == [
        deleted,
        found,
        folder,
    ]

    # Nothing to upload: the error names every import path
    with pytest.raises(exceptions.MapillaryFileNotFoundError) as ex:
        upload._normalize_import_paths([deleted, tmp_path / "deleted_folder"])
    assert str(ex.value) == (
        "None of the 2 import files or directories was found: "
        f"{deleted}, {tmp_path / 'deleted_folder'}"
    )
    with pytest.raises(exceptions.MapillaryFileNotFoundError) as ex:
        upload._normalize_import_paths(deleted)
    assert str(ex.value) == f"Import file or directory not found: {deleted}"


@pytest.mark.parametrize(
    "missing_count, expected",
    [
        (0, None),
        (1, "Skipped 1 import path not found"),
        (2, "Skipped 2 import paths not found"),
    ],
)
def test_upload_summary_counts_import_paths_not_found(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    missing_count: int,
    expected: T.Optional[str],
):
    missing_paths = [tmp_path / f"deleted_{idx}.jpg" for idx in range(missing_count)]

    with caplog.at_level(logging.INFO):
        upload._show_upload_summary([], [], missing_import_paths=missing_paths)

    skipped = [
        r.getMessage() for r in caplog.records if "import path" in r.getMessage()
    ]
    assert skipped == ([] if expected is None else [expected])


def test_find_upload_candidates_skips_apple_double_zip(capture_tree: Path):
    apple_double = capture_tree / "._d.zip"
    apple_double.touch()

    candidates = upload._find_upload_candidates([], [apple_double], False)

    assert candidates == upload._UploadCandidates([], [], [])


def _write_desc_file(path: Path, descs: list) -> str:
    path.write_text(json.dumps(descs))
    return str(path)


def test_load_descs_from_desc_path(tmp_path: Path):
    image = _image(tmp_path / "a.jpg")
    video = _video(tmp_path / "c.mp4")
    desc_path = _write_desc_file(
        tmp_path / "descs.json",
        [
            upload.DescriptionJSONSerializer.as_desc(image),
            {"error": {"type": "Error", "message": "x"}, "filename": "b.jpg"},
            upload.DescriptionJSONSerializer.as_desc(video),
        ],
    )

    metadatas = upload._load_valid_metadatas_from_desc_path([tmp_path], desc_path)

    assert [type(m) for m in metadatas] == [types.ImageMetadata, types.VideoMetadata]
    assert [m.filename for m in metadatas] == [
        image.filename.resolve(),
        video.filename.resolve(),
    ]


def test_load_descs_from_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    image = _image(tmp_path / "a.jpg")
    data = json.dumps([upload.DescriptionJSONSerializer.as_desc(image)]).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))

    metadatas = upload._load_valid_metadatas_from_desc_path([tmp_path], "-")

    assert [m.filename for m in metadatas] == [image.filename.resolve()]


def test_load_descs_invalid(tmp_path: Path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("[{")
    with pytest.raises(exceptions.MapillaryInvalidDescriptionFile):
        upload._load_valid_metadatas_from_desc_path([tmp_path], str(bad_json))

    desc_path = _write_desc_file(
        tmp_path / "descs.json", [{"filename": "a.jpg", "filetype": "image"}]
    )
    with pytest.raises(exceptions.MapillaryMetadataValidationError):
        upload._load_valid_metadatas_from_desc_path([tmp_path], desc_path)

    with pytest.raises(exceptions.MapillaryFileNotFoundError):
        upload._load_valid_metadatas_from_desc_path(
            [tmp_path], str(tmp_path / "missing.json")
        )
