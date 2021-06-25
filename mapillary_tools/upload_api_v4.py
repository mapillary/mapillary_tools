import requests
import os
import io
import typing as T

from .api_v4 import MAPILLARY_GRAPH_API_ENDPOINT

MAPILLARY_UPLOAD_ENDPOINT = os.getenv(
    "MAPILLARY_UPLOAD_ENDPOINT", "https://rupload.facebook.com/mapillary_public_uploads"
)
DEFAULT_CHUNK_SIZE = 1024 * 1024 * 64


class UploadService:
    user_access_token: str
    # This amount of data that will be loaded to memory
    chunk_size: int

    def __init__(self, user_access_token: str, chunk_size: int = DEFAULT_CHUNK_SIZE):
        if chunk_size <= 0:
            raise ValueError("Expect positive chunk size")
        self.user_access_token = user_access_token
        self.chunk_size = chunk_size

    def fetch_offset(self, session_key: str) -> int:
        headers = {
            "Authorization": f"OAuth {self.user_access_token}",
        }
        resp = requests.get(
            f"{MAPILLARY_UPLOAD_ENDPOINT}/{session_key}", headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        return data["offset"]

    def upload(
        self,
        session_key: str,
        data: T.IO[bytes],
        entity_size: int,
        callback: T.Optional[T.Callable] = None,
    ) -> requests.Response:
        if entity_size <= 0:
            raise ValueError(f"Expect positive entity size but got {entity_size}")

        offset = self.fetch_offset(session_key)
        data.seek(offset, io.SEEK_CUR)

        while True:
            chunk = data.read(self.chunk_size)
            # it is possible to upload an empty chunk here
            # in order to return the handle
            headers = {
                "Authorization": f"OAuth {self.user_access_token}",
                "Offset": f"{offset}",
                "X-Entity-Length": str(entity_size),
                "X-Entity-Name": session_key,
                "X-Entity-Type": "application/zip",
            }
            resp = requests.post(
                f"{MAPILLARY_UPLOAD_ENDPOINT}/{session_key}",
                headers=headers,
                data=chunk,
            )
            resp.raise_for_status()
            offset += len(chunk)
            if callback:
                callback(chunk, resp)
            # we can assert that offset == self.fetch_offset(session_key)
            # otherwise, server will throw

            if not chunk:
                break

        assert (
            offset == entity_size
        ), f"offset ends at {offset} but the entity size is {entity_size}"

        return resp

    def finish(
        self, file_handle: str, organization_id: T.Optional[int] = None
    ) -> requests.Response:
        headers = {
            "Authorization": f"OAuth {self.user_access_token}",
        }
        data = {
            "file_handle": file_handle,
        }
        if organization_id is not None:
            data["organization_id"] = organization_id

        return requests.post(
            f"{MAPILLARY_GRAPH_API_ENDPOINT}/finish_upload", headers=headers, json=data
        )


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
    from .login import wrap_http_exception

    user_access_token = os.getenv("MAPILLARY_TOOLS_USER_ACCESS_TOKEN")
    if not user_access_token:
        raise RuntimeError("MAPILLARY_TOOLS_USER_ACCESS_TOKEN is required")

    path = sys.argv[1]
    with open(path, "rb") as fp:
        md5sum, entity_size = _file_stats(fp)
    session_key = sys.argv[2] if sys.argv[2:] else f"mly_tools_test_{md5sum}"
    service = UploadService(user_access_token)

    print(f"session key: {session_key}")
    print(f"entity size: {entity_size}")
    print(f"initial offset: {service.fetch_offset(session_key)}")

    with open(path, "rb") as fp:
        with tqdm.tqdm(
            total=entity_size, initial=service.fetch_offset(session_key)
        ) as pbar:
            try:
                resp = service.upload(
                    session_key,
                    fp,
                    entity_size,
                    callback=lambda chunk, _: pbar.update(len(chunk)),
                )
            except requests.HTTPError as ex:
                raise wrap_http_exception(ex)
    print(resp.json())
