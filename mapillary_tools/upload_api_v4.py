import requests
import os
import io
import sys
import typing as T

if sys.version_info >= (3, 8):
    from typing import Literal  # pylint: disable=no-name-in-module
else:
    from typing_extensions import Literal

from .api_v4 import MAPILLARY_GRAPH_API_ENDPOINT

MAPILLARY_UPLOAD_ENDPOINT = os.getenv(
    "MAPILLARY_UPLOAD_ENDPOINT", "https://rupload.facebook.com/mapillary_public_uploads"
)
DEFAULT_CHUNK_SIZE = 1024 * 1024 * 64


FileType = Literal["zip", "mly_blackvue_video"]


class UploadHTTPError(Exception):
    pass


def wrap_http_exception(ex: requests.HTTPError):
    resp = ex.response
    lines = [
        f"{ex.request.method} {resp.url}",
        f"> HTTP Status: {ex.response.status_code}",
        f"{ex.response.text}",
    ]
    return UploadHTTPError("\n".join(lines))


class UploadService:
    user_access_token: str
    entity_size: int
    session_key: str
    callbacks: T.List[T.Callable[[bytes, T.Optional[requests.Response]], None]]
    file_type: FileType
    organization_id: T.Optional[T.Union[str, int]]

    def __init__(
        self,
        user_access_token: str,
        session_key: str,
        entity_size: int,
        organization_id: T.Optional[T.Union[str, int]] = None,
        file_type: FileType = "zip",
    ):
        if entity_size <= 0:
            raise ValueError(f"Expect positive entity size but got {entity_size}")

        if file_type.lower() not in ["zip", "mly_blackvue_video"]:
            raise ValueError(f"Invalid file type {file_type}")

        self.user_access_token = user_access_token
        self.session_key = session_key
        self.entity_size = entity_size
        self.organization_id = organization_id
        self.file_type = T.cast(FileType, file_type.lower())
        self.callbacks = []

    def fetch_offset(self) -> int:
        headers = {
            "Authorization": f"OAuth {self.user_access_token}",
        }
        resp = requests.get(
            f"{MAPILLARY_UPLOAD_ENDPOINT}/{self.session_key}", headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        return data["offset"]

    def upload(
        self,
        data: T.IO[bytes],
        offset: T.Optional[int] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> str:
        if chunk_size <= 0:
            raise ValueError("Expect positive chunk size")

        if offset is None:
            offset = self.fetch_offset()

        entity_type_map: T.Dict[FileType, str] = {
            "zip": "application/zip",
            "mly_blackvue_video": "video/mp4",
        }

        entity_type = entity_type_map[self.file_type]

        data.seek(offset, io.SEEK_CUR)

        while True:
            chunk = data.read(chunk_size)
            # it is possible to upload an empty chunk here
            # in order to return the handle
            headers = {
                "Authorization": f"OAuth {self.user_access_token}",
                "Offset": f"{offset}",
                "X-Entity-Length": str(self.entity_size),
                "X-Entity-Name": self.session_key,
                "X-Entity-Type": entity_type,
            }
            resp = requests.post(
                f"{MAPILLARY_UPLOAD_ENDPOINT}/{self.session_key}",
                headers=headers,
                data=chunk,
            )
            resp.raise_for_status()
            offset += len(chunk)
            for callback in self.callbacks:
                callback(chunk, resp)
            # we can assert that offset == self.fetch_offset(session_key)
            # otherwise, server will throw

            if not chunk:
                break

        assert (
            offset == self.entity_size
        ), f"Offset ends at {offset} but the entity size is {self.entity_size}"

        payload = resp.json()
        try:
            return payload["h"]
        except KeyError:
            raise RuntimeError(
                f"Upload server error: File handle not found in the upload response {resp.text}"
            )

    def finish(self, file_handle: str) -> int:
        headers = {
            "Authorization": f"OAuth {self.user_access_token}",
        }
        data: T.Dict[str, T.Union[str, int]] = {
            "file_handle": file_handle,
            "file_type": self.file_type,
        }
        if self.organization_id is not None:
            data["organization_id"] = self.organization_id

        resp = requests.post(
            f"{MAPILLARY_GRAPH_API_ENDPOINT}/finish_upload",
            headers=headers,
            json=data,
        )

        resp.raise_for_status()

        data = resp.json()

        cluster_id = data.get("cluster_id")
        if cluster_id is None:
            raise RuntimeError(
                f"Upload server error: failed to create the cluster {resp.text}"
            )

        return T.cast(int, cluster_id)


import random


# A mock class for testing only
class FakeUploadService(UploadService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._upload_path = os.getenv(
            "MAPILLARY_UPLOAD_PATH", "mapillary_public_uploads"
        )
        self._error_ratio = 0.2

    def upload(
        self,
        data: T.IO[bytes],
        offset: T.Optional[int] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> str:
        if offset is None:
            offset = self.fetch_offset()
        os.makedirs(self._upload_path, exist_ok=True)
        filename = os.path.join(self._upload_path, self.session_key)
        with open(filename, "ab") as fp:
            data.seek(offset, io.SEEK_CUR)
            while True:
                chunk = data.read(chunk_size)
                if not chunk:
                    break
                # fail here means nothing uploaded
                if random.random() <= self._error_ratio:
                    raise requests.ConnectionError(
                        f"TEST ONLY: Failed to upload with error ratio {self._error_ratio}"
                    )
                fp.write(chunk)
                # fail here means patially uploaded
                if random.random() <= self._error_ratio:
                    raise requests.ConnectionError(
                        f"TEST ONLY: Partially uploaded with error ratio {self._error_ratio}"
                    )
                for callback in self.callbacks:
                    callback(chunk, None)
        return self.session_key

    def finish(self, _: str) -> int:
        return 0

    def fetch_offset(self) -> int:
        filename = os.path.join(self._upload_path, self.session_key)
        if not os.path.exists(filename):
            return 0
        with open(filename, "rb") as fp:
            fp.seek(0, io.SEEK_END)
            return fp.tell()


def _file_stats(fp: T.IO[bytes]):
    md5 = hashlib.md5()
    while True:
        buf = fp.read(DEFAULT_CHUNK_SIZE)
        if not buf:
            break
        md5.update(buf)
    fp.seek(0, os.SEEK_END)
    return md5.hexdigest(), fp.tell()


if __name__ == "__main__":
    import sys, hashlib, os
    import tqdm

    user_access_token = os.getenv("MAPILLARY_TOOLS_USER_ACCESS_TOKEN")
    if not user_access_token:
        raise RuntimeError("MAPILLARY_TOOLS_USER_ACCESS_TOKEN is required")

    path = sys.argv[1]
    with open(path, "rb") as fp:
        md5sum, entity_size = _file_stats(fp)
    session_key = sys.argv[2] if sys.argv[2:] else f"mly_tools_test_{md5sum}"
    service = UploadService(user_access_token, session_key, entity_size)

    print(f"session key: {session_key}")
    print(f"entity size: {entity_size}")
    print(f"initial offset: {service.fetch_offset()}")

    with open(path, "rb") as fp:
        with tqdm.tqdm(
            total=entity_size,
            initial=service.fetch_offset(),
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
        ) as pbar:
            service.callbacks.append(lambda chunk, resp: pbar.update(len(chunk)))
            try:
                file_handle = service.upload(fp)
            except requests.HTTPError as ex:
                raise wrap_http_exception(ex)
    print(file_handle)
