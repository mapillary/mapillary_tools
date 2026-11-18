# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import contextlib
import json
import os
import random
import sqlite3
import sys
import typing as T
from pathlib import Path

import pytest
from mapillary_tools import constants, fingerprint, history, history_index


@pytest.fixture
def history_path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "history"
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(path))
    return path


def _file(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _record(summary: dict, *paths: Path) -> Path:
    """Record the files as one upload, as upload does, and return the record"""
    files = [
        history.UploadedFile(
            path, path.stat().st_size, fingerprint.fingerprint_file(path)
        )
        for path in paths
    ]
    history.write_uploaded_files(files, {}, T.cast(history.JSONDict, summary))
    key = fingerprint.combine_fingerprints(file.fingerprint for file in files)
    return history._uploaded_files_dir() / key[:2] / f"{key[2:]}.json"


def _index_path() -> Path:
    return history._uploaded_files_dir() / history_index.INDEX_FILENAME


def _connect() -> T.ContextManager[sqlite3.Connection]:
    return contextlib.closing(sqlite3.connect(_index_path()))


def _count(table: str) -> int:
    with _connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _open() -> history.UploadedFilesLookup:
    uploaded = history_index.open_uploaded_files()
    assert uploaded is not None
    return uploaded


def _count_record_reads(monkeypatch) -> list[str]:
    reads: list[str] = []
    read_record = history_index._read_record

    def _read_record(path: Path):
        reads.append(path.name)
        return read_record(path)

    monkeypatch.setattr(history_index, "_read_record", _read_record)
    return reads


def test_finds_what_the_records_hold(history_path, tmp_path):
    uploaded_image = _file(tmp_path / "uploaded.jpg", b"an uploaded image")
    other_image = _file(tmp_path / "other.jpg", b"another uploaded image")
    same_size = _file(tmp_path / "same-size.jpg", b"AN UPLOADED IMAGE")
    new_size = _file(tmp_path / "new.jpg", b"a new image")
    _record({"upload_end_time": 1.0}, uploaded_image)
    _record({"upload_end_time": 2.0}, uploaded_image, other_image)
    _record({"cluster_id": None, "upload_end_time": 3.0}, new_size)

    uploaded = _open()
    try:
        assert isinstance(uploaded, history_index.UploadedFilesIndex)
        for path in [uploaded_image, other_image]:
            assert uploaded.find(path) == fingerprint.fingerprint_file(path)
        assert uploaded.find(same_size) is None
        # In an unfinished upload: not taken as uploaded
        assert uploaded.find(new_size) is None
        # The latest upload
        assert uploaded.last_uploaded_at(
            fingerprint.fingerprint_file(uploaded_image)
        ) == pytest.approx(2.0)
        assert uploaded.last_uploaded_at("0" * 32) is None
    finally:
        uploaded.close()

    # As without the index
    scanned = history.read_uploaded_files()
    assert scanned is not None
    for path in [uploaded_image, other_image, same_size, new_size]:
        assert scanned.find(path) == (
            fingerprint.fingerprint_file(path)
            if path in [uploaded_image, other_image]
            else None
        )


def test_reads_only_the_records_added_or_changed_since(
    history_path, tmp_path, monkeypatch
):
    paths = [
        _file(tmp_path / f"video-{idx}.mp4", b"video %d" % idx) for idx in range(3)
    ]
    records = [_record({"upload_end_time": 1.0}, path) for path in paths[:2]]
    reads = _count_record_reads(monkeypatch)

    _open().close()
    assert sorted(reads) == sorted(record.name for record in records)

    # Unchanged: no record is read
    reads.clear()
    uploaded = _open()
    assert reads == []
    assert uploaded.find(paths[0]) is not None
    uploaded.close()

    # Added
    added = _record({"upload_end_time": 2.0}, paths[2])
    uploaded = _open()
    assert reads == [added.name]
    assert uploaded.find(paths[2]) is not None
    uploaded.close()

    # Changed: rewritten as an unfinished upload
    reads.clear()
    record = json.loads(records[0].read_text())
    record["summary"] = {"cluster_id": None, "upload_end_time": 1.0}
    records[0].write_text(json.dumps(record))
    uploaded = _open()
    assert reads == [records[0].name]
    assert uploaded.find(paths[0]) is None
    uploaded.close()

    # Deleted
    reads.clear()
    records[1].unlink()
    uploaded = _open()
    assert reads == []
    assert uploaded.find(paths[1]) is None
    assert uploaded.find(paths[2]) is not None
    uploaded.close()

    assert (_count("records"), _count("files")) == (2, 1)


def test_many_records_are_indexed_in_bulk(history_path, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(history_index, "_BULK_RECORD_COUNT", 3)
    paths = [
        _file(tmp_path / f"image-{idx}.jpg", b"image %d" % idx) for idx in range(5)
    ]
    for path in paths[:3]:
        _record({"upload_end_time": 1.0}, path)

    def indexes() -> list[str]:
        with _connect() as conn:
            return sorted(
                name
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'files_by_%'"
                )
            )

    expected = ["files_by_fingerprint", "files_by_record", "files_by_size"]
    _open().close()
    assert indexes() == expected

    # Fewer than are indexed: with the indexes in place
    for path in paths[3:5]:
        _record({"upload_end_time": 2.0}, path)
    monkeypatch.setattr(history_index, "_BULK_RECORD_COUNT", 2)
    caplog.set_level("INFO")
    caplog.clear()
    uploaded = _open()
    assert "Indexing" not in caplog.text
    assert indexes() == expected
    assert [uploaded.find(path) is not None for path in paths] == [True] * 5
    uploaded.close()


def test_invalid_records_are_warned_about_once(history_path, tmp_path, caplog):
    root = history._uploaded_files_dir()
    invalid = root / "00" / "invalid.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("{")
    video = _file(tmp_path / "video.mp4", b"video")
    _record({"upload_end_time": 1.0}, video)

    with caplog.at_level("WARNING"):
        uploaded = _open()
    assert "invalid.json" in caplog.text
    assert uploaded.find(video) is not None
    uploaded.close()

    caplog.clear()
    with caplog.at_level("WARNING"):
        _open().close()
    assert caplog.text == ""


def test_files_added_since_opened_are_found(history_path, tmp_path):
    _record({}, _file(tmp_path / "old.mp4", b"an old video"))
    video = _file(tmp_path / "video.mp4", b"a video")
    file = history.UploadedFile(
        video, video.stat().st_size, fingerprint.fingerprint_file(video)
    )

    uploaded = _open()
    assert uploaded.find(video) is None
    uploaded.add([file], 5.0)
    assert uploaded.find(video) == file.fingerprint
    assert uploaded.last_uploaded_at(file.fingerprint) == 5.0
    uploaded.close()


@pytest.mark.parametrize("damage", ["garbage", "other_version"])
def test_an_index_that_cannot_be_read_is_rebuilt(
    history_path, tmp_path, caplog, damage
):
    video = _file(tmp_path / "video.mp4", b"video")
    _record({"upload_end_time": 1.0}, video)
    _open().close()

    if damage == "garbage":
        _index_path().write_bytes(b"not a database" * 100)
    else:
        with _connect() as conn:
            conn.execute("DELETE FROM files")
            conn.execute("PRAGMA user_version = 99")
            conn.commit()

    with caplog.at_level("WARNING"):
        uploaded = _open()
    assert isinstance(uploaded, history_index.UploadedFilesIndex)
    assert uploaded.find(video) is not None
    uploaded.close()
    if damage == "garbage":
        assert "Rebuilding the upload history index" in caplog.text


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="file modes: not on Windows, nor as root",
)
@pytest.mark.parametrize("left", ["index", "shared_memory"])
def test_an_index_left_read_only_is_rebuilt(history_path, tmp_path, caplog, left):
    video = _file(tmp_path / "video.mp4", b"video")
    _record({"upload_end_time": 1.0}, video)
    _open().close()
    if left == "index":
        _index_path().chmod(0o444)
    else:
        # Left by a run as another user
        for suffix in ["-wal", "-shm"]:
            leftover = Path(f"{_index_path()}{suffix}")
            leftover.write_bytes(b"")
            leftover.chmod(0o444)
    other = _file(tmp_path / "other.mp4", b"other video")
    _record({"upload_end_time": 2.0}, other)

    with caplog.at_level("WARNING"):
        uploaded = _open()

    assert isinstance(uploaded, history_index.UploadedFilesIndex)
    assert uploaded.find(video) is not None
    assert uploaded.find(other) is not None
    uploaded.close()
    assert "Rebuilding the upload history index" in caplog.text
    # Not again
    caplog.clear()
    with caplog.at_level("WARNING"):
        _open().close()
    assert caplog.text == ""


def test_reads_every_record_when_the_index_cannot_be_used(
    history_path, tmp_path, caplog
):
    video = _file(tmp_path / "video.mp4", b"video")
    _record({"upload_end_time": 1.0}, video)
    _index_path().mkdir()

    with caplog.at_level("WARNING"):
        uploaded = _open()

    assert isinstance(uploaded, history.UploadedFiles)
    assert uploaded.find(video) is not None
    assert "Not using the upload history index" in caplog.text


def test_reads_every_record_while_another_process_updates_the_index(
    history_path, tmp_path, caplog, monkeypatch
):
    video = _file(tmp_path / "video.mp4", b"video")
    _record({"upload_end_time": 1.0}, video)
    _open().close()
    monkeypatch.setattr(history_index, "LOCK_TIMEOUT_SECONDS", 0.1)

    other = sqlite3.connect(_index_path(), isolation_level=None)
    other.execute("BEGIN EXCLUSIVE")
    try:
        with caplog.at_level("WARNING"):
            uploaded = _open()
    finally:
        other.execute("ROLLBACK")
        other.close()

    # Not rebuilt: read without it
    assert isinstance(uploaded, history.UploadedFiles)
    assert uploaded.find(video) is not None
    assert "Rebuilding" not in caplog.text
    assert _count("files") == 1


def test_no_history(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", "")
    monkeypatch.chdir(tmp_path)
    assert history_index.open_uploaded_files() is None
    assert list(tmp_path.iterdir()) == []


def test_nothing_uploaded_yet(history_path, tmp_path):
    uploaded = _open()
    assert uploaded.find(_file(tmp_path / "video.mp4", b"video")) is None
    uploaded.close()
    # Nothing is created until something is uploaded
    assert not history_path.exists()


@pytest.mark.parametrize("mtime", ["changed", "restored"])
def test_a_record_rewritten_with_the_same_size_is_read_again(
    history_path, tmp_path, monkeypatch, mtime
):
    if mtime == "restored" and sys.platform == "win32":
        pytest.skip("Windows: only the size and modification time are compared")
    video = _file(tmp_path / "video.mp4", b"video")
    record_path = _record({"cluster_id": "1234", "upload_end_time": 1.0}, video)
    _open().close()
    reads = _count_record_reads(monkeypatch)

    text = record_path.read_text()
    rewritten = text.replace('"1234"', "null  ")
    assert rewritten != text and len(rewritten) == len(text)
    stat = record_path.stat()
    record_path.write_text(rewritten)
    os.utime(
        record_path,
        ns=(
            stat.st_atime_ns,
            stat.st_mtime_ns + (1_000_000 if mtime == "changed" else 0),
        ),
    )

    uploaded = _open()
    assert reads == [record_path.name]
    assert uploaded.find(video) is None
    uploaded.close()


def test_values_that_sqlite_cannot_store_make_a_record_invalid(
    history_path, tmp_path, caplog
):
    video = _file(tmp_path / "video.mp4", b"video")
    other = _file(tmp_path / "other.mp4", b"other video")
    big = _record({"upload_end_time": 1.0}, video)
    record = json.loads(big.read_text())
    record["files"][0]["filesize"] = 2**64
    big.write_text(json.dumps(record))
    late = _record({"upload_end_time": 10**400}, other)

    with caplog.at_level("WARNING"):
        uploaded = _open()
    assert isinstance(uploaded, history_index.UploadedFilesIndex)
    assert uploaded.find(video) is None
    # Uploaded at a time that is not known
    other_fingerprint = fingerprint.fingerprint_file(other)
    assert uploaded.find(other) == other_fingerprint
    assert uploaded.last_uploaded_at(other_fingerprint) is None
    uploaded.close()
    assert f"Invalid upload history record {big}" in caplog.text
    assert late.name not in caplog.text


def test_lookups_read_every_record_when_the_index_fails(history_path, tmp_path, caplog):
    video = _file(tmp_path / "video.mp4", b"video")
    _record({"upload_end_time": 3.0}, video)
    video_fingerprint = fingerprint.fingerprint_file(video)
    uploaded = _open()
    assert isinstance(uploaded, history_index.UploadedFilesIndex)

    class _FailingConnection:
        def execute(self, *args):
            raise sqlite3.OperationalError("disk I/O error")

        def close(self):
            pass

    uploaded._conn.close()
    uploaded._conn = T.cast(sqlite3.Connection, _FailingConnection())

    with caplog.at_level("WARNING"):
        assert uploaded.find(video) == video_fingerprint
        assert uploaded.last_uploaded_at(video_fingerprint) == 3.0
        assert uploaded.find(_file(tmp_path / "new.mp4", b"new")) is None
    assert caplog.text.count("Failed to look files up in the upload history") == 1
    uploaded.close()


def test_an_error_that_is_not_corruption_keeps_the_index(
    history_path, tmp_path, monkeypatch, caplog
):
    video = _file(tmp_path / "video.mp4", b"video")
    _record({"upload_end_time": 1.0}, video)
    _open().close()
    other = _file(tmp_path / "other.mp4", b"other video")
    _record({"upload_end_time": 2.0}, other)

    def _read_record(path: Path):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(history_index, "_read_record", _read_record)
    with caplog.at_level("WARNING"):
        uploaded = _open()

    # Not rebuilt, nor changed: read without it
    assert isinstance(uploaded, history.UploadedFiles)
    assert uploaded.find(other) is not None
    assert "Rebuilding" not in caplog.text
    assert (_count("records"), _count("files")) == (1, 1)


def test_indexes_like_reading_every_record(history_path, tmp_path):
    rng = random.Random(7)
    # Files of a few sizes, so that some share their size but not their content
    paths = [
        _file(
            tmp_path / f"file-{idx}.jpg",
            bytes(rng.randrange(256) for _ in range(rng.choice([10, 20, 30]))),
        )
        for idx in range(30)
    ]
    for _ in range(25):
        summary: dict = {
            "upload_end_time": rng.choice([None, float(rng.randrange(100))])
        }
        if rng.random() < 0.2:
            summary["cluster_id"] = None
        _record(summary, *rng.sample(paths[:20], rng.randrange(1, 5)))

    scanned = history.read_uploaded_files()
    assert scanned is not None
    uploaded = _open()
    assert isinstance(uploaded, history_index.UploadedFilesIndex)
    for path in paths:
        found = scanned.find(path)
        assert uploaded.find(path) == found
        if found is not None:
            assert uploaded.last_uploaded_at(found) == scanned.last_uploaded_at(found)
    uploaded.close()


@pytest.mark.parametrize("failure", ["bad_options", "upload_error"])
def test_upload_closes_the_index_when_it_fails(
    history_path, tmp_path, monkeypatch, failure
):
    from mapillary_tools import exceptions, upload

    _record({}, _file(tmp_path / "video.mp4", b"video"))
    monkeypatch.setattr(constants, "MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN", True)
    opened: list[history.UploadedFilesLookup] = []
    open_uploaded_files = history_index.open_uploaded_files

    def _open_uploaded_files():
        uploaded = open_uploaded_files()
        assert uploaded is not None
        opened.append(uploaded)
        return uploaded

    def _gen_upload_everything(*args):
        raise RuntimeError("upload failed")
        yield

    monkeypatch.setattr(history_index, "open_uploaded_files", _open_uploaded_files)
    monkeypatch.setattr(upload, "_gen_upload_everything", _gen_upload_everything)
    with pytest.raises(
        exceptions.MapillaryBadParameterError
        if failure == "bad_options"
        else RuntimeError
    ):
        upload.upload(
            tmp_path,
            {"user_upload_token": "YOUR_USER_ACCESS_TOKEN"},
            num_upload_workers=0 if failure == "bad_options" else 1,
            _metadatas_from_process=[],
            dry_run=True,
        )

    # Not opened when the options are bad, and closed otherwise
    assert len(opened) == (0 if failure == "bad_options" else 1)
    for uploaded in opened:
        assert isinstance(uploaded, history_index.UploadedFilesIndex)
        with pytest.raises(sqlite3.ProgrammingError):
            uploaded._conn.execute("SELECT 1")
