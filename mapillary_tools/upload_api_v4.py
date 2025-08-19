from __future__ import annotations

import io
import os
import random
import sys
import typing as T
import uuid
from pathlib import Path

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

import tempfile

import requests

from .api_v4 import HTTPContentError, jsonify_response, REQUESTS_TIMEOUT

MAPILLARY_UPLOAD_ENDPOINT = os.getenv(
    "MAPILLARY_UPLOAD_ENDPOINT", "https://rupload.facebook.com/mapillary_public_uploads"
)


class UploadService:
    """
    Upload byte streams to the Upload Service.
    """

    user_access_token: str
    session_key: str

    def __init__(self, user_session: requests.Session, session_key: str):
        self.user_session = user_session
        self.session_key = session_key

    def fetch_offset(self) -> int:
        url = f"{MAPILLARY_UPLOAD_ENDPOINT}/{self.session_key}"

        resp = self.user_session.get(url, timeout=REQUESTS_TIMEOUT)
        resp.raise_for_status()

        data = jsonify_response(resp)
        try:
            return data["offset"]
        except KeyError:
            raise HTTPContentError("Offset not found in the response", resp)

    @classmethod
    def chunkize_byte_stream(
        cls, stream: T.IO[bytes], chunk_size: int
    ) -> T.Generator[bytes, None, None]:
        """
        Chunkize a byte stream into chunks of the specified size.

        >>> list(UploadService.chunkize_byte_stream(io.BytesIO(b"foo"), 1))
        [b'f', b'o', b'o']

        >>> list(UploadService.chunkize_byte_stream(io.BytesIO(b"foo"), 10))
        [b'foo']
        """

        if chunk_size <= 0:
            raise ValueError("Expect positive chunk size")

        while True:
            data = stream.read(chunk_size)
            if not data:
                break
            yield data

    @classmethod
    def shift_chunks(
        cls, chunks: T.Iterable[bytes], offset: int
    ) -> T.Generator[bytes, None, None]:
        """
        Shift the chunks by the offset.

        >>> list(UploadService.shift_chunks([b"foo", b"bar"], 0))
        [b'foo', b'bar']

        >>> list(UploadService.shift_chunks([b"foo", b"bar"], 1))
        [b'oo', b'bar']

        >>> list(UploadService.shift_chunks([b"foo", b"bar"], 3))
        [b'bar']

        >>> list(UploadService.shift_chunks([b"foo", b"bar"], 6))
        []

        >>> list(UploadService.shift_chunks([b"foo", b"bar"], 7))
        []

        >>> list(UploadService.shift_chunks([], 0))
        []
        """

        if offset < 0:
            raise ValueError(f"Expect non-negative offset but got {offset}")

        for chunk in chunks:
            if offset:
                if offset < len(chunk):
                    yield chunk[offset:]
                    offset = 0
                else:
                    offset -= len(chunk)
            else:
                yield chunk

    def upload_byte_stream(
        self,
        stream: T.IO[bytes],
        offset: int | None = None,
        chunk_size: int = 2 * 1024 * 1024,  # 2MB
        read_timeout: float | None = None,
    ) -> str:
        if offset is None:
            offset = self.fetch_offset()
        return self.upload_chunks(
            self.chunkize_byte_stream(stream, chunk_size),
            offset,
            read_timeout=read_timeout,
        )

    def upload_chunks(
        self,
        chunks: T.Iterable[bytes],
        offset: int | None = None,
        read_timeout: float | None = None,
    ) -> str:
        if offset is None:
            offset = self.fetch_offset()
        shifted_chunks = self.shift_chunks(chunks, offset)
        return self.upload_shifted_chunks(
            shifted_chunks, offset, read_timeout=read_timeout
        )

    def upload_shifted_chunks(
        self,
        shifted_chunks: T.Iterable[bytes],
        offset: int,
        read_timeout: float | None = None,
    ) -> str:
        """
        Upload the chunks that must already be shifted by the offset (e.g. fp.seek(offset, io.SEEK_SET))
        """

        url = f"{MAPILLARY_UPLOAD_ENDPOINT}/{self.session_key}"
        headers = {
            "Offset": f"{offset}",
            "X-Entity-Name": self.session_key,
        }

        resp = self.user_session.post(
            url,
            headers=headers,
            data=shifted_chunks,
            timeout=(REQUESTS_TIMEOUT, read_timeout),  # type: ignore
        )
        resp.raise_for_status()

        data = jsonify_response(resp)
        try:
            return data["h"]
        except KeyError:
            raise HTTPContentError("File handle not found in the response", resp)


# A mock class for testing only
class FakeUploadService(UploadService):
    """
    A mock upload service that simulates the upload process for testing purposes.
    It writes the uploaded data to a file in a temporary directory and generates a fake file handle.
    """

    FILE_HANDLE_DIR: str = "file_handles"

    def __init__(
        self,
        *args,
        upload_path: Path | None = None,
        transient_error_ratio: float = 0.0,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if upload_path is None:
            upload_path = Path(tempfile.gettempdir()).joinpath(
                "mapillary_public_uploads"
            )
        self._upload_path = upload_path
        self._transient_error_ratio = transient_error_ratio

    @override
    def upload_shifted_chunks(
        self,
        shifted_chunks: T.Iterable[bytes],
        offset: int,
        read_timeout: float | None = None,
    ) -> str:
        expected_offset = self.fetch_offset()
        if offset != expected_offset:
            raise ValueError(
                f"Expect offset {expected_offset} but got {offset} for session {self.session_key}"
            )

        os.makedirs(self._upload_path, exist_ok=True)
        filename = self._upload_path.joinpath(self.session_key)
        with filename.open("ab") as fp:
            for chunk in shifted_chunks:
                self._randomly_raise_transient_error()
                fp.write(chunk)
                self._randomly_raise_transient_error()

        file_handle_dir = self._upload_path.joinpath(self.FILE_HANDLE_DIR)
        file_handle_path = file_handle_dir.joinpath(self.session_key)
        if not file_handle_path.exists():
            os.makedirs(file_handle_dir, exist_ok=True)
            random_file_handle = uuid.uuid4().hex
            file_handle_path.write_text(random_file_handle)

        return file_handle_path.read_text()

    @override
    def fetch_offset(self) -> int:
        self._randomly_raise_transient_error()
        filename = self._upload_path.joinpath(self.session_key)
        if not filename.exists():
            return 0
        with open(filename, "rb") as fp:
            fp.seek(0, io.SEEK_END)
            return fp.tell()

    @property
    def upload_path(self) -> Path:
        return self._upload_path

    def _randomly_raise_transient_error(self):
        """
        Randomly raise a transient error based on the configured error ratio.
        This is for testing purposes only.
        """
        if random.random() <= self._transient_error_ratio:
            raise requests.ConnectionError(
                f"[TEST ONLY]: Transient error with ratio {self._transient_error_ratio}"
            )
