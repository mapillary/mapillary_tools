# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
import os
import typing as T
from pathlib import Path

import pytest
from mapillary_tools import constants, fingerprint, history, types, upload


def _uploaded_file(path: Path) -> history.UploadedFile:
    return history.UploadedFile(
        path, path.stat().st_size, fingerprint.fingerprint_file(path)
    )


class TestUploadedFiles:
    def test_written_files_are_read_back(self, tmp_path, monkeypatch):
        history_path = tmp_path / "history"
        monkeypatch.setattr(
            history.constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path)
        )
        first = tmp_path / "first.jpg"
        first.write_bytes(b"first image")
        second = tmp_path / "second.jpg"
        second.write_bytes(b"second image, longer")
        files = [_uploaded_file(first), _uploaded_file(second)]

        history.write_uploaded_files(
            files, {"version": "test"}, {"upload_end_time": 123.0}
        )

        [record_path] = history_path.glob(f"{history.UPLOADED_FILES_DIR}/*/*.json")
        record = json.loads(record_path.read_text())
        assert record["params"] == {"version": "test"}
        assert record["files"] == [
            {
                "filename": os.path.abspath(first),
                "filesize": len(b"first image"),
                "fingerprint": files[0].fingerprint,
            },
            {
                "filename": os.path.abspath(second),
                "filesize": len(b"second image, longer"),
                "fingerprint": files[1].fingerprint,
            },
        ]
        # No checksum record is written
        assert list(history_path.glob("*/*.json")) == []

        uploaded = history.read_uploaded_files()
        assert uploaded is not None
        assert uploaded.sizes == {len(b"first image"), len(b"second image, longer")}
        assert uploaded.uploaded_at == {
            files[0].fingerprint: 123.0,
            files[1].fingerprint: 123.0,
        }

    def test_find_reads_only_files_of_uploaded_sizes(self, tmp_path, monkeypatch):
        uploaded_path = tmp_path / "uploaded.mp4"
        uploaded_path.write_bytes(b"video A")
        uploaded = history.UploadedFiles()
        uploaded.add([_uploaded_file(uploaded_path)], 1.0)
        new_size = tmp_path / "new.mp4"
        new_size.write_bytes(b"a new video")
        same_size = tmp_path / "same-size.mp4"
        same_size.write_bytes(b"video B")

        reads: list[str] = []
        fingerprint_file = fingerprint.fingerprint_file

        def _fingerprint_file(path):
            reads.append(path.name)
            return fingerprint_file(path)

        monkeypatch.setattr(fingerprint, "fingerprint_file", _fingerprint_file)
        fingerprints: dict[Path, str] = {}

        assert uploaded.find(new_size, fingerprints) is None
        assert reads == []
        assert uploaded.find(same_size, fingerprints) is None
        assert uploaded.find(uploaded_path, fingerprints) is not None
        assert reads == ["same-size.mp4", "uploaded.mp4"]
        # Fingerprints computed are kept
        assert uploaded.find(uploaded_path, fingerprints) is not None
        assert reads == ["same-size.mp4", "uploaded.mp4"]
        assert set(fingerprints) == {same_size, uploaded_path}

    def test_add_keeps_the_latest_upload_time(self):
        file = history.UploadedFile(Path("video.mp4"), 1, "0" * 32)
        uploaded = history.UploadedFiles()
        uploaded.add([file], None)
        assert uploaded.uploaded_at == {"0" * 32: None}
        uploaded.add([file], 2.0)
        uploaded.add([file], 1.0)
        assert uploaded.uploaded_at == {"0" * 32: 2.0}

    def test_invalid_records_are_skipped(self, tmp_path, monkeypatch, caplog):
        history_path = tmp_path / "history"
        monkeypatch.setattr(
            history.constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path)
        )
        root = history_path / history.UPLOADED_FILES_DIR
        records = {
            "00/invalid-json.json": b"{",
            "01/not-utf8.json": b"\xff",
            "02/not-a-dict.json": b"[]",
            "03/no-files.json": json.dumps({"summary": {}}).encode(),
            "04/bad-entry.json": json.dumps(
                {"files": [{"filesize": "1", "fingerprint": "0" * 32}]}
            ).encode(),
            "05/bad-fingerprint.json": json.dumps(
                {"files": [{"filesize": 1, "fingerprint": "not one"}]}
            ).encode(),
            "06/valid.json": json.dumps(
                {
                    "summary": {"upload_end_time": "yesterday"},
                    "files": [
                        {"filename": "a.jpg", "filesize": 7, "fingerprint": "a" * 32}
                    ],
                }
            ).encode(),
        }
        for name, contents in records.items():
            root.joinpath(name).parent.mkdir(parents=True, exist_ok=True)
            root.joinpath(name).write_bytes(contents)

        with caplog.at_level("WARNING"):
            uploaded = history.read_uploaded_files()

        assert uploaded is not None
        assert uploaded.sizes == {7}
        assert uploaded.uploaded_at == {"a" * 32: None}
        for name in list(records)[:-1]:
            assert name.split("/")[1] in caplog.text

    def test_no_history(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history.constants, "MAPILLARY_UPLOAD_HISTORY_PATH", "")
        monkeypatch.chdir(tmp_path)
        assert history.read_uploaded_files() is None
        path = tmp_path / "video.mp4"
        path.write_bytes(b"video")
        history.write_uploaded_files([_uploaded_file(path)], {}, {})
        assert [p.name for p in tmp_path.iterdir()] == ["video.mp4"]

    def test_empty_history(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            history.constants,
            "MAPILLARY_UPLOAD_HISTORY_PATH",
            str(tmp_path / "history"),
        )
        uploaded = history.read_uploaded_files()
        assert uploaded == history.UploadedFiles()
        assert not (tmp_path / "history").exists()


