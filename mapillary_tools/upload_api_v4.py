import enum
import io
import json
import logging
import os
import random
import typing as T

import requests

LOG = logging.getLogger(__name__)
MAPILLARY_UPLOAD_ENDPOINT = os.getenv(
    "MAPILLARY_UPLOAD_ENDPOINT", "https://rupload.facebook.com/mapillary_public_uploads"
)
MAPILLARY_GRAPH_API_ENDPOINT = os.getenv(
    "MAPILLARY_GRAPH_API_ENDPOINT", "https://graph.mapillary.com"
)
DEFAULT_CHUNK_SIZE = 1024 * 1024 * 16  # 16MB
# According to the docs, UPLOAD_REQUESTS_TIMEOUT can be a tuple of
# (connection_timeout, read_timeout): https://requests.readthedocs.io/en/latest/user/advanced/#timeouts
# In my test, however, the connection_timeout rules both connection timeout and read timeout.
# i.e. if your the server does not respond within this timeout, it will throw:
# ConnectionError: ('Connection aborted.', timeout('The write operation timed out'))
# So let us make sure the largest possible chunks can be uploaded before this timeout for now,
REQUESTS_TIMEOUT = (20, 20)  # 20 seconds
UPLOAD_REQUESTS_TIMEOUT = (30 * 60, 30 * 60)  # 30 minutes


class ClusterFileType(enum.Enum):
    ZIP = "zip"
    BLACKVUE = "mly_blackvue_video"
    CAMM = "mly_camm_video"


def _sanitize_headers(headers: T.Dict):
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in ["authorization", "cookie", "x-fb-access-token"]
    }


_S = T.TypeVar("_S", str, bytes)


def _truncate_end(s: _S) -> _S:
    MAX_LENGTH = 512
    if MAX_LENGTH < len(s):
        if isinstance(s, bytes):
            return s[:MAX_LENGTH] + b"..."
        else:
            return str(s[:MAX_LENGTH]) + "..."
    else:
        return s


class UploadService:
    user_access_token: str
    entity_size: int
    session_key: str
    callbacks: T.List[T.Callable[[bytes, T.Optional[requests.Response]], None]]
    cluster_filetype: ClusterFileType
    organization_id: T.Optional[T.Union[str, int]]
    chunk_size: int

    def __init__(
        self,
        user_access_token: str,
        session_key: str,
        entity_size: int,
        organization_id: T.Optional[T.Union[str, int]] = None,
        cluster_filetype: ClusterFileType = ClusterFileType.ZIP,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        if entity_size <= 0:
            raise ValueError(f"Expect positive entity size but got {entity_size}")

        if chunk_size <= 0:
            raise ValueError("Expect positive chunk size")

        self.user_access_token = user_access_token
        self.session_key = session_key
        self.entity_size = entity_size
        self.organization_id = organization_id
        #  validate the input
        self.cluster_filetype = ClusterFileType(cluster_filetype)
        self.callbacks = []
        self.chunk_size = chunk_size

    def fetch_offset(self) -> int:
        headers = {
            "Authorization": f"OAuth {self.user_access_token}",
        }
        url = f"{MAPILLARY_UPLOAD_ENDPOINT}/{self.session_key}"
        LOG.debug("GET %s", url)
        resp = requests.get(
            url,
            headers=headers,
            timeout=REQUESTS_TIMEOUT,
        )
        LOG.debug("HTTP response %s: %s", resp.status_code, resp.content)
        resp.raise_for_status()
        data = resp.json()
        return data["offset"]

    def upload(
        self,
        data: T.IO[bytes],
        offset: T.Optional[int] = None,
    ) -> str:
        if offset is None:
            offset = self.fetch_offset()

        entity_type_map: T.Dict[ClusterFileType, str] = {
            ClusterFileType.ZIP: "application/zip",
            ClusterFileType.BLACKVUE: "video/mp4",
            ClusterFileType.CAMM: "video/mp4",
        }

        entity_type = entity_type_map[self.cluster_filetype]

        data.seek(offset, io.SEEK_CUR)

        while True:
            chunk = data.read(self.chunk_size)
            # it is possible to upload an empty chunk here
            # in order to return the handle
            headers = {
                "Authorization": f"OAuth {self.user_access_token}",
                "Offset": f"{offset}",
                "X-Entity-Length": str(self.entity_size),
                "X-Entity-Name": self.session_key,
                "X-Entity-Type": entity_type,
            }
            url = f"{MAPILLARY_UPLOAD_ENDPOINT}/{self.session_key}"
            LOG.debug("POST %s HEADERS %s", url, json.dumps(_sanitize_headers(headers)))
            resp = requests.post(
                url,
                headers=headers,
                data=chunk,
                timeout=UPLOAD_REQUESTS_TIMEOUT,
            )
            LOG.debug(
                "HTTP response %s: %s", resp.status_code, _truncate_end(resp.content)
            )
            resp.raise_for_status()
            offset += len(chunk)
            LOG.debug("The next offset will be: %s", offset)
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

    def finish(self, file_handle: str) -> str:
        headers = {
            "Authorization": f"OAuth {self.user_access_token}",
        }
        data: T.Dict[str, T.Union[str, int]] = {
            "file_handle": file_handle,
            "file_type": self.cluster_filetype.value,
        }
        if self.organization_id is not None:
            data["organization_id"] = self.organization_id

        url = f"{MAPILLARY_GRAPH_API_ENDPOINT}/finish_upload"

        LOG.debug("POST %s HEADERS %s", url, json.dumps(_sanitize_headers(headers)))
        resp = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=REQUESTS_TIMEOUT,
        )
        LOG.debug("HTTP response %s: %s", resp.status_code, _truncate_end(resp.content))

        resp.raise_for_status()

        data = resp.json()

        cluster_id = data.get("cluster_id")
        if cluster_id is None:
            raise RuntimeError(
                f"Upload server error: failed to create the cluster {resp.text}"
            )

        return T.cast(str, cluster_id)


# A mock class for testing only
class FakeUploadService(UploadService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._upload_path = os.getenv(
            "MAPILLARY_UPLOAD_PATH", "mapillary_public_uploads"
        )
        self._error_ratio = 0.1

    def upload(
        self,
        data: T.IO[bytes],
        offset: T.Optional[int] = None,
    ) -> str:
        if offset is None:
            offset = self.fetch_offset()
        os.makedirs(self._upload_path, exist_ok=True)
        filename = os.path.join(self._upload_path, self.session_key)
        with open(filename, "ab") as fp:
            data.seek(offset, io.SEEK_CUR)
            while True:
                chunk = data.read(self.chunk_size)
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

    def finish(self, _: str) -> str:
        return "0"

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
