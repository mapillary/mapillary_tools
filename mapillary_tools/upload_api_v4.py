from __future__ import annotations

import io
import os
import random
import sys
import typing as T
import uuid

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

import requests

from .api_v4 import ClusterFileType, request_get, request_post, REQUESTS_TIMEOUT

MAPILLARY_UPLOAD_ENDPOINT = os.getenv(
    "MAPILLARY_UPLOAD_ENDPOINT", "https://rupload.facebook.com/mapillary_public_uploads"
)
# According to the docs, UPLOAD_REQUESTS_TIMEOUT can be a tuple of
# (connection_timeout, read_timeout): https://requests.readthedocs.io/en/latest/user/advanced/#timeouts
# In my test, however, the connection_timeout rules both connection timeout and read timeout.
# i.e. if your the server does not respond within this timeout, it will throw:
# ConnectionError: ('Connection aborted.', timeout('The write operation timed out'))
# So let us make sure the largest possible chunks can be uploaded before this timeout for now,
UPLOAD_REQUESTS_TIMEOUT = (30 * 60, 30 * 60)  # 30 minutes


class UploadService:
    user_access_token: str
    session_key: str
    cluster_filetype: ClusterFileType

    MIME_BY_CLUSTER_TYPE: dict[ClusterFileType, str] = {
        ClusterFileType.ZIP: "application/zip",
        ClusterFileType.BLACKVUE: "video/mp4",
        ClusterFileType.CAMM: "video/mp4",
    }

    def __init__(
        self,
        user_access_token: str,
        session_key: str,
        cluster_filetype: ClusterFileType,
    ):
        self.user_access_token = user_access_token
        self.session_key = session_key
        # Validate the input
        self.cluster_filetype = cluster_filetype

    def fetch_offset(self) -> int:
        headers = {
            "Authorization": f"OAuth {self.user_access_token}",
        }
        url = f"{MAPILLARY_UPLOAD_ENDPOINT}/{self.session_key}"
        resp = request_get(
            url,
            headers=headers,
            timeout=REQUESTS_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["offset"]

    @classmethod
    def chunkize_byte_stream(
        cls, stream: T.IO[bytes], chunk_size: int
    ) -> T.Generator[bytes, None, None]:
        if chunk_size <= 0:
            raise ValueError("Expect positive chunk size")
        while True:
            data = stream.read(chunk_size)
            if not data:
                break
            yield data

    def shift_chunks(
        self, chunks: T.Iterable[bytes], offset: int
    ) -> T.Generator[bytes, None, None]:
        assert offset >= 0, f"Expect non-negative offset but got {offset}"

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
    ) -> str:
        if offset is None:
            offset = self.fetch_offset()
        return self.upload_chunks(self.chunkize_byte_stream(stream, chunk_size), offset)

    def upload_chunks(
        self,
        chunks: T.Iterable[bytes],
        offset: int | None = None,
    ) -> str:
        if offset is None:
            offset = self.fetch_offset()
        shifted_chunks = self.shift_chunks(chunks, offset)
        return self.upload_shifted_chunks(shifted_chunks, offset)

    def upload_shifted_chunks(
        self,
        shifted_chunks: T.Iterable[bytes],
        offset: int,
    ) -> str:
        """
        Upload the chunks that must already be shifted by the offset (e.g. fp.seek(begin_offset, io.SEEK_SET))
        """

        headers = {
            "Authorization": f"OAuth {self.user_access_token}",
            "Offset": f"{offset}",
            "X-Entity-Name": self.session_key,
            "X-Entity-Type": self.MIME_BY_CLUSTER_TYPE[self.cluster_filetype],
        }
        url = f"{MAPILLARY_UPLOAD_ENDPOINT}/{self.session_key}"
        resp = request_post(
            url,
            headers=headers,
            data=shifted_chunks,
            timeout=UPLOAD_REQUESTS_TIMEOUT,
        )

        resp.raise_for_status()

        payload = resp.json()
        try:
            return payload["h"]
        except KeyError:
            raise RuntimeError(
                f"Upload server error: File handle not found in the upload response {resp.text}"
            )


# A mock class for testing only
class FakeUploadService(UploadService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._upload_path = os.getenv(
            "MAPILLARY_UPLOAD_PATH", "mapillary_public_uploads"
        )
        self._error_ratio = 0.02

    @override
    def upload_shifted_chunks(
        self,
        shifted_chunks: T.Iterable[bytes],
        offset: int,
    ) -> str:
        expected_offset = self.fetch_offset()
        if offset != expected_offset:
            raise ValueError(
                f"Expect offset {expected_offset} but got {offset} for session {self.session_key}"
            )

        os.makedirs(self._upload_path, exist_ok=True)
        filename = os.path.join(self._upload_path, self.session_key)
        with open(filename, "ab") as fp:
            for chunk in shifted_chunks:
                if random.random() <= self._error_ratio:
                    raise requests.ConnectionError(
                        f"TEST ONLY: Failed to upload with error ratio {self._error_ratio}"
                    )
                fp.write(chunk)
                if random.random() <= self._error_ratio:
                    raise requests.ConnectionError(
                        f"TEST ONLY: Partially uploaded with error ratio {self._error_ratio}"
                    )
        return uuid.uuid4().hex

    @override
    def fetch_offset(self) -> int:
        if random.random() <= self._error_ratio:
            raise requests.ConnectionError(
                f"TEST ONLY: Partially uploaded with error ratio {self._error_ratio}"
            )
        filename = os.path.join(self._upload_path, self.session_key)
        if not os.path.exists(filename):
            return 0
        with open(filename, "rb") as fp:
            fp.seek(0, io.SEEK_END)
            return fp.tell()