TEST_IMAGE_DIR = Path(__file__).parent.parent.joinpath("data", "images")


def _write_record(summary: dict, *paths: Path) -> Path:
    files = [_uploaded_file(path) for path in paths]
    history.write_uploaded_files(files, {}, T.cast(history.JSONDict, summary))
    key = fingerprint.combine_fingerprints(file.fingerprint for file in files)
    return history._uploaded_files_dir() / key[:2] / f"{key[2:]}.json"


class TestUnfinishedUploads:
    # upload wrote a record with the cluster ID null when finish_upload
    # answered without one, as for an organization that the account is not a
    # member of: nothing was uploaded

    @pytest.fixture(autouse=True)
    def _history_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(tmp_path / "history")
        )

    def test_unfinished_record_is_not_read(self, tmp_path, caplog):
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"video")
        record_path = _write_record(
            {"cluster_id": None, "upload_end_time": 1.0}, video_path
        )

        with caplog.at_level("INFO"):
            uploaded = history.read_uploaded_files()

        assert uploaded == history.UploadedFiles()
        assert f"the upload in the history record {record_path} was not finished" in (
            caplog.text
        )
        assert "Invalid upload history record" not in caplog.text

    @pytest.mark.parametrize(
        "summary",
        [
            {"upload_end_time": 1.0},
            {"cluster_id": "123", "upload_end_time": 1.0},
            # Uploaded with --dry_run
            {"cluster_id": "0", "upload_end_time": 1.0},
        ],
    )
    def test_finished_record_is_read(self, tmp_path, summary: dict):
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"video")
        _write_record(summary, video_path)
        uploaded = history.read_uploaded_files()
        assert uploaded is not None
        assert uploaded.find(video_path) == fingerprint.fingerprint_file(video_path)

    def test_check_upload_history_ignores_unfinished_records(self, tmp_path):
        image_paths = [tmp_path / "first.jpg", tmp_path / "second.jpg"]
        metadatas = []
        for idx, image_path in enumerate(image_paths):
            image_path.write_bytes(f"image {idx}".encode())
            metadatas.append(
                types.ImageMetadata(
                    filename=image_path,
                    lat=1.0,
                    lon=2.0,
                    alt=None,
                    angle=None,
                    time=float(idx),
                    MAPSequenceUUID="sequence",
                )
            )

        def check() -> dict:
            [result] = upload.check_upload_history(
                image_paths, _metadatas_from_process=metadatas
            )
            return result

        _write_record({"cluster_id": None}, *image_paths)
        result = check()
        assert result["already_uploaded"] is False
        assert result["already_uploaded_filenames"] == []

        _write_record({"cluster_id": "123"}, *image_paths)
        assert check()["already_uploaded"] is True

    def test_upload_uploads_unfinished_upload_again(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            constants, "MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN", True
        )
        upload_path = tmp_path / "uploads"
        upload_path.mkdir()
        monkeypatch.setenv("MAPILLARY_UPLOAD_ENDPOINT", str(upload_path))

        image_dir = tmp_path / "images"
        image_dir.mkdir()
        metadatas: list[types.MetadataOrError] = []
        for idx, name in enumerate(["DSC00001.JPG", "DSC00497.JPG"]):
            image_path = image_dir / name
            image_path.write_bytes(TEST_IMAGE_DIR.joinpath(name).read_bytes())
            metadatas.append(
                types.ImageMetadata(
                    filename=image_path,
                    lat=58.5927694 + idx * 0.0001,
                    lon=16.1840944,
                    alt=None,
                    angle=None,
                    time=1613222680.0 + idx,
                    MAPSequenceUUID="sequence",
                    filesize=image_path.stat().st_size,
                )
            )

        def upload_images() -> None:
            upload.upload(
                image_dir,
                {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
                num_upload_workers=1,
                _metadatas_from_process=metadatas,
                dry_run=True,
            )

        upload_images()
        [record_path] = (tmp_path / "history").glob(
            f"{history.UPLOADED_FILES_DIR}/*/*.json"
        )

        def rewrite_summary(**summary) -> None:
            record = json.loads(record_path.read_text())
            record["summary"] = summary
            record_path.write_text(json.dumps(record))

        # Not finished: uploaded again, and the record replaced
        rewrite_summary(cluster_id=None, upload_end_time=1.0)
        upload_images()
        summary = json.loads(record_path.read_text())["summary"]
        assert summary["cluster_id"] == "0"
        assert summary["upload_end_time"] != 1.0

        # Written before 0.14.0, without a cluster ID: skipped as uploaded
        rewrite_summary(upload_end_time=1.0)
        upload_images()
        assert json.loads(record_path.read_text())["summary"] == {
            "upload_end_time": 1.0
        }
