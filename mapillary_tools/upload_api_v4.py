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
    entity_size: int
    session_key: str
    callbacks: T.List[T.Callable]

    def __init__(self, user_access_token: str, session_key: str, entity_size: int):
        if entity_size <= 0:
            raise ValueError(f"Expect positive entity size but got {entity_size}")
        self.user_access_token = user_access_token
        self.session_key = session_key
        self.entity_size = entity_size
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
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> requests.Response:
        if chunk_size <= 0:
            raise ValueError("Expect positive chunk size")

        offset = self.fetch_offset()
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
                "X-Entity-Type": "application/zip",
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
        ), f"offset ends at {offset} but the entity size is {self.entity_size}"

        return resp

    def finish(
        self, file_handle: str, organization_id: T.Optional[T.Union[str, int]] = None
    ) -> requests.Response:
        headers = {
            "Authorization": f"OAuth {self.user_access_token}",
        }
        data: T.Dict[str, T.Union[str, int]] = {
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
    service = UploadService(user_access_token, session_key, entity_size)

    print(f"session key: {session_key}")
    print(f"entity size: {entity_size}")
    print(f"initial offset: {service.fetch_offset()}")

    with open(path, "rb") as fp:
        with tqdm.tqdm(total=entity_size, initial=service.fetch_offset()) as pbar:
            service.callbacks.append(lambda chunk, _: pbar.update(len(chunk)))
            try:
                resp = service.upload(fp)
            except requests.HTTPError as ex:
                raise wrap_http_exception(ex)
    print(resp.json())
