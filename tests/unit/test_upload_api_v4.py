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
