# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import io
from pathlib import Path

import py
from mapillary_tools import upload_api_v4


def test_upload(tmpdir: py.path.local):
    upload_service = upload_api_v4.FakeUploadService(
        user_session=None,
        session_key="FOOBAR.txt",
        upload_path=Path(tmpdir),
        transient_error_ratio=0.02,
    )
    upload_service._transient_error_ratio = 0
    content = b"double_foobar"
    cluster_id = upload_service.upload_byte_stream(io.BytesIO(content), chunk_size=1)
    assert isinstance(cluster_id, str), cluster_id
    assert (tmpdir.join("FOOBAR.txt").read_binary()) == content

    # reupload should not affect the file
    upload_service.upload_byte_stream(io.BytesIO(content), chunk_size=1)
    assert (tmpdir.join("FOOBAR.txt").read_binary()) == content


def test_upload_big_chunksize(tmpdir: py.path.local):
    upload_service = upload_api_v4.FakeUploadService(
        user_session=None,
        session_key="FOOBAR.txt",
        upload_path=Path(tmpdir),
        transient_error_ratio=0.02,
    )
    upload_service._transient_error_ratio = 0
    content = b"double_foobar"
    cluster_id = upload_service.upload_byte_stream(io.BytesIO(content), chunk_size=1000)
    assert isinstance(cluster_id, str), cluster_id
    assert (tmpdir.join("FOOBAR.txt").read_binary()) == content

    # reupload should not affect the file
    upload_service.upload_byte_stream(io.BytesIO(content), chunk_size=1000)
    assert (tmpdir.join("FOOBAR.txt").read_binary()) == content


def test_upload_chunks(tmpdir: py.path.local):
    upload_service = upload_api_v4.FakeUploadService(
        user_session=None,
        session_key="FOOBAR2.txt",
        upload_path=Path(tmpdir),
        transient_error_ratio=0.02,
    )
    upload_service._transient_error_ratio = 0

    def _gen_chunks():
        yield b"foo"
        yield b""
        yield b"bar"
        yield b""

    cluster_id = upload_service.upload_chunks(_gen_chunks())

    assert isinstance(cluster_id, str), cluster_id
    assert (tmpdir.join("FOOBAR2.txt").read_binary()) == b"foobar"

    # reupload should not affect the file
    upload_service.upload_chunks(_gen_chunks())
    assert (tmpdir.join("FOOBAR2.txt").read_binary()) == b"foobar"


class _ReadSpy(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.read_sizes: list[int] = []

    def read(self, size: int | None = -1) -> bytes:  # type: ignore[override]
        if size is None:
            size = -1
        self.read_sizes.append(size)
        return super().read(size)


def test_chunkize_caps_read_to_remaining_bytes():
    spy = _ReadSpy(b"hello world")
    chunks = list(
        upload_api_v4.UploadService.chunkize_byte_stream(spy, 1024 * 1024 * 1000)
    )
    assert b"".join(chunks) == b"hello world"
    assert spy.read_sizes == [len(b"hello world")]


class _SeekSpy(_ReadSpy):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.seek_count = 0

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self.seek_count += 1
        return super().seek(offset, whence)


def test_chunkize_measures_remaining_bytes_once():
    # Seeking a video stream rebuilt from many samples walks all of them,
    # so seeking for every chunk made large video uploads quadratic
    spy = _SeekSpy(b"hello world")
    spy.seek(6)
    spy.seek_count = 0
    chunks = list(upload_api_v4.UploadService.chunkize_byte_stream(spy, 2))
    assert chunks == [b"wo", b"rl", b"d"]
    assert spy.read_sizes == [2, 2, 1]
    assert spy.seek_count == 2


class _UnseekableStream:
    def __init__(self, data: bytes):
        self._stream = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_chunkize_unseekable_stream():
    stream = _UnseekableStream(b"hello world")
    chunks = list(
        upload_api_v4.UploadService.chunkize_byte_stream(stream, 4)  # type: ignore[arg-type]
    )
    assert chunks == [b"hell", b"o wo", b"rld"]
