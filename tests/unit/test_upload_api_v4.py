import io

import py

from mapillary_tools import upload_api_v4

from ..integration.fixtures import setup_upload


def test_upload(setup_upload: py.path.local):
    upload_service = upload_api_v4.FakeUploadService(
        user_access_token="TEST",
        session_key="FOOBAR.txt",
        chunk_size=1,
    )
    upload_service._error_ratio = 0
    content = b"double_foobar"
    cluster_id = upload_service.upload(io.BytesIO(content))
    assert isinstance(cluster_id, str), cluster_id
    assert (setup_upload.join("FOOBAR.txt").read_binary()) == content

    # reupload should not affect the file
    upload_service.upload(io.BytesIO(content))
    assert (setup_upload.join("FOOBAR.txt").read_binary()) == content


def test_upload_chunks(setup_upload: py.path.local):
    upload_service = upload_api_v4.FakeUploadService(
        user_access_token="TEST",
        session_key="FOOBAR2.txt",
        chunk_size=1,
    )
    upload_service._error_ratio = 0

    def _gen_chunks():
        yield b"foo"
        yield b""
        yield b"bar"
        yield b""

    cluster_id = upload_service.upload_chunks(_gen_chunks())

    assert isinstance(cluster_id, str), cluster_id
    assert (setup_upload.join("FOOBAR2.txt").read_binary()) == b"foobar"

    # reupload should not affect the file
    upload_service.upload_chunks(_gen_chunks())
    assert (setup_upload.join("FOOBAR2.txt").read_binary()) == b"foobar"
