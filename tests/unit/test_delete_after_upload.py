# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import itertools
import logging
import os
import sys
import typing as T
from pathlib import Path

import pytest
import requests
from mapillary_tools import (
    api_v4,
    constants,
    geo,
    types,
    upload,
    upload_api_v4,
    uploader,
)
from mapillary_tools.commands import __main__ as commands
from mapillary_tools.commands import (
    process_and_upload as process_and_upload_command,
    upload as upload_command,
)

from .test_uploader import _write_empty_mp4

TEST_IMAGE_DIR = Path(__file__).parent.parent.joinpath("data", "images")
USER_ITEMS: T.Any = {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"}


class _Server:
    """
    Stands in for Mapillary: stores the uploads in a local folder, as a dry
    run does, and finishes them with a cluster ID
    """

    def __init__(self, upload_path: Path):
        self.upload_path = upload_path
        # The response body of finish_upload
        self.finish_body = b'{"cluster_id": "123"}'
        # Which of these files existed when each upload was finished
        self.watched_paths: list[Path] = []
        self.existing_at_finish: list[list[Path]] = []

    def finish_upload(self, user_session, file_handle, cluster_filetype, **kwargs):
        self.existing_at_finish.append(
            [path for path in self.watched_paths if path.exists()]
        )
        resp = requests.Response()
        resp.status_code = 200
        resp.reason = "OK"
        resp._content = self.finish_body
        resp.url = "https://graph.mapillary.com/finish_upload"
        resp.request = requests.Request("POST", resp.url).prepare()
        return resp


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Server:
    upload_path = tmp_path / "uploads"
    upload_path.mkdir()
    server = _Server(upload_path)

    def _create_upload_service(self, user_session, session_key):
        return upload_api_v4.FakeUploadService(
            user_session, session_key, upload_path=upload_path
        )

    monkeypatch.setattr(
        uploader.Uploader, "_create_upload_service", _create_upload_service
    )
    monkeypatch.setattr(api_v4, "finish_upload", server.finish_upload)
    # Where a dry run uploads to
    monkeypatch.setenv("MAPILLARY_UPLOAD_ENDPOINT", str(upload_path))
    monkeypatch.setattr(
        constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(tmp_path / "history")
    )
    monkeypatch.setattr(constants, "UPLOAD_CACHE_DIR", str(tmp_path / "upload_cache"))
    monkeypatch.setattr(constants, "MAPILLARY_DISABLE_API_LOGGING", True)
    return server


def _uploads(server: _Server) -> list[str]:
    return sorted(path.name for path in server.upload_path.iterdir() if path.is_file())


# Tells the images apart
_image_numbers = itertools.count(1)


def _images(image_dir: Path, sequence_uuid: str, count: int) -> list[Path]:
    """
    Images that are different files, so that none is found in the upload
    history as another one
    """
    image_dir.mkdir(exist_ok=True)
    data = TEST_IMAGE_DIR.joinpath("DSC00001.JPG").read_bytes()
    image_paths = []
    for idx in range(count):
        image = bytearray(data)
        # A byte of the image data
        image[-10] = next(_image_numbers) % 250 + 1
        image_path = image_dir / f"{sequence_uuid}_{idx}.jpg"
        image_path.write_bytes(bytes(image))
        image_paths.append(image_path)
    return image_paths


def _image_metadatas(
    image_paths: T.Sequence[Path], sequence_uuid: str
) -> list[types.Metadata]:
    return [
        types.ImageMetadata(
            filename=image_path,
            lat=58.5927694 + idx * 0.0001,
            lon=16.1840944,
            alt=None,
            angle=None,
            time=1613222681.0 + idx,
            MAPSequenceUUID=sequence_uuid,
            filesize=image_path.stat().st_size,
        )
        for idx, image_path in enumerate(image_paths)
    ]


def _video_metadata(video_path: Path, timescale: int = 60000) -> types.VideoMetadata:
    # Videos of other timescales are different files
    _write_empty_mp4(video_path, timescale)
    return types.VideoMetadata(
        video_path,
        types.FileType.VIDEO,
        points=[
            geo.Point(time=0.0, lat=1, lon=1, alt=None, angle=None),
            geo.Point(time=1.0, lat=1.0001, lon=1, alt=None, angle=None),
        ],
    )


def test_deletes_the_images_of_a_sequence_after_the_sequence_finished(
    tmp_path: Path, server: _Server, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO)
    image_dir = tmp_path / "images"
    sequence_a = _images(image_dir, "a", 3)
    sequence_b = _images(image_dir, "b", 2)
    sidecars = [image_dir / "track.gpx", image_dir / "mapillary_image_description.json"]
    for sidecar in sidecars:
        sidecar.write_text("not uploaded")
    server.watched_paths = [*sequence_a, *sequence_b]

    upload.upload(
        image_dir,
        USER_ITEMS,
        num_upload_workers=2,
        _metadatas_from_process=[
            *_image_metadatas(sequence_a, "a"),
            *_image_metadatas(sequence_b, "b"),
        ],
        delete_after_upload=True,
    )

    # No image is deleted before its whole sequence finished, and the images
    # of a finished sequence are deleted before the next sequence finishes
    assert server.existing_at_finish == [
        [*sequence_a, *sequence_b],
        sequence_b,
    ]
    assert [path for path in [*sequence_a, *sequence_b] if path.exists()] == []
    assert all(sidecar.exists() for sidecar in sidecars)
    assert (
        "Files will be automatically deleted after they are uploaded "
        "(--delete_after_upload). If something goes wrong, the original files "
        "cannot be restored." in caplog.text
    )
    for path in [*sequence_a, *sequence_b]:
        assert f"Deleted the uploaded file {path}\n" in caplog.text
    assert "5 uploaded files deleted" in caplog.text


def test_deletes_videos_and_zip_files_after_their_uploads_finished(
    tmp_path: Path, server: _Server, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO)
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video_metadatas = [
        _video_metadata(video_dir / "a.mp4"),
        _video_metadata(video_dir / "b.mp4", 90000),
    ]
    gpx_path = video_dir / "a.gpx"
    gpx_path.write_text("not uploaded")
    zipped_images = _images(tmp_path / "zipped", "z", 2)
    zip_dir = tmp_path / "zips"
    uploader.ZipUploader.zip_images(
        T.cast(T.List[types.ImageMetadata], _image_metadatas(zipped_images, "z")),
        zip_dir,
    )
    [zip_path] = zip_dir.glob("*.zip")
    video_paths = [metadata.filename for metadata in video_metadatas]
    server.watched_paths = [*video_paths, zip_path]

    upload.upload(
        [video_dir, zip_dir],
        USER_ITEMS,
        num_upload_workers=1,
        _metadatas_from_process=video_metadatas,
        delete_after_upload=True,
    )

    # Each file is deleted once its own upload finished
    assert server.existing_at_finish == [
        [*video_paths, zip_path],
        [video_paths[1], zip_path],
        [zip_path],
    ]
    assert not any(path.exists() for path in [*video_paths, zip_path])
    # Not uploaded themselves
    assert gpx_path.exists()
    assert all(path.exists() for path in zipped_images)
    assert "3 uploaded files deleted" in caplog.text


def test_keeps_the_images_of_a_sequence_that_failed(
    tmp_path: Path,
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    image_dir = tmp_path / "images"
    sequence_a = _images(image_dir, "a", 2)
    sequence_b = _images(image_dir, "b", 1)

    # The second image of sequence a fails, after the first one was uploaded
    dumped: list[Path] = []
    dump_image_bytes = uploader.CachedImageUploader.dump_image_bytes

    def _dump_image_bytes(metadata: types.ImageMetadata) -> bytes:
        if metadata.filename == sequence_a[1]:
            raise uploader.ExifError("Broken image", metadata.filename)
        dumped.append(metadata.filename)
        return dump_image_bytes(metadata)

    monkeypatch.setattr(
        uploader.CachedImageUploader,
        "dump_image_bytes",
        staticmethod(_dump_image_bytes),
    )

    upload.upload(
        image_dir,
        USER_ITEMS,
        num_upload_workers=1,
        _metadatas_from_process=[
            *_image_metadatas(sequence_a, "a"),
            *_image_metadatas(sequence_b, "b"),
        ],
        delete_after_upload=True,
    )

    assert sequence_a[0] in dumped
    assert "ExifError: Broken image" in caplog.text
    assert all(path.exists() for path in sequence_a)
    assert not sequence_b[0].exists()
    assert "1 uploaded files deleted" in caplog.text


@pytest.mark.parametrize("file_type", ["image", "video"])
@pytest.mark.parametrize(
    "finish_body", [b"{}", b'{"cluster_id": null, "organization_id": null}']
)
def test_keeps_the_files_when_the_upload_is_not_finished(
    tmp_path: Path, server: _Server, file_type: str, finish_body: bytes
):
    import_dir = tmp_path / "import"
    if file_type == "image":
        paths = _images(import_dir, "a", 2)
        metadatas = _image_metadatas(paths, "a")
    else:
        import_dir.mkdir()
        paths = [import_dir / "video.mp4"]
        metadatas = [_video_metadata(paths[0])]
    server.finish_body = finish_body
    server.watched_paths = paths

    with pytest.raises(api_v4.HTTPContentError):
        upload.upload(
            import_dir,
            USER_ITEMS,
            num_upload_workers=1,
            _metadatas_from_process=metadatas,
            delete_after_upload=True,
        )

    # Uploaded, but Mapillary did not confirm it
    assert _uploads(server)
    assert server.existing_at_finish == [paths]
    assert all(path.exists() for path in paths)


@pytest.mark.parametrize(
    "dry_run, nofinish, reason",
    [
        (True, False, "nothing is uploaded to Mapillary with --dry_run"),
        (False, True, "the uploads are not finished with --nofinish"),
    ],
)
def test_deletes_nothing_in_a_dry_run_or_without_finishing(
    tmp_path: Path,
    server: _Server,
    caplog: pytest.LogCaptureFixture,
    dry_run: bool,
    nofinish: bool,
    reason: str,
):
    caplog.set_level(logging.INFO)
    image_dir = tmp_path / "images"
    image_paths = _images(image_dir, "a", 2)
    video_path = image_dir / "video.mp4"

    upload.upload(
        image_dir,
        USER_ITEMS,
        num_upload_workers=1,
        _metadatas_from_process=[
            *_image_metadatas(image_paths, "a"),
            _video_metadata(video_path),
        ],
        dry_run=dry_run,
        nofinish=nofinish,
        delete_after_upload=True,
    )

    assert _uploads(server)
    assert all(path.exists() for path in image_paths)
    assert video_path.exists()
    assert (
        f"No files will be deleted, despite --delete_after_upload: {reason}"
        in caplog.text
    )
    assert "Files will be automatically deleted" not in caplog.text
    assert "Deleted the uploaded file" not in caplog.text


def test_keeps_the_files_skipped_as_uploaded_before(
    tmp_path: Path, server: _Server, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO)
    image_dir = tmp_path / "images"
    sequence_a = _images(image_dir, "a", 2)
    sequence_b = _images(image_dir, "b", 2)
    video_path = image_dir / "video.mp4"
    metadatas = [
        *_image_metadatas(sequence_a, "a"),
        *_image_metadatas(sequence_b, "b"),
        _video_metadata(video_path),
    ]

    def _upload(import_path, **kwargs):
        upload.upload(
            import_path,
            USER_ITEMS,
            num_upload_workers=1,
            _metadatas_from_process=metadatas,
            **kwargs,
        )

    # Sequence a and the video were uploaded before, without deleting them
    _upload([*sequence_a, video_path])
    assert all(path.exists() for path in [*sequence_a, video_path])

    caplog.clear()
    _upload(image_dir, delete_after_upload=True)

    assert "UploadedAlready: Skipping sequence_a, already uploaded" in caplog.text
    assert "UploadedAlready: Skipping video.mp4, already uploaded" in caplog.text
    assert all(path.exists() for path in [*sequence_a, video_path])
    assert not any(path.exists() for path in sequence_b)
    assert "2 uploaded files deleted" in caplog.text

    # Uploaded again in this run, so deleted
    caplog.clear()
    _upload(image_dir, delete_after_upload=True, reupload=True)

    assert not any(path.exists() for path in [*sequence_a, video_path])
    assert "3 uploaded files deleted" in caplog.text


def test_a_file_that_cannot_be_deleted_only_warns(
    tmp_path: Path,
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    image_dir = tmp_path / "images"
    image_paths = _images(image_dir, "a", 3)
    video_path = image_dir / "video.mp4"
    metadatas = [*_image_metadatas(image_paths, "a"), _video_metadata(video_path)]

    # One image cannot be deleted, and another one is gone already
    protected_path, gone_path = image_paths[1], image_paths[2]
    errors: dict[Path, OSError] = {
        protected_path: PermissionError(13, "Permission denied", str(protected_path)),
        gone_path: FileNotFoundError(2, "No such file or directory", str(gone_path)),
    }
    remove = os.remove

    def _remove(path, *args, **kwargs):
        if Path(path) in errors:
            raise errors[Path(path)]
        return remove(path, *args, **kwargs)

    monkeypatch.setattr(os, "remove", _remove)

    upload.upload(
        image_dir,
        USER_ITEMS,
        num_upload_workers=1,
        _metadatas_from_process=metadatas,
        delete_after_upload=True,
    )

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    # Each warning names the file and the error
    for path, error in errors.items():
        assert f"Failed to delete the uploaded file {path}: {error}" in warnings
    assert "2 uploaded files could not be deleted (see the warnings above)" in warnings
    # The uploads carry on
    assert protected_path.exists()
    assert not image_paths[0].exists()
    assert not video_path.exists()
    assert "1 sequences uploaded" in caplog.text
    assert "1 video uploaded" in caplog.text
    assert "2 uploaded files deleted" in caplog.text


def _parse(
    monkeypatch: pytest.MonkeyPatch, command_module, argv: list[str]
) -> dict[str, T.Any]:
    parsed: dict[str, T.Any] = {}
    monkeypatch.setattr(
        command_module.Command, "run", lambda self, vars_args: parsed.update(vars_args)
    )
    monkeypatch.setattr(sys, "argv", ["mapillary_tools", *argv])
    commands.main()
    return parsed


@pytest.mark.parametrize("command_module", [upload_command, process_and_upload_command])
def test_delete_after_upload_is_off_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command_module
):
    name = command_module.Command.name
    assert (
        _parse(monkeypatch, command_module, [name, str(tmp_path)])[
            "delete_after_upload"
        ]
        is False
    )
    assert (
        _parse(
            monkeypatch, command_module, [name, str(tmp_path), "--delete_after_upload"]
        )["delete_after_upload"]
        is True
    )


def test_video_process_and_upload_rejects_delete_after_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mapillary_tools",
            "video_process_and_upload",
            str(tmp_path),
            "--delete_after_upload",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        commands.main()
    assert exc_info.value.code == 2
    assert "unrecognized arguments: --delete_after_upload" in capsys.readouterr().err
